# DDC/CI Reference

DDC/CI (Display Data Channel Command Interface) is a communication protocol for controlling monitor settings via the I2C bus.

## Overview

### What is DDC/CI?

DDC/CI allows software to:
- Read and write monitor settings
- Query monitor capabilities
- Control brightness, contrast, color modes, etc.

### How It Works

```
┌──────────┐    I2C Bus    ┌──────────┐
│ Computer │ ─────────────▶│ Monitor  │
│ (Host)   │◀───────────── │ (Device) │
└──────────┘               └──────────┘
```

1. Host sends VCP code and value
2. Monitor processes command
3. Monitor sends response (for reads)

### Requirements

- **Monitor:** DDC/CI enabled in OSD
- **Connection:** DisplayPort, HDMI, DVI (not all adapters work)
- **Software:** ddcutil on Linux

## VCP (Virtual Control Panel) Codes

VCP codes are standardized feature identifiers defined by VESA.

### Standard Codes Used by Monitor Control

| Code | Name | Range | Description |
|------|------|-------|-------------|
| 0x10 | Brightness | 0-100 | Display brightness level |
| 0x12 | Contrast | 0-100 | Display contrast level |
| 0x14 | Color Preset | varies | Color temperature preset |
| 0x16 | Red Gain | 0-100 | Red channel gain |
| 0x18 | Green Gain | 0-100 | Green channel gain |
| 0x1A | Blue Gain | 0-100 | Blue channel gain |
| 0x60 | Input Source | varies | Video input selection |
| 0x87 | Sharpness | 0-100 | Image sharpness |
| 0x8A | Color Saturation | 0-100 | Color saturation level |
| 0xDC | Display Mode | varies | Picture mode / color profile |

### Color Temperature Presets (0x14)

Common values for VCP 0x14:

| Value | Description |
|-------|-------------|
| 0x01 | sRGB |
| 0x02 | Display Native |
| 0x03 | 4000K |
| 0x04 | 5000K |
| 0x05 | 6500K |
| 0x06 | 7500K |
| 0x07 | 8200K |
| 0x08 | 9300K |
| 0x09 | 10000K |
| 0x0A | 11500K |
| 0x0B | User 1 |
| 0x0C | User 2 |
| 0x0D | User 3 |

**Note:** Actual values vary by manufacturer. Use `ddcutil capabilities` to check your monitor.

### Display Mode (0xDC)

VCP 0xDC controls picture modes. Values are manufacturer-specific:

**Example (BenQ):**
| Value | Mode |
|-------|------|
| 0x00 | Standard |
| 0x0A | sRGB |
| 0x0F | M-book |
| 0x12 | User |
| 0x1F | ePaper |
| 0x23 | HDR |
| 0x30 | Dark Theme |
| 0x31 | Light Theme |
| 0x32 | Cinema |

**Example (Dell):**
| Value | Mode |
|-------|------|
| 0x00 | Standard |
| 0x01 | Multimedia |
| 0x02 | Movie |
| 0x03 | Game |
| 0x04 | Paper |
| 0x05 | Color Temp |
| 0x06 | sRGB |
| 0x07 | Custom |

### Input Source (0x60)

Common input source values:

| Value | Input |
|-------|-------|
| 0x01 | VGA-1 |
| 0x02 | VGA-2 |
| 0x03 | DVI-1 |
| 0x04 | DVI-2 |
| 0x0F | DisplayPort-1 |
| 0x10 | DisplayPort-2 |
| 0x11 | HDMI-1 |
| 0x12 | HDMI-2 |

## Using ddcutil

### Detect Monitors

```bash
ddcutil detect
```

Output:
```
Display 1
   I2C bus:  /dev/i2c-5
   EDID synopsis:
      Mfg id:               BNQ
      Model:                BenQ RD280UA
      Serial number:        ABC12345
   VCP version:         2.1
```

### Query Capabilities

```bash
ddcutil capabilities --display 1
```

Shows all supported VCP features and their valid values.

### Read a VCP Value

```bash
# Read brightness
ddcutil getvcp 0x10 --display 1

# Output:
# VCP code 0x10 (Brightness): current value = 50, max value = 100
```

### Write a VCP Value

```bash
# Set brightness to 60
ddcutil setvcp 0x10 60 --display 1

# Set color mode to sRGB (value 10)
ddcutil setvcp 0xdc 10 --display 1
```

### Multiple Displays

```bash
# List all displays
ddcutil detect

# Operate on specific display
ddcutil getvcp 0x10 --display 2
```

### Useful Options

