# Monitor Control Wiki

Welcome to the Monitor Control documentation! This wiki provides comprehensive guides for installing, configuring, and using Monitor Control.

## What is Monitor Control?

Monitor Control is a Linux desktop application that controls your monitor's settings via DDC/CI (Display Data Channel Command Interface). It provides:

- **Brightness, Contrast, Sharpness Control** - Adjust monitor settings without touching the OSD
- **Color Mode Switching** - Quick access to monitor color presets
- **RGB Gain Control** - Fine-tune red, green, and blue channels
- **Automatic Profile Switching** - Change settings based on the active application
- **Adaptive Brightness/Contrast** - Automatically adjust based on screen content
- **Multi-Monitor Support** - Independent control of each connected monitor

## Quick Start

```bash
# Clone and install
git clone https://github.com/YOUR_USERNAME/monitor-control.git
cd monitor-control
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run
python main.py
```

## Documentation Index

### Getting Started
- [Installation](Installation.md) - Complete installation guide
- [Configuration](Configuration.md) - Configuration file reference
- [Troubleshooting](Troubleshooting.md) - Common issues and solutions

### Features
- [Multi-Monitor Setup](Multi-Monitor-Setup.md) - Per-monitor configuration
- [Application Profiles](Application-Profiles.md) - Automatic profile switching
- [Adaptive Brightness](Adaptive-Brightness.md) - Screen content-based adjustments

### Platform Specific
- [Wayland Setup](Wayland-Setup.md) - Wayland-specific configuration

### Reference
- [DDC/CI Reference](DDC-CI-Reference.md) - VCP codes and monitor compatibility
- [API Reference](API-Reference.md) - Python API for developers

## System Requirements

| Requirement | Details |
|-------------|---------|
| **OS** | Linux (X11 or Wayland) |
| **Python** | 3.8 or higher |
| **Monitor** | DDC/CI compatible (most modern monitors) |
| **Dependencies** | ddcutil, i2c-tools |

## Support

- **Issues**: [GitHub Issues](https://github.com/YOUR_USERNAME/monitor-control/issues)
- **Discussions**: [GitHub Discussions](https://github.com/YOUR_USERNAME/monitor-control/discussions)

## License

MIT License - See [LICENSE](../LICENSE) for details.

