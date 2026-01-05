#!/usr/bin/env python3
"""
Benchmark gnome-screenshot capture rate with different settings.

Tests various configurations to find the fastest capture method.
"""

import subprocess
import tempfile
import time
import os
import statistics
import shutil
from pathlib import Path

def benchmark_capture(cmd: list, name: str, num_captures: int = 10):
    """Benchmark screenshot capture times."""
    times = []
    failures = 0
    sizes = []
    
    print(f"\n{'='*50}")
    print(f"Testing: {name}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*50}")
    
    for i in range(num_captures):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name
        
        try:
            full_cmd = cmd + ["-f", temp_path]
            start = time.perf_counter()
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                timeout=10
            )
            elapsed = time.perf_counter() - start
            
            if result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                file_size = os.path.getsize(temp_path) / 1024  # KB
                times.append(elapsed)
                sizes.append(file_size)
                print(f"  [{i+1:2d}] {elapsed*1000:6.0f}ms  {file_size:6.0f} KB")
            else:
                failures += 1
                stderr = result.stderr.decode() if result.stderr else ""
                print(f"  [{i+1:2d}] FAILED (rc={result.returncode}) {stderr[:50]}")
        except subprocess.TimeoutExpired:
            failures += 1
            print(f"  [{i+1:2d}] TIMEOUT")
        except FileNotFoundError:
            print(f"  Command not found: {cmd[0]}")
            return None, None, None
        except Exception as e:
            failures += 1
            print(f"  [{i+1:2d}] ERROR: {e}")
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    if times:
        avg = statistics.mean(times) * 1000
        avg_size = statistics.mean(sizes)
        print(f"\n  Avg: {avg:.0f}ms, Size: {avg_size:.0f} KB, Failed: {failures}")
        return avg, avg_size, failures
    return None, None, failures


def test_with_imagemagick(num_captures: int = 5):
    """Test using ImageMagick import command (X11 only)."""
    if not shutil.which("import"):
        print("\nImageMagick 'import' not found, skipping")
        return None, None, None
    
    return benchmark_capture(["import", "-window", "root"], "ImageMagick import", num_captures)


def test_with_scrot(num_captures: int = 5):
    """Test using scrot (X11 only)."""
    if not shutil.which("scrot"):
        print("\nscrot not found, skipping")
        return None, None, None
    
    return benchmark_capture(["scrot"], "scrot", num_captures)


def test_with_grim(num_captures: int = 5):
    """Test using grim (Wayland wlroots)."""
    if not shutil.which("grim"):
        print("\ngrim not found, skipping")
        return None, None, None
    
    return benchmark_capture(["grim"], "grim (Wayland)", num_captures)


def test_gnome_screenshot_options():
    """Test gnome-screenshot with different options."""
    results = []
    
    # Find available gnome-screenshot binaries
    binaries = []
    if os.path.exists("/tmp/gnome-screenshot-silent"):
        binaries.append(("/tmp/gnome-screenshot-silent", "Custom silent (1/4 scale)"))
    if os.path.exists("/usr/local/bin/gnome-screenshot-silent"):
        binaries.append(("/usr/local/bin/gnome-screenshot-silent", "Installed silent"))
    if shutil.which("gnome-screenshot"):
        binaries.append(("gnome-screenshot", "System gnome-screenshot"))
    
    for binary, name in binaries:
        avg, size, fails = benchmark_capture([binary], name, num_captures=8)
        if avg:
            results.append((name, avg, size, fails))
    
    return results


