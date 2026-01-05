# Multi-Monitor Setup

Monitor Control supports multiple monitors with independent settings for each display.

## How It Works

### Monitor Detection

On startup, the app detects all DDC/CI capable monitors:

```bash
python main.py --detect
```

Output:
```
Detected monitors:
  Display 1:
    Model:        BenQ RD280UA
    Manufacturer: BNQ
    Serial:       ABC123
    I2C Bus:      /dev/i2c-5
    
  Display 2:
    Model:        Dell U2412M
    Manufacturer: DEL
    Serial:       XYZ789
    I2C Bus:      /dev/i2c-6
```

### Per-Monitor Configuration

Each monitor gets its own configuration file:

```
~/.config/monitor-control/monitors/
├── BenQ_RD280UA_ABC123.yaml
└── Dell_U2412M_XYZ789.yaml
```

The filename is derived from `{Model}_{Serial}.yaml` with special characters replaced.

### Independent Settings

Each monitor maintains:

- **Color modes** - Different monitors have different presets
- **Brightness/Contrast** - Independent levels
- **RGB Gain** - Per-monitor color calibration
- **Adaptive settings** - Min/max values, interval
- **Profile color modes** - Which preset to use for each profile

## GUI Multi-Monitor Support

### Overview Tab

The Overview tab shows all monitors in a layout matching your physical setup:

```
┌──────────────────────────────────────┐
│            Monitor Layout            │
│  ┌─────────┐  ┌─────────┐           │
│  │ BenQ    │  │ Dell    │           │
│  │ RD280UA │  │ U2412M  │           │
│  └─────────┘  └─────────┘           │
└──────────────────────────────────────┘
```

Each monitor card shows:
- Current brightness/contrast
- Auto brightness/contrast toggles
- Auto profile toggle

### Monitor Tabs

Each monitor has its own tab with full controls:

- **Basic Controls** - Brightness, Contrast, Sharpness
- **RGB Gain** - Red, Green, Blue channels
- **Color Mode** - Monitor-specific presets
- **Adaptive Settings** - Min/max values, interval
- **Application Profiles** - Profile assignments

### Switching Monitors

Click on a monitor tab or use the overview to switch. Settings shown are always for the selected monitor.

## Per-Monitor Adaptive Brightness

### How Screen Analysis Works

1. The app captures a screenshot of the entire desktop
2. It crops to each monitor's specific region based on geometry
3. Each monitor's brightness is analyzed independently
4. Adjustments are applied only to the relevant monitor

### Monitor Geometry Detection

The app uses xrandr to determine monitor positions:

```bash
xrandr --query
```

Example output:
```
DP-1 connected primary 3072x1920+0+0
HDMI-1 connected 1920x1200+3072+0
```

This tells the app:
- Monitor 1 (DP-1): 3072x1920 at position (0, 0)
- Monitor 2 (HDMI-1): 1920x1200 at position (3072, 0)

### Independent Auto Settings

Each monitor can have different adaptive settings:

**Monitor 1 (Photo editing):**
```yaml
adaptive_settings:
  min_brightness: 40
  max_brightness: 60
  interval: 5.0
```

**Monitor 2 (General use):**
```yaml
adaptive_settings:
  min_brightness: 20
  max_brightness: 80
  interval: 2.0
```

## Per-Monitor Profile Switching

### Window Position Detection

When a window gains focus:

1. The app gets the window's center coordinates
2. It checks which monitor contains that point
3. Profile changes only apply to that monitor

### Example Scenario

Setup:
- Monitor 1: Primary display (coding)
- Monitor 2: Secondary display (reference/video)

Behavior:
- Click on VS Code on Monitor 1 → Monitor 1 switches to "coding" profile
- Monitor 2 remains unchanged
- Click on YouTube on Monitor 2 → Monitor 2 switches to "video" profile
- Monitor 1 remains in "coding" profile

### Profile Color Modes

Each monitor can use different color presets for the same profile:

**BenQ config:**
```yaml
profile_color_modes:
  coding: 31    # ePaper mode
  video: 50     # Cinema mode
```

