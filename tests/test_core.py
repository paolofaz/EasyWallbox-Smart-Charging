"""Offline contract tests for deterministic simulation-only core."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / 'custom_components/easywallbox_smart/core.py'
spec = importlib.util.spec_from_file_location('easywallbox_test_core', SRC)
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)

T = datetime(2026, 11, 15, 18, 0, tzinfo=timezone.utc)


def at(m): return T + timedelta(minutes=m)


def session(**overrides):
    d = dict(session_id='s1', mode='AUTO', vehicle_id='kia', vehicle_ambiguous=False,
             charging=True, soc=40, soc_at=T, target_soc=80, departure_at=at(720),
             usable_capacity_kwh=77, ac_efficiency=.9, sustainable_kw=4, reserve_minutes=30)
    d.update(overrides)
    return core.SessionSnapshot(**d)


def house(kw, quality='ok'):
    return core.HouseSnapshot(kw, 0.2, quality)


def limits(**kw):
    d = dict(requested_kw=4., confirmed_kw=4., manual_owner=False)
    d.update(kw)
    return core.LimitSnapshot(**d)


def run(seq, s=None, l=None, cfg=None):
    st = None
    out = []
    for minute, household in seq:
        fixture = (s(minute) if callable(s) else s) if s is not None else session(soc_at=at((minute // 15) * 15))
        st, proposal = core.evaluate(at(minute), fixture, household, l or limits(), st, cfg or core.Config())
        out.append(proposal)
    return st, out


class TestPlanner(unittest.TestCase):
    def test_slack_and_budget_are_derived_not_magic(self):
        p = core.plan(T, session())
        self.assertEqual(p.reason, 'flexible')
        self.assertGreater(p.remaining_grid_kwh, 0)
        self.assertGreater(p.discretionary_budget_kwh, 0)

    def test_no_soc_target_or_unreachable(self):
        self.assertEqual(core.plan(T, session(soc=None)).reason, 'insufficient_planner_data')
        self.assertEqual(core.plan(T, session(departure_at=at(30))).reason, 'at_risk')
        self.assertEqual(core.plan(T, session(soc=80)).reason, 'target_reached')
        self.assertEqual(core.plan(T, session(vehicle_ambiguous=True)).reason, 'unidentified_vehicle')
        self.assertEqual(core.plan(at(31), session()).reason, 'insufficient_planner_data')


class TestSupervisor(unittest.TestCase):
    def test_phon_and_direct_restore(self):
        st, result = run([(0, house(2.1)), (1, house(2.1)), (2, house(2.1)),
                          (10, house(.2)), (13, house(.2)), (20, house(.2))])
        self.assertEqual([x.action for x in result].count('reduce'), 1)
        self.assertEqual([x.action for x in result].count('restore'), 1)
        self.assertEqual(st.mode, 'NORMAL')
        self.assertEqual(result[-1].proposed_cap_kw, 4.)

    def test_phon_short_pause_does_not_ramp(self):
        seq = [(0, house(2.1)), (1, house(2.1)), (3, house(.2)),
               (5, house(.2)), (6, house(2.1)), (7, house(2.1)),
               (9, house(.2)), (19, house(.2))]
        _, result = run(seq)
        self.assertEqual([x.action for x in result].count('reduce'), 1)
        self.assertEqual([x.action for x in result].count('restore'), 1)
        self.assertEqual(result[-1].reason, 'documented_quiet')

    def test_iron_cycles_one_cap_without_small_raises(self):
        seq = [(0, house(2.1)), (1, house(2.1))]
        for m in range(2, 61):
            seq.append((m, house(2.1 if m % 8 < 4 else .2)))
        _, result = run(seq, s=lambda m: session(departure_at=at(900),
                                                      soc_at=at((m // 15) * 15)))
        self.assertEqual([x.action for x in result].count('reduce'), 1)
        self.assertFalse(any(x.action == 'restore' for x in result))

    def test_dishwasher_long_break_can_start_new_episode(self):
        seq = [(0, house(2.1)), (1, house(2.1)), (2, house(.2)),
               (12, house(.2)), (30, house(2.1)), (31, house(2.1))]
        _, result = run(seq)
        self.assertEqual([x.action for x in result].count('reduce'), 2)
        self.assertEqual([x.action for x in result].count('restore'), 1)

    def test_cooking_and_too_high_house_dpm_only(self):
        _, r = run([(0, house(3.5)), (1, house(3.5))])
        self.assertEqual(r[-1].reason, 'no_useful_cap_dpm_handles_load')

    def test_urgency_veto_and_budget_exhaustion(self):
        s = session(departure_at=at(390))
        _, r = run([(0, house(2.1)), (1, house(2.1))], s)
        self.assertNotEqual(r[-1].action, 'reduce')
        st, r = run([(0, house(2.1)), (1, house(2.1)), (100, house(2.1))])
        self.assertEqual(r[-1].action, 'restore')
        self.assertEqual(r[-1].reason, 'planner_needs_full_power')
        self.assertEqual(st.mode, 'NORMAL')

    def test_bad_house_does_not_become_zero_or_restore(self):
        st, r = run([(0, house(2.1)), (1, house(2.1)), (2, house(None, 'unavailable')),
                     (5, house(.2, 'stale')), (6, house(.2)), (7, house(None, 'unavailable'))])
        self.assertEqual(st.mode, 'LIMITED')
        self.assertEqual(r[-1].reason, 'house_data_not_trusted')
        self.assertEqual([x.action for x in r].count('restore'), 0)

    def test_missing_data_breaks_quiet_continuity(self):
        _, out = run([(0, house(2.1)), (1, house(2.1)),
                      (2, house(.2)), (6, house(.2, 'unavailable')),
                      (12, house(.2)), (21, house(.2)), (22, house(.2))])
        self.assertEqual([x.action for x in out].count('restore'), 1)
        self.assertEqual(out[-2].action, 'hold')
        self.assertEqual(out[-1].reason, 'documented_quiet')

    def test_old_high_is_not_a_confirmed_trigger(self):
        _, out = run([(0, house(2.1)), (15, house(2.1))])
        self.assertEqual(out[-1].reason, 'confirming_house_load')
        self.assertEqual([x.action for x in out].count('reduce'), 0)

    def test_manual_pause_and_lost_ownership(self):
        for mode in ('MANUAL', 'PAUSE'):
            st, out = run([(0, house(2.1)), (1, house(2.1))], session(mode=mode))
            self.assertEqual(st.mode, 'NORMAL')
            self.assertTrue(all(x.action == 'inactive' for x in out))
        st, _ = run([(0, house(2.1)), (1, house(2.1))])
        st, r = core.evaluate(at(2), session(), house(.2), limits(confirmed_kw=3., requested_kw=3.), st)
        self.assertEqual(r.action, 'retire')
        self.assertEqual(st.mode, 'NORMAL')
        self.assertEqual(r.reason, 'external_limit_changed')

    def test_stop_session_restart_and_second_car(self):
        st, r = run([(0, house(2.1)), (1, house(2.1))])
        self.assertEqual(st.mode, 'LIMITED')
        st, p = core.evaluate(at(2), session(charging=False), house(2.1), limits(), st)
        self.assertEqual(p.action, 'inactive')
        self.assertEqual(st.mode, 'NORMAL')
        st, p = core.evaluate(at(3), session(session_id='s2', vehicle_id='fiat', vehicle_ambiguous=True), house(2.1), limits(), st)
        self.assertEqual(p.action, 'inactive')
        # A restarted pure simulation does not interpret a prior virtual cap as actual.
        fresh, p = core.evaluate(at(4), session(session_id='s2'), house(.2), limits(), None)
        self.assertEqual(fresh.mode, 'NORMAL')

    def test_duplicate_limit_and_no_untrusted_reduction(self):
        _, r = run([(0, house(2.1)), (1, house(2.1))], l=limits(confirmed_kw=3.2, requested_kw=4))
        self.assertEqual(r[-1].reason, 'limit_unconfirmed')
        _, r = run([(0, house(2.1)), (1, house(2.1))], l=limits(confirmed_kw=1.6, requested_kw=1.6))
        self.assertEqual(r[-1].reason, 'no_useful_cap_dpm_handles_load')

    def test_cooldown_and_no_idle_sampling_required(self):
        st, r = run([(0, house(2.1)), (1, house(2.1)), (2, house(.2)), (12, house(.2)),
                     (13, house(2.1)), (14, house(2.1))])
        self.assertEqual(r[-1].reason, 'cooldown')
        self.assertEqual(st.mode, 'NORMAL')
        self.assertTrue(all(isinstance(p.simulation_only, bool) and p.simulation_only for p in r))


if __name__ == '__main__':
    unittest.main()
