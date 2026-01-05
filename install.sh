#!/bin/bash
# Monitor Control Installation Script
# ====================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config/monitor-control"
AUTOSTART_DIR="$HOME/.config/autostart"
SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "Monitor Control Installer"
echo "========================="
echo

# Check for ddcutil
if ! command -v ddcutil &> /dev/null; then
    echo "❌ ddcutil not found. Installing..."
    sudo apt install -y ddcutil i2c-tools
else
    echo "✓ ddcutil found: $(ddcutil --version | head -1)"
fi

# Enable i2c-dev module
echo
echo "Enabling I2C kernel module..."
sudo modprobe i2c-dev
if ! grep -q "i2c-dev" /etc/modules-load.d/i2c-dev.conf 2>/dev/null; then
    echo "i2c-dev" | sudo tee /etc/modules-load.d/i2c-dev.conf > /dev/null
    echo "✓ Added i2c-dev to modules-load.d"
fi

# Add user to i2c group
echo
if groups | grep -q i2c; then
    echo "✓ User already in i2c group"
else
    echo "Adding user to i2c group..."
    sudo usermod -aG i2c "$USER"
    echo "⚠ Please log out and back in for group changes to take effect"
fi

# Install Python dependencies
echo
echo "Installing Python dependencies..."
pip install -e "$SCRIPT_DIR[full]" --quiet

# Install GTK dependencies
echo
echo "Checking GTK dependencies..."
if python3 -c "import gi; gi.require_version('Gtk', '3.0')" 2>/dev/null; then
    echo "✓ GTK3 Python bindings available"
else
    echo "Installing GTK dependencies..."
    sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0
fi

# Check for AppIndicator (for better system tray on GNOME)
if python3 -c "import gi; gi.require_version('AppIndicator3', '0.1')" 2>/dev/null; then
    echo "✓ AppIndicator3 available"
else
    echo "Installing AppIndicator3..."
    sudo apt install -y gir1.2-appindicator3-0.1 || true
fi

# Install screenshot tool
if command -v scrot &> /dev/null || command -v gnome-screenshot &> /dev/null; then
    echo "✓ Screenshot tool available"
else
    echo "Installing scrot for screen capture..."
    sudo apt install -y scrot
fi

# Create config directory and copy default config
echo
echo "Setting up configuration..."
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    if [ -f "$SCRIPT_DIR/config.yaml.example" ]; then
        cp "$SCRIPT_DIR/config.yaml.example" "$CONFIG_DIR/config.yaml"
        echo "✓ Created default configuration at $CONFIG_DIR/config.yaml"
    else
        echo "⚠ No config template found - app will create default on first run"
    fi
else
    echo "✓ Configuration already exists"
fi

# Option to install autostart
echo
read -p "Install autostart entry? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    mkdir -p "$AUTOSTART_DIR"
    # Update path in desktop file
    sed "s|INSTALL_DIR|$SCRIPT_DIR|g" \
        "$SCRIPT_DIR/monitor-control.desktop" > "$AUTOSTART_DIR/monitor-control.desktop"
    echo "✓ Autostart entry installed"
fi

# Option to install systemd service
echo
read -p "Install systemd user service? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    mkdir -p "$SYSTEMD_DIR"
    sed "s|INSTALL_DIR|$SCRIPT_DIR|g" \
        "$SCRIPT_DIR/monitor-control.service" > "$SYSTEMD_DIR/monitor-control.service"
    systemctl --user daemon-reload
    echo "✓ Systemd service installed"
    echo "  Enable with: systemctl --user enable monitor-control"
    echo "  Start with:  systemctl --user start monitor-control"
fi

# Test monitor detection
echo
echo "Testing monitor detection..."
if python3 "$SCRIPT_DIR/main.py" --detect; then
    echo
    echo "✓ Installation complete!"
else
    echo
    echo "⚠ Monitor detection failed. You may need to:"
    echo "  1. Log out and back in (for i2c group)"
    echo "  2. Enable DDC/CI in your monitor's OSD settings"
    echo "  3. Run: sudo modprobe i2c-dev"
fi

echo
echo "To run Monitor Control:"
echo "  python3 $SCRIPT_DIR/main.py"
echo
echo "Edit configuration at:"
echo "  $CONFIG_DIR/config.yaml"