```bash
# Verbose output
ddcutil getvcp 0x10 -v

# Show timing
ddcutil getvcp 0x10 --stats

# Increase retries for unreliable monitors
ddcutil getvcp 0x10 --maxtries 15

# Use specific I2C bus
ddcutil getvcp 0x10 --bus 5
```

## Finding Your Monitor's Features

### Step 1: Detect Monitor

```bash
ddcutil detect
```

Note the display number.

### Step 2: Query Capabilities

```bash
ddcutil capabilities --display 1 > capabilities.txt
```

### Step 3: Find Color Modes

Look for Feature DC in the output:

```
Feature: DC (Display Mode)
   Values:
      00: Standard/Default mode
      01: Productivity
      02: Mixed
      03: Movie
      ...
```

### Step 4: Test Values

```bash
# Try a value
ddcutil setvcp 0xdc 3 --display 1

# Check current value
ddcutil getvcp 0xdc --display 1
```

### Step 5: Map to Config

```yaml
color_modes:
  Standard: 0
  Productivity: 1
  Mixed: 2
  Movie: 3
```

## Monitor Compatibility

### Known Compatible Monitors

| Manufacturer | Models | Notes |
|--------------|--------|-------|
| BenQ | RD280UA, PD series | Full DDC/CI support |
| Dell | UltraSharp series | Good support |
| LG | UltraFine series | Generally good |
| ASUS | ProArt series | Full support |
| Philips | Most models | Generally good |

### Potential Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| No detection | DDC/CI disabled | Enable in OSD |
| Slow response | Monitor processing | Increase sleep_multiplier |
| Partial support | Manufacturer limitation | Use supported features only |
| Adapter issues | Some adapters block DDC | Use direct connection |

### Adapters and DDC/CI

DDC/CI compatibility varies with adapters:

| Adapter Type | DDC/CI Support |
|--------------|----------------|
| DP to DP | ✅ Full |
| HDMI to HDMI | ✅ Full |
| DVI to DVI | ✅ Full |
| USB-C to DP/HDMI | ⚠️ Varies |
| DP to HDMI (active) | ⚠️ May not work |
| VGA adapters | ❌ Usually no |

## Timing and Reliability

### Communication Delays

DDC/CI requires delays between commands:

```python
# Typical timing
write_command()
sleep(0.05)  # 50ms minimum
read_response()
```

### Retry Strategy

For unreliable monitors:

```yaml
monitor:
  ddc:
    retry_count: 5
    sleep_multiplier: 2.0
```

### Avoiding Conflicts

- Don't send commands too rapidly
- Allow monitor to process before next command
- Some monitors need 100-200ms between commands

## Advanced Topics

### I2C Bus Detection

```bash
# List I2C buses
ls /dev/i2c-*

# Check bus permissions
ls -la /dev/i2c-*

# Test specific bus
ddcutil detect --bus 5
```

### Kernel Module

The `i2c-dev` module exposes I2C buses to userspace:

```bash
# Load module
sudo modprobe i2c-dev

# Make permanent
echo "i2c-dev" | sudo tee /etc/modules-load.d/i2c-dev.conf
```

### udev Rules

For automatic permissions:

```bash
# /etc/udev/rules.d/60-ddcutil.rules
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
```

### EDID Information

Read monitor identification:

```bash
ddcutil environment
```

Shows:
- I2C bus mapping
- EDID data
- Monitor capabilities

## Debugging DDC Issues

### Verbose Detection

```bash
ddcutil detect -v
```

### Test Communication

```bash
# With statistics
ddcutil getvcp 0x10 --stats

# With maximum verbosity
ddcutil getvcp 0x10 -v -v -v
```

### Check I2C Bus

```bash
# Scan I2C bus (requires i2c-tools)
sudo i2cdetect -y 5
```

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| "No I2C devices" | Module not loaded | `sudo modprobe i2c-dev` |
| "Permission denied" | User not in i2c group | `sudo usermod -aG i2c $USER` |
| "DDC communication failed" | Monitor not responding | Enable DDC/CI, check cable |
| "Feature not found" | VCP code not supported | Check capabilities |

## Resources

- [VESA Monitor Control Command Set (MCCS)](https://vesa.org/vesa-standards/)
- [ddcutil Documentation](https://www.ddcutil.com/)
- [DDC/CI Wikipedia](https://en.wikipedia.org/wiki/Display_Data_Channel)

## Next Steps

- [Configuration](Configuration.md) - Set up VCP codes
- [Troubleshooting](Troubleshooting.md) - DDC issues
- [API Reference](API-Reference.md) - Programmatic access

