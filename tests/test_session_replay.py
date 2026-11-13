"""Offline verification for a whole-night replay, no live EV required."""

from dataclasses import replace
from datetime import timedelta
import importlib.util
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1] / (
    "custom_components/easywallbox_smart/session_replay.py"
)
spec = importlib.util.spec_from_file_location("_ew_session_replay_test", BASE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
run_night = module.run_night
example = module.kia_nov13_example


class TestSessionReplay(unittest.TestCase):
    def test_kia_night_compares_three_strategies(self):
        x = example()
        dpm = run_night(x, "dpm_only")
        restore = run_night(x, "manual_restore")
        forgotten = run_night(x, "manual_forget")
        self.assertLess(dpm.minutes_until_target, restore.minutes_until_target)
        self.assertLess(
            restore.minutes_until_target, forgotten.minutes_until_target
        )
        self.assertAlmostEqual(dpm.minutes_until_target, 518.14, delta=.2)
        self.assertAlmostEqual(restore.minutes_until_target, 535.58, delta=.2)
        self.assertAlmostEqual(forgotten.minutes_until_target, 658.43, delta=.2)
        self.assertEqual(dpm.ideal_dpm_clipped_minutes, 23)
        self.assertGreater(forgotten.shortfall_kwh_at_departure, .4)
        self.assertEqual(dpm.shortfall_kwh_at_departure, 0)
        self.assertTrue(all(
            r.no_commands_sent for r in (dpm, restore, forgotten)
        ))

    def test_higher_home_load_cannot_increase_energy_by_departure(self):
        x = example()
        base = run_night(x, "dpm_only")
        busy = run_night(replace(x, home_baseline_kw=2.0), "dpm_only")
        self.assertLessEqual(
            busy.battery_kwh_at_departure, base.battery_kwh_at_departure
        )

    def test_lower_efficiency_never_finishes_earlier(self):
        x = example()
        normal = run_night(x, "manual_forget")
        lower = run_night(replace(x, ac_efficiency=.75), "manual_forget")
        self.assertGreater(lower.minutes_until_target, normal.minutes_until_target)

    def test_limited_dpm_cannot_violate_global_limit_in_model(self):
        x = example()
        weak = run_night(replace(x, site_dpm_kw=2.5), "dpm_only")
        normal = run_night(x, "dpm_only")
        self.assertLessEqual(
            weak.battery_kwh_at_departure, normal.battery_kwh_at_departure
        )

    def test_zero_battery_needed_finishes_immediately(self):
        x = replace(example(), battery_needed_kwh=0)
        for mode in module.MODES:
            self.assertEqual(run_night(x, mode).target_reached_at, x.started)

    def test_invalid_parameters_are_rejected(self):
        x = example()
        variants = [
            replace(x, effective_low_kw=4.9),
            replace(x, ac_efficiency=0),
            replace(x, home_baseline_kw=-1),
            replace(x, battery_needed_kwh=float("nan")),
            replace(x, dishwasher_cycle_minutes=0),
            replace(x, departure=x.started-timedelta(minutes=5)),
        ]
        for bad in variants:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    run_night(bad, "dpm_only")

    def test_no_integration_or_network_api(self):
        text = BASE.read_text(encoding="utf-8")
        self.assertNotIn("homeassistant", text)
        self.assertNotIn("async_call", text)
        self.assertNotIn("requests.", text)


if __name__ == "__main__":
    unittest.main()
