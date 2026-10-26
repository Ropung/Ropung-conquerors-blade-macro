import unittest
from unittest.mock import Mock, patch

from automation.dismantle_automation import dismantle
from core.state_machine import SafetyError


class DismantleFinishTests(unittest.TestCase):
    def test_confirm_then_empty_list_then_one_finish_click(self):
        session = Mock()
        session.detector.present.return_value = False
        events = []
        session.inputs.click.side_effect = lambda point: events.append("click")
        session.click.side_effect = lambda *args: events.append("confirm")
        session.wait_absent.side_effect = lambda *args: events.append("closed")
        def check_slots(s, count):
            events.append(f"slots:{count}")
        with patch("automation.dismantle_automation.slots", side_effect=check_slots), patch("automation.dismantle_automation.targets"):
            dismantle(session, 15, 0)
        self.assertEqual(events, ["slots:15", "click", "confirm", "closed", "slots:0", "click"])
        session.expect.assert_called_once_with("complete_popup", session.config.completion_timeout_seconds)

    def test_nonempty_list_prevents_finish_click(self):
        session = Mock()
        session.detector.present.return_value = False
        with patch("automation.dismantle_automation.slots", side_effect=[None, SafetyError("one left")]), patch("automation.dismantle_automation.targets"):
            with self.assertRaises(SafetyError):
                dismantle(session, 15, 0)
        self.assertEqual(session.inputs.click.call_count, 1)

    def test_popup_still_open_prevents_finish_click(self):
        session = Mock()
        session.detector.present.side_effect = [False, True]
        with patch("automation.dismantle_automation.slots"), patch("automation.dismantle_automation.targets"):
            with self.assertRaises(SafetyError):
                dismantle(session, 15, 0)
        self.assertEqual(session.inputs.click.call_count, 1)
