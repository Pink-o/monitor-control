# Wayland Setup Guide

Monitor Control works on both X11 and Wayland, but Wayland requires additional setup due to its stricter security model.

## What Works on Wayland

| Feature | Status | Notes |
|---------|--------|-------|
| DDC/CI Control | ✅ Full | Brightness, contrast, color modes, RGB |
| Multi-Monitor | ✅ Full | Per-monitor configs and settings |
| Application Profiles | ✅ Full | Automatic switching |
| Window Detection | ✅ Full | AT-SPI + libwnck hybrid |
| GUI | ✅ Full | CustomTkinter works natively |
| Adaptive Brightness | ⚠️ Setup Required | Needs screenshot tool |
| Screen Analysis | ⚠️ Setup Required | Needs screenshot tool |

## Screen Capture Setup

Wayland prevents direct screen capture for security. You need to install an external screenshot tool.

### Option 1: Silent gnome-screenshot (GNOME - Recommended)

Build a patched version without screen flash:

```bash
cd /path/to/monitor-control
./patches/build-gnome-screenshot-silent.sh
```

**Build Dependencies:**

Ubuntu/Debian:
```bash
sudo apt install meson ninja-build gcc pkg-config git \
                 libgtk-3-dev libhandy-1-dev libportal-dev \
                 libportal-gtk3-dev gettext itstool
```

Fedora:
```bash
sudo dnf install meson ninja-build gcc pkg-config git \
                 gtk3-devel libhandy-devel libportal-devel \
                 libportal-gtk3-devel gettext itstool
```

Arch:
```bash
sudo pacman -S meson ninja gcc pkgconf git gtk3 libhandy \
               libportal gettext itstool
```

**What the patch does:**

1. **Disables screen flash** - No visual disruption
2. **Fast PNG compression** (level 1) - Faster encoding
3. **Downscales to 1/4 size** - Faster processing (~5MB → ~600KB)
4. **NEAREST interpolation** - Fastest scaling

**Installation location:**
```
/usr/local/bin/gnome-screenshot-silent
```

The app automatically detects and uses this version.

### Option 2: Flameshot (Universal)

Works on GNOME, KDE, and other desktops:

```bash
# Ubuntu/Debian
sudo apt install flameshot

# Fedora
sudo dnf install flameshot

# Arch
sudo pacman -S flameshot
```

**Note:** Flameshot may show a brief notification on each capture.

### Option 3: Standard gnome-screenshot (GNOME)

```bash
sudo apt install gnome-screenshot
```

**Note:** Shows a screen flash on each capture, which can be distracting.

### Option 4: grim (Sway/wlroots)

For Sway and other wlroots-based compositors:

```bash
sudo apt install grim
```

**Note:** Very fast (~0.5s), but only works on wlroots compositors.

### Option 5: spectacle (KDE)

For KDE Plasma:

```bash
sudo apt install spectacle
```

## Screenshot Tool Detection Order

The app tries screenshot tools in this order:

1. `/usr/local/bin/gnome-screenshot-silent` (custom build)
2. `/tmp/gnome-screenshot-silent` (temporary build)
3. `flameshot` (if installed)
4. `gnome-screenshot` (if installed)
5. `grim` (if installed)
6. `spectacle` (if installed)

Once a working method is found, it's cached for the session.

## Window Detection Setup

### AT-SPI (Recommended)

AT-SPI (Assistive Technology Service Provider Interface) provides window information for native Wayland applications:

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

**Enable accessibility services:**

1. Open GNOME Settings
2. Go to Accessibility
3. Enable accessibility features

Or via gsettings:
```bash
gsettings set org.gnome.desktop.interface toolkit-accessibility true
```

### libwnck (For XWayland apps)

libwnck provides window information for XWayland applications:

```bash
sudo apt install gir1.2-wnck-3.0
```

### Hybrid Detection

The app uses both AT-SPI and libwnck together:

- **Native Wayland apps** → AT-SPI
- **XWayland apps** → libwnck
- **Fallback** → D-Bus/GIO

## Wayland-Specific Intervals

Due to screenshot tool overhead, Wayland has longer minimum intervals:

