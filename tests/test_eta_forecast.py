"""Tests for advisory ETA only. Does not issue commands or alter policy."""
import unittest
from datetime import datetime, timedelta, timezone

import test_controller_smoke as rig

forecast = rig.load("planner_rate").estimate_charge_eta
NOW = datetime(2026, 11, 23, 21, 0, tzinfo=timezone.utc)


def seq(count, *, kw, ending=NOW, minutes=1):
    return [(ending-timedelta(minutes=i*minutes), kw) for i in reversed(range(count))]


class EtaForecast(unittest.TestCase):
    def test_first_minutes_are_provisional_but_not_unavailable(self):
        value = forecast(now=NOW, remaining_kwh=18, base_kw=4.0,
                         contracted_kw=4.4)
        self.assertIsNotNone(value)
        self.assertEqual(value.quality, "provvisoria")
        self.assertAlmostEqual(value.free_kw, 3.84, places=2)
        self.assertAlmostEqual(value.seconds, 3600*18/3.84, delta=3)

    def test_short_load_is_not_projected_through_entire_night(self):
        free = seq(31, kw=3.83)
        busy = seq(9, kw=1.65)
        e = forecast(now=NOW, remaining_kwh=18, base_kw=4.0,
                     contracted_kw=4.4, free_ev_samples=free,
                     recent_ev_samples=busy, energy_calibrated=True)
        self.assertEqual(e.quality, "consolidata")
        self.assertAlmostEqual(e.free_kw, 3.83, places=2)
        self.assertAlmostEqual(e.now_kw, 1.65, places=2)
        self.assertLess(e.seconds, 3600*6)  # No six-hour extrapolation at 1.65kW.
        self.assertGreater(e.seconds, e.earliest_seconds)

    def test_verified_dpm_pause_has_eta_not_none(self):
        e = forecast(now=NOW, remaining_kwh=8.0, base_kw=4.0,
                     contracted_kw=4.4, recent_ev_samples=seq(8, kw=0))
        self.assertIsNotNone(e)
        self.assertEqual(e.now_kw, 0.0)
        self.assertAlmostEqual(e.seconds, 1800+8*3600/3.84, delta=3)

    def test_missing_soc_or_invalid_power_never_fabricates(self):
        self.assertIsNone(forecast(now=NOW, remaining_kwh=-1,
                         base_kw=4.0, contracted_kw=4.4))
        self.assertIsNone(forecast(now=NOW, remaining_kwh=float("nan"),
                         base_kw=4.0, contracted_kw=4.4))
        self.assertIsNone(forecast(now=NOW, remaining_kwh=4,
                         base_kw=1.0, contracted_kw=4.4))

    def test_ignores_stale_and_incomplete_free_sample_sets(self):
        old = seq(30, kw=1.8, ending=NOW-timedelta(hours=6))
        e = forecast(now=NOW, remaining_kwh=12, base_kw=4.0,
                     contracted_kw=4.4, free_ev_samples=old)
        self.assertEqual(e.free_kw, 3.84)
        recent = seq(12, kw=2.7)
        e2 = forecast(now=NOW, remaining_kwh=12, base_kw=4.0,
                      contracted_kw=4.4, free_ev_samples=recent)
        self.assertEqual(e2.free_kw, 3.84)

    def test_different_contractual_limit_bounds_provisional_rate(self):
        e = forecast(now=NOW, remaining_kwh=12, base_kw=4.0,
                     contracted_kw=3.6)
        self.assertAlmostEqual(e.free_kw, 3.4)

    def test_partial_rate_does_not_change_margin_function(self):
        planner = rig.load("planner_rate")
        samples = seq(15, kw=2.5)
        before = planner.estimate_ac_kw(
            now=NOW, dpm_kw=4.4, ev_base_kw=4.0,
            house_samples=samples)
        _ = forecast(now=NOW, remaining_kwh=18, base_kw=4.0,
                     contracted_kw=4.4, recent_ev_samples=samples)
        after = planner.estimate_ac_kw(
            now=NOW, dpm_kw=4.4, ev_base_kw=4.0,
            house_samples=samples)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
