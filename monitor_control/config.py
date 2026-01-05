"""
Configuration Management
========================
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ProfileSettings:
    """Monitor settings for a profile."""
    color_preset: Optional[int] = None
    brightness: Optional[int] = None
    contrast: Optional[int] = None
    red_gain: Optional[int] = None
    green_gain: Optional[int] = None
    blue_gain: Optional[int] = None
    
    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in {
            'color_preset': self.color_preset,
            'brightness': self.brightness,
            'contrast': self.contrast,
            'red_gain': self.red_gain,
            'green_gain': self.green_gain,
            'blue_gain': self.blue_gain,
        }.items() if v is not None}


@dataclass
class ProfileMatch:
    """Matching criteria for a profile."""
    window_class: List[str] = field(default_factory=list)
    window_title: List[str] = field(default_factory=list)


@dataclass
class Profile:
    """Application profile configuration."""
    name: str
    priority: int
    match: ProfileMatch
    settings: ProfileSettings
    require_fullscreen: bool = False
    auto_brightness: Optional[bool] = None  # None = inherit global setting
    auto_contrast: Optional[bool] = None    # None = inherit global setting
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], color_modes: Dict[str, int]) -> 'Profile':
        """Create Profile from configuration dictionary."""
        match_data = data.get('match', {})
        settings_data = data.get('settings', {})
        
        # Resolve color preset name to value
        color_preset = settings_data.get('color_preset')
        if isinstance(color_preset, str):
            color_preset = color_modes.get(color_preset, 0)
        
        return cls(
            name=data.get('name', 'unnamed'),
            priority=data.get('priority', 0),
            match=ProfileMatch(
                window_class=match_data.get('window_class', []),
                window_title=match_data.get('window_title', []),
            ),
            settings=ProfileSettings(
                color_preset=color_preset,
                brightness=settings_data.get('brightness'),
                contrast=settings_data.get('contrast'),
                red_gain=settings_data.get('red_gain'),
                green_gain=settings_data.get('green_gain'),
                blue_gain=settings_data.get('blue_gain'),
            ),
            require_fullscreen=data.get('require_fullscreen', False),
            auto_brightness=data.get('auto_brightness'),  # None, true, or false
            auto_contrast=data.get('auto_contrast'),      # None, true, or false
        )


@dataclass
class AdaptiveContrastConfig:
    """Configuration for adaptive contrast and brightness."""
    enabled: bool = True
    interval: float = 5.0
    region: str = "fullscreen"
    min_contrast: int = 30
    max_contrast: int = 70
    min_brightness: int = 20
    max_brightness: int = 80
    dark_threshold: float = 0.3
    bright_threshold: float = 0.7
    smoothing: float = 0.7
    respect_profiles: bool = True


@dataclass
class GUIConfig:
    """GUI configuration."""
    tray_icon: bool = True
    overlay_style: str = "osd"
    overlay_position: str = "bottom-center"
    overlay_timeout: float = 3.0
    notifications: bool = True
    theme: str = "dark"


class Config:
    """
    Configuration manager for monitor control.
    
    Handles loading, saving, and accessing configuration settings.
    """
    
    DEFAULT_CONFIG_PATH = Path.home() / ".config" / "monitor-control" / "config.yaml"
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration.
        
        Args:
            config_path: Path to configuration file, or None for default
        """
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._data: Dict[str, Any] = {}
        
        # Parsed configuration objects
        self.monitor_identifier: Optional[str] = None
        self.ddc_retry_count: int = 3
        self.ddc_sleep_multiplier: float = 1.0
        self.vcp_codes: Dict[str, int] = {}
        self.color_modes: Dict[str, int] = {}
        self.profiles: List[Profile] = []
        self.default_profile: Profile = Profile(
            name="default",
            priority=-1,
            match=ProfileMatch(),
            settings=ProfileSettings(brightness=40, contrast=50),
        )
        self.adaptive_contrast = AdaptiveContrastConfig()
        self.gui = GUIConfig()
        self.auto_profile_enabled = False  # Remember auto profile switch state
        
    def load(self) -> bool:
        """
        Load configuration from file.
        
        Returns:
            True if configuration was loaded successfully
        """
        if not self.config_path.exists():
            logger.warning(f"Configuration file not found: {self.config_path}")
            return False
            
        try:
            with open(self.config_path, 'r') as f:
                self._data = yaml.safe_load(f) or {}
            
            self._parse_config()
            logger.info(f"Loaded configuration from {self.config_path}")
            return True
            
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse configuration: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return False
    
    def _parse_config(self):
        """Parse loaded configuration data into typed objects."""
        # Monitor settings
        monitor = self._data.get('monitor', {})
        self.monitor_identifier = monitor.get('identifier')
        ddc = monitor.get('ddc', {})
        self.ddc_retry_count = ddc.get('retry_count', 3)
        self.ddc_sleep_multiplier = ddc.get('sleep_multiplier', 1.0)
        
        # VCP codes
        self.vcp_codes = self._data.get('vcp_codes', {})
        
        # Color modes
        self.color_modes = self._data.get('color_modes', {})
        
        # Profiles
        self.profiles = []
        for profile_data in self._data.get('profiles', []):
            try:
                profile = Profile.from_dict(profile_data, self.color_modes)
                self.profiles.append(profile)
            except Exception as e:
                logger.warning(f"Failed to parse profile: {e}")
        
        # Sort profiles by priority (higher priority first)
        self.profiles.sort(key=lambda p: -p.priority)
        
        # Default profile
        default_data = self._data.get('default_profile', {})
        if default_data:
            self.default_profile = Profile.from_dict(
                {**default_data, 'priority': -1, 'match': {}},
                self.color_modes
            )
        
        # Adaptive contrast
        adaptive = self._data.get('adaptive_contrast', {})
        self.adaptive_contrast = AdaptiveContrastConfig(
            enabled=adaptive.get('enabled', True),
            interval=adaptive.get('interval', 5.0),
            region=adaptive.get('region', 'fullscreen'),
            min_contrast=adaptive.get('min_contrast', 30),
            max_contrast=adaptive.get('max_contrast', 70),
            min_brightness=adaptive.get('min_brightness', 20),
            max_brightness=adaptive.get('max_brightness', 80),
            dark_threshold=adaptive.get('dark_threshold', 0.3),
            bright_threshold=adaptive.get('bright_threshold', 0.7),
            smoothing=adaptive.get('smoothing', 0.7),
            respect_profiles=adaptive.get('respect_profiles', True),
        )
        
        # GUI settings
        gui = self._data.get('gui', {})
        self.gui = GUIConfig(
            tray_icon=gui.get('tray_icon', True),
            overlay_style=gui.get('overlay_style', 'osd'),
            overlay_position=gui.get('overlay_position', 'bottom-center'),
            overlay_timeout=gui.get('overlay_timeout', 3.0),
            notifications=gui.get('notifications', True),
            theme=gui.get('theme', 'dark'),
        )
        
        # App state (persisted settings)
        app_state = self._data.get('app_state', {})
        self.auto_profile_enabled = app_state.get('auto_profile_enabled', False)
        self.min_brightness = app_state.get('min_brightness', 20)
        self.max_brightness = app_state.get('max_brightness', 80)
    
    def save(self) -> bool:
        """
        Save current configuration to file.
        
        Returns:
            True if configuration was saved successfully
        """
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w') as f:
                yaml.safe_dump(self._data, f, default_flow_style=False)
            logger.info(f"Saved configuration to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return False
    
    def get_color_mode_name(self, value: int) -> str:
        """Get the name of a color mode by its value."""
        for name, val in self.color_modes.items():
            if val == value:
                return name
        return f"Mode {value}"
    
    def get_color_mode_value(self, name: str) -> int:
        """Get the value of a color mode by its name."""
        return self.color_modes.get(name, 0)
    
    def set_profile_color_mode(self, profile_name: str, color_mode_name: str) -> bool:
        """
        Update a profile's color preset and save to config file.
        
        Args:
            profile_name: Name of the profile to update
            color_mode_name: Name of the color mode to set
            
        Returns:
            True if successfully updated and saved
        """
        color_value = self.color_modes.get(color_mode_name)
        if color_value is None:
            logger.warning(f"Unknown color mode: {color_mode_name}")
            return False
        
        # Update in-memory profile
        if profile_name == "default":
            self.default_profile.settings.color_preset = color_value
            # Update _data for saving
            if 'default_profile' not in self._data:
                self._data['default_profile'] = {'name': 'default', 'settings': {}}
            if 'settings' not in self._data['default_profile']:
                self._data['default_profile']['settings'] = {}
            self._data['default_profile']['settings']['color_preset'] = color_mode_name
        else:
            # Find and update the profile
            for profile in self.profiles:
                if profile.name == profile_name:
                    profile.settings.color_preset = color_value
                    break
            
            # Update _data for saving
            for profile_data in self._data.get('profiles', []):
                if profile_data.get('name') == profile_name:
                    if 'settings' not in profile_data:
                        profile_data['settings'] = {}
                    profile_data['settings']['color_preset'] = color_mode_name
                    break
        
        logger.info(f"Set profile '{profile_name}' color mode to '{color_mode_name}' ({color_value})")
        return self.save()
    
    def save_profile_auto_settings(self, profile_name: str, 
                                    auto_brightness: bool = None, 
                                    auto_contrast: bool = None) -> bool:
        """
        Save auto brightness/contrast settings to a profile's config.
        
        Args:
            profile_name: Name of the profile to update
            auto_brightness: New auto_brightness value (None = don't change)
            auto_contrast: New auto_contrast value (None = don't change)
            
        Returns:
            True if successfully saved
        """
        # Update in-memory profile
        if profile_name == "default":
            if auto_brightness is not None:
                self.default_profile.auto_brightness = auto_brightness
            if auto_contrast is not None:
                self.default_profile.auto_contrast = auto_contrast
            # Update _data for saving
            if 'default_profile' not in self._data:
                self._data['default_profile'] = {'name': 'default', 'settings': {}}
            if auto_brightness is not None:
                self._data['default_profile']['auto_brightness'] = auto_brightness
            if auto_contrast is not None:
                self._data['default_profile']['auto_contrast'] = auto_contrast
        else:
            # Find and update the profile in memory
            for profile in self.profiles:
                if profile.name == profile_name:
                    if auto_brightness is not None:
                        profile.auto_brightness = auto_brightness
                    if auto_contrast is not None:
                        profile.auto_contrast = auto_contrast
                    break
            
            # Update _data for saving
            for profile_data in self._data.get('profiles', []):
                if profile_data.get('name') == profile_name:
                    if auto_brightness is not None:
                        profile_data['auto_brightness'] = auto_brightness
                    if auto_contrast is not None:
                        profile_data['auto_contrast'] = auto_contrast
                    break
        
        changes = []
        if auto_brightness is not None:
            changes.append(f"auto_brightness={auto_brightness}")
        if auto_contrast is not None:
            changes.append(f"auto_contrast={auto_contrast}")
        logger.info(f"Saved profile '{profile_name}': {', '.join(changes)}")
        return self.save()
    
    def add_app_to_profile(self, profile_name: str, window_class: str) -> tuple:
        """
        Add a window class to a profile's match list and save to config file.
        If the app exists in another profile, it will be moved (removed from old, added to new).
        This applies to all monitors (stored in global config).
        
        Args:
            profile_name: Name of the profile to update
            window_class: Window class to add to the match list
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if not window_class or window_class.strip() == "":
            logger.warning("Cannot add empty window class to profile")
            return False, "Empty window class"
        
        window_class = window_class.strip()
        
        # Check if already in target profile
        already_in_target = False
        if profile_name == "default":
            already_in_target = window_class in self.default_profile.match.window_class
        else:
            for profile in self.profiles:
                if profile.name == profile_name:
                    already_in_target = window_class in profile.match.window_class
                    break
        
        if already_in_target:
            logger.info(f"App '{window_class}' already in profile '{profile_name}'")
            return True, "already_present"
        
        # Remove from other profiles first (move behavior)
        removed_from = None
        # Check default profile
        if profile_name != "default" and window_class in self.default_profile.match.window_class:
            self.default_profile.match.window_class.remove(window_class)
            removed_from = "default"
            # Update _data
            if 'default_profile' in self._data and 'match' in self._data['default_profile']:
                wc_list = self._data['default_profile']['match'].get('window_class', [])
                if window_class in wc_list:
                    wc_list.remove(window_class)
        
        # Check other profiles
        for profile in self.profiles:
            if profile.name != profile_name and window_class in profile.match.window_class:
                profile.match.window_class.remove(window_class)
                removed_from = profile.name
                break
        
        # Update _data for other profiles
        for profile_data in self._data.get('profiles', []):
            if profile_data.get('name') != profile_name:
                wc_list = profile_data.get('match', {}).get('window_class', [])
                if window_class in wc_list:
                    wc_list.remove(window_class)
        
        # Now add to target profile
        profile_found = False
        if profile_name == "default":
            self.default_profile.match.window_class.append(window_class)
            profile_found = True
            # Update _data for saving
            if 'default_profile' not in self._data:
                self._data['default_profile'] = {'name': 'default', 'match': {'window_class': []}}
            if 'match' not in self._data['default_profile']:
                self._data['default_profile']['match'] = {'window_class': []}
            if 'window_class' not in self._data['default_profile']['match']:
                self._data['default_profile']['match']['window_class'] = []
            self._data['default_profile']['match']['window_class'].append(window_class)
        else:
            # Find and update the profile
            for profile in self.profiles:
                if profile.name == profile_name:
                    profile.match.window_class.append(window_class)
                    profile_found = True
                    break
            
            # Update _data for saving
            for profile_data in self._data.get('profiles', []):
                if profile_data.get('name') == profile_name:
                    if 'match' not in profile_data:
                        profile_data['match'] = {'window_class': []}
                    if 'window_class' not in profile_data['match']:
                        profile_data['match']['window_class'] = []
                    profile_data['match']['window_class'].append(window_class)
                    break
        
        if not profile_found:
            logger.warning(f"Profile '{profile_name}' not found")
            return False, "profile_not_found"
        
        if removed_from:
            logger.info(f"Moved app '{window_class}' from profile '{removed_from}' to '{profile_name}'")
            self.save()
            return True, f"moved_from:{removed_from}"
        else:
            logger.info(f"Added app '{window_class}' to profile '{profile_name}'")
            self.save()
            return True, "added"
    
    def set_profile_auto_settings(self, profile_name: str, auto_brightness: Optional[bool] = None, 
                                   auto_contrast: Optional[bool] = None) -> bool:
        """
        Update a profile's auto brightness/contrast settings and save to config file.
        
        Args:
            profile_name: Name of the profile to update
            auto_brightness: Auto brightness setting (True/False/None)
            auto_contrast: Auto contrast setting (True/False/None)
            
        Returns:
            True if successfully updated and saved
        """
        # Update in-memory profile
        if profile_name == "default":
            self.default_profile.auto_brightness = auto_brightness
            self.default_profile.auto_contrast = auto_contrast
            # Update _data for saving
            if 'default_profile' not in self._data:
                self._data['default_profile'] = {'name': 'default', 'settings': {}}
            if auto_brightness is not None:
                self._data['default_profile']['auto_brightness'] = auto_brightness
            if auto_contrast is not None:
                self._data['default_profile']['auto_contrast'] = auto_contrast
        else:
            # Find and update the profile
            for profile in self.profiles:
                if profile.name == profile_name:
                    if auto_brightness is not None:
                        profile.auto_brightness = auto_brightness
                    if auto_contrast is not None:
                        profile.auto_contrast = auto_contrast
                    break
            
            # Update _data for saving
            for profile_data in self._data.get('profiles', []):
                if profile_data.get('name') == profile_name:
                    if auto_brightness is not None:
                        profile_data['auto_brightness'] = auto_brightness
                    if auto_contrast is not None:
                        profile_data['auto_contrast'] = auto_contrast
                    break
        
        logger.info(f"Set profile '{profile_name}' auto settings: brightness={auto_brightness}, contrast={auto_contrast}")
        return self.save()
    
    def set_auto_profile_enabled(self, enabled: bool) -> bool:
        """
        Update and save auto profile enabled state.
        
        Args:
            enabled: Whether auto profile switching is enabled
            
        Returns:
            True if successfully saved
        """
        self.auto_profile_enabled = enabled
        
        # Update _data for saving
        if 'app_state' not in self._data:
            self._data['app_state'] = {}
        self._data['app_state']['auto_profile_enabled'] = enabled
        
        logger.info(f"Auto profile switching {'enabled' if enabled else 'disabled'}")
        return self.save()
    
    def save_adaptive_setting(self, setting: str, value) -> bool:
        """
        Save a single adaptive contrast setting.
        
        Args:
            setting: Setting name (min_contrast, max_contrast, min_brightness, etc.)
            value: Setting value
            
        Returns:
            True if successfully saved
        """
        # Update in-memory config
        if setting in ['min_contrast', 'max_contrast', 'dark_threshold', 'bright_threshold', 'smoothing', 'interval']:
            setattr(self.adaptive_contrast, setting, value)
        
        # Update _data for saving
        if 'adaptive_contrast' not in self._data:
            self._data['adaptive_contrast'] = {}
        
        # Map settings to their storage names
        if setting in ['min_brightness', 'max_brightness']:
            # These are stored in app_state since they're analyzer params
            if 'app_state' not in self._data:
                self._data['app_state'] = {}
            self._data['app_state'][setting] = value
        else:
            self._data['adaptive_contrast'][setting] = value
        
        return self.save()
    
    @classmethod
    def get_default_config_dir(cls) -> Path:
        """Get the default configuration directory."""
        return cls.DEFAULT_CONFIG_PATH.parent
    
    @classmethod
    def create_default_config(cls, path: Optional[Path] = None) -> bool:
        """
        Create a default configuration file.
        
        Args:
            path: Path for the configuration file
            
        Returns:
            True if file was created successfully
        """
        target_path = path or cls.DEFAULT_CONFIG_PATH
        
        # Check if default config exists in package
        package_config = Path(__file__).parent.parent / "config.yaml"
        if package_config.exists():
            import shutil
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(package_config, target_path)
                logger.info(f"Created default configuration at {target_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to copy default config: {e}")
                return False
        
        logger.error("Default configuration template not found")
        return False


class MonitorConfig:
    """
    Per-monitor configuration manager.
    
    Stores monitor-specific settings like color modes, brightness, contrast, etc.
    Each monitor gets its own config file based on model and serial.
    """
    
    MONITORS_DIR = Path.home() / ".config" / "monitor-control" / "monitors"
    
    def __init__(self, monitor_id: str):
        """
        Initialize monitor configuration.
        
        Args:
            monitor_id: Unique identifier for this monitor (from MonitorInfo.get_config_id())
        """
        self.monitor_id = monitor_id
        self.config_path = self.MONITORS_DIR / f"{monitor_id}.yaml"
        self._data: Dict[str, Any] = {}
        
        # Monitor-specific settings
        self.color_modes: Dict[str, int] = {}  # name -> VCP value
        self.brightness: int = 50
        self.contrast: int = 50
        self.sharpness: int = 50
        self.sharpness_max: int = 100  # Max sharpness value varies by monitor
        self.color_preset: int = 0
        self.red_gain: int = 100
        self.green_gain: int = 100
        self.blue_gain: int = 100
        
        # Per-monitor auto settings
        self.auto_brightness: bool = False
        self.auto_contrast: bool = False
        self.auto_profile: bool = False
        self.fullscreen_only: bool = False  # Only switch profiles when app is fullscreen
        
        # Per-monitor profile color modes (profile_name -> color_mode_value)
        self.profile_color_modes: Dict[str, int] = {}
        
        # Per-monitor profile color presets (0x14) - for monitors with separate display mode + color temp
        # (profile_name -> color_preset_value)
        self.profile_color_presets: Dict[str, int] = {}
        
        # Per-monitor adaptive parameters
        self.adaptive_settings: Dict[str, Any] = {
            'min_brightness': 20,
            'max_brightness': 80,
            'min_contrast': 20,
            'max_contrast': 80,
            'dark_threshold': 0.3,
            'bright_threshold': 0.7,
            'interval': 2.0,
            'smoothing': 0.3,
        }
        
        # Features not supported by this monitor (e.g., 'sharpness', 'red_gain')
        self.unsupported_features: List[str] = []
    
    def load(self) -> bool:
        """Load configuration from file."""
        if not self.config_path.exists():
            logger.info(f"No config file for monitor {self.monitor_id}, will create on save")
            return False
        
        try:
            with open(self.config_path, 'r') as f:
                self._data = yaml.safe_load(f) or {}
            
            self._parse_config()
            logger.info(f"Loaded monitor config from {self.config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load monitor config: {e}")
            return False
    
    def _parse_config(self):
        """Parse loaded configuration."""
        self.color_modes = self._data.get('color_modes', {})
        
        settings = self._data.get('settings', {})
        self.brightness = settings.get('brightness', 50)
        self.contrast = settings.get('contrast', 50)
        self.sharpness = settings.get('sharpness', 50)
        self.sharpness_max = settings.get('sharpness_max', 100)
        self.color_preset = settings.get('color_preset', 0)
        self.red_gain = settings.get('red_gain', 100)
        self.green_gain = settings.get('green_gain', 100)
        self.blue_gain = settings.get('blue_gain', 100)
        
        # Per-monitor auto settings
        auto = self._data.get('auto', {})
        self.auto_brightness = auto.get('brightness', False)
        self.auto_contrast = auto.get('contrast', False)
        self.auto_profile = auto.get('profile', False)
        self.fullscreen_only = auto.get('fullscreen_only', False)
        
        # Per-monitor profile color modes
        self.profile_color_modes = self._data.get('profile_color_modes', {})
        
        # Per-monitor profile color presets (0x14) - for monitors with both display mode + color temp
        self.profile_color_presets = self._data.get('profile_color_presets', {})
        
        # Adaptive parameters
        adaptive = self._data.get('adaptive', {})
        self.adaptive_settings = {
            'min_brightness': adaptive.get('min_brightness', 20),
            'max_brightness': adaptive.get('max_brightness', 80),
            'min_contrast': adaptive.get('min_contrast', 20),
            'max_contrast': adaptive.get('max_contrast', 80),
            'dark_threshold': adaptive.get('dark_threshold', 0.3),
            'bright_threshold': adaptive.get('bright_threshold', 0.7),
            'interval': adaptive.get('interval', 2.0),
            'smoothing': adaptive.get('smoothing', 0.3),
        }
        
        # Unsupported features
        self.unsupported_features = self._data.get('unsupported_features', [])
    
    def save(self) -> bool:
        """Save configuration to file."""
        try:
            self.MONITORS_DIR.mkdir(parents=True, exist_ok=True)
            
            self._data = {
                'monitor_id': self.monitor_id,
                'color_modes': self.color_modes,
                'settings': {
                    'brightness': self.brightness,
                    'contrast': self.contrast,
                    'sharpness': self.sharpness,
                    'sharpness_max': self.sharpness_max,
                    'color_preset': self.color_preset,
                    'red_gain': self.red_gain,
                    'green_gain': self.green_gain,
                    'blue_gain': self.blue_gain,
                },
                'auto': {
                    'brightness': self.auto_brightness,
                    'contrast': self.auto_contrast,
                    'profile': self.auto_profile,
                    'fullscreen_only': self.fullscreen_only,
                },
                'adaptive': self.adaptive_settings,
                'profile_color_modes': self.profile_color_modes,
                'profile_color_presets': self.profile_color_presets,
                'unsupported_features': self.unsupported_features,
            }
            
            with open(self.config_path, 'w') as f:
                yaml.safe_dump(self._data, f, default_flow_style=False, sort_keys=False)
            
            logger.info(f"Saved monitor config to {self.config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save monitor config: {e}")
            return False
    
    def set_color_modes_from_ddc(self, ddc_modes: Dict[int, str], global_color_modes: Dict[str, int] = None):
        """
        Set available color modes from DDC capabilities, using global config for names.
        
        Args:
            ddc_modes: Dictionary mapping VCP value to mode name (from DDC)
            global_color_modes: User-defined color mode names -> values from global config
        """
        # Build color modes using DDC-detected values with user-defined names where available
        self.color_modes = {}
        
        # First, add user-defined modes that match DDC values
        if global_color_modes:
            for name, value in global_color_modes.items():
                if value in ddc_modes:
                    self.color_modes[name] = value
        
        # Then, add any remaining DDC modes that weren't in global config
        for value, ddc_name in ddc_modes.items():
            # Check if we already have a name for this value
            if any(v == value for v in self.color_modes.values()):
                continue
            # Use DDC name, but clean up "Unrecognized value" entries
            if "Unrecognized" in ddc_name:
                name = f"Mode {value}"
            else:
                name = ddc_name
            self.color_modes[name] = value
    
    def get_color_mode_name(self, value: int) -> str:
        """Get the name for a color mode value."""
        for name, val in self.color_modes.items():
            if val == value:
                return name
        return f"Mode {value}"
    
    def get_color_mode_value(self, name: str) -> Optional[int]:
        """Get the VCP value for a color mode name."""
        return self.color_modes.get(name)
    
    def get_profile_color_mode(self, profile_name: str) -> Optional[int]:
        """Get the color mode value for a profile."""
        return self.profile_color_modes.get(profile_name)
    
    def get_profile_color_mode_name(self, profile_name: str) -> str:
        """Get the color mode name for a profile."""
        value = self.profile_color_modes.get(profile_name)
        if value is not None:
            return self.get_color_mode_name(value)
        return "Unknown"
    
    def set_profile_color_mode(self, profile_name: str, color_mode_value: int):
        """Set the color mode for a profile."""
        self.profile_color_modes[profile_name] = color_mode_value
        logger.info(f"Monitor {self.monitor_id}: Set profile '{profile_name}' to color mode {color_mode_value}")
    
    def get_profile_color_preset(self, profile_name: str) -> Optional[int]:
        """Get the color preset (0x14) value for a profile."""
        return self.profile_color_presets.get(profile_name)
    
    def set_profile_color_preset(self, profile_name: str, color_preset_value: int):
        """Set the color preset (0x14) for a profile."""
        self.profile_color_presets[profile_name] = color_preset_value
        logger.info(f"Monitor {self.monitor_id}: Set profile '{profile_name}' to color preset {color_preset_value}")
    
    def initialize_profile_color_modes(self, profile_names: List[str], current_color_mode: int):
        """
        Initialize all profile color modes to the current monitor's color mode.
        Only initializes profiles that don't already have a color mode set.
        
        Args:
            profile_names: List of profile names to initialize
            current_color_mode: Current color mode value from the monitor
        """
        for profile_name in profile_names:
            if profile_name not in self.profile_color_modes:
                self.profile_color_modes[profile_name] = current_color_mode
                logger.info(f"Monitor {self.monitor_id}: Initialized profile '{profile_name}' to color mode {current_color_mode}")
    
    @classmethod
    def get_or_create(cls, monitor_id: str, ddc_color_modes: Dict[int, str] = None, 
                      global_color_modes: Dict[str, int] = None) -> 'MonitorConfig':
        """
        Get existing config or create new one for a monitor.
        
        Args:
            monitor_id: Unique monitor identifier
            ddc_color_modes: Color modes from DDC capabilities (value -> name)
            global_color_modes: User-defined color mode names from global config
        
        Returns:
            MonitorConfig instance
        """
        config = cls(monitor_id)
        
        if config.load():
            # Config exists, update color modes if DDC provided and no modes saved
            if ddc_color_modes and not config.color_modes:
                config.set_color_modes_from_ddc(ddc_color_modes, global_color_modes)
                config.save()
        else:
            # New config, initialize from DDC
            if ddc_color_modes:
                config.set_color_modes_from_ddc(ddc_color_modes, global_color_modes)
            config.save()
        
        return config

