import unittest
from unittest.mock import Mock

from core.controller import Session
from core.state_machine import SafetyError


class MenuClickTests(unittest.TestCase):
    def session(self):
        session = Session.__new__(Session)
        session.frame = Mock()
        session.detector = Mock()
        session.detector.present.return_value = False
        session.inputs = Mock()
        session.expect = Mock()
        session.log = Mock()
        return session

    def test_retries_missed_menu_click(self):
        session = self.session()
        session.expect.side_effect = [SafetyError("화면 확인 시간 초과: shop_open"), None]
        session.click("shop_menu", "shop_open")
        self.assertEqual(session.inputs.click_ui.call_count, 2)

    def test_foreground_failure_does_not_retry(self):
        session = self.session()
        session.expect.side_effect = SafetyError("게임이 활성 창이 아니므로 중지합니다.")
        with self.assertRaises(SafetyError):
            session.click("shop_menu", "shop_open")
        session.inputs.click_ui.assert_called_once()

    def test_open_shop_is_never_clicked_again(self):
        session = self.session()
        session.detector.present.return_value = True
        session.click("shop_menu", "shop_open")
        session.inputs.click_ui.assert_not_called()
