from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from core.run_stats import RunStats, next_quantity
from core.controller import run
from core.config import Config


class RunStatsTests(unittest.TestCase):
    def test_confirmed_costs_and_interrupted_batch(self):
        stats = RunStats()
        stats.begin_purchase(15)
        stats.confirm_purchase()
        stats.begin_dismantle(15)
        stats.confirm_dismantle()
        stats.begin_dismantle(2)
        self.assertEqual(stats.report()["total_cost"], 28500)
        self.assertEqual(stats.dismantled, 15)
        self.assertEqual(stats.dismantle_pending, 2)
        self.assertIn("미확정", stats.text())

    def test_existing_items_have_no_purchase_cost(self):
        stats = RunStats()
        stats.begin_dismantle(15)
        stats.confirm_dismantle()
        self.assertEqual(stats.report()["total_cost"], 4500)
        self.assertEqual(stats.report()["purchase_cost"], 0)

    def test_limit_never_rounds_up(self):
        self.assertEqual(next_quantity(15, 17, 15), 2)
        self.assertEqual(next_quantity(15, 17, 17), 0)
        self.assertEqual(next_quantity(15, 0, 500), 15)

    def test_full_loop_stops_exactly_at_limit(self):
        with ExitStack() as stack:
            mocks = {name: stack.enter_context(patch("core.controller." + name)) for name in (
                "Profile", "Detector", "GameWindow", "ScreenCapture", "InputController", "Session",
                "open_shop", "open_inventory", "slots", "targets", "purchase", "register", "dismantle")}
            mocks["Profile"].return_value.data = {"reviewed_quantities": [15, 2]}
            run(Config(quantity=15, live_input=True), Path("."), Mock(), Mock(), Mock(), max_dismantle=17)
            self.assertEqual([c.args[1] for c in mocks["purchase"].call_args_list], [15, 2])
            self.assertEqual([c.args[1] for c in mocks["dismantle"].call_args_list], [15, 2])
            mocks["open_shop"].assert_not_called()
            self.assertEqual(mocks["open_inventory"].call_count, 2)

    def test_purchase_failure_does_not_start_second_cycle(self):
        with ExitStack() as stack:
            mocks = {name: stack.enter_context(patch("core.controller." + name)) for name in (
                "Profile", "Detector", "GameWindow", "ScreenCapture", "InputController", "Session",
                "open_shop", "open_inventory", "slots", "targets", "purchase", "register", "dismantle")}
            mocks["Profile"].return_value.data = {"reviewed_quantities": [15]}
            mocks["purchase"].side_effect = RuntimeError("interrupted")
            with self.assertRaises(RuntimeError):
                run(Config(quantity=15, live_input=True), Path("."), Mock(), Mock(), Mock(), max_dismantle=30)
            mocks["purchase"].assert_called_once()
            mocks["dismantle"].assert_not_called()
