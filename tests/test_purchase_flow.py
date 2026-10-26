import unittest
from unittest.mock import Mock, patch

from automation.shop_automation import purchase
from core.state_machine import SafetyError


class PurchaseFlowTests(unittest.TestCase):
    def test_clicks_row_purchase_button_without_item_hover(self):
        session = Mock()
        session.detector.one.side_effect = lambda frame, name: name
        with patch("automation.shop_automation.open_shop"):
            purchase(session, 15)
        session.hover_target.assert_not_called()
        session.require.assert_any_call(session.expect.return_value, "shop_target", "buy_button")
        self.assertEqual([c.args[0] for c in session.inputs.click.call_args_list], ["buy_button", "buy_confirm"])
        self.assertFalse(any(c.args[0] == "shop_target" for c in session.click.call_args_list))

    def test_failed_item_or_button_check_prevents_click(self):
        session = Mock()
        session.require.side_effect = SafetyError("not recognized")
        with patch("automation.shop_automation.open_shop"), self.assertRaises(SafetyError):
            purchase(session, 15)
        session.inputs.click.assert_not_called()
