# Application Profiles

Application profiles automatically switch monitor settings based on the active application.

## How Profiles Work

1. **Window Monitoring** - The app monitors which window has focus
2. **Pattern Matching** - Window class or title is matched against profile rules
3. **Profile Selection** - Highest priority matching profile is selected
4. **Settings Applied** - Color mode, brightness, contrast are applied

## Profile Structure

```yaml
profiles:
  - name: "profile_name"        # Unique identifier
    priority: 10                # Higher number = higher priority
    match:
      window_class:             # WM_CLASS patterns
        - "pattern1"
        - "pattern2"
      window_title:             # Window title patterns
        - "*pattern*"
    auto_brightness: false      # Per-profile auto brightness
    auto_contrast: false        # Per-profile auto contrast
    settings:
      color_preset: Mode        # Color mode name
      brightness: 50            # Initial brightness
      contrast: 50              # Initial contrast
```

## Window Matching

### Window Class Matching

Window class (WM_CLASS) is the most reliable matching method. To find an application's window class:

**Using xprop (X11):**
```bash
xprop | grep WM_CLASS
# Click on the window
# Output: WM_CLASS(STRING) = "code", "Code"
```

**Using the app's detection:**
The GUI shows the current window class in the Application Profiles section.

### Window Title Matching

Window title matching uses glob patterns:

```yaml
window_title:
  - "*YouTube*"           # Contains "YouTube"
  - "Netflix*"            # Starts with "Netflix"
  - "*Visual Studio Code" # Ends with "Visual Studio Code"
```

### Priority System

When multiple profiles match, the highest priority wins:

```yaml
profiles:
  - name: "browser"
    priority: 8           # Lower priority
    match:
      window_class: ["firefox", "chrome"]
      
  - name: "video"
    priority: 20          # Higher priority
    match:
      window_class: ["firefox", "chrome"]
      window_title: ["*YouTube*", "*Netflix*"]
```

In this example:
- Firefox showing YouTube → "video" profile (priority 20)
- Firefox showing regular page → "browser" profile (priority 8)

## Built-in Profile Examples

### Coding Profile

```yaml
- name: "coding"
  priority: 10
  match:
    window_class:
      - "code"
      - "Code"
      - "cursor"
      - "Cursor"
      - "jetbrains-*"
      - "vim"
      - "nvim"
      - "emacs"
      - "sublime_text"
      - "Alacritty"
      - "kitty"
      - "gnome-terminal"
      - "konsole"
    window_title:
      - "*Visual Studio Code*"
      - "*Cursor*"
  auto_brightness: false    # Stable brightness for focus
  auto_contrast: false
  settings:
    color_preset: ePaper    # Low blue light
    brightness: 35
    contrast: 50
```

### Video Profile

```yaml
- name: "video"
  priority: 20
  match:
    window_class:
      - "vlc"
      - "mpv"
      - "totem"
      - "celluloid"
      - "firefox"
      - "chromium"
      - "chrome"
    window_title:
      - "*YouTube*"
      - "*Netflix*"
      - "*Prime Video*"
      - "*VLC*"
      - "*mpv*"
  auto_brightness: false    # Fixed for video
  auto_contrast: false
  settings:
    color_preset: Cinema
    brightness: 50
    contrast: 55
```

### Gaming Profile

```yaml
- name: "gaming"
  priority: 25
  match:
    window_class:
      - "steam_app_*"
      - "Steam"
      - "lutris"
      - "heroic"
    window_title: []
  auto_brightness: false
  auto_contrast: false
  settings:
    color_preset: Game
    brightness: 45
    contrast: 60
```

### Photo Editing Profile

```yaml
- name: "photo"
  priority: 15
  match:
    window_class:
      - "gimp*"
      - "Gimp*"
      - "darktable"
      - "rawtherapee"
      - "inkscape"
      - "krita"
    window_title: []
  auto_brightness: false    # Color accuracy requires stable settings
  auto_contrast: false
  settings:
    color_preset: sRGB
    brightness: 40
    contrast: 50
```

### Browser Profile

```yaml
- name: "browser"
  priority: 8
  match:
    window_class:
      - "firefox"
      - "Firefox"
      - "Navigator"
      - "chromium"
      - "Chromium"
      - "chrome"
      - "Google-chrome"
      - "brave"
      - "Brave-browser"
    window_title: []
  auto_brightness: true     # Adaptive for varying content
  auto_contrast: false
  settings:
    color_preset: sRGB
    brightness: 40
    contrast: 50
```

### CAD/3D Modeling Profile

