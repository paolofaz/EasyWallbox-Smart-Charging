"""Offline tests: compare Fiat/Kia and reject unsafe planning assumptions."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest

DIR = Path(__file__).resolve().parents[1] / "custom_components" / "easywallbox_smart"
package = types.ModuleType("_planner_test_package")
package.__path__ = [str(DIR)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location("_planner_test_package.planner", DIR / "planner.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Request = module.Request
plan = module.plan
NOW = datetime(2026, 11, 13, 18, tzinfo=timezone.utc)


def inputs(kwh, **kw):
    args = dict(now=NOW, departure=NOW + timedelta(hours=14),
                battery_kwh=kwh, continuous_kw=4.4,
                house_reference_kw=.6, vehicle_cap_kw=6,
                efficiency=.9, reserve_minutes=45,
                preferred_start=NOW + timedelta(hours=7))
    args.update(kw)
    return Request(**args)


class TestPlanner(unittest.TestCase):
    def test_fiat_can_wait_until_one(self):
        result = plan(inputs(18.65))
        self.assertEqual(result.reason, "preferred_window_compatible")
        self.assertEqual(result.recommended_start, NOW + timedelta(hours=7))
        self.assertAlmostEqual(result.estimated_ev_kw, 3.8)

    def test_kia_cannot_wait_until_one(self):
        result = plan(inputs(39))
        self.assertEqual(result.reason, "preferred_window_too_late")
        self.assertEqual(result.recommended_start, NOW)

    def test_high_house_use_makes_deadline_risky(self):
        result = plan(inputs(39, house_reference_kw=2))
        self.assertEqual(result.status, "deadline_at_risk")

    def test_no_temporary_30_percent_budget(self):
        result = plan(inputs(8))
        self.assertLessEqual(result.estimated_ev_kw, 4.4)
        self.assertNotEqual(result.estimated_ev_kw, 5.2)

    def test_missing_or_invalid_inputs_do_not_invent_zero(self):
        for kw in (
            {"house_reference_kw": None}, {"battery_kwh": float("nan")},
            {"efficiency": 1.1}, {"continuous_kw": -1},
            {"departure": NOW}, {"reserve_minutes": -10},
        ):
            with self.subTest(kw=kw):
                self.assertEqual(plan(inputs(8, **kw)).status, "insufficient_data")

    def test_no_headroom(self):
        result = plan(inputs(8, house_reference_kw=4.4))
        self.assertEqual(result.reason, "no_continuous_headroom")

    def test_no_energy_is_already_estimated_reached(self):
        result = plan(inputs(0))
        self.assertEqual(result.status, "target_estimated_reached")
        self.assertEqual(result.required_hours, 0)

    def test_without_preference_starts_conservatively(self):
        result = plan(inputs(8, preferred_start=None))
        self.assertEqual(result.reason, "start_now")


if __name__ == "__main__":
    unittest.main()
