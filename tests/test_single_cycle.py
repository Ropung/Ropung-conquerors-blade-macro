from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from core.config import Config
from core.controller import run


class SingleCycleTests(unittest.TestCase):
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
