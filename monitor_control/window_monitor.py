"""
Window Monitor - Track active window and fullscreen state
=========================================================
"""

import logging
import threading
import time
import re
import subprocess
from typing import Callable, Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Check if running on Wayland
import os
IS_WAYLAND = (os.environ.get('XDG_SESSION_TYPE') == 'wayland' or 
              os.environ.get('WAYLAND_DISPLAY') is not None)

# Try to import Xlib for X11 support
try:
    from Xlib import X, display, Xatom
    from Xlib.protocol import event
    XLIB_AVAILABLE = True
except ImportError:
    XLIB_AVAILABLE = False
    if not IS_WAYLAND:
        logger.warning("python-xlib not available, falling back to xdotool")

# Try to import AT-SPI for Wayland support (native Wayland apps with accessibility)
ATSPI_AVAILABLE = False
if IS_WAYLAND:
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        ATSPI_AVAILABLE = True
        logger.info("AT-SPI available for Wayland window monitoring")
    except (ImportError, ValueError) as e:
        logger.warning(f"AT-SPI not available for Wayland: {e}")

# Try to import libwnck for XWayland window support (works better for XWayland apps)
WNCK_AVAILABLE = False
if IS_WAYLAND:
    try:
        import gi
        gi.require_version('Wnck', '3.0')
        gi.require_version('Gdk', '3.0')
        from gi.repository import Wnck, Gdk
        # Initialize GDK (required for Wnck)
        Gdk.init([])
        WNCK_AVAILABLE = True
        logger.info("libwnck available for XWayland window monitoring")
    except (ImportError, ValueError) as e:
        logger.debug(f"libwnck not available: {e}")


@dataclass
class WindowInfo:
    """Information about a window."""
    window_id: int
    title: str
    window_class: str
    instance_name: str
    pid: int
    is_fullscreen: bool
    is_maximized: bool  # True if maximized horizontally AND vertically
    geometry: Tuple[int, int, int, int]  # x, y, width, height
    
    def matches_pattern(self, pattern: str) -> bool:
        """Check if window matches a glob-style pattern."""
        import fnmatch
        pattern_lower = pattern.lower()
        return (
            fnmatch.fnmatch(self.window_class.lower(), pattern_lower) or
            fnmatch.fnmatch(self.instance_name.lower(), pattern_lower) or
            fnmatch.fnmatch(self.title.lower(), pattern_lower)
        )


