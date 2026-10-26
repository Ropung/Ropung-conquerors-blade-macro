from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from core.config import Config, write_json
from core.state_machine import RunControl, SafetyError
from core.step_test import NAVIGATION_STEPS, execute_step, run_step_test


class StepTests(unittest.TestCase):
    def test_f_test_is_one_key_and_one_expected_screen(self):
        session = Mock()
        execute_step(session, "npc", 15)
        self.assertEqual(session.mock_calls, [call.key("f", "shop_menu")])

    def test_item_select_verifies_identity_before_click(self):
        session = Mock()
        execute_step(session, "select", 15)
        names = [entry[0] for entry in session.mock_calls]
        self.assertLess(names.index("hover_target"), names.index("click"))
        session.click.assert_called_once_with("shop_target", "buy_button")

    def test_navigation_actions_never_confirm_purchase_or_dismantle(self):
        for key, _, _ in NAVIGATION_STEPS:
            with self.subTest(key=key):
                session = Mock()
                execute_step(session, key, 15)
                for entry in session.mock_calls:
                    if entry[0] == "click":
                        self.assertNotIn(entry.args[0], ("buy_confirm", "dismantle_button"))
                session.inputs.click.assert_not_called()

    def test_missing_template_prevents_all_game_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "calibration/profile.json", {"resolution": [2560, 1440], "templates": {}})
            with patch("core.step_test.InputController") as inputs, patch("core.step_test.GameWindow") as window:
                with self.assertRaises(SafetyError):
                    run_step_test(Config(), root, RunControl(), "npc", Mock())
                inputs.assert_not_called()
                window.assert_not_called()

    def test_unknown_action_cannot_send_input(self):
        session = Mock()
        with self.assertRaises(SafetyError):
            execute_step(session, "buy_confirm", 15)
        self.assertEqual(session.mock_calls, [])
