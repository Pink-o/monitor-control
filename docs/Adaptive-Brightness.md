# Adaptive Brightness & Contrast

Monitor Control can automatically adjust brightness and contrast based on screen content.

## How It Works

### Screen Analysis Pipeline

1. **Capture** - Screenshot of the monitor's display area
2. **Downsample** - Reduce to ~200px for fast processing
3. **Analyze** - Calculate mean brightness and dark/bright ratios
4. **Calculate** - Determine target brightness/contrast
5. **Apply** - Smoothly transition to new values

### Analysis Algorithm

The analyzer calculates:

- **Mean Brightness** - Average pixel luminance (0-255)
- **Dark Ratio** - Percentage of pixels below dark threshold
- **Bright Ratio** - Percentage of pixels above bright threshold

Based on these values:
- **Dark screen** (IDE, terminal) → Higher brightness
- **Bright screen** (documents, web) → Lower brightness

This is intentionally **inverse** - it reduces eye strain by counteracting screen content.

## Enabling Adaptive Features

### Global Enable/Disable

In the Overview tab, each monitor has toggle buttons:
- ☀️ **Auto Brightness** - Toggle adaptive brightness
- ◐ **Auto Contrast** - Toggle adaptive contrast
- 📁 **Auto Profile** - Toggle automatic profile switching

### Per-Profile Settings

Each application profile can have independent settings:

```yaml
profiles:
  - name: "coding"
    auto_brightness: false    # Disabled for coding
    auto_contrast: false
    
  - name: "browser"
    auto_brightness: true     # Enabled for browsing
    auto_contrast: false
```

## Configuration Options

### Per-Monitor Adaptive Settings

Each monitor can have different adaptive parameters:

```yaml
# ~/.config/monitor-control/monitors/Monitor_Serial.yaml
adaptive_settings:
  min_brightness: 20      # Minimum brightness (0-100)
  max_brightness: 80      # Maximum brightness (0-100)
  min_contrast: 30        # Minimum contrast (0-100)
  max_contrast: 70        # Maximum contrast (0-100)
  interval: 2.0           # Analysis interval (seconds)
  smoothing: 0.3          # Transition smoothness (0.0-1.0)
```

### Parameter Explanations

#### Min/Max Brightness
```
min_brightness: 20    # Never go below 20%
max_brightness: 80    # Never exceed 80%
```

The adaptive range. Narrower ranges provide more subtle adjustments.

#### Min/Max Contrast
```
min_contrast: 30
max_contrast: 70
```

Same as brightness but for contrast adjustments.

#### Interval
```
interval: 2.0    # Check every 2 seconds
```

How often to analyze the screen:
- **Lower (0.5-1.0)**: More responsive, higher CPU usage
- **Higher (3.0-5.0)**: Less responsive, lower CPU usage

**Platform Limits:**
- X11 minimum: 0.5 seconds
- Wayland minimum: 2.5 seconds (due to screenshot tool overhead)

#### Smoothing
```
smoothing: 0.3    # 30% smoothing
```

Transition smoothness (0.0 to 1.0):
- **0.0**: Immediate changes (can be jarring)
- **0.5**: Moderate smoothing
- **1.0**: Very slow transitions

Formula: `new_value = current + (target - current) * (1 - smoothing)`

## GUI Controls

### Monitor Tab Adaptive Section

Each monitor tab has an "Adaptive Settings" section:

```
┌─────────────────────────────────────┐
│ ⚙️ Adaptive Settings        [▼]     │
├─────────────────────────────────────┤
│ ☀️ Auto Brightness: ON              │
│ ◐ Auto Contrast: OFF                │
│ 📁 Auto Profile: ON                 │
│ □ Fullscreen Only                   │
│─────────────────────────────────────│
│ ⬇️ Min Brightness    [====|   ] 20  │
│ ⬆️ Max Brightness    [=======|] 80  │
│ ⬇️ Min Contrast      [===|    ] 30  │
│ ⬆️ Max Contrast      [======| ] 70  │
│ ⏱️ Interval          [===|    ] 2.0s│
│ 〰️ Smoothing         [===|    ] 0.3 │
└─────────────────────────────────────┘
```

### Overview Tab Quick Toggles

The Overview tab provides quick access to toggle all auto features for each monitor.

## Screen Capture Methods

### X11 (mss)

On X11, the app uses **mss** for silent, fast screen capture:

```python
import mss
with mss.mss() as sct:
    screenshot = sct.grab(monitor_region)
```

- **Speed**: ~20-50ms per capture
- **Silent**: No visual/audio feedback
- **Multi-monitor**: Direct region capture

### Wayland

Wayland's security model prevents direct screen capture. External tools are required:

