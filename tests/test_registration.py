from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from automation.inventory_automation import register
from core.state_machine import SafetyError


class RegistrationTests(unittest.TestCase):
    def test_identical_batch_checks_tooltip_once_and_final_count(self):
        session = Mock()
        session.detector.images = {"inventory_target": SimpleNamespace(shape=(77, 62, 3))}
        session.detector.find_all.side_effect = [[(100, 100)], [], [(200, 100)], [], [(300, 100)], []]
        with patch("automation.inventory_automation.slots") as slots, patch("automation.inventory_automation.targets") as targets:
            targets.return_value = [(300, 100), (100, 100), (200, 100)]
            register(session, 3, 3)
            self.assertEqual(slots.call_count, 2)
            targets.assert_any_call(session, 0)
        session.expect_all.assert_called_once()
        self.assertEqual(session.inputs.click.call_count, 3)

    def test_changed_icon_prevents_click_and_batch_completion(self):
        session = Mock()
        session.detector.images = {"inventory_target": SimpleNamespace(shape=(77, 62, 3))}
        session.detector.find_all.return_value = []
        with patch("automation.inventory_automation.slots"), patch("automation.inventory_automation.targets", return_value=[(100, 100)]):
            with self.assertRaises(SafetyError):
                register(session, 1, 1)
        session.inputs.click.assert_not_called()

    def test_missed_click_retries_only_the_remaining_item(self):
        session = Mock()
        session.detector.images = {"inventory_target": SimpleNamespace(shape=(77, 62, 3))}
        session.detector.find_all.side_effect = [[(100, 100)], [(100, 100)], [(100, 100)], []]
        with patch("automation.inventory_automation.slots"), patch("automation.inventory_automation.targets", return_value=[(100, 100)]):
            register(session, 1, 1)
        self.assertEqual(session.inputs.click.call_count, 2)

    def test_repeated_missed_click_stops_before_completion(self):
        session = Mock()
        session.detector.images = {"inventory_target": SimpleNamespace(shape=(77, 62, 3))}
        session.detector.find_all.return_value = [(100, 100)]
        with patch("automation.inventory_automation.slots") as slots, patch("automation.inventory_automation.targets", return_value=[(100, 100)]):
            with self.assertRaises(SafetyError):
                register(session, 1, 1)
        self.assertEqual(session.inputs.click.call_count, 2)
        self.assertEqual(slots.call_count, 1)
