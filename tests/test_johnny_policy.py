"""Johnny v1 virtual-controller tests. Every EV load is synthetic."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import sys
import types
import unittest

COMP = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PKG = "_ew_johnny_v1_tests"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(COMP)]
sys.modules[PKG] = pkg
spec = importlib.util.spec_from_file_location(PKG + ".johnny_policy", COMP / "johnny_policy.py")
jp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = jp
spec.loader.exec_module(jp)
from importlib import import_module
core = import_module(PKG + ".core")

T = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)


def at(minute):
    return T + timedelta(minutes=minute)


def car(minute, *, soc=70, departure_hours=8, rate=4, mode="AUTO",
        charging=True):
    # Timestamp of SOC updated per EV poll (~15 minutes).
    return core.SessionSnapshot(
        session_id="synthetic-ev-1", mode=mode, vehicle_id="test-car",
        vehicle_ambiguous=False, charging=charging, soc=soc,
        soc_at=at((minute // 15) * 15), target_soc=80,
        departure_at=T + timedelta(hours=departure_hours),
        usable_capacity_kwh=77, ac_efficiency=.9, sustainable_kw=rate
    )


def house(minute, kw, *, quality="ok", observed=None):
    return core.HouseSnapshot(
        None, None, quality, sources_kw=(kw,),
        observed_at=at(minute) if observed is None else observed
    )


def limits(ev=4, dpm=4.4, requested=None):
    return core.LimitSnapshot(
        ev if requested is None else requested, ev, dpm_kw=dpm
    )


def step(previous, minute, kw, *, departure=8, rate=4, ev=4,
         dpm=4.4, soc=70, mode="AUTO", quality="ok",
         observed=None, requested=None, charging=True):
    return jp.evaluate(
        at(minute),
        car(minute, departure_hours=departure, rate=rate, soc=soc,
            mode=mode, charging=charging),
        house(minute, kw, quality=quality, observed=observed),
        limits(ev, dpm, requested), previous,
        core.Config(dpm_model_kw=4.4),
    )


def enter(*, departure=8, kw=1.4, ev=4):
    state = None
    results = []
    for minute in range(3):
        state, p = step(state, minute, kw, departure=departure, ev=ev)
        results.append(p)
    return state, results


class TestJohnnyV1(unittest.TestCase):
    def test_three_bands_follow_soc_and_departure(self):
        self.assertEqual(jp.margin_band(core.plan(at(0), car(0))), "wide")
        self.assertEqual(jp.margin_band(core.plan(at(0), car(0, departure_hours=4))), "medium")
        self.assertEqual(jp.margin_band(core.plan(at(0), car(0, departure_hours=2))), "urgent")
        self.assertEqual(jp.margin_band(core.plan(at(0), car(0, rate=None))), "unknown")

    def test_dynamic_pressure_at_4kw(self):
        state, out = enter()
        self.assertEqual([p.action for p in out], ["hold", "hold", "reduce"])
        self.assertEqual(state.mode, "LIMITED")
        self.assertAlmostEqual(state.cap_kw, 2.8)
        self.assertTrue(out[-1].simulation_only)

    def test_two_kw_ev_does_not_need_an_extra_ble_write(self):
        state, out = enter(ev=2)
        self.assertEqual(state.mode, "NORMAL")
        self.assertFalse(any(p.action == "reduce" for p in out))

    def test_small_dpm_pressure_has_no_change(self):
        state, out = enter(kw=.7)
        self.assertEqual(out[-1].reason, "dpm_pressure_not_significant")
        self.assertEqual(state.mode, "NORMAL")

    def test_medium_requires_three_minutes(self):
        state, out = enter(departure=4)
        self.assertEqual(state.mode, "NORMAL")
        self.assertFalse(any(p.action == "reduce" for p in out))
        state, p = step(state, 3, 1.4, departure=4)
        self.assertEqual(p.action, "reduce")

    def test_urgent_or_missing_rate_never_reduces(self):
        for dep, rate in ((2,4), (8,None)):
            with self.subTest(departure=dep,rate=rate):
                state = None
                for m in range(7):
                    state, p = step(state, m, 2., departure=dep, rate=rate)
                self.assertEqual(state.mode, "NORMAL")

    def test_stale_single_report_cannot_confirm_load(self):
        state = None
        for m in range(3):
            state, p = step(state, m, 1.4, observed=T)
        self.assertEqual(state.mode, "NORMAL")
        self.assertNotEqual(p.action, "reduce")

    def test_missing_sample_interrupts_confirmation(self):
        state, _ = step(None, 0, 1.4)
        state, p = step(state, 1, None, quality="unavailable")
        self.assertEqual(p.action, "insufficient_data")
        state, p = step(state, 2, 1.4)
        self.assertNotEqual(p.action, "reduce")

    def test_large_sample_gap_does_not_confirm(self):
        state, _ = step(None, 0, 1.4)
        state, p = step(state, 10, 1.4)
        self.assertNotEqual(p.action, "reduce")

    def test_quiet_18_minutes_wide_then_restore(self):
        state, _ = enter()
        results = []
        for m in range(3,22):
            state,p = step(state, m, .2)
            results.append(p)
        self.assertEqual([p.action for p in results].count("restore"), 1)
        self.assertEqual(results[-1].reason, "documented_quiet")
        self.assertEqual(state.mode, "NORMAL")

    def test_short_thermostat_off_cycles_do_not_oscillate(self):
        state, out = enter()
        for m in range(3,61):
            state,p = step(state,m,1.5 if m%7<3 else .25)
            out.append(p)
        self.assertEqual([p.action for p in out].count("reduce"),1)
        self.assertEqual([p.action for p in out].count("restore"),0)

    def test_missing_house_report_is_not_quiet(self):
        state,_=enter()
        for m in range(3,7):
            state,p=step(state,m,.2)
        state,p=step(state,7,None,quality="unavailable")
        self.assertEqual(p.reason,"house_data_not_trusted")
        state,p=step(state,21,.2)
        self.assertNotEqual(p.action,"restore")

    def test_planner_urgency_restores_even_without_house_data(self):
        state,_=enter()
        state,p=step(state,3,None,quality="unavailable",departure=2)
        self.assertEqual((p.action,p.reason),("restore","planner_needs_full_power"))

    def test_session_budget_is_locked_and_caps_end(self):
        state,_=enter()
        state=replace(state,locked_budget_kwh=.01)
        state,p=step(state,4,1.4)
        self.assertEqual((state.mode,p.action,p.reason),
                         ("NORMAL","restore","session_budget_exhausted"))
        self.assertGreater(state.spent_kwh_upper_bound,.01)

    def test_external_ev_limit_change_retires_virtual_cap(self):
        state,_=enter()
        state,p=step(state,3,1.4,ev=3.6)
        self.assertEqual((state.mode,p.action),("NORMAL","retire"))

    def test_dpm_change_retires_virtual_cap(self):
        state,_=enter()
        state,p=step(state,3,1.4,dpm=4.2)
        self.assertEqual((state.mode,p.action),("NORMAL","retire"))

    def test_missing_configured_dpm_has_no_new_cap(self):
        state=None
        for m in range(5):
            state,p=step(state,m,1.4,dpm=None)
        self.assertEqual(state.mode,"NORMAL")
        self.assertEqual(p.reason,"dpm_limit_unavailable")

    def test_manual_pause_and_no_real_charge_inactive(self):
        for mode,charging in [("PAUSE",True),("MANUAL",True),("AUTO",False)]:
            with self.subTest(mode=mode,charging=charging):
                state,p=step(None,0,1.4,mode=mode,charging=charging)
                self.assertEqual(p.action,"inactive")

    def test_failing_requested_vs_confirmed_is_not_assumed_effective(self):
        state,p=step(None,0,1.4,requested=3.)
        self.assertEqual(p.action,"insufficient_data")
        self.assertEqual(p.reason,"limit_unconfirmed")

    def test_not_an_actuator(self):
        source=(COMP/"johnny_policy.py").read_text()
        for forbidden in ("homeassistant", "async_call(", "bleak", "mqtt",
                          "requests", "write_text(", "async_update_entry"):
            self.assertNotIn(forbidden,source)


if __name__=="__main__":
    unittest.main()
