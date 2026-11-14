"""Offline tests of the simulation-only adaptive cap policy."""

import unittest
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "easywallbox_smart"
pkg = types.ModuleType("_ew_adaptive_test")
pkg.__path__ = [str(BASE)]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location(
    "_ew_adaptive_test.adaptive_policy", BASE / "adaptive_policy.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
PolicyConfig = module.PolicyConfig
SimulatedCapPolicy = module.SimulatedCapPolicy

T0 = datetime(2026, 11, 14, 21, 0, tzinfo=timezone.utc)


def t(minutes=0, seconds=0):
    return T0 + timedelta(minutes=minutes, seconds=seconds)


def make():
    return SimulatedCapPolicy(PolicyConfig(4.4, 5.0, 4.0))


def sample_range(policy, start_minute, end_minute, house=0.4):
    for m in range(start_minute, end_minute):
        for sec in (0, 20, 40):
            policy.observe(t(m, sec), house, house + policy.cap_kw)


class TestPolicy(unittest.TestCase):
    def test_no_charging_no_observation_or_proposal(self):
        p = make()
        self.assertFalse(p.observe(t(), 2.1, 5.1))
        self.assertEqual(p.window.count, 0)
        self.assertEqual(p.evaluate(t(), 120).action, "inactive")

    def test_one_peak_reduces_using_house_without_wallbox(self):
        p = make()
        p.set_charging(True)
        p.observe(t(), 2.1, 5.1)
        r = p.evaluate(t(), 120)
        self.assertEqual((r.action, r.cap_kw), ("reduce", 2.0))
        # Sustained high total readings are one episode, not many.
        p.observe(t(0, 20), 2.1, 5.1)
        self.assertEqual(p.evaluate(t(0, 20), 120).count_recent_peaks, 1)

    def test_departure_veto(self):
        p = make()
        p.set_charging(True)
        p.observe(t(), 2.1, 5.1)
        self.assertEqual(p.evaluate(t(), 10).reason, "planner_vetoes_extra_reduction")
        self.assertEqual(p.cap_kw, 4.0)

    def test_window_contains_recent_high_even_if_last_value_low(self):
        p = make()
        p.set_charging(True)
        p.observe(t(), 2.1, 5.1)
        p.evaluate(t(), 120)
        # High domestic consumption just before minute five, then 200 W.
        sample_range(p, 1, 4, 0.4)
        p.observe(t(4, 40), 2.5, 4.5)
        p.observe(t(5), 0.2, 2.2)
        sample_range(p, 6, 10, 0.2)
        self.assertEqual(p.evaluate(t(9, 40), 120).action, "hold")
        # That high reading has left the five-minute window by minute ten.
        self.assertEqual(p.evaluate(t(10), 120).action, "raise")

    def test_new_peak_slows_rise_without_a_burst_of_changes(self):
        p = make()
        p.set_charging(True)
        p.observe(t(), 2.1, 5.1)
        p.evaluate(t(), 120)
        sample_range(p, 1, 8, 0.4)
        first = p.evaluate(t(7, 40), 120)
        self.assertEqual(first.action, "raise")
        # Crossing back from below the alarm arms a second episode.
        p.observe(t(8), .4, 2.8)
        p.observe(t(8, 20), 2.1, 5.1)
        second = p.evaluate(t(8, 20), 120)
        self.assertEqual(second.count_recent_peaks, 2)
        self.assertEqual(second.action, "hold")  # No simulated burst within 2 min.
        sample_range(p, 9, 17, 0.4)
        self.assertEqual(p.evaluate(t(16, 40), 120).reason, "cooldown")

    def test_charging_end_clears_volatile_memory(self):
        p = make()
        p.set_charging(True)
        p.observe(t(), 2.1, 5.1)
        p.evaluate(t(), 120)
        p.set_charging(False)
        self.assertEqual(p.window.count, 0)
        self.assertEqual(p.cap_kw, 4.0)
        p.set_charging(True)
        self.assertEqual(p.evaluate(t(10), 120).reason, "no_optional_cap_active")

    def test_stale_window_cannot_raise(self):
        p = make()
        p.set_charging(True)
        p.observe(t(), 2.1, 5.1)
        p.evaluate(t(), 120)
        self.assertEqual(p.evaluate(t(10), 120).action, "insufficient_data")

    def test_invalid_configuration_rejected(self):
        for args in ((4.4, 4.0, 4), (4.4, 5.0, 1.0), (-1, 5, 4)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    PolicyConfig(*args)


if __name__ == "__main__":
    unittest.main()
