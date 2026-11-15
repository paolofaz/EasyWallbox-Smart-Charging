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

    def test_wallbox_reports_charge_but_no_verified_power_is_uncertain(self):
        s = car(sustainable_kw=None, wallbox_reports_charging=True, charging=False)
        a = advice(T, s, house(2.7))
        self.assertEqual(a.action, "insufficient_data")
        self.assertEqual(a.reason, "charging_report_without_ev_power")

    def test_no_measured_rate_does_not_justify_wait(self):
        s = car(sustainable_kw=None)
        a = advice(T, s, house(2.7))
        self.assertEqual(a.action, "start_now")
        self.assertEqual(a.reason, "no_observed_rate_do_not_wait")

    def test_stale_soc_and_no_rate_remain_insufficient(self):
        s = car(sustainable_kw=None, soc_at=T - timedelta(minutes=40))
        self.assertEqual(advice(T, s, house(0.4)).action, "insufficient_data")

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

    def test_explicit_charge_now_bypasses_domestic_wait(self):
        s = car(mode="CHARGE_NOW")
        result = advice(T, s, house(2.4))
        self.assertEqual(result.action, "start_now")
        self.assertEqual(result.reason, "explicit_charge_now_simulation_only")
        self.assertTrue(result.simulation_only)

    def test_explicit_charge_now_still_refuses_missing_soc(self):
        s = car(mode="CHARGE_NOW", soc=None)
        self.assertEqual(advice(T, s, house(0.2)).action, "insufficient_data")

    def test_restart_reconciliation_never_recommends_start(self):
        s = car(mode="RECONCILE")
        result = advice(T, s, house(0.2))
        self.assertEqual(result.action, "insufficient_data")
        self.assertEqual(result.reason, "explicit_mode_confirmation_required")

    def test_charge_now_does_not_restart_balancing_at_target_100(self):
        s = car(mode="CHARGE_NOW", soc=100, target_soc=100, charging=True)
        result = advice(T, s, house(2.0))
        self.assertEqual(result.action, "charging")
        self.assertEqual(result.reason, "vehicle_may_be_balancing")

    def test_charge_now_never_installs_optional_cap(self):
        s = car(mode="CHARGE_NOW", charging=True)
        state, proposal = core.evaluate(
            T, s, house(2.2), core.LimitSnapshot(4.0, 4.0)
        )
        self.assertEqual(state.mode, "NORMAL")
        self.assertEqual(proposal.action, "inactive")
        self.assertEqual(proposal.reason, "charge_now_disables_optional_cap")

    def test_time_naive_and_invalid_configs_rejected(self):
        with self.assertRaises(ValueError):
            departure.advise_departure(T.replace(tzinfo=None), car(), core.plan(T, car()), house(2))
        with self.assertRaises(ValueError):
            departure.advise_departure(T, car(), core.plan(T, car()), house(2), check_minutes=0)


if __name__ == "__main__":
    unittest.main()
