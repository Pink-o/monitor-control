# Configuration Reference

Monitor Control uses YAML configuration files. This guide covers all configuration options.

## Configuration Files

### File Locations

| File | Location | Purpose |
|------|----------|---------|
| Global Config | `~/.config/monitor-control/config.yaml` | Profiles, app settings |
| Per-Monitor Config | `~/.config/monitor-control/monitors/<id>.yaml` | Monitor-specific settings |
| Example Config | `config.yaml.example` | Template in repo |

### Configuration Hierarchy

1. **Global Config** - Shared across all monitors (profiles, application matches)
2. **Per-Monitor Config** - Monitor-specific (color modes, brightness, contrast, adaptive settings)

Per-monitor configs are created automatically when a new monitor is detected. The filename is based on the monitor model and serial number (e.g., `Dell_U2412M_ABC123.yaml`).

## Global Configuration

### Monitor Section

```yaml
monitor:
  # Monitor identifier - can be display number, serial, or model name
  identifier: "RD280UA"
  
  # DDC/CI communication settings
  ddc:
    retry_count: 3           # Number of retries on failure
    sleep_multiplier: 1.0    # Delay multiplier (increase for slow monitors)
```

### VCP Codes Section

Standard VCP (Virtual Control Panel) codes for monitor features:

```yaml
vcp_codes:
  brightness: 0x10        # Standard brightness control
  contrast: 0x12          # Standard contrast control
  color_preset: 0xDC      # Display mode / Picture mode
  color_temp: 0x14        # Color temperature preset
  input_source: 0x60      # Input selection
  red_gain: 0x16          # Red color channel
  green_gain: 0x18        # Green color channel
  blue_gain: 0x1A         # Blue color channel
  sharpness: 0x87         # Sharpness control
  color_saturation: 0x8A  # Color saturation
```

> **Note:** These are industry-standard VCP codes. Most monitors support them, but some may use different codes. Use `ddcutil capabilities` to check your monitor.

### Color Modes Section

Map friendly names to VCP values for the Display Mode feature (0xDC):

```yaml
color_modes:
  sRGB: 10           # 0x0a
  M-book: 15         # 0x0f
  User: 18           # 0x12
  ePaper: 31         # 0x1f
  HDR: 35            # 0x23
  Dark Theme: 48     # 0x30
  Light Theme: 49    # 0x31
  Cinema: 50         # 0x32
```

To find your monitor's color modes:
```bash
ddcutil capabilities | grep -A 20 "Feature: DC"
```

### Color Temperature Section

Map friendly names to VCP values for Color Temperature (0x14):

```yaml
color_temps:
  5000K: 4     # Warm
  6500K: 5     # Neutral (sRGB standard)
  9300K: 8     # Cool
  User1: 11    # Custom RGB settings
  User2: 12    # Custom RGB settings
```

### Profiles Section

Application profiles for automatic switching:

```yaml
profiles:
  - name: "coding"
    priority: 10              # Higher = more specific
    match:
      window_class:           # Match by WM_CLASS
        - "code"
        - "Code"
        - "cursor"
        - "jetbrains-*"       # Wildcards supported
      window_title:           # Match by window title
        - "*Visual Studio Code*"
    auto_brightness: false    # Per-profile auto brightness
    auto_contrast: false      # Per-profile auto contrast
    settings:
      color_preset: ePaper
      brightness: 35
      contrast: 50
```

See [Application Profiles](Application-Profiles.md) for detailed profile configuration.

### Default Profile Section

Settings when no application profile matches:

```yaml
default_profile:
  name: "default"
  auto_brightness: true      # Enable adaptive brightness
  auto_contrast: false       # Disable adaptive contrast
  settings:
    color_preset: standard
    brightness: 40
    contrast: 50
```

### Adaptive Contrast Section

Global adaptive brightness/contrast settings:

```yaml
adaptive_contrast:
  enabled: true
  interval: 2.0              # Analysis interval (seconds)
  region: "fullscreen"       # Area to analyze
  min_contrast: 30           # Minimum contrast value
  max_contrast: 70           # Maximum contrast value
  dark_threshold: 0.3        # Screen darkness threshold
  bright_threshold: 0.7      # Screen brightness threshold
  smoothing: 0.3             # Transition smoothness (0-1)
  respect_profiles: false    # Override profile settings
```

### Time Schedules Section (Not Implemented)

> ⚠️ **Note:** Time-based scheduling is **not currently implemented**. This is a planned feature for a future release. The configuration below is for reference only.

