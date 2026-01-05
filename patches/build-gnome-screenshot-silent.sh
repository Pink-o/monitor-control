#!/bin/bash
#
# Build optimized gnome-screenshot for Monitor Control adaptive brightness
# 
# Optimizations applied:
# 1. Screen flash disabled (silent capture)
# 2. PNG compression level 1 (fastest encoding)
# 3. Scale to 1/4 size (5MB → 600KB, e.g., 6240x2560 → 1560x640)
# 4. NEAREST interpolation (fastest scaling)
#
# These make screen capture ~10x faster for brightness analysis on GNOME Wayland
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="/tmp/gnome-screenshot-build"
INSTALL_PATH="${1:-/usr/local/bin/gnome-screenshot-silent}"

echo "=== Building Silent gnome-screenshot ==="
echo "Install path: $INSTALL_PATH"
echo ""

# Check for build dependencies
echo "Checking build dependencies..."
MISSING_DEPS=""

for cmd in meson ninja gcc pkg-config git; do
    if ! command -v $cmd &> /dev/null; then
        MISSING_DEPS="$MISSING_DEPS $cmd"
    fi
done

if [ -n "$MISSING_DEPS" ]; then
    echo "Missing build tools:$MISSING_DEPS"
    echo ""
    echo "Install with:"
    echo "  Ubuntu/Debian: sudo apt install meson ninja-build gcc pkg-config git"
    echo "  Fedora: sudo dnf install meson ninja-build gcc pkg-config git"
    echo "  Arch: sudo pacman -S meson ninja gcc pkgconf git"
    exit 1
fi

# Check for required libraries
echo "Checking library dependencies..."
MISSING_LIBS=""

for lib in gtk+-3.0 libhandy-1 libportal libportal-gtk3; do
    if ! pkg-config --exists $lib 2>/dev/null; then
        MISSING_LIBS="$MISSING_LIBS $lib"
    fi
done

if [ -n "$MISSING_LIBS" ]; then
    echo "Missing libraries:$MISSING_LIBS"
    echo ""
    echo "Install with:"
    echo "  Ubuntu/Debian: sudo apt install libgtk-3-dev libhandy-1-dev libportal-dev libportal-gtk3-dev gettext itstool"
    echo "  Fedora: sudo dnf install gtk3-devel libhandy-devel libportal-devel libportal-gtk3-devel gettext itstool"
    echo "  Arch: sudo pacman -S gtk3 libhandy libportal libportal-gtk3 gettext itstool"
    exit 1
fi

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Clone gnome-screenshot
echo ""
echo "Cloning gnome-screenshot..."
git clone --depth 1 https://gitlab.gnome.org/GNOME/gnome-screenshot.git
cd gnome-screenshot

# Apply patch
echo ""
echo "Applying silent patch..."
patch -p1 < "$SCRIPT_DIR/gnome-screenshot-silent.patch"

# Build
echo ""
echo "Building..."
meson setup build
ninja -C build

# Install
echo ""
if [[ "$INSTALL_PATH" == /usr/* ]]; then
    echo "Installing to $INSTALL_PATH (requires sudo)..."
    sudo cp build/src/gnome-screenshot "$INSTALL_PATH"
    sudo chmod +x "$INSTALL_PATH"
else
    echo "Installing to $INSTALL_PATH..."
    cp build/src/gnome-screenshot "$INSTALL_PATH"
    chmod +x "$INSTALL_PATH"
fi

# Cleanup
cd /
rm -rf "$BUILD_DIR"

echo ""
echo "=== Build Complete ==="
echo "Silent gnome-screenshot installed to: $INSTALL_PATH"
echo ""
echo "Monitor Control will automatically use this for adaptive brightness on Wayland."

