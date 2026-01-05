# API Reference

Monitor Control provides a Python API for programmatic monitor control.

## Installation

```python
pip install -e /path/to/monitor-control
```

Or use directly from the source:

```python
import sys
sys.path.insert(0, '/path/to/monitor-control')

from monitor_control import DDCController, Config, ProfileManager
```

## DDCController

The main class for DDC/CI communication.

### Initialization

```python
from monitor_control.ddc import DDCController

# Create controller for display 1
ddc = DDCController(display=1)

# Or specify by serial number
ddc = DDCController(serial="ABC12345")

# Or by model name
ddc = DDCController(model="RD280UA")
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `display` | int | Display number (from ddcutil detect) |
| `serial` | str | Monitor serial number |
| `model` | str | Monitor model name |
| `bus` | int | I2C bus number (optional) |

### Basic Operations

#### Get/Set Brightness

```python
# Read current brightness
brightness = ddc.get_brightness()
print(f"Brightness: {brightness}")

# Set brightness (0-100)
ddc.set_brightness(50)
```

#### Get/Set Contrast

```python
contrast = ddc.get_contrast()
ddc.set_contrast(60)
```

#### Get/Set Sharpness

```python
sharpness = ddc.get_sharpness()
ddc.set_sharpness(50)
```

### Color Control

#### Color Mode (Display Mode)

```python
# Get current color mode
mode = ddc.get_color_mode()

# Set color mode by VCP value
ddc.set_color_mode(10)  # e.g., sRGB

# Set with friendly name (requires mode mapping)
ddc.set_color_preset(10, "sRGB")
```

#### RGB Gain

```python
# Get RGB values
red = ddc.get_red_gain()
green = ddc.get_green_gain()
blue = ddc.get_blue_gain()

# Set RGB values (0-100)
ddc.set_red_gain(100)
ddc.set_green_gain(95)
ddc.set_blue_gain(90)
```

### Reading All Settings

```python
settings = ddc.get_all_settings()
print(settings)
# Output:
# {
#     'brightness': 50,
#     'contrast': 50,
#     'color_preset': 10,
#     'red_gain': 100,
#     'green_gain': 100,
#     'blue_gain': 100,
#     'sharpness': 50,
#     'sharpness_max': 100
# }
```

### Raw VCP Access

```python
# Read any VCP code
result = ddc.get_vcp(0x10)  # Brightness
print(f"Current: {result.current_value}, Max: {result.max_value}")

# Write any VCP code
ddc.set_vcp(0x10, 50)

# Write with force (bypass cache)
ddc.set_vcp(0xdc, 10, force=True)
```

### Monitor Information

```python
# Get monitor geometry (position and size)
geometry = ddc.get_monitor_geometry()
print(geometry)
# Output: {'x': 0, 'y': 0, 'width': 3072, 'height': 1920}

# Get monitor capabilities
caps = ddc.get_capabilities()
```

### Monitor Detection

```python
from monitor_control.ddc import DDCController

# Detect all monitors
monitors = DDCController.detect_monitors()
for m in monitors:
    print(f"Display {m.display}: {m.model} ({m.serial})")
```

### MonitorInfo Class

```python
from monitor_control.ddc import MonitorInfo

# MonitorInfo attributes
info = monitors[0]
print(info.display)      # Display number
print(info.model)        # Model name
print(info.manufacturer) # Manufacturer code
print(info.serial)       # Serial number
print(info.bus)          # I2C bus path
print(info.get_config_id())  # Config filename
```

## Config

Configuration management class.

### Loading Configuration

```python
from monitor_control.config import Config

# Load default config
config = Config()

# Load specific config file
config = Config(config_path="/path/to/config.yaml")
```

### Accessing Settings

```python
# Global settings
print(config.display)
print(config.color_modes)

# Profiles
for profile in config.profiles:
    print(f"Profile: {profile.name}, Priority: {profile.priority}")

# Default profile
print(config.default_profile.name)
```

### MonitorConfig

Per-monitor configuration:

```python
from monitor_control.config import MonitorConfig

# Load or create monitor config
mon_config = MonitorConfig("BenQ_RD280UA_ABC123")

# Access settings
print(mon_config.brightness)
print(mon_config.color_modes)
print(mon_config.adaptive_settings)

# Modify and save
mon_config.brightness = 50
mon_config.save()
```

## ProfileManager

Manages automatic profile switching.

### Initialization

```python
from monitor_control.profile_manager import ProfileManager

pm = ProfileManager(config, ddc, monitor_index=1)
pm.start()
```

### Manual Profile Control

```python
# Set profile by name
pm.set_profile("coding")

# Get current profile
profile = pm.get_active_profile()
print(f"Active: {profile.name}")
```

### Auto Features

```python
# Enable/disable auto brightness
pm.set_auto_brightness_enabled(True)

# Enable/disable auto contrast
pm.set_auto_contrast_enabled(True)

# Enable/disable auto profile switching
pm.set_auto_profile_enabled(True)
```

### Callbacks

```python
# Profile change callback
def on_profile_change(profile):
    print(f"Profile changed to: {profile.name}")

