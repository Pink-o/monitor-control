#!/usr/bin/env python3
"""
Monitor Control - DDC/CI Monitor Management for Linux
=====================================================

Control your monitor settings (brightness, contrast, color modes) via DDC/CI.
Designed for BenQ RD280UA but works with any DDC/CI compatible monitor.

Features:
- Automatic profile switching based on active applications
- Adaptive brightness/contrast based on screen content
- Modern GUI overlay with CustomTkinter
- Per-profile auto brightness/contrast settings

Usage:
    python main.py [--config PATH] [--no-gui] [--debug] [--skip-ddc]
    
    Options:
        --config PATH   Path to configuration file
        --no-gui        Run without GUI (daemon mode)
        --debug         Enable debug logging
        --skip-ddc      Skip DDC readings at startup (for faster debugging)
        --detect        Detect monitors and exit
        --capabilities  Show monitor capabilities and exit
"""

# Disable IBus integration to prevent high CPU usage
# Must be set before any tkinter imports
import os
os.environ['GTK_IM_MODULE'] = ''
os.environ['QT_IM_MODULE'] = ''
os.environ['XMODIFIERS'] = ''

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path
from typing import Optional, List

# Set up logging first
def setup_logging(debug: bool = False, log_file: Optional[Path] = None):
    """Configure logging."""
    level = logging.DEBUG if debug else logging.INFO
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers,
    )

logger = logging.getLogger(__name__)


def detect_monitors():
    """Detect and display connected monitors."""
    from monitor_control.ddc import DDCController, check_ddcutil_available, check_i2c_permissions
    
    # Check prerequisites
    available, msg = check_ddcutil_available()
    if not available:
        print(f"Error: {msg}")
        return 1
    print(f"✓ {msg}")
    
    has_perms, msg = check_i2c_permissions()
    if not has_perms:
        print(f"Warning: {msg}")
    else:
        print(f"✓ {msg}")
    
    print("\nDetecting monitors...")
    monitors = DDCController.detect_monitors()
    
    if not monitors:
        print("No DDC/CI capable monitors found.")
        print("\nTroubleshooting:")
        print("  1. Ensure DDC/CI is enabled in monitor OSD settings")
        print("  2. Try: sudo modprobe i2c-dev")
        print("  3. Check: ls /dev/i2c-*")
        return 1
    
    print(f"\nFound {len(monitors)} monitor(s):\n")
    for m in monitors:
        print(f"  Display {m.display_number}:")
        print(f"    Model:        {m.model}")
        print(f"    Manufacturer: {m.manufacturer}")
        print(f"    Serial:       {m.serial or 'N/A'}")
        print(f"    I2C Bus:      {m.i2c_bus}")
        print()
    
    return 0


def show_capabilities(display: Optional[int] = None):
    """Show capabilities of a monitor."""
    from monitor_control.ddc import DDCController, check_ddcutil_available
    
    available, msg = check_ddcutil_available()
    if not available:
        print(f"Error: {msg}")
        return 1
    
    ddc = DDCController(display=display)
    
    print("Querying monitor capabilities...")
    try:
        caps = ddc.get_capabilities()
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    print(f"\nModel: {caps.get('model', 'Unknown')}")
    print(f"MCCS Version: {caps.get('mccs_version', 'Unknown')}")
    print(f"\nSupported Features:\n")
    
    for code, feature in sorted(caps.get('features', {}).items()):
        print(f"  0x{code:02X} - {feature['name']}")
        if feature.get('values'):
            for val, desc in sorted(feature['values'].items()):
                print(f"         {val}: {desc}")
    
    # Also try to read current values for key features
    print("\nCurrent Values:")
    for name, code in [('Brightness', 0x10), ('Contrast', 0x12), ('Color Preset', 0xDC)]:
        try:
            vcp = ddc.get_vcp(code)
            print(f"  {name}: {vcp.current_value} (max: {vcp.max_value})")
        except Exception as e:
            print(f"  {name}: Unable to read (0x{code:02X})")
    
    return 0


