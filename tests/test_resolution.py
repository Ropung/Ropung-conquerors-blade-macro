import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.config import Config, write_json, profile_path, app_root
from core.image_detector import Profile, valid_rect
from core.input_controller import InputController
from core.state_machine import RunControl, SafetyError
from core.screen_capture import GameWindow


class ResolutionTests(unittest.TestCase):
    def test_embedded_profile_used_without_external_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / 'embedded'
            with patch('core.config.resource_root', return_value=bundled):
                config = Config(width=1920, height=1080)
                expected = bundled / 'calibration/1920x1080/profile.json'
                self.assertEqual(profile_path(config, root / 'settings'), expected)
                local = root / 'settings' / config.calibration_profile
                write_json(local, {})
                self.assertEqual(profile_path(config, root / 'settings'), local)

    def test_release_settings_are_outside_executable(self):
        with patch('core.config.sys.frozen', True, create=True), patch.dict('core.config.os.environ', {'LOCALAPPDATA': 'C:/Example/AppData/Local'}):
            self.assertEqual(app_root(), Path('C:/Example/AppData/Local/ConquerorsBladeMacro'))

    def test_game_window_accepts_fhd_client_and_rejects_wrong_size(self):
        window = GameWindow.__new__(GameWindow)
        window.resolution = (1920, 1080)
        window.hwnd, window.origin = 123, None
        window.user32 = Mock()
        window.user32.IsWindow.return_value = True
        window.user32.IsIconic.return_value = False
        window.user32.GetForegroundWindow.return_value = 123

        def client_rect(hwnd, pointer):
            pointer._obj.right, pointer._obj.bottom = 1920, 1080
            return True

        def client_origin(hwnd, pointer):
            pointer._obj.x, pointer._obj.y = 20, 40
            return True

        window.user32.GetClientRect.side_effect = client_rect
        window.user32.ClientToScreen.side_effect = client_origin
        self.assertEqual(window.check(), {'left': 20, 'top': 40, 'width': 1920, 'height': 1080})
        window.resolution = (2560, 1440)
        with self.assertRaisesRegex(SafetyError, '1920×1080'):
            window.check()

    def test_resolution_roundtrip_and_separate_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(width=1920, height=1080, similarity=87.5)
            config.save(root)
            self.assertEqual(Config.load(root).resolution, (1920, 1080))
            self.assertEqual(Config.load(root).similarity, 87.5)
            self.assertEqual(config.calibration_profile, Path('calibration/1920x1080/profile.json'))
            self.assertEqual(Config().calibration_profile, Path('calibration/profile.json'))

    def test_mismatched_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            write_json(path, {'resolution': [1920, 1080]})
            self.assertEqual(Profile(path, (1920, 1080)).resolution, [1920, 1080])
            with self.assertRaises(SafetyError):
                Profile(path, (2560, 1440))

    def test_region_bounds_use_selected_resolution(self):
        self.assertTrue(valid_rect([0, 0, 3840, 2160], (3840, 2160)))
        self.assertFalse(valid_rect([1910, 0, 20, 20], (1920, 1080)))

    def test_input_uses_selected_bounds(self):
        backend = Mock()
        window = Mock(origin=(10, 20), resolution=(1920, 1080))
        with patch.dict('sys.modules', {'pyautogui': backend, 'pydirectinput': backend}):
            inputs = InputController(window, RunControl(), enabled=True)
            inputs.move((1919, 1079))
            backend.moveTo.assert_called_once_with(1929, 1099)
            with self.assertRaises(SafetyError):
                inputs.move((1920, 1079))

    def test_invalid_sizes_are_rejected(self):
        for width in (True, 0, -1, '1920', 20000):
            with self.assertRaises(ValueError):
                Config(width=width).validate()
