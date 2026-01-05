# Installation Guide

This guide covers installing Monitor Control on Linux systems.

## Prerequisites

### 1. Install ddcutil

ddcutil is required for DDC/CI communication with your monitor.

**Ubuntu/Debian:**
```bash
sudo apt install ddcutil i2c-tools
```

**Fedora:**
```bash
sudo dnf install ddcutil i2c-tools
```

**Arch Linux:**
```bash
sudo pacman -S ddcutil i2c-tools
```

### 2. Load I2C Kernel Module

```bash
# Load the module
sudo modprobe i2c-dev

# Make it permanent (loads on boot)
echo "i2c-dev" | sudo tee /etc/modules-load.d/i2c-dev.conf
```

### 3. Set Up I2C Permissions

Add your user to the `i2c` group to avoid running as root:

```bash
sudo usermod -aG i2c $USER
```

**Important:** Log out and back in for the group change to take effect.

### 4. Verify I2C Access

```bash
# Check I2C devices exist
ls /dev/i2c-*

# Test ddcutil can detect your monitor
ddcutil detect
```

### 5. Enable DDC/CI on Your Monitor

Most monitors have DDC/CI disabled by default. Enable it in your monitor's OSD:

1. Press the menu button on your monitor
2. Navigate to Settings/System/Setup (varies by manufacturer)
3. Find DDC/CI option and enable it
4. Save and exit

## Installing Monitor Control

### Method 1: From Source (Recommended)

```bash
# Clone the repository
git clone https://github.com/Pink-o/monitor-control.git
cd monitor-control

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy example config (optional - app creates default on first run)
cp config.yaml.example config.yaml

# Run the application
python main.py
```

### Method 2: Using install.sh

The install script automates the setup process:

```bash
git clone https://github.com/Pink-o/monitor-control.git
cd monitor-control
./install.sh
```

The script will:
- Install ddcutil if missing
- Configure I2C permissions
- Install Python dependencies
- Optionally set up autostart
- Optionally install systemd service

## Dependencies

### Required Python Packages

| Package | Version | Purpose |
|---------|---------|---------|
| customtkinter | ≥5.0.0 | Modern GUI framework |
| PyYAML | ≥6.0 | Configuration file parsing |
| Pillow | ≥9.0.0 | Image processing |
| numpy | ≥1.20.0 | Screen brightness calculations |

### Optional: X11 Support

```bash
pip install python-xlib mss
```

- **python-xlib** - Native X11 window monitoring
- **mss** - Fast screenshot capture (silent)

### Optional: Wayland Support

See [Wayland Setup](Wayland-Setup.md) for detailed instructions.

```bash
# Window monitoring
sudo apt install python3-gi gir1.2-atspi-2.0 gir1.2-wnck-3.0

# Screen capture (choose one)
sudo apt install flameshot      # Universal
sudo apt install gnome-screenshot  # GNOME
sudo apt install grim           # Sway/wlroots
sudo apt install spectacle      # KDE
```

## Desktop Integration

### Autostart on Login

Copy the desktop file to autostart:

```bash
mkdir -p ~/.config/autostart
cp monitor-control.desktop ~/.config/autostart/

# Edit to update the path
nano ~/.config/autostart/monitor-control.desktop
```

Update the `Exec` and `Icon` paths to match your installation.

### Systemd User Service

For headless/daemon mode:

```bash
mkdir -p ~/.config/systemd/user
cp monitor-control.service ~/.config/systemd/user/

# Edit to update the path
nano ~/.config/systemd/user/monitor-control.service

# Enable and start
systemctl --user daemon-reload
systemctl --user enable monitor-control
systemctl --user start monitor-control

# Check status
systemctl --user status monitor-control
journalctl --user -u monitor-control -f
```

## Verifying Installation

### 1. Test Monitor Detection

```bash
python main.py --detect
```

Expected output:
```
Detected monitors:
  Display 1:
    Model:        Your Monitor Model
    Manufacturer: MFG
    Serial:       ABC123
    I2C Bus:      /dev/i2c-X
```

### 2. Test Monitor Capabilities

```bash
python main.py --capabilities
```

This shows all VCP codes your monitor supports.

### 3. Test Basic Control

```bash
# Set brightness to 50%
python main.py --brightness 50

# Set contrast to 60%
python main.py --contrast 60
```

### 4. Launch GUI

```bash
python main.py
```

## Updating

```bash
cd monitor-control
git pull
source venv/bin/activate
pip install -r requirements.txt --upgrade
```

## Uninstalling

```bash
# Remove autostart
rm ~/.config/autostart/monitor-control.desktop

# Remove systemd service
systemctl --user disable monitor-control
rm ~/.config/systemd/user/monitor-control.service

# Remove config
rm -rf ~/.config/monitor-control

# Remove application
rm -rf /path/to/monitor-control
```

## Next Steps

- [Configuration](Configuration.md) - Configure your monitors
- [Application Profiles](Application-Profiles.md) - Set up automatic profile switching
- [Troubleshooting](Troubleshooting.md) - If you encounter issues

