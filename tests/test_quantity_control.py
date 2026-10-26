import unittest
from unittest.mock import Mock

from automation.quantity_control import set_quantity
from core.state_machine import SafetyError


class QuantityControlTests(unittest.TestCase):
    def test_one_to_fifteen_uses_fourteen_plus_clicks_and_no_keys(self):
        session = Mock()
        session.detector.present.return_value = True
        session.detector.one.side_effect = lambda frame, name: name
        set_quantity(session, 15)
        self.assertEqual(session.inputs.click.call_count, 14)
        self.assertEqual({c.args[0] for c in session.inputs.click.call_args_list}, {"quantity_plus"})
        session.inputs.key.assert_not_called()
        session.inputs.quantity.assert_not_called()
        session.expect_all.assert_called_once_with(("quantity_15", "buy_cost_24000"), timeout=2)

    def test_unknown_initial_quantity_is_reset_before_increment(self):
        session = Mock()
        session.detector.present.return_value = False
        session.detector.one.side_effect = lambda frame, name: name
        set_quantity(session, 15)
        clicks = [c.args[0] for c in session.inputs.click.call_args_list]
        self.assertEqual(clicks, ["quantity_minus"] * 19 + ["quantity_plus"] * 14)

    def test_missing_popup_prevents_any_input(self):
        session = Mock()
        session.require.side_effect = SafetyError("popup missing")
        with self.assertRaises(SafetyError):
            set_quantity(session, 15)
        session.inputs.click.assert_not_called()
