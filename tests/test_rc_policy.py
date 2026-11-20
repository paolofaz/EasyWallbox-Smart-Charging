"""Deterministic RC policy regressions (no Home Assistant import, no devices)."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components/easywallbox_smart/rc_policy.py"
spec = importlib.util.spec_from_file_location("ew_rc_policy", SOURCE)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)
T = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)


def sample(minute, *, house=.1, current=4.0, margin=90, budget=10.0, **change):
    now = T + timedelta(minutes=minute)
    return replace(policy.Observation(
        at=now, session_id="synthetic",
        connected=True, charging=True, auto=True, trusted=True,
        house_kw=house, house_at=now, dpm_kw=4.4, current_kw=current,
        margin_minutes=margin, remaining_budget_kwh=budget,
        max_kw=4.0, boost_max_kw=4.2,
    ), **change)


def run_many(points, *, state=None):
    out=[]
    for params in points:
        obs = sample(**params)
        state, decision = policy.evaluate(obs, state)
        out.append((obs, state, decision))
    return out


class RCRules(unittest.TestCase):
    def test_real_disconnected_never_proposes_limit(self):
        s, d=policy.evaluate(sample(0, connected=False, house=2.5))
        self.assertEqual(d.action, "none")

    def test_manual_or_unconfirmed_charging_no_command(self):
        for changes in ({"auto": False}, {"charging": False},
                        {"trusted": False}, {"house_kw": None},
                        {"dpm_kw": None}, {"current_kw": None}):
            with self.subTest(changes):
                _, d=policy.evaluate(sample(0, **changes))
                self.assertEqual(d.action, "none")

    def test_strong_after_two_minutes_with_new_reports(self):
        out=run_many([{"minute": i,"house": 1.3} for i in range(3)])
        self.assertEqual([d.action for _,_,d in out], ["none","none","set_limit"])
        self.assertAlmostEqual(out[-1][2].target_kw, 2.8)

    def test_timer_cannot_forge_a_new_shelly_sample(self):
        st,d=policy.evaluate(sample(0,house=1.5))
        st,d=policy.evaluate(sample(1,house=1.5,house_at=T),st)
        self.assertEqual(d.reason, "waiting_for_new_shelly_report")
        st,d=policy.evaluate(sample(2,house=1.5,house_at=T),st)
        self.assertEqual(d.action, "none")

    def test_gap_does_not_count_as_continuous_evidence(self):
        st,_=policy.evaluate(sample(0,house=1.5))
        st,d=policy.evaluate(sample(5,house=1.5),st)
        self.assertNotEqual(d.action, "set_limit")

    def test_moderate_ten_of_twelve(self):
        out=run_many([{"minute":i,"house":.85} for i in range(12)])
        changes=[(obs.at, d.target_kw) for obs,st,d in out if d.action=="set_limit"]
        self.assertEqual(len(changes),1)
        self.assertEqual(changes[0][1],3.6)

    def test_no_moderate_with_urgent_target(self):
        out=run_many([{"minute":i,"house":.85,"margin":30} for i in range(14)])
        self.assertEqual(sum(d.action=="set_limit" for _,_,d in out),0)

    def test_budget_can_veto_strong_reduction(self):
        out=run_many([{"minute":i,"house":1.6,"budget":.01} for i in range(6)])
        self.assertFalse(any(d.action=="set_limit" for _,_,d in out))

    def test_boost_never_when_large_slack(self):
        out=run_many([{"minute":i,"house":.08,"margin":120} for i in range(31)])
        self.assertFalse(any(d.action=="set_limit" for _,_,d in out))

    def test_boost_after_fifteen_fresh_quiet_minutes_only_if_urgent(self):
        out=run_many([{"minute":i,"house":.08,"margin":55} for i in range(17)])
        changes=[d for _,_,d in out if d.action=="set_limit"]
        self.assertEqual(len(changes),1)
        self.assertAlmostEqual(changes[0].target_kw,4.2)

    def test_boost_allowed_even_with_negative_slack(self):
        out=run_many([{"minute":i,"house":.08,"margin":-10} for i in range(17)])
        self.assertEqual(out[-1][1].phase,"BOOST")

    def test_boost_exits_immediately_above_two_hundred_watts(self):
        out=run_many([{"minute":i,"house":.08,"margin":55} for i in range(16)])
        st=out[-1][1]
        st,d=policy.evaluate(sample(16,house=.21,current=4.2,margin=55),st)
        self.assertEqual((d.action,d.target_kw),("set_limit",4.0))

    def test_boost_hysteresis_does_not_exit_at_61_minutes(self):
        out=run_many([{"minute":i,"house":.08,"margin":55} for i in range(16)])
        st=out[-1][1]
        st,d=policy.evaluate(sample(16,house=.08,current=4.2,margin=61),st)
        self.assertNotEqual(d.action,"set_limit")

    def test_boost_releases_after_stable_75min_margin(self):
        out=run_many([{"minute":i,"house":.08,"margin":55} for i in range(16)])
        st=out[-1][1]
        decisions=[]
        for i in range(16,23):
            st,d=policy.evaluate(sample(i,house=.08,current=4.2,margin=77),st)
            decisions.append(d)
        self.assertIn(("set_limit",4.0),[(d.action,d.target_kw) for d in decisions])

    def test_same_session_limit_owner_fences_external_changes(self):
        out=run_many([{"minute":i,"house":1.2} for i in range(3)])
        st=out[-1][1]
        st,d=policy.evaluate(sample(3,house=1.2,current=4.0),st)
        self.assertEqual(d.reason,"limit_changed_externally_reconcile")

    def test_normal_restoration_after_fifteen_documented_minutes(self):
        out=run_many([{"minute":i,"house":1.2} for i in range(3)])
        st=out[-1][1]
        cap=out[-1][2].target_kw
        decisions=[]
        for minute in range(3,21):
            st,d=policy.evaluate(sample(minute,house=.08,current=cap),st)
            decisions.append(d)
            if d.action=="set_limit":
                break
        self.assertEqual((decisions[-1].action, decisions[-1].target_kw),
                         ("set_limit",4.0))

    def test_short_quiet_after_strong_does_not_restore(self):
        out=run_many([{"minute":i,"house":1.2} for i in range(3)])
        st=out[-1][1]
        cap=out[-1][2].target_kw
        for i in range(3,10):
            st,d=policy.evaluate(sample(i,house=.08,current=cap),st)
            self.assertNotEqual(d.action,"set_limit")

    def test_recheck_5_of_7_only_after_ten_minutes(self):
        out=run_many([{"minute":i,"house":1.2} for i in range(3)])
        st=out[-1][1]
        cap=out[-1][2].target_kw
        target=None
        for minute in range(3,17):
            st,d=policy.evaluate(sample(minute,house=2.2,current=cap),st)
            if d.action=="set_limit":
                target=d.target_kw
                break
        self.assertIsNotNone(target)
        self.assertAlmostEqual(target,cap-.4)

    def test_new_session_discards_previous_shelly_evidence(self):
        st,_=policy.evaluate(sample(0,house=1.5))
        st,d=policy.evaluate(sample(1,house=1.5,session_id="new"),st)
        self.assertEqual(d.action,"none")

    def test_configured_lower_baseline_restores_to_normal_not_limited(self):
        baseline = 3.6
        state = None
        reduced = None
        for m in range(4):
            observation = sample(m, house=1.6, current=(
                reduced if reduced is not None else baseline),
                max_kw=baseline, boost_max_kw=3.8)
            state, decision = policy.evaluate(observation, state)
            if decision.action == "set_limit":
                reduced = decision.target_kw
                self.assertEqual(state.phase, "LIMITED")
                break
        self.assertIsNotNone(reduced)
        for m in range(4, 24):
            observation = sample(m, house=0.08, current=reduced,
                                 max_kw=baseline, boost_max_kw=3.8)
            state, decision = policy.evaluate(observation, state)
            if decision.action == "set_limit":
                self.assertEqual((decision.target_kw, state.phase),
                                 (baseline, "NORMAL"))
                break
        else:
            self.fail("Did not restore a configured non-4.0 baseline")

    def test_no_electrical_or_io_imports_in_policy(self):
        source=SOURCE.read_text(encoding="utf-8")
        for forbidden in ("homeassistant", "services.async_call", "bleak",
                          "subprocess", "mqtt", "open(", "write_text("):
            self.assertNotIn(forbidden,source)


if __name__ == "__main__":
    unittest.main()
