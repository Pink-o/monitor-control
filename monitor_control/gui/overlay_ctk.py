"""
CustomTkinter-based Modern OSD Overlay
======================================
Beautiful, modern UI for monitor control
"""

import json
import logging
import threading
import os
import tkinter as tk
from pathlib import Path
import customtkinter as ctk
from typing import Callable, Dict, Optional, List

# Window geometry persistence file
WINDOW_GEOMETRY_FILE = Path.home() / ".config" / "monitor-control" / "window_geometry.json"

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)

# Set appearance mode and theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class SmartOptionMenu(ctk.CTkOptionMenu):
    """CTkOptionMenu that attempts to drop up when near the bottom of the screen."""
    
    def _open_dropdown_menu(self):
        """Override to reposition dropdown if it would go off screen."""
        # Get screen dimensions and button position
        try:
            screen_height = self.winfo_screenheight()
            button_y = self.winfo_rooty()
            button_height = self.winfo_height()
            
            # Estimate dropdown height (roughly 32px per item)
            num_items = len(self._values) if hasattr(self, '_values') else 5
            dropdown_height = min(num_items * 32 + 20, 400)
            
            # Check if dropdown would go below screen
            if button_y + button_height + dropdown_height > screen_height - 20:
                # Store flag to indicate we should drop up
                self._should_drop_up = True
            else:
                self._should_drop_up = False
        except Exception:
            self._should_drop_up = False
        
        # Call parent implementation
        super()._open_dropdown_menu()
        
        # Try to reposition if needed
        if getattr(self, '_should_drop_up', False):
            try:
                if hasattr(self, '_dropdown_menu') and self._dropdown_menu:
                    menu = self._dropdown_menu
                    # Give it a moment to render
                    self.after(10, lambda: self._reposition_menu_up(menu))
            except Exception:
                pass
    
    def _reposition_menu_up(self, menu):
        """Reposition menu above the button."""
        try:
            button_y = self.winfo_rooty()
            menu_height = menu.winfo_reqheight()
            menu_x = self.winfo_rootx()
            # Post menu above the button
            menu.post(menu_x, button_y - menu_height)
        except Exception:
            pass  # Fall back to default position


