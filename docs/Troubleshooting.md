# Troubleshooting Guide

This guide covers common issues and their solutions.

## Monitor Detection Issues

### "No monitors detected"

**Causes:**
1. DDC/CI disabled on monitor
2. I2C module not loaded
3. Permission issues

**Solutions:**

1. **Enable DDC/CI on monitor:**
   - Access monitor OSD menu
   - Find Settings/System/Setup
   - Enable DDC/CI option

2. **Load I2C module:**
   ```bash
   sudo modprobe i2c-dev
   echo "i2c-dev" | sudo tee /etc/modules-load.d/i2c-dev.conf
   ```

3. **Check I2C devices:**
   ```bash
   ls /dev/i2c-*
   ```

4. **Test with ddcutil:**
   ```bash
   ddcutil detect
   ```

### "Permission denied" accessing I2C

**Solution:**
```bash
sudo usermod -aG i2c $USER
# Log out and back in
```

Verify:
```bash
groups | grep i2c
```

### Monitor detected but not responding

**Causes:**
1. Monitor needs longer delays
2. Wrong display number
3. Monitor busy

**Solutions:**

1. **Increase sleep multiplier:**
   ```yaml
   # config.yaml
   monitor:
     ddc:
       sleep_multiplier: 2.0
   ```

2. **Verify display number:**
   ```bash
   ddcutil detect
   # Note the display number
   ddcutil getvcp 10 --display 1
   ```

3. **Wait and retry:**
   Some monitors need time between commands.

## DDC Communication Issues

### "DDC command failed" / Timeouts

**Solutions:**

1. **Increase retries:**
   ```yaml
   monitor:
     ddc:
       retry_count: 5
   ```

2. **Check cable quality:**
   - Use high-quality DisplayPort/HDMI cable
   - Avoid adapters if possible

3. **Test specific VCP code:**
   ```bash
   ddcutil getvcp 0x10 --display 1
   ```

### "Feature not supported"

**Cause:** Monitor doesn't support the VCP code.

**Solutions:**

1. **Check capabilities:**
   ```bash
   ddcutil capabilities --display 1
   ```

2. **Feature is marked unsupported:**
   The app automatically disables unsupported features. Check per-monitor config:
   ```yaml
   unsupported_features:
     - 0x87  # Sharpness
   ```

### RGB Gain not changing

**Cause:** RGB Gain only works in "User" color mode.

**Solution:**
1. Switch to User/Custom color mode first
2. Then adjust RGB values

## GUI Issues

### GUI not starting

**Solutions:**

1. **Check display:**
   ```bash
   echo $DISPLAY
   # Should be :0 or :1
   ```

2. **Install CustomTkinter:**
   ```bash
   pip install customtkinter
   ```

3. **Check Tk installation:**
   ```bash
   python3 -c "import tkinter; print('OK')"
   ```

### GUI freezes during DDC commands

**Cause:** DDC commands blocking main thread.

**Solution:** This should not happen in current version. Update to latest:
```bash
git pull
pip install -r requirements.txt --upgrade
```

### Sliders affecting wrong monitor

**Cause:** Lambda closure bug (fixed in latest version).

**Solution:**
```bash
git pull
```

The fix ensures each slider callback captures the correct `display_num`.

## Profile Switching Issues

### Profile not switching automatically

**Solutions:**

1. **Check auto profile is enabled:**
   - In GUI: Verify 📁 toggle is ON
   - In config: `auto_profile: true`

2. **Verify window class:**
   ```bash
   xprop | grep WM_CLASS
   ```

3. **Check profile matches:**
   ```yaml
   profiles:
     - name: "coding"
       match:
         window_class:
           - "code"  # Must match exactly
   ```

4. **Check priority:**
   Higher priority profiles override lower ones.

5. **Enable debug logging:**
   ```bash
   python main.py --debug 2>&1 | grep -i profile
   ```

### Profile switches to wrong monitor

**Cause:** Window position detection issue.

**Solutions:**

1. **Check monitor geometry:**
   ```bash
   xrandr --query
   ```

2. **Verify display arrangement:**
   System Settings → Displays

3. **Restart after display changes:**
   The app caches geometry on startup.

### Color mode not applying

**Solutions:**

1. **Verify color mode exists:**
   ```bash
   ddcutil getvcp 0xdc --display 1
   ```

2. **Check per-monitor config:**
   ```yaml
   profile_color_modes:
     coding: 31  # Must match monitor's actual value
   ```

3. **Test manually:**
   ```bash
   ddcutil setvcp 0xdc 31 --display 1
   ```

## Adaptive Brightness Issues

### "All screen capture methods failed"

**On X11:**
```bash
pip install mss
```

**On Wayland:**
Install a screenshot tool:
```bash
sudo apt install flameshot
# or build gnome-screenshot-silent
./patches/build-gnome-screenshot-silent.sh
```

### Both monitors show same brightness values

**Cause:** Monitor regions not detected correctly.

**Solutions:**

1. **Check geometry detection:**
   ```bash
   python main.py --debug 2>&1 | grep -i geometry
   ```

2. **Verify xrandr output:**
   ```bash
   xrandr --query
   ```

3. **Restart after display changes.**

### Brightness changes too slowly/quickly

**Solution:** Adjust smoothing:
```yaml
adaptive_settings:
  smoothing: 0.5  # Higher = slower
```

### Brightness oscillating

