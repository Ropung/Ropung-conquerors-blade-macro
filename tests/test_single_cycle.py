from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from core.config import Config
from core.controller import run, run_dismantle_once
from core.state_machine import SafetyError


class SingleCycleTests(unittest.TestCase):
    def test_existing_items_test_never_purchases(self):
        with ExitStack() as stack:
            mocks = {name: stack.enter_context(patch("core.controller." + name)) for name in (
                "Profile", "Detector", "GameWindow", "ScreenCapture", "InputController", "Session",
                "slots", "slot_count", "targets", "purchase", "register", "dismantle")}
            mocks["Profile"].return_value.templates = {}
            mocks["slot_count"].return_value = 15
            run_dismantle_once(Config(quantity=15, live_input=True), Path("."), Mock(), Mock(), Mock())
            mocks["purchase"].assert_not_called()
            mocks["register"].assert_not_called()
            mocks["dismantle"].assert_called_once_with(mocks["Session"].return_value, 15, 0)
            mocks["ScreenCapture"].return_value.close.assert_called_once()

    def test_dismantle_only_requires_explicit_live_input(self):
        with patch("core.controller.InputController") as inputs:
            with self.assertRaises(SafetyError):
                run_dismantle_once(Config(quantity=15), Path("."), Mock(), Mock(), Mock())
            inputs.assert_not_called()

    def test_single_cycle_never_starts_second_purchase(self):
        with ExitStack() as stack:
            mocks = {name: stack.enter_context(patch("core.controller." + name)) for name in (
                "Profile", "Detector", "GameWindow", "ScreenCapture", "InputController", "Session",
                "open_shop", "open_inventory", "slots", "targets", "purchase", "register", "dismantle")}
            mocks["Profile"].return_value.data = {"reviewed_quantities": [1]}
            run(Config(quantity=1, live_input=True), Path("."), Mock(), Mock(), Mock(), single_cycle=True)
            mocks["purchase"].assert_called_once()
            mocks["register"].assert_called_once()
            mocks["dismantle"].assert_called_once()
            mocks["ScreenCapture"].return_value.close.assert_called_once()
