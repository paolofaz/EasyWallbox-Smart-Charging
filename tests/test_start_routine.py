"""Offline acceptance tests for the AUTO-ready / scheduled-start bench.

These tests deliberately do not import Home Assistant or use service calls.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import sys
import unittest

PATH = (Path(__file__).resolve().parents[1] /
        "custom_components/easywallbox_smart/start_routine.py")
spec = importlib.util.spec_from_file_location("ew_start_routine_bench", PATH)
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)
NOW = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)


def sample(**update):
    data = bench.BenchInputs(
        now=NOW, mode="AUTO", wallbox_cable=False, vehicle_cable=False,
        session_id=None, vehicle_id=None, target_reached=None,
        ble_ready=True, data_valid=True, wallbox_fault=False,
        dpm_active=True, dpm_confirmed_kw=4.4, dpm_original_kw=4.4,
        ev_requested_kw=3.6, ev_confirmed_kw=3.6, ev_session_max_kw=4.2,
        charging=False, auto_park_enabled=True,
    )
    return replace(data, **update)


def connected(**update):
    return sample(
        wallbox_cable=True, vehicle_cable=True,
        session_id="fiat-1", vehicle_id="fiat", target_reached=False,
        **update,
    )


class StartRoutineBenchTest(unittest.TestCase):
    def test_disconnected_auto_offer_one_preplug_pause(self):
        r = bench.evaluate_bench(sample())
        self.assertEqual((r.phase, r.action, r.target_kw),
                         ("DISCONNECTED", "offer_park", 0.0))
        self.assertTrue(r.simulation_only and r.requires_explicit_authorization)

    def test_unplugged_default_without_opt_in_has_no_actions(self):
        r = bench.evaluate_bench(sample(auto_park_enabled=False))
        self.assertEqual(r.action, "none")

    def test_arm_attempt_is_not_retried_blindly(self):
        r = bench.evaluate_bench(sample(arm_attempted=True))
        self.assertEqual((r.action, r.reason),
                         ("none", "arm_attempt_pending_no_blind_retry"))

    def test_johnny_owned_zero_dpm_remains_ready_without_writes(self):
        r = bench.evaluate_bench(sample(
            arm_owner="johnny", dpm_confirmed_kw=0.0, arm_attempted=True))
        self.assertEqual((r.phase, r.action), ("AUTO_READY", "none"))

    def test_zero_dpm_held_by_external_owner_not_inherited(self):
        r = bench.evaluate_bench(sample(dpm_confirmed_kw=0.0, arm_owner="unknown"))
        self.assertEqual(r.reason, "zero_dpm_without_proven_ownership")

    def test_dpm_changed_after_arming_blocks_new_pause(self):
        r = bench.evaluate_bench(sample(arm_owner="johnny"))
        self.assertEqual(r.phase, "RECONCILE")

    def test_manual_and_explicit_pause_never_offer_any_action(self):
        for mode in ("MANUAL", "PAUSE", "RECONCILE"):
            with self.subTest(mode=mode):
                self.assertEqual(bench.evaluate_bench(sample(mode=mode)).action, "none")

    def test_untrusted_cable_or_ble_cannot_offer(self):
        for edits in ({"vehicle_cable": None}, {"wallbox_cable": True},
                      {"ble_ready": False}, {"data_valid": False},
                      {"wallbox_fault": None}, {"dpm_active": False}):
            with self.subTest(edits=edits):
                self.assertEqual(bench.evaluate_bench(sample(**edits)).action, "none")

    def test_manual_override_wins_even_while_disconnected(self):
        r = bench.evaluate_bench(sample(user_override=True))
        self.assertEqual(r.reason, "external_manual_intervention")

    def test_dpm_baseline_requires_exact_confirmed_ampere_quantization(self):
        self.assertEqual(bench.evaluate_bench(sample(dpm_original_kw=4.8)).action,
                         "none")
        self.assertEqual(bench.nominal_deciamps(4.4), 191)
        self.assertEqual(bench.nominal_deciamps(4.2), 183)

    def test_future_schedule_waits_only_if_dpm_zero_and_owned(self):
        r = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny",
            preferred_start_at=NOW+timedelta(hours=4),
            latest_safe_start_at=NOW+timedelta(hours=3),
        ))
        self.assertEqual((r.phase, r.action), ("WAIT_SCHEDULE", "none"))

    def test_unarmed_future_schedule_never_pretends_charging_will_wait(self):
        r = bench.evaluate_bench(connected(
            preferred_start_at=NOW+timedelta(hours=4),
            latest_safe_start_at=NOW+timedelta(hours=3),
        ))
        self.assertEqual((r.phase, r.reason), ("RECONCILE", "scheduled_wait_not_armed"))

    def test_latest_safe_start_overrides_preferred_start(self):
        r = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny",
            preferred_start_at=NOW+timedelta(hours=4),
            latest_safe_start_at=NOW-timedelta(minutes=1),
        ))
        self.assertEqual((r.action, r.target_kw), ("offer_ev_limit", 4.2))

    def test_start_hour_reached_proposes_ev_max_before_dpm(self):
        r = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny",
            preferred_start_at=NOW, latest_safe_start_at=NOW+timedelta(hours=2),
        ))
        self.assertEqual((r.action, r.target_kw), ("offer_ev_limit", 4.2))

    def test_ev_limit_confirmed_then_propose_original_dpm_not_hardcoded(self):
        r = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny",
            dpm_original_kw=4.8, ev_requested_kw=4.2, ev_confirmed_kw=4.2,
        ))
        self.assertEqual((r.action, r.target_kw), ("offer_resume", 4.8))

    def test_ev_requested_differs_from_confirmed_never_resume(self):
        r = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny",
            ev_requested_kw=4.2, ev_confirmed_kw=3.8,
        ))
        self.assertEqual((r.phase, r.action), ("WAIT_ACK", "none"))

    def test_ev_and_resume_attempt_flags_block_blind_repeats(self):
        r = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny",
            ev_limit_attempted=True))
        self.assertEqual(r.phase, "WAIT_ACK")
        r2 = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny",
            ev_requested_kw=4.2, ev_confirmed_kw=4.2,
            resume_attempted=True))
        self.assertEqual(r2.reason, "dpm_resume_confirmation_pending_no_retry")

    def test_manual_zero_dpm_while_plugged_is_never_resumed(self):
        r = bench.evaluate_bench(connected(dpm_confirmed_kw=0.0))
        self.assertEqual(r.reason, "zero_dpm_without_proven_ownership")

    def test_target_reached_never_restart_while_cable_still_plugged(self):
        r = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny", target_reached=True))
        self.assertEqual((r.phase, r.action), ("COMPLETED", "none"))

    def test_if_charging_already_observed_leave_normal(self):
        r = bench.evaluate_bench(connected(charging=True))
        self.assertEqual((r.phase, r.action), ("CHARGING_NORMAL", "none"))

    def test_no_new_start_with_unknown_soc_or_identity(self):
        r = bench.evaluate_bench(connected(target_reached=None))
        self.assertEqual(r.action, "none")
        r2 = bench.evaluate_bench(connected(vehicle_id=None))
        self.assertEqual(r2.action, "none")

    def test_dpm_zero_but_real_charging_is_inconsistent(self):
        r = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny", charging=True))
        self.assertEqual(r.reason, "charging_conflicts_with_zero_dpm")

    def test_invalid_ev_step_never_offered(self):
        r = bench.evaluate_bench(connected(
            dpm_confirmed_kw=0.0, arm_owner="johnny", ev_session_max_kw=3.5))
        self.assertEqual(r.action, "none")

    def test_pure_read_only_no_homeassistant_ble_or_storage(self):
        s = PATH.read_text()
        for forbidden in ("homeassistant", "bleak", "services.async_call(",
                          "switch.turn_off", "number.set_value", "open(",
                          "write_text", "_storage.Store"):
            self.assertNotIn(forbidden, s)


if __name__ == "__main__":
    unittest.main()
