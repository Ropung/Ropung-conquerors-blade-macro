import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from core.config import Config
from core.image_detector import Profile, required_templates, valid_rect
from core.input_controller import InputController
from core.state_machine import RunControl, SafetyError, Stopped, batches


class SafetyTests(unittest.TestCase):
    def test_batches_conserve_quantity_and_slot_limit(self):
        for quantity in range(1, 21):
            with self.subTest(quantity=quantity):
                self.assertEqual(sum(batches(quantity)), quantity)
                self.assertTrue(all(1 <= count <= 15 for count in batches(quantity)))
        self.assertEqual(batches(20), [15, 5])

    def test_invalid_quantities_rejected(self):
        for value in (0, 21, -1, True, 1.5, "15"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Config(quantity=value).validate()

    def test_config_persists_quantity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Config(quantity=20).save(root)
            loaded = Config.load(root)
            self.assertEqual(loaded.quantity, 20)
            self.assertFalse(loaded.live_input)

    def test_stop_releases_paused_worker(self):
        control = RunControl()
        control.pause()
        done = threading.Event()

        def worker():
            try:
                control.checkpoint()
            except Stopped:
                done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        control.stop()
        self.assertTrue(done.wait(1))
        thread.join(1)

    def test_pause_blocks_until_resumed(self):
        control = RunControl()
        control.pause()
        done = threading.Event()
        thread = threading.Thread(target=lambda: (control.checkpoint(), done.set()), daemon=True)
        thread.start()
        self.assertFalse(done.wait(.05))
        control.resume()
        self.assertTrue(done.wait(1))
        thread.join(1)

    def test_no_input_in_read_only_mode(self):
        backend = Mock()
        with patch.dict("sys.modules", {"pyautogui": backend, "pydirectinput": backend}):
            inputs = InputController(Mock(origin=(0, 0)), RunControl())
            with self.assertRaises(SafetyError):
                inputs.key("f")
        backend.press.assert_not_called()
        backend.keyDown.assert_not_called()

    def test_key_is_held_briefly_and_released(self):
        backend = Mock()
        control = RunControl()
        with patch.dict("sys.modules", {"pyautogui": backend, "pydirectinput": backend}), patch.object(control, "delay") as delay:
            inputs = InputController(Mock(origin=(0, 0)), control, enabled=True)
            inputs.key("f")
        backend.keyDown.assert_called_once_with("f")
        backend.keyUp.assert_called_once_with("f")
        delay.assert_called_once_with(.12)

    def test_game_key_uses_scan_code_backend_only(self):
        mouse, scan = Mock(), Mock()
        control = RunControl()
        with patch.dict("sys.modules", {"pyautogui": mouse, "pydirectinput": scan}), patch.object(control, "delay"):
            inputs = InputController(Mock(origin=(0, 0)), control, enabled=True)
            inputs.key("f")
        scan.keyDown.assert_called_once_with("f")
        scan.keyUp.assert_called_once_with("f")
        mouse.keyDown.assert_not_called()
        mouse.keyUp.assert_not_called()
        self.assertTrue(scan.FAILSAFE)

    def test_stop_during_key_hold_always_releases_key(self):
        backend = Mock()
        control = RunControl()
        backend.keyDown.side_effect = lambda key: control.stop()
        with patch.dict("sys.modules", {"pyautogui": backend, "pydirectinput": backend}):
            inputs = InputController(Mock(origin=(0, 0)), control, enabled=True)
            with self.assertRaises(Stopped):
                inputs.key("f")
        backend.keyUp.assert_called_once_with("f")

    def test_stop_prevents_click(self):
        backend = Mock()
        control = RunControl()
        control.stop()
        with patch.dict("sys.modules", {"pyautogui": backend, "pydirectinput": backend}):
            inputs = InputController(Mock(origin=(0, 0)), control, enabled=True)
            with self.assertRaises(Stopped):
                inputs.click((100, 100))
        backend.click.assert_not_called()
        backend.moveTo.assert_not_called()

    def test_pause_invalidates_previously_recognized_point(self):
        backend = Mock()
        control = RunControl()
        with patch.dict("sys.modules", {"pyautogui": backend, "pydirectinput": backend}):
            inputs = InputController(Mock(origin=(0, 0)), control, enabled=True)
            control.pause()
            control.resume()
            with self.assertRaises(SafetyError):
                inputs.click((100, 100))
        backend.click.assert_not_called()

    def test_cost_templates_for_twenty(self):
        names = required_templates(20)
        self.assertIn("buy_cost_32000", names)
        self.assertIn("dismantle_cost_4500", names)
        self.assertIn("dismantle_cost_1500", names)

    def test_missing_profile_stops_before_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"resolution": [2560, 1440]}), encoding="utf-8")
            with self.assertRaises(SafetyError):
                Profile(path).validate(15)

    def test_regions_must_stay_in_game(self):
        self.assertTrue(valid_rect([0, 0, 2560, 1440]))
        for rect in ([-1, 0, 20, 20], [2550, 0, 20, 20], [0, 0, 0, 10]):
            self.assertFalse(valid_rect(rect))


if __name__ == "__main__":
    unittest.main()
