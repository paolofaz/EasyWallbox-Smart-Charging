"""Offline domain tests for start/wait advice (all proposals virtual)."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest

BASE = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PACKAGE = "_ew_departure_tests"
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(BASE)]
sys.modules[PACKAGE] = pkg


def load(modname):
    spec = importlib.util.spec_from_file_location(
        PACKAGE + "." + modname, BASE / (modname + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = load("core")
departure = load("departure_policy")
T = datetime(2026, 11, 15, 18, tzinfo=timezone.utc)


def car(**changes):
    values = dict(
        session_id="s1", mode="AUTO", vehicle_id="kia", vehicle_ambiguous=False,
        charging=False, soc=70, soc_at=T, target_soc=80,
        departure_at=T + timedelta(hours=8),
        usable_capacity_kwh=77, ac_efficiency=.9, sustainable_kw=4,
        reserve_minutes=30,
    )
    values.update(changes)
    return core.SessionSnapshot(**values)


def house(kw, quality="ok"):
    return core.HouseSnapshot(kw, 0.2, quality)


def advice(now, s, h):
    return departure.advise_departure(now, s, core.plan(now, s), h)


class TestDepartureAdvice(unittest.TestCase):
    def test_wait_with_busy_house_and_ample_slack(self):
        a = advice(T, car(), house(2.2))
        self.assertEqual((a.action, a.reason), ("wait", "house_busy_slack_available"))
        self.assertEqual(a.next_check_at, T + timedelta(minutes=5))
        self.assertTrue(a.simulation_only)

    def test_quiet_house_suggests_start_now(self):
        a = advice(T, car(), house(0.25))
        self.assertEqual((a.action, a.reason), ("start_now", "house_quiet"))

    def test_wait_does_not_extend_past_latest_safe_start(self):
        s = car(departure_at=T + timedelta(hours=4))
        p = core.plan(T, s)
        latest = s.departure_at - timedelta(minutes=p.required_minutes + s.reserve_minutes)
        a = advice(T, s, house(2))
        self.assertEqual(a.next_check_at, min(latest, T + timedelta(minutes=5)))
        a2 = advice(latest, car(departure_at=s.departure_at, soc_at=latest), house(2))
        self.assertEqual(a2.action, "start_now")

    def test_urgency_vetoes_house_busy(self):
        s = car(departure_at=T + timedelta(hours=2))
        self.assertEqual(advice(T, s, house(2.4)).action, "start_now")

    def test_target_reached_does_not_start(self):
        self.assertEqual(advice(T, car(soc=80), house(0.1)).action, "complete")

    def test_manual_and_pause_are_respected(self):
        for mode, expected in [("MANUAL", "manual"), ("PAUSE", "paused")]:
            with self.subTest(mode=mode):
                self.assertEqual(advice(T, car(mode=mode), house(0)).action, expected)

    def test_unknown_car_does_not_start(self):
        self.assertEqual(advice(T, car(vehicle_id=None), house(0)).action, "inactive")
        self.assertEqual(
            advice(T, car(vehicle_ambiguous=True), house(0)).action,
            "insufficient_data",
        )

    def test_stale_soc_gives_no_start(self):
        s = car(soc_at=T - timedelta(hours=1))
        self.assertEqual(advice(T, s, house(0.2)).action, "insufficient_data")

    def test_missing_house_never_equated_to_quiet(self):
        a = advice(T, car(), house(None, "unavailable"))
        self.assertEqual(a.action, "insufficient_data")
        self.assertEqual(a.reason, "house_data_missing_or_incoherent")
        self.assertIsNotNone(a.next_check_at)

    def test_already_charging_not_another_start(self):
        a = advice(T, car(charging=True), house(2.2))
        self.assertEqual(a.action, "charging")
        self.assertIsNone(a.next_check_at)

    def test_deadline_crossed_does_not_jump_to_next_day(self):
        s = car(departure_at=T + timedelta(hours=1), soc_at=T)
        a = advice(T, s, house(2.2))
        self.assertEqual(a.action, "start_now")
        self.assertLess(a.latest_safe_start, s.departure_at)

    def test_time_naive_and_invalid_configs_rejected(self):
        with self.assertRaises(ValueError):
            departure.advise_departure(T.replace(tzinfo=None), car(), core.plan(T, car()), house(2))
        with self.assertRaises(ValueError):
            departure.advise_departure(T, car(), core.plan(T, car()), house(2), check_minutes=0)


if __name__ == "__main__":
    unittest.main()
