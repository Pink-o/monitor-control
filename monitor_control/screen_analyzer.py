"""
Screen Analyzer - Analyze screen content for adaptive settings
==============================================================
"""

import logging
import threading
import time
import subprocess
import tempfile
import os
import io
from typing import Callable, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import PIL and numpy for image analysis
try:
    from PIL import Image
    import numpy as np
    IMAGING_AVAILABLE = True
except ImportError:
    IMAGING_AVAILABLE = False
    logger.warning("PIL/numpy not available, screen analysis disabled")

# Try to import mss for silent screenshots
try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False



@dataclass
class ScreenAnalysis:
    """Results of screen content analysis."""
    mean_brightness: float  # 0.0 (black) to 1.0 (white)
    brightness_std: float   # Standard deviation
    dark_ratio: float       # Ratio of dark pixels (< 0.3)
    bright_ratio: float     # Ratio of bright pixels (> 0.7)
    is_mostly_dark: bool
    is_mostly_bright: bool
    suggested_contrast: int  # Suggested contrast value (0-100)
    suggested_brightness: int  # Suggested brightness value (0-100)


class ScreenAnalyzer:
    """
    Analyzes screen content to determine optimal monitor settings.
    
    Uses screen capture and image analysis to detect:
    - Overall brightness of displayed content
    - Dark/light distribution
    - Suggested contrast adjustments
    """
    
    # Class-level shared capture cache (one capture serves all monitors)
    # When multiple monitors run auto-brightness, they share ONE screenshot
    # instead of each calling gnome-screenshot separately (which fails)
    _shared_capture: Optional['Image.Image'] = None
    _shared_capture_time: float = 0
    _shared_capture_lock: threading.Lock = threading.Lock()
    _shared_capture_max_age: float = 0.3  # Only share within same cycle (handles monitor timing offset)
    
    @classmethod
    def _get_shared_capture(cls) -> Optional['Image.Image']:
        """Get a shared full-screen capture, reusing recent captures."""
        import time as _time
        now = _time.time()
        
        # Return cached capture if still fresh
        if cls._shared_capture is not None:
            age = now - cls._shared_capture_time
            if age < cls._shared_capture_max_age:
                logger.debug(f"Using shared capture (age: {age:.2f}s)")
                return cls._shared_capture.copy()
        
        # Need new capture - try to acquire lock
        if not cls._shared_capture_lock.acquire(timeout=3.0):
            logger.debug("Could not acquire capture lock, using stale cache")
            return cls._shared_capture.copy() if cls._shared_capture else None
        
        try:
            # Double-check after acquiring lock (another thread might have captured)
            now = _time.time()
            if cls._shared_capture is not None:
                age = now - cls._shared_capture_time
                if age < cls._shared_capture_max_age:
                    logger.debug(f"Another thread captured (age: {age:.2f}s)")
                    return cls._shared_capture.copy()
            
            # Perform the capture
            img = cls._do_shared_capture()
            if img is not None:
                cls._shared_capture = img
                cls._shared_capture_time = _time.time()
                logger.debug(f"New shared capture: {img.size}")
                return img.copy()
            return None
        finally:
            cls._shared_capture_lock.release()
    
    @classmethod
    def _do_shared_capture(cls) -> Optional['Image.Image']:
        """Perform the actual screen capture (called with lock held)."""
        if not IMAGING_AVAILABLE:
            return None
        
        # Try gnome-screenshot-silent first (Wayland)
        img = cls._capture_gnome_screenshot_shared()
        if img is not None:
            return img
        
        # Try mss (X11)
        if MSS_AVAILABLE:
            try:
                with mss.mss() as sct:
                    # Capture all monitors combined
                    screenshot = sct.grab(sct.monitors[0])
                    return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            except Exception as e:
                logger.debug(f"mss shared capture failed: {e}")
        
        return None
    
    @classmethod
    def _capture_gnome_screenshot_shared(cls) -> Optional['Image.Image']:
        """Capture full screen with gnome-screenshot for shared use."""
        gnome_screenshot_paths = [
            "/usr/local/bin/gnome-screenshot-silent",
            "/tmp/gnome-screenshot-silent",
            "gnome-screenshot",
        ]
        
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name
        
        try:
            for gnome_cmd in gnome_screenshot_paths:
                if gnome_cmd.startswith("/") and not os.path.exists(gnome_cmd):
                    continue
                
                try:
                    result = subprocess.run(
                        [gnome_cmd, "-f", temp_path],
                        capture_output=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                        img = Image.open(temp_path)
                        logger.debug(f"Shared capture with {gnome_cmd}: {img.size}")
                        return img.copy()  # Copy before file is deleted
                except FileNotFoundError:
                    continue
                except subprocess.TimeoutExpired:
                    logger.debug(f"{gnome_cmd} timed out")
                    continue
                except Exception as e:
                    logger.debug(f"{gnome_cmd} failed: {e}")
                    continue
            return None
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def _crop_shared_capture(self, img: 'Image.Image', region: Tuple[int, int, int, int]) -> Optional['Image.Image']:
        """Crop a shared capture to the specified region, handling scaling."""
        x, y, w, h = region
        img_w, img_h = img.size
        
        # Check if image was scaled (e.g., 1/4 size from optimized gnome-screenshot)
        if x + w > img_w or y + h > img_h:
            # Calculate scale factor
            scale_x = img_w / (x + w) if x + w > img_w else 1.0
            scale_y = img_h / (y + h) if y + h > img_h else 1.0
            scale = min(scale_x, scale_y)
            
            # Scale the crop coordinates
            sx, sy = int(x * scale), int(y * scale)
            sw, sh = int(w * scale), int(h * scale)
            
            # Ensure we stay within bounds
            sw = min(sw, img_w - sx)
            sh = min(sh, img_h - sy)
            
            if sw > 0 and sh > 0:
                return img.crop((sx, sy, sx + sw, sy + sh))
            return img  # Can't crop, return full image
        else:
            # No scaling needed
            return img.crop((x, y, x + w, y + h))
    
    def __init__(
        self,
        dark_threshold: float = 0.3,
        bright_threshold: float = 0.7,
        min_contrast: int = 30,
        max_contrast: int = 70,
        min_brightness: int = 20,
        max_brightness: int = 80,
        smoothing: float = 0.3,  # Lower = faster response (was 0.7)
        monitor_index: int = 1,  # Which monitor to capture (1-based, like mss)
        monitor_region: Optional[Tuple[int, int, int, int]] = None,  # (x, y, width, height) for precise capture
    ):
        """
        Initialize screen analyzer.
        
        Args:
            dark_threshold: Brightness level below which pixels are "dark"
            bright_threshold: Brightness level above which pixels are "bright"
            min_contrast: Minimum contrast value to suggest
            max_contrast: Maximum contrast value to suggest
            min_brightness: Minimum brightness value to suggest
            max_brightness: Maximum brightness value to suggest
            smoothing: Smoothing factor for changes (0-1)
            monitor_index: Which monitor to capture (1-based, 1=first monitor) - fallback if no region
            monitor_region: (x, y, width, height) for precise monitor area capture
        """
        self.dark_threshold = dark_threshold
        self.bright_threshold = bright_threshold
        self.monitor_index = monitor_index
        self.min_contrast = min_contrast
        self.max_contrast = max_contrast
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness
        self.smoothing = smoothing
        self.monitor_region = monitor_region  # (x, y, w, h) for precise monitor capture
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[ScreenAnalysis], None]] = None
        self._interval: float = 5.0
        self._last_contrast: float = (min_contrast + max_contrast) / 2
        self._last_brightness: float = (min_brightness + max_brightness) / 2
        
        # Region to analyze (can be overridden per-capture)
        self._region: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h
        
        # Cache for skip-unchanged optimization
        self._last_image_hash: Optional[int] = None
        self._last_analysis: Optional[ScreenAnalysis] = None
        self._unchanged_count: int = 0
        
        # Cache the working capture method (don't retry all methods every time)
        self._cached_capture_method: Optional[Callable] = None
        self._capture_method_failures: int = 0
        
    def _is_wayland(self) -> bool:
        """Check if running on Wayland."""
        return (os.environ.get('XDG_SESSION_TYPE') == 'wayland' or 
                os.environ.get('WAYLAND_DISPLAY') is not None)
    
    def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[Image.Image]:
        """
        Capture the screen or a region of it.
        
        Args:
            region: Optional (x, y, width, height) tuple for region capture
            
        Returns:
            PIL Image of the captured screen, or None on failure
        """
        if not IMAGING_AVAILABLE:
            return None
        
        # On Wayland, prefer shared capture to avoid gnome-screenshot conflicts
        # when multiple monitors are running auto-brightness
        if self._is_wayland():
            img = self._get_shared_capture()
            if img is not None:
                # Crop to region if specified
                if region:
                    return self._crop_shared_capture(img, region)
                return img
            # Fall through to individual capture methods if shared fails
        
        # Use cached capture method if available (much faster)
        if self._cached_capture_method is not None:
            try:
                img = self._cached_capture_method(region)
                if img is not None:
                    self._capture_method_failures = 0
                    return img
                # Method returned None - count as failure
                self._capture_method_failures += 1
            except Exception as e:
                logger.debug(f"Cached capture method failed: {e}")
                self._capture_method_failures += 1
            
            # After 3 failures, try to find a new method
            if self._capture_method_failures >= 3:
                logger.info("Cached capture method failing, searching for new method...")
                self._cached_capture_method = None
                self._capture_method_failures = 0
            else:
                return None
        
        # Find a working capture method
        if self._is_wayland():
            # Wayland: GDK returns black image due to security, must use portal/external tools
            methods = [
                self._capture_with_gnome_screenshot,  # GNOME (~2s but works)
                self._capture_with_flameshot,  # Universal: works on GNOME + KDE
                self._capture_with_grim,  # wlroots (Sway, etc.)
                self._capture_with_spectacle,  # KDE
            ]
        else:
            # X11: mss is fastest and silent, then GDK as pure Python fallback
            methods = [
                self._capture_with_mss,  # Silent, pure Python
                self._capture_with_gdk,  # GDK/GTK (pure Python)
                self._capture_with_gnome_screenshot,
                self._capture_with_scrot,
                self._capture_with_import,
            ]
        
        for method in methods:
            try:
                img = method(region)
                if img is not None:
                    # Cache this working method for future calls
                    self._cached_capture_method = method
                    logger.info(f"Screen capture using {method.__name__} (cached for future)")
                    return img
            except Exception as e:
                logger.debug(f"Capture method {method.__name__} failed: {e}")
                
        if self._is_wayland():
            logger.warning(
                "All screen capture methods failed. On Wayland, install one of: "
                "flameshot (recommended), gnome-screenshot (GNOME), spectacle (KDE), or grim (Sway)"
            )
        else:
            logger.warning("All screen capture methods failed")
        return None
    
    def _capture_with_mss(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Image.Image]:
        """Capture using mss (pure Python, silent, X11 only)."""
        if not MSS_AVAILABLE:
            return None
            
        try:
            with mss.mss() as sct:
                # Priority: explicit region > monitor_region > monitor_index
                capture_region = region or self.monitor_region
                
                if capture_region:
                    x, y, w, h = capture_region
                    monitor = {"top": y, "left": x, "width": w, "height": h}
                    logger.debug(f"Capturing region: {w}x{h}+{x}+{y}")
                else:
                    # Capture specific monitor (monitor_index is 1-based)
                    # mss.monitors[0] = all monitors combined
                    # mss.monitors[1] = first monitor, etc.
                    if self.monitor_index < len(sct.monitors):
                        monitor = sct.monitors[self.monitor_index]
                    else:
                        # Fallback to first monitor if index out of range
                        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                
                screenshot = sct.grab(monitor)
                # Convert to PIL Image
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                return img
        except Exception as e:
            logger.debug(f"mss capture failed: {e}")
            return None
    
    # Track last gnome-screenshot call to prevent rate limiting issues
    _last_gnome_screenshot_time: float = 0
    
    def _capture_with_gnome_screenshot(
        self, 
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Image.Image]:
        """Capture using gnome-screenshot (tries silent version first)."""
        # Rate limit gnome-screenshot calls (min 0.5s between calls)
        import time as _time
        now = _time.time()
        if now - ScreenAnalyzer._last_gnome_screenshot_time < 0.5:
            _time.sleep(0.5 - (now - ScreenAnalyzer._last_gnome_screenshot_time))
        ScreenAnalyzer._last_gnome_screenshot_time = _time.time()
        
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name
        
        # Try custom silent version first, then system gnome-screenshot
        gnome_screenshot_paths = [
            "/usr/local/bin/gnome-screenshot-silent",  # Installed silent build
            "/tmp/gnome-screenshot-silent",  # Temporary silent build
            "gnome-screenshot",  # System default
        ]
        
        try:
            for gnome_cmd in gnome_screenshot_paths:
                # Skip if custom path doesn't exist
                if gnome_cmd.startswith("/") and not os.path.exists(gnome_cmd):
                    continue
                    
                try:
                    # gnome-screenshot doesn't support region coordinates
                    # We capture full screen and crop in Python
                    cmd = [gnome_cmd, "-f", temp_path]
                        
                    result = subprocess.run(cmd, capture_output=True, timeout=5)
                    
                    # Check file exists AND has content (not empty)
                    if result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                        img = Image.open(temp_path)
                        img_w, img_h = img.size
                        
                        # Crop to monitor region if specified
                        if region:
                            x, y, w, h = region
                            # Detect if image was scaled (optimized gnome-screenshot uses 1/4 scale)
                            # Check if region is larger than image - if so, scale coordinates
                            if x + w > img_w or y + h > img_h:
                                # Calculate scale factor based on expected vs actual size
                                # Assume region represents original coordinates
                                scale_x = img_w / (x + w) if x + w > img_w else 1.0
                                scale_y = img_h / (y + h) if y + h > img_h else 1.0
                                scale = min(scale_x, scale_y)
                                
                                # Scale the crop coordinates
                                sx, sy = int(x * scale), int(y * scale)
                                sw, sh = int(w * scale), int(h * scale)
                                
                                # Ensure we stay within bounds
                                sw = min(sw, img_w - sx)
                                sh = min(sh, img_h - sy)
                                
                                if sw > 0 and sh > 0:
                                    img = img.crop((sx, sy, sx + sw, sy + sh))
                                    logger.debug(f"Scaled crop: {img_w}x{img_h} -> {sw}x{sh}+{sx}+{sy} (scale={scale:.2f})")
                            else:
                                # No scaling needed, use original coordinates
                                img = img.crop((x, y, x + w, y + h))
                                logger.debug(f"Cropped {img_w}x{img_h} to {w}x{h}+{x}+{y}")
                        else:
                            logger.debug(f"Full capture: {img_w}x{img_h}")
                        return img
                except FileNotFoundError:
                    continue
                except Exception as e:
                    logger.debug(f"{gnome_cmd} capture failed: {e}")
                    continue
                    
                # Log why capture failed
                if result.returncode != 0:
                    logger.debug(f"{gnome_cmd} returned {result.returncode}")
                elif not os.path.exists(temp_path):
                    logger.debug(f"{gnome_cmd} didn't create output file")
                elif os.path.getsize(temp_path) == 0:
                    logger.debug(f"{gnome_cmd} created empty file")
                    
            return None
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def _capture_with_scrot(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Image.Image]:
        """Capture using scrot."""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name
            
        try:
            # -o overwrites existing file, redirect stderr to suppress any messages
            cmd = ["scrot", "-o", temp_path]
            result = subprocess.run(cmd, capture_output=True, timeout=5, stderr=subprocess.DEVNULL)
            if result.returncode == 0 and os.path.exists(temp_path):
                img = Image.open(temp_path)
                if region:
                    img = img.crop((region[0], region[1],
                                   region[0] + region[2], region[1] + region[3]))
                return img
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        return None
    
    def _capture_with_import(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Image.Image]:
        """Capture using ImageMagick import."""
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name
            
        try:
            cmd = ["import", "-window", "root"]
            if region:
                x, y, w, h = region
                cmd.extend(["-crop", f"{w}x{h}+{x}+{y}"])
            cmd.append(temp_path)
            
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            if result.returncode == 0 and os.path.exists(temp_path):
                return Image.open(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        return None
    
    def _capture_with_flameshot(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Image.Image]:
        """Capture using flameshot (works on GNOME + KDE Wayland)."""
        # Quick check if flameshot is available
        import shutil
        if not shutil.which("flameshot"):
            return None
            
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name
        
        try:
            # flameshot full mode captures entire screen silently
            cmd = ["flameshot", "full", "--raw"]
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            
            if result.returncode == 0 and result.stdout:
                # flameshot --raw outputs PNG data to stdout
                from io import BytesIO
                img = Image.open(BytesIO(result.stdout))
                img_w, img_h = img.size
                if region:
                    x, y, w, h = region
                    # Validate and crop
                    if x + w <= img_w and y + h <= img_h:
                        img = img.crop((x, y, x + w, y + h))
                        logger.debug(f"Flameshot: {img_w}x{img_h} -> {w}x{h}+{x}+{y}")
                    else:
                        logger.debug(f"Flameshot: {img_w}x{img_h} (region {w}x{h}+{x}+{y} out of bounds)")
                else:
                    logger.debug(f"Flameshot: {img_w}x{img_h}")
                return img
        except FileNotFoundError:
            pass  # flameshot not installed
        except Exception as e:
            logger.debug(f"flameshot capture failed: {e}")
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        return None
    
    def _capture_with_spectacle(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Image.Image]:
        """Capture using spectacle (KDE Wayland)."""
        import shutil
        if not shutil.which("spectacle"):
            return None
            
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name
        
        try:
            # -b = background mode, -n = no notification, -o = output file
            cmd = ["spectacle", "-b", "-n", "-f", "-o", temp_path]
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            
            if result.returncode == 0 and os.path.exists(temp_path):
                img = Image.open(temp_path)
                if region:
                    x, y, w, h = region
                    img = img.crop((x, y, x + w, y + h))
                # Make a copy so we can delete the temp file
                img_copy = img.copy()
                img.close()
                return img_copy
        except FileNotFoundError:
            pass  # spectacle not installed
        except Exception as e:
            logger.debug(f"spectacle capture failed: {e}")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
        return None
    
    def _capture_with_gdk(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Image.Image]:
        """Capture using GDK/GTK (X11 only, pure Python fallback)."""
        try:
            import gi
            gi.require_version('Gdk', '3.0')
            gi.require_version('GdkPixbuf', '2.0')
            from gi.repository import Gdk, GdkPixbuf
            
            window = Gdk.get_default_root_window()
            if window is None:
                return None
            
            # Get screen geometry
            width = window.get_width()
            height = window.get_height()
            
            # Capture the root window
            pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, width, height)
            if pixbuf is None:
                return None
            
            # Convert to PIL Image
            data = pixbuf.get_pixels()
            img = Image.frombytes(
                'RGB' if pixbuf.get_n_channels() == 3 else 'RGBA',
                (pixbuf.get_width(), pixbuf.get_height()),
                data,
                'raw',
                'RGB' if pixbuf.get_n_channels() == 3 else 'RGBA',
                pixbuf.get_rowstride(),
            )
            
            if region:
                x, y, w, h = region
                img = img.crop((x, y, x + w, y + h))
            
            return img
        except ImportError:
            logger.debug("GDK not available for screen capture")
            return None
        except Exception as e:
            logger.debug(f"GDK capture failed: {e}")
            return None
    
    def _capture_with_grim(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Image.Image]:
        """Capture using grim (Wayland - wlroots compositors like Sway)."""
        import shutil
        if not shutil.which("grim"):
            return None
            
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name
            
        try:
            cmd = ["grim"]
            if region:
                x, y, w, h = region
                cmd.extend(["-g", f"{x},{y} {w}x{h}"])
            cmd.append(temp_path)
            
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            if result.returncode == 0 and os.path.exists(temp_path):
                img = Image.open(temp_path)
                img_copy = img.copy()
                img.close()
                return img_copy
        except FileNotFoundError:
            pass  # grim not installed
        except Exception as e:
            logger.debug(f"grim capture failed: {e}")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
        return None
    
    def analyze_image(self, image: Image.Image) -> ScreenAnalysis:
        """
        Analyze an image for brightness characteristics.
        
        Args:
            image: PIL Image to analyze
            
        Returns:
            ScreenAnalysis with brightness metrics
        """
        # Downsample if needed (optimized gnome-screenshot already outputs 200px max)
        max_size = 200
        if image.width > max_size or image.height > max_size:
            ratio = max_size / max(image.width, image.height)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            # Use NEAREST - fastest, good enough for brightness analysis
            image = image.resize(new_size, Image.Resampling.NEAREST)
        
        # Convert to grayscale
        gray = image.convert('L')
        
        # Convert to numpy array and normalize to 0-1
        pixels = np.array(gray, dtype=np.float32) / 255.0
        
        # Calculate statistics
        mean_brightness = float(np.mean(pixels))
        brightness_std = float(np.std(pixels))
        
        dark_pixels = np.sum(pixels < self.dark_threshold)
        bright_pixels = np.sum(pixels > self.bright_threshold)
        total_pixels = pixels.size
        
        dark_ratio = dark_pixels / total_pixels
        bright_ratio = bright_pixels / total_pixels
        
        # Determine if mostly dark or bright
        is_mostly_dark = dark_ratio > 0.6 or mean_brightness < 0.35
        is_mostly_bright = bright_ratio > 0.6 or mean_brightness > 0.65
        
        # Calculate suggested contrast
        # Dark content -> higher contrast to see details
        # Bright content -> lower contrast for comfort
        if is_mostly_dark:
            base_contrast = self.max_contrast - 10
        elif is_mostly_bright:
            base_contrast = self.min_contrast + 10
        else:
            # Map brightness to contrast inversely
            contrast_range = self.max_contrast - self.min_contrast
            base_contrast = self.max_contrast - (mean_brightness * contrast_range)
        
        # Apply smoothing to avoid sudden changes
        suggested_contrast = int(
            self.smoothing * self._last_contrast + 
            (1 - self.smoothing) * base_contrast
        )
        suggested_contrast = max(self.min_contrast, min(self.max_contrast, suggested_contrast))
        self._last_contrast = suggested_contrast
        
        # Calculate suggested brightness (INVERSE relationship)
        # Dark screen content -> HIGHER monitor brightness (to see better)
        # Bright screen content -> LOWER monitor brightness (reduce eye strain)
        # Always use the full range - map mean_brightness inversely to monitor brightness
        brightness_range = self.max_brightness - self.min_brightness
        # mean_brightness 0.0 (dark screen) -> max_brightness
        # mean_brightness 1.0 (bright screen) -> min_brightness
        base_brightness = self.max_brightness - (mean_brightness * brightness_range)
        
        # Apply smoothing
        suggested_brightness = int(
            self.smoothing * self._last_brightness +
            (1 - self.smoothing) * base_brightness
        )
        suggested_brightness = max(self.min_brightness, min(self.max_brightness, suggested_brightness))
        self._last_brightness = suggested_brightness
        
        return ScreenAnalysis(
            mean_brightness=mean_brightness,
            brightness_std=brightness_std,
            dark_ratio=dark_ratio,
            bright_ratio=bright_ratio,
            is_mostly_dark=is_mostly_dark,
            is_mostly_bright=is_mostly_bright,
            suggested_contrast=suggested_contrast,
            suggested_brightness=suggested_brightness,
        )
    
    def analyze_screen(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[ScreenAnalysis]:
        """
        Capture and analyze current screen content.
        
        Args:
            region: Optional region to analyze (x, y, width, height)
            
        Returns:
            ScreenAnalysis or None if capture failed
        """
        image = self.capture_screen(region)
        if image is None:
            return None
        
        # Quick hash check - skip full analysis if image hasn't changed much
        # Sample a few pixels for fast comparison (corners + center)
        try:
            w, h = image.size
            sample_points = [
                (0, 0), (w-1, 0), (0, h-1), (w-1, h-1),  # corners
                (w//2, h//2), (w//4, h//4), (3*w//4, 3*h//4)  # center area
            ]
            sample_values = tuple(image.getpixel(p)[:3] if isinstance(image.getpixel(p), tuple) else image.getpixel(p) for p in sample_points)
            current_hash = hash(sample_values)
            
            # If hash matches and we have cached result, return cached (but not forever)
            if (current_hash == self._last_image_hash and 
                self._last_analysis is not None and 
                self._unchanged_count < 5):  # Force re-analyze every 5th unchanged frame
                self._unchanged_count += 1
                logger.debug(f"Screen unchanged (hash match), using cached analysis")
                return self._last_analysis
            
            self._last_image_hash = current_hash
            self._unchanged_count = 0
        except Exception:
            pass  # If sampling fails, just do full analysis
        
        analysis = self.analyze_image(image)
        self._last_analysis = analysis
        return analysis
    
    def start_monitoring(
        self,
        callback: Callable[[ScreenAnalysis], None],
        interval: float = 5.0,
        region: Optional[Tuple[int, int, int, int]] = None,
    ):
        """
        Start continuous screen monitoring.
        
        Args:
            callback: Function called with analysis results
            interval: Seconds between analyses
            region: Optional fixed region to analyze (falls back to monitor_region from constructor)
        """
        if self._running:
            return
            
        if not IMAGING_AVAILABLE:
            logger.error("Cannot start screen monitoring: PIL/numpy not available")
            return
            
        self._callback = callback
        self.set_interval(interval)  # Use setter to enforce minimum for Wayland
        # Use provided region, or fall back to monitor_region from constructor
        self._region = region or self.monitor_region
        self._running = True
        
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        if self._region:
            x, y, w, h = self._region
            logger.info(f"Started screen analysis (interval: {self._interval}s, region: {w}x{h}+{x}+{y})")
        else:
            logger.info(f"Started screen analysis (interval: {self._interval}s, full screen)")
    
    def stop_monitoring(self):
        """Stop screen monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self._interval + 2)
            self._thread = None
        logger.info("Stopped screen analysis")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                analysis = self.analyze_screen(self._region)
                if analysis and self._callback:
                    self._callback(analysis)
            except Exception as e:
                logger.error(f"Error in screen analysis: {e}")
            
            # Interruptible sleep (handles intervals as small as 0.1s)
            sleep_steps = max(1, int(self._interval * 10))
            sleep_per_step = self._interval / sleep_steps
            for _ in range(sleep_steps):
                if not self._running:
                    break
                time.sleep(sleep_per_step)
    
    def set_region(self, region: Optional[Tuple[int, int, int, int]]):
        """Set the screen region to analyze."""
        self._region = region
    
    def set_interval(self, interval: float):
        """Set the analysis interval. Minimum is 0.5s on X11, 2.5s on Wayland (gnome-screenshot is slow)."""
        if self._is_wayland():
            # gnome-screenshot takes ~2s per capture, need buffer
            self._interval = max(2.5, interval)
            if interval < 2.5:
                logger.info(f"Wayland: adjusted interval from {interval}s to {self._interval}s (gnome-screenshot is slow)")
        else:
            # X11: mss/GDK are fast (~50-200ms)
            self._interval = max(0.5, interval)
    
    def set_monitor_index(self, index: int):
        """Set which monitor to capture (1-based)."""
        self.monitor_index = max(1, index)
        logger.info(f"Screen analyzer now capturing monitor {self.monitor_index}")


def check_imaging_available() -> Tuple[bool, str]:
    """
    Check if imaging libraries are available.
    
    Returns:
        Tuple of (available, message)
    """
    if IMAGING_AVAILABLE:
        return True, "PIL and numpy available for screen analysis"
    return False, (
        "Screen analysis disabled: PIL and numpy not available.\n"
        "Install with: pip install Pillow numpy"
    )
