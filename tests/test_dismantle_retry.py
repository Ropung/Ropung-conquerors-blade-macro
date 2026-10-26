import unittest
from unittest.mock import Mock, patch

from automation.dismantle_automation import dismantle, wait_for_completion
from core.state_machine import SafetyError


class DismantleFinishTests(unittest.TestCase):
    def wait_session(self, popup_after_retry):
        session = Mock()
        session.config.completion_timeout_seconds = 5
        clock = [0.0]
        session.control.delay.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        def present(frame, name):
            if name == "complete_popup":
                return popup_after_retry and session.inputs.click.call_count > 0
            return True
        session.detector.present.side_effect = present
        return session, clock

    def test_lone_item_without_popup_gets_one_retry_then_completion(self):
        session, clock = self.wait_session(True)
        with patch("automation.dismantle_automation.time.monotonic", side_effect=lambda: clock[0]), patch("automation.dismantle_automation.slot_count", return_value=1), patch("automation.dismantle_automation.slots"), patch("automation.dismantle_automation.targets"):
            wait_for_completion(session, 0)
        session.inputs.click.assert_called_once()
        session.require.assert_called_with(session.frame.return_value, "dismantle_panel", "dismantle_cost_300")
        session.expect.assert_called_once_with("complete_popup", 5)

    def test_retry_cannot_repeat_indefinitely(self):
        session, clock = self.wait_session(False)
        with patch("automation.dismantle_automation.time.monotonic", side_effect=lambda: clock[0]), patch("automation.dismantle_automation.slot_count", return_value=1), patch("automation.dismantle_automation.slots"), patch("automation.dismantle_automation.targets"):
            with self.assertRaises(SafetyError):
                wait_for_completion(session, 0)
        session.inputs.click.assert_called_once()

    def test_more_than_one_remaining_never_triggers_retry(self):
        session, clock = self.wait_session(False)
        with patch("automation.dismantle_automation.time.monotonic", side_effect=lambda: clock[0]), patch("automation.dismantle_automation.slot_count", return_value=2):
            with self.assertRaises(SafetyError):
                wait_for_completion(session, 0)
        session.inputs.click.assert_not_called()

    def test_confirm_then_empty_list_then_one_finish_click(self):
        session = Mock()
        session.detector.present.return_value = False
        events = []
        session.inputs.click.side_effect = lambda point: events.append("click")
        session.click.side_effect = lambda *args: events.append("confirm")
        session.wait_absent.side_effect = lambda *args: events.append("closed")
        def check_slots(s, count):
            events.append(f"slots:{count}")
        with patch("automation.dismantle_automation.slots", side_effect=check_slots), patch("automation.dismantle_automation.targets"), patch("automation.dismantle_automation.wait_for_completion"):
            dismantle(session, 15, 0)
        self.assertEqual(events, ["slots:15", "click", "confirm", "closed", "slots:0", "click"])
        session.click.assert_called_once_with("complete_confirm", "dismantle_panel")

    def test_nonempty_list_prevents_finish_click(self):
        session = Mock()
        session.detector.present.return_value = False
        with patch("automation.dismantle_automation.slots", side_effect=[None, SafetyError("one left")]), patch("automation.dismantle_automation.targets"), patch("automation.dismantle_automation.wait_for_completion"):
            with self.assertRaises(SafetyError):
                dismantle(session, 15, 0)
        self.assertEqual(session.inputs.click.call_count, 1)

    def test_popup_still_open_prevents_finish_click(self):
        session = Mock()
        session.detector.present.side_effect = [False, True]
        with patch("automation.dismantle_automation.slots"), patch("automation.dismantle_automation.targets"), patch("automation.dismantle_automation.wait_for_completion"):
            with self.assertRaises(SafetyError):
                dismantle(session, 15, 0)
        self.assertEqual(session.inputs.click.call_count, 1)