**Cause:** Screen content changes trigger adjustments.

**Solutions:**

1. **Narrow the range:**
   ```yaml
   min_brightness: 35
   max_brightness: 55
   ```

2. **Increase smoothing:**
   ```yaml
   smoothing: 0.6
   ```

3. **Increase interval:**
   ```yaml
   interval: 3.0
   ```

### High CPU usage

**Solutions:**

1. **Increase interval:**
   ```yaml
   interval: 5.0
   ```

2. **Use optimized screenshot tool:**
   - gnome-screenshot-silent has built-in downscaling

## Configuration Issues

### Config not loading

**Solutions:**

1. **Check file location:**
   ```bash
   ls ~/.config/monitor-control/
   ```

2. **Validate YAML syntax:**
   ```bash
   python -c "import yaml; yaml.safe_load(open('config.yaml'))"
   ```

3. **Check permissions:**
   ```bash
   ls -la ~/.config/monitor-control/
   ```

### Per-monitor config not created

**Cause:** Monitor not properly detected.

**Solutions:**

1. **Check ddcutil detection:**
   ```bash
   ddcutil detect
   ```

2. **Force config creation:**
   Run the app, open each monitor's tab.

### Settings not saving

**Solutions:**

1. **Check write permissions:**
   ```bash
   touch ~/.config/monitor-control/test
   ```

2. **Check disk space:**
   ```bash
   df -h ~/.config
   ```

## Wayland-Specific Issues

> **Note:** See [Wayland Setup - Known Limitations](Wayland-Setup.md#known-limitations) for detailed information.

### Snap applications not detected

**Cause:** Snap's sandboxing prevents AT-SPI from accessing window information.

**Symptoms:**
- Window class shows as "unknown" or empty
- Auto profile switching doesn't trigger

**Workarounds:**
1. Install via apt/dnf instead of Snap
2. Use Flatpak versions (better AT-SPI support)
3. Manually select profiles

**Commonly affected:**
- Firefox (Snap on Ubuntu 22.04+)
- VS Code (Snap version)
- Chromium (Snap version)

### Window position always (0,0) in multi-monitor

**Cause:** Wayland security prevents absolute position access for some apps.

**Symptoms:**
- Profile switches apply to wrong monitor
- Debug log shows `position: (0, 0)` for windows not at top-left

**Affected apps:**
- Some Electron apps
- Some GTK4 applications
- Certain XWayland applications

**Workarounds:**
1. Keep related windows on primary monitor
2. Manually select profiles
3. Disable per-monitor profile isolation

**Diagnosis:**
```bash
python main.py --debug 2>&1 | grep -E "position|geometry"
```

### Window detection not working

**Solutions:**

1. **Enable accessibility:**
   ```bash
   gsettings set org.gnome.desktop.interface toolkit-accessibility true
   ```

2. **Install AT-SPI:**
   ```bash
   sudo apt install python3-gi gir1.2-atspi-2.0
   ```

3. **Install libwnck for XWayland apps:**
   ```bash
   sudo apt install gir1.2-wnck-3.0
   ```

### Screen capture shows black image

**Causes:**
1. Portal permission not granted
2. Compositor blocking capture

**Solutions:**

1. **Grant portal permission:**
   - First capture triggers dialog
   - Click "Allow"

2. **Check GNOME settings:**
   - Settings → Privacy → Screen Recording

### gnome-screenshot-silent build fails

**Solutions:**

1. **Install all dependencies:**
   ```bash
   sudo apt install meson ninja-build gcc pkg-config git \
                    libgtk-3-dev libhandy-1-dev libportal-dev \
                    libportal-gtk3-dev gettext itstool
   ```

2. **Check build output:**
   ```bash
   ./patches/build-gnome-screenshot-silent.sh 2>&1 | tail -50
   ```

## Logging and Debugging

### Enable debug logging

```bash
python main.py --debug
```

### Filter specific issues

```bash
# DDC issues
python main.py --debug 2>&1 | grep -i ddc

# Profile issues
python main.py --debug 2>&1 | grep -i profile

# Capture issues
python main.py --debug 2>&1 | grep -i capture

# Monitor issues
python main.py --debug 2>&1 | grep -i monitor
```

### Log file location

```
~/.local/share/monitor-control/monitor-control.log
```

### Systemd service logs

```bash
journalctl --user -u monitor-control -f
```

## Getting Help

### Information to include in bug reports

1. **System info:**
   ```bash
   uname -a
   echo $XDG_SESSION_TYPE
   python3 --version
   ```

2. **Monitor info:**
   ```bash
   ddcutil detect
   ddcutil capabilities --display 1
   ```

3. **Debug log:**
   ```bash
   python main.py --debug 2>&1 | head -200
   ```

4. **Config files:**
   - `~/.config/monitor-control/config.yaml`
   - `~/.config/monitor-control/monitors/*.yaml`

### Useful commands summary

| Command | Purpose |
|---------|---------|
| `ddcutil detect` | List monitors |
| `ddcutil capabilities` | Show monitor features |
| `ddcutil getvcp 0x10` | Read brightness |
| `xrandr --query` | Display layout |
| `xprop \| grep WM_CLASS` | Window class |
| `python main.py --debug` | Debug logging |

## Next Steps

- [Installation](Installation.md) - Verify setup
- [Configuration](Configuration.md) - Check settings
- [Wayland Setup](Wayland-Setup.md) - Wayland-specific help