def test_mss_python():
    """Test Python mss library (X11 only, silent)."""
    print(f"\n{'='*50}")
    print("Testing: Python mss library")
    print(f"{'='*50}")
    
    try:
        import mss
        from PIL import Image
        import io
    except ImportError as e:
        print(f"  mss or PIL not available: {e}")
        return None, None, None
    
    times = []
    sizes = []
    
    for i in range(10):
        start = time.perf_counter()
        try:
            with mss.mss() as sct:
                screenshot = sct.grab(sct.monitors[0])  # All monitors
                # Convert to PIL and save to measure full pipeline
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                buffer = io.BytesIO()
                img.save(buffer, format='PNG', compress_level=1)
                size = len(buffer.getvalue()) / 1024
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            sizes.append(size)
            print(f"  [{i+1:2d}] {elapsed*1000:6.0f}ms  {size:6.0f} KB")
        except Exception as e:
            print(f"  [{i+1:2d}] ERROR: {e}")
    
    if times:
        avg = statistics.mean(times) * 1000
        avg_size = statistics.mean(sizes)
        print(f"\n  Avg: {avg:.0f}ms, Size: {avg_size:.0f} KB")
        return avg, avg_size, 0
    return None, None, None


def test_gdk_python():
    """Test Python GDK/GTK screenshot (works on X11 and some Wayland)."""
    print(f"\n{'='*50}")
    print("Testing: Python GDK/GTK")
    print(f"{'='*50}")
    
    try:
        import gi
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gdk, GdkPixbuf
    except Exception as e:
        print(f"  GDK not available: {e}")
        return None, None, None
    
    times = []
    sizes = []
    
    for i in range(10):
        start = time.perf_counter()
        try:
            window = Gdk.get_default_root_window()
            if window is None:
                print("  GDK root window not available (Wayland?)")
                return None, None, None
            
            width = window.get_width()
            height = window.get_height()
            pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, width, height)
            
            if pixbuf:
                # Save to measure full pipeline
                import io
                success, data = pixbuf.save_to_bufferv("png", ["compression"], ["1"])
                size = len(data) / 1024 if success else 0
                elapsed = time.perf_counter() - start
                times.append(elapsed)
                sizes.append(size)
                print(f"  [{i+1:2d}] {elapsed*1000:6.0f}ms  {size:6.0f} KB")
            else:
                print(f"  [{i+1:2d}] Failed to get pixbuf")
        except Exception as e:
            print(f"  [{i+1:2d}] ERROR: {e}")
    
    if times:
        avg = statistics.mean(times) * 1000
        avg_size = statistics.mean(sizes)
        print(f"\n  Avg: {avg:.0f}ms, Size: {avg_size:.0f} KB")
        return avg, avg_size, 0
    return None, None, None


def main():
    print("=" * 60)
    print("SCREENSHOT METHOD BENCHMARK")
    print("=" * 60)
    
    # Detect display server
    is_wayland = (os.environ.get('XDG_SESSION_TYPE') == 'wayland' or 
                  os.environ.get('WAYLAND_DISPLAY') is not None)
    print(f"\nDisplay server: {'Wayland' if is_wayland else 'X11'}")
    
    all_results = []
    
    # Test gnome-screenshot variants
    gnome_results = test_gnome_screenshot_options()
    all_results.extend(gnome_results)
    
    # Test Python libraries
    result = test_mss_python()
    if result[0]:
        all_results.append(("Python mss", result[0], result[1], result[2]))
    
    result = test_gdk_python()
    if result[0]:
        all_results.append(("Python GDK", result[0], result[1], result[2]))
    
    # Test other tools
    if not is_wayland:
        result = test_with_scrot()
        if result[0]:
            all_results.append(("scrot", result[0], result[1], result[2]))
        
        result = test_with_imagemagick()
        if result[0]:
            all_results.append(("ImageMagick", result[0], result[1], result[2]))
    else:
        result = test_with_grim()
        if result[0]:
            all_results.append(("grim", result[0], result[1], result[2]))
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY (sorted by speed)")
    print("=" * 60)
    print(f"{'Method':<30} {'Time':>10} {'Size':>10}")
    print("-" * 60)
    
    for name, avg_time, avg_size, fails in sorted(all_results, key=lambda x: x[1]):
        print(f"{name:<30} {avg_time:>8.0f}ms {avg_size:>8.0f}KB")
    
    if all_results:
        fastest = min(all_results, key=lambda x: x[1])
        print(f"\n🏆 Fastest: {fastest[0]} ({fastest[1]:.0f}ms)")
        print(f"   Recommended interval: {max(0.5, fastest[1]/1000 * 1.5):.1f}s")


if __name__ == "__main__":
    main()