class WindowMonitorX11:
    """
    Window monitor using X11/Xlib.
    
    Monitors the active window and detects fullscreen state changes.
    """
    
    def __init__(self):
        """Initialize X11 window monitor."""
        if not XLIB_AVAILABLE:
            raise RuntimeError("Xlib not available")
            
        self._display = display.Display()
        self._root = self._display.screen().root
        self._atoms = {
            'active_window': self._display.intern_atom('_NET_ACTIVE_WINDOW'),
            'wm_class': self._display.intern_atom('WM_CLASS'),
            'wm_name': self._display.intern_atom('_NET_WM_NAME'),
            'wm_pid': self._display.intern_atom('_NET_WM_PID'),
            'wm_state': self._display.intern_atom('_NET_WM_STATE'),
            'fullscreen': self._display.intern_atom('_NET_WM_STATE_FULLSCREEN'),
            'maximized_vert': self._display.intern_atom('_NET_WM_STATE_MAXIMIZED_VERT'),
            'maximized_horz': self._display.intern_atom('_NET_WM_STATE_MAXIMIZED_HORZ'),
        }
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[WindowInfo], None]] = None
        self._last_window_id = 0
        self._last_fullscreen = False
        self._last_maximized = False
        self._current_window = None  # Track current X window for event subscription
        
    def get_active_window(self) -> Optional[WindowInfo]:
        """
        Get information about the currently active window.
        
        Returns:
            WindowInfo for the active window, or None if no window is active
        """
        try:
            # Get active window ID
            prop = self._root.get_full_property(
                self._atoms['active_window'], 
                X.AnyPropertyType
            )
            if not prop or not prop.value:
                return None
                
            window_id = prop.value[0]
            if window_id == 0:
                return None
                
            window = self._display.create_resource_object('window', window_id)
            return self._get_window_info(window, window_id)
            
        except Exception as e:
            logger.debug(f"Error getting active window: {e}")
            return None
    
    def _get_window_info(self, window, window_id: int) -> Optional[WindowInfo]:
        """Get WindowInfo for a specific window."""
        try:
            # Get window class
            wm_class = window.get_wm_class()
            if wm_class:
                instance_name, window_class = wm_class
            else:
                instance_name = window_class = ""
            
            # Get window title
            title = ""
            try:
                prop = window.get_full_property(
                    self._atoms['wm_name'],
                    X.AnyPropertyType
                )
                if prop:
                    title = prop.value.decode('utf-8', errors='replace')
            except Exception:
                pass
            
            if not title:
                title = window.get_wm_name() or ""
            
            # Get PID
            pid = 0
            try:
                prop = window.get_full_property(
                    self._atoms['wm_pid'],
                    X.AnyPropertyType
                )
                if prop and prop.value:
                    pid = prop.value[0]
            except Exception:
                pass
            
            # Check fullscreen and maximized state
            is_fullscreen = False
            is_maximized = False
            try:
                prop = window.get_full_property(
                    self._atoms['wm_state'],
                    X.AnyPropertyType
                )
                if prop and prop.value:
                    is_fullscreen = self._atoms['fullscreen'] in prop.value
                    # Check for both horizontal and vertical maximized
                    is_maximized = (self._atoms['maximized_vert'] in prop.value and 
                                   self._atoms['maximized_horz'] in prop.value)
            except Exception:
                pass
            
            # Get geometry - need absolute (root) coordinates
            try:
                geom = window.get_geometry()
                
                # Walk up the window tree to accumulate x,y offsets to get absolute position
                abs_x, abs_y = 0, 0
                current = window
                while current and current.id != self._root.id:
                    current_geom = current.get_geometry()
                    abs_x += current_geom.x
                    abs_y += current_geom.y
                    tree = current.query_tree()
                    current = tree.parent
                
                geometry = (abs_x, abs_y, geom.width, geom.height)
            except Exception as e:
                logger.debug(f"Error getting window geometry: {e}")
                geometry = (0, 0, 0, 0)
            
            return WindowInfo(
                window_id=window_id,
                title=title,
                window_class=window_class,
                instance_name=instance_name,
                pid=pid,
                is_fullscreen=is_fullscreen,
                is_maximized=is_maximized,
                geometry=geometry,
            )
            
        except Exception as e:
            logger.debug(f"Error getting window info: {e}")
            return None
    
    def start_monitoring(self, callback: Callable[[WindowInfo], None]):
        """
        Start monitoring window changes.
        
        Args:
            callback: Function called when active window changes
        """
        if self._running:
            return
            
        self._callback = callback
        self._running = True
        
        # Subscribe to property changes on root window (for active window changes)
        self._root.change_attributes(event_mask=X.PropertyChangeMask)
        
        # Subscribe to current active window's state changes
        self._on_active_window_change()
        
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Started X11 window monitoring (event-driven)")
    
    def stop_monitoring(self):
        """Stop monitoring window changes."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("Stopped X11 window monitoring")
    
    def _monitor_loop(self):
        """Main monitoring loop - event-driven for window and state changes."""
        while self._running:
            try:
                # Process all pending events
                while self._display.pending_events():
                    ev = self._display.next_event()
                    if ev.type == X.PropertyNotify:
                        # Active window changed on root
                        if ev.atom == self._atoms['active_window']:
                            self._on_active_window_change()
                        # Window state changed (fullscreen/maximized) on current window
                        elif ev.atom == self._atoms['wm_state']:
                            self._check_window_change()
                
                # Small sleep to avoid busy-wait, but events are primary trigger
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in window monitor loop: {e}")
                time.sleep(1)
    
    def _on_active_window_change(self):
        """Handle active window change - subscribe to new window's state changes."""
        try:
            # Get new active window
            prop = self._root.get_full_property(
                self._atoms['active_window'], 
                X.AnyPropertyType
            )
            if not prop or not prop.value:
                return
            
            window_id = prop.value[0]
            if window_id == 0:
                return
            
            window = self._display.create_resource_object('window', window_id)
            
            # Unsubscribe from old window's events
            if self._current_window and self._current_window != window:
                try:
                    self._current_window.change_attributes(event_mask=0)
                except Exception:
                    pass  # Window may have been destroyed
            
            # Subscribe to new window's property changes (for state changes)
            self._current_window = window
            try:
                window.change_attributes(event_mask=X.PropertyChangeMask | X.StructureNotifyMask)
            except Exception as e:
                logger.debug(f"Could not subscribe to window events: {e}")
            
            # Check the new window
            self._check_window_change()
            
        except Exception as e:
            logger.debug(f"Error in active window change handler: {e}")
    
    def _check_window_change(self):
        """Check if active window has changed and invoke callback."""
        window = self.get_active_window()
        if window is None:
            return
            
        # Check if window, fullscreen, or maximized state changed
        if (window.window_id != self._last_window_id or 
            window.is_fullscreen != self._last_fullscreen or
            window.is_maximized != self._last_maximized):
            
            self._last_window_id = window.window_id
            self._last_fullscreen = window.is_fullscreen
            self._last_maximized = window.is_maximized
            
            if self._callback:
                try:
                    self._callback(window)
                except Exception as e:
                    logger.error(f"Error in window change callback: {e}")


