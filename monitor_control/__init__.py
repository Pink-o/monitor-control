"""
BenQ Monitor Control - DDC/CI based monitor management for Linux
================================================================

Control your BenQ RD280UA (or other DDC/CI compatible monitors) with:
- Automatic profile switching based on active applications
- Adaptive contrast based on screen content
- OSD-style GUI overlay
- System tray integration
"""

__version__ = "1.0.0"
__author__ = "Monitor Control"

from .ddc import DDCController
from .config import Config
from .profile_manager import ProfileManager
from .window_monitor import WindowMonitor
from .screen_analyzer import ScreenAnalyzer

__all__ = [
    "DDCController",
    "Config", 
    "ProfileManager",
    "WindowMonitor",
    "ScreenAnalyzer",
]


