"""
Generate app icon programmatically
"""

from PIL import Image, ImageDraw
import os

def create_icon(size: int = 256) -> Image.Image:
    """Create a monitor with gear icon."""
    # Create image with transparency
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Colors
    bg_color = (26, 26, 26, 255)  # Dark background
    accent = (255, 107, 0, 255)   # BenQ orange
    screen_color = (80, 80, 80, 255)  # Brighter screen for better visibility at small sizes
    highlight = (255, 140, 50, 255)
    
    # Padding
    pad = size // 10
    
    # Monitor frame
    monitor_top = pad
    monitor_bottom = int(size * 0.7)
    monitor_left = pad
    monitor_right = size - pad
    frame_radius = size // 15
    
    # Draw monitor body (rounded rectangle)
    draw.rounded_rectangle(
        [monitor_left, monitor_top, monitor_right, monitor_bottom],
        radius=frame_radius,
        fill=accent
    )
    
    # Screen (inner rectangle)
    screen_pad = size // 20
    draw.rounded_rectangle(
        [monitor_left + screen_pad, monitor_top + screen_pad, 
         monitor_right - screen_pad, monitor_bottom - screen_pad],
        radius=frame_radius // 2,
        fill=screen_color
    )
    
    # Monitor stand (neck)
    stand_width = size // 6
    stand_left = (size - stand_width) // 2
    stand_right = stand_left + stand_width
    stand_top = monitor_bottom
    stand_bottom = int(size * 0.8)
    
    draw.rectangle(
        [stand_left, stand_top, stand_right, stand_bottom],
        fill=accent
    )
    
    # Monitor base
    base_width = size // 3
    base_left = (size - base_width) // 2
    base_right = base_left + base_width
    base_top = stand_bottom
    base_bottom = int(size * 0.85)
    
    draw.rounded_rectangle(
        [base_left, base_top, base_right, base_bottom],
        radius=size // 30,
        fill=accent
    )
    
    # Gear icon (on screen, bottom right)
    gear_center_x = int(size * 0.65)
    gear_center_y = int(size * 0.45)
    gear_outer = size // 6
    gear_inner = size // 10
    gear_hole = size // 18
    
    # Gear teeth (8 teeth)
    import math
    teeth = 8
    tooth_width = math.pi / teeth
    
    for i in range(teeth):
        angle = i * 2 * math.pi / teeth
        # Outer point
        x1 = gear_center_x + int(gear_outer * math.cos(angle - tooth_width/2))
        y1 = gear_center_y + int(gear_outer * math.sin(angle - tooth_width/2))
        x2 = gear_center_x + int(gear_outer * math.cos(angle + tooth_width/2))
        y2 = gear_center_y + int(gear_outer * math.sin(angle + tooth_width/2))
        # Inner point
        x3 = gear_center_x + int(gear_inner * math.cos(angle + tooth_width))
        y3 = gear_center_y + int(gear_inner * math.sin(angle + tooth_width))
        x4 = gear_center_x + int(gear_inner * math.cos(angle - tooth_width))
        y4 = gear_center_y + int(gear_inner * math.sin(angle - tooth_width))
        
        draw.polygon([(x1, y1), (x2, y2), (x3, y3), (x4, y4)], fill=highlight)
    
    # Gear body (circle)
    draw.ellipse(
        [gear_center_x - gear_inner, gear_center_y - gear_inner,
         gear_center_x + gear_inner, gear_center_y + gear_inner],
        fill=highlight
    )
    
    # Gear hole
    draw.ellipse(
        [gear_center_x - gear_hole, gear_center_y - gear_hole,
         gear_center_x + gear_hole, gear_center_y + gear_hole],
        fill=screen_color
    )
    
    # Brightness lines on screen (left side)
    line_x = int(size * 0.25)
    for i, length in enumerate([0.15, 0.2, 0.15]):
        y = int(size * (0.3 + i * 0.12))
        line_len = int(size * length)
        draw.rounded_rectangle(
            [line_x, y, line_x + line_len, y + size//40],
            radius=size//80,
            fill=highlight if i == 1 else (80, 80, 80, 255)
        )
    
    return img


def save_icons():
    """Save icon in multiple sizes."""
    assets_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Generate different sizes
    sizes = [16, 32, 48, 64, 128, 256]
    
    for size in sizes:
        icon = create_icon(size)
        icon.save(os.path.join(assets_dir, f'icon_{size}.png'))
    
    # Save main icon
    icon = create_icon(256)
    icon.save(os.path.join(assets_dir, 'icon.png'))
    
    # Create ICO file for Windows (multiple sizes)
    icon_256 = create_icon(256)
    icon_256.save(
        os.path.join(assets_dir, 'icon.ico'),
        format='ICO',
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    
    print(f"Icons saved to {assets_dir}")
    return os.path.join(assets_dir, 'icon.png')


if __name__ == '__main__':
    save_icons()