```yaml
- name: "cad"
  priority: 15
  match:
    window_class:
      - "freecad"
      - "FreeCAD"
      - "blender"
      - "Blender"
      - "openscad"
      - "kicad"
      - "fusion360"
    window_title: []
  auto_brightness: false
  auto_contrast: false
  settings:
    color_preset: HDR       # Wide color gamut
    brightness: 40
    contrast: 50
```

## Default Profile

When no application matches, the default profile is used:

```yaml
default_profile:
  name: "default"
  auto_brightness: true     # Adaptive by default
  auto_contrast: false
  settings:
    color_preset: Standard
    brightness: 40
    contrast: 50
```

## Per-Profile Auto Settings

Each profile can have independent auto brightness/contrast settings:

```yaml
- name: "reading"
  auto_brightness: true     # Enabled for reading
  auto_contrast: false
  
- name: "photo"
  auto_brightness: false    # Disabled for color accuracy
  auto_contrast: false
  
- name: "video"
  auto_brightness: false    # Fixed for video
  auto_contrast: false
```

These settings are saved per-profile and persist across sessions.

## GUI Profile Management

### Viewing Profiles

Each monitor tab shows all profiles with:
- Profile name button (click to activate)
- Color mode dropdown
- Auto brightness toggle (☀️)
- Auto contrast toggle (◐)
- Add app button (+)

### Adding Apps to Profiles

1. Focus the application window you want to add
2. Open Monitor Control
3. Go to the monitor tab
4. Find the profile you want
5. Click the **+** button

The current window's class is automatically added to that profile.

### Changing Profile Color Modes

1. Find the profile in the monitor tab
2. Use the dropdown to select a color mode
3. If the profile is active, the change applies immediately

### Manual Profile Selection

Click the profile name button to manually activate a profile. This overrides automatic matching until you click another profile or enable auto-switching again.

## Fullscreen-Only Mode

Enable fullscreen-only to trigger profiles only when windows are fullscreen or maximized:

```yaml
# In per-monitor config
fullscreen_only: true
```

This is useful for:
- Gaming monitors - only change when game is fullscreen
- Video monitors - only change for fullscreen video

## Multi-Monitor Profiles

Profiles apply per-monitor. The same profile can have different color modes on different monitors:

**Monitor 1 (BenQ):**
```yaml
profile_color_modes:
  coding: 31    # ePaper
  video: 50     # Cinema
```

**Monitor 2 (Dell):**
```yaml
profile_color_modes:
  coding: 4     # Paper
  video: 2      # Movie
```

## Adding Custom Profiles

### Step 1: Identify Window Class

```bash
# X11
xprop | grep WM_CLASS

# Or watch the GUI - it shows current window class
```

### Step 2: Add to config.yaml

```yaml
profiles:
  - name: "my_app"
    priority: 15
    match:
      window_class:
        - "my-application"
    auto_brightness: false
    auto_contrast: false
    settings:
      color_preset: Standard
      brightness: 45
      contrast: 50
```

### Step 3: Restart or Reload

The app loads profiles on startup. Restart to apply changes.

## Profile Tips

### 1. Use Specific Window Classes

```yaml
# Good - specific
window_class: ["jetbrains-idea"]

# Less good - might match unintended apps
window_class: ["java"]
```

### 2. Use Priority Wisely

```
Priority 5-10:  General apps (browsers, file managers)
Priority 10-15: Work apps (IDEs, office)
Priority 15-20: Specialized apps (photo editing, CAD)
Priority 20-25: Media (video, games)
```

### 3. Test with Debug Mode

```bash
python main.py --debug 2>&1 | grep -i profile
```

### 4. Consider Auto Settings

- **Reading/Coding**: Stable brightness preferred
- **Browsing**: Adaptive brightness helpful
- **Photo/Video**: Fixed settings for accuracy

## Troubleshooting

### Profile Not Switching

1. Check window class matches:
   ```bash
   xprop | grep WM_CLASS
   ```
2. Check priority - higher priority profiles may be matching
3. Enable debug logging to see matching:
   ```bash
   python main.py --debug
   ```

### Wrong Profile Activating

Check for overlapping patterns. A browser profile might match when you want video:

```yaml
# Browser matches all Firefox
window_class: ["firefox"]

# Video should have higher priority AND more specific match
priority: 20
window_title: ["*YouTube*"]
```

### Profile Changes Not Applying

1. Check if color mode is supported by monitor
2. Verify per-monitor config has the color mode mapped
3. Check DDC communication:
   ```bash
   ddcutil getvcp 0xdc
   ```

## Next Steps

- [Adaptive Brightness](Adaptive-Brightness.md) - Configure auto brightness/contrast
- [Multi-Monitor Setup](Multi-Monitor-Setup.md) - Per-monitor profiles
- [Configuration](Configuration.md) - Full config reference