class MonitorOverlayCTk:
    """
    Modern OSD-style overlay using CustomTkinter.
    """
    
    # Color scheme
    COLORS = {
        'accent': '#FF6B00',  # BenQ orange
        'accent_hover': '#FF8533',
        'bg': '#1a1a1a',
        'bg_secondary': '#2d2d2d',
        'bg_tertiary': '#3a3a3a',  # Slightly lighter than secondary
        'border': '#3d3d3d',
        'text': '#ffffff',
        'text_dim': '#888888',
    }
    
    # Font sizes - change these to adjust all text sizes
    FONT_SIZES = {
        'title': 12,            # Section titles, headers
        'normal': 12,           # Normal text, labels
        'small': 12,             # Small labels, hints
        'button': 10,           # Button text
        'slider_label': 9,      # Slider value labels
        'icon': 12,             # Emoji/icon text in rows
        'icon_large': 20,       # Large icons
        'value': 12,            # Value displays (brightness %, etc.)
    }
    
    def __init__(
        self,
        position: str = "center",
        timeout: float = 0,
        theme: str = "dark",
    ):
        """Initialize the CustomTkinter overlay."""
        self.position = position
        self.timeout = timeout
        self.theme = theme
        
        self._root: Optional[ctk.CTk] = None
        self._visible = False
        self._hide_timer: Optional[str] = None
        self._callbacks: Dict[str, Callable] = {}
        
        # Current values
        self._brightness = 50
        self._contrast = 50
        self._color_mode = 0
        self._color_mode_names = ["Standard"]
        self._all_color_modes = {}
        self._monitor_color_modes: Dict[int, Dict[str, int]] = {}  # Per-monitor: {display_num: {name: vcp_value}}
        self._status_text = "Profile: Default"
        
        # Profile management
        self._available_profiles: List[str] = []
        self._profile_color_modes: Dict[str, str] = {}
        self._current_profile_name = "default"
        self._profile_widgets = {}
        self._current_app_classes: Dict[int, str] = {}  # display_num -> current app class
        
        # Adaptive settings (separate brightness and contrast)
        self._auto_brightness_enabled = False
        self._auto_contrast_enabled = False
        
        # Thread management
        self._tk_thread: Optional[threading.Thread] = None
        self._running = False
        self._initialized = threading.Event()
        
        # Debounce timer
        self._interval_debounce_timer = None
        self._slider_debounce_timers = {}  # Key: (callback_name, display_num)
        self._slider_debounce_delay = 100  # ms - short delay, main.py handles skipping outdated values
        self._updating_from_code = False  # Flag to prevent callback loops when setting slider values programmatically
        
    def _create_window(self):
        """Create the CustomTkinter window."""
        # Detect and apply system DPI scaling for Linux
        scale_factor = self._detect_system_scale()
        if scale_factor > 1.0:
            ctk.set_widget_scaling(scale_factor)
            logger.info(f"Applied widget scaling: {scale_factor}")
        
        self._root = ctk.CTk(className='monitor-control')
        self._root.title("Monitor Control")
        
        # Set WM_CLASS properly for Linux
        try:
            self._root.tk.call('tk', 'appname', 'monitor-control')
        except Exception:
            pass
        
        # Set window icon
        self._set_window_icon()
        
        # Window settings
        self._root.attributes('-topmost', True)
        self._root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        
        # Set size and position - try to restore saved geometry first
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()
        
        saved_geom = self._load_window_geometry()
        if saved_geom:
            # Use saved geometry, but ensure it's still on screen
            width = saved_geom.get('width', 650)
            height = saved_geom.get('height', 1050)
            x = saved_geom.get('x', 0)
            y = saved_geom.get('y', 0)
            
            # Make sure window is visible on current screen setup
            if x < -width + 50:
                x = 50
            if y < -height + 50:
                y = 50
            if x > screen_width - 50:
                x = screen_width - width - 50
            if y > screen_height - 50:
                y = screen_height - height - 50
            
            logger.info(f"Restored window geometry: {width}x{height}+{x}+{y}")
        else:
            # Default size
            width, height = 650, 1050
            
            # Make sure window fits on screen
            if height > screen_height - 100:
                height = screen_height - 100
            if width > screen_width - 100:
                width = screen_width - 100
            
            if self.position == "center":
                x = (screen_width - width) // 2
                y = (screen_height - height) // 2
            elif self.position == "bottom-center":
                x = (screen_width - width) // 2
                y = screen_height - height - 100
            else:
                x = (screen_width - width) // 2
                y = (screen_height - height) // 2
        
        self._root.geometry(f"{width}x{height}+{x}+{y}")
        self._root.minsize(300, 600)
        
        # Loading overlay (shown during startup)
        self._loading_frame = ctk.CTkFrame(
            self._root,
            fg_color=self.COLORS['bg'],
            corner_radius=0
        )
        self._loading_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        loading_content = ctk.CTkFrame(self._loading_frame, fg_color="transparent")
        loading_content.place(relx=0.5, rely=0.5, anchor="center")
        
        # Try to load app icon for loading screen
        self._loading_icon = self._load_app_icon(size=96)
        if self._loading_icon:
            ctk.CTkLabel(
                loading_content,
                text="",
                image=self._loading_icon
            ).pack(pady=(0, 20))
        else:
            # Fallback to text if icon not available
            ctk.CTkLabel(
                loading_content,
                text="MC",
                font=ctk.CTkFont(size=48, weight="bold"),
                text_color=self.COLORS['accent']
            ).pack(pady=(0, 20))
        
        ctk.CTkLabel(
            loading_content,
            text="Monitor Control",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=self.COLORS['text']
        ).pack(pady=(0, 10))
        
        self._loading_label = ctk.CTkLabel(
            loading_content,
            text="Reading monitor settings...",
            font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
            text_color=self.COLORS['text_dim']
        )
        self._loading_label.pack(pady=(0, 20))
        
        self._loading_progress = ctk.CTkProgressBar(
            loading_content,
            width=300,
            height=8,
            progress_color=self.COLORS['accent'],
            fg_color=self.COLORS['bg_secondary'],
            mode="indeterminate"
        )
        self._loading_progress.pack()
        self._loading_progress.start()
        
        # Main frame (hidden initially) - not scrollable since each tab has its own scroll
        self._main_frame = ctk.CTkFrame(
            self._root,
            fg_color="transparent"
        )
        # Don't pack yet - will be shown after loading
        
        # Header (just title, no monitor selector)
        self._create_header()
        
        # Monitor tabs container
        self._create_monitor_tabs()
        
        # Key bindings
        self._root.bind('<Escape>', lambda e: self.hide_overlay())
        self._root.bind('q', lambda e: self.hide_overlay())
        
        self._visible = True
        self._initialized.set()
        logger.info("CustomTkinter overlay initialized")
    
    def _create_header(self):
        """Create the header section."""
        header_frame = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 4))
        
        # App icon
        self._header_icon = self._load_app_icon(size=32)
        if self._header_icon:
            icon_label = ctk.CTkLabel(header_frame, text="", image=self._header_icon)
            icon_label.pack(side="left", padx=(0, 10))
        
        # Title
        title = ctk.CTkLabel(
            header_frame,
            text="Monitor Control",
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color=self.COLORS['accent']
        )
        title.pack(side="left")
        
        # Refresh button (to re-detect monitors)
        self._refresh_btn = ctk.CTkButton(
            header_frame,
            text="⟳",
            width=36,
            height=36,
            font=ctk.CTkFont(size=22, weight="bold"),
            fg_color="transparent",
            hover_color=self.COLORS['bg_secondary'],
            text_color=self.COLORS['accent'],
            corner_radius=8,
            command=self._on_refresh_monitors
        )
        self._refresh_btn.pack(side="right", padx=(5, 0))
        
        # Store monitor info for mapping tab names to display numbers
        self._monitors: List[tuple] = []  # [(display_num, display_name), ...]
        self._monitor_tabs: Dict[int, ctk.CTkFrame] = {}  # display_num -> tab frame
        self._monitor_widgets: Dict[int, Dict] = {}  # display_num -> widget references
        self._overview_widgets: Dict[int, Dict] = {}  # display_num -> overview widget references
        self._monitor_geometries: Dict[int, Dict] = {}  # display_num -> geometry info for graphical display
    
    def _bind_mousewheel(self, scrollable_frame):
        """Bind mouse wheel scrolling to a CTkScrollableFrame.
        
        Uses Enter/Leave events to track which scrollable frame should receive scroll events.
        Also auto-hides scrollbar when content fits vertically.
        """
        # Try to get internal canvas - may vary by CTk version
        canvas = getattr(scrollable_frame, '_parent_canvas', None)
        if canvas is None:
            # Fallback: try to find canvas in children
            for child in scrollable_frame.winfo_children():
                if 'canvas' in str(type(child)).lower():
                    canvas = child
                    break
        
        if canvas is None:
            logger.debug("Could not find canvas in scrollable frame, skipping mousewheel binding")
            return
        
        # Initialize the list of scrollbar check functions if not exists
        if not hasattr(self, '_scrollbar_check_funcs'):
            self._scrollbar_check_funcs = []
        
        def on_mousewheel(event):
            # Scroll the frame vertically
            try:
                # Check if vertical scrolling is needed
                yview = canvas.yview()
                if yview != (0.0, 1.0):
                    if event.num == 4 or event.delta > 0:  # Scroll up
                        canvas.yview_scroll(-3, "units")
                    elif event.num == 5 or event.delta < 0:  # Scroll down
                        canvas.yview_scroll(3, "units")
                    return "break"  # Prevent event propagation
            except Exception:
                pass
        
        def on_enter(event):
            # Bind mousewheel when mouse enters the scrollable frame
            scrollable_frame.bind_all("<Button-4>", on_mousewheel)
            scrollable_frame.bind_all("<Button-5>", on_mousewheel)
            scrollable_frame.bind_all("<MouseWheel>", on_mousewheel)
        
        def on_leave(event):
            # Unbind mousewheel when mouse leaves
            try:
                scrollable_frame.unbind_all("<Button-4>")
                scrollable_frame.unbind_all("<Button-5>")
                scrollable_frame.unbind_all("<MouseWheel>")
            except Exception:
                pass
        
        # Track last height to avoid unnecessary updates
        last_height = [0]
        scrollbar_ref = [None]
        
        def find_scrollbar():
            """Find the scrollbar widget in the scrollable frame."""
            if scrollbar_ref[0]:
                return scrollbar_ref[0]
            # Try common attribute names
            for attr in ['_scrollbar', '_y_scrollbar', 'scrollbar']:
                sb = getattr(scrollable_frame, attr, None)
                if sb:
                    scrollbar_ref[0] = sb
                    return sb
            # Search children for scrollbar-like widgets
            try:
                for child in scrollable_frame.winfo_children():
                    child_type = str(type(child)).lower()
                    if 'scrollbar' in child_type:
                        scrollbar_ref[0] = child
                        return child
            except Exception:
                pass
            return None
        
        def check_scrollbar_visibility(event=None):
            """Hide scrollbar if content fits vertically in view."""
            try:
                scrollbar = find_scrollbar()
                if not scrollbar or not canvas:
                    return
                
                # Force update to get accurate dimensions
                canvas.update_idletasks()
                scrollable_frame.update_idletasks()
                
                # Get frame height and scroll region
                frame_height = scrollable_frame.winfo_height()
                
                # Skip if height hasn't changed significantly (unless forced)
                if event and abs(frame_height - last_height[0]) < 5:
                    return
                last_height[0] = frame_height
                
                # Get the scroll region - this tells us the actual content size
                scroll_region = canvas.cget('scrollregion')
                if scroll_region:
                    # Parse scroll region (x1, y1, x2, y2)
                    parts = scroll_region.split()
                    if len(parts) >= 4:
                        content_height = int(float(parts[3])) - int(float(parts[1]))
                        visible_height = canvas.winfo_height()
                        
                        if content_height <= visible_height:
                            # Content fits, hide scrollbar
                            try:
                                scrollbar.grid_remove()
                            except Exception:
                                try:
                                    scrollbar.pack_forget()
                                except Exception:
                                    pass
                            return
                
                # Fallback: use yview check
                yview = canvas.yview()
                
                if yview == (0.0, 1.0):
                    # Content fits vertically, hide scrollbar
                    try:
                        scrollbar.grid_remove()
                    except Exception:
                        try:
                            scrollbar.pack_forget()
                        except Exception:
                            pass
                else:
                    # Content doesn't fit, show scrollbar
                    try:
                        scrollbar.grid()
                    except Exception:
                        try:
                            scrollbar.pack(side="right", fill="y")
                        except Exception:
                            pass
            except Exception:
                pass
        
        # Bind Enter/Leave to control mousewheel binding
        scrollable_frame.bind("<Enter>", on_enter, add="+")
        scrollable_frame.bind("<Leave>", on_leave, add="+")
        
        # Check scrollbar visibility on resize and when frame becomes visible
        scrollable_frame.bind("<Configure>", check_scrollbar_visibility, add="+")
        scrollable_frame.bind("<Map>", lambda e: self._root.after(50, check_scrollbar_visibility) if self._root else None, add="+")
        scrollable_frame.bind("<Visibility>", lambda e: self._root.after(50, check_scrollbar_visibility) if self._root else None, add="+")
        
        # Store the check function for later use (e.g., when sections are toggled)
        self._scrollbar_check_funcs.append(check_scrollbar_visibility)
        
        # Check scrollbar visibility after multiple delays (let content render)
        # Need several checks because CTkScrollableFrame takes time to calculate scroll region
        if self._root:
            for delay in [100, 200, 500, 1000, 1500, 2000, 3000]:
                self._root.after(delay, check_scrollbar_visibility)
    
    def _trigger_all_scrollbar_checks(self):
        """Trigger scrollbar visibility checks on all registered scrollable frames."""
        if hasattr(self, '_scrollbar_check_funcs'):
            for check_func in self._scrollbar_check_funcs:
                try:
                    check_func()
                except Exception:
                    pass
    
    def _create_monitor_tabs(self):
        """Create the tabbed interface for monitors."""
        # Create tabview
        self._tabview = ctk.CTkTabview(
            self._main_frame,
            fg_color=self.COLORS['bg'],
            segmented_button_fg_color=self.COLORS['bg_secondary'],
            segmented_button_selected_color=self.COLORS['accent'],
            segmented_button_selected_hover_color=self.COLORS['accent_hover'],
            segmented_button_unselected_color=self.COLORS['bg_secondary'],
            segmented_button_unselected_hover_color=self.COLORS['border'],
            text_color=self.COLORS['text'],
            corner_radius=4,
        )
        self._tabview.pack(fill="both", expand=True, pady=0)
        
        # Initial placeholder tab (will be replaced when monitors are detected)
        self._tabview.add("Detecting...")
        placeholder = self._tabview.tab("Detecting...")
        ctk.CTkLabel(
            placeholder,
            text="🔍 Detecting monitors...",
            font=ctk.CTkFont(size=self.FONT_SIZES['title']),
            text_color=self.COLORS['text_dim']
        ).pack(expand=True)
        
        # Bind tab change event
        self._tabview.configure(command=self._on_tab_changed)
    
    def _on_tab_changed(self):
        """Handle tab selection change."""
        if not hasattr(self, '_tabview'):
            return
        
        # Hide monitor selection highlight when changing tabs
        self._hide_monitor_selection()
            
        tab_name = self._tabview.get()
        
        # Overview tab doesn't trigger monitor change
        if tab_name == "📊 Overview":
            logger.info("Switched to Overview tab")
            return
        
        # Find the display number for this tab
        for display_num, display_name in self._monitors:
            if display_name == tab_name:
                logger.info(f"Tab changed to: {display_name} (display {display_num})")
                self._invoke_callback('monitor_change', display_num)
                break
    
    def _create_monitor_tab_content(self, parent: ctk.CTkFrame, display_num: int) -> Dict:
        """Create all controls for a monitor tab. Returns dict of widget references."""
        widgets = {}
        
        # Configure parent to expand
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        
        # Scrollable frame for all content - minimal padding
        scrollable = ctk.CTkScrollableFrame(
            parent,
            fg_color="transparent",
            scrollbar_button_color=self.COLORS['bg_secondary'],
            scrollbar_button_hover_color=self.COLORS['accent'],
        )
        scrollable.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        
        # Hide scrollbar initially - it will be shown if needed after content is created
        try:
            if hasattr(scrollable, '_scrollbar'):
                scrollable._scrollbar.grid_remove()
        except Exception:
            pass
        
        # Enable mouse wheel scrolling and auto-hide scrollbar
        self._bind_mousewheel(scrollable)
        
        # Screen analysis gauges at the top
        gauges_frame = ctk.CTkFrame(scrollable, fg_color=self.COLORS['bg_secondary'], corner_radius=4, border_width=0)
        gauges_frame.pack(fill="x", pady=(0, 4))
        
        gauges_inner = ctk.CTkFrame(gauges_frame, fg_color="transparent")
        gauges_inner.pack(fill="x", padx=6, pady=4)
        
        widgets['gauge_mean'] = self._create_gauge(gauges_inner, "Mean", self.COLORS['accent'])
        widgets['gauge_dark'] = self._create_gauge(gauges_inner, "Dark", "#4488FF")
        widgets['gauge_bright'] = self._create_gauge(gauges_inner, "Bright", "#FFCC00")
        
        # DDC Status indicator
        ddc_frame = ctk.CTkFrame(scrollable, fg_color=self.COLORS['bg_secondary'], corner_radius=4, border_width=0)
        ddc_frame.pack(fill="x", pady=(0, 4))
        
        ddc_inner = ctk.CTkFrame(ddc_frame, fg_color="transparent")
        ddc_inner.pack(fill="x", padx=6, pady=4)
        
        ctk.CTkLabel(
            ddc_inner, text="DDC Status:",
            font=ctk.CTkFont(size=self.FONT_SIZES['button']),
            text_color=self.COLORS['text_dim']
        ).pack(side="left")
        
        # Status dot (canvas for colored circle)
        import tkinter as tk
        ddc_dot = tk.Canvas(ddc_inner, width=12, height=12, bg=self.COLORS['bg_secondary'], 
                           highlightthickness=0)
        ddc_dot.pack(side="left", padx=(8, 4))
        ddc_dot.create_oval(2, 2, 10, 10, fill="#44AA44", outline="", tags="dot")
        widgets['ddc_indicator'] = ddc_dot
        
        widgets['ddc_status'] = ctk.CTkLabel(
            ddc_inner, text="Idle",
            font=ctk.CTkFont(size=self.FONT_SIZES['button']),
            text_color="#44AA44"
        )
        widgets['ddc_status'].pack(side="left")
        
        # Basic Controls section
        basic_content = self._create_section(scrollable, "Basic Controls", "🔆")
        widgets['brightness_slider'], widgets['brightness_label'] = self._create_slider_for_tab(
            basic_content, "Brightness", "☀️", lambda v, d=display_num: self._on_brightness_for_tab(v, d)
        )
        widgets['contrast_slider'], widgets['contrast_label'] = self._create_slider_for_tab(
            basic_content, "Contrast", "◐", lambda v, d=display_num: self._on_contrast_for_tab(v, d)
        )
        widgets['sharpness_slider'], widgets['sharpness_label'] = self._create_slider_for_tab(
            basic_content, "Sharpness", "🔳", lambda v, d=display_num: self._on_sharpness_for_tab(v, d)
        )
        
        # Refresh button for basic controls only (brightness/contrast/sharpness)
        refresh_frame = ctk.CTkFrame(basic_content, fg_color="transparent")
        refresh_frame.pack(fill="x", pady=(10, 0))
        widgets['refresh_basic_btn'] = ctk.CTkButton(
            refresh_frame,
            text="⟳",
            width=36,
            height=28,
            font=ctk.CTkFont(size=self.FONT_SIZES['icon'], weight="bold"),
            fg_color=self.COLORS['bg_tertiary'],
            hover_color=self.COLORS['accent'],
            command=lambda d=display_num: self._on_refresh_basic_values(d)
        )
        widgets['refresh_basic_btn'].pack(side="right")
        
        # RGB Gain section
        rgb_content = self._create_section(scrollable, "RGB Gain", "🎨")
        widgets['red_slider'], widgets['red_label'] = self._create_colored_slider_for_tab(
            rgb_content, "Red", "#FF4444", lambda v, d=display_num: self._on_rgb_for_tab('red', v, d)
        )
        widgets['green_slider'], widgets['green_label'] = self._create_colored_slider_for_tab(
            rgb_content, "Green", "#44FF44", lambda v, d=display_num: self._on_rgb_for_tab('green', v, d)
        )
        widgets['blue_slider'], widgets['blue_label'] = self._create_colored_slider_for_tab(
            rgb_content, "Blue", "#4488FF", lambda v, d=display_num: self._on_rgb_for_tab('blue', v, d)
        )
        
        # Refresh button for RGB values only
        rgb_refresh_frame = ctk.CTkFrame(rgb_content, fg_color="transparent")
        rgb_refresh_frame.pack(fill="x", pady=(10, 0))
        widgets['refresh_rgb_btn'] = ctk.CTkButton(
            rgb_refresh_frame,
            text="⟳",
            width=36,
            height=28,
            font=ctk.CTkFont(size=self.FONT_SIZES['icon'], weight="bold"),
            fg_color=self.COLORS['bg_tertiary'],
            hover_color=self.COLORS['accent'],
            command=lambda d=display_num: self._on_refresh_rgb_values(d)
        )
        widgets['refresh_rgb_btn'].pack(side="right")
        
        # Color Mode section
        mode_content = self._create_section(scrollable, "Color Mode", "🖼️")
        mode_frame = ctk.CTkFrame(mode_content, fg_color="transparent")
        mode_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(
            mode_frame,
            text="Mode:",
            font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
            text_color=self.COLORS['text_dim']
        ).pack(side="left", padx=(0, 8))
        
        widgets['color_mode_dropdown'] = SmartOptionMenu(
            mode_frame,
            values=self._color_mode_names,
            width=200,
            height=36,
            font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
            fg_color=self.COLORS['bg_secondary'],
            button_color=self.COLORS['accent'],
            button_hover_color=self.COLORS['accent_hover'],
            dropdown_fg_color=self.COLORS['bg_secondary'],
            dropdown_hover_color=self.COLORS['border'],
            command=lambda v, d=display_num: self._on_color_mode_for_tab(v, d)
        )
        widgets['color_mode_dropdown'].pack(side="left", fill="x", expand=True)
        
        # Edit color mode names button - clearer "Edit" text
        widgets['edit_color_names_btn'] = ctk.CTkButton(
            mode_frame,
            text="Edit",
            width=50,
            height=36,
            font=ctk.CTkFont(size=self.FONT_SIZES['button'], weight="bold"),
            fg_color=self.COLORS['accent'],
            hover_color=self.COLORS['accent_hover'],
            command=lambda d=display_num: self._show_edit_color_names_dialog(d)
        )
        widgets['edit_color_names_btn'].pack(side="left", padx=(8, 0))
        
        # Adaptive Settings section
        adaptive_content = self._create_section(scrollable, "Adaptive Settings", "⚡")
        widgets.update(self._create_adaptive_controls_for_tab(adaptive_content, display_num))
        
        # Profiles section
        profiles_content = self._create_section(scrollable, "Application Profiles", "📁")
        widgets['profiles_frame'] = profiles_content
        widgets['profile_widgets'] = {}
        
        # Current active app display
        app_frame = ctk.CTkFrame(profiles_content, fg_color=self.COLORS['bg'], corner_radius=4, border_width=0)
        app_frame.pack(fill="x", pady=(0, 6))
        
        ctk.CTkLabel(
            app_frame,
            text="Current App:",
            font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
            text_color=self.COLORS['text_dim']
        ).pack(side="left", padx=10, pady=8)
        
        widgets['current_app_label'] = ctk.CTkLabel(
            app_frame,
            text="Not detected",
            font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['text'],
            anchor="w"
        )
        widgets['current_app_label'].pack(side="left", fill="x", expand=True, padx=(0, 10), pady=8)
        
        widgets['current_app_class'] = ctk.CTkLabel(
            app_frame,
            text="",
            font=ctk.CTkFont(size=self.FONT_SIZES['small']),
            text_color=self.COLORS['text_dim'],
            anchor="e"
        )
        widgets['current_app_class'].pack(side="right", padx=10, pady=8)
        
        # Profile list
        self._create_profile_list_for_tab(profiles_content, widgets['profile_widgets'], display_num)
        
        return widgets
    
    def _create_overview_tab(self, parent: ctk.CTkFrame, monitors: List[tuple]):
        """Create the Overview tab with graphical monitor layout and real-time stats."""
        self._overview_widgets = {}
        self._overview_monitors = monitors
        
        # Configure parent to expand
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        
        # Single scrollable area for everything (like monitor tabs)
        scrollable = ctk.CTkScrollableFrame(
            parent,
            fg_color="transparent",
            scrollbar_button_color=self.COLORS['bg_secondary'],
            scrollbar_button_hover_color=self.COLORS['accent'],
        )
        scrollable.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        
        # Store reference for scrollbar fix
        self._overview_details_frame = scrollable
        
        # Hide scrollbar initially - it will be shown if needed after content is created
        try:
            if hasattr(scrollable, '_scrollbar'):
                scrollable._scrollbar.grid_remove()
        except Exception:
            pass
        
        # Enable mouse wheel scrolling and auto-hide scrollbar
        self._bind_mousewheel(scrollable)
        
        # Monitor Layout section (collapsible)
        layout_content = self._create_section(scrollable, "Monitor Layout", "")
        
        # Canvas for visual monitor representation
        self._layout_canvas = tk.Canvas(
            layout_content, 
            bg=self.COLORS['bg'],
            highlightthickness=0,
            height=250
        )
        self._layout_canvas.pack(fill="both", expand=True, pady=(0, 4))
        
        # Bind resize event to redraw
        self._layout_canvas.bind('<Configure>', lambda e: self._draw_monitor_layout())
        
        # Click to select monitor and show highlight
        self._layout_canvas.bind('<Button-1>', self._on_monitor_layout_click)
        
        # Store monitor rectangles for later updates and click detection
        self._monitor_rects = {}
        self._monitor_labels = {}
        self._monitor_layout_bounds = {}  # display_num -> (x1, y1, x2, y2) for click detection
        self._selection_highlight_id = None  # Canvas item ID for selection highlight
        self._selection_hide_timer = None  # Timer ID for auto-hide
        
        # Create a collapsible section for each monitor
        for display_num, display_name in monitors:
            self._create_monitor_card_collapsible(scrollable, display_num, display_name)
        
        # Additional delayed scrollbar check after all content is created
        if self._root:
            self._root.after(100, self._trigger_all_scrollbar_checks)
            self._root.after(500, self._trigger_all_scrollbar_checks)
    
    def _create_gauge(self, parent, label: str, color: str) -> dict:
        """Create a speedometer-style gauge widget.
        
        Returns dict with 'frame', 'canvas', 'value_label', 'arc_id' for updating.
        """
        gauge_size = 70
        
        # Container frame
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(side="left", padx=8, pady=5)
        
        # Canvas for the gauge arc
        canvas = tk.Canvas(
            frame, 
            width=gauge_size, 
            height=gauge_size // 2 + 15,
            bg=self.COLORS['bg_secondary'],
            highlightthickness=0
        )
        canvas.pack()
        
        cx, cy = gauge_size // 2, gauge_size // 2
        radius = gauge_size // 2 - 5
        arc_width = 8
        
        # Background arc (gray) - semicircle from 180° to 0°
        canvas.create_arc(
            cx - radius, cy - radius, cx + radius, cy + radius,
            start=0, extent=180,
            outline=self.COLORS['border'], width=arc_width, style='arc'
        )
        
        # Foreground arc (colored) - will be updated
        arc_id = canvas.create_arc(
            cx - radius, cy - radius, cx + radius, cy + radius,
            start=180, extent=0,  # Start at 0%
            outline=color, width=arc_width, style='arc'
        )
        
        # Value label below gauge
        value_label = ctk.CTkLabel(
            frame, text="--",
            font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=color
        )
        value_label.pack()
        
        # Label for gauge name
        name_label = ctk.CTkLabel(
            frame, text=label,
            font=ctk.CTkFont(size=self.FONT_SIZES['slider_label']),
            text_color=self.COLORS['text_dim']
        )
        name_label.pack()
        
        return {
            'frame': frame,
            'canvas': canvas,
            'value_label': value_label,
            'arc_id': arc_id,
            'color': color,
            'cx': cx, 'cy': cy, 'radius': radius
        }
    
    def _update_gauge(self, gauge: dict, value: float, is_percentage: bool = True):
        """Update a gauge to show a value (0-100 for percentage, 0-1 for ratio)."""
        if not gauge:
            return
        
        canvas = gauge['canvas']
        arc_id = gauge['arc_id']
        value_label = gauge['value_label']
        cx, cy, radius = gauge['cx'], gauge['cy'], gauge['radius']
        
        # Normalize value to 0-1
        if is_percentage:
            normalized = min(1.0, max(0.0, value / 100.0))
            display_text = f"{int(value)}%"
        else:
            normalized = min(1.0, max(0.0, value))
            display_text = f"{int(value * 100)}%"
        
        # Calculate arc extent (180° = full gauge)
        # Arc goes from left (180°) to right (0°), so we use negative extent
        extent = -normalized * 180
        
        # Update arc
        canvas.itemconfig(arc_id, extent=extent)
        
        # Update value label
        value_label.configure(text=display_text)
    
    def _create_monitor_card(self, parent, display_num: int, display_name: str):
        """Create a monitor info card for the overview - compact vertical layout."""
        # Monitor card frame - minimal padding, flat look
        card = ctk.CTkFrame(parent, fg_color=self.COLORS['bg_secondary'], corner_radius=4, border_width=0)
        card.pack(fill="x", pady=(0, 4), padx=0)
        
        # Store widgets for this monitor
        monitor_widgets = {}
        
        # Header with monitor name
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=6, pady=(4, 2))
        
        ctk.CTkLabel(
            header,
            text=display_name,
            font=ctk.CTkFont(size=self.FONT_SIZES['title'], weight="bold"),
            text_color=self.COLORS['accent']
        ).pack(side="left")
        
        # Gauges below monitor name (original size)
        gauges_frame = ctk.CTkFrame(card, fg_color="transparent")
        gauges_frame.pack(fill="x", padx=6, pady=2)
        
        monitor_widgets['gauge_mean'] = self._create_gauge(gauges_frame, "Mean", self.COLORS['accent'])
        monitor_widgets['gauge_dark'] = self._create_gauge(gauges_frame, "Dark", "#4488FF")
        monitor_widgets['gauge_bright'] = self._create_gauge(gauges_frame, "Bright", "#FFCC00")
        
        # Content frame
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="x", padx=6, pady=(0, 4))
        
        # Resolution row
        row1 = ctk.CTkFrame(content, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        ctk.CTkLabel(row1, text="Resolution:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']), 
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['resolution'] = ctk.CTkLabel(
            row1, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['text'], anchor="w"
        )
        monitor_widgets['resolution'].pack(side="left")
        
        # Position row
        row2 = ctk.CTkFrame(content, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        ctk.CTkLabel(row2, text="Position:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['position'] = ctk.CTkLabel(
            row2, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['text'], anchor="w"
        )
        monitor_widgets['position'].pack(side="left")
        
        # Orientation (hidden by default - rarely changes)
        monitor_widgets['orientation'] = ctk.CTkLabel(content, text="Normal")
        
        # Separator
        sep = ctk.CTkFrame(content, fg_color=self.COLORS['border'], height=1)
        sep.pack(fill="x", pady=6)
        
        # Brightness row
        row3 = ctk.CTkFrame(content, fg_color="transparent")
        row3.pack(fill="x", pady=2)
        ctk.CTkLabel(row3, text="Brightness:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['brightness'] = ctk.CTkLabel(
            row3, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], width=50, anchor="w"
        )
        monitor_widgets['brightness'].pack(side="left")
        
        # Contrast row
        row4 = ctk.CTkFrame(content, fg_color="transparent")
        row4.pack(fill="x", pady=2)
        ctk.CTkLabel(row4, text="Contrast:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['contrast'] = ctk.CTkLabel(
            row4, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], width=50, anchor="w"
        )
        monitor_widgets['contrast'].pack(side="left")
        
        # Sharpness row
        row5 = ctk.CTkFrame(content, fg_color="transparent")
        row5.pack(fill="x", pady=2)
        ctk.CTkLabel(row5, text="Sharpness:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['sharpness'] = ctk.CTkLabel(
            row5, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], width=50, anchor="w"
        )
        monitor_widgets['sharpness'].pack(side="left")
        
        # App row
        row6 = ctk.CTkFrame(content, fg_color="transparent")
        row6.pack(fill="x", pady=2)
        ctk.CTkLabel(row6, text="App:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['current_app'] = ctk.CTkLabel(
            row6, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
            text_color=self.COLORS['text'], anchor="w"
        )
        monitor_widgets['current_app'].pack(side="left", fill="x", expand=True)
        
        # Profile row
        row7 = ctk.CTkFrame(content, fg_color="transparent")
        row7.pack(fill="x", pady=2)
        ctk.CTkLabel(row7, text="Profile:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['current_profile'] = ctk.CTkLabel(
            row7, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], anchor="w"
        )
        monitor_widgets['current_profile'].pack(side="left")
        
        # DDC row
        row8 = ctk.CTkFrame(content, fg_color="transparent")
        row8.pack(fill="x", pady=2)
        ctk.CTkLabel(row8, text="DDC:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        indicator_canvas = tk.Canvas(row8, width=12, height=12, 
                                      bg=self.COLORS['bg_secondary'], highlightthickness=0)
        indicator_canvas.pack(side="left", padx=(0, 5))
        indicator_canvas.create_oval(2, 2, 10, 10, fill="#44AA44", outline="", tags="dot")
        monitor_widgets['ddc_indicator'] = indicator_canvas
        monitor_widgets['ddc_status'] = ctk.CTkLabel(
            row8, text="Idle", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
            text_color="#44AA44", anchor="w"
        )
        monitor_widgets['ddc_status'].pack(side="left")
        
        # Auto buttons row (no label, just buttons)
        auto_row = ctk.CTkFrame(content, fg_color="transparent")
        auto_row.pack(fill="x", pady=(4, 2))
        
        auto_bright_btn = ctk.CTkButton(
            auto_row, text="☀", width=32, height=24,
            font=ctk.CTkFont(size=self.FONT_SIZES['small']),
            fg_color=self.COLORS['bg_tertiary'],
            hover_color=self.COLORS['accent'],
            command=lambda d=display_num: self._on_overview_auto_brightness_toggle(d)
        )
        auto_bright_btn.pack(side="left", padx=(0, 3))
        monitor_widgets['auto_brightness_btn'] = auto_bright_btn
        
        auto_contrast_btn = ctk.CTkButton(
            auto_row, text="◐", width=32, height=24,
            font=ctk.CTkFont(size=self.FONT_SIZES['small']),
            fg_color=self.COLORS['bg_tertiary'],
            hover_color=self.COLORS['accent'],
            command=lambda d=display_num: self._on_overview_auto_contrast_toggle(d)
        )
        auto_contrast_btn.pack(side="left", padx=(0, 3))
        monitor_widgets['auto_contrast_btn'] = auto_contrast_btn
        
        auto_profile_btn = ctk.CTkButton(
            auto_row, text="📋", width=32, height=24,
            font=ctk.CTkFont(size=self.FONT_SIZES['small']),
            fg_color=self.COLORS['bg_tertiary'],
            hover_color=self.COLORS['accent'],
            command=lambda d=display_num: self._on_overview_auto_profile_toggle(d)
        )
        auto_profile_btn.pack(side="left")
        monitor_widgets['auto_profile_btn'] = auto_profile_btn
        
        # Store widgets
        self._overview_widgets[display_num] = monitor_widgets
    
    def _create_monitor_card_collapsible(self, parent, display_num: int, display_name: str):
        """Create a collapsible monitor section for the overview tab."""
        # Create collapsible section for this monitor
        content = self._create_section(parent, display_name, "")
        
        # Store widgets for this monitor
        monitor_widgets = {}
        
        # Gauges row
        gauges_frame = ctk.CTkFrame(content, fg_color="transparent")
        gauges_frame.pack(fill="x", pady=(0, 4))
        
        monitor_widgets['gauge_mean'] = self._create_gauge(gauges_frame, "Mean", self.COLORS['accent'])
        monitor_widgets['gauge_dark'] = self._create_gauge(gauges_frame, "Dark", "#4488FF")
        monitor_widgets['gauge_bright'] = self._create_gauge(gauges_frame, "Bright", "#FFCC00")
        
        # Info rows
        info_frame = ctk.CTkFrame(content, fg_color="transparent")
        info_frame.pack(fill="x")
        
        # Resolution row
        row1 = ctk.CTkFrame(info_frame, fg_color="transparent")
        row1.pack(fill="x", pady=1)
        ctk.CTkLabel(row1, text="Resolution:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']), 
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['resolution'] = ctk.CTkLabel(
            row1, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['text'], anchor="w"
        )
        monitor_widgets['resolution'].pack(side="left")
        
        # Position row
        row2 = ctk.CTkFrame(info_frame, fg_color="transparent")
        row2.pack(fill="x", pady=1)
        ctk.CTkLabel(row2, text="Position:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['position'] = ctk.CTkLabel(
            row2, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['text'], anchor="w"
        )
        monitor_widgets['position'].pack(side="left")
        
        # Hidden orientation
        monitor_widgets['orientation'] = ctk.CTkLabel(info_frame, text="Normal")
        
        # Separator
        sep = ctk.CTkFrame(info_frame, fg_color=self.COLORS['border'], height=1)
        sep.pack(fill="x", pady=4)
        
        # Brightness row
        row3 = ctk.CTkFrame(info_frame, fg_color="transparent")
        row3.pack(fill="x", pady=1)
        ctk.CTkLabel(row3, text="Brightness:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['brightness'] = ctk.CTkLabel(
            row3, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], width=50, anchor="w"
        )
        monitor_widgets['brightness'].pack(side="left")
        
        # Contrast row
        row4 = ctk.CTkFrame(info_frame, fg_color="transparent")
        row4.pack(fill="x", pady=1)
        ctk.CTkLabel(row4, text="Contrast:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['contrast'] = ctk.CTkLabel(
            row4, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], width=50, anchor="w"
        )
        monitor_widgets['contrast'].pack(side="left")
        
        # Sharpness row
        row5 = ctk.CTkFrame(info_frame, fg_color="transparent")
        row5.pack(fill="x", pady=1)
        ctk.CTkLabel(row5, text="Sharpness:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['sharpness'] = ctk.CTkLabel(
            row5, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], width=50, anchor="w"
        )
        monitor_widgets['sharpness'].pack(side="left")
        
        # App row
        row6 = ctk.CTkFrame(info_frame, fg_color="transparent")
        row6.pack(fill="x", pady=1)
        ctk.CTkLabel(row6, text="App:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['current_app'] = ctk.CTkLabel(
            row6, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
            text_color=self.COLORS['text'], anchor="w"
        )
        monitor_widgets['current_app'].pack(side="left", fill="x", expand=True)
        
        # Profile row
        row7 = ctk.CTkFrame(info_frame, fg_color="transparent")
        row7.pack(fill="x", pady=1)
        ctk.CTkLabel(row7, text="Profile:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        monitor_widgets['current_profile'] = ctk.CTkLabel(
            row7, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], anchor="w"
        )
        monitor_widgets['current_profile'].pack(side="left")
        
        # DDC row
        row8 = ctk.CTkFrame(info_frame, fg_color="transparent")
        row8.pack(fill="x", pady=1)
        ctk.CTkLabel(row8, text="DDC:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="w").pack(side="left")
        indicator_canvas = tk.Canvas(row8, width=12, height=12, 
                                      bg=self.COLORS['bg_secondary'], highlightthickness=0)
        indicator_canvas.pack(side="left", padx=(0, 5))
        indicator_canvas.create_oval(2, 2, 10, 10, fill="#44AA44", outline="", tags="dot")
        monitor_widgets['ddc_indicator'] = indicator_canvas
        monitor_widgets['ddc_status'] = ctk.CTkLabel(
            row8, text="Idle", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
            text_color="#44AA44", anchor="w"
        )
        monitor_widgets['ddc_status'].pack(side="left")
        
        # Auto row with label and vertical buttons inline
        auto_row = ctk.CTkFrame(info_frame, fg_color="transparent")
        auto_row.pack(fill="x", pady=(4, 0))
        
        # Auto label on left
        ctk.CTkLabel(auto_row, text="Auto:", font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=80, anchor="nw").pack(side="left", anchor="n")
        
        # Vertical buttons frame on right
        auto_btns = ctk.CTkFrame(auto_row, fg_color="transparent")
        auto_btns.pack(side="left", anchor="n")
        
        auto_bright_btn = ctk.CTkButton(
            auto_btns, text="☀ Brightness", width=100, height=24,
            font=ctk.CTkFont(size=self.FONT_SIZES['button']),
            fg_color=self.COLORS['bg_tertiary'],
            hover_color=self.COLORS['accent'],
            command=lambda d=display_num: self._on_overview_auto_brightness_toggle(d)
        )
        auto_bright_btn.pack(anchor="w", pady=(0, 2))
        monitor_widgets['auto_brightness_btn'] = auto_bright_btn
        
        auto_contrast_btn = ctk.CTkButton(
            auto_btns, text="◐ Contrast", width=100, height=24,
            font=ctk.CTkFont(size=self.FONT_SIZES['button']),
            fg_color=self.COLORS['bg_tertiary'],
            hover_color=self.COLORS['accent'],
            command=lambda d=display_num: self._on_overview_auto_contrast_toggle(d)
        )
        auto_contrast_btn.pack(anchor="w", pady=(0, 2))
        monitor_widgets['auto_contrast_btn'] = auto_contrast_btn
        
        auto_profile_btn = ctk.CTkButton(
            auto_btns, text="📋 Profile", width=100, height=24,
            font=ctk.CTkFont(size=self.FONT_SIZES['button']),
            fg_color=self.COLORS['bg_tertiary'],
            hover_color=self.COLORS['accent'],
            command=lambda d=display_num: self._on_overview_auto_profile_toggle(d)
        )
        auto_profile_btn.pack(anchor="w")
        monitor_widgets['auto_profile_btn'] = auto_profile_btn
        
        # Store widgets
        self._overview_widgets[display_num] = monitor_widgets
    
    def _create_gauge_mini(self, parent, label: str, color: str) -> dict:
        """Create a mini gauge for compact display."""
        gauge_size = 40
        
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(side="left", padx=3)
        
        canvas = tk.Canvas(frame, width=gauge_size, height=gauge_size // 2 + 8,
                          bg=self.COLORS['bg_secondary'], highlightthickness=0)
        canvas.pack()
        
        cx, cy = gauge_size // 2, gauge_size // 2
        radius = gauge_size // 2 - 3
        arc_width = 4
        
        canvas.create_arc(cx - radius, cy - radius, cx + radius, cy + radius,
                         start=0, extent=180, outline=self.COLORS['border'], width=arc_width, style='arc')
        
        arc_id = canvas.create_arc(cx - radius, cy - radius, cx + radius, cy + radius,
                                   start=180, extent=0, outline=color, width=arc_width, style='arc')
        
        value_label = ctk.CTkLabel(frame, text="--", font=ctk.CTkFont(size=self.FONT_SIZES['small']-1),
                                   text_color=color)
        value_label.pack()
        
        return {'frame': frame, 'canvas': canvas, 'value_label': value_label, 'arc_id': arc_id,
                'color': color, 'cx': cx, 'cy': cy, 'radius': radius}
    
    def update_overview_monitor_info(self, display_num: int, resolution: str = None, 
                                      position: str = None, orientation: str = None,
                                      x: int = None, y: int = None, width: int = None, height: int = None,
                                      native_width: int = None, native_height: int = None, scale: int = None):
        """Update monitor geometry info in overview and redraw visual layout."""
        if display_num not in self._overview_widgets:
            return
        widgets = self._overview_widgets[display_num]
        
        # Store geometry for graphical display
        if width and height:
            self._monitor_geometries[display_num] = {
                'x': x or 0, 'y': y or 0, 
                'width': width, 'height': height,
                'native_width': native_width or width,
                'native_height': native_height or height,
                'scale': scale or 100,
                'resolution': resolution, 'name': None
            }
            # Get monitor name
            for disp, name in getattr(self, '_overview_monitors', []):
                if disp == display_num:
                    self._monitor_geometries[display_num]['name'] = name
                    break
        
        def update():
            if resolution and 'resolution' in widgets:
                widgets['resolution'].configure(text=resolution)
            if position and 'position' in widgets:
                widgets['position'].configure(text=position)
            if orientation and 'orientation' in widgets:
                widgets['orientation'].configure(text=orientation)
            if scale and 'scale' in widgets:
                widgets['scale'].configure(text=f"{scale}%")
            # Redraw visual layout
            self._draw_monitor_layout()
        
        if self._root:
            self._root.after(0, update)
    
    def _draw_monitor_layout(self):
        """Draw visual representation of monitor layout on canvas."""
        if not hasattr(self, '_layout_canvas') or not self._layout_canvas:
            return
        if not self._monitor_geometries:
            return
        
        canvas = self._layout_canvas
        canvas.delete("all")
        
        # Clear bounds and selection
        self._monitor_layout_bounds = {}
        self._selection_highlight_id = None
        
        # Get canvas dimensions
        canvas.update_idletasks()
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        
        if canvas_width < 50 or canvas_height < 50:
            canvas_width = 600
            canvas_height = 250
        
        # Calculate bounding box of all monitors (using framebuffer dimensions for layout)
        all_geoms = list(self._monitor_geometries.values())
        if not all_geoms:
            return
        
        min_x = min(g['x'] for g in all_geoms)
        min_y = min(g['y'] for g in all_geoms)
        max_x = max(g['x'] + g['width'] for g in all_geoms)
        max_y = max(g['y'] + g['height'] for g in all_geoms)
        
        total_width = max_x - min_x
        total_height = max_y - min_y
        
        if total_width == 0 or total_height == 0:
            return
        
        # Calculate scale to fit in canvas with padding
        padding = 20
        scale_x = (canvas_width - 2 * padding) / total_width
        scale_y = (canvas_height - 2 * padding) / total_height
        scale = min(scale_x, scale_y)
        
        # Center offset
        scaled_width = total_width * scale
        scaled_height = total_height * scale
        offset_x = (canvas_width - scaled_width) / 2
        offset_y = (canvas_height - scaled_height) / 2
        
        # Draw each monitor - use vivid, saturated colors
        colors = ['#ff6b00', '#00d4ff', '#00ff88', '#ff4466', '#aa66ff']
        for i, (display_num, geom) in enumerate(sorted(self._monitor_geometries.items())):
            # Calculate position on canvas
            x1 = offset_x + (geom['x'] - min_x) * scale
            y1 = offset_y + (geom['y'] - min_y) * scale
            x2 = x1 + geom['width'] * scale
            y2 = y1 + geom['height'] * scale
            
            color = colors[i % len(colors)]
            rect_width = x2 - x1
            rect_height = y2 - y1
            
            # Draw monitor bezel (outer rectangle)
            bezel = 4
            canvas.create_rectangle(
                x1 - bezel, y1 - bezel, x2 + bezel, y2 + bezel,
                fill='#2d2d2d',
                outline='#444444',
                width=2
            )
            
            # Draw screen area (inner rectangle)
            canvas.create_rectangle(
                x1, y1, x2, y2,
                fill=self.COLORS['bg'],
                outline=color,
                width=3,
                tags=f"monitor_{display_num}"
            )
            
            # Store bounds for click detection (including bezel)
            self._monitor_layout_bounds[display_num] = (x1 - bezel, y1 - bezel, x2 + bezel, y2 + bezel + 10, color)
            
            # Draw monitor stand
            stand_width = min(40, rect_width * 0.3)
            stand_height = 8
            stand_x = (x1 + x2) / 2 - stand_width / 2
            canvas.create_rectangle(
                stand_x, y2 + bezel, stand_x + stand_width, y2 + bezel + stand_height,
                fill='#2d2d2d', outline='#444444'
            )
            
            # Calculate font sizes based on rectangle size
            title_size = max(11, min(14, int(rect_height / 10)))
            info_size = max(10, min(12, int(rect_height / 12)))
            
            # Draw monitor label - center
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2
            
            # Get monitor name from overview_monitors
            monitor_name = f"Display {display_num}"
            for disp, name in getattr(self, '_overview_monitors', []):
                if disp == display_num:
                    # Extract just the model name (remove "Display X" part if present)
                    if "(Display" in name:
                        monitor_name = name.split(" (Display")[0]
                    else:
                        monitor_name = name
                    break
            
            # Monitor name (bold, colored)
            canvas.create_text(
                center_x, center_y - rect_height * 0.15,
                text=monitor_name,
                fill=color,
                font=("Segoe UI", title_size, "bold")
            )
            
            # Native resolution (main info)
            native_w = geom.get('native_width', geom['width'])
            native_h = geom.get('native_height', geom['height'])
            res_text = f"{native_w}×{native_h}"
            canvas.create_text(
                center_x, center_y + rect_height * 0.05,
                text=res_text,
                fill=self.COLORS['text'],
                font=("Segoe UI", info_size, "bold")
            )
            
            # Scale percentage (if not 100%)
            scale_pct = geom.get('scale', 100)
            if scale_pct != 100:
                canvas.create_text(
                    center_x, center_y + rect_height * 0.22,
                    text=f"@ {scale_pct}%",
                    fill=self.COLORS['text_dim'],
                    font=("Segoe UI", info_size - 1)
                )
    
    def _on_monitor_layout_click(self, event):
        """Handle click on monitor layout canvas - show border overlay on actual monitor."""
        if not hasattr(self, '_monitor_layout_bounds'):
            return
        
        x, y = event.x, event.y
        
        # Find which monitor was clicked
        for display_num, bounds in self._monitor_layout_bounds.items():
            x1, y1, x2, y2, color = bounds
            if x1 <= x <= x2 and y1 <= y <= y2:
                # Get the actual monitor geometry
                geom = self._monitor_geometries.get(display_num)
                if geom:
                    self._show_monitor_overlay_border(display_num, geom, color)
                return
    
    def _show_monitor_overlay_border(self, display_num: int, geom: dict, color: str):
        """Show a border overlay on the actual physical monitor."""
        # Cancel existing timer
        if hasattr(self, '_selection_hide_timer') and self._selection_hide_timer:
            self._root.after_cancel(self._selection_hide_timer)
            self._selection_hide_timer = None
        
        # Close existing overlay
        self._hide_monitor_selection()
        
        # Get monitor position and size
        mon_x = geom.get('x', 0)
        mon_y = geom.get('y', 0)
        mon_width = geom.get('width', 1920)
        mon_height = geom.get('height', 1080)
        
        # Create transparent overlay window
        overlay = tk.Toplevel(self._root)
        overlay.overrideredirect(True)  # No window decorations
        overlay.attributes('-topmost', True)  # Always on top
        
        # Try to make it transparent and click-through
        try:
            overlay.attributes('-alpha', 0.9)
            # Make window click-through on Linux
            overlay.attributes('-type', 'dock')
        except:
            pass
        
        # Position and size to cover the monitor
        border_width = 8
        overlay.geometry(f"{mon_width}x{mon_height}+{mon_x}+{mon_y}")
        
        # Create canvas for drawing the border
        canvas = tk.Canvas(
            overlay,
            width=mon_width,
            height=mon_height,
            bg='black',
            highlightthickness=0
        )
        canvas.pack(fill='both', expand=True)
        
        # Make the center transparent (only show border)
        # Draw colored border rectangles on each edge
        canvas.create_rectangle(0, 0, mon_width, border_width, fill=color, outline='')  # Top
        canvas.create_rectangle(0, mon_height - border_width, mon_width, mon_height, fill=color, outline='')  # Bottom
        canvas.create_rectangle(0, 0, border_width, mon_height, fill=color, outline='')  # Left
        canvas.create_rectangle(mon_width - border_width, 0, mon_width, mon_height, fill=color, outline='')  # Right
        
        # Make center area transparent by creating a "hole"
        # Use a transparent color for the center
        canvas.create_rectangle(
            border_width, border_width,
            mon_width - border_width, mon_height - border_width,
            fill='', outline=''
        )
        
        # Set the transparent color
        try:
            overlay.wm_attributes('-transparentcolor', 'black')
        except:
            # Fallback: just use low alpha
            try:
                overlay.attributes('-alpha', 0.7)
            except:
                pass
        
        # Store reference
        self._monitor_overlay = overlay
        
        # Auto-hide after 3 seconds
        self._selection_hide_timer = self._root.after(3000, self._hide_monitor_selection)
    
    def _hide_monitor_selection(self):
        """Hide the monitor overlay border."""
        # Close overlay window
        if hasattr(self, '_monitor_overlay') and self._monitor_overlay:
            try:
                self._monitor_overlay.destroy()
            except:
                pass
            self._monitor_overlay = None
        
        self._selection_hide_timer = None
    
    def update_overview_settings(self, display_num: int, brightness: int = None, contrast: int = None, sharpness: int = None):
        """Update brightness/contrast/sharpness in overview."""
        if display_num not in self._overview_widgets:
            return
        widgets = self._overview_widgets[display_num]
        
        def update():
            if brightness is not None and 'brightness' in widgets:
                widgets['brightness'].configure(text=str(brightness))
            if contrast is not None and 'contrast' in widgets:
                widgets['contrast'].configure(text=str(contrast))
            if sharpness is not None and 'sharpness' in widgets:
                widgets['sharpness'].configure(text=str(sharpness))
        
        if self._root:
            self._root.after(0, update)
    
    def update_overview_screen_analysis(self, display_num: int, mean: float, dark_pct: float, bright_pct: float):
        """Update screen analysis values in overview and monitor tab using speedometer gauges."""
        def update():
            # Update overview gauges
            if display_num in self._overview_widgets:
                widgets = self._overview_widgets[display_num]
                if 'gauge_mean' in widgets:
                    self._update_gauge(widgets['gauge_mean'], mean, is_percentage=False)
                if 'gauge_dark' in widgets:
                    self._update_gauge(widgets['gauge_dark'], dark_pct * 100, is_percentage=True)
                if 'gauge_bright' in widgets:
                    self._update_gauge(widgets['gauge_bright'], bright_pct * 100, is_percentage=True)
            
            # Update monitor tab gauges
            if display_num in self._monitor_widgets:
                tab_widgets = self._monitor_widgets[display_num]
                if 'gauge_mean' in tab_widgets:
                    self._update_gauge(tab_widgets['gauge_mean'], mean, is_percentage=False)
                if 'gauge_dark' in tab_widgets:
                    self._update_gauge(tab_widgets['gauge_dark'], dark_pct * 100, is_percentage=True)
                if 'gauge_bright' in tab_widgets:
                    self._update_gauge(tab_widgets['gauge_bright'], bright_pct * 100, is_percentage=True)
        
        if self._root:
            self._root.after(0, update)
    
    def update_overview_current_app(self, display_num: int, app_name: str, app_class: str = None):
        """Update current app in overview."""
        if display_num not in self._overview_widgets:
            return
        widgets = self._overview_widgets[display_num]
        
        def update():
            if 'current_app' in widgets:
                text = app_name or "--"
                if app_class:
                    text = f"{text} ({app_class})"
                widgets['current_app'].configure(text=text)
        
        if self._root:
            self._root.after(0, update)
    
    def update_overview_profile(self, display_num: int, profile_name: str):
        """Update current profile in overview."""
        if display_num not in self._overview_widgets:
            return
        widgets = self._overview_widgets[display_num]
        
        def update():
            if 'current_profile' in widgets:
                text = profile_name.capitalize() if profile_name else "--"
                widgets['current_profile'].configure(text=text)
        
        if self._root:
            self._root.after(0, update)
    
    def set_ddc_busy(self, display_num: int, busy: bool, command: str = None):
        """Update DDC busy status in overview and monitor tab for a specific monitor.
        
        Args:
            display_num: Monitor display number
            busy: True if DDC command is in progress, False when idle
            command: Optional command description (e.g., "Reading brightness...")
        """
        def update():
            if busy:
                # Busy state - orange/yellow color with pulsing dot
                color = "#FFAA00"
                text = command if command else "Working..."
            else:
                # Idle state - green color
                color = "#44AA44"
                text = "Idle"
            
            # Update overview tab
            if display_num in self._overview_widgets:
                overview_widgets = self._overview_widgets[display_num]
                if 'ddc_status' in overview_widgets and 'ddc_indicator' in overview_widgets:
                    overview_widgets['ddc_status'].configure(text=text, text_color=color)
                    canvas = overview_widgets['ddc_indicator']
                    canvas.delete("dot")
                    canvas.create_oval(2, 2, 10, 10, fill=color, outline="", tags="dot")
            
            # Update monitor tab
            if display_num in self._monitor_widgets:
                tab_widgets = self._monitor_widgets[display_num]
                if 'ddc_status' in tab_widgets and 'ddc_indicator' in tab_widgets:
                    tab_widgets['ddc_status'].configure(text=text, text_color=color)
                    canvas = tab_widgets['ddc_indicator']
                    canvas.delete("dot")
                    canvas.create_oval(2, 2, 10, 10, fill=color, outline="", tags="dot")
        
        if self._root:
            self._root.after(0, update)
    
    def _on_overview_auto_brightness_toggle(self, display_num: int):
        """Handle auto brightness toggle from overview."""
        # Get current state from the button color
        widgets = self._overview_widgets.get(display_num, {})
        btn = widgets.get('auto_brightness_btn')
        if not btn:
            return
        
        # Toggle state based on current color
        is_on = btn.cget('fg_color') == self.COLORS['accent']
        new_state = not is_on
        
        # Update button appearance
        self._update_overview_auto_button(display_num, 'auto_brightness_btn', new_state)
        
        # Invoke the callback (use same name as tab buttons)
        self._invoke_callback('toggle_auto_brightness', new_state, display_num)
    
    def _on_overview_auto_contrast_toggle(self, display_num: int):
        """Handle auto contrast toggle from overview."""
        widgets = self._overview_widgets.get(display_num, {})
        btn = widgets.get('auto_contrast_btn')
        if not btn:
            return
        
        is_on = btn.cget('fg_color') == self.COLORS['accent']
        new_state = not is_on
        
        self._update_overview_auto_button(display_num, 'auto_contrast_btn', new_state)
        self._invoke_callback('toggle_auto_contrast', new_state, display_num)
    
    def _on_overview_auto_profile_toggle(self, display_num: int):
        """Handle auto profile toggle from overview."""
        widgets = self._overview_widgets.get(display_num, {})
        btn = widgets.get('auto_profile_btn')
        if not btn:
            return
        
        is_on = btn.cget('fg_color') == self.COLORS['accent']
        new_state = not is_on
        
        self._update_overview_auto_button(display_num, 'auto_profile_btn', new_state)
        self._invoke_callback('toggle_auto_profile', new_state, display_num)
    
    def _update_overview_auto_button(self, display_num: int, btn_key: str, is_on: bool):
        """Update an auto button appearance in overview."""
        widgets = self._overview_widgets.get(display_num, {})
        btn = widgets.get(btn_key)
        if not btn:
            return
        
        def update():
            if is_on:
                btn.configure(fg_color=self.COLORS['accent'])
            else:
                btn.configure(fg_color=self.COLORS['bg_tertiary'])
        
        if self._root:
            self._root.after(0, update)
    
    def update_overview_auto_states(self, display_num: int, auto_brightness: bool = None, 
                                     auto_contrast: bool = None, auto_profile: bool = None):
        """Update auto mode button states in overview for a specific monitor."""
        if display_num not in self._overview_widgets:
            return
        
        if auto_brightness is not None:
            self._update_overview_auto_button(display_num, 'auto_brightness_btn', auto_brightness)
        if auto_contrast is not None:
            self._update_overview_auto_button(display_num, 'auto_contrast_btn', auto_contrast)
        if auto_profile is not None:
            self._update_overview_auto_button(display_num, 'auto_profile_btn', auto_profile)
    
    def _create_slider_for_tab(self, parent, label: str, icon: str, callback: Callable) -> tuple:
        """Create a slider for a tab. Returns (slider, value_label)."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=10)
        
        ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=self.FONT_SIZES['icon_large']), width=36).pack(side="left")
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=self.FONT_SIZES['title']), width=120, anchor="w").pack(side="left", padx=(5, 10))
        
        value_label = ctk.CTkLabel(
            row, text="50", font=ctk.CTkFont(size=self.FONT_SIZES['title']+2, weight="bold"),
            text_color=self.COLORS['accent'], width=55
        )
        value_label.pack(side="right")
        
        slider = ctk.CTkSlider(
            row, from_=0, to=100, number_of_steps=100,
            progress_color=self.COLORS['accent'],
            button_color=self.COLORS['accent'],
            button_hover_color=self.COLORS['accent_hover'],
            command=lambda v: self._slider_callback(v, value_label, callback)
        )
        slider.set(50)
        slider.pack(side="left", fill="x", expand=True, padx=10)
        
        return slider, value_label
    
    def _create_colored_slider_for_tab(self, parent, label: str, color: str, callback: Callable) -> tuple:
        """Create a slider with a colored circle indicator (for RGB sliders)."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=10)
        
        # Use a colored bullet character instead of emoji
        ctk.CTkLabel(row, text="●", font=ctk.CTkFont(size=self.FONT_SIZES['icon_large']+4), text_color=color, width=36).pack(side="left")
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=self.FONT_SIZES['title']), width=120, anchor="w").pack(side="left", padx=(5, 10))
        
        value_label = ctk.CTkLabel(
            row, text="50", font=ctk.CTkFont(size=self.FONT_SIZES['title']+2, weight="bold"),
            text_color=self.COLORS['accent'], width=55
        )
        value_label.pack(side="right")
        
        slider = ctk.CTkSlider(
            row, from_=0, to=100, number_of_steps=100,
            progress_color=self.COLORS['accent'],
            button_color=self.COLORS['accent'],
            button_hover_color=self.COLORS['accent_hover'],
            command=lambda v: self._slider_callback(v, value_label, callback)
        )
        slider.set(50)
        slider.pack(side="left", fill="x", expand=True, padx=10)
        
        return slider, value_label
    
    def _slider_callback(self, value, label, callback):
        """Handle slider change - update label and call callback."""
        int_value = int(value)
        label.configure(text=str(int_value))
        # Skip callback if slider is being set programmatically (to prevent feedback loops)
        if not self._updating_from_code:
            callback(int_value)
    
    def _debounced_invoke(self, callback_name: str, value: int, display_num: int):
        """Invoke callback with debouncing to prevent flooding DDC commands."""
        key = (callback_name, display_num)
        
        # Cancel existing timer for this callback
        if key in self._slider_debounce_timers:
            self._root.after_cancel(self._slider_debounce_timers[key])
        
        # Schedule new callback
        def invoke():
            if key in self._slider_debounce_timers:
                del self._slider_debounce_timers[key]
            self._invoke_callback(callback_name, value, display_num)
        
        self._slider_debounce_timers[key] = self._root.after(self._slider_debounce_delay, invoke)
    
    def _on_brightness_for_tab(self, value: int, display_num: int):
        """Handle brightness change for specific monitor."""
        self._debounced_invoke('brightness_change', value, display_num)
    
    def _on_contrast_for_tab(self, value: int, display_num: int):
        """Handle contrast change for specific monitor."""
        self._debounced_invoke('contrast_change', value, display_num)
    
    def _on_sharpness_for_tab(self, value: int, display_num: int):
        """Handle sharpness change for specific monitor."""
        self._debounced_invoke('sharpness_change', value, display_num)
    
    def _on_rgb_for_tab(self, channel: str, value: int, display_num: int):
        """Handle RGB change for specific monitor."""
        self._debounced_invoke(f'{channel}_gain_change', value, display_num)
    
    def _on_refresh_values(self, display_num: int):
        """Handle refresh button click for specific monitor (all values)."""
        self._invoke_callback('refresh_values', display_num)
    
    def _on_refresh_basic_values(self, display_num: int):
        """Handle refresh button click for basic controls (brightness/contrast/sharpness)."""
        self._invoke_callback('refresh_basic_values', display_num)
    
    def _on_refresh_rgb_values(self, display_num: int):
        """Handle refresh button click for RGB gain values."""
        self._invoke_callback('refresh_rgb_values', display_num)
    
    def _on_color_mode_for_tab(self, mode_name: str, display_num: int):
        """Handle color mode change for specific monitor."""
        # _all_color_modes is {name: vcp_value}, so direct lookup
        vcp_value = self._all_color_modes.get(mode_name)
        
        if vcp_value is not None:
            self._color_mode = vcp_value
            self._invoke_callback('mode_change', vcp_value, display_num)
    
    def _create_adaptive_controls_for_tab(self, parent, display_num: int) -> Dict:
        """Create adaptive brightness/contrast controls for a tab - vertical layout."""
        widgets = {}
        
        # Vertical toggle buttons - NOTE: d=display_num captures value, not reference
        widgets['auto_brightness_btn'] = ctk.CTkButton(
            parent, text="☀️ Auto Brightness: OFF", height=28,
            font=ctk.CTkFont(size=self.FONT_SIZES['button']), fg_color=self.COLORS['bg'],
            hover_color=self.COLORS['border'], corner_radius=6,
            command=lambda d=display_num: self._toggle_auto_brightness_for_tab(d)
        )
        widgets['auto_brightness_btn'].pack(fill="x", pady=(0, 4))
        
        widgets['auto_contrast_btn'] = ctk.CTkButton(
            parent, text="◐ Auto Contrast: OFF", height=28,
            font=ctk.CTkFont(size=self.FONT_SIZES['button']), fg_color=self.COLORS['bg'],
            hover_color=self.COLORS['border'], corner_radius=6,
            command=lambda d=display_num: self._toggle_auto_contrast_for_tab(d)
        )
        widgets['auto_contrast_btn'].pack(fill="x", pady=(0, 4))
        
        widgets['auto_profile_btn'] = ctk.CTkButton(
            parent, text="📁 Auto Profile Switch: OFF", height=28,
            font=ctk.CTkFont(size=self.FONT_SIZES['button']), fg_color=self.COLORS['bg'],
            hover_color=self.COLORS['border'], corner_radius=6,
            command=lambda d=display_num: self._toggle_auto_profile_for_tab(d)
        )
        widgets['auto_profile_btn'].pack(fill="x", pady=(0, 4))
        
        # Fullscreen only toggle below
        widgets['fullscreen_only_switch'] = ctk.CTkSwitch(
            parent, text="Fullscreen Only", height=24,
            font=ctk.CTkFont(size=self.FONT_SIZES['button']),
            fg_color=self.COLORS['bg'],
            progress_color=self.COLORS['accent'],
            button_color=self.COLORS['text'],
            button_hover_color=self.COLORS['accent'],
            command=lambda d=display_num: self._on_fullscreen_only_toggle(d)
        )
        widgets['fullscreen_only_switch'].pack(anchor="w", pady=(0, 8))
        
        # Separator
        sep = ctk.CTkFrame(parent, fg_color=self.COLORS['border'], height=1)
        sep.pack(fill="x", pady=8)
        
        # Sliders for min/max values with full labels
        widgets['min_brightness_slider'], widgets['min_brightness_label'] = self._create_slider_adaptive(
            parent, "Min Brightness", "⬇️", lambda v, d=display_num: self._on_adaptive_setting_for_tab('min_brightness', v, d)
        )
        widgets['max_brightness_slider'], widgets['max_brightness_label'] = self._create_slider_adaptive(
            parent, "Max Brightness", "⬆️", lambda v, d=display_num: self._on_adaptive_setting_for_tab('max_brightness', v, d)
        )
        widgets['min_contrast_slider'], widgets['min_contrast_label'] = self._create_slider_adaptive(
            parent, "Min Contrast", "⬇️", lambda v, d=display_num: self._on_adaptive_setting_for_tab('min_contrast', v, d)
        )
        widgets['max_contrast_slider'], widgets['max_contrast_label'] = self._create_slider_adaptive(
            parent, "Max Contrast", "⬆️", lambda v, d=display_num: self._on_adaptive_setting_for_tab('max_contrast', v, d)
        )
        
        # Interval slider - gnome-screenshot takes ~2s on Wayland
        is_wayland = (os.environ.get('XDG_SESSION_TYPE') == 'wayland' or 
                      os.environ.get('WAYLAND_DISPLAY') is not None)
        min_interval = 2.5 if is_wayland else 0.5
        max_interval = 10.0 if is_wayland else 3.0
        default_interval = 3.0 if is_wayland else 1.0
        
        interval_row = ctk.CTkFrame(parent, fg_color="transparent")
        interval_row.pack(fill="x", pady=5)
        ctk.CTkLabel(interval_row, text="⏱️", font=ctk.CTkFont(size=self.FONT_SIZES['icon']), width=30).pack(side="left")
        ctk.CTkLabel(interval_row, text="Interval", font=ctk.CTkFont(size=self.FONT_SIZES['normal']), width=100, anchor="w").pack(side="left")
        widgets['interval_label'] = ctk.CTkLabel(
            interval_row, text=f"{default_interval:.1f}s", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], width=50
        )
        widgets['interval_label'].pack(side="right")
        widgets['interval_slider'] = ctk.CTkSlider(
            interval_row, from_=min_interval, to=max_interval, number_of_steps=int((max_interval - min_interval) * 10),
            progress_color=self.COLORS['accent'], button_color=self.COLORS['accent'],
            button_hover_color=self.COLORS['accent_hover'],
            command=lambda v, d=display_num: self._on_interval_for_tab(v, widgets['interval_label'], d)
        )
        widgets['interval_slider'].set(default_interval)
        widgets['interval_slider'].pack(side="left", fill="x", expand=True, padx=10)
        
        # Smoothing slider
        smooth_row = ctk.CTkFrame(parent, fg_color="transparent")
        smooth_row.pack(fill="x", pady=5)
        ctk.CTkLabel(smooth_row, text="〰️", font=ctk.CTkFont(size=self.FONT_SIZES['icon']), width=30).pack(side="left")
        ctk.CTkLabel(smooth_row, text="Smoothing", font=ctk.CTkFont(size=self.FONT_SIZES['normal']), width=100, anchor="w").pack(side="left")
        widgets['smoothing_label'] = ctk.CTkLabel(
            smooth_row, text="0.3", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            text_color=self.COLORS['accent'], width=50
        )
        widgets['smoothing_label'].pack(side="right")
        widgets['smoothing_slider'] = ctk.CTkSlider(
            smooth_row, from_=0, to=100, number_of_steps=100,
            progress_color=self.COLORS['accent'], button_color=self.COLORS['accent'],
            button_hover_color=self.COLORS['accent_hover'],
            command=lambda v, d=display_num: self._on_smoothing_for_tab(v, widgets['smoothing_label'], d)
        )
        widgets['smoothing_slider'].set(30)
        widgets['smoothing_slider'].pack(side="left", fill="x", expand=True, padx=10)
        
        return widgets
    
    def _create_slider_adaptive(self, parent, label: str, icon: str, command) -> tuple:
        """Create a slider row for adaptive settings with full labels."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=5)
        
        ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=self.FONT_SIZES['icon']), width=30).pack(side="left")
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                     text_color=self.COLORS['text_dim'], width=100, anchor="w").pack(side="left")
        
        value_label = ctk.CTkLabel(row, text="50", font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
                                   text_color=self.COLORS['accent'], width=40)
        value_label.pack(side="right")
        
        def on_change(v, lbl=value_label):
            lbl.configure(text=str(int(v)))
            command(int(v))
        
        slider = ctk.CTkSlider(row, from_=0, to=100, number_of_steps=100,
                               progress_color=self.COLORS['accent'], button_color=self.COLORS['accent'],
                               button_hover_color=self.COLORS['accent_hover'], command=on_change)
        slider.set(50)
        slider.pack(side="left", fill="x", expand=True, padx=10)
        
        return slider, value_label
    
    def _toggle_auto_brightness_for_tab(self, display_num: int):
        """Toggle auto brightness for a specific monitor."""
        widgets = self._monitor_widgets.get(display_num, {})
        btn = widgets.get('auto_brightness_btn')
        if not btn:
            return
        
        # Toggle state
        current = "ON" in btn.cget("text")
        new_state = not current
        
        btn.configure(
            text=f"☀️ Auto Brightness: {'ON' if new_state else 'OFF'}",
            fg_color=self.COLORS['accent'] if new_state else self.COLORS['bg']
        )
        
        self._invoke_callback('toggle_auto_brightness', new_state, display_num)
    
    def _toggle_auto_contrast_for_tab(self, display_num: int):
        """Toggle auto contrast for a specific monitor."""
        widgets = self._monitor_widgets.get(display_num, {})
        btn = widgets.get('auto_contrast_btn')
        if not btn:
            return
        
        current = "ON" in btn.cget("text")
        new_state = not current
        
        btn.configure(
            text=f"◐ Auto Contrast: {'ON' if new_state else 'OFF'}",
            fg_color=self.COLORS['accent'] if new_state else self.COLORS['bg']
        )
        
        self._invoke_callback('toggle_auto_contrast', new_state, display_num)
    
    def _on_fullscreen_only_toggle(self, display_num: int):
        """Handle fullscreen only toggle for a specific monitor."""
        widgets = self._monitor_widgets.get(display_num, {})
        switch = widgets.get('fullscreen_only_switch')
        if switch:
            enabled = switch.get() == 1
            logger.info(f"Fullscreen only toggle: display={display_num}, enabled={enabled}")
            self._invoke_callback('fullscreen_only_toggle', enabled, display_num)
    
    def set_fullscreen_only_state(self, enabled: bool, display_num: int = None):
        """Set the fullscreen only switch state."""
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            switch = widgets.get('fullscreen_only_switch')
            if switch:
                if enabled:
                    switch.select()
                else:
                    switch.deselect()
    
    def _toggle_auto_profile_for_tab(self, display_num: int):
        """Toggle auto profile switch for a specific monitor."""
        widgets = self._monitor_widgets.get(display_num, {})
        btn = widgets.get('auto_profile_btn')
        if not btn:
            return
        
        current = "ON" in btn.cget("text")
        new_state = not current
        
        btn.configure(
            text=f"📁 Auto Profile Switch: {'ON' if new_state else 'OFF'}",
            fg_color=self.COLORS['accent'] if new_state else self.COLORS['bg']
        )
        
        self._invoke_callback('toggle_auto_profile', new_state, display_num)
    
    def _detect_system_scale(self) -> float:
        """Detect system DPI scaling factor on Linux."""
        import subprocess
        import os
        
        # Method 1: Check GDK_SCALE environment variable
        gdk_scale = os.environ.get('GDK_SCALE')
        if gdk_scale:
            try:
                return float(gdk_scale)
            except ValueError:
                pass
        
        # Method 2: Check GNOME scaling factor
        try:
            result = subprocess.run(
                ['gsettings', 'get', 'org.gnome.desktop.interface', 'scaling-factor'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                # Output is like "uint32 2" for 200%
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    scale = int(parts[-1])
                    if scale > 0:
                        return float(scale)
        except Exception:
            pass
        
        # Method 3: Check GNOME text-scaling-factor (for fractional scaling)
        try:
            result = subprocess.run(
                ['gsettings', 'get', 'org.gnome.desktop.interface', 'text-scaling-factor'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                scale = float(result.stdout.strip())
                if scale > 1.0:
                    return scale
        except Exception:
            pass
        
        # Method 4: Check Xft.dpi from xrdb
        try:
            result = subprocess.run(
                ['xrdb', '-query'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'Xft.dpi' in line:
                        dpi = float(line.split(':')[1].strip())
                        # 96 is standard DPI, calculate scale factor
                        scale = dpi / 96.0
                        if scale > 1.0:
                            return scale
        except Exception:
            pass
        
        # Method 5: Check QT_SCALE_FACTOR
        qt_scale = os.environ.get('QT_SCALE_FACTOR')
        if qt_scale:
            try:
                scale = float(qt_scale)
                if scale > 1.0:
                    return scale
            except ValueError:
                pass
        
        # Default: no scaling
        return 1.0
    
    def _on_adaptive_setting_for_tab(self, setting: str, value: int, display_num: int):
        """Handle adaptive setting change for a specific monitor (debounced)."""
        self._debounced_adaptive_callback(setting, value, display_num)
    
    def _on_interval_for_tab(self, value, label, display_num: int):
        """Handle interval change for a specific monitor (debounced)."""
        # Slider value IS the interval in seconds (0.5-30 on X11, 1.0-30 on Wayland)
        interval = float(value)
        label.configure(text=f"{interval:.1f}s")
        self._debounced_adaptive_callback('interval', interval, display_num)
    
    def _on_smoothing_for_tab(self, value, label, display_num: int):
        """Handle smoothing change for a specific monitor (debounced)."""
        smoothing = value / 100.0  # Convert 0-100 to 0.0-1.0
        label.configure(text=f"{smoothing:.2f}")
        self._debounced_adaptive_callback('smoothing', smoothing, display_num)
    
    def _debounced_adaptive_callback(self, setting: str, value, display_num: int):
        """Debounce adaptive setting changes - only invoke after user stops dragging."""
        key = f'adaptive_{setting}_{display_num}'
        
        # Cancel existing timer
        if key in self._slider_debounce_timers:
            self._root.after_cancel(self._slider_debounce_timers[key])
        
        # Schedule callback with longer delay for settings that trigger saves
        def invoke():
            if key in self._slider_debounce_timers:
                del self._slider_debounce_timers[key]
            self._invoke_callback('adaptive_setting_change', setting, value, display_num)
        
        # 300ms delay - enough to batch rapid changes while feeling responsive
        self._slider_debounce_timers[key] = self._root.after(300, invoke)
    
    def _create_profile_list_for_tab(self, parent, profile_widgets: Dict, display_num: int):
        """Create profile list for a tab."""
        for profile_name in self._available_profiles:
            self._add_profile_row_to_tab(parent, profile_name, profile_widgets, display_num)
    
    def _add_profile_row_to_tab(self, parent, profile_name: str, profile_widgets: Dict, display_num: int):
        """Add a profile row to a tab's profile list."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        
        # Use grid layout with fixed widths for consistency
        row.grid_columnconfigure(0, weight=0, minsize=100)  # Button fixed width
        row.grid_columnconfigure(1, weight=1)  # Dropdown expands to fill remaining space
        row.grid_columnconfigure(2, weight=0, minsize=36)   # Auto brightness switch
        row.grid_columnconfigure(3, weight=0, minsize=36)   # Auto contrast switch
        row.grid_columnconfigure(4, weight=0, minsize=36)   # Add button fixed width
        
        # Profile select button - fixed width for consistency
        btn = ctk.CTkButton(
            row, text=profile_name.capitalize(), width=100, height=32,
            font=ctk.CTkFont(size=self.FONT_SIZES['button']), fg_color=self.COLORS['bg'],
            hover_color=self.COLORS['border'], corner_radius=6,
            command=lambda p=profile_name, d=display_num: self._on_profile_select_for_tab(p, d)
        )
        btn.grid(row=0, column=0, sticky="w", padx=(0, 5))
        
        # Color mode dropdown - expands to fill available space
        current_mode = self._profile_color_modes.get(profile_name, "Standard")
        dropdown = SmartOptionMenu(
            row, values=self._color_mode_names, height=32,
            font=ctk.CTkFont(size=self.FONT_SIZES['small']), fg_color=self.COLORS['bg_secondary'],
            button_color=self.COLORS['accent'], button_hover_color=self.COLORS['accent_hover'],
            dropdown_fg_color=self.COLORS['bg_secondary'], dropdown_hover_color=self.COLORS['border'],
            command=lambda mode, p=profile_name, d=display_num: self._on_profile_mode_change_for_tab(p, mode, d)
        )
        dropdown.set(current_mode)
        dropdown.grid(row=0, column=1, sticky="ew", padx=5)
        
        # Auto brightness switch for this profile
        auto_bright_switch = ctk.CTkSwitch(
            row, text="☀", width=36, height=24,
            font=ctk.CTkFont(size=self.FONT_SIZES['small']),
            fg_color=self.COLORS['bg'],
            progress_color=self.COLORS['accent'],
            button_color=self.COLORS['text'],
            button_hover_color=self.COLORS['accent'],
            command=lambda p=profile_name, d=display_num: self._on_profile_auto_brightness_toggle(p, d)
        )
        auto_bright_switch.grid(row=0, column=2, padx=2)
        
        # Auto contrast switch for this profile
        auto_contrast_switch = ctk.CTkSwitch(
            row, text="◐", width=36, height=24,
            font=ctk.CTkFont(size=self.FONT_SIZES['small']),
            fg_color=self.COLORS['bg'],
            progress_color=self.COLORS['accent'],
            button_color=self.COLORS['text'],
            button_hover_color=self.COLORS['accent'],
            command=lambda p=profile_name, d=display_num: self._on_profile_auto_contrast_toggle(p, d)
        )
        auto_contrast_switch.grid(row=0, column=3, padx=2)
        
        # Add current app button - fixed width
        add_btn = ctk.CTkButton(
            row, text="+", width=32, height=32,
            font=ctk.CTkFont(size=self.FONT_SIZES['title'], weight="bold"),
            fg_color=self.COLORS['bg'],
            hover_color=self.COLORS['accent'],
            corner_radius=6,
            command=lambda p=profile_name, d=display_num: self._on_add_app_to_profile(p, d)
        )
        add_btn.grid(row=0, column=4, sticky="e", padx=(0, 0))
        
        profile_widgets[profile_name] = {
            'button': btn, 
            'dropdown': dropdown, 
            'add_btn': add_btn,
            'auto_bright_switch': auto_bright_switch,
            'auto_contrast_switch': auto_contrast_switch
        }
    
    def _on_profile_auto_brightness_toggle(self, profile_name: str, display_num: int):
        """Handle auto brightness toggle for a specific profile."""
        logger.info(f"Profile auto brightness toggle: profile={profile_name}, display={display_num}")
        widgets = self._monitor_widgets.get(display_num, {}).get('profile_widgets', {}).get(profile_name, {})
        switch = widgets.get('auto_bright_switch')
        if switch:
            enabled = switch.get() == 1
            logger.info(f"Profile auto brightness: {profile_name} -> {enabled}")
            self._invoke_callback('profile_auto_brightness_toggle', profile_name, enabled, display_num)
        else:
            logger.warning(f"No switch found for profile {profile_name} display {display_num}")
    
    def _on_profile_auto_contrast_toggle(self, profile_name: str, display_num: int):
        """Handle auto contrast toggle for a specific profile."""
        logger.info(f"Profile auto contrast toggle: profile={profile_name}, display={display_num}")
        widgets = self._monitor_widgets.get(display_num, {}).get('profile_widgets', {}).get(profile_name, {})
        switch = widgets.get('auto_contrast_switch')
        if switch:
            enabled = switch.get() == 1
            logger.info(f"Profile auto contrast: {profile_name} -> {enabled}")
            self._invoke_callback('profile_auto_contrast_toggle', profile_name, enabled, display_num)
        else:
            logger.warning(f"No switch found for profile {profile_name} display {display_num}")
    
    def _on_profile_select_for_tab(self, profile_name: str, display_num: int):
        """Handle profile selection for a specific monitor."""
        self._invoke_callback('profile_select', profile_name, display_num)
    
    def _on_profile_mode_change_for_tab(self, profile_name: str, mode_name: str, display_num: int):
        """Handle profile mode change for a specific monitor."""
        self._invoke_callback('profile_mode_change', profile_name, mode_name, display_num)
    
    def _on_add_app_to_profile(self, profile_name: str, display_num: int):
        """Add current detected app to the specified profile's match list."""
        # Get current app class for this display
        current_app_class = self._current_app_classes.get(display_num, "")
        if current_app_class and current_app_class not in ("", "Not detected", "unknown"):
            logger.info(f"Adding app '{current_app_class}' to profile '{profile_name}'")
            self._invoke_callback('add_app_to_profile', profile_name, current_app_class)
            # Show brief confirmation in the app label
            if display_num in self._monitor_widgets:
                widgets = self._monitor_widgets[display_num]
                if 'current_app_label' in widgets:
                    original_text = widgets['current_app_label'].cget("text")
                    widgets['current_app_label'].configure(
                        text=f"✓ Added to {profile_name.capitalize()}",
                        text_color=self.COLORS['accent']
                    )
                    # Restore after 2 seconds
                    def restore():
                        if 'current_app_label' in widgets:
                            widgets['current_app_label'].configure(
                                text=original_text,
                                text_color=self.COLORS['text']
                            )
                    self._root.after(2000, restore)
        else:
            logger.warning(f"No valid app detected for display {display_num} to add to profile '{profile_name}'")
    
    def _create_section(self, parent, title: str, icon: str = "", collapsed: bool = False) -> ctk.CTkFrame:
        """Create a collapsible section with title."""
        # Use minimal corner_radius for flatter look
        section = ctk.CTkFrame(parent, fg_color=self.COLORS['bg_secondary'], corner_radius=4, border_width=0)
        section.pack(fill="x", pady=(0, 4))
        
        # Section header (clickable to toggle)
        header = ctk.CTkFrame(section, fg_color="transparent", cursor="hand2")
        header.pack(fill="x", padx=6, pady=(4, 2))
        
        # Collapse indicator
        collapse_label = ctk.CTkLabel(
            header, text="▼" if not collapsed else "▶",
            font=ctk.CTkFont(size=self.FONT_SIZES['small']),
            text_color=self.COLORS['text_dim'], width=15
        )
        collapse_label.pack(side="left")
        
        ctk.CTkLabel(
            header,
            text=f"{icon} {title}",
            font=ctk.CTkFont(size=self.FONT_SIZES['title'], weight="bold"),
            text_color=self.COLORS['accent']
        ).pack(side="left")
        
        # Content frame
        content = ctk.CTkFrame(section, fg_color="transparent")
        if not collapsed:
            content.pack(fill="x", padx=6, pady=(0, 4))
        
        # Toggle function
        def toggle_section(event=None):
            if content.winfo_ismapped():
                content.pack_forget()
                collapse_label.configure(text="▶")
            else:
                content.pack(fill="x", padx=6, pady=(0, 4))
                collapse_label.configure(text="▼")
            # Trigger scrollbar visibility check after content change
            if hasattr(self, '_scrollbar_check_funcs') and self._root:
                self._root.after(50, self._trigger_all_scrollbar_checks)
        
        # Bind click events to header and all its children
        header.bind("<Button-1>", toggle_section)
        for child in header.winfo_children():
            child.bind("<Button-1>", toggle_section)
        
        return content
    
    def _set_wm_class(self):
        """Set WM_CLASS for proper taskbar icon association on Linux."""
        # WM_CLASS is now set via className parameter in CTk() constructor
        # This method kept for backwards compatibility
        pass
    
    def _load_app_icon(self, size: int = 64):
        """Load the app icon as a CTkImage for use in the GUI."""
        try:
            if not PIL_AVAILABLE:
                return None
            
            icon_paths = [
                Path(__file__).parent.parent.parent / "assets" / "icon.png",
                Path(__file__).parent.parent.parent / "assets" / f"icon_{size}.png",
                Path(__file__).parent.parent.parent / "assets" / "icon_64.png",
                Path.home() / ".local" / "share" / "monitor-control" / "icon.png",
            ]
            
            for path in icon_paths:
                if path.exists():
                    img = Image.open(path)
                    img = img.resize((size, size), Image.Resampling.LANCZOS)
                    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
            
            return None
        except Exception as e:
            logger.debug(f"Could not load app icon: {e}")
            return None
    
    def _set_window_icon(self):
        """Set the window icon."""
        try:
            # Find icon file
            icon_paths = [
                Path(__file__).parent.parent.parent / "assets" / "icon.png",
                Path(__file__).parent.parent.parent / "assets" / "icon_64.png",
                Path.home() / ".local" / "share" / "monitor-control" / "icon.png",
            ]
            
            icon_path = None
            for path in icon_paths:
                if path.exists():
                    icon_path = path
                    break
            
            if icon_path and PIL_AVAILABLE:
                # Load multiple sizes for better display
                icon_sizes = []
                for size in [16, 32, 48, 64, 128, 256]:
                    size_path = icon_path.parent / f"icon_{size}.png"
                    if size_path.exists():
                        img = Image.open(size_path)
                        icon_sizes.append(ImageTk.PhotoImage(img))
                
                if not icon_sizes:
                    # Fall back to main icon
                    icon_img = Image.open(icon_path)
                    icon_sizes = [ImageTk.PhotoImage(icon_img)]
                
                # Set all icon sizes
                self._root.iconphoto(True, *icon_sizes)
                self._icon_photos = icon_sizes  # Keep references
                logger.debug(f"Window icon set from {icon_path}")
            else:
                # Create a simple icon programmatically
                self._create_fallback_icon()
        except Exception as e:
            logger.debug(f"Could not set window icon: {e}")
            self._create_fallback_icon()
    
    def _create_fallback_icon(self):
        """Create a simple fallback icon."""
        try:
            if PIL_AVAILABLE:
                # Create a simple 32x32 icon
                img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)
                
                # Orange monitor shape
                draw.rounded_rectangle([2, 2, 30, 22], radius=3, fill=(255, 107, 0, 255))
                draw.rectangle([13, 22, 19, 26], fill=(255, 107, 0, 255))
                draw.rounded_rectangle([10, 26, 22, 29], radius=2, fill=(255, 107, 0, 255))
                
                icon_photo = ImageTk.PhotoImage(img)
                self._root.iconphoto(True, icon_photo)
                self._icon_photo = icon_photo
        except Exception as e:
            logger.debug(f"Could not create fallback icon: {e}")
    
    def _on_window_close(self):
        logger.info("Window closed, shutting down...")
        self._running = False
        
        # Save window geometry before closing
        self._save_window_geometry()
        
        # Notify main app to stop (this just sets a flag)
        self._invoke_callback('quit')
        
        # Destroy the GUI (we're on the tkinter thread)
        self._force_quit()
    
    def _load_window_geometry(self) -> Optional[Dict]:
        """Load saved window geometry from file."""
        try:
            if WINDOW_GEOMETRY_FILE.exists():
                with open(WINDOW_GEOMETRY_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Could not load window geometry: {e}")
        return None
    
    def _save_window_geometry(self):
        """Save current window geometry to file."""
        try:
            if not self._root:
                return
            
            # Get current geometry
            geometry = self._root.geometry()
            # Parse "WIDTHxHEIGHT+X+Y" format
            import re
            match = re.match(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)', geometry)
            if match:
                data = {
                    'width': int(match.group(1)),
                    'height': int(match.group(2)),
                    'x': int(match.group(3)),
                    'y': int(match.group(4))
                }
                WINDOW_GEOMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(WINDOW_GEOMETRY_FILE, 'w') as f:
                    json.dump(data, f)
                logger.debug(f"Saved window geometry: {data}")
        except Exception as e:
            logger.debug(f"Could not save window geometry: {e}")
    
    def _invoke_callback(self, name: str, *args):
        if name in self._callbacks:
            try:
                self._callbacks[name](*args)
            except Exception as e:
                logger.error(f"Callback error ({name}): {e}")
    
    # Public API
    def start(self):
        """Start the overlay in background thread."""
        if self._running:
            return
        self._running = True
        self._tk_thread = threading.Thread(target=self._run_mainloop, daemon=True)
        self._tk_thread.start()
        self._initialized.wait(timeout=5)
        logger.info("CustomTkinter overlay started")
    
    def _run_mainloop(self):
        self._create_window()
        self._root.mainloop()
    
    def stop(self):
        self._running = False
        if self._root:
            try:
                # Schedule quit on the tkinter thread
                self._root.after(0, self._force_quit)
            except:
                pass
            # Wait for tkinter thread to finish
            if hasattr(self, '_tk_thread') and self._tk_thread:
                self._tk_thread.join(timeout=2)
    
    def _force_quit(self):
        """Force quit from the tkinter thread."""
        try:
            self._root.quit()
        except:
            pass
        try:
            self._root.destroy()
        except:
            pass
        self._root = None
    
    def _on_refresh_monitors(self):
        """Handle refresh monitors button click."""
        logger.info("Refreshing monitor list...")
        # Update button to show loading state
        if hasattr(self, '_refresh_btn'):
            self._refresh_btn.configure(text="◌")
        # Invoke callback to re-detect monitors
        self._invoke_callback('refresh_monitors')
        # Reset button after a short delay
        if self._root:
            self._root.after(500, lambda: self._refresh_btn.configure(text="⟳") if hasattr(self, '_refresh_btn') else None)
    
    def set_monitors(self, monitors: List[tuple], current_display: int = 1):
        """
        Set available monitors - creates a tab for each monitor.
        
        Args:
            monitors: List of (display_number, display_name) tuples
            current_display: Currently selected display number
        """
        self._monitors = monitors
        if not monitors or not self._root or not hasattr(self, '_tabview'):
            return
        
        def create_tabs():
            # Remove old tabs
            for tab_name in list(self._tabview._tab_dict.keys()):
                self._tabview.delete(tab_name)
            
            self._monitor_tabs.clear()
            self._monitor_widgets.clear()
            self._overview_widgets.clear()
            self._monitor_geometries.clear()
            
            # Create Overview tab first
            self._tabview.add("📊 Overview")
            overview_frame = self._tabview.tab("📊 Overview")
            self._create_overview_tab(overview_frame, monitors)
            
            # Create a tab for each monitor
            current_tab_name = None
            for display_num, display_name in monitors:
                try:
                    # Extract just the model name (remove "Display X" part)
                    tab_name = display_name
                    if "(Display" in display_name:
                        tab_name = display_name.split(" (Display")[0]
                    
                    # Add tab
                    logger.debug(f"Creating tab for display {display_num}: {tab_name}")
                    self._tabview.add(tab_name)
                    tab_frame = self._tabview.tab(tab_name)
                    self._monitor_tabs[display_num] = tab_frame
                    
                    # Create all controls for this monitor
                    self._monitor_widgets[display_num] = self._create_monitor_tab_content(tab_frame, display_num)
                    
                    if display_num == current_display:
                        current_tab_name = tab_name
                    logger.debug(f"Successfully created tab for display {display_num}")
                except Exception as e:
                    logger.error(f"Failed to create tab for display {display_num}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            # Always select Overview as default tab
            self._tabview.set("📊 Overview")
            
            logger.info(f"Created {len(monitors)} monitor tabs + Overview")
        
        self._root.after(0, create_tabs)
    
    def are_tabs_ready(self, expected_count: int) -> bool:
        """Check if all monitor tabs have been created."""
        return len(self._monitor_widgets) >= expected_count
    
    def set_loading_status(self, text: str):
        """Update the loading status text."""
        if self._root and hasattr(self, '_loading_label'):
            self._root.after(0, lambda: self._loading_label.configure(text=text))
    
    def show_loading(self, text: str = "Loading..."):
        """Show the loading overlay."""
        if self._root and hasattr(self, '_loading_frame'):
            def _show():
                self._main_frame.pack_forget()
                self._loading_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
                if hasattr(self, '_loading_label'):
                    self._loading_label.configure(text=text)
                if hasattr(self, '_loading_progress'):
                    self._loading_progress.start()
                logger.info(f"Showing loading: {text}")
            self._root.after(0, _show)
    
    def hide_loading(self):
        """Hide the loading overlay and show the main content."""
        if self._root and hasattr(self, '_loading_frame'):
            def _hide():
                if hasattr(self, '_loading_progress'):
                    self._loading_progress.stop()
                self._loading_frame.place_forget()
                self._main_frame.pack(fill="both", expand=True, padx=6, pady=6)
                logger.info("Loading complete, showing main UI")
                # Trigger scrollbar visibility checks after main UI is shown
                for delay in [100, 300, 500, 1000]:
                    self._root.after(delay, self._trigger_all_scrollbar_checks)
            self._root.after(0, _hide)
    
    def show_overlay(self):
        if self._root:
            self._root.after(0, lambda: (self._root.deiconify(), self._root.lift()))
            self._visible = True
    
    def hide_overlay(self):
        if self._root:
            self._root.after(0, self._root.withdraw)
            self._visible = False
    
    def toggle(self):
        if self._visible:
            self.hide_overlay()
        else:
            self.show_overlay()
    
    def _get_current_display(self) -> Optional[int]:
        """Get the display number for the currently selected tab."""
        if not hasattr(self, '_tabview'):
            return None
        tab_name = self._tabview.get()
        for display_num, display_name in self._monitors:
            if display_name == tab_name:
                return display_num
        return None
    
    def set_brightness(self, value: int, display_num: int = None):
        """Set brightness slider value for current or specified monitor tab."""
        self._brightness = value
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            slider = widgets.get('brightness_slider')
            label = widgets.get('brightness_label')
            if slider and label:
                def update(v=value, s=slider, l=label):
                    self._updating_from_code = True
                    try:
                        s.set(v)
                        l.configure(text=str(v))
                        s.update_idletasks()
                    finally:
                        self._updating_from_code = False
                self._root.after(0, update)
    
    def set_contrast(self, value: int, display_num: int = None):
        """Set contrast slider value for current or specified monitor tab."""
        self._contrast = value
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            slider = widgets.get('contrast_slider')
            label = widgets.get('contrast_label')
            if slider and label:
                def update(v=value, s=slider, l=label):
                    self._updating_from_code = True
                    try:
                        s.set(v)
                        l.configure(text=str(v))
                        s.update_idletasks()
                    finally:
                        self._updating_from_code = False
                self._root.after(0, update)
    
    def set_sharpness(self, value: int, display_num: int = None):
        """Set sharpness slider value for current or specified monitor tab."""
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            slider = widgets.get('sharpness_slider')
            label = widgets.get('sharpness_label')
            if slider and label:
                def update(v=value, s=slider, l=label):
                    self._updating_from_code = True
                    try:
                        s.set(v)
                        l.configure(text=str(v))
                        s.update_idletasks()
                    finally:
                        self._updating_from_code = False
                self._root.after(0, update)
    
    def configure_sharpness_range(self, max_value: int, display_num: int = None):
        """Configure the sharpness slider range for a monitor."""
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            slider = widgets.get('sharpness_slider')
            if slider:
                def update(s=slider, m=max_value):
                    s.configure(to=m, number_of_steps=m)
                self._root.after(0, update)
            # Store the max value for later use
            widgets['sharpness_max'] = max_value
    
    def disable_feature(self, feature: str, display_num: int = None):
        """Disable a feature slider for a monitor that doesn't support it.
        
        Args:
            feature: Feature name ('sharpness', 'red_gain', 'green_gain', 'blue_gain')
            display_num: Monitor display number
        """
        if display_num is None:
            display_num = self._get_current_display()
        
        if not display_num:
            return
        
        # Map feature names to widget names (for monitor tab)
        feature_map = {
            'sharpness': ('sharpness_slider', 'sharpness_label'),
            'red_gain': ('red_slider', 'red_label'),
            'green_gain': ('green_slider', 'green_label'),
            'blue_gain': ('blue_slider', 'blue_label'),
        }
        
        # Map feature names to overview widget names
        overview_feature_map = {
            'sharpness': 'sharpness',
        }
        
        if feature not in feature_map:
            logger.warning(f"Unknown feature: {feature}")
            return
        
        def update():
            # Disable in monitor tab
            if display_num in self._monitor_widgets:
                widgets = self._monitor_widgets[display_num]
                slider_key, label_key = feature_map[feature]
                slider = widgets.get(slider_key)
                label = widgets.get(label_key)
                
                if slider:
                    slider.configure(state="disabled", button_color=self.COLORS['border'])
                    slider.set(0)
                if label:
                    label.configure(text="N/A", text_color=self.COLORS['text_dim'])
                
                # Store disabled state
                if 'disabled_features' not in widgets:
                    widgets['disabled_features'] = set()
                widgets['disabled_features'].add(feature)
            
            # Also update overview if applicable
            if feature in overview_feature_map and display_num in self._overview_widgets:
                overview_widgets = self._overview_widgets[display_num]
                overview_key = overview_feature_map[feature]
                if overview_key in overview_widgets:
                    overview_widgets[overview_key].configure(text="N/A", text_color=self.COLORS['text_dim'])
        
        if self._root:
            self._root.after(0, update)
        
        logger.info(f"GUI: Disabled {feature} for display {display_num} (not supported)")
    
    def set_red_gain(self, value: int, display_num: int = None):
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            slider = widgets.get('red_slider')
            label = widgets.get('red_label')
            if slider and label:
                def update(v=value, s=slider, l=label):
                    self._updating_from_code = True
                    try:
                        s.set(v)
                        l.configure(text=str(v))
                        s.update_idletasks()
                    finally:
                        self._updating_from_code = False
                self._root.after(0, update)
    
    def set_green_gain(self, value: int, display_num: int = None):
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            slider = widgets.get('green_slider')
            label = widgets.get('green_label')
            if slider and label:
                def update(v=value, s=slider, l=label):
                    self._updating_from_code = True
                    try:
                        s.set(v)
                        l.configure(text=str(v))
                        s.update_idletasks()
                    finally:
                        self._updating_from_code = False
                self._root.after(0, update)
    
    def set_blue_gain(self, value: int, display_num: int = None):
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            slider = widgets.get('blue_slider')
            label = widgets.get('blue_label')
            if slider and label:
                def update(v=value, s=slider, l=label):
                    self._updating_from_code = True
                    try:
                        s.set(v)
                        l.configure(text=str(v))
                        s.update_idletasks()
                    finally:
                        self._updating_from_code = False
                self._root.after(0, update)
    
    def set_auto_brightness_state(self, enabled: bool, display_num: int = None):
        """Update auto brightness toggle state in GUI (called when profile changes)."""
        logger.info(f"GUI: set_auto_brightness_state({enabled}, display={display_num})")
        self._auto_brightness_enabled = enabled
        
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            btn = widgets.get('auto_brightness_btn')
            if btn:
                text = f"☀️ Auto Brightness: {'ON' if enabled else 'OFF'}"
                color = self.COLORS['accent'] if enabled else self.COLORS['bg']
                def update(t=text, c=color, b=btn):
                    b.configure(text=t, fg_color=c)
                    b.update_idletasks()
                self._root.after(10, update)  # Small delay to ensure widget is ready
    
    def set_auto_contrast_state(self, enabled: bool, display_num: int = None):
        """Update auto contrast toggle state in GUI (called when profile changes)."""
        logger.info(f"GUI: set_auto_contrast_state({enabled}, display={display_num})")
        self._auto_contrast_enabled = enabled
        
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            btn = widgets.get('auto_contrast_btn')
            if btn:
                text = f"◐ Auto Contrast: {'ON' if enabled else 'OFF'}"
                color = self.COLORS['accent'] if enabled else self.COLORS['bg']
                def update(t=text, c=color, b=btn):
                    b.configure(text=t, fg_color=c)
                    b.update_idletasks()
                self._root.after(10, update)
    
    def set_auto_profile_state(self, enabled: bool, display_num: int = None):
        """Update auto profile toggle state in GUI."""
        logger.info(f"GUI: set_auto_profile_state({enabled})")
        self._auto_profile_enabled = enabled
        
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            btn = widgets.get('auto_profile_btn')
            if btn:
                text = f"📁 Auto Profile Switch: {'ON' if enabled else 'OFF'}"
                color = self.COLORS['accent'] if enabled else self.COLORS['bg']
                def update(t=text, c=color, b=btn):
                    b.configure(text=t, fg_color=c)
                    b.update_idletasks()
                self._root.after(10, update)
    
    def set_profile_auto_states(self, profile_states: Dict[str, Dict[str, bool]], display_num: int = None):
        """
        Update auto brightness/contrast switch states for all profiles in a monitor tab.
        
        Args:
            profile_states: Dict of {profile_name: {'auto_brightness': bool, 'auto_contrast': bool}}
            display_num: Display number to update
        """
        if display_num is None:
            display_num = self._get_current_display()
        
        def apply_states():
            if display_num and display_num in self._monitor_widgets:
                profile_widgets = self._monitor_widgets[display_num].get('profile_widgets', {})
                for profile_name, states in profile_states.items():
                    if profile_name in profile_widgets:
                        widgets = profile_widgets[profile_name]
                        if 'auto_bright_switch' in widgets and 'auto_brightness' in states:
                            switch = widgets['auto_bright_switch']
                            if states['auto_brightness']:
                                switch.select()
                            else:
                                switch.deselect()
                        if 'auto_contrast_switch' in widgets and 'auto_contrast' in states:
                            switch = widgets['auto_contrast_switch']
                            if states['auto_contrast']:
                                switch.select()
                            else:
                                switch.deselect()
        
        # Schedule to run after widgets are created
        if self._root:
            self._root.after(100, apply_states)
    
    def set_all_profiles_auto_brightness(self, enabled: bool, display_num: int = None):
        """Set auto brightness for ALL profiles on a monitor (used by overview toggle)."""
        if display_num is None:
            display_num = self._get_current_display()
        
        logger.info(f"set_all_profiles_auto_brightness: enabled={enabled}, display_num={display_num}")
        logger.debug(f"Available monitor widgets keys: {list(self._monitor_widgets.keys())}")
        
        if display_num and display_num in self._monitor_widgets:
            profile_widgets = self._monitor_widgets[display_num].get('profile_widgets', {})
            logger.info(f"Updating {len(profile_widgets)} profile widgets for display {display_num}: {list(profile_widgets.keys())}")
            for profile_name, widgets in profile_widgets.items():
                if 'auto_bright_switch' in widgets:
                    switch = widgets['auto_bright_switch']
                    if enabled:
                        switch.select()
                    else:
                        switch.deselect()
        else:
            logger.warning(f"No widgets found for display_num={display_num}")
    
    def set_all_profiles_auto_contrast(self, enabled: bool, display_num: int = None):
        """Set auto contrast for ALL profiles on a monitor (used by overview toggle)."""
        if display_num is None:
            display_num = self._get_current_display()
        
        logger.info(f"set_all_profiles_auto_contrast: enabled={enabled}, display_num={display_num}")
        
        if display_num and display_num in self._monitor_widgets:
            profile_widgets = self._monitor_widgets[display_num].get('profile_widgets', {})
            logger.info(f"Updating {len(profile_widgets)} profile widgets for display {display_num}")
            for profile_name, widgets in profile_widgets.items():
                if 'auto_contrast_switch' in widgets:
                    switch = widgets['auto_contrast_switch']
                    if enabled:
                        switch.select()
                    else:
                        switch.deselect()
        else:
            logger.warning(f"No widgets found for display_num={display_num}")
    
    def set_color_mode(self, mode: int, name: str = None, display_num: int = None):
        """Set the current color mode in the dropdown for current or specified monitor."""
        self._color_mode = mode
        
        if display_num is None:
            display_num = self._get_current_display()
        
        # Determine the name to display
        # _all_color_modes is {name: vcp_value}
        display_name = name
        if not display_name and self._all_color_modes:
            for mode_name, vcp_value in self._all_color_modes.items():
                if vcp_value == mode:
                    display_name = mode_name
                    break
        
        if display_name and display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            dropdown = widgets.get('color_mode_dropdown')
            if dropdown:
                logger.debug(f"Setting color mode dropdown to: {display_name} (value={mode})")
                self._root.after(0, lambda n=display_name: dropdown.set(n))
    
    def set_color_modes(self, modes: list, display_num: int = None):
        """Set available color modes in the dropdown for current or specified monitor."""
        self._color_mode_names = modes if modes else ["Standard"]
        
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            dropdown = widgets.get('color_mode_dropdown')
            if dropdown:
                self._root.after(0, lambda: dropdown.configure(values=self._color_mode_names))
            # Also update profile dropdowns for this monitor
            self._refresh_profile_color_mode_dropdowns_for_tab(display_num)
    
    def set_all_color_modes(self, modes_dict: dict, display_num: int = None):
        """Set the full color modes dictionary and update the dropdown for current or specified monitor.
        
        Args:
            modes_dict: Dictionary mapping color mode names to VCP values {name: vcp_value}
            display_num: Display number to set color modes for
        """
        self._all_color_modes = modes_dict if modes_dict else {}
        self._color_mode_names = list(modes_dict.keys()) if modes_dict else ["Standard"]
        
        if display_num is None:
            display_num = self._get_current_display()
        
        # Store per-monitor color modes
        if display_num:
            self._monitor_color_modes[display_num] = modes_dict if modes_dict else {}
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            dropdown = widgets.get('color_mode_dropdown')
            if dropdown:
                self._root.after(0, lambda: dropdown.configure(values=self._color_mode_names))
            self._refresh_profile_color_mode_dropdowns_for_tab(display_num)
    
    def _refresh_profile_color_mode_dropdowns_for_tab(self, display_num: int):
        """Refresh profile color mode dropdowns for a specific monitor tab."""
        if display_num not in self._monitor_widgets:
            return
        
        widgets = self._monitor_widgets[display_num]
        profile_widgets = widgets.get('profile_widgets', {})
        
        for profile_name, pw in profile_widgets.items():
            dropdown = pw.get('dropdown')
            if dropdown:
                def update_dropdown(d=dropdown):
                    d.configure(values=self._color_mode_names)
                self._root.after(0, update_dropdown)
    
    def set_profiles(self, profiles: list, profile_color_modes: dict = None):
        """Set available profiles (used for all monitors)."""
        self._available_profiles = profiles
        if profile_color_modes:
            self._profile_color_modes = profile_color_modes
        logger.info(f"Loaded {len(profiles)} profiles: {profiles}")
    
    def set_profile_color_modes(self, profile_color_modes: dict, display_num: int = None):
        """Update profile color mode dropdowns for a specific monitor tab.
        
        Args:
            profile_color_modes: Dict mapping profile name to color mode name
            display_num: Display number (or None for current)
        """
        if display_num is None:
            display_num = self._get_current_display()
        
        if not display_num or display_num not in self._monitor_widgets:
            return
        
        widgets = self._monitor_widgets[display_num]
        profile_widgets = widgets.get('profile_widgets', {})
        
        def update():
            for profile_name, pw in profile_widgets.items():
                if 'dropdown' in pw and profile_name in profile_color_modes:
                    mode_name = profile_color_modes[profile_name]
                    pw['dropdown'].set(mode_name)
        
        if self._root:
            self._root.after(0, update)
    
    def set_current_profile(self, profile_name: str, display_num: int = None):
        """Set the current active profile for a monitor tab."""
        self._current_profile_name = profile_name
        
        if display_num is None:
            display_num = self._get_current_display()
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            profile_widgets = widgets.get('profile_widgets', {})
            
            def update():
                for name, pw in profile_widgets.items():
                    is_active = name == profile_name
                    pw['button'].configure(
                        text=f"{'●' if is_active else '○'} {name.title()}",
                        fg_color=self.COLORS['accent'] if is_active else self.COLORS['bg']
                    )
            self._root.after(0, update)
    
    def set_current_app(self, app_title: str, app_class: str = "", display_num: int = None):
        """Set the current active application display for a monitor tab."""
        if display_num is None:
            display_num = self._get_current_display()
        
        # Store current app class for this display (used by add-app-to-profile button)
        if display_num:
            self._current_app_classes[display_num] = app_class or ""
        
        if display_num and display_num in self._monitor_widgets:
            widgets = self._monitor_widgets[display_num]
            
            def update():
                if 'current_app_label' in widgets:
                    # Truncate long titles
                    title = app_title[:40] + "..." if len(app_title) > 40 else app_title
                    widgets['current_app_label'].configure(text=title or "No window")
                if 'current_app_class' in widgets:
                    widgets['current_app_class'].configure(text=app_class or "")
            
            self._root.after(0, update)
    
    def _show_edit_color_names_dialog(self, display_num: int):
        """Show a dialog to edit color mode names for a specific monitor."""
        import tkinter as tk
        
        # Get current color modes for this monitor
        if display_num not in self._monitor_color_modes:
            logger.warning(f"No color modes for display {display_num}")
            return
        
        color_modes = self._monitor_color_modes[display_num]
        
        # Create dialog window - larger size
        dialog = ctk.CTkToplevel(self._root)
        dialog.title(f"Edit Color Mode Names - Display {display_num}")
        dialog.configure(fg_color=self.COLORS['bg'])
        dialog.transient(self._root)
        dialog.minsize(450, 400)
        
        # Calculate dialog size based on number of entries
        num_entries = len(color_modes)
        dialog_height = min(max(400, 150 + num_entries * 45), 700)
        dialog_width = 500
        
        # Center on parent
        dialog.update_idletasks()
        x = self._root.winfo_x() + (self._root.winfo_width() - dialog_width) // 2
        y = self._root.winfo_y() + (self._root.winfo_height() - dialog_height) // 2
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        
        # Defer grab_set until dialog is visible
        def do_grab():
            try:
                dialog.grab_set()
            except Exception:
                pass  # Ignore grab errors
        dialog.after(100, do_grab)
        
        # Main container with grid layout to keep buttons visible
        dialog.grid_rowconfigure(1, weight=1)  # Scrollable area expands
        dialog.grid_columnconfigure(0, weight=1)
        
        # Header frame (fixed at top)
        header_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 5))
        
        ctk.CTkLabel(
            header_frame,
            text="Edit Color Mode Names",
            font=ctk.CTkFont(size=self.FONT_SIZES['title']+2, weight="bold"),
            text_color=self.COLORS['text']
        ).pack()
        
        ctk.CTkLabel(
            header_frame,
            text="Rename color modes to match your monitor's UI",
            font=ctk.CTkFont(size=self.FONT_SIZES['small']),
            text_color=self.COLORS['text_dim']
        ).pack(pady=(5, 0))
        
        # Scrollable frame for entries (expands)
        scroll_frame = ctk.CTkScrollableFrame(
            dialog,
            fg_color=self.COLORS['bg_secondary'],
            corner_radius=8
        )
        scroll_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=10)
        
        # Store entry widgets
        entries = {}
        
        for name, value in sorted(color_modes.items(), key=lambda x: x[1]):
            row = ctk.CTkFrame(scroll_frame, fg_color="transparent")
            row.pack(fill="x", pady=4, padx=5)
            
            # VCP value label
            vcp_label = f"0x{value:04X}" if value >= 0x1000 else f"0x{value:02X}"
            ctk.CTkLabel(
                row,
                text=f"({vcp_label})",
                font=ctk.CTkFont(size=self.FONT_SIZES['small']),
                text_color=self.COLORS['text_dim'],
                width=80
            ).pack(side="left", padx=(0, 8))
            
            # Name entry
            entry = ctk.CTkEntry(
                row,
                font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
                height=32,
                fg_color=self.COLORS['bg'],
                border_color=self.COLORS['border'],
                text_color=self.COLORS['text']
            )
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, name)
            entries[value] = (name, entry)
        
        # Buttons frame (fixed at bottom)
        btn_frame = ctk.CTkFrame(dialog, fg_color=self.COLORS['bg_secondary'], corner_radius=8)
        btn_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=15)
        
        def save_changes():
            # Collect renamed modes
            new_modes = {}
            for value, (old_name, entry) in entries.items():
                new_name = entry.get().strip()
                if new_name:
                    new_modes[new_name] = value
            
            # Update internal storage
            self._monitor_color_modes[display_num] = new_modes
            self._all_color_modes = new_modes
            self._color_mode_names = list(new_modes.keys())
            
            # Update ALL dropdowns for this monitor
            new_names = list(new_modes.keys())
            
            # Update main color mode dropdown
            if display_num in self._monitor_widgets:
                widgets = self._monitor_widgets[display_num]
                dropdown = widgets.get('color_mode_dropdown')
                if dropdown:
                    dropdown.configure(values=new_names)
                
                # Update all profile dropdowns
                profile_widgets = widgets.get('profile_widgets', {})
                for profile_name, pw in profile_widgets.items():
                    profile_dropdown = pw.get('dropdown')
                    if profile_dropdown:
                        profile_dropdown.configure(values=new_names)
            
            # Notify main app to save to config
            self._invoke_callback('color_mode_names_changed', display_num, new_modes)
            
            logger.info(f"Updated color mode names for display {display_num}: {new_names}")
            dialog.destroy()
        
        def cancel():
            dialog.destroy()
        
        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=100,
            height=36,
            font=ctk.CTkFont(size=self.FONT_SIZES['normal']),
            fg_color=self.COLORS['bg'],
            hover_color=self.COLORS['border'],
            command=cancel
        ).pack(side="left", padx=15, pady=10)
        
        ctk.CTkButton(
            btn_frame,
            text="Save",
            width=100,
            height=36,
            font=ctk.CTkFont(size=self.FONT_SIZES['normal'], weight="bold"),
            fg_color=self.COLORS['accent'],
            hover_color=self.COLORS['accent_hover'],
            command=save_changes
        ).pack(side="right", padx=15, pady=10)
    
    def set_adaptive_settings(self, auto_brightness: bool, auto_contrast: bool, 
                               min_contrast: int, max_contrast: int,
                               min_brightness: int, max_brightness: int,
                               dark_threshold: float, bright_threshold: float, 
                               interval: float, smoothing: float = 0.3,
                               display_num: int = None):
        """Set adaptive settings for current or specified monitor tab."""
        self._auto_brightness_enabled = auto_brightness
        self._auto_contrast_enabled = auto_contrast
        
        if display_num is None:
            display_num = self._get_current_display()
        
        if not display_num or display_num not in self._monitor_widgets:
            return
        
        widgets = self._monitor_widgets[display_num]
        
        def update():
            # Update auto toggle buttons
            if 'auto_brightness_btn' in widgets:
                widgets['auto_brightness_btn'].configure(
                    text=f"☀️ Auto Brightness: {'ON' if auto_brightness else 'OFF'}",
                    fg_color=self.COLORS['accent'] if auto_brightness else self.COLORS['bg']
                )
            if 'auto_contrast_btn' in widgets:
                widgets['auto_contrast_btn'].configure(
                    text=f"◐ Auto Contrast: {'ON' if auto_contrast else 'OFF'}",
                    fg_color=self.COLORS['accent'] if auto_contrast else self.COLORS['bg']
                )
            
            # Update min/max sliders
            for name, val in [
                ('min_brightness', min_brightness),
                ('max_brightness', max_brightness),
                ('min_contrast', min_contrast),
                ('max_contrast', max_contrast),
            ]:
                slider_key = f'{name}_slider'
                label_key = f'{name}_label'
                if slider_key in widgets:
                    widgets[slider_key].set(val)
                    if label_key in widgets:
                        widgets[label_key].configure(text=str(val))
            
            # Update interval slider (slider value = seconds directly)
            # Clamp to min/max based on display server
            is_wayland = (os.environ.get('XDG_SESSION_TYPE') == 'wayland' or 
                          os.environ.get('WAYLAND_DISPLAY') is not None)
            min_interval = 2.5 if is_wayland else 0.5
            max_interval = 10.0 if is_wayland else 3.0
            clamped_interval = max(min_interval, min(max_interval, interval))
            
            if 'interval_slider' in widgets:
                widgets['interval_slider'].set(clamped_interval)
                if 'interval_label' in widgets:
                    widgets['interval_label'].configure(text=f"{clamped_interval:.1f}s")
            
            # Update smoothing slider (0.0-1.0, slider is 0-100)
            if 'smoothing_slider' in widgets:
                slider_val = int(smoothing * 100)
                widgets['smoothing_slider'].set(slider_val)
                if 'smoothing_label' in widgets:
                    widgets['smoothing_label'].configure(text=f"{smoothing:.2f}")
        
        if self._root:
            self._root.after(0, update)
    
    def set_status(self, text: str):
        self._status_text = text
    
    def set_callback(self, name: str, callback: Callable):
        self._callbacks[name] = callback


# Alias for compatibility
MonitorOverlay = MonitorOverlayCTk

