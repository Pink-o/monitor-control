"""
Profile Manager - Match applications to profiles and apply settings
===================================================================
"""

import logging
import fnmatch
import threading
from typing import Optional, List, Callable
from dataclasses import dataclass

from .config import Config, Profile, ProfileSettings
from .ddc import DDCController, MonitorGeometry
from .window_monitor import WindowMonitor, WindowInfo
from .screen_analyzer import ScreenAnalyzer, ScreenAnalysis

logger = logging.getLogger(__name__)


@dataclass
class ProfileState:
    """Current state of profile management."""
    active_profile: Optional[Profile]
    window_info: Optional[WindowInfo]
    adaptive_enabled: bool
    last_analysis: Optional[ScreenAnalysis]
    current_brightness: int
    current_contrast: int
    current_color_preset: int


class ProfileManager:
    """
    Manages automatic profile switching based on active applications
    and adaptive settings based on screen content.
    """
    
    def __init__(
        self,
        config: Config,
        ddc: DDCController,
        window_monitor: Optional[WindowMonitor] = None,
        screen_analyzer: Optional[ScreenAnalyzer] = None,
        monitor_index: int = 1,
    ):
        """
        Initialize profile manager.
        
        Args:
            config: Application configuration
            ddc: DDC controller for the monitor
            window_monitor: Optional window monitor (will create if None)
            screen_analyzer: Optional screen analyzer (will create if None)
            monitor_index: Which monitor to capture for screen analysis (1-based)
        """
        self.config = config
        self.ddc = ddc
        self.window_monitor = window_monitor or WindowMonitor()
        
        # Monitor geometry for per-monitor profile filtering and screen analysis
        self._monitor_geometry: Optional[MonitorGeometry] = ddc.get_geometry()
        if self._monitor_geometry:
            logger.info(f"ProfileManager: Monitor geometry {self._monitor_geometry.width}x{self._monitor_geometry.height}"
                       f"+{self._monitor_geometry.x}+{self._monitor_geometry.y}")
        else:
            logger.warning("ProfileManager: Could not determine monitor geometry - profile switching will apply to all windows")
        
        # Convert geometry to region tuple for screen analyzer
        monitor_region = None
        if self._monitor_geometry:
            monitor_region = (
                self._monitor_geometry.x,
                self._monitor_geometry.y,
                self._monitor_geometry.width,
                self._monitor_geometry.height
            )
        
        # Create screen analyzer with config settings and monitor region
        if screen_analyzer:
            self.screen_analyzer = screen_analyzer
        else:
            ac = config.adaptive_contrast
            self.screen_analyzer = ScreenAnalyzer(
                dark_threshold=ac.dark_threshold,
                bright_threshold=ac.bright_threshold,
                min_contrast=ac.min_contrast,
                max_contrast=ac.max_contrast,
                min_brightness=ac.min_brightness,
                max_brightness=ac.max_brightness,
                smoothing=ac.smoothing,
                monitor_index=monitor_index,
                monitor_region=monitor_region,  # Use precise geometry for capture
            )
        
        # State tracking
        self._active_profile: Optional[Profile] = None
        self._current_window: Optional[WindowInfo] = None
        self._last_analysis: Optional[ScreenAnalysis] = None
        self._auto_brightness_enabled = False  # Default OFF
        self._auto_contrast_enabled = False    # Default OFF
        self._auto_profile_enabled = config.auto_profile_enabled  # Load from config
        self._fullscreen_only = False  # Only switch profiles when app is fullscreen
        self._running = False
        
        # Whether this ProfileManager should update the GUI (only one at a time)
        self._is_gui_active = True  # Set to False when another monitor is selected
        
        # Cache last sent values to avoid redundant DDC commands
        self._last_sent_brightness: Optional[int] = None
        self._last_sent_contrast: Optional[int] = None
        
        # Callbacks for UI updates
        self._profile_change_callbacks: List[Callable[[Profile], None]] = []
        self._settings_change_callbacks: List[Callable[[dict], None]] = []
        self._window_change_callbacks: List[Callable[[WindowInfo], None]] = []
        
        # Callbacks to get profile color settings from monitor-specific config
        self._get_profile_color_mode_callback: Optional[Callable[[str], Optional[int]]] = None
        self._get_profile_color_preset_callback: Optional[Callable[[str], Optional[int]]] = None
        
    def start(self):
        """Start profile management and monitoring."""
        if self._running:
            return
            
        self._running = True
        
        # Start window monitoring
        self.window_monitor.start_monitoring(self._on_window_change)
        
        # Screen analysis always runs (for gauge updates), auto modes control actual changes
        # Will be started by _update_screen_monitoring after startup is complete
        
        # Apply default profile initially
        self._apply_profile(self.config.default_profile)
        
        logger.info("Profile manager started")
    
    def stop(self):
        """Stop profile management."""
        self._running = False
        self.window_monitor.stop_monitoring()
        self.screen_analyzer.stop_monitoring()
        logger.info("Profile manager stopped")
    
    def refresh_geometry(self):
        """
        Refresh monitor geometry from DDC/xrandr.
        
        Call this after display configuration changes (resolution, scaling, arrangement).
        Updates both profile manager and screen analyzer regions.
        """
        new_geometry = self.ddc.refresh_geometry()
        self._monitor_geometry = new_geometry
        
        if new_geometry:
            logger.info(f"ProfileManager: Refreshed geometry to {new_geometry.width}x{new_geometry.height}"
                       f"+{new_geometry.x}+{new_geometry.y}")
            # Update screen analyzer region
            self.screen_analyzer.monitor_region = (
                new_geometry.x,
                new_geometry.y,
                new_geometry.width,
                new_geometry.height
            )
        else:
            logger.warning("ProfileManager: Could not refresh geometry")
            self.screen_analyzer.monitor_region = None
    
    def switch_monitor(self, new_ddc: 'DDCController'):
        """
        Switch to controlling a different monitor.
        
        Updates the DDC controller and refreshes geometry for the new monitor.
        Also restarts screen analysis if it was running.
        
        Args:
            new_ddc: DDCController for the new monitor to control
        """
        was_analyzing = self.screen_analyzer._running
        
        # Stop screen analysis during switch
        if was_analyzing:
            self.screen_analyzer.stop_monitoring()
        
        # Update DDC controller
        self.ddc = new_ddc
        logger.info(f"ProfileManager: Switched to monitor {new_ddc.display}")
        
        # Refresh geometry for the new monitor
        self._monitor_geometry = new_ddc.get_geometry(refresh=True)
        
        if self._monitor_geometry:
            logger.info(f"ProfileManager: New monitor geometry {self._monitor_geometry.width}x{self._monitor_geometry.height}"
                       f"+{self._monitor_geometry.x}+{self._monitor_geometry.y}")
            # Update screen analyzer region
            self.screen_analyzer.monitor_region = (
                self._monitor_geometry.x,
                self._monitor_geometry.y,
                self._monitor_geometry.width,
                self._monitor_geometry.height
            )
        else:
            logger.warning(f"ProfileManager: Could not get geometry for monitor {new_ddc.display}")
            self.screen_analyzer.monitor_region = None
        
        # Restart screen analysis if it was running
        if was_analyzing and (self._auto_brightness_enabled or self._auto_contrast_enabled):
            interval = self.config.adaptive_contrast.interval
            self.screen_analyzer.start_monitoring(self._on_screen_analysis, interval)
            logger.info(f"ProfileManager: Restarted screen analysis for monitor {new_ddc.display}")
    
    def _is_window_on_this_monitor(self, window: WindowInfo) -> bool:
        """
        Check if a window is on this monitor (based on geometry).
        
        Args:
            window: Window information with geometry
            
        Returns:
            True if window is on this monitor, or if we can't determine (no geometry)
        """
        # If we don't have monitor geometry, assume window is on our monitor
        if self._monitor_geometry is None:
            logger.info(f"Monitor {self.ddc.display}: No geometry set, defaulting to True")
            return True
            
        # Check if window geometry is valid
        if window.geometry == (0, 0, 0, 0):
            # No valid geometry - return False to avoid false positives
            # Only the first monitor should claim windows with no geometry
            is_first_monitor = self.ddc.display == 1
            if is_first_monitor:
                logger.debug(f"Monitor {self.ddc.display}: Window has no geometry, claiming as first monitor")
            return is_first_monitor
            
        wx, wy, ww, wh = window.geometry
        window_center_x = wx + ww // 2
        window_center_y = wy + wh // 2
        
        mon = self._monitor_geometry
        is_on = mon.contains_window(wx, wy, ww, wh)
        
        # Log result for debugging
        if is_on:
            logger.info(f"Monitor {self.ddc.display}: Window '{window.title[:40]}' "
                       f"at ({wx},{wy}) center=({window_center_x},{window_center_y}) is ON this monitor "
                       f"(bounds: {mon.x}-{mon.x + mon.width}, {mon.y}-{mon.y + mon.height})")
        else:
            logger.debug(f"Monitor {self.ddc.display}: Window at center ({window_center_x},{window_center_y}) "
                        f"NOT on this monitor (bounds: {mon.x}-{mon.x + mon.width}, {mon.y}-{mon.y + mon.height})")
        
        return is_on
    
    def _on_window_change(self, window: WindowInfo):
        """Handle window focus change."""
        self._current_window = window
        
        # Log window geometry once (only from first monitor to reduce spam)
        if self.ddc.display == 1 and window:
            logger.info(f"Active window: '{window.title[:50]}' geometry={window.geometry} fullscreen={window.is_fullscreen} maximized={window.is_maximized}")
        
        # Check if window is on this monitor (for GUI display and profile matching)
        is_on_this_monitor = self._is_window_on_this_monitor(window)
        
        # Notify GUI of window change for this monitor
        # If the window is NOT on this monitor, send None (don't update)
        window_to_report = window if is_on_this_monitor else None
        
        # Log what we're sending to callbacks
        if window_to_report:
            logger.info(f"ProfileManager {self.ddc.display}: Sending window to {len(self._window_change_callbacks)} callbacks")
        
        for callback in self._window_change_callbacks:
            try:
                callback(window_to_report)
            except Exception as e:
                logger.error(f"Window change callback error: {e}")
        
        # Skip profile switching if disabled
        if not self._auto_profile_enabled:
            return
        
        # Skip if this is the monitor-control window (keep current profile)
        if window and (
            window.window_class and 'monitor-control' in window.window_class.lower() or
            window.title and 'Monitor Control' in window.title
        ):
            logger.debug(f"Skipping profile switch for monitor-control window")
            return
        
        # Skip if window is not on this monitor
        if not is_on_this_monitor:
            logger.debug(f"Window '{window.title}' is not on this monitor, skipping profile switch")
            return
        
        # Skip if fullscreen only mode is enabled and window is not fullscreen/maximized
        if self._fullscreen_only:
            is_full = window.is_fullscreen or window.is_maximized
            if not is_full:
                logger.info(f"Fullscreen only: skipping '{window.title[:30]}' (not fullscreen/maximized)")
                return
            else:
                state = "fullscreen" if window.is_fullscreen else "maximized"
                logger.info(f"Fullscreen only: window '{window.title[:30]}' IS {state}, will check profile")
        
        # Find matching profile
        matched_profile = self._find_matching_profile(window)
        
        if matched_profile != self._active_profile:
            self._apply_profile(matched_profile)
    
    def _on_screen_analysis(self, analysis: ScreenAnalysis):
        """Handle screen analysis results."""
        self._last_analysis = analysis
        
        logger.debug(f"Screen: mean={analysis.mean_brightness:.2f}, dark={analysis.dark_ratio:.0%}, bright={analysis.bright_ratio:.0%} "
                    f"→ suggest b={analysis.suggested_brightness}, c={analysis.suggested_contrast}")
        
        # Note: Per-profile auto_brightness/auto_contrast settings now control whether
        # auto adjustment is active for each profile. The old respect_profiles check
        # is no longer needed.
        
        settings_changed = {}
        
        # Apply auto brightness if enabled AND value changed (async to not block)
        logger.debug(f"_on_screen_analysis: auto_brightness={self._auto_brightness_enabled}, auto_contrast={self._auto_contrast_enabled}")
        if self._auto_brightness_enabled:
            new_brightness = analysis.suggested_brightness
            logger.info(f"Auto brightness check: new={new_brightness}, last={self._last_sent_brightness}")
            if new_brightness != self._last_sent_brightness:
                self._last_sent_brightness = new_brightness
                settings_changed['brightness'] = new_brightness
                # Run DDC command in background thread
                threading.Thread(
                    target=self.ddc.set_brightness,
                    args=(new_brightness,),
                    daemon=True
                ).start()
                logger.info(f"Auto brightness → {new_brightness}")
        
        # Apply auto contrast if enabled AND value changed (async to not block)
        if self._auto_contrast_enabled:
            new_contrast = analysis.suggested_contrast
            logger.debug(f"Auto contrast check: new={new_contrast}, last={self._last_sent_contrast}")
            if new_contrast != self._last_sent_contrast:
                self._last_sent_contrast = new_contrast
                settings_changed['contrast'] = new_contrast
                # Run DDC command in background thread
                threading.Thread(
                    target=self.ddc.set_contrast,
                    args=(new_contrast,),
                    daemon=True
                ).start()
                logger.info(f"Auto contrast → {new_contrast}")
        
        # Always add screen analysis data for overview updates
        settings_changed['screen_analysis'] = {
            'mean': analysis.mean_brightness,
            'dark_ratio': analysis.dark_ratio,
            'bright_ratio': analysis.bright_ratio,
        }
        
        # Notify callbacks (always notify for screen analysis even if brightness/contrast unchanged)
        # Only notify GUI callbacks if this ProfileManager is the active one for GUI
        if self._is_gui_active:
            logger.debug(f"Screen brightness: {analysis.mean_brightness:.2f}")
            for callback in self._settings_change_callbacks:
                try:
                    callback(settings_changed)
                except Exception as e:
                    logger.error(f"Settings callback error: {e}")
    
    def _find_matching_profile(self, window: WindowInfo) -> Profile:
        """
        Find the best matching profile for a window.
        
        Args:
            window: Window information to match
            
        Returns:
            Matching profile or default profile
        """
        # Note: fullscreen_only is now a global setting (per-monitor), checked in _on_window_change
        # Profile-specific require_fullscreen is deprecated
        for profile in self.config.profiles:
            # Check window class patterns
            for pattern in profile.match.window_class:
                if window.matches_pattern(pattern):
                    logger.debug(f"Window class '{window.window_class}' matched "
                               f"pattern '{pattern}' for profile '{profile.name}'")
                    return profile
            
            # Check window title patterns
            for pattern in profile.match.window_title:
                if fnmatch.fnmatch(window.title.lower(), pattern.lower()):
                    logger.debug(f"Window title '{window.title}' matched "
                               f"pattern '{pattern}' for profile '{profile.name}'")
                    return profile
        
        return self.config.default_profile
    
    def _apply_profile(self, profile: Profile, force: bool = False):
        """
        Apply a profile's settings to the monitor.
        
        Only applies color_preset (color mode) - brightness and contrast
        are left unchanged to preserve user's manual adjustments.
        
        Also applies per-profile auto brightness/contrast settings.
        User can modify these via GUI, and changes are saved back to the profile.
        
        Args:
            profile: Profile to apply
            force: If True, apply even if profile is already active (for manual color mode changes)
        """
        if profile == self._active_profile and not force:
            return
            
        logger.info(f"Switching to profile: {profile.name}")
        
        # Apply per-profile auto brightness/contrast settings
        # User can modify these via GUI and they'll be saved back to the profile
        auto_settings_changed = False
        
        if profile.auto_brightness is not None:
            if profile.auto_brightness != self._auto_brightness_enabled:
                self._auto_brightness_enabled = profile.auto_brightness
                auto_settings_changed = True
            logger.info(f"Profile '{profile.name}': auto brightness {'ON' if profile.auto_brightness else 'OFF'}")
        
        if profile.auto_contrast is not None:
            if profile.auto_contrast != self._auto_contrast_enabled:
                self._auto_contrast_enabled = profile.auto_contrast
                auto_settings_changed = True
            logger.info(f"Profile '{profile.name}': auto contrast {'ON' if profile.auto_contrast else 'OFF'}")
        
        # Update screen monitoring if auto settings changed
        if auto_settings_changed:
            self._update_screen_monitoring()
        
        # Notify callbacks IMMEDIATELY (before slow DDC command)
        # This ensures the GUI updates right away
        if self._is_gui_active:
            for callback in self._profile_change_callbacks:
                try:
                    callback(profile)
                except Exception as e:
                    logger.error(f"Profile callback error: {e}")
        
        # NOW apply color_preset (this is the slow DDC command)
        # This preserves the user's manual brightness/contrast settings
        
        # Get color mode from monitor-specific config if available
        # Get color mode from profile - this may be a combined value (0xDC raw or 0x14+0x1000)
        combined_color_value = None
        if self._get_profile_color_mode_callback:
            combined_color_value = self._get_profile_color_mode_callback(profile.name)
            logger.debug(f"Profile '{profile.name}' per-monitor color mode: {combined_color_value}")
        
        # Fall back to profile's global setting
        if combined_color_value is None:
            combined_color_value = profile.settings.color_preset
            logger.debug(f"Profile '{profile.name}' fallback to global color_preset: {combined_color_value}")
        
        # Get separately stored color preset (0x14) for this profile (for dual-code monitors)
        separate_color_preset = None
        if self._get_profile_color_preset_callback:
            separate_color_preset = self._get_profile_color_preset_callback(profile.name)
            if separate_color_preset is not None:
                logger.debug(f"Profile '{profile.name}' separate color preset (0x14): {separate_color_preset}")
        
        # Determine what to apply:
        # - If combined_color_value >= 0x1000, it's a 0x14 value (subtract 0x1000)
        # - If combined_color_value < 0x1000, it's a 0xDC value
        # - separate_color_preset is always a raw 0x14 value
        
        display_mode_value = None  # 0xDC
        color_preset_value = None   # 0x14
        
        if combined_color_value is not None:
            if combined_color_value >= 0x1000:
                # This is a 0x14 color preset (with offset)
                color_preset_value = combined_color_value - 0x1000
                logger.debug(f"Combined value {combined_color_value} is 0x14 preset: {color_preset_value}")
            else:
                # This is a 0xDC display mode
                display_mode_value = combined_color_value
                logger.debug(f"Combined value {combined_color_value} is 0xDC mode")
        
        # If we have a separate color preset, use it (overrides or supplements)
        if separate_color_preset is not None:
            color_preset_value = separate_color_preset
        
        # Log what we're about to apply
        logger.info(f"Profile '{profile.name}' color values: 0xDC={display_mode_value}, 0x14={color_preset_value}")
        
        # Apply color settings - check both 0xDC and 0x14, only apply what differs
        # When force=True (manual color mode change), skip cache comparison
        color_mode_applied = True  # Assume success unless we need to apply and fail
        
        # Apply Display Mode (0xDC) if configured (skip -1 placeholder)
        if display_mode_value is not None and display_mode_value >= 0:
            # Check cache to see if 0xDC needs to change (skip check if force=True)
            cached_dc = self.ddc._vcp_cache.get(0xDC)
            logger.info(f"0xDC check: cached={cached_dc}, new={display_mode_value}, force={force}")
            if force or cached_dc is None or cached_dc != display_mode_value:
                color_mode_name = self.config.get_color_mode_name(display_mode_value)
                result = self.ddc.set_vcp(0xDC, display_mode_value, noverify=True, force=True)
                if result:
                    logger.info(f"Applied Display Mode (0xDC): {display_mode_value} ({color_mode_name})")
                else:
                    logger.warning(f"Failed to apply Display Mode (0xDC) for profile '{profile.name}'")
                    color_mode_applied = False
            else:
                logger.info(f"Display Mode (0xDC) unchanged: cached={cached_dc}, new={display_mode_value}")
        elif display_mode_value == -1:
            logger.debug(f"Display Mode (0xDC) not configured for profile '{profile.name}' (placeholder)")
        
        # Apply Color Preset (0x14) if configured (skip -1 placeholder)
        if color_preset_value is not None and color_preset_value >= 0:
            # Check cache to see if 0x14 needs to change (skip check if force=True)
            cached_14 = self.ddc._vcp_cache.get(0x14)
            logger.info(f"0x14 check: cached={cached_14}, new={color_preset_value}, force={force}")
            if force or cached_14 is None or cached_14 != color_preset_value:
                result = self.ddc.set_vcp(0x14, color_preset_value, noverify=True, force=True)
                if result:
                    logger.info(f"Applied Color Preset (0x14): {color_preset_value}")
                else:
                    logger.warning(f"Failed to apply Color Preset (0x14) for profile '{profile.name}'")
            else:
                logger.debug(f"Color Preset (0x14) unchanged: {color_preset_value}")
        elif color_preset_value == -1:
            logger.debug(f"Color Preset (0x14) not configured for profile '{profile.name}' (placeholder)")
        
        # Only mark profile as active if color mode was applied (or no color mode needed)
        # This ensures we retry on the next window change if DDC failed
        if color_mode_applied:
            self._active_profile = profile
        else:
            # Keep trying - don't mark as active so next window change will retry
            logger.debug(f"Profile '{profile.name}' DDC command failed, keeping for retry")
    
    # Public API for manual control
    
    def set_profile(self, profile_name: str) -> bool:
        """
        Manually set a profile by name.
        
        Args:
            profile_name: Name of the profile to apply
            
        Returns:
            True if profile was found and applied
        """
        # Check named profiles
        for profile in self.config.profiles:
            if profile.name == profile_name:
                self._apply_profile(profile)
                return True
        
        # Check default profile
        if profile_name == "default":
            self._apply_profile(self.config.default_profile)
            return True
        
        logger.warning(f"Profile not found: {profile_name}")
        return False
    
    def set_auto_brightness_enabled(self, enabled: bool, save_to_profile: bool = True, start_monitoring: bool = True):
        """Enable or disable auto brightness.
        
        Args:
            enabled: Whether to enable auto brightness
            save_to_profile: If True, save this setting to the current profile's config
            start_monitoring: If True, start/stop screen monitoring immediately
        """
        logger.info(f"ProfileManager: set_auto_brightness_enabled({enabled}) called")
        self._auto_brightness_enabled = enabled
        
        if start_monitoring:
            self._update_screen_monitoring()
        
        # Save to current profile so it persists
        if save_to_profile and self._active_profile:
            self._active_profile.auto_brightness = enabled
            self.config.save_profile_auto_settings(self._active_profile.name, 
                                                    auto_brightness=enabled)
            logger.info(f"Saved auto_brightness={enabled} to profile '{self._active_profile.name}'")
    
    def set_auto_contrast_enabled(self, enabled: bool, save_to_profile: bool = True, start_monitoring: bool = True):
        """Enable or disable auto contrast.
        
        Args:
            enabled: Whether to enable auto contrast
            save_to_profile: If True, save this setting to the current profile's config
            start_monitoring: If True, start/stop screen monitoring immediately
        """
        self._auto_contrast_enabled = enabled
        
        if start_monitoring:
            self._update_screen_monitoring()
        
        # Save to current profile so it persists
        if save_to_profile and self._active_profile:
            self._active_profile.auto_contrast = enabled
            self.config.save_profile_auto_settings(self._active_profile.name,
                                                    auto_contrast=enabled)
            logger.info(f"Saved auto_contrast={enabled} to profile '{self._active_profile.name}'")
        logger.info(f"Auto contrast {'enabled' if enabled else 'disabled'}")
    
    def _update_screen_monitoring(self):
        """Start screen monitoring - always runs for gauge updates, auto modes control actual changes."""
        # Always run screen analysis when ProfileManager is running (for gauge updates)
        # The _on_screen_analysis method checks auto_brightness/auto_contrast before applying changes
        if self._running:
            if not self.screen_analyzer._running:
                self.screen_analyzer.start_monitoring(
                    self._on_screen_analysis,
                    interval=self.config.adaptive_contrast.interval,
                )
                logger.info("Screen analysis started (gauges always update)")
    
    def is_auto_brightness_enabled(self) -> bool:
        """Check if auto brightness is enabled."""
        return self._auto_brightness_enabled
    
    def is_auto_contrast_enabled(self) -> bool:
        """Check if auto contrast is enabled."""
        return self._auto_contrast_enabled
    
    def set_auto_profile_enabled(self, enabled: bool):
        """Enable or disable automatic profile switching."""
        self._auto_profile_enabled = enabled
        logger.info(f"Auto profile switching {'enabled' if enabled else 'disabled'}")
    
    def is_auto_profile_enabled(self) -> bool:
        """Check if automatic profile switching is enabled."""
        return self._auto_profile_enabled
    
    def set_fullscreen_only(self, enabled: bool):
        """Set whether to only switch profiles when app is in fullscreen mode."""
        self._fullscreen_only = enabled
        logger.info(f"Fullscreen only mode {'enabled' if enabled else 'disabled'}")
    
    def is_fullscreen_only(self) -> bool:
        """Check if fullscreen only mode is enabled."""
        return self._fullscreen_only
    
    def get_state(self) -> ProfileState:
        """Get current profile manager state (without DDC reads - uses cached values)."""
        return ProfileState(
            active_profile=self._active_profile,
            window_info=self._current_window,
            adaptive_enabled=self._adaptive_enabled,
            last_analysis=self._last_analysis,
            current_brightness=self._last_brightness,
            current_contrast=self._last_contrast,
            current_color_preset=0,  # Not tracked - use DDC if needed
        )
    
    def get_available_profiles(self) -> List[str]:
        """Get list of available profile names."""
        names = ["default"]  # Default first
        names.extend([p.name for p in self.config.profiles])
        return names
    
    def get_active_profile(self) -> Optional[Profile]:
        """Get the currently active profile."""
        return self._active_profile
    
    def add_profile_change_callback(self, callback: Callable[[Profile], None]):
        """Add callback for profile changes."""
        self._profile_change_callbacks.append(callback)
    
    def add_settings_change_callback(self, callback: Callable[[dict], None]):
        """Add callback for settings changes."""
        self._settings_change_callbacks.append(callback)
    
    def add_window_change_callback(self, callback: Callable[[WindowInfo], None]):
        """Add callback for window changes (for GUI updates)."""
        self._window_change_callbacks.append(callback)
    
    def set_profile_color_mode_callback(self, callback: Callable[[str], Optional[int]]):
        """
        Set callback to get profile color mode from monitor-specific config.
        
        Args:
            callback: Function that takes profile_name and returns color_mode value or None
        """
        self._get_profile_color_mode_callback = callback
    
    def set_profile_color_preset_callback(self, callback: Callable[[str], Optional[int]]):
        """
        Set callback to get profile color preset (0x14) from monitor-specific config.
        
        For monitors that have both Display Mode (0xDC) and Color Temperature (0x14),
        this allows setting both per profile.
        
        Args:
            callback: Function that takes profile_name and returns color_preset value or None
        """
        self._get_profile_color_preset_callback = callback
    
    def remove_profile_change_callback(self, callback: Callable[[Profile], None]):
        """Remove profile change callback."""
        if callback in self._profile_change_callbacks:
            self._profile_change_callbacks.remove(callback)
    
    def remove_settings_change_callback(self, callback: Callable[[dict], None]):
        """Remove settings change callback."""
        if callback in self._settings_change_callbacks:
            self._settings_change_callbacks.remove(callback)
    
    def set_gui_active(self, active: bool):
        """
        Set whether this ProfileManager should update the GUI.
        
        Only one ProfileManager should be GUI-active at a time.
        When switching monitors, call this to deactivate the old one
        and activate the new one.
        
        Args:
            active: True to enable GUI updates, False to disable
        """
        self._is_gui_active = active
        logger.info(f"ProfileManager for display {self.ddc.display}: GUI active = {active}")

