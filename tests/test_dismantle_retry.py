import unittest
from unittest.mock import Mock, patch

from automation.dismantle_automation import dismantle, wait_complete
from core.state_machine import SafetyError


class DismantleRetryTests(unittest.TestCase):
    def run_case(self, counts, completed):
        session = Mock()
        session.detector.present.return_value = False
        with patch("automation.dismantle_automation.slots"), patch("automation.dismantle_automation.targets"), patch("automation.dismantle_automation.slot_count", side_effect=counts), patch("automation.dismantle_automation.wait_complete", side_effect=completed):
            dismantle(session, 15, 0)
        return session

    def test_normal_completion_clicks_once(self):
        session = self.run_case([0], [True])
        self.assertEqual(session.inputs.click.call_count, 1)

    def test_one_left_before_popup_clicks_again(self):
        session = self.run_case([1, 0], [False, True])
        self.assertEqual(session.inputs.click.call_count, 2)
        self.assertEqual(session.click.call_count, 1)
        session.require.assert_any_call(session.frame.return_value, "dismantle_panel", "dismantle_cost_300")

    def test_one_left_after_popup_clicks_again(self):
        session = self.run_case([1, 0], [True, True])
        self.assertEqual(session.inputs.click.call_count, 2)
        self.assertEqual(session.click.call_count, 2)

    def test_remaining_more_than_one_stops(self):
        with self.assertRaises(SafetyError):
            self.run_case([2], [True])

    def test_retry_is_limited_to_once(self):
        with self.assertRaises(SafetyError):
            self.run_case([1, 1], [False, True])

    def test_lone_item_must_persist_before_retry(self):
        session = Mock()
        session.config.completion_timeout_seconds = 90
        session.detector.present.side_effect = lambda frame, name: name != "complete_popup"
        with patch("automation.dismantle_automation.slot_count", return_value=1), patch("automation.dismantle_automation.time.monotonic", side_effect=[0, .1, .2, .3, 1, 1.1, 1.8, 1.9]):
            self.assertFalse(wait_complete(session, True))
        session.expect.assert_not_called()