pm.add_profile_change_callback(on_profile_change)

# Settings change callback
def on_settings_change(settings):
    print(f"New brightness: {settings.get('brightness')}")

pm.add_settings_change_callback(on_settings_change)

# Window change callback
def on_window_change(window_info):
    print(f"Window: {window_info.window_class}")

pm.add_window_change_callback(on_window_change)
```

### Cleanup

```python
pm.stop()
```

## ScreenAnalyzer

Screen content analysis for adaptive brightness.

### Initialization

```python
from monitor_control.screen_analyzer import ScreenAnalyzer

analyzer = ScreenAnalyzer(monitor_region=(0, 0, 1920, 1080))
```

### Configuration

```python
# Set brightness range
analyzer.min_brightness = 20
analyzer.max_brightness = 80

# Set contrast range
analyzer.min_contrast = 30
analyzer.max_contrast = 70

# Set smoothing
analyzer.smoothing = 0.3

# Set analysis interval
analyzer.set_interval(2.0)
```

### Manual Analysis

```python
# Capture and analyze
result = analyzer.analyze_screen()
print(f"Mean brightness: {result['mean']}")
print(f"Dark ratio: {result['dark_ratio']}")
print(f"Bright ratio: {result['bright_ratio']}")
print(f"Suggested brightness: {result['suggested_brightness']}")
```

### Continuous Monitoring

```python
def on_brightness_change(brightness):
    print(f"Suggested brightness: {brightness}")
    ddc.set_brightness(brightness)

def on_contrast_change(contrast):
    print(f"Suggested contrast: {contrast}")
    ddc.set_contrast(contrast)

# Start monitoring
analyzer.start_monitoring(
    region=(0, 0, 1920, 1080),
    brightness_callback=on_brightness_change,
    contrast_callback=on_contrast_change
)

# Stop monitoring
analyzer.stop_monitoring()
```

## WindowMonitor

Active window detection.

### Initialization

```python
from monitor_control.window_monitor import WindowMonitor

wm = WindowMonitor()
```

### Get Active Window

```python
window_info = wm.get_active_window()
if window_info:
    print(f"Class: {window_info.window_class}")
    print(f"Title: {window_info.title}")
    print(f"Position: {window_info.x}, {window_info.y}")
    print(f"Size: {window_info.width}x{window_info.height}")
```

### Window Monitoring

```python
def on_window_change(window_info):
    print(f"Active window: {window_info.window_class}")

wm.add_callback(on_window_change)
wm.start()

# Later...
wm.stop()
```

## Complete Example

```python
#!/usr/bin/env python3
"""Example: Monitor control script"""

from monitor_control.ddc import DDCController
from monitor_control.config import Config, MonitorConfig
from monitor_control.profile_manager import ProfileManager

def main():
    # Detect monitors
    monitors = DDCController.detect_monitors()
    print(f"Found {len(monitors)} monitors")
    
    for mon in monitors:
        print(f"\nMonitor: {mon.model} (Display {mon.display})")
        
        # Create controller
        ddc = DDCController(display=mon.display)
        
        # Read current settings
        settings = ddc.get_all_settings()
        print(f"  Brightness: {settings['brightness']}")
        print(f"  Contrast: {settings['contrast']}")
        
        # Load config
        config = Config()
        mon_config = MonitorConfig(mon.get_config_id())
        
        # Create profile manager
        pm = ProfileManager(config, ddc, monitor_index=mon.display)
        
        # Set up callbacks
        def on_profile(profile, display=mon.display):
            print(f"Display {display}: Profile -> {profile.name}")
        
        pm.add_profile_change_callback(on_profile)
        
        # Start
        pm.start()
        pm.set_auto_profile_enabled(True)
        pm.set_auto_brightness_enabled(True)
        
        print(f"  Auto features enabled for display {mon.display}")

if __name__ == "__main__":
    main()
```

## Error Handling

```python
from monitor_control.ddc import DDCController, DDCError

try:
    ddc = DDCController(display=1)
    brightness = ddc.get_brightness()
except DDCError as e:
    print(f"DDC error: {e}")
except Exception as e:
    print(f"Error: {e}")
```

## Type Hints

The API uses Python type hints:

```python
def set_brightness(self, value: int) -> bool:
    """
    Set monitor brightness.
    
    Args:
        value: Brightness level (0-100)
        
    Returns:
        True if successful
        
    Raises:
        DDCError: If DDC communication fails
    """
    ...
```

## Thread Safety

- `DDCController` methods are thread-safe
- `ProfileManager` runs in its own thread
- `ScreenAnalyzer` runs in its own thread
- Callbacks are invoked from worker threads

Use appropriate synchronization when updating UI:

```python
import threading

def on_brightness_change(brightness):
    # Schedule UI update on main thread
    root.after(0, lambda: update_slider(brightness))
```

## Next Steps

- [Configuration](Configuration.md) - Configuration options
- [DDC/CI Reference](DDC-CI-Reference.md) - VCP codes
- [Examples](#complete-example) - More code examples