| Platform | Minimum Interval | Recommended |
|----------|------------------|-------------|
| X11 | 0.5s | 1.0-2.0s |
| Wayland | 2.5s | 3.0s |

The GUI slider automatically enforces these minimums.

## GNOME-Specific Setup

### Portal Permissions

GNOME uses XDG portals for screenshot access. The first screenshot may trigger a permission dialog.

**Grant permission permanently:**

The app requests screenshot permission via the portal. Click "Allow" when prompted.

### Screen Recording Permission

Some GNOME versions require screen recording permission:

1. Settings → Privacy → Screen Recording
2. Allow Monitor Control

### Disable Screen Flash (Alternative)

If you can't build gnome-screenshot-silent, you can disable the flash via dconf:

```bash
# This may not work on all GNOME versions
gsettings set org.gnome.gnome-screenshot include-pointer false
```

## KDE-Specific Setup

### Spectacle Configuration

Configure spectacle for background capture:

```bash
# Set to capture without GUI
spectacle --background --fullscreen --output /tmp/screenshot.png
```

### KWin Scripts

For advanced window detection, ensure KWin scripts are enabled:

```bash
qdbus org.kde.KWin /KWin supportInformation
```

## Sway/wlroots Setup

### grim + slurp

For region capture on Sway:

```bash
sudo apt install grim slurp
```

The app uses grim for full-screen capture, which is faster.

### Sway IPC

Window detection on Sway uses Sway IPC:

```bash
swaymsg -t get_tree
```

## Troubleshooting

### "All screen capture methods failed"

1. **Check tool installation:**
   ```bash
   which flameshot gnome-screenshot grim spectacle
   ```

2. **Test manually:**
   ```bash
   gnome-screenshot -f /tmp/test.png
   # or
   flameshot full -p /tmp/test.png
   ```

3. **Check permissions:**
   - GNOME: Settings → Privacy → Screen Recording
   - Verify portal access

### Screen Capture Shows Black Image

1. **Portal permission needed:**
   - First capture triggers permission dialog
   - Grant access and retry

2. **Compositor compatibility:**
   - Some compositors block capture
   - Check compositor settings

### Window Detection Not Working

1. **Enable accessibility:**
   ```bash
   gsettings set org.gnome.desktop.interface toolkit-accessibility true
   ```

2. **Install AT-SPI:**
   ```bash
   sudo apt install gir1.2-atspi-2.0
   ```

3. **Check AT-SPI daemon:**
   ```bash
   ps aux | grep at-spi
   ```

### Slow Screen Capture

Wayland capture is inherently slower than X11. Mitigations:

1. **Use gnome-screenshot-silent** - optimized with 1/4 scaling
2. **Increase interval** - reduce capture frequency
3. **Use grim on Sway** - fastest Wayland option

### High CPU During Capture

1. **Increase interval:**
   ```yaml
   interval: 3.0
   ```

2. **Use optimized tool:**
   - gnome-screenshot-silent has built-in downscaling

## Performance Comparison

| Method | Capture Time | Notes |
|--------|--------------|-------|
| mss (X11) | ~30ms | Fastest, X11 only |
| grim (Sway) | ~500ms | Fast, wlroots only |
| gnome-screenshot-silent | ~2.5s | GNOME, silent |
| gnome-screenshot | ~2.5s | GNOME, has flash |
| flameshot | ~1-2s | Universal |
| spectacle | ~1-2s | KDE |

## Verifying Wayland Setup

### Check Session Type

```bash
echo $XDG_SESSION_TYPE
# Should output: wayland
```

### Test Window Detection

```bash
python main.py --debug 2>&1 | grep -i "window\|wayland"
```

### Test Screen Capture

```bash
python main.py --debug 2>&1 | grep -i "capture\|screenshot"
```

### Full Diagnostic

```bash
python main.py --debug 2>&1 | head -100
```

Look for:
- "Wayland detected"
- "Using gnome-screenshot-silent"
- "Window: <app_name>"

## Next Steps

- [Adaptive Brightness](Adaptive-Brightness.md) - Configure auto brightness
- [Troubleshooting](Troubleshooting.md) - More solutions
- [Installation](Installation.md) - General setup

