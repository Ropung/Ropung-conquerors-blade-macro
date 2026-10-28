import unittest
from unittest.mock import Mock

from automation.quantity_control import set_quantity
from core.state_machine import SafetyError


class QuantityControlTests(unittest.TestCase):
    def test_fifteen_enters_quantity_without_quantity_or_cost_recognition(self):
        session = Mock()
        session.detector.present.return_value = False
        set_quantity(session, 15)
        session.require.assert_called_once_with(session.frame.return_value, "buy_popup")
        session.click.assert_called_once_with("quantity_field", "buy_popup")
        session.inputs.quantity.assert_called_once_with(15)
        session.detector.present.assert_not_called()
        session.expect_all.assert_not_called()
        session.inputs.click.assert_not_called()

    def test_invalid_quantity_prevents_input(self):
        session = Mock()
        with self.assertRaises(SafetyError):
            set_quantity(session, 0)
        session.inputs.quantity.assert_not_called()

    def test_missing_popup_prevents_input(self):
        session = Mock()
        session.detector.present.return_value = False
        session.require.side_effect = SafetyError("popup missing")
        with self.assertRaises(SafetyError):
            set_quantity(session, 15)
        session.inputs.quantity.assert_not_called()
