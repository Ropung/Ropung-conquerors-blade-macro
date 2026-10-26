import unittest
from unittest.mock import Mock

from automation.quantity_control import set_quantity
from core.state_machine import SafetyError


class QuantityControlTests(unittest.TestCase):
    def test_fifteen_uses_text_entry_after_confirming_default_one(self):
        session = Mock()
        session.detector.present.return_value = False
        set_quantity(session, 15)
        session.require.assert_any_call(session.frame.return_value, "buy_cost_1600")
        session.click.assert_called_once_with("quantity_field", "buy_popup")
        session.inputs.quantity.assert_called_once_with(15)
        session.expect_all.assert_called_once_with(("quantity_15", "buy_cost_24000"), timeout=2)
        session.inputs.click.assert_not_called()

    def test_already_correct_quantity_is_not_appended_again(self):
        session = Mock()
        session.detector.present.return_value = True
        set_quantity(session, 15)
        session.inputs.quantity.assert_not_called()

    def test_unknown_initial_quantity_prevents_input(self):
        session = Mock()
        session.detector.present.return_value = False
        session.require.side_effect = [None, SafetyError("not default one")]
        with self.assertRaises(SafetyError):
            set_quantity(session, 15)
        session.inputs.quantity.assert_not_called()
