"""
DDC/CI Controller - Interface to ddcutil for monitor communication
==================================================================
"""

import subprocess
import re
import logging
import threading
import time
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass
class MonitorGeometry:
    """Monitor screen geometry from xrandr."""
    name: str          # xrandr output name (e.g., "DisplayPort-0")
    x: int             # X offset (in framebuffer pixels)
    y: int             # Y offset (in framebuffer pixels)
    width: int         # Framebuffer width in pixels (scaled)
    height: int        # Framebuffer height in pixels (scaled)
    is_primary: bool   # Is primary monitor
    native_width: int = 0   # Native panel resolution width
    native_height: int = 0  # Native panel resolution height
    scale_x: float = 1.0    # Horizontal scale factor
    scale_y: float = 1.0    # Vertical scale factor
    
    def contains_point(self, px: int, py: int) -> bool:
        """Check if a point is within this monitor."""
        return (self.x <= px < self.x + self.width and 
                self.y <= py < self.y + self.height)
    
    def contains_window(self, wx: int, wy: int, ww: int, wh: int) -> bool:
        """Check if a window overlaps with this monitor (by center point)."""
        # Use window center point
        cx = wx + ww // 2
        cy = wy + wh // 2
        return self.contains_point(cx, cy)
    
    @property
    def scale_percent(self) -> int:
        """Return scaling percentage (e.g., 150 for 150%)."""
        if self.native_width > 0:
            return int(round(self.scale_x * 100))
        return 100


@dataclass
class MonitorInfo:
    """Information about a detected monitor."""
    display_number: int
    model: str
    serial: str
    manufacturer: str
    bus: str
    i2c_bus: str
    drm_connector: str = ""  # DRM connector name (e.g., "card1-DP-1")
    geometry: Optional[MonitorGeometry] = None  # Screen geometry if matched
    
    def __str__(self):
        return f"{self.manufacturer} {self.model} (Display {self.display_number})"
    
    def get_config_id(self) -> str:
        """Get a unique ID for this monitor's config file."""
        # Use serial if available, otherwise use model + bus
        if self.serial:
            # Clean serial for filesystem
            safe_serial = "".join(c if c.isalnum() else "_" for c in self.serial)
            return f"{self.model}_{safe_serial}".replace(" ", "_")
        else:
            safe_model = "".join(c if c.isalnum() or c == " " else "_" for c in self.model)
            return f"{safe_model}_display{self.display_number}".replace(" ", "_")


@dataclass  
class VCPFeature:
    """VCP feature information."""
    code: int
    name: str
    current_value: int
    max_value: int
    feature_type: str  # "C" (continuous), "NC" (non-continuous), "T" (table)


class DDCError(Exception):
    """Exception raised for DDC communication errors."""
    pass


