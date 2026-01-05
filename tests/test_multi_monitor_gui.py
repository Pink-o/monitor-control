#!/usr/bin/env python3
"""
Automated UI tests for multi-monitor functionality.

Tests that operations on monitor X only affect monitor X, not other monitors.
"""

import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitor_control.gui.overlay_ctk import MonitorOverlayCTk


class MockCTkRoot:
    """Mock CTk root window."""
    def __init__(self):
        self.after_callbacks = []
        
    def after(self, delay, callback):
        # Execute immediately for testing
        callback()
        return len(self.after_callbacks)
    
    def after_cancel(self, timer_id):
        pass
    
    def geometry(self):
        return "800x600+100+100"
    
    def winfo_screenwidth(self):
        return 1920
    
    def winfo_screenheight(self):
        return 1080


class TestMultiMonitorGUI(unittest.TestCase):
    """Test that GUI operations respect monitor boundaries."""
    
    def setUp(self):
        """Set up test fixtures with 2 monitors."""
        # Create overlay instance without initializing GUI
        self.overlay = object.__new__(MonitorOverlayCTk)
        
        # Initialize required attributes
        self.overlay._root = MockCTkRoot()
        self.overlay._callbacks = {}
        self.overlay._slider_debounce_timers = {}
        self.overlay.COLORS = {
            'bg': '#1e1e1e',
            'bg_secondary': '#2d2d2d',
            'accent': '#ff6b00',
            'text': '#ffffff',
            'text_dim': '#888888',
            'border': '#404040',
        }
        self.overlay._updating_from_code = False
        
        # Mock monitor widgets for 2 monitors
        self.overlay._monitor_widgets = {
            1: {
                'brightness_slider': Mock(),
                'brightness_label': Mock(),
                'contrast_slider': Mock(),
                'contrast_label': Mock(),
                'sharpness_slider': Mock(),
                'sharpness_label': Mock(),
                'auto_brightness_btn': Mock(cget=Mock(return_value='#2d2d2d')),
                'auto_contrast_btn': Mock(cget=Mock(return_value='#2d2d2d')),
                'auto_profile_btn': Mock(cget=Mock(return_value='#2d2d2d')),
                'profile_widgets': {
                    'default': {
                        'auto_bright_switch': Mock(),
                        'auto_contrast_switch': Mock(),
                    },
                    'browser': {
                        'auto_bright_switch': Mock(),
                        'auto_contrast_switch': Mock(),
                    },
                },
            },
            2: {
                'brightness_slider': Mock(),
                'brightness_label': Mock(),
                'contrast_slider': Mock(),
                'contrast_label': Mock(),
                'sharpness_slider': Mock(),
                'sharpness_label': Mock(),
                'auto_brightness_btn': Mock(cget=Mock(return_value='#2d2d2d')),
                'auto_contrast_btn': Mock(cget=Mock(return_value='#2d2d2d')),
                'auto_profile_btn': Mock(cget=Mock(return_value='#2d2d2d')),
                'profile_widgets': {
                    'default': {
                        'auto_bright_switch': Mock(),
                        'auto_contrast_switch': Mock(),
                    },
                    'browser': {
                        'auto_bright_switch': Mock(),
                        'auto_contrast_switch': Mock(),
                    },
                },
            },
        }
        
        # Mock overview widgets
        self.overlay._overview_widgets = {
            1: {
                'brightness': Mock(),
                'contrast': Mock(),
                'sharpness': Mock(),
                'auto_brightness_btn': Mock(cget=Mock(return_value='#2d2d2d')),
                'auto_contrast_btn': Mock(cget=Mock(return_value='#2d2d2d')),
            },
            2: {
                'brightness': Mock(),
                'contrast': Mock(),
                'sharpness': Mock(),
                'auto_brightness_btn': Mock(cget=Mock(return_value='#2d2d2d')),
                'auto_contrast_btn': Mock(cget=Mock(return_value='#2d2d2d')),
            },
        }
    
    def reset_mocks(self):
        """Reset all mock call counts."""
        for display_num in [1, 2]:
            widgets = self.overlay._monitor_widgets[display_num]
            for w in widgets.values():
                if isinstance(w, Mock):
                    w.reset_mock()
                elif isinstance(w, dict):
                    for pw in w.values():
                        if isinstance(pw, dict):
                            for m in pw.values():
                                if isinstance(m, Mock):
                                    m.reset_mock()
    
    # === Test set_all_profiles_auto_brightness ===
    
    def test_set_all_profiles_auto_brightness_monitor1_only_affects_monitor1(self):
        """Setting auto brightness on monitor 1 should NOT affect monitor 2."""
        self.reset_mocks()
        
        # Act: Set auto brightness for monitor 1
        self.overlay.set_all_profiles_auto_brightness(True, display_num=1)
        
        # Assert: Monitor 1 switches should be updated
        mon1_default = self.overlay._monitor_widgets[1]['profile_widgets']['default']['auto_bright_switch']
        mon1_browser = self.overlay._monitor_widgets[1]['profile_widgets']['browser']['auto_bright_switch']
        self.assertTrue(mon1_default.select.called, "Monitor 1 default switch should be selected")
        self.assertTrue(mon1_browser.select.called, "Monitor 1 browser switch should be selected")
        
        # Assert: Monitor 2 switches should NOT be updated
        mon2_default = self.overlay._monitor_widgets[2]['profile_widgets']['default']['auto_bright_switch']
        mon2_browser = self.overlay._monitor_widgets[2]['profile_widgets']['browser']['auto_bright_switch']
        self.assertFalse(mon2_default.select.called, "Monitor 2 default switch should NOT be selected")
        self.assertFalse(mon2_browser.select.called, "Monitor 2 browser switch should NOT be selected")
    
    def test_set_all_profiles_auto_brightness_monitor2_only_affects_monitor2(self):
        """Setting auto brightness on monitor 2 should NOT affect monitor 1."""
        self.reset_mocks()
        
        # Act: Set auto brightness for monitor 2
        self.overlay.set_all_profiles_auto_brightness(True, display_num=2)
        
        # Assert: Monitor 2 switches should be updated
        mon2_default = self.overlay._monitor_widgets[2]['profile_widgets']['default']['auto_bright_switch']
        mon2_browser = self.overlay._monitor_widgets[2]['profile_widgets']['browser']['auto_bright_switch']
        self.assertTrue(mon2_default.select.called, "Monitor 2 default switch should be selected")
        self.assertTrue(mon2_browser.select.called, "Monitor 2 browser switch should be selected")
        
        # Assert: Monitor 1 switches should NOT be updated
        mon1_default = self.overlay._monitor_widgets[1]['profile_widgets']['default']['auto_bright_switch']
        mon1_browser = self.overlay._monitor_widgets[1]['profile_widgets']['browser']['auto_bright_switch']
        self.assertFalse(mon1_default.select.called, "Monitor 1 default switch should NOT be selected")
        self.assertFalse(mon1_browser.select.called, "Monitor 1 browser switch should NOT be selected")
    
    # === Test set_all_profiles_auto_contrast ===
    
    def test_set_all_profiles_auto_contrast_monitor1_only_affects_monitor1(self):
        """Setting auto contrast on monitor 1 should NOT affect monitor 2."""
        self.reset_mocks()
        
        # Act
        self.overlay.set_all_profiles_auto_contrast(True, display_num=1)
        
        # Assert
        mon1_default = self.overlay._monitor_widgets[1]['profile_widgets']['default']['auto_contrast_switch']
        mon2_default = self.overlay._monitor_widgets[2]['profile_widgets']['default']['auto_contrast_switch']
        self.assertTrue(mon1_default.select.called, "Monitor 1 switch should be selected")
        self.assertFalse(mon2_default.select.called, "Monitor 2 switch should NOT be selected")
    
    def test_set_all_profiles_auto_contrast_monitor2_only_affects_monitor2(self):
        """Setting auto contrast on monitor 2 should NOT affect monitor 1."""
        self.reset_mocks()
        
        # Act
        self.overlay.set_all_profiles_auto_contrast(True, display_num=2)
        
        # Assert
        mon1_default = self.overlay._monitor_widgets[1]['profile_widgets']['default']['auto_contrast_switch']
        mon2_default = self.overlay._monitor_widgets[2]['profile_widgets']['default']['auto_contrast_switch']
        self.assertFalse(mon1_default.select.called, "Monitor 1 switch should NOT be selected")
        self.assertTrue(mon2_default.select.called, "Monitor 2 switch should be selected")
    
    # === Test set_brightness ===
    
    def test_set_brightness_monitor1_only_affects_monitor1(self):
        """Setting brightness on monitor 1 should NOT affect monitor 2."""
        self.reset_mocks()
        
        # Act
        self.overlay.set_brightness(50, display_num=1)
        
        # Assert
        mon1_slider = self.overlay._monitor_widgets[1]['brightness_slider']
        mon2_slider = self.overlay._monitor_widgets[2]['brightness_slider']
        self.assertTrue(mon1_slider.set.called, "Monitor 1 slider should be set")
        self.assertFalse(mon2_slider.set.called, "Monitor 2 slider should NOT be set")
    
    def test_set_brightness_monitor2_only_affects_monitor2(self):
        """Setting brightness on monitor 2 should NOT affect monitor 1."""
        self.reset_mocks()
        
        # Act
        self.overlay.set_brightness(50, display_num=2)
        
        # Assert
        mon1_slider = self.overlay._monitor_widgets[1]['brightness_slider']
        mon2_slider = self.overlay._monitor_widgets[2]['brightness_slider']
        self.assertFalse(mon1_slider.set.called, "Monitor 1 slider should NOT be set")
        self.assertTrue(mon2_slider.set.called, "Monitor 2 slider should be set")
    
    # === Test set_contrast ===
    
    def test_set_contrast_monitor1_only_affects_monitor1(self):
        """Setting contrast on monitor 1 should NOT affect monitor 2."""
        self.reset_mocks()
        
        # Act
        self.overlay.set_contrast(50, display_num=1)
        
        # Assert
        mon1_slider = self.overlay._monitor_widgets[1]['contrast_slider']
        mon2_slider = self.overlay._monitor_widgets[2]['contrast_slider']
        self.assertTrue(mon1_slider.set.called, "Monitor 1 slider should be set")
        self.assertFalse(mon2_slider.set.called, "Monitor 2 slider should NOT be set")
    
    # === Test set_auto_brightness_state ===
    
    def test_set_auto_brightness_state_monitor1_only_affects_monitor1(self):
        """Setting auto brightness state on monitor 1 should NOT affect monitor 2."""
        self.reset_mocks()
        
        # Act
        self.overlay.set_auto_brightness_state(True, display_num=1)
        
        # Assert
        mon1_btn = self.overlay._monitor_widgets[1]['auto_brightness_btn']
        mon2_btn = self.overlay._monitor_widgets[2]['auto_brightness_btn']
        self.assertTrue(mon1_btn.configure.called, "Monitor 1 button should be configured")
        self.assertFalse(mon2_btn.configure.called, "Monitor 2 button should NOT be configured")
    
    # === Test set_auto_contrast_state ===
    
    def test_set_auto_contrast_state_monitor2_only_affects_monitor2(self):
        """Setting auto contrast state on monitor 2 should NOT affect monitor 1."""
        self.reset_mocks()
        
        # Act
        self.overlay.set_auto_contrast_state(True, display_num=2)
        
        # Assert
        mon1_btn = self.overlay._monitor_widgets[1]['auto_contrast_btn']
        mon2_btn = self.overlay._monitor_widgets[2]['auto_contrast_btn']
        self.assertFalse(mon1_btn.configure.called, "Monitor 1 button should NOT be configured")
        self.assertTrue(mon2_btn.configure.called, "Monitor 2 button should be configured")
    
    # === Test update_overview_settings ===
    
    def test_update_overview_settings_monitor1_only_affects_monitor1(self):
        """Updating overview settings for monitor 1 should NOT affect monitor 2."""
        self.reset_mocks()
        
        # Act
        self.overlay.update_overview_settings(1, brightness=50, contrast=60)
        
        # Assert
        mon1_brightness = self.overlay._overview_widgets[1]['brightness']
        mon2_brightness = self.overlay._overview_widgets[2]['brightness']
        self.assertTrue(mon1_brightness.configure.called, "Monitor 1 brightness should be configured")
        self.assertFalse(mon2_brightness.configure.called, "Monitor 2 brightness should NOT be configured")
    
    # === Test disable_feature ===
    
    def test_disable_feature_monitor1_only_affects_monitor1(self):
        """Disabling a feature on monitor 1 should NOT affect monitor 2."""
        self.reset_mocks()
        
        # Act
        self.overlay.disable_feature('sharpness', display_num=1)
        
        # Assert
        mon1_slider = self.overlay._monitor_widgets[1]['sharpness_slider']
        mon2_slider = self.overlay._monitor_widgets[2]['sharpness_slider']
        self.assertTrue(mon1_slider.configure.called, "Monitor 1 slider should be configured (disabled)")
        self.assertFalse(mon2_slider.configure.called, "Monitor 2 slider should NOT be configured")