| Tool | Speed | Notes |
|------|-------|-------|
| gnome-screenshot-silent | ~2.5s | Recommended for GNOME |
| flameshot | ~1-2s | Universal, may flash |
| gnome-screenshot | ~2.5s | Has screen flash |
| grim | ~0.5s | Sway/wlroots only |
| spectacle | ~1-2s | KDE only |

See [Wayland Setup](Wayland-Setup.md) for installation instructions.

### Capture Optimization

The app uses several optimizations:

1. **Method Caching** - First working method is cached
2. **Shared Capture** - Single screenshot shared across monitors
3. **Downsampling** - Images reduced to ~200px before analysis
4. **Skip Unchanged** - Identical frames skip full analysis

## Multi-Monitor Analysis

### Independent Analysis

Each monitor is analyzed independently:

1. Full desktop screenshot is captured
2. Screenshot is cropped to each monitor's region
3. Each region is analyzed separately
4. Adjustments applied to the corresponding monitor

### Geometry Detection

Monitor regions are determined via xrandr:

```bash
xrandr --query
# DP-1: 3072x1920+0+0
# HDMI-1: 1920x1200+3072+0
```

### Shared Capture Cache

To avoid multiple screenshot calls:

1. First monitor requests screenshot → captured and cached
2. Second monitor requests screenshot → uses cached version
3. Cache expires after 0.3 seconds

This prevents conflicts when multiple monitors request captures simultaneously.

## Performance Tuning

### For Low CPU Usage

```yaml
adaptive_settings:
  interval: 5.0       # Less frequent checks
  smoothing: 0.5      # Slower transitions
```

### For Responsiveness

```yaml
adaptive_settings:
  interval: 1.0       # More frequent (X11 only)
  smoothing: 0.1      # Faster transitions
```

### For Stability (Photo Editing)

```yaml
adaptive_settings:
  min_brightness: 40
  max_brightness: 50  # Narrow range
  interval: 10.0      # Infrequent
  smoothing: 0.8      # Very slow changes
```

## Troubleshooting

### "All screen capture methods failed"

**On Wayland:**
Install a screenshot tool. See [Wayland Setup](Wayland-Setup.md).

**On X11:**
```bash
pip install mss
```

### Both Monitors Show Same Values

Check that monitor geometry is correct:
```bash
python main.py --debug 2>&1 | grep -i geometry
```

Verify xrandr shows correct positions:
```bash
xrandr --query
```

### Brightness Changes Too Fast/Slow

Adjust smoothing:
```yaml
smoothing: 0.5    # Increase for slower changes
```

### Brightness Range Too Wide/Narrow

Adjust min/max values:
```yaml
min_brightness: 30    # Don't go too dark
max_brightness: 70    # Don't go too bright
```

### High CPU Usage

Increase interval:
```yaml
interval: 3.0    # Less frequent analysis
```

### Adaptive Not Working on Wayland

1. Check screenshot tool is installed
2. Verify minimum interval (2.5s for Wayland)
3. Check logs for capture errors:
   ```bash
   python main.py --debug 2>&1 | grep -i capture
   ```

## Best Practices

### 1. Start Conservative

Begin with a narrow range and wide interval:
```yaml
min_brightness: 35
max_brightness: 55
interval: 3.0
```

### 2. Adjust Based on Use

- **Coding/Reading**: Disable or narrow range
- **Browsing**: Enable with moderate range
- **Video/Gaming**: Disable

### 3. Use Per-Profile Settings

```yaml
profiles:
  - name: "coding"
    auto_brightness: false    # Stable for focus
    
  - name: "browser"
    auto_brightness: true     # Adaptive for variety
```

### 4. Consider Environment

- **Bright room**: Higher min_brightness
- **Dark room**: Lower max_brightness
- **Mixed lighting**: Wider range with more smoothing

## Technical Details

### Analysis Metrics

```python
mean = np.mean(pixels)              # 0-255
dark_ratio = (pixels < 64).sum() / total
bright_ratio = (pixels > 192).sum() / total
```

### Brightness Calculation

```python
if mean < 128:  # Dark content
    # Increase brightness (inverse relationship)
    target = max_brightness - (mean / 128) * range
else:  # Bright content
    # Decrease brightness
    target = max_brightness - ((mean - 128) / 128) * range
```

### Smoothing Application

```python
new_brightness = current + (target - current) * (1 - smoothing)
```

## Next Steps

- [Wayland Setup](Wayland-Setup.md) - Configure Wayland screen capture
- [Multi-Monitor Setup](Multi-Monitor-Setup.md) - Per-monitor adaptive settings
- [Application Profiles](Application-Profiles.md) - Per-profile auto settings

