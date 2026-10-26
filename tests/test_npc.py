import unittest
from unittest.mock import Mock, call

from automation.npc_interaction import open_shop
from core.image_detector import required_templates


class NpcTests(unittest.TestCase):
    def test_f_is_first_action_then_menu_is_verified(self):
        session = Mock()
        open_shop(session)
        self.assertEqual(session.mock_calls, [
            call.key("f", "shop_menu"),
            call.click("shop_menu", "shop_open"),
            call.click("page_two", "page_two_active"),
        ])

    def test_interaction_prompt_is_not_required(self):
        self.assertNotIn("npc_ready", required_templates(15))