class MonitorControlApp:
    """
    Main application controller.
    
    Coordinates all components: DDC control, profile management,
    window monitoring, screen analysis, and GUI.
    """
    
    def __init__(self, config_path: Optional[Path] = None, gui_enabled: bool = True, skip_ddc: bool = False):
        """
        Initialize the application.
        
        Args:
            config_path: Path to configuration file
            gui_enabled: Whether to enable GUI components
            skip_ddc: Skip DDC readings at startup (for faster debugging)
        """
        self.config_path = config_path
        self.gui_enabled = gui_enabled
        self.skip_ddc = skip_ddc
        self._running = False
        self._gtk_thread: Optional[threading.Thread] = None
        
        # Components (initialized in start())
        self.config = None
        self.ddc = None
        self.profile_manager = None  # Current monitor's profile manager
        self.profile_managers = {}  # Dict[display_number, ProfileManager] - for multi-monitor auto
        self.ddc_controllers = {}   # Dict[display_number, DDCController] - cached controllers
        self.monitor_configs = {}   # Dict[display_number, MonitorConfig] - cached per-monitor configs
        self.overlay = None
        self.monitor_config = None  # Per-monitor config (current monitor)
        self.current_monitor: Optional['MonitorInfo'] = None
        self.monitors: List['MonitorInfo'] = []
        
        # Latest value tracking for slider commands (to skip queued outdated values)
        self._latest_brightness = {}  # Dict[display_num, value]
        self._latest_contrast = {}
        self._latest_mode = {}
        self._latest_red_gain = {}
        self._latest_green_gain = {}
        self._latest_blue_gain = {}
        self._pending_commands = {}  # Dict[(display_num, vcp_code), bool] - track if command is pending
        
    def start(self):
        """Start the application."""
        from monitor_control.config import Config
        from monitor_control.ddc import DDCController, check_ddcutil_available, check_i2c_permissions
        from monitor_control.profile_manager import ProfileManager
        from monitor_control.window_monitor import check_window_tools
        from monitor_control.screen_analyzer import check_imaging_available
        
        logger.info("Starting Monitor Control...")
        
        # Check prerequisites
        available, msg = check_ddcutil_available()
        if not available:
            logger.error(msg)
            return False
        logger.info(msg)
        
        has_perms, msg = check_i2c_permissions()
        if not has_perms:
            logger.warning(msg)
        
        available, msg = check_window_tools()
        if not available:
            logger.warning(msg)
        else:
            logger.info(msg)
        
        available, msg = check_imaging_available()
        if not available:
            logger.warning(msg)
        
        # Load configuration
        self.config = Config(self.config_path)
        if self.config_path and self.config_path.exists():
            self.config.load()
        else:
            # Try default path or create default
            if Config.DEFAULT_CONFIG_PATH.exists():
                self.config.config_path = Config.DEFAULT_CONFIG_PATH
                self.config.load()
            else:
                logger.warning("No configuration file found, using defaults")
                # Try to copy default config
                Config.create_default_config()
                if Config.DEFAULT_CONFIG_PATH.exists():
                    self.config.config_path = Config.DEFAULT_CONFIG_PATH
                    self.config.load()
        
        # Initialize DDC controller
        self.monitors = DDCController.detect_monitors()
        if not self.monitors:
            logger.error("No monitors detected")
            return False
        
        # Find matching monitor or use first one
        display = 1
        self.current_monitor = self.monitors[0]
        if self.config.monitor_identifier:
            for m in self.monitors:
                if (self.config.monitor_identifier.lower() in m.model.lower() or
                    self.config.monitor_identifier == m.serial):
                    display = m.display_number
                    self.current_monitor = m
                    break
        
        self.ddc = DDCController(
            display=display,
            retry_count=self.config.ddc_retry_count,
            sleep_multiplier=self.config.ddc_sleep_multiplier,
        )
        self.ddc_controllers[display] = self.ddc  # Cache DDC controller
        # Set up busy callback for overview indicator (will work once overlay is created)
        self._setup_ddc_busy_callback(self.ddc, display)
        logger.info(f"Using display {display}")
        
        # Load per-monitor configuration
        self._load_monitor_config()
        
        # Initialize GUI if enabled - this will trigger _populate_monitors which
        # creates and starts ALL ProfileManagers uniformly
        if self.gui_enabled:
            self._init_gui()
        else:
            # No GUI mode: create and start ProfileManager for initial display
            display = self.ddc.display if hasattr(self.ddc, 'display') else 1
            self.profile_manager = self._get_or_create_profile_manager(display)
            if self.monitor_config:
                # During startup, don't save to profile and defer screen analysis until monitors are loaded
                self.profile_manager.set_auto_brightness_enabled(self.monitor_config.auto_brightness, save_to_profile=False, start_monitoring=False)
                self.profile_manager.set_auto_contrast_enabled(self.monitor_config.auto_contrast, save_to_profile=False, start_monitoring=False)
                self.profile_manager.set_auto_profile_enabled(self.monitor_config.auto_profile)
        
        self._running = True
        logger.info("Monitor Control started successfully")
        
        return True
    
    def _load_monitor_config(self):
        """Load or create per-monitor configuration."""
        from monitor_control.config import MonitorConfig
        
        if not self.current_monitor:
            logger.warning("No current monitor, skipping per-monitor config")
            return
        
        monitor_id = self.current_monitor.get_config_id()
        logger.info(f"Loading config for monitor: {monitor_id}")
        
        # Get available color modes from DDC
        ddc_color_modes = self.ddc.get_available_color_modes()
        
        # Load or create monitor config, using global color mode names
        self.monitor_config = MonitorConfig.get_or_create(
            monitor_id, 
            ddc_color_modes,
            self.config.color_modes  # Pass global config color mode names
        )
        
        # Cache monitor config by display number
        display_num = self.current_monitor.display_number if self.current_monitor else self.ddc.display
        self.monitor_configs[display_num] = self.monitor_config
        
        # If still no color modes, use global config as fallback
        if not self.monitor_config.color_modes and self.config.color_modes:
            self.monitor_config.color_modes = self.config.color_modes
            self.monitor_config.save()
        
        logger.info(f"Monitor has {len(self.monitor_config.color_modes)} color modes: {list(self.monitor_config.color_modes.keys())}")
        
        # Initialize profile color modes and presets - fill in any missing profiles
        profile_names = ["default"] + [p.name for p in self.config.profiles]
        needs_save = False
        
        # Check if any profiles are missing color settings
        missing_color_modes = [p for p in profile_names if p not in self.monitor_config.profile_color_modes]
        missing_color_presets = [p for p in profile_names if p not in self.monitor_config.profile_color_presets]
        
        if (missing_color_modes or missing_color_presets) and not self.skip_ddc:
            # Get current Display Mode (0xDC) from monitor
            # Use -1 as fallback (impossible VCP value) to ensure first switch always sends command
            current_display_mode = -1
            try:
                vcp_result = self.ddc.get_vcp(0xDC)
                if vcp_result:
                    current_display_mode = vcp_result.current_value
                logger.info(f"Monitor current display mode (0xDC): {current_display_mode}")
            except Exception as e:
                logger.warning(f"Could not read display mode (0xDC), using placeholder {current_display_mode}: {e}")
            
            # Get current Color Preset (0x14) from monitor
            # Use -1 as fallback (impossible VCP value) to ensure first switch always sends command
            current_color_preset = -1
            try:
                vcp_result = self.ddc.get_vcp(0x14)
                if vcp_result:
                    current_color_preset = vcp_result.current_value
                logger.info(f"Monitor current color preset (0x14): {current_color_preset}")
            except Exception as e:
                logger.warning(f"Could not read color preset (0x14), using placeholder {current_color_preset}: {e}")
            
            # Initialize missing profiles to current monitor settings
            if missing_color_modes:
                for profile_name in missing_color_modes:
                    self.monitor_config.set_profile_color_mode(profile_name, current_display_mode)
                logger.info(f"Initialized {len(missing_color_modes)} missing profile display modes to {current_display_mode}: {missing_color_modes}")
                needs_save = True
            
            # Always initialize missing presets (use current value or default 6500K)
            if missing_color_presets:
                for profile_name in missing_color_presets:
                    self.monitor_config.set_profile_color_preset(profile_name, current_color_preset)
                logger.info(f"Initialized {len(missing_color_presets)} missing profile color presets to {current_color_preset}: {missing_color_presets}")
                needs_save = True
            
            if needs_save:
                self.monitor_config.save()
        elif (missing_color_modes or missing_color_presets) and self.skip_ddc:
            logger.info(f"[--skip-ddc] Skipping profile color mode initialization")
    
    def _get_or_create_profile_manager(self, display_number: int) -> 'ProfileManager':
        """
        Get or create a ProfileManager for a specific monitor.
        
        This allows each monitor to have its own independent auto brightness/contrast.
        
        Args:
            display_number: DDC display number
            
        Returns:
            ProfileManager for the specified monitor
        """
        from monitor_control.profile_manager import ProfileManager
        
        if display_number in self.profile_managers:
            return self.profile_managers[display_number]
        
        # Get or create DDC controller for this display
        if display_number not in self.ddc_controllers:
            from monitor_control.ddc import DDCController
            ddc = DDCController(
                display=display_number,
                retry_count=self.config.ddc_retry_count,
                sleep_multiplier=self.config.ddc_sleep_multiplier,
            )
            self.ddc_controllers[display_number] = ddc
            # Set up busy callback for overview indicator
            self._setup_ddc_busy_callback(ddc, display_number)
        
        ddc = self.ddc_controllers[display_number]
        
        # Create new ProfileManager for this monitor
        pm = ProfileManager(self.config, ddc, monitor_index=display_number)
        self.profile_managers[display_number] = pm
        
        # Add callbacks for this monitor's ProfileManager (capture display_number in closure)
        def make_settings_callback(disp_num):
            def callback(settings):
                self._on_settings_change_for_display(settings, disp_num)
            return callback
        
        def make_profile_callback(disp_num):
            def callback(profile):
                self._on_profile_change_for_display(profile, disp_num)
            return callback
        
        def make_window_callback(disp_num):
            def callback(window):
                self._on_window_change_for_display(window, disp_num)
            return callback
        
        pm.add_settings_change_callback(make_settings_callback(display_number))
        pm.add_profile_change_callback(make_profile_callback(display_number))
        pm.add_window_change_callback(make_window_callback(display_number))
        
        # Set callback to get profile color modes from monitor-specific config
        # Use cached monitor config to avoid disk I/O on every profile switch
        def make_color_mode_callback(disp_num):
            def callback(profile_name: str):
                # Use cached monitor config from self.monitor_configs
                mon_cfg = self.monitor_configs.get(disp_num)
                if mon_cfg:
                    return mon_cfg.get_profile_color_mode(profile_name)
                return None
            return callback
        
        def make_color_preset_callback(disp_num):
            def callback(profile_name: str):
                # Use cached monitor config to get color preset (0x14)
                mon_cfg = self.monitor_configs.get(disp_num)
                if mon_cfg:
                    return mon_cfg.get_profile_color_preset(profile_name)
                return None
            return callback
        
        pm.set_profile_color_mode_callback(make_color_mode_callback(display_number))
        pm.set_profile_color_preset_callback(make_color_preset_callback(display_number))
        
        # Start the ProfileManager so it can respond to auto settings
        pm.start()
        
        logger.info(f"Created and started ProfileManager for display {display_number}")
        
        return pm
    
    def _init_gui(self):
        """Initialize GUI components."""
        from monitor_control.gui import MonitorOverlayCTk
        
        try:
            # Create overlay
            self.overlay = MonitorOverlayCTk(
                position=self.config.gui.overlay_position,
                timeout=self.config.gui.overlay_timeout,
                theme=self.config.gui.theme,
            )
            
            # Connect overlay callbacks
            self.overlay.set_callback('brightness_change', self._on_brightness_change)
            self.overlay.set_callback('contrast_change', self._on_contrast_change)
            self.overlay.set_callback('sharpness_change', self._on_sharpness_change)
            self.overlay.set_callback('mode_change', self._on_mode_change)
            self.overlay.set_callback('red_gain_change', self._on_red_gain_change)
            self.overlay.set_callback('green_gain_change', self._on_green_gain_change)
            self.overlay.set_callback('blue_gain_change', self._on_blue_gain_change)
            self.overlay.set_callback('toggle_auto_profile', self._on_toggle_auto_profile)
            self.overlay.set_callback('toggle_auto_brightness', self._on_toggle_auto_brightness)
            self.overlay.set_callback('toggle_auto_contrast', self._on_toggle_auto_contrast)
            self.overlay.set_callback('profile_auto_brightness_toggle', self._on_profile_auto_brightness_toggle)
            self.overlay.set_callback('profile_auto_contrast_toggle', self._on_profile_auto_contrast_toggle)
            self.overlay.set_callback('fullscreen_only_toggle', self._on_fullscreen_only_toggle)
            self.overlay.set_callback('adaptive_setting_change', self._on_adaptive_setting_change)
            self.overlay.set_callback('profile_select', self._on_profile_select)
            self.overlay.set_callback('profile_mode_change', self._on_profile_mode_change)
            self.overlay.set_callback('add_app_to_profile', self._on_add_app_to_profile)
            self.overlay.set_callback('vcp_change', self._on_vcp_change)
            self.overlay.set_callback('monitor_change', self._on_monitor_change)
            self.overlay.set_callback('refresh_monitors', self._on_refresh_monitors)
            self.overlay.set_callback('refresh_values', self._on_refresh_values)
            self.overlay.set_callback('refresh_basic_values', self._on_refresh_basic_values)
            self.overlay.set_callback('refresh_rgb_values', self._on_refresh_rgb_values)
            self.overlay.set_callback('color_mode_names_changed', self._on_color_mode_names_changed)
            self.overlay.set_callback('quit', self._on_quit)
            
            # Start the overlay first (creates the window)
            self.overlay.start()
            
            # Wait a moment for window to be fully created
            import time
            time.sleep(0.3)
            
            # Loading: Set up profiles FIRST (before creating tabs)
            self.overlay.set_loading_status("Loading profiles...")
            # Get profiles from config (not ProfileManager - it's created later in _populate_monitors)
            profiles = ["default"] + [p.name for p in self.config.profiles]
            profile_color_modes = self._get_profile_color_modes()
            logger.info(f"Available profiles from config: {profiles}")
            if self.skip_ddc:
                logger.info(f"[--skip-ddc] Profile color modes at GUI init: {profile_color_modes}")
            self.overlay.set_profiles(profiles, profile_color_modes)
            
            # Loading: Detect monitors and read ALL their settings (creates tabs with profiles)
            self.overlay.set_loading_status("Detecting monitors and reading settings...")
            self._populate_monitors()  # This now reads settings for ALL monitors
            
            # Done loading - show main UI
            self.overlay.hide_loading()
            
            # Note: Per-display callbacks are registered in _get_or_create_profile_manager()
            # No need for legacy callbacks here - they cause duplicate updates
            
            logger.info("GUI initialized")
            
        except Exception as e:
            logger.warning(f"Could not initialize GUI: {e}")
            import traceback
            traceback.print_exc()
            self.overlay = None
    
    def _populate_monitors(self):
        """Detect monitors and populate the monitor selector, reading settings for all."""
        if not self.overlay:
            return
        
        from monitor_control.ddc import DDCController
        from monitor_control.config import MonitorConfig
        
        self.monitors = DDCController.detect_monitors()
        
        if not self.monitors:
            logger.warning("No monitors detected")
            return
        
        # Build list of (display_number, display_name) tuples
        monitor_list = []
        for m in self.monitors:
            if m.model and m.model != "Unknown":
                name = m.model
            elif m.manufacturer and m.manufacturer != "Unknown":
                name = m.manufacturer
            else:
                name = "Unknown Monitor"
            name = f"{name} (Display {m.display_number})"
            monitor_list.append((m.display_number, name))
        
        logger.info(f"Detected {len(monitor_list)} monitors: {[n for _, n in monitor_list]}")
        
        current_display = self.ddc.display if self.ddc.display else 1
        self.overlay.set_monitors(monitor_list, current_display)
        
        # Wait for tabs to be created (they're created asynchronously)
        import time
        max_wait = 2.0  # Max 2 seconds
        waited = 0
        while waited < max_wait:
            time.sleep(0.1)
            waited += 0.1
            # Check if all tabs are ready
            if self.overlay.are_tabs_ready(len(monitor_list)):
                break
        logger.info(f"Waited {waited:.1f}s for tabs to be created")
        
        # Read settings for ALL monitors and populate their tabs
        for m in self.monitors:
            display_num = m.display_number
            try:
                # Get or create DDC controller for this monitor
                if display_num not in self.ddc_controllers:
                    ddc = DDCController(
                        display=display_num,
                        retry_count=self.config.ddc_retry_count,
                        sleep_multiplier=self.config.ddc_sleep_multiplier,
                    )
                    self.ddc_controllers[display_num] = ddc
                    # Set up busy callback for overview indicator
                    self._setup_ddc_busy_callback(ddc, display_num)
                ddc = self.ddc_controllers[display_num]
                
                # Load monitor config (for color modes and auto settings)
                monitor_id = m.get_config_id()
                # Use cached config or create new one
                if display_num in self.monitor_configs:
                    monitor_config = self.monitor_configs[display_num]
                else:
                    monitor_config = MonitorConfig.get_or_create(monitor_id)
                    self.monitor_configs[display_num] = monitor_config
                
                # Get color modes if not cached
                if not monitor_config.color_modes and not self.skip_ddc:
                    ddc_color_modes = ddc.get_available_color_modes()
                    monitor_config.set_color_modes_from_ddc(ddc_color_modes, self.config.color_modes)
                    monitor_config.save()
                elif not monitor_config.color_modes and self.skip_ddc:
                    logger.info(f"[--skip-ddc] No color modes in config for display {display_num}, using defaults from global config")
                    # Use color modes from global config as fallback
                    if self.config.color_modes:
                        monitor_config.color_modes = dict(self.config.color_modes)
                
                # Initialize profile color modes and presets - fill in any missing profiles
                profile_names = ["default"] + [p.name for p in self.config.profiles]
                missing_modes = [p for p in profile_names if p not in monitor_config.profile_color_modes]
                missing_presets = [p for p in profile_names if p not in monitor_config.profile_color_presets]
                needs_save = False
                
                if (missing_modes or missing_presets) and not self.skip_ddc:
                    # Get current values from monitor
                    # Use -1 as fallback (impossible VCP value) to ensure first switch always sends command
                    current_mode = -1
                    current_preset = -1
                    try:
                        vcp_result = ddc.get_vcp(0xDC)
                        current_mode = vcp_result.current_value if vcp_result else -1
                        logger.info(f"Display {display_num}: Read current 0xDC = {current_mode}")
                    except Exception as e:
                        logger.warning(f"Display {display_num}: Could not read 0xDC, using placeholder {current_mode}: {e}")
                    try:
                        vcp_result = ddc.get_vcp(0x14)
                        if vcp_result:
                            current_preset = vcp_result.current_value
                        logger.info(f"Display {display_num}: Read current 0x14 = {current_preset}")
                    except Exception as e:
                        logger.warning(f"Display {display_num}: Could not read 0x14, using placeholder {current_preset}: {e}")
                    
                    if missing_modes:
                        for profile_name in missing_modes:
                            monitor_config.set_profile_color_mode(profile_name, current_mode)
                        logger.info(f"Display {display_num}: Initialized {len(missing_modes)} missing profile display modes to {current_mode}")
                        needs_save = True
                    
                    # Always initialize missing presets (use current value or default 6500K)
                    if missing_presets:
                        for profile_name in missing_presets:
                            monitor_config.set_profile_color_preset(profile_name, current_preset)
                        logger.info(f"Display {display_num}: Initialized {len(missing_presets)} missing profile color presets to {current_preset}")
                        needs_save = True
                    
                    if needs_save:
                        monitor_config.save()
                elif (missing_modes or missing_presets) and self.skip_ddc:
                    logger.info(f"[--skip-ddc] Skipping profile color mode initialization for display {display_num}")
                    logger.info(f"[--skip-ddc] Saved profile_color_modes: {monitor_config.profile_color_modes}")
                    logger.info(f"[--skip-ddc] Saved profile_color_presets: {monitor_config.profile_color_presets}")
                
                # Update GUI with color modes for this tab
                if monitor_config.color_modes:
                    self.overlay.set_color_modes(list(monitor_config.color_modes.keys()), display_num=display_num)
                    self.overlay.set_all_color_modes(monitor_config.color_modes, display_num=display_num)
                
                # Update profile color modes for this tab (load saved selections)
                profile_color_modes = self._get_profile_color_modes(monitor_config)
                self.overlay.set_profile_color_modes(profile_color_modes, display_num=display_num)
                
                # Update profile auto brightness/contrast switches with values from config
                profile_auto_states = {}
                # Include default profile
                default_profile = self.config.default_profile
                profile_auto_states[default_profile.name] = {
                    'auto_brightness': default_profile.auto_brightness if default_profile.auto_brightness is not None else False,
                    'auto_contrast': default_profile.auto_contrast if default_profile.auto_contrast is not None else False
                }
                # Include all other profiles
                for profile in self.config.profiles:
                    profile_auto_states[profile.name] = {
                        'auto_brightness': profile.auto_brightness if profile.auto_brightness is not None else False,
                        'auto_contrast': profile.auto_contrast if profile.auto_contrast is not None else False
                    }
                self.overlay.set_profile_auto_states(profile_auto_states, display_num=display_num)
                
                # Update auto settings for this tab and overview
                self.overlay.set_auto_brightness_state(monitor_config.auto_brightness, display_num=display_num)
                self.overlay.set_auto_contrast_state(monitor_config.auto_contrast, display_num=display_num)
                self.overlay.set_auto_profile_state(monitor_config.auto_profile, display_num=display_num)
                # Also update overview auto buttons
                if hasattr(self.overlay, 'update_overview_auto_states'):
                    self.overlay.update_overview_auto_states(
                        display_num,
                        auto_brightness=monitor_config.auto_brightness,
                        auto_contrast=monitor_config.auto_contrast,
                        auto_profile=monitor_config.auto_profile
                    )
                self.overlay.set_adaptive_settings(
                    auto_brightness=monitor_config.auto_brightness,
                    auto_contrast=monitor_config.auto_contrast,
                    display_num=display_num,
                    **monitor_config.adaptive_settings
                )
                
                # Read current values from DDC (all settings including RGB)
                if self.skip_ddc:
                    logger.info(f"[--skip-ddc] Skipping DDC readings for display {display_num}")
                    # Use cached values from config
                    settings = {
                        'brightness': monitor_config.brightness,
                        'contrast': monitor_config.contrast,
                        'color_preset': monitor_config.color_preset,
                    }
                    # Only include supported features
                    unsupported = monitor_config.unsupported_features
                    if 'sharpness' not in unsupported:
                        settings['sharpness'] = monitor_config.sharpness
                        settings['sharpness_max'] = monitor_config.sharpness_max
                    if 'red_gain' not in unsupported:
                        settings['red_gain'] = monitor_config.red_gain
                    if 'green_gain' not in unsupported:
                        settings['green_gain'] = monitor_config.green_gain
                    if 'blue_gain' not in unsupported:
                        settings['blue_gain'] = monitor_config.blue_gain
                    
                    logger.info(f"[--skip-ddc] Loaded from config: brightness={settings.get('brightness')}, contrast={settings.get('contrast')}, sharpness={settings.get('sharpness', 'N/A')}")
                    if unsupported:
                        logger.info(f"[--skip-ddc] Unsupported features for display {display_num}: {unsupported}")
                else:
                    logger.info(f"Reading settings for display {display_num}...")
                    settings = ddc.get_all_settings(quick=False)
                
                # Update GUI sliders for this tab
                self.overlay.set_brightness(settings.get('brightness', 50), display_num=display_num)
                self.overlay.set_contrast(settings.get('contrast', 50), display_num=display_num)
                
                # Configure sharpness range and set value (if supported)
                unsupported_changed = False
                if 'sharpness' in settings:
                    sharpness_max = settings.get('sharpness_max', 100)
                    self.overlay.configure_sharpness_range(sharpness_max, display_num=display_num)
                    self.overlay.set_sharpness(settings.get('sharpness', 50), display_num=display_num)
                    # Store the max for later use and save to config (for --skip-ddc mode)
                    if monitor_config.sharpness_max != sharpness_max:
                        monitor_config.sharpness_max = sharpness_max
                        monitor_config.sharpness = settings.get('sharpness', 50)
                        monitor_config.save()
                        logger.debug(f"Saved sharpness_max={sharpness_max} to config for display {display_num}")
                    # Remove from unsupported if it was previously marked
                    if 'sharpness' in monitor_config.unsupported_features:
                        monitor_config.unsupported_features.remove('sharpness')
                        unsupported_changed = True
                else:
                    # Sharpness not supported - disable slider and save to config
                    self.overlay.disable_feature('sharpness', display_num=display_num)
                    if 'sharpness' not in monitor_config.unsupported_features:
                        monitor_config.unsupported_features.append('sharpness')
                        unsupported_changed = True
                
                # Set RGB gains (if supported)
                if 'red_gain' in settings:
                    self.overlay.set_red_gain(settings.get('red_gain', 100), display_num=display_num)
                    if 'red_gain' in monitor_config.unsupported_features:
                        monitor_config.unsupported_features.remove('red_gain')
                        unsupported_changed = True
                else:
                    self.overlay.disable_feature('red_gain', display_num=display_num)
                    if 'red_gain' not in monitor_config.unsupported_features:
                        monitor_config.unsupported_features.append('red_gain')
                        unsupported_changed = True
                
                if 'green_gain' in settings:
                    self.overlay.set_green_gain(settings.get('green_gain', 100), display_num=display_num)
                    if 'green_gain' in monitor_config.unsupported_features:
                        monitor_config.unsupported_features.remove('green_gain')
                        unsupported_changed = True
                else:
                    self.overlay.disable_feature('green_gain', display_num=display_num)
                    if 'green_gain' not in monitor_config.unsupported_features:
                        monitor_config.unsupported_features.append('green_gain')
                        unsupported_changed = True
                
                if 'blue_gain' in settings:
                    self.overlay.set_blue_gain(settings.get('blue_gain', 100), display_num=display_num)
                    if 'blue_gain' in monitor_config.unsupported_features:
                        monitor_config.unsupported_features.remove('blue_gain')
                        unsupported_changed = True
                else:
                    self.overlay.disable_feature('blue_gain', display_num=display_num)
                    if 'blue_gain' not in monitor_config.unsupported_features:
                        monitor_config.unsupported_features.append('blue_gain')
                        unsupported_changed = True
                
                # Save if unsupported features changed
                if unsupported_changed:
                    monitor_config.save()
                    logger.info(f"Display {display_num}: Saved unsupported features: {monitor_config.unsupported_features}")
                
                # Set color mode if available
                if 'color_preset' in settings:
                    mode = settings.get('color_preset', 0)
                    mode_name = monitor_config.get_color_mode_name(mode) if monitor_config else f"Mode {mode}"
                    self.overlay.set_color_mode(mode, mode_name, display_num=display_num)
                
                logger.info(f"Display {display_num} loaded: brightness={settings.get('brightness')}, contrast={settings.get('contrast')}, auto_brightness={monitor_config.auto_brightness}")
                
                # Create/get ProfileManager for this monitor
                # During startup, don't save to profile and defer screen analysis
                # Screen analysis will be started after all monitors are loaded
                pm = self._get_or_create_profile_manager(display_num)
                pm.set_auto_brightness_enabled(monitor_config.auto_brightness, save_to_profile=False, start_monitoring=False)
                pm.set_auto_contrast_enabled(monitor_config.auto_contrast, save_to_profile=False, start_monitoring=False)
                pm.set_auto_profile_enabled(monitor_config.auto_profile)
                pm.set_fullscreen_only(monitor_config.fullscreen_only)
                
                # Apply adaptive settings
                analyzer = pm.screen_analyzer
                adaptive = monitor_config.adaptive_settings
                analyzer.min_brightness = adaptive.get('min_brightness', 20)
                analyzer.max_brightness = adaptive.get('max_brightness', 80)
                analyzer.min_contrast = adaptive.get('min_contrast', 30)
                analyzer.max_contrast = adaptive.get('max_contrast', 70)
                
                # Set as current if this is the active display
                if display_num == current_display:
                    self.profile_manager = pm
                    self.monitor_config = monitor_config
                    self.ddc = ddc
                
                logger.info(f"Initialized display {display_num}: auto_brightness={monitor_config.auto_brightness}, auto_contrast={monitor_config.auto_contrast}, auto_profile={monitor_config.auto_profile}")
                
                # Update overview tab with monitor info
                if hasattr(self.overlay, 'update_overview_settings'):
                    self.overlay.update_overview_settings(display_num, 
                        brightness=settings.get('brightness', 50),
                        contrast=settings.get('contrast', 50))
                
                # Get geometry info for overview (including graphical layout)
                geometry = ddc.get_geometry()
                if geometry and hasattr(self.overlay, 'update_overview_monitor_info'):
                    # Use native resolution for display, framebuffer for layout
                    native_res = f"{geometry.native_width}x{geometry.native_height}"
                    scale_str = f" ({geometry.scale_percent}%)" if geometry.scale_percent != 100 else ""
                    logger.info(f"Display {display_num}: native={native_res}, fb={geometry.width}x{geometry.height}, scale={geometry.scale_percent}%")
                    self.overlay.update_overview_monitor_info(
                        display_num,
                        resolution=f"{native_res}{scale_str}",
                        position=f"{geometry.x}, {geometry.y}",
                        orientation="Normal",
                        x=geometry.x,
                        y=geometry.y,
                        width=geometry.width,
                        height=geometry.height,
                        native_width=geometry.native_width,
                        native_height=geometry.native_height,
                        scale=geometry.scale_percent
                    )
                
                # Set initial profile in overview (default profile at startup)
                if hasattr(self.overlay, 'update_overview_profile'):
                    self.overlay.update_overview_profile(display_num, "default")
                
            except Exception as e:
                logger.warning(f"Could not read settings for display {display_num}: {e}")
        
        # Force a delayed refresh of all auto states and redraw layout (after GUI has fully initialized)
        def refresh_all_states():
            for m in self.monitors:
                disp = m.display_number
                # Use cached config
                mon_cfg = self.monitor_configs.get(disp)
                if not mon_cfg:
                    mon_id = m.get_config_id()
                    mon_cfg = MonitorConfig.get_or_create(mon_id)
                    self.monitor_configs[disp] = mon_cfg
                logger.info(f"Refreshing auto states for display {disp}: auto_brightness={mon_cfg.auto_brightness}")
                self.overlay.set_auto_brightness_state(mon_cfg.auto_brightness, display_num=disp)
                self.overlay.set_auto_contrast_state(mon_cfg.auto_contrast, display_num=disp)
                self.overlay.set_auto_profile_state(mon_cfg.auto_profile, display_num=disp)
                self.overlay.set_fullscreen_only_state(mon_cfg.fullscreen_only, display_num=disp)
                # Also update overview auto buttons
                if hasattr(self.overlay, 'update_overview_auto_states'):
                    self.overlay.update_overview_auto_states(
                        disp,
                        auto_brightness=mon_cfg.auto_brightness,
                        auto_contrast=mon_cfg.auto_contrast,
                        auto_profile=mon_cfg.auto_profile
                    )
            
            # Redraw monitor layout after all geometries are loaded
            if hasattr(self.overlay, '_draw_monitor_layout'):
                self.overlay._draw_monitor_layout()
            
            # NOW start screen monitoring for all ProfileManagers (after all monitors are loaded)
            logger.info("Starting screen monitoring for all monitors...")
            for pm in self.profile_managers.values():
                pm._update_screen_monitoring()
        
        if self.overlay and hasattr(self.overlay, '_root') and self.overlay._root:
            self.overlay._root.after(500, refresh_all_states)  # Refresh after GUI is stable
    
    def _on_refresh_monitors(self):
        """Handle refresh monitors button click."""
        # Show loading overlay
        if self.overlay and hasattr(self.overlay, 'show_loading'):
            self.overlay.show_loading()
            self.overlay.set_loading_status("Detecting monitors...")
        
        def refresh():
            logger.info("Refreshing monitors...")
            
            # Update loading status
            if self.overlay and hasattr(self.overlay, 'set_loading_status'):
                def update_status(msg):
                    if self.overlay._root:
                        self.overlay._root.after(0, lambda: self.overlay.set_loading_status(msg))
                
                update_status("Refreshing geometry...")
            
            # Force geometry refresh for all cached DDC controllers
            for display_num, ddc in self.ddc_controllers.items():
                ddc.refresh_geometry()
                logger.info(f"Refreshed geometry for display {display_num}")
            
            # Refresh geometry in all profile managers
            for display_num, pm in self.profile_managers.items():
                pm.refresh_geometry()
                logger.info(f"Refreshed ProfileManager geometry for display {display_num}")
            
            if self.overlay and hasattr(self.overlay, 'set_loading_status') and self.overlay._root:
                self.overlay._root.after(0, lambda: self.overlay.set_loading_status("Loading monitors..."))
            
            # Re-populate monitors (this will re-detect and update everything)
            self._populate_monitors()
            
            if self.overlay and hasattr(self.overlay, 'set_loading_status') and self.overlay._root:
                self.overlay._root.after(0, lambda: self.overlay.set_loading_status("Loading settings..."))
            
            # Reload per-monitor config
            self._load_monitor_config()
            
            # Force GUI refresh on main thread and hide loading
            if self.overlay and hasattr(self.overlay, '_root') and self.overlay._root:
                def update_gui():
                    # Hide loading overlay
                    if hasattr(self.overlay, 'hide_loading'):
                        self.overlay.hide_loading()
                    # Redraw monitor layout
                    if hasattr(self.overlay, '_draw_monitor_layout'):
                        self.overlay._draw_monitor_layout()
                    # Switch to Overview tab to show updated values
                    if hasattr(self.overlay, '_tabview'):
                        self.overlay._tabview.set("📊 Overview")
                    # Force update of all widgets
                    self.overlay._root.update_idletasks()
                self.overlay._root.after(100, update_gui)
            
            logger.info("Monitor refresh complete")
        
        # Run in background to not block GUI
        threading.Thread(target=refresh, daemon=True).start()
    
    def _on_monitor_change(self, display_number: int):
        """Handle monitor selection change.
        
        Note: This does NOT stop the previous monitor's auto features - they
        continue running in the background. Each monitor has its own ProfileManager.
        """
        logger.info(f"Switching to monitor display {display_number}")
        
        def switch_monitor():
            from monitor_control.ddc import DDCController
            from monitor_control.config import MonitorConfig
            
            # Update config (fast, just memory)
            self.config.display = display_number
            
            # Find the monitor info for this display
            for m in self.monitors:
                if m.display_number == display_number:
                    self.current_monitor = m
                    break
            
            # Get or create DDC controller for this display (cached)
            if display_number not in self.ddc_controllers:
                ddc = DDCController(
                    display=display_number,
                    retry_count=self.config.ddc_retry_count,
                    sleep_multiplier=self.config.ddc_sleep_multiplier,
                )
                self.ddc_controllers[display_number] = ddc
                # Set up busy callback for overview indicator
                self._setup_ddc_busy_callback(ddc, display_number)
            self.ddc = self.ddc_controllers[display_number]
            
            # Deactivate GUI updates for the OLD ProfileManager
            if self.profile_manager:
                self.profile_manager.set_gui_active(False)
            
            # Get or create ProfileManager for this monitor
            self.profile_manager = self._get_or_create_profile_manager(display_number)
            self.profile_manager.set_gui_active(True)
            
            # Ensure correct DDC and geometry
            if self.profile_manager.ddc.display != display_number:
                self.profile_manager.switch_monitor(self.ddc)
            
            # Start profile manager if not running
            if not self.profile_manager._running:
                self.profile_manager.start()
            
            # Load per-monitor config (uses cached color modes from MonitorConfig)
            if self.current_monitor:
                # Use cached config
                if display_number in self.monitor_configs:
                    self.monitor_config = self.monitor_configs[display_number]
                else:
                    monitor_id = self.current_monitor.get_config_id()
                    self.monitor_config = MonitorConfig.get_or_create(monitor_id)
                    self.monitor_configs[display_number] = self.monitor_config
                
                # If no color modes cached, fetch them (only happens once per monitor)
                if not self.monitor_config.color_modes:
                    ddc_color_modes = self.ddc.get_available_color_modes()
                    self.monitor_config.set_color_modes_from_ddc(ddc_color_modes, self.config.color_modes)
                    self.monitor_config.save()
                
                # Update GUI with cached color modes
                if self.overlay and self.monitor_config.color_modes:
                    self.overlay.set_color_modes(list(self.monitor_config.color_modes.keys()), display_num=display_number)
                    self.overlay.set_all_color_modes(self.monitor_config.color_modes, display_num=display_number)
                
                # Update auto settings in GUI
                if self.overlay:
                    self.overlay.set_auto_brightness_state(self.monitor_config.auto_brightness, display_num=display_number)
                    self.overlay.set_auto_contrast_state(self.monitor_config.auto_contrast, display_num=display_number)
                    self.overlay.set_auto_profile_state(self.monitor_config.auto_profile, display_num=display_number)
                    # Also update overview auto buttons
                    if hasattr(self.overlay, 'update_overview_auto_states'):
                        self.overlay.update_overview_auto_states(
                            display_number,
                            auto_brightness=self.monitor_config.auto_brightness,
                            auto_contrast=self.monitor_config.auto_contrast,
                            auto_profile=self.monitor_config.auto_profile
                        )
                    self.overlay.set_adaptive_settings(
                        auto_brightness=self.monitor_config.auto_brightness,
                        auto_contrast=self.monitor_config.auto_contrast,
                        display_num=display_number,
                        **self.monitor_config.adaptive_settings
                    )
                
                # Apply auto settings to profile manager (don't save - just loading existing settings)
                # start_monitoring=True here since this is a tab switch, not startup
                if self.profile_manager:
                    self.profile_manager.set_auto_brightness_enabled(self.monitor_config.auto_brightness, save_to_profile=False, start_monitoring=True)
                    self.profile_manager.set_auto_contrast_enabled(self.monitor_config.auto_contrast, save_to_profile=False, start_monitoring=True)
                    self.profile_manager.set_auto_profile_enabled(self.monitor_config.auto_profile)
                    
                    # Apply per-monitor adaptive settings to the screen analyzer
                    analyzer = self.profile_manager.screen_analyzer
                    adaptive = self.monitor_config.adaptive_settings
                    analyzer.min_brightness = adaptive.get('min_brightness', 20)
                    analyzer.max_brightness = adaptive.get('max_brightness', 80)
                    analyzer.min_contrast = adaptive.get('min_contrast', 30)
                    analyzer.max_contrast = adaptive.get('max_contrast', 70)
                    analyzer.dark_threshold = adaptive.get('dark_threshold', 0.3)
                    analyzer.bright_threshold = adaptive.get('bright_threshold', 0.7)
                    analyzer.smoothing = adaptive.get('smoothing', 0.3)
                    logger.info(f"Applied adaptive settings to display {display_number}: min_b={adaptive.get('min_brightness')}, max_b={adaptive.get('max_brightness')}")
            
            # Note: We no longer read DDC settings on every tab switch.
            # Use the Refresh button to manually read values, or let auto mode update them.
        
        # Run in background to not block tab switch
        threading.Thread(target=switch_monitor, daemon=True).start()
    
    def _on_brightness_change(self, value: int, display_num: int = None):
        """Handle brightness change from overlay (async, skips outdated values)."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        # Store latest value
        self._latest_brightness[display_num] = value
        
        # If a command is already pending, it will pick up the latest value
        key = (display_num, 'brightness')
        if self._pending_commands.get(key):
            logger.debug(f"Brightness change queued for display {display_num}: {value}")
            return
        
        self._pending_commands[key] = True
        
        def _send_brightness():
            try:
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if ddc:
                    # Get the latest value (may have changed while waiting)
                    to_send = self._latest_brightness.get(display_num, value)
                    ddc.set_brightness(to_send)
                    # Check if value changed while we were running
                    new_latest = self._latest_brightness.get(display_num)
                    if new_latest is not None and new_latest != to_send:
                        logger.debug(f"Brightness changed during send, re-sending: {new_latest}")
                        ddc.set_brightness(new_latest)
            finally:
                self._pending_commands[key] = False
        
        threading.Thread(target=_send_brightness, daemon=True).start()
    
    def _on_contrast_change(self, value: int, display_num: int = None):
        """Handle contrast change from overlay (async, skips outdated values)."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        # Store latest value
        self._latest_contrast[display_num] = value
        
        # If a command is already pending, it will pick up the latest value
        key = (display_num, 'contrast')
        if self._pending_commands.get(key):
            logger.debug(f"Contrast change queued for display {display_num}: {value}")
            return
        
        self._pending_commands[key] = True
        
        def _send_contrast():
            try:
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if ddc:
                    to_send = self._latest_contrast.get(display_num, value)
                    ddc.set_contrast(to_send)
                    new_latest = self._latest_contrast.get(display_num)
                    if new_latest is not None and new_latest != to_send:
                        logger.debug(f"Contrast changed during send, re-sending: {new_latest}")
                        ddc.set_contrast(new_latest)
            finally:
                self._pending_commands[key] = False
        
        threading.Thread(target=_send_contrast, daemon=True).start()
    
    def _on_sharpness_change(self, value: int, display_num: int = None):
        """Handle sharpness change from overlay (async, skips outdated values)."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        # Store latest value
        if not hasattr(self, '_latest_sharpness'):
            self._latest_sharpness = {}
        self._latest_sharpness[display_num] = value
        
        # If a command is already pending, it will pick up the latest value
        key = (display_num, 'sharpness')
        if self._pending_commands.get(key):
            logger.debug(f"Sharpness change queued for display {display_num}: {value}")
            return
        
        self._pending_commands[key] = True
        
        def _send_sharpness():
            try:
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if ddc:
                    to_send = self._latest_sharpness.get(display_num, value)
                    # Get max sharpness for this monitor from config
                    max_sharpness = 100
                    monitor_config = self.monitor_configs.get(display_num)
                    if monitor_config and hasattr(monitor_config, 'sharpness_max'):
                        max_sharpness = monitor_config.sharpness_max
                    ddc.set_sharpness(to_send, max_value=max_sharpness)
                    new_latest = self._latest_sharpness.get(display_num)
                    if new_latest is not None and new_latest != to_send:
                        logger.debug(f"Sharpness changed during send, re-sending: {new_latest}")
                        ddc.set_sharpness(new_latest, max_value=max_sharpness)
            finally:
                self._pending_commands[key] = False
        
        threading.Thread(target=_send_sharpness, daemon=True).start()
    
    def _on_mode_change(self, mode_value: int, display_num: int = None):
        """Handle color mode change from overlay (async, skips outdated values)."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        self._latest_mode[display_num] = mode_value
        key = (display_num, 'mode')
        if self._pending_commands.get(key):
            return
        
        self._pending_commands[key] = True
        
        def _set_mode():
            try:
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if ddc:
                    latest = self._latest_mode.get(display_num, mode_value)
                    mode_name = None
                    if self.monitor_config:
                        mode_name = self.monitor_config.get_color_mode_name(latest)
                    ddc.set_color_mode(latest, mode_name)
            finally:
                self._pending_commands[key] = False
        
        threading.Thread(target=_set_mode, daemon=True).start()
    
    def _on_red_gain_change(self, value: int, display_num: int = None):
        """Handle red gain change from overlay (async, skips outdated values)."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        self._latest_red_gain[display_num] = value
        key = (display_num, 'red_gain')
        if self._pending_commands.get(key):
            return
        
        self._pending_commands[key] = True
        
        def _send():
            try:
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if ddc:
                    latest = self._latest_red_gain.get(display_num, value)
                    ddc.set_red_gain(latest)
            finally:
                self._pending_commands[key] = False
        
        threading.Thread(target=_send, daemon=True).start()
    
    def _on_green_gain_change(self, value: int, display_num: int = None):
        """Handle green gain change from overlay (async, skips outdated values)."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        self._latest_green_gain[display_num] = value
        key = (display_num, 'green_gain')
        if self._pending_commands.get(key):
            return
        
        self._pending_commands[key] = True
        
        def _send():
            try:
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if ddc:
                    latest = self._latest_green_gain.get(display_num, value)
                    ddc.set_green_gain(latest)
            finally:
                self._pending_commands[key] = False
        
        threading.Thread(target=_send, daemon=True).start()
    
    def _on_blue_gain_change(self, value: int, display_num: int = None):
        """Handle blue gain change from overlay (async, skips outdated values)."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        self._latest_blue_gain[display_num] = value
        key = (display_num, 'blue_gain')
        if self._pending_commands.get(key):
            return
        
        self._pending_commands[key] = True
        
        def _send():
            try:
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if ddc:
                    latest = self._latest_blue_gain.get(display_num, value)
                    ddc.set_blue_gain(latest)
            finally:
                self._pending_commands[key] = False
        
        threading.Thread(target=_send, daemon=True).start()
    
    def _on_vcp_change(self, vcp_code: int, value: int):
        """Handle generic VCP change from overlay (async to keep GUI responsive)."""
        threading.Thread(target=self.ddc.set_vcp, args=(vcp_code, value), daemon=True).start()
    
    def _on_refresh_values(self, display_num: int = None):
        """Handle refresh button click - read current DDC values for a monitor."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        def refresh():
            try:
                # Get DDC controller for this display
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if not ddc:
                    logger.warning(f"No DDC controller for display {display_num}")
                    return
                
                logger.info(f"Refreshing DDC values for display {display_num}...")
                settings = ddc.get_all_settings()
                logger.info(f"DDC values for display {display_num}: brightness={settings.get('brightness')}, contrast={settings.get('contrast')}")
                
                if self.overlay:
                    self.overlay.set_brightness(settings.get('brightness', 50), display_num=display_num)
                    self.overlay.set_contrast(settings.get('contrast', 50), display_num=display_num)
                    
                    mon_cfg = self.monitor_configs.get(display_num, self.monitor_config)
                    mode = settings.get('color_preset', 0)
                    mode_name = mon_cfg.get_color_mode_name(mode) if mon_cfg else f"Mode {mode}"
                    self.overlay.set_color_mode(mode, mode_name, display_num=display_num)
                    
                    self.overlay.set_red_gain(settings.get('red_gain', 100), display_num=display_num)
                    self.overlay.set_green_gain(settings.get('green_gain', 100), display_num=display_num)
                    self.overlay.set_blue_gain(settings.get('blue_gain', 100), display_num=display_num)
                    
                    logger.info(f"GUI updated with refreshed values for display {display_num}")
            except Exception as e:
                logger.warning(f"Could not refresh values for display {display_num}: {e}")
        
        threading.Thread(target=refresh, daemon=True).start()
    
    def _on_refresh_basic_values(self, display_num: int = None):
        """Handle refresh button click - read basic DDC values (brightness/contrast/sharpness)."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        def refresh():
            try:
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if not ddc:
                    logger.warning(f"No DDC controller for display {display_num}")
                    return
                
                logger.info(f"Refreshing basic DDC values for display {display_num}...")
                brightness = ddc.get_brightness()
                contrast = ddc.get_contrast()
                sharpness = ddc.get_sharpness()
                
                if self.overlay:
                    if brightness is not None:
                        self.overlay.set_brightness(brightness, display_num=display_num)
                    if contrast is not None:
                        self.overlay.set_contrast(contrast, display_num=display_num)
                    if sharpness is not None:
                        self.overlay.set_sharpness(sharpness, display_num=display_num)
                    
                    logger.info(f"Basic values refreshed: brightness={brightness}, contrast={contrast}, sharpness={sharpness}")
            except Exception as e:
                logger.warning(f"Could not refresh basic values for display {display_num}: {e}")
        
        threading.Thread(target=refresh, daemon=True).start()
    
    def _on_refresh_rgb_values(self, display_num: int = None):
        """Handle refresh button click - read RGB gain DDC values."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        def refresh():
            try:
                ddc = self.ddc_controllers.get(display_num, self.ddc)
                if not ddc:
                    logger.warning(f"No DDC controller for display {display_num}")
                    return
                
                logger.info(f"Refreshing RGB DDC values for display {display_num}...")
                red = ddc.get_red_gain()
                green = ddc.get_green_gain()
                blue = ddc.get_blue_gain()
                
                if self.overlay:
                    if red is not None:
                        self.overlay.set_red_gain(red, display_num=display_num)
                    if green is not None:
                        self.overlay.set_green_gain(green, display_num=display_num)
                    if blue is not None:
                        self.overlay.set_blue_gain(blue, display_num=display_num)
                    
                    logger.info(f"RGB values refreshed: red={red}, green={green}, blue={blue}")
            except Exception as e:
                logger.warning(f"Could not refresh RGB values for display {display_num}: {e}")
        
        threading.Thread(target=refresh, daemon=True).start()
    
    def _on_color_mode_names_changed(self, display_num: int, new_modes: dict):
        """Handle color mode names change from the edit dialog."""
        logger.info(f"Color mode names changed for display {display_num}: {list(new_modes.keys())}")
        
        # Get monitor config for this display
        mon_config = self.monitor_configs.get(display_num, self.monitor_config)
        if mon_config:
            # Update the color modes in the config
            mon_config.color_modes = new_modes
            mon_config.save()
            logger.info(f"Saved renamed color modes to config for display {display_num}")
            
            # Update profile dropdowns with new names
            if self.overlay:
                profile_color_modes = self._get_profile_color_modes(mon_config)
                self.overlay.set_profile_color_modes(profile_color_modes, display_num=display_num)
    
    def _on_toggle_auto_brightness(self, enabled: bool, display_num: int = None):
        """Handle auto brightness toggle from overview - sets ALL profiles for this monitor."""
        # Use specified display or current
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        logger.info(f"Toggle auto brightness (ALL profiles): enabled={enabled}, display={display_num}")
        
        # Get or create ProfileManager for this display
        pm = self._get_or_create_profile_manager(display_num)
        pm.set_auto_brightness_enabled(enabled, save_to_profile=False)  # Don't save to single profile
        
        # Save to ALL profiles in config (including default)
        for profile in self.config.profiles:
            self.config.save_profile_auto_settings(profile.name, auto_brightness=enabled)
        # Also save to default profile
        self.config.save_profile_auto_settings("default", auto_brightness=enabled)
        
        # Also update current monitor config
        mon_cfg = self.monitor_configs.get(display_num, self.monitor_config)
        if mon_cfg:
            mon_cfg.auto_brightness = enabled
            mon_cfg.save()
        
        # Update GUI - both overview and all profile switches
        if self.overlay:
            self.overlay.set_auto_brightness_state(enabled, display_num=display_num)
            self.overlay.set_all_profiles_auto_brightness(enabled, display_num=display_num)
            if hasattr(self.overlay, 'update_overview_auto_states'):
                self.overlay.update_overview_auto_states(display_num, auto_brightness=enabled)
    
    def _on_toggle_auto_contrast(self, enabled: bool, display_num: int = None):
        """Handle auto contrast toggle from overview - sets ALL profiles for this monitor."""
        # Use specified display or current
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        logger.info(f"Toggle auto contrast (ALL profiles): enabled={enabled}, display={display_num}")
        
        # Get or create ProfileManager for this display
        pm = self._get_or_create_profile_manager(display_num)
        pm.set_auto_contrast_enabled(enabled, save_to_profile=False)  # Don't save to single profile
        
        # Save to ALL profiles in config (including default)
        for profile in self.config.profiles:
            self.config.save_profile_auto_settings(profile.name, auto_contrast=enabled)
        # Also save to default profile
        self.config.save_profile_auto_settings("default", auto_contrast=enabled)
        
        # Also update current monitor config
        mon_cfg = self.monitor_configs.get(display_num, self.monitor_config)
        if mon_cfg:
            mon_cfg.auto_contrast = enabled
            mon_cfg.save()
        
        # Update GUI - both overview and all profile switches
        if self.overlay:
            self.overlay.set_auto_contrast_state(enabled, display_num=display_num)
            self.overlay.set_all_profiles_auto_contrast(enabled, display_num=display_num)
            if hasattr(self.overlay, 'update_overview_auto_states'):
                self.overlay.update_overview_auto_states(display_num, auto_contrast=enabled)
    
    def _on_profile_auto_brightness_toggle(self, profile_name: str, enabled: bool, display_num: int = None):
        """Handle auto brightness toggle for a specific profile."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        logger.info(f"Toggle auto brightness for profile '{profile_name}': enabled={enabled}")
        
        # Save to this specific profile
        self.config.save_profile_auto_settings(profile_name, auto_brightness=enabled)
        
        # If this is the current active profile, update the ProfileManager
        pm = self._get_or_create_profile_manager(display_num)
        if pm._active_profile and pm._active_profile.name == profile_name:
            pm.set_auto_brightness_enabled(enabled, save_to_profile=False)
    
    def _on_profile_auto_contrast_toggle(self, profile_name: str, enabled: bool, display_num: int = None):
        """Handle auto contrast toggle for a specific profile."""
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        logger.info(f"Toggle auto contrast for profile '{profile_name}': enabled={enabled}")
        
        # Save to this specific profile
        self.config.save_profile_auto_settings(profile_name, auto_contrast=enabled)
        
        # If this is the current active profile, update the ProfileManager
        pm = self._get_or_create_profile_manager(display_num)
        if pm._active_profile and pm._active_profile.name == profile_name:
            pm.set_auto_contrast_enabled(enabled, save_to_profile=False)
    
    def _on_adaptive_setting_change(self, setting: str, value, display_num: int = None):
        """Handle adaptive brightness/contrast setting change from overlay."""
        # Use specified display or current
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        # Get profile manager and config for the specified display
        pm = self._get_or_create_profile_manager(display_num)
        analyzer = pm.screen_analyzer
        monitor_config = self.monitor_configs.get(display_num, self.monitor_config)
        
        # Update analyzer settings
        if setting == 'min_contrast':
            analyzer.min_contrast = value
        elif setting == 'max_contrast':
            analyzer.max_contrast = value
        elif setting == 'min_brightness':
            analyzer.min_brightness = value
        elif setting == 'max_brightness':
            analyzer.max_brightness = value
        elif setting == 'dark_threshold':
            analyzer.dark_threshold = value
        elif setting == 'bright_threshold':
            analyzer.bright_threshold = value
        elif setting == 'smoothing':
            analyzer.smoothing = value
        elif setting == 'interval':
            # Restart screen analyzer with new interval if running
            if pm.is_auto_brightness_enabled() or pm.is_auto_contrast_enabled():
                analyzer.stop_monitoring()
                analyzer.start_monitoring(
                    pm._on_screen_analysis,
                    interval=value
                )
        
        logger.info(f"Adaptive {setting} set to {value} for display {display_num}")
        
        # Save to monitor config
        if monitor_config:
            monitor_config.adaptive_settings[setting] = value
            threading.Thread(target=monitor_config.save, daemon=True).start()
    
    def _on_toggle_auto_profile(self, enabled: bool, display_num: int = None):
        """Handle auto profile toggle from overlay."""
        # Use specified display or current
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        logger.info(f"Toggle auto profile: enabled={enabled}, display={display_num}")
        
        # Get or create ProfileManager for this display
        pm = self._get_or_create_profile_manager(display_num)
        pm.set_auto_profile_enabled(enabled)
        logger.info(f"Auto profile {'enabled' if enabled else 'disabled'} for display {display_num}")
        
        # Save to monitor config for this display
        mon_cfg = self.monitor_configs.get(display_num, self.monitor_config)
        if mon_cfg:
            mon_cfg.auto_profile = enabled
            mon_cfg.save()
        
        # Update both tab and overview button states
        if self.overlay:
            self.overlay.set_auto_profile_state(enabled, display_num=display_num)
            if hasattr(self.overlay, 'update_overview_auto_states'):
                self.overlay.update_overview_auto_states(display_num, auto_profile=enabled)
    
    def _on_fullscreen_only_toggle(self, enabled: bool, display_num: int = None):
        """Handle fullscreen only toggle from overlay."""
        # Use specified display or current
        if display_num is None:
            display_num = self.ddc.display if self.ddc else 1
        
        logger.info(f"Fullscreen only: enabled={enabled}, display={display_num}")
        
        # Get or create ProfileManager for this display
        pm = self._get_or_create_profile_manager(display_num)
        pm.set_fullscreen_only(enabled)
        
        # Save to monitor config for this display
        mon_cfg = self.monitor_configs.get(display_num, self.monitor_config)
        if mon_cfg:
            mon_cfg.fullscreen_only = enabled
            mon_cfg.save()
    
    def _on_profile_select(self, profile_name: str, display_num: int = None):
        """Handle profile selection from overlay for a specific monitor."""
        # Use the specific display's ProfileManager, or fall back to current
        if display_num and display_num in self.profile_managers:
            pm = self.profile_managers[display_num]
        else:
            pm = self.profile_manager
        pm.set_profile(profile_name)
    
    def _on_profile_mode_change(self, profile_name: str, color_mode_name: str, display_num: int = None):
        """Handle profile color mode change from overlay - saves to monitor-specific config and applies if active (async)."""
        # Use the specific display's config and DDC controller, or fall back to current
        if display_num and display_num in self.monitor_configs:
            mon_config = self.monitor_configs[display_num]
            ddc = self.ddc_controllers.get(display_num, self.ddc)
            pm = self.profile_managers.get(display_num)
        else:
            mon_config = self.monitor_config
            ddc = self.ddc
            pm = self.profile_manager
        
        def _save_and_update():
            if mon_config:
                # Get color mode value from name
                color_value = mon_config.get_color_mode_value(color_mode_name)
                if color_value is not None:
                    # Determine if this is a 0xDC or 0x14 value and save ONLY the changed one
                    # (Don't auto-capture the other value - that causes unwanted double changes)
                    if color_value >= 0x1000:
                        # This is a 0x14 color preset - save it separately
                        actual_preset = color_value - 0x1000
                        mon_config.set_profile_color_preset(profile_name, actual_preset)
                        logger.info(f"Saved profile '{profile_name}' color preset (0x14): {actual_preset}")
                    else:
                        # This is a 0xDC display mode
                        mon_config.set_profile_color_mode(profile_name, color_value)
                        logger.info(f"Saved profile '{profile_name}' display mode (0xDC): {color_value}")
                    
                    mon_config.save()
                    logger.info(f"Saved profile '{profile_name}' color settings for display {display_num or 'current'}")
                    
                    # If this is the currently active profile, apply the new color mode immediately
                    if pm:
                        active_profile = pm.get_active_profile()
                        active_name = active_profile.name if active_profile else "default"
                        if active_name == profile_name:
                            logger.info(f"'{profile_name}' is the active profile - applying new color mode to monitor")
                            if active_profile:
                                pm._apply_profile(active_profile, force=True)
                            else:
                                # Default profile - apply using default profile settings
                                pm._apply_profile(self.config.default_profile, force=True)
                else:
                    logger.warning(f"Unknown color mode: {color_mode_name}")
            else:
                logger.warning("No monitor config available, cannot save profile color mode")
        # Run config save in background to not block GUI
        threading.Thread(target=_save_and_update, daemon=True).start()
    
    def _on_add_app_to_profile(self, profile_name: str, window_class: str):
        """Handle adding current app to a profile's match list (saves to global config)."""
        def _save():
            success, message = self.config.add_app_to_profile(profile_name, window_class)
            if success:
                if message == "already_present":
                    logger.info(f"App '{window_class}' already in profile '{profile_name}'")
                elif message.startswith("moved_from:"):
                    old_profile = message.split(":")[1]
                    logger.info(f"Moved '{window_class}' from '{old_profile}' to '{profile_name}'")
                else:
                    logger.info(f"Added '{window_class}' to profile '{profile_name}'")
            else:
                logger.error(f"Failed to add '{window_class}' to profile '{profile_name}': {message}")
        # Run config save in background to not block GUI
        threading.Thread(target=_save, daemon=True).start()
    
    def _setup_ddc_busy_callback(self, ddc, display_num: int):
        """Set up DDC busy callback to update overview indicator.
        
        Args:
            ddc: DDCController instance
            display_num: Display number for this controller
        """
        def busy_callback(busy: bool, command: str = None):
            if self.overlay and hasattr(self.overlay, 'set_ddc_busy'):
                self.overlay.set_ddc_busy(display_num, busy, command)
        
        ddc.set_busy_callback(busy_callback)
    
    def _get_profile_color_modes(self, monitor_config=None) -> dict:
        """Get a mapping of profile names to their color mode names.
        
        Uses monitor-specific profile color modes if available,
        falls back to global config otherwise.
        """
        result = {}
        mc = monitor_config or self.monitor_config
        
        # Get all profile names
        profile_names = ["default"] + [p.name for p in self.config.profiles]
        
        for profile_name in profile_names:
            # First try monitor-specific color mode
            if mc and profile_name in mc.profile_color_modes:
                value = mc.profile_color_modes[profile_name]
                mode_name = mc.get_color_mode_name(value)
                result[profile_name] = mode_name
            else:
                # Fall back to global config
                if profile_name == "default":
                    if self.config.default_profile.settings.color_preset is not None:
                        mode_name = self.config.get_color_mode_name(self.config.default_profile.settings.color_preset)
                        result[profile_name] = mode_name
                else:
                    for profile in self.config.profiles:
                        if profile.name == profile_name and profile.settings.color_preset is not None:
                            mode_name = self.config.get_color_mode_name(profile.settings.color_preset)
                            result[profile_name] = mode_name
                            break
        
        return result
    
    def _on_quit(self):
        """Handle quit request from GUI."""
        # Just set the flag - the main run() loop will call stop()
        self._running = False
    
    def _on_window_change(self, window):
        """Handle window focus change notification (legacy)."""
        display = self.ddc.display if self.ddc else 1
        self._on_window_change_for_display(window, display)
    
    def _on_window_change_for_display(self, window, display_num: int):
        """Handle window focus change notification for a specific display."""
        if self.overlay and window:
            # Only update when the active window IS on this display
            # When window=None (active window is on another display), keep showing last known app
            logger.info(f"GUI update: display {display_num} ← '{window.title[:40] if window.title else ''}'")
            self.overlay.set_current_app(
                app_title=window.title or "",
                app_class=window.window_class or "",
                display_num=display_num
            )
            # Update overview
            if hasattr(self.overlay, 'update_overview_current_app'):
                self.overlay.update_overview_current_app(
                    display_num,
                    app_name=window.title or "--",
                    app_class=window.window_class
                )
    
    def _on_profile_change(self, profile):
        """Handle profile change notification (legacy)."""
        display = self.ddc.display if self.ddc else 1
        self._on_profile_change_for_display(profile, display)
    
    def _on_profile_change_for_display(self, profile, display_num: int):
        """Handle profile change notification for a specific display."""
        if not self.overlay:
            return
            
        self.overlay.set_current_profile(profile.name, display_num=display_num)
        # Also update the overview profile display
        self.overlay.update_overview_profile(display_num, profile.name)
        
        # Get the profile manager for this display
        pm = self.profile_managers.get(display_num, self.profile_manager)
        
        # Update auto brightness/contrast toggle states in GUI
        auto_brightness = pm.is_auto_brightness_enabled()
        auto_contrast = pm.is_auto_contrast_enabled()
        self.overlay.set_auto_brightness_state(auto_brightness, display_num=display_num)
        self.overlay.set_auto_contrast_state(auto_contrast, display_num=display_num)
        # Also update overview auto buttons
        if hasattr(self.overlay, 'update_overview_auto_states'):
            self.overlay.update_overview_auto_states(
                display_num,
                auto_brightness=auto_brightness,
                auto_contrast=auto_contrast
            )
        
        # Update color mode in GUI based on what the profile set (no DDC read needed)
        # The profile manager already applied the color mode, we just need to update the GUI
        mc = self.monitor_configs.get(display_num)
        if mc:
            color_value = mc.get_profile_color_mode(profile.name)
            if color_value is not None:
                mode_name = mc.get_color_mode_name(color_value)
                self.overlay.set_color_mode(color_value, mode_name, display_num=display_num)
    
    def _on_settings_change(self, settings: dict):
        """Handle settings change notification (legacy, no display_num)."""
        # Forward to display-specific handler using current display
        display = self.ddc.display if self.ddc else 1
        self._on_settings_change_for_display(settings, display)
    
    def _on_settings_change_for_display(self, settings: dict, display_num: int):
        """Handle settings change notification for a specific display."""
        if self.overlay:
            if 'brightness' in settings:
                self.overlay.set_brightness(settings['brightness'], display_num=display_num)
            if 'contrast' in settings:
                self.overlay.set_contrast(settings['contrast'], display_num=display_num)
            
            # Update overview with brightness/contrast
            if hasattr(self.overlay, 'update_overview_settings'):
                self.overlay.update_overview_settings(
                    display_num,
                    brightness=settings.get('brightness'),
                    contrast=settings.get('contrast')
                )
            
            # Update overview with screen analysis
            if 'screen_analysis' in settings and hasattr(self.overlay, 'update_overview_screen_analysis'):
                analysis = settings['screen_analysis']
                self.overlay.update_overview_screen_analysis(
                    display_num,
                    mean=analysis['mean'],
                    dark_pct=analysis['dark_ratio'],
                    bright_pct=analysis['bright_ratio']
                )
    
    def stop(self):
        """Stop the application."""
        # Guard against double-stop
        if hasattr(self, '_stopped') and self._stopped:
            return
        self._stopped = True
        
        logger.info("Stopping Monitor Control...")
        self._running = False
        
        # Stop ALL profile managers (one per monitor)
        for display_num, pm in self.profile_managers.items():
            try:
                pm.stop()
                logger.debug(f"Stopped ProfileManager for display {display_num}")
            except Exception as e:
                logger.warning(f"Error stopping profile manager for display {display_num}: {e}")
        
        # Stop GUI last
        if self.overlay:
            try:
                self.overlay.stop()
            except Exception as e:
                logger.warning(f"Error stopping overlay: {e}")
        
        logger.info("Monitor Control stopped")
    
    def run(self):
        """Run the application (blocking)."""
        if not self.start():
            return 1
        
        # Set up signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            self._running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Main loop - poll frequently so we respond quickly to quit
        import time
        try:
            while self._running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        
        self.stop()
        return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor Control - DDC/CI based monitor management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--config', '-c',
        type=Path,
        help='Path to configuration file'
    )
    parser.add_argument(
        '--no-gui',
        action='store_true',
        help='Run without GUI (daemon mode)'
    )
    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug logging'
    )
    parser.add_argument(
        '--detect',
        action='store_true',
        help='Detect monitors and exit'
    )
    parser.add_argument(
        '--capabilities',
        action='store_true',
        help='Show monitor capabilities and exit'
    )
    parser.add_argument(
        '--display',
        type=int,
        help='Display number for --capabilities'
    )
    
    # Debug/testing options
    parser.add_argument(
        '--skip-ddc',
        action='store_true',
        help='Skip DDC readings at startup (for faster debugging)'
    )
    
    # Quick commands
    parser.add_argument(
        '--brightness', '-b',
        type=int,
        metavar='VALUE',
        help='Set brightness (0-100) and exit'
    )
    parser.add_argument(
        '--contrast',
        type=int,
        metavar='VALUE',
        help='Set contrast (0-100) and exit'
    )
    parser.add_argument(
        '--mode', '-m',
        type=str,
        metavar='NAME',
        help='Set color mode by name and exit'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_file = None
    if not args.detect and not args.capabilities:
        log_file = Path.home() / ".local" / "share" / "monitor-control" / "monitor-control.log"
    setup_logging(args.debug, log_file)
    
    # Handle quick commands
    if args.detect:
        return detect_monitors()
    
    if args.capabilities:
        return show_capabilities(args.display)
    
    if args.brightness is not None or args.contrast is not None or args.mode:
        from monitor_control.ddc import DDCController
        from monitor_control.config import Config
        
        ddc = DDCController(display=args.display or 1)
        
        if args.brightness is not None:
            ddc.set_brightness(args.brightness)
            print(f"Brightness set to {args.brightness}")
        
        if args.contrast is not None:
            ddc.set_contrast(args.contrast)
            print(f"Contrast set to {args.contrast}")
        
        if args.mode:
            # Load config to get mode mappings
            config = Config(args.config)
            config.load()
            mode_value = config.get_color_mode_value(args.mode)
            ddc.set_color_preset(mode_value)
            print(f"Color mode set to {args.mode} ({mode_value})")
        
        return 0
    
    # Run main application
    app = MonitorControlApp(
        config_path=args.config,
        gui_enabled=not args.no_gui,
        skip_ddc=args.skip_ddc,
    )
    
    return app.run()


if __name__ == '__main__':
    sys.exit(main())