class TestMonitorTabToggleFunctions(unittest.TestCase):
    """Test that monitor tab toggle functions use correct display_num."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.overlay = object.__new__(MonitorOverlayCTk)
        self.overlay._root = MockCTkRoot()
        self.callback_received = {}
        self.overlay.COLORS = {'accent': '#ff6b00', 'bg': '#1e1e1e'}
        self.overlay._auto_brightness_enabled = False
        self.overlay._auto_contrast_enabled = False
        self.overlay._auto_profile_enabled = False
        
        # Mock widgets for 2 monitors
        self.overlay._monitor_widgets = {
            1: {'auto_brightness_btn': Mock(cget=Mock(return_value='#1e1e1e'))},
            2: {'auto_brightness_btn': Mock(cget=Mock(return_value='#1e1e1e'))},
        }
        
        # Set up callback capture
        def capture_callback(name, *args):
            self.callback_received[name] = args
        
        self.overlay._invoke_callback = capture_callback
    
    def test_toggle_auto_brightness_for_tab_passes_correct_display_num(self):
        """Monitor tab auto brightness toggle should pass correct display_num."""
        # Simulate clicking monitor 2's auto brightness button
        self.overlay._toggle_auto_brightness_for_tab(2)
        
        # Check callback received correct display_num
        self.assertIn('toggle_auto_brightness', self.callback_received)
        args = self.callback_received['toggle_auto_brightness']
        # args[0] = enabled, args[1] = display_num
        self.assertEqual(args[1], 2, "display_num should be 2")
    
    def test_toggle_auto_contrast_for_tab_passes_correct_display_num(self):
        """Monitor tab auto contrast toggle should pass correct display_num."""
        self.overlay._monitor_widgets[1]['auto_contrast_btn'] = Mock(cget=Mock(return_value='#1e1e1e'))
        self.overlay._monitor_widgets[2]['auto_contrast_btn'] = Mock(cget=Mock(return_value='#1e1e1e'))
        
        # Simulate clicking monitor 2's auto contrast button
        self.overlay._toggle_auto_contrast_for_tab(2)
        
        # Check callback received correct display_num
        self.assertIn('toggle_auto_contrast', self.callback_received)
        args = self.callback_received['toggle_auto_contrast']
        self.assertEqual(args[1], 2, "display_num should be 2")
    
    def test_toggle_auto_profile_for_tab_passes_correct_display_num(self):
        """Monitor tab auto profile toggle should pass correct display_num."""
        self.overlay._monitor_widgets[1]['auto_profile_btn'] = Mock(cget=Mock(return_value='#1e1e1e'))
        self.overlay._monitor_widgets[2]['auto_profile_btn'] = Mock(cget=Mock(return_value='#1e1e1e'))
        
        # Simulate clicking monitor 2's auto profile button
        self.overlay._toggle_auto_profile_for_tab(2)
        
        # Check callback received correct display_num
        self.assertIn('toggle_auto_profile', self.callback_received)
        args = self.callback_received['toggle_auto_profile']
        self.assertEqual(args[1], 2, "display_num should be 2")


class TestCallbackDisplayNum(unittest.TestCase):
    """Test that callbacks pass display_num correctly."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create overlay instance without initializing GUI
        self.overlay = object.__new__(MonitorOverlayCTk)
        
        self.overlay._root = MockCTkRoot()
        self.callback_received = {}
        
        # Set up callback capture
        def capture_callback(name, *args):
            self.callback_received[name] = args
        
        self.overlay._invoke_callback = capture_callback
        self.overlay._slider_debounce_timers = {}
    
    def test_debounced_adaptive_callback_passes_display_num(self):
        """Debounced adaptive callback should include display_num."""
        # Act
        self.overlay._debounced_adaptive_callback('min_brightness', 30, display_num=2)
        
        # Assert
        self.assertIn('adaptive_setting_change', self.callback_received)
        args = self.callback_received['adaptive_setting_change']
        self.assertEqual(args[0], 'min_brightness')  # setting
        self.assertEqual(args[1], 30)  # value
        self.assertEqual(args[2], 2)  # display_num


def run_tests():
    """Run all tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestMultiMonitorGUI))
    suite.addTests(loader.loadTestsFromTestCase(TestMonitorTabToggleFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestCallbackDisplayNum))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result


if __name__ == '__main__':
    result = run_tests()
    sys.exit(0 if result.wasSuccessful() else 1)

