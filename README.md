# Monitor Control

<p align="center">
  <img src="assets/icon_128.png" alt="Monitor Control Icon" width="128">
</p>

**DDC/CI Monitor Control for Linux** - Control your monitor's brightness, contrast, color modes, and RGB gain via DDC/CI protocol.

![Linux](https://img.shields.io/badge/Linux-X11%20%7C%20Wayland-orange)
![Python](https://img.shields.io/badge/Python-3.8+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

- 🎛️ **Modern GUI** - CustomTkinter-based overlay with dark theme
- 🖥️ **Multi-Monitor Support** - Independent control per monitor with separate configs
- 🔄 **Automatic Profile Switching** - Change settings based on active application
- ☀️ **Adaptive Brightness/Contrast** - Auto-adjust based on screen content
- 🎨 **Color Mode Control** - Switch between monitor color presets
- 🔴🟢🔵 **RGB Gain Control** - Fine-tune color channels
- 💾 **Persistent Settings** - All settings saved and restored on startup

## Screenshots

![Monitor Overview GUI](docs/Overview.png)
![Monitor Settings GUI](docs/Benq.png)

## Quick Start

```bash
# Prerequisites
sudo apt install ddcutil i2c-tools
sudo modprobe i2c-dev
sudo usermod -aG i2c $USER
# Log out and back in

# Install
git clone https://github.com/Pink-o/monitor-control.git
cd monitor-control
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run
python main.py
```

> **Important:** Enable DDC/CI in your monitor's OSD settings menu.

## Usage

```bash
python main.py              # GUI mode
python main.py --detect     # List monitors
python main.py --brightness 50   # Set brightness
python main.py --no-gui     # Daemon mode
python main.py --debug      # Debug logging
```

## Documentation

📚 **[Full Documentation](docs/Home.md)**

| Guide | Description |
|-------|-------------|
| [Installation](docs/Installation.md) | Detailed setup instructions |
| [Configuration](docs/Configuration.md) | Config file reference |
| [Multi-Monitor Setup](docs/Multi-Monitor-Setup.md) | Per-monitor configuration |
| [Application Profiles](docs/Application-Profiles.md) | Automatic profile switching |
| [Adaptive Brightness](docs/Adaptive-Brightness.md) | Auto brightness/contrast setup |
| [Wayland Setup](docs/Wayland-Setup.md) | Wayland-specific configuration |
| [Troubleshooting](docs/Troubleshooting.md) | Common issues and solutions |
| [DDC/CI Reference](docs/DDC-CI-Reference.md) | VCP codes and monitor compatibility |
| [API Reference](docs/API-Reference.md) | Python API for developers |

## Configuration

Configuration files are stored in `~/.config/monitor-control/`:

- **Global config** (`config.yaml`) - Profiles and application settings
- **Per-monitor configs** (`monitors/*.yaml`) - Monitor-specific settings

See [Configuration Guide](docs/Configuration.md) for details.

## Wayland Support

Works on both X11 and Wayland. For adaptive brightness on Wayland, install a screenshot tool:

```bash
# Recommended for GNOME (silent, optimized)
./patches/build-gnome-screenshot-silent.sh

# Or use flameshot (universal)
sudo apt install flameshot
```

See [Wayland Setup Guide](docs/Wayland-Setup.md) for full instructions.

## Dependencies

| Package | Purpose |
|---------|---------|
| ddcutil | DDC/CI communication |
| customtkinter | Modern GUI |
| PyYAML | Configuration |
| Pillow + numpy | Screen analysis |
| python-xlib | X11 window monitoring |
| mss | Screenshot capture (X11) |

## License

MIT License - See [LICENSE](LICENSE) for details.

## Acknowledgments

- [ddcutil](https://www.ddcutil.com/) - DDC/CI communication tool
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) - Modern Python UI library