**Dell config:**
```yaml
profile_color_modes:
  coding: 4     # Paper mode
  video: 2      # Movie mode
```

## Configuration Examples

### Dual Monitor Setup

**Monitor 1 - Design Work:**
```yaml
# ~/.config/monitor-control/monitors/BenQ_RD280UA_ABC123.yaml
settings:
  brightness: 40
  contrast: 50

adaptive_settings:
  min_brightness: 35
  max_brightness: 50
  interval: 5.0

profile_color_modes:
  default: 10   # sRGB
  coding: 31    # ePaper
  photo: 10     # sRGB
```

**Monitor 2 - Reference/Video:**
```yaml
# ~/.config/monitor-control/monitors/Dell_U2412M_XYZ789.yaml
settings:
  brightness: 50
  contrast: 55

adaptive_settings:
  min_brightness: 30
  max_brightness: 70
  interval: 2.0

profile_color_modes:
  default: 6    # sRGB
  video: 2      # Movie
```

### Triple Monitor Setup

For gaming/streaming setups:

```
┌─────────┐ ┌─────────┐ ┌─────────┐
│ Monitor │ │ Monitor │ │ Monitor │
│    1    │ │    2    │ │    3    │
│ (Left)  │ │ (Center)│ │ (Right) │
└─────────┘ └─────────┘ └─────────┘
```

- **Monitor 1**: Chat/Discord - Low brightness, ePaper mode
- **Monitor 2**: Main game - High brightness, Game mode
- **Monitor 3**: Streaming software - Medium brightness, Standard mode

## Troubleshooting

### Monitor Not Detected

1. Check DDC/CI is enabled in monitor OSD
2. Verify I2C device exists:
   ```bash
   ls /dev/i2c-*
   ```
3. Test with ddcutil:
   ```bash
   ddcutil detect
   ```

### Wrong Monitor Layout

The app reads geometry from xrandr. If layout is wrong:

1. Check xrandr output:
   ```bash
   xrandr --query
   ```
2. Verify display arrangement in system settings
3. Restart the app after changing display arrangement

### Adaptive Brightness Affecting Wrong Monitor

If brightness changes affect the wrong monitor:

1. Check the log for geometry information:
   ```bash
   python main.py --debug 2>&1 | grep geometry
   ```
2. Verify monitor display numbers match:
   ```bash
   ddcutil detect
   ```

### Profile Switching Affects Wrong Monitor

This was a known bug (lambda closure issue) that has been fixed. If you experience this:

1. Update to the latest version
2. Check log for correct display_num passing:
   ```bash
   python main.py --debug 2>&1 | grep "display_num"
   ```

### Wayland: Window Position Always (0,0)

**On Wayland**, some applications report their position as (0,0) due to security restrictions. This affects per-monitor profile switching.

**Symptoms:**
- Profile changes apply to wrong monitor
- Debug shows `position: (0, 0)` for windows not at top-left

**Affected:**
- Some Electron apps
- Some GTK4 applications
- Snap applications (also have detection issues)

**Workarounds:**
1. Use manual profile selection for affected apps
2. Keep work-related windows on primary monitor
3. Consider using X11 session for full multi-monitor profile support

See [Wayland Setup - Known Limitations](Wayland-Setup.md#known-limitations) for details.

## Best Practices

### 1. Name Your Monitors Distinctly

Use the monitor's model name in the GUI rather than "Display 1", "Display 2".

### 2. Calibrate Each Monitor Separately

Different monitors have different color characteristics. Set appropriate:
- RGB gain values
- Color mode mappings
- Brightness/contrast ranges

### 3. Use Appropriate Intervals

- **Photo editing monitors**: Longer interval (5s), narrow range
- **General use monitors**: Shorter interval (2s), wider range

### 4. Consider Fullscreen-Only

For gaming/video monitors, enable "Fullscreen Only" to prevent profile switching during normal use:

```yaml
fullscreen_only: true
```

## Next Steps

- [Application Profiles](Application-Profiles.md) - Set up per-application settings
- [Adaptive Brightness](Adaptive-Brightness.md) - Configure automatic adjustments
- [Troubleshooting](Troubleshooting.md) - Common issues and solutions