```yaml
# PLANNED FEATURE - NOT YET IMPLEMENTED
time_schedules:
  enabled: false
  schedules:
    - name: "day"
      start: "08:00"
      end: "20:00"
      settings:
        brightness: 45
        color_temp: 6500
    - name: "evening"
      start: "20:00"
      end: "23:00"
      settings:
        brightness: 35
        color_temp: 5000
    - name: "night"
      start: "23:00"
      end: "08:00"
      settings:
        brightness: 25
        color_temp: 3500
```

**Workaround:** Use external tools like `cron` with command-line options:
```bash
# Example crontab entries
0 8 * * * /path/to/venv/bin/python /path/to/main.py --brightness 45
0 20 * * * /path/to/venv/bin/python /path/to/main.py --brightness 35
0 23 * * * /path/to/venv/bin/python /path/to/main.py --brightness 25
```

### GUI Section

GUI appearance and behavior:

```yaml
gui:
  tray_icon: true                    # Show system tray icon
  overlay_style: "osd"               # "osd" or "panel"
  overlay_position: "bottom-center"  # Position on screen
  overlay_timeout: 0                 # Auto-hide (0 = never)
  notifications: true                # Show profile change notifications
  theme: "dark"                      # "dark", "light", or "system"
```

### Logging Section

```yaml
logging:
  level: "INFO"    # DEBUG, INFO, WARNING, ERROR
  file: "~/.local/share/monitor-control/monitor-control.log"
```

## Per-Monitor Configuration

Each monitor gets its own configuration file in `~/.config/monitor-control/monitors/`.

### Example Per-Monitor Config

```yaml
# ~/.config/monitor-control/monitors/Dell_U2412M_ABC123.yaml
monitor_id: Dell_U2412M_ABC123

# Monitor-specific color mode mappings
color_modes:
  Standard: 0
  Multimedia: 1
  Movie: 2
  Game: 3
  Paper: 4
  Color Temp: 5
  sRGB: 6
  Custom: 7

# Current settings (saved on change)
settings:
  brightness: 45
  contrast: 50
  color_preset: 6
  red_gain: 100
  green_gain: 100
  blue_gain: 100
  sharpness: 50

# Per-monitor adaptive settings
adaptive_settings:
  min_brightness: 20
  max_brightness: 80
  min_contrast: 30
  max_contrast: 70
  interval: 2.0
  smoothing: 0.3

# Monitor capabilities
auto_brightness: true
auto_contrast: false
auto_profile: true
fullscreen_only: false

# Profile-specific color modes for this monitor
profile_color_modes:
  default: 6
  coding: 4
  video: 2
  photo: 6

# Profile-specific color presets (0x14)
profile_color_presets:
  default: 5
  coding: 5
  video: 8
  photo: 5

# Features not supported by this monitor
unsupported_features:
  - 0x87  # Sharpness
```

### Auto-Generated Fields

These fields are automatically populated:

| Field | Description |
|-------|-------------|
| `monitor_id` | Unique identifier (model + serial) |
| `color_modes` | Detected from DDC capabilities |
| `unsupported_features` | VCP codes that failed |

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `XDG_CONFIG_HOME` | Config directory base | `~/.config` |
| `XDG_SESSION_TYPE` | Detect X11/Wayland | Auto-detected |
| `WAYLAND_DISPLAY` | Wayland display | Auto-detected |
| `DISPLAY` | X11 display | Auto-detected |

## Command-Line Options

```bash
python main.py [OPTIONS]

Options:
  --config PATH      Path to config file
  --no-gui           Run without GUI (daemon mode)
  --debug            Enable debug logging
  --skip-ddc         Skip DDC reads (use cached values)
  --detect           Detect and list monitors
  --capabilities     Show monitor capabilities
  --brightness N     Set brightness (0-100)
  --contrast N       Set contrast (0-100)
  -h, --help         Show help message
```

## Configuration Tips

### Finding Color Mode Values

```bash
# List all capabilities
ddcutil capabilities --display 1

# Get current color mode
ddcutil getvcp 0xdc --display 1

# Test a color mode value
ddcutil setvcp 0xdc 10 --display 1
```

### Debugging Configuration

```bash
# Run with debug logging
python main.py --debug

# Check config loading
python main.py --debug 2>&1 | grep -i config
```

### Multiple Monitors

Each monitor is automatically assigned a display number. Check with:

```bash
ddcutil detect
```

The app creates separate config files for each monitor automatically.

## Next Steps

- [Application Profiles](Application-Profiles.md) - Set up automatic switching
- [Adaptive Brightness](Adaptive-Brightness.md) - Configure screen-based adjustments
- [Multi-Monitor Setup](Multi-Monitor-Setup.md) - Configure multiple displays