class DDCController:
    """
    Controller for DDC/CI communication with monitors via ddcutil.
    
    This class provides a high-level interface to control monitor settings
    using the DDC/CI protocol through the ddcutil command-line tool.
    """
    
    # Common VCP feature codes
    VCP_BRIGHTNESS = 0x10
    VCP_CONTRAST = 0x12
    VCP_COLOR_PRESET = 0xDC
    VCP_COLOR_TEMP = 0x14
    VCP_INPUT_SOURCE = 0x60
    VCP_RED_GAIN = 0x16
    VCP_GREEN_GAIN = 0x18
    VCP_BLUE_GAIN = 0x1A
    VCP_SHARPNESS = 0x87
    VCP_AUDIO_VOLUME = 0x62
    VCP_POWER_MODE = 0xD6
    
    # Human-readable names for VCP codes
    VCP_NAMES = {
        0x10: "Brightness",
        0x12: "Contrast",
        0xDC: "Color Mode",
        0x14: "Color Temperature",
        0x60: "Input Source",
        0x16: "Red Gain",
        0x18: "Green Gain",
        0x1A: "Blue Gain",
        0x87: "Sharpness",
        0x8A: "Color Saturation",
        0x62: "Audio Volume",
        0xD6: "Power Mode",
    }
    
    def __init__(
        self,
        display: Optional[int] = None,
        model: Optional[str] = None,
        serial: Optional[str] = None,
        retry_count: int = 1,
        sleep_multiplier: float = 0.5,
    ):
        """
        Initialize DDC controller.
        
        Args:
            display: Display number (1-based) to control
            model: Model name to match
            serial: Serial number to match
            retry_count: Number of retries for failed commands
            sleep_multiplier: Multiplier for inter-command delays
        """
        self.display = display
        self.model = model
        self.serial = serial
        self.retry_count = retry_count
        self.sleep_multiplier = sleep_multiplier
        self._lock = threading.Lock()
        self._capabilities_cache: Optional[Dict] = None
        self._last_command_time = 0
        self._min_command_interval = 0.1 * sleep_multiplier
        self._geometry: Optional[MonitorGeometry] = None
        self._monitor_info: Optional[MonitorInfo] = None
        # Cache of last-set VCP values to avoid redundant DDC writes
        self._vcp_cache: Dict[int, int] = {}
        # Set of VCP features that are known to be unsupported (failed reads)
        self._unsupported_features: set = set()
        # Callback for busy status updates (busy: bool, command: str)
        self._busy_callback: Optional[Callable[[bool, str], None]] = None
    
    def set_busy_callback(self, callback: Callable[[bool, str], None]):
        """Set callback for DDC busy status updates.
        
        Args:
            callback: Function(busy: bool, command: str) called when DDC starts/finishes commands
        """
        self._busy_callback = callback
    
    def _notify_busy(self, busy: bool, command: str = None):
        """Notify busy callback if set."""
        if self._busy_callback:
            try:
                self._busy_callback(busy, command)
            except Exception:
                pass  # Don't let callback errors affect DDC operations
    
    def _get_command_description(self, command: List[str]) -> str:
        """Generate a human-readable description of a DDC command."""
        if not command:
            return "DDC command..."
        
        cmd = command[0] if command else ""
        
        if cmd == "getvcp":
            vcp = command[1] if len(command) > 1 else ""
            vcp_num = int(vcp, 16) if vcp.startswith("0x") else 0
            name = self.VCP_NAMES.get(vcp_num, vcp)
            return f"Reading {name}..."
        elif cmd == "setvcp":
            vcp = command[1] if len(command) > 1 else ""
            vcp_num = int(vcp, 16) if vcp.startswith("0x") else 0
            name = self.VCP_NAMES.get(vcp_num, vcp)
            return f"Setting {name}..."
        elif cmd == "capabilities":
            return "Reading capabilities..."
        elif cmd == "detect":
            return "Detecting monitors..."
        else:
            return f"{cmd}..."
    
    def clear_vcp_cache(self, feature_code: int = None):
        """
        Clear cached VCP values.
        
        Args:
            feature_code: Specific VCP code to clear, or None to clear all
        """
        if feature_code is not None:
            self._vcp_cache.pop(feature_code, None)
        else:
            self._vcp_cache.clear()
        
    def get_geometry(self, refresh: bool = False) -> Optional[MonitorGeometry]:
        """
        Get the screen geometry for this monitor.
        
        Uses cached value, or detects monitors to find geometry.
        
        Args:
            refresh: If True, re-detect from xrandr (ignores cache)
        
        Returns:
            MonitorGeometry or None if not found
        """
        if self._geometry is not None and not refresh:
            return self._geometry
            
        # Detect monitors and find ours
        monitors = self.detect_monitors()
        for m in monitors:
            if m.display_number == self.display:
                self._geometry = m.geometry
                self._monitor_info = m
                if self._geometry:
                    logger.info(f"Monitor {self.display} geometry: {self._geometry.width}x{self._geometry.height}+{self._geometry.x}+{self._geometry.y}")
                return self._geometry
        
        return None
    
    def refresh_geometry(self) -> Optional[MonitorGeometry]:
        """
        Force refresh of monitor geometry from xrandr.
        
        Use this after display configuration changes (resolution, scaling, arrangement).
        
        Returns:
            Updated MonitorGeometry or None if not found
        """
        self._geometry = None
        self._monitor_info = None
        return self.get_geometry(refresh=True)
    
    def get_monitor_info(self) -> Optional[MonitorInfo]:
        """Get MonitorInfo for this DDC controller's monitor."""
        if self._monitor_info is not None:
            return self._monitor_info
        
        # Trigger geometry detection which also populates monitor_info
        self.get_geometry()
        return self._monitor_info
        
    def _build_display_args(self) -> List[str]:
        """Build ddcutil arguments for display selection and speed optimization."""
        args = []
        # Speed up I2C communication with faster sleep multiplier
        args.extend(["--sleep-multiplier", f"{self.sleep_multiplier:.1f}"])
        
        if self.display is not None:
            args.extend(["--display", str(self.display)])
        elif self.model:
            args.extend(["--model", self.model])
        elif self.serial:
            args.extend(["--sn", self.serial])
        return args
    
    def _run_ddcutil(
        self,
        command: List[str],
        timeout: float = 5.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """
        Run a ddcutil command with retry logic.
        
        Args:
            command: Command arguments to pass to ddcutil
            timeout: Command timeout in seconds
            check: Whether to raise on non-zero exit code
            
        Returns:
            CompletedProcess result
            
        Raises:
            DDCError: If command fails after retries
        """
        # Generate a friendly command description for the busy indicator
        cmd_desc = self._get_command_description(command)
        
        with self._lock:
            # Rate limiting
            elapsed = time.time() - self._last_command_time
            if elapsed < self._min_command_interval:
                time.sleep(self._min_command_interval - elapsed)
            
            full_command = ["ddcutil"] + self._build_display_args() + command
            start_time = time.time()
            logger.debug(f"DDC[{self.display}] Running: {' '.join(full_command)}")
            
            # Notify busy start
            self._notify_busy(True, cmd_desc)
            
            last_error = None
            try:
                for attempt in range(self.retry_count):
                    try:
                        attempt_start = time.time()
                        logger.debug(f"DDC[{self.display}] Starting command (attempt {attempt + 1}): {' '.join(full_command)}")
                        result = subprocess.run(
                            full_command,
                            capture_output=True,
                            text=True,
                            timeout=timeout,
                            check=check,
                        )
                        self._last_command_time = time.time()
                        exec_time = time.time() - attempt_start
                        logger.debug(f"DDC[{self.display}] Command completed in {exec_time:.2f}s")
                        return result
                    except subprocess.CalledProcessError as e:
                        last_error = e
                        exec_time = time.time() - attempt_start
                        stderr_msg = e.stderr.strip() if e.stderr else "(no stderr)"
                        logger.warning(
                            f"DDC[{self.display}] Command failed (attempt {attempt + 1}/{self.retry_count}, {exec_time:.1f}s): "
                            f"{' '.join(command)} → {stderr_msg}"
                        )
                        if attempt < self.retry_count - 1:
                            time.sleep(0.3 * (attempt + 1))  # Faster retry
                    except subprocess.TimeoutExpired as e:
                        last_error = e
                        exec_time = time.time() - attempt_start
                        logger.warning(
                            f"DDC[{self.display}] Command timed out after {exec_time:.1f}s (attempt {attempt + 1}/{self.retry_count}): "
                            f"{' '.join(command)}"
                        )
                
                total_time = time.time() - start_time
                logger.error(f"DDC[{self.display}] All retries failed for '{' '.join(command)}', total time: {total_time:.1f}s")
            finally:
                # Always notify busy end
                self._notify_busy(False)
            raise DDCError(f"DDC command '{' '.join(command)}' failed after {self.retry_count} attempts: {last_error}")
    
    @staticmethod
    def get_xrandr_monitors() -> List[MonitorGeometry]:
        """
        Get all monitor geometries from xrandr including native resolution.
        
        Returns:
            List of MonitorGeometry objects with native resolution and scale factor
        """
        try:
            result = subprocess.run(
                ["xrandr", "--query"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            monitors = []
            lines = result.stdout.split('\n')
            current_monitor = None
            
            for i, line in enumerate(lines):
                # Match lines like: "DisplayPort-0 connected primary 5118x3412+0+0"
                match = re.match(
                    r'^(\S+)\s+connected\s+(primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)',
                    line
                )
                if match:
                    # Save previous monitor if exists
                    if current_monitor:
                        monitors.append(current_monitor)
                    
                    # Create new monitor with framebuffer dimensions
                    fb_width = int(match.group(3))
                    fb_height = int(match.group(4))
                    current_monitor = MonitorGeometry(
                        name=match.group(1),
                        width=fb_width,
                        height=fb_height,
                        x=int(match.group(5)),
                        y=int(match.group(6)),
                        is_primary=bool(match.group(2)),
                        native_width=fb_width,  # Default to framebuffer, will update if mode found
                        native_height=fb_height,
                        scale_x=1.0,
                        scale_y=1.0,
                    )
                    continue
                
                # Match mode lines like: "   3840x2560     59.98*+  49.98"
                # The * indicates the active mode (native resolution)
                if current_monitor and line.startswith('   '):
                    mode_match = re.match(r'^\s+(\d+)x(\d+)\s+.*\*', line)
                    if mode_match:
                        native_w = int(mode_match.group(1))
                        native_h = int(mode_match.group(2))
                        current_monitor.native_width = native_w
                        current_monitor.native_height = native_h
                        # Calculate scale factor
                        if native_w > 0 and native_h > 0:
                            current_monitor.scale_x = current_monitor.width / native_w
                            current_monitor.scale_y = current_monitor.height / native_h
                
                # If we hit a line that's not indented and not a connected line, we've moved past modes
                elif current_monitor and not line.startswith(' ') and line.strip():
                    # Check for disconnected or another output
                    if 'connected' in line or 'disconnected' in line:
                        monitors.append(current_monitor)
                        current_monitor = None
            
            # Don't forget last monitor
            if current_monitor:
                monitors.append(current_monitor)
            
            for m in monitors:
                logger.debug(f"Monitor {m.name}: fb={m.width}x{m.height}, native={m.native_width}x{m.native_height}, scale={m.scale_percent}%")
            
            return monitors
            
        except subprocess.SubprocessError as e:
            logger.error(f"Failed to get xrandr monitors: {e}")
            return []
    
    @staticmethod
    def _match_drm_to_xrandr(drm_connector: str, xrandr_monitors: List[MonitorGeometry]) -> Optional[MonitorGeometry]:
        """
        Try to match DDC DRM connector name to xrandr output.
        
        DRM connectors are like "card1-DP-1", xrandr outputs like "DisplayPort-0".
        We try various matching strategies.
        """
        if not drm_connector or not xrandr_monitors:
            return None
            
        # Extract connector type and number from DRM name (e.g., "card1-DP-1" -> "DP", "1")
        drm_match = re.match(r'card\d+-(\w+)-(\d+)', drm_connector)
        if not drm_match:
            return None
            
        drm_type = drm_match.group(1)  # e.g., "DP", "HDMI"
        drm_num = int(drm_match.group(2))
        
        # Build xrandr pattern based on connector type
        patterns = []
        if drm_type == "DP":
            # Try "DisplayPort-N" where N might differ from DRM number
            patterns.append(f"DisplayPort-{drm_num - 1}")  # Often 0-indexed
            patterns.append(f"DisplayPort-{drm_num}")
            patterns.append(f"DP-{drm_num - 1}")
            patterns.append(f"DP-{drm_num}")
        elif drm_type == "HDMI":
            patterns.append(f"HDMI-{drm_num - 1}")
            patterns.append(f"HDMI-{drm_num}")
            patterns.append(f"HDMI-A-{drm_num}")
        elif drm_type == "eDP":
            patterns.append("eDP")
            patterns.append("eDP-1")
        
        # Try exact matches first
        for pattern in patterns:
            for monitor in xrandr_monitors:
                if monitor.name == pattern:
                    logger.debug(f"Matched DRM '{drm_connector}' to xrandr '{monitor.name}'")
                    return monitor
        
        # Fall back to partial matching
        for monitor in xrandr_monitors:
            monitor_type = monitor.name.split('-')[0].upper() if '-' in monitor.name else monitor.name.upper()
            if drm_type.upper() in monitor_type or monitor_type in drm_type.upper():
                logger.debug(f"Partial match: DRM '{drm_connector}' to xrandr '{monitor.name}'")
                return monitor
        
        return None

    @staticmethod
    def detect_monitors() -> List[MonitorInfo]:
        """
        Detect all DDC/CI capable monitors with geometry info.
        
        Returns:
            List of MonitorInfo objects for each detected monitor
        """
        # Get xrandr geometries first
        xrandr_monitors = DDCController.get_xrandr_monitors()
        
        try:
            result = subprocess.run(
                ["ddcutil", "detect", "--terse"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            monitors = []
            current_monitor: Dict[str, Any] = {}
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line:
                    if current_monitor.get('display_number'):
                        drm_connector = current_monitor.get('drm_connector', '')
                        geometry = DDCController._match_drm_to_xrandr(drm_connector, xrandr_monitors)
                        
                        monitors.append(MonitorInfo(
                            display_number=current_monitor.get('display_number', 0),
                            model=current_monitor.get('model', 'Unknown'),
                            serial=current_monitor.get('serial', ''),
                            manufacturer=current_monitor.get('manufacturer', 'Unknown'),
                            bus=current_monitor.get('bus', ''),
                            i2c_bus=current_monitor.get('i2c_bus', ''),
                            drm_connector=drm_connector,
                            geometry=geometry,
                        ))
                    current_monitor = {}
                    continue
                    
                if line.startswith('Display'):
                    match = re.match(r'Display (\d+)', line)
                    if match:
                        current_monitor['display_number'] = int(match.group(1))
                elif ':' in line:
                    key, _, value = line.partition(':')
                    key = key.strip().lower().replace(' ', '_')
                    value = value.strip()
                    
                    # Terse format has "Monitor: MFG:Model:Serial"
                    if key == 'monitor' and ':' in value:
                        parts = value.split(':')
                        if len(parts) >= 1:
                            current_monitor['manufacturer'] = parts[0] if parts[0] else 'Unknown'
                        if len(parts) >= 2:
                            current_monitor['model'] = parts[1] if parts[1] else 'Unknown'
                        if len(parts) >= 3:
                            current_monitor['serial'] = parts[2] if parts[2] else ''
                    elif key == 'model':
                        current_monitor['model'] = value
                    elif key == 'serial_number':
                        current_monitor['serial'] = value
                    elif key == 'manufacturer':
                        current_monitor['manufacturer'] = value
                    elif key == 'i2c_bus':
                        current_monitor['i2c_bus'] = value
                    elif key == 'drm_connector':
                        current_monitor['drm_connector'] = value
                        current_monitor['bus'] = value  # Keep bus for compatibility
                        
            # Don't forget the last monitor
            if current_monitor.get('display_number'):
                drm_connector = current_monitor.get('drm_connector', '')
                geometry = DDCController._match_drm_to_xrandr(drm_connector, xrandr_monitors)
                
                monitors.append(MonitorInfo(
                    display_number=current_monitor.get('display_number', 0),
                    model=current_monitor.get('model', 'Unknown'),
                    serial=current_monitor.get('serial', ''),
                    manufacturer=current_monitor.get('manufacturer', 'Unknown'),
                    bus=current_monitor.get('bus', ''),
                    i2c_bus=current_monitor.get('i2c_bus', ''),
                    drm_connector=drm_connector,
                    geometry=geometry,
                ))
            
            # Log geometry info
            for m in monitors:
                if m.geometry:
                    logger.info(f"Display {m.display_number} ({m.model}): {m.geometry.width}x{m.geometry.height}+{m.geometry.x}+{m.geometry.y}")
                else:
                    logger.warning(f"Display {m.display_number} ({m.model}): Could not match xrandr geometry")
                
            return monitors
            
        except subprocess.SubprocessError as e:
            logger.error(f"Failed to detect monitors: {e}")
            return []
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get monitor capabilities (cached).
        
        Returns:
            Dictionary with monitor capabilities
        """
        if self._capabilities_cache is not None:
            return self._capabilities_cache
            
        result = self._run_ddcutil(["capabilities"], timeout=30)
        
        capabilities = {
            'model': '',
            'mccs_version': '',
            'features': {},
        }
        
        current_feature = None
        for line in result.stdout.split('\n'):
            if line.startswith('   Model:'):
                capabilities['model'] = line.split(':', 1)[1].strip()
            elif line.startswith('   MCCS version:'):
                capabilities['mccs_version'] = line.split(':', 1)[1].strip()
            elif re.match(r'^\s+Feature: [0-9A-Fa-f]{2}', line):
                match = re.search(r'Feature: ([0-9A-Fa-f]{2})\s*\((.*?)\)', line)
                if match:
                    code = int(match.group(1), 16)
                    name = match.group(2)
                    current_feature = {'name': name, 'values': {}}
                    capabilities['features'][code] = current_feature
            elif current_feature and 'Values:' in line:
                # Parse allowed values for non-continuous features
                pass
            elif current_feature and re.match(r'^\s+([0-9A-Fa-f]{2}):', line):
                match = re.match(r'^\s+([0-9A-Fa-f]{2}):\s*(.*)', line)
                if match:
                    value = int(match.group(1), 16)
                    desc = match.group(2).strip()
                    current_feature['values'][value] = desc
                    
        self._capabilities_cache = capabilities
        return capabilities
    
    def get_vcp(self, feature_code: int) -> VCPFeature:
        """
        Get current value of a VCP feature.
        
        Args:
            feature_code: VCP feature code (e.g., 0x10 for brightness)
            
        Returns:
            VCPFeature with current and max values
            
        Raises:
            DDCError: If feature is unsupported or read fails
        """
        # Skip if this feature was previously found to be unsupported
        if feature_code in self._unsupported_features:
            feature_name = self.VCP_NAMES.get(feature_code, f"VCP 0x{feature_code:02x}")
            raise DDCError(f"Feature {feature_name} (0x{feature_code:02x}) is not supported by this monitor")
        
        feature_name = self.VCP_NAMES.get(feature_code, f"VCP 0x{feature_code:02x}")
        logger.debug(f"Reading {feature_name}...")
        
        try:
            result = self._run_ddcutil(["getvcp", f"0x{feature_code:02x}"])
        except DDCError as e:
            # Mark feature as unsupported so we don't try again
            self._unsupported_features.add(feature_code)
            logger.info(f"DDC[{self.display}] Marking {feature_name} (0x{feature_code:02x}) as unsupported")
            raise
        
        # Parse output like: "VCP code 0x10 (Brightness): current value = 50, max value = 100"
        match = re.search(
            r'VCP code 0x([0-9A-Fa-f]+)\s+\(([^)]+)\).*?'
            r'current value\s*=\s*(\d+).*?max value\s*=\s*(\d+)',
            result.stdout,
            re.IGNORECASE
        )
        
        if match:
            current_value = int(match.group(3))
            # Update cache with read value
            self._vcp_cache[feature_code] = current_value
            return VCPFeature(
                code=int(match.group(1), 16),
                name=match.group(2),
                current_value=current_value,
                max_value=int(match.group(4)),
                feature_type="C",
            )
        
        # Try non-continuous format: "current value = 0x01, max value = 0x0b"
        match = re.search(
            r'VCP code 0x([0-9A-Fa-f]+)\s+\(([^)]+)\).*?'
            r'current value\s*=\s*0x([0-9A-Fa-f]+)',
            result.stdout,
            re.IGNORECASE
        )
        
        if match:
            current_value = int(match.group(3), 16)
            # Update cache with read value
            self._vcp_cache[feature_code] = current_value
            return VCPFeature(
                code=int(match.group(1), 16),
                name=match.group(2),
                current_value=current_value,
                max_value=255,
                feature_type="NC",
            )
        
        # Try "Invalid value" format from some monitors: "Invalid value (sl=0x12)"
        # This happens when the value is outside the monitor's declared range but still valid
        match = re.search(
            r'VCP code 0x([0-9A-Fa-f]+)\s+\(([^)]+)\).*?'
            r'Invalid value\s+\(sl=0x([0-9A-Fa-f]+)\)',
            result.stdout,
            re.IGNORECASE
        )
        
        if match:
            current_value = int(match.group(3), 16)
            logger.debug(f"Parsed 'Invalid value' format: VCP 0x{feature_code:02x} = {current_value}")
            # Update cache with read value
            self._vcp_cache[feature_code] = current_value
            return VCPFeature(
                code=int(match.group(1), 16),
                name=match.group(2),
                current_value=current_value,
                max_value=255,
                feature_type="NC",
            )
        
        # Try named value format: "Standard/Default mode (sl=0x00)" or "User 1 (sl=0x0b)"
        # This format is used by some monitors for color modes/presets
        match = re.search(
            r'VCP code 0x([0-9A-Fa-f]+)\s+\(([^)]+)\):\s*'
            r'([^(]+?)\s*\(sl=0x([0-9A-Fa-f]+)\)',
            result.stdout,
            re.IGNORECASE
        )
        
        if match:
            current_value = int(match.group(4), 16)
            mode_name = match.group(3).strip()
            logger.debug(f"Parsed named value format: VCP 0x{feature_code:02x} = {current_value} ({mode_name})")
            # Update cache with read value
            self._vcp_cache[feature_code] = current_value
            return VCPFeature(
                code=int(match.group(1), 16),
                name=match.group(2),
                current_value=current_value,
                max_value=255,
                feature_type="NC",
            )
            
        raise DDCError(f"Failed to parse VCP response: {result.stdout}")
    
    # VCP codes that require --noverify (verification often fails even when successful)
    # VCP codes that should skip verification reads (speeds up commands)
    # Verification reads are slow and these codes work reliably without them
    VCP_NOVERIFY = {
        0x10,  # Brightness
        0x12,  # Contrast
        0x14,  # Color temperature
        0x16,  # Red gain
        0x18,  # Green gain
        0x1a,  # Blue gain
        0xdc,  # Color preset/display mode
    }
    
    def set_vcp(self, feature_code: int, value: int, noverify: bool = None, force: bool = False) -> bool:
        """
        Set a VCP feature value.
        
        Args:
            feature_code: VCP feature code
            value: Value to set
            noverify: Skip verification (auto-detected for known problematic codes)
            force: Force send even if cached value matches
            
        Returns:
            True if successful (or skipped because value unchanged)
        """
        feature_name = self.VCP_NAMES.get(feature_code, f"VCP 0x{feature_code:02x}")
        
        # Skip if value hasn't changed (unless forced)
        if not force and feature_code in self._vcp_cache and self._vcp_cache[feature_code] == value:
            logger.info(f"Skipping {feature_name} - already set to {value}")
            return True
        
        # Auto-detect noverify for known problematic VCP codes
        if noverify is None:
            noverify = feature_code in self.VCP_NOVERIFY
        
        try:
            cmd = ["setvcp", f"0x{feature_code:02x}", str(value)]
            if noverify:
                cmd.append("--noverify")
            self._run_ddcutil(cmd)
            # Update cache on success
            self._vcp_cache[feature_code] = value
            logger.info(f"Set {feature_name} to {value}")
            return True
        except DDCError as e:
            # Clear cache on failure so next attempt will actually try to send
            if feature_code in self._vcp_cache:
                del self._vcp_cache[feature_code]
                logger.debug(f"Cleared cache for {feature_name} due to failure")
            logger.error(f"Failed to set {feature_name}: {e}")
            return False
    
    # Convenience methods for common operations
    
    def get_brightness(self) -> int:
        """Get current brightness (0-100)."""
        return self.get_vcp(self.VCP_BRIGHTNESS).current_value
    
    def set_brightness(self, value: int) -> bool:
        """Set brightness (0-100)."""
        return self.set_vcp(self.VCP_BRIGHTNESS, max(0, min(100, value)))
    
    def get_contrast(self) -> int:
        """Get current contrast (0-100)."""
        return self.get_vcp(self.VCP_CONTRAST).current_value
    
    def set_contrast(self, value: int) -> bool:
        """Set contrast (0-100)."""
        return self.set_vcp(self.VCP_CONTRAST, max(0, min(100, value)))
    
    def get_color_preset(self) -> int:
        """Get current color preset/mode."""
        return self.get_vcp(self.VCP_COLOR_PRESET).current_value
    
    def get_sharpness(self) -> int:
        """Get current sharpness."""
        result = self.get_vcp(self.VCP_SHARPNESS)
        return result.current_value if result else None
    
    def get_sharpness_info(self) -> tuple:
        """Get sharpness info including min/max values.
        
        Returns:
            Tuple of (current_value, max_value) or (None, None) on error.
        """
        result = self.get_vcp(self.VCP_SHARPNESS)
        if result:
            return (result.current_value, result.max_value)
        return (None, None)
    
    def set_sharpness(self, value: int, max_value: int = 100) -> bool:
        """Set sharpness (0 to max_value)."""
        return self.set_vcp(self.VCP_SHARPNESS, max(0, min(max_value, value)))
    
    def get_available_color_modes(self) -> Dict[int, str]:
        """
        Get available color modes from monitor capabilities.
        
        Returns:
            Dictionary mapping VCP value to mode name.
            For monitors with both 0xDC and 0x14, values are combined.
            0x14 values are offset by 0x1000 to distinguish them.
        """
        try:
            capabilities = self.get_capabilities()
            features = capabilities.get('features', {})
            
            color_modes = {}
            
            # Get Display Mode (0xDC) if available
            if 0xDC in features:
                dc_modes = features[0xDC].get('values', {})
                for value, name in dc_modes.items():
                    color_modes[value] = name
                logger.info(f"Found {len(dc_modes)} display modes (0xDC)")
            
            # Get Color Preset (0x14) if available
            # Offset by 0x1000 to distinguish from 0xDC values
            if 0x14 in features:
                cp_modes = features[0x14].get('values', {})
                for value, name in cp_modes.items():
                    # Use offset to indicate this is a 0x14 value
                    color_modes[value + 0x1000] = name
                logger.info(f"Found {len(cp_modes)} color presets (0x14)")
            
            if color_modes:
                logger.info(f"Detected {len(color_modes)} total color modes from monitor")
                return color_modes
            else:
                logger.warning("No color modes found in monitor capabilities")
                return {}
                
        except Exception as e:
            logger.warning(f"Could not get color modes from capabilities: {e}")
            return {}
    
    def set_color_mode(self, value: int, mode_name: str = None) -> bool:
        """
        Set color mode, automatically detecting whether to use 0xDC or 0x14.
        
        Args:
            value: VCP value (if >= 0x1000, it's a 0x14 color preset)
            mode_name: Optional name for logging
        """
        # Check if this is a 0x14 color preset (offset by 0x1000)
        if value >= 0x1000:
            actual_value = value - 0x1000
            vcp_code = 0x14
            vcp_name = "Color Preset"
        else:
            actual_value = value
            vcp_code = self.VCP_COLOR_PRESET  # 0xDC
            vcp_name = "Display Mode"
        
        # Use set_vcp with noverify=True and force=True for color modes
        # force=True ensures the command is always sent (user-initiated action)
        # This is important with --skip-ddc where cache might not reflect actual monitor state
        result = self.set_vcp(vcp_code, actual_value, noverify=True, force=True)
        
        # Log only if command was actually sent (set_vcp logs internally)
        # If mode_name was provided, add it to a follow-up log
        if mode_name and result:
            logger.debug(f"Color mode set to: {mode_name}")
        
        return result
    
    def set_color_preset(self, value: int, mode_name: str = None) -> bool:
        """Set color preset/mode. Delegates to set_color_mode for proper VCP handling."""
        return self.set_color_mode(value, mode_name)
    
    def get_red_gain(self) -> int:
        """Get current red gain (0-100)."""
        return self.get_vcp(self.VCP_RED_GAIN).current_value
    
    def get_green_gain(self) -> int:
        """Get current green gain (0-100)."""
        return self.get_vcp(self.VCP_GREEN_GAIN).current_value
    
    def get_blue_gain(self) -> int:
        """Get current blue gain (0-100)."""
        return self.get_vcp(self.VCP_BLUE_GAIN).current_value
    
    def get_all_settings(self, quick: bool = False) -> Dict[str, int]:
        """
        Get all common monitor settings.
        
        Args:
            quick: If True, only read brightness and contrast (faster)
        
        Returns:
            Dictionary with setting names and current values
        """
        settings = {}
        logger.debug(f"DDC[{self.display}] get_all_settings(quick={quick}) starting...")
        
        try:
            logger.debug(f"DDC[{self.display}] Reading brightness (0x10)...")
            settings['brightness'] = self.get_brightness()
        except DDCError as e:
            logger.debug(f"DDC[{self.display}] Brightness read failed: {e}")
        
        try:
            logger.debug(f"DDC[{self.display}] Reading contrast (0x12)...")
            settings['contrast'] = self.get_contrast()
        except DDCError as e:
            logger.debug(f"DDC[{self.display}] Contrast read failed: {e}")
        
        # Get sharpness with min/max info
        try:
            logger.debug(f"DDC[{self.display}] Reading sharpness (0x87)...")
            sharpness_val, sharpness_max = self.get_sharpness_info()
            if sharpness_val is not None:
                settings['sharpness'] = sharpness_val
                settings['sharpness_max'] = sharpness_max if sharpness_max else 100
        except DDCError as e:
            logger.debug(f"DDC[{self.display}] Sharpness read failed: {e}")
        
        # Skip extended settings in quick mode
        if quick:
            logger.debug(f"DDC[{self.display}] Quick mode - skipping extended settings")
            return settings
            
        try:
            logger.debug(f"DDC[{self.display}] Reading color_preset (0xDC)...")
            settings['color_preset'] = self.get_color_preset()
        except DDCError as e:
            logger.debug(f"DDC[{self.display}] Color preset read failed: {e}")
        
        try:
            logger.debug(f"DDC[{self.display}] Reading red_gain (0x16)...")
            settings['red_gain'] = self.get_red_gain()
        except DDCError as e:
            logger.debug(f"DDC[{self.display}] Red gain read failed: {e}")
        
        try:
            logger.debug(f"DDC[{self.display}] Reading green_gain (0x18)...")
            settings['green_gain'] = self.get_green_gain()
        except DDCError as e:
            logger.debug(f"DDC[{self.display}] Green gain read failed: {e}")
        
        try:
            logger.debug(f"DDC[{self.display}] Reading blue_gain (0x1A)...")
            settings['blue_gain'] = self.get_blue_gain()
        except DDCError as e:
            logger.debug(f"DDC[{self.display}] Blue gain read failed: {e}")
        
        logger.debug(f"DDC[{self.display}] get_all_settings completed: {list(settings.keys())}")
        return settings
    
    def apply_settings(self, settings: Dict[str, int], color_mode_name: str = None) -> bool:
        """
        Apply multiple settings at once.
        
        Args:
            settings: Dictionary mapping setting names to values
            color_mode_name: Optional name for the color mode (for logging)
            
        Returns:
            True if all settings were applied successfully
        """
        success = True
        
        if 'brightness' in settings and settings['brightness'] is not None:
            success &= self.set_brightness(settings['brightness'])
        if 'contrast' in settings and settings['contrast'] is not None:
            success &= self.set_contrast(settings['contrast'])
        if 'color_preset' in settings and settings['color_preset'] is not None:
            success &= self.set_color_preset(settings['color_preset'], color_mode_name)
            
        return success


def check_ddcutil_available() -> Tuple[bool, str]:
    """
    Check if ddcutil is installed and working.
    
    Returns:
        Tuple of (is_available, message)
    """
    try:
        result = subprocess.run(
            ["ddcutil", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.split('\n')[0] if result.stdout else "unknown"
            return True, f"ddcutil found: {version}"
        else:
            return False, f"ddcutil error: {result.stderr}"
    except FileNotFoundError:
        return False, "ddcutil not found. Install with: sudo apt install ddcutil"
    except subprocess.TimeoutExpired:
        return False, "ddcutil timed out"
    except Exception as e:
        return False, f"Error checking ddcutil: {e}"


def check_i2c_permissions() -> Tuple[bool, str]:
    """
    Check if user has permissions to access I2C devices.
    
    Returns:
        Tuple of (has_permission, message)
    """
    import os
    import grp
    
    # Check if user is in i2c group
    try:
        i2c_group = grp.getgrnam('i2c')
        if os.getlogin() in i2c_group.gr_mem or os.getuid() == 0:
            return True, "User has i2c group access"
    except KeyError:
        pass
    except OSError:
        pass
    
    # Check if /dev/i2c-* devices are accessible
    import glob
    i2c_devices = glob.glob('/dev/i2c-*')
    if not i2c_devices:
        return False, "No I2C devices found. Load i2c-dev module: sudo modprobe i2c-dev"
    
    for device in i2c_devices:
        if os.access(device, os.R_OK | os.W_OK):
            return True, f"I2C device {device} is accessible"
            
    return False, (
        "Cannot access I2C devices. Add user to i2c group:\n"
        "  sudo usermod -aG i2c $USER\n"
        "Then log out and back in."
    )