class WindowMonitorXdotool:
    """
    Window monitor using xdotool (fallback when Xlib not available).
    """
    
    def __init__(self):
        """Initialize xdotool-based window monitor."""
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[WindowInfo], None]] = None
        self._last_window_id = 0
        self._last_fullscreen = False
        self._last_maximized = False
        
    def get_active_window(self) -> Optional[WindowInfo]:
        """Get information about the currently active window."""
        try:
            # Get active window ID
            result = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode != 0:
                return None
                
            window_id = int(result.stdout.strip())
            
            # Get window name
            result = subprocess.run(
                ["xdotool", "getwindowname", str(window_id)],
                capture_output=True,
                text=True,
                timeout=2,
            )
            title = result.stdout.strip() if result.returncode == 0 else ""
            
            # Get window class using xprop
            result = subprocess.run(
                ["xprop", "-id", str(window_id), "WM_CLASS"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            window_class = ""
            instance_name = ""
            if result.returncode == 0:
                match = re.search(r'WM_CLASS.*=\s*"([^"]*)",\s*"([^"]*)"', result.stdout)
                if match:
                    instance_name = match.group(1)
                    window_class = match.group(2)
            
            # Get PID
            result = subprocess.run(
                ["xdotool", "getwindowpid", str(window_id)],
                capture_output=True,
                text=True,
                timeout=2,
            )
            pid = int(result.stdout.strip()) if result.returncode == 0 else 0
            
            # Check fullscreen and maximized state
            result = subprocess.run(
                ["xprop", "-id", str(window_id), "_NET_WM_STATE"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            is_fullscreen = "_NET_WM_STATE_FULLSCREEN" in result.stdout
            is_maximized = ("_NET_WM_STATE_MAXIMIZED_VERT" in result.stdout and 
                           "_NET_WM_STATE_MAXIMIZED_HORZ" in result.stdout)
            
            # Get geometry
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", str(window_id)],
                capture_output=True,
                text=True,
                timeout=2,
            )
            geometry = (0, 0, 0, 0)
            if result.returncode == 0:
                pos_match = re.search(r'Position:\s*(\d+),(\d+)', result.stdout)
                size_match = re.search(r'Geometry:\s*(\d+)x(\d+)', result.stdout)
                if pos_match and size_match:
                    geometry = (
                        int(pos_match.group(1)),
                        int(pos_match.group(2)),
                        int(size_match.group(1)),
                        int(size_match.group(2)),
                    )
            
            return WindowInfo(
                window_id=window_id,
                title=title,
                window_class=window_class,
                instance_name=instance_name,
                pid=pid,
                is_fullscreen=is_fullscreen,
                is_maximized=is_maximized,
                geometry=geometry,
            )
            
        except Exception as e:
            logger.debug(f"Error getting active window: {e}")
            return None
    
    def start_monitoring(self, callback: Callable[[WindowInfo], None]):
        """Start monitoring window changes."""
        if self._running:
            return
            
        self._callback = callback
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Started xdotool window monitoring")
    
    def stop_monitoring(self):
        """Stop monitoring window changes."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("Stopped xdotool window monitoring")
    
    def _monitor_loop(self):
        """Main monitoring loop (polling-based)."""
        while self._running:
            try:
                window = self.get_active_window()
                if window is not None:
                    if (window.window_id != self._last_window_id or
                        window.is_fullscreen != self._last_fullscreen or
                        window.is_maximized != self._last_maximized):
                        
                        self._last_window_id = window.window_id
                        self._last_fullscreen = window.is_fullscreen
                        self._last_maximized = window.is_maximized
                        
                        if self._callback:
                            self._callback(window)
                
                time.sleep(1)  # Poll every second
                
            except Exception as e:
                logger.error(f"Error in window monitor loop: {e}")
                time.sleep(2)


class WindowMonitorWayland:
    """
    Hybrid window monitor for Wayland using AT-SPI + libwnck.
    
    AT-SPI: Works for native Wayland apps with accessibility support
    libwnck: Works for XWayland apps (Java apps, some Electron apps, etc.)
    
    We try libwnck first (more reliable geometry) then fall back to AT-SPI.
    """
    
    def __init__(self):
        """Initialize hybrid Wayland window monitor."""
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[WindowInfo], None]] = None
        self._last_window_key = ""
        self._last_fullscreen = False
        self._last_maximized = False
        
        # Initialize AT-SPI
        self._atspi_desktop = None
        if ATSPI_AVAILABLE:
            self._atspi_desktop = Atspi.get_desktop(0)
            logger.info(f"AT-SPI: Found {self._atspi_desktop.get_child_count()} applications")
        
        # Initialize libwnck
        self._wnck_screen = None
        if WNCK_AVAILABLE:
            self._wnck_screen = Wnck.Screen.get_default()
            if self._wnck_screen:
                self._wnck_screen.force_update()
                logger.info(f"libwnck: Found {len(self._wnck_screen.get_windows())} XWayland windows")
    
    def _get_active_window_wnck(self) -> Optional[WindowInfo]:
        """Get active window from libwnck (XWayland apps)."""
        if not self._wnck_screen:
            return None
        
        try:
            self._wnck_screen.force_update()
            active = self._wnck_screen.get_active_window()
            
            if active and active.get_window_type() == Wnck.WindowType.NORMAL:
                geo = active.get_client_window_geometry()
                
                # Check maximized state (both vertical and horizontal)
                is_maximized = active.is_maximized_vertically() and active.is_maximized_horizontally()
                
                return WindowInfo(
                    window_id=active.get_xid(),
                    title=active.get_name() or "",
                    window_class=active.get_class_group_name() or "",
                    instance_name=active.get_class_instance_name() or "",
                    pid=active.get_pid(),
                    is_fullscreen=active.is_fullscreen(),
                    is_maximized=is_maximized,
                    geometry=(geo[0], geo[1], geo[2], geo[3]),
                )
        except Exception as e:
            logger.debug(f"libwnck get_active failed: {e}")
        
        return None
    
    def _get_active_window_atspi(self) -> Optional[WindowInfo]:
        """Get active window from AT-SPI (native Wayland apps)."""
        if not self._atspi_desktop:
            return None
        
        try:
            # Refresh desktop
            self._atspi_desktop = Atspi.get_desktop(0)
            
            skip_apps = {'gnome-shell', 'ibus-extension-gtk3', 'gsd-', 'evolution-alarm'}
            
            for i in range(self._atspi_desktop.get_child_count()):
                app = self._atspi_desktop.get_child_at_index(i)
                if not app:
                    continue
                
                app_name = app.get_name() or ""
                if any(skip in app_name.lower() for skip in skip_apps):
                    continue
                
                for j in range(app.get_child_count()):
                    window = app.get_child_at_index(j)
                    if not window:
                        continue
                    
                    try:
                        states = window.get_state_set()
                        if not states or not states.contains(Atspi.StateType.ACTIVE):
                            continue
                        
                        win_name = window.get_name() or ""
                        
                        # Get geometry
                        geometry = (0, 0, 0, 0)
                        try:
                            comp = window.get_component_iface()
                            if comp:
                                rect = comp.get_extents(Atspi.CoordType.SCREEN)
                                geometry = (rect.x, rect.y, rect.width, rect.height)
                        except Exception:
                            pass
                        
                        pid = 0
                        try:
                            pid = app.get_process_id()
                        except Exception:
                            pass
                        
                        is_fullscreen = False
                        is_maximized = False
                        try:
                            if hasattr(Atspi.StateType, 'FULLSCREEN'):
                                is_fullscreen = states.contains(Atspi.StateType.FULLSCREEN)
                            # AT-SPI doesn't have separate H/V maximized, just check if window is maximized
                            # by checking if geometry fills the screen (rough approximation)
                            # For now, assume not maximized if we can't determine
                        except Exception:
                            pass
                        
                        return WindowInfo(
                            window_id=hash(f"{app_name}:{win_name}"),
                            title=win_name,
                            window_class=app_name,
                            instance_name=app_name.lower(),
                            pid=pid,
                            is_fullscreen=is_fullscreen,
                            is_maximized=is_maximized,
                            geometry=geometry,
                        )
                    except Exception as e:
                        logger.debug(f"AT-SPI window check error: {e}")
                        continue
        except Exception as e:
            logger.debug(f"AT-SPI get_active failed: {e}")
        
        return None
    
    def get_active_window(self) -> Optional[WindowInfo]:
        """
        Get the currently active window using hybrid approach.
        
        Tries libwnck first (better geometry for XWayland apps like Vivado, Firefox),
        then falls back to AT-SPI (for native Wayland apps like Slack, native Firefox).
        """
        # Try libwnck first - more reliable for XWayland apps
        result = self._get_active_window_wnck()
        if result:
            logger.debug(f"Wayland: Active window (wnck): {result.window_class} @ {result.geometry}")
            return result
        
        # Fall back to AT-SPI for native Wayland apps
        result = self._get_active_window_atspi()
        if result:
            logger.debug(f"Wayland: Active window (atspi): {result.window_class} @ {result.geometry}")
            return result
        
        return None
    
    def start_monitoring(self, callback: Callable[[WindowInfo], None]):
        """Start monitoring window changes."""
        if self._running:
            return
        
        self._callback = callback
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Wayland hybrid window monitoring started")
    
    def stop_monitoring(self):
        """Stop monitoring window changes."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
    
    def _monitor_loop(self):
        """Main monitoring loop - polls for active window changes."""
        while self._running:
            try:
                window = self.get_active_window()
                if window:
                    # Create unique key for window
                    current_key = f"{window.window_class}:{window.title[:50]}"
                    # Also check for fullscreen/maximized state changes
                    state_changed = (window.is_fullscreen != self._last_fullscreen or
                                   window.is_maximized != self._last_maximized)
                    
                    if current_key != self._last_window_key or state_changed:
                        self._last_window_key = current_key
                        self._last_fullscreen = window.is_fullscreen
                        self._last_maximized = window.is_maximized
                        if self._callback:
                            try:
                                self._callback(window)
                            except Exception as e:
                                logger.error(f"Error in window change callback: {e}")
            except Exception as e:
                logger.debug(f"Wayland monitor loop error: {e}")
            
            time.sleep(1)  # Poll every second


# Keep old class name as alias for backwards compatibility
WindowMonitorAtspi = WindowMonitorWayland


class WindowMonitor:
    """
    Unified window monitor that uses the best available method.
    """
    
    def __init__(self):
        """Initialize window monitor with best available backend."""
        # On Wayland, use hybrid approach (libwnck + AT-SPI)
        if IS_WAYLAND and (WNCK_AVAILABLE or ATSPI_AVAILABLE):
            try:
                self._backend = WindowMonitorWayland()
                backends = []
                if WNCK_AVAILABLE:
                    backends.append("libwnck")
                if ATSPI_AVAILABLE:
                    backends.append("AT-SPI")
                self._backend_name = f"Wayland ({'+'.join(backends)})"
            except Exception as e:
                logger.warning(f"Failed to initialize Wayland backend: {e}")
                self._backend = WindowMonitorXdotool()
                self._backend_name = "xdotool (fallback)"
        elif XLIB_AVAILABLE:
            try:
                self._backend = WindowMonitorX11()
                self._backend_name = "X11/Xlib"
            except Exception as e:
                logger.warning(f"Failed to initialize X11 backend: {e}")
                self._backend = WindowMonitorXdotool()
                self._backend_name = "xdotool"
        else:
            self._backend = WindowMonitorXdotool()
            self._backend_name = "xdotool"
            
        logger.info(f"Using window monitor backend: {self._backend_name}")
    
    def get_active_window(self) -> Optional[WindowInfo]:
        """Get information about the currently active window."""
        return self._backend.get_active_window()
    
    def start_monitoring(self, callback: Callable[[WindowInfo], None]):
        """Start monitoring window changes."""
        self._backend.start_monitoring(callback)
    
    def stop_monitoring(self):
        """Stop monitoring window changes."""
        self._backend.stop_monitoring()


def check_window_tools() -> Tuple[bool, str]:
    """
    Check if required window management tools are available.
    
    Returns:
        Tuple of (tools_available, message)
    """
    # On Wayland, we use hybrid libwnck + AT-SPI
    if IS_WAYLAND:
        backends = []
        if WNCK_AVAILABLE:
            backends.append("libwnck (XWayland)")
        if ATSPI_AVAILABLE:
            backends.append("AT-SPI (native)")
        if backends:
            return True, f"Wayland window monitoring: {', '.join(backends)}"
    
    if XLIB_AVAILABLE:
        return True, "python-xlib available for X11 window monitoring"
    
    # Check for xdotool
    try:
        result = subprocess.run(
            ["xdotool", "--version"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return True, "xdotool available for window monitoring"
    except FileNotFoundError:
        pass
    except Exception:
        pass
    
    if IS_WAYLAND:
        return False, (
            "No window monitoring tools available for Wayland.\n"
            "Install python3-gi and gir1.2-atspi-2.0 for AT-SPI support."
        )
    
    return False, (
        "No window monitoring tools available.\n"
        "Install python-xlib: pip install python-xlib\n"
        "Or install xdotool: sudo apt install xdotool"
    )


