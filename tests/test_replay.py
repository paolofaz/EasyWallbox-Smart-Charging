"""Pure offline replay tests. Real household data is not checked into GitHub."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "easywallbox_smart"
pkg = types.ModuleType("_ew_replay_test")
pkg.__path__ = [str(BASE)]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location("_ew_replay_test.replay", BASE / "replay.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
PowerPoint, replay = module.PowerPoint, module.replay
T0 = datetime(2026, 11, 12, 22, tzinfo=timezone.utc)


class TestReplay(unittest.TestCase):
    def test_short_surge_requires_theoretical_dpm_limit(self):
        # 10 minutes home low, 10 minutes home high, 10 minutes home low.
        samples = [
            PowerPoint(T0, .1),
            PowerPoint(T0 + timedelta(minutes=10), 2.1),
            PowerPoint(T0 + timedelta(minutes=20), .1),
        ]
        results = [
            replay(samples, T0, T0 + timedelta(minutes=30),
                   site_limit_kw=4.4, other_home_kw=.3,
                   requested_ev_kw=p, stale_after_seconds=1200)
            for p in (3.8, 3.0, 1.8)
        ]
        self.assertEqual([r.theoretical_limited_minutes for r in results],
                         [10, 10, 0])
        self.assertEqual([r.theoretical_limit_periods for r in results], [1, 1, 0])
        self.assertGreater(results[0].theoretical_ev_kwh,
                           results[1].theoretical_ev_kwh)
        self.assertGreater(results[1].theoretical_ev_kwh,
                           results[2].theoretical_ev_kwh)

    def test_unknown_is_not_treated_as_zero(self):
        points = [PowerPoint(T0, .2),
                  PowerPoint(T0 + timedelta(minutes=5), None),
                  PowerPoint(T0 + timedelta(minutes=10), .2)]
        r = replay(points, T0, T0 + timedelta(minutes=15),
                   site_limit_kw=4.4, other_home_kw=0,
                   requested_ev_kw=3, stale_after_seconds=1200)
        self.assertEqual(r.valid_minutes, 10)
        self.assertEqual(r.missing_minutes, 5)

    def test_stale_time_is_excluded(self):
        points = [PowerPoint(T0, .2)]
        r = replay(points, T0, T0 + timedelta(minutes=12),
                   site_limit_kw=4.4, other_home_kw=.1,
                   requested_ev_kw=2, stale_after_seconds=120)
        self.assertEqual(r.valid_minutes, 2)
        self.assertEqual(r.missing_minutes, 10)

    def test_invalid_samples_and_power(self):
        points = [PowerPoint(T0, 0.1)]
        for override in ({"site_limit_kw": 0}, {"other_home_kw": -1},
                         {"requested_ev_kw": float("nan")}):
            args = dict(site_limit_kw=4.4, other_home_kw=.3, requested_ev_kw=3)
            args.update(override)
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    replay(points, T0, T0 + timedelta(minutes=10), **args)


if __name__ == "__main__":
    unittest.main()
