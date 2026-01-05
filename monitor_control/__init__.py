"""
Monitor Control - DDC/CI based monitor management for Linux
============================================================

Control your DDC/CI compatible monitors with:
- Automatic profile switching based on active applications
- Adaptive brightness/contrast based on screen content
- Modern GUI overlay with CustomTkinter
- Multi-monitor support
"""

__version__ = "1.0.0"
__author__ = "Pink-o"

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


