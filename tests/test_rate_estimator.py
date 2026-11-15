"""Pure automatic EV rate estimator regression tests."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest

FILE = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart/rate_estimator.py"
spec = importlib.util.spec_from_file_location("_ew_rate_estimator_tests", FILE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
T = datetime(2026, 11, 15, 19, tzinfo=timezone.utc)


def sample(minutes, kw, energy=None, duration=None, previous=None, session_id="car:1", ceiling=4.0, charging=True):
    return mod.estimate(T + timedelta(minutes=minutes), session_id, charging, kw,
                        energy, duration, ceiling, previous)


class TestAutoRate(unittest.TestCase):
    def test_first_charge_uses_shelly_instead_of_setpoint(self):
        s, out = sample(0, 2.0, 0.1, 2.0)
        self.assertEqual((out.kw, out.source), (2.0, "shelly_instant"))
        self.assertNotEqual(out.kw, 4.0)
        self.assertTrue(out.simulation_only)

    def test_counter_pair_after_30min_can_contribute(self):
        s, first = sample(0, 2.0, 0.8, 20)
        s, out = sample(10, 3.0, 1.7, 31, s)
        self.assertEqual(out.source, "mixed_session_mean")
        self.assertAlmostEqual(out.session_mean_kw, 1.7 * 60 / 31)
        self.assertGreater(out.kw, 3.0)

    def test_counter_under_30min_cannot_contribute(self):
        s, _ = sample(0, 2.0, 0.2, 10)
        s, out = sample(3, 1.6, 0.28, 13, s)
        self.assertEqual((out.kw, out.source), (1.6, "shelly_instant"))

    def test_counter_reset_is_not_cross_session_average(self):
        s, _ = sample(0, 3.0, 1.0, 30)
        s, _ = sample(10, 3.0, 1.5, 40, s)
        s, out = sample(11, 2.4, 0.1, 1, s)
        self.assertEqual((out.kw, out.source), (2.4, "shelly_instant"))
        self.assertEqual(s.counter_samples, 1)

    def test_no_charging_clears_previous_counters(self):
        s, _ = sample(0, 3.0, 1.0, 30)
        s, out = sample(1, 3.0, 1.2, 32, s, charging=False)
        self.assertIsNone(s.session_id)
        self.assertIsNone(out.kw)

    def test_connection_identity_change_clears_previous(self):
        s, _ = sample(0, 2.0, 1.0, 30)
        s, out = sample(1, 4.0, 0.7, 35, s, session_id="other:2")
        self.assertEqual(out.source, "shelly_instant")
        self.assertEqual(s.counter_samples, 1)

    def test_invalid_shelly_means_no_rate_even_with_energy(self):
        s, _ = sample(0, 3.0, 1.0, 30)
        s, out = sample(1, None, 1.1, 31, s)
        self.assertIsNone(out.kw)
        self.assertEqual(out.source, "unavailable")

    def test_invalid_counters_only_instant_survives(self):
        s, _ = sample(0, 3.0, float("nan"), 30)
        s, out = sample(31, 2.5, 0.9, -1, s)
        self.assertEqual(out.source, "shelly_instant")
        self.assertEqual(s.counter_samples, 0)

    def test_limit_is_ceiling_not_estimated_rate(self):
        _, out = sample(0, 4.0, None, None, ceiling=2.8)
        self.assertEqual(out.kw, 2.8)

    def test_when_disconnected_no_rate(self):
        _, out = sample(0, None, 3, 60, session_id=None)
        self.assertIsNone(out.kw)

    def test_clock_goes_back_no_estimate(self):
        s, _ = sample(5, 2.0, 1, 35)
        earlier = mod.estimate(T, "car:1", True, 3, 1.1, 36, 4, s)
        self.assertIsNone(earlier[1].kw)

    def test_no_external_effects(self):
        src = FILE.read_text()
        for forbidden in ("homeassistant", "async_call(", "write_text(", "open(", "bleak"):
            self.assertNotIn(forbidden, src)

if __name__ == "__main__":
    unittest.main()
