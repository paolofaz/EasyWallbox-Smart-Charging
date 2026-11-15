"""Synthetic hairdryer replay: test *proposed* policy, not device control.

The numbers below are illustrative test fixtures, NOT household history.
Observed household power must never be committed to the public repository.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest

SRC=Path(__file__).resolve().parents[1]/"custom_components/easywallbox_smart/core.py"
spec=importlib.util.spec_from_file_location("_ew_hairdry_core",SRC)
core=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=core
spec.loader.exec_module(core)
T=datetime(2026,11,15,20,0,tzinfo=timezone.utc)


def hypothetical_ev(minute, *, soc=70, measured_kw=4):
    return core.SessionSnapshot(
        session_id="synthetic-session",mode="AUTO",
        vehicle_id="hypothetical-ev",vehicle_ambiguous=False,charging=True,
        soc=soc,soc_at=T+timedelta(minutes=(minute//15)*15),
        target_soc=80,departure_at=T+timedelta(hours=8),
        usable_capacity_kwh=77,ac_efficiency=.9,
        sustainable_kw=measured_kw, reserve_minutes=30,
    )


def playback(*, soc=70,trigger=1.5,measured_kw=4):
    # Distinct stages: quiet house, long warm-up, intermittent hairdryer use.
    # Not timestamps or exact readings from the user's household.
    samples=[
        (0,.3), (20,1.36),(21,1.35),(22,1.34),(23,1.34),
        (24,.22),(25,1.05),(26,.22),(27,1.05),(28,.22),
        (29,1.05),(30,.22),
    ]
    state=None
    outcomes=[]
    cfg=replace(core.Config(),trigger_kw=trigger)
    for m,kw in samples:
        state,p=core.evaluate(
            T+timedelta(minutes=m),
            hypothetical_ev(m,soc=soc,measured_kw=measured_kw),
            core.HouseSnapshot(None,None,"ok",sources_kw=(kw,)),
            core.LimitSnapshot(4.,4.),state,cfg,
        )
        outcomes.append((m,p))
    return outcomes


class TestHairdryerCandidate(unittest.TestCase):
    def test_current_threshold_misses_sustained_sub_threshold_load(self):
        out=playback()
        self.assertFalse(any(p.action=="reduce" for _,p in out))
        self.assertTrue(all(p.simulation_only for _,p in out))

    def test_lower_trigger_can_propose_one_long_stable_cap(self):
        out=playback(trigger=1.3)
        reductions=[(m,p) for m,p in out if p.action=="reduce"]
        self.assertEqual(len(reductions),1)
        self.assertEqual(reductions[0][0],21)
        self.assertAlmostEqual(reductions[0][1].proposed_cap_kw,2.4)
        self.assertFalse(any(p.action=="restore" for _,p in out))
        self.assertEqual(out[-1][1].state,"LIMITED")

    def test_low_slack_vetoes_reduction_even_with_lower_trigger(self):
        out=playback(soc=40,trigger=1.3)
        self.assertFalse(any(p.action=="reduce" for _,p in out))
        self.assertTrue(all(p.reason=="at_risk" or p.reason=="house_not_busy"
                            for _,p in out))

    def test_unknown_rate_never_authorizes_candidate_cap(self):
        out=playback(trigger=1.3,measured_kw=None)
        self.assertFalse(any(p.action=="reduce" for _,p in out))
        self.assertTrue(all(p.reason=="power_estimate_unavailable"
                            for _,p in out))

if __name__=="__main__":
    unittest.main()
