"""No-HA, no-BLE guard tests; zero device writes by construction."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "custom_components/easywallbox_smart/control_guard.py"
spec = importlib.util.spec_from_file_location("ew_control_guard_test", PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def observed(**changes):
    item = mod.ElectricalObservation(
        session_id="session-A", user_mode="AUTO", connected=True,
        charging=True, ble_connected=True, telemetry_fresh=True,
        wallbox_fault=False, dpm_active=True, requested_kw=4.2,
        confirmed_kw=4.2, dpm_confirmed_kw=4.4,
        meter_valid=True, observed_at=NOW,
    )
    return replace(item, **changes)


def offer(obs=None, lease=None, **kw):
    args = {"expected_dpm_kw": 4.4, "action": "reduce", "proposed_kw": 3.8,
            "planner_allows": True, "lease": lease}
    args.update(kw)
    return mod.assess_limit_offer(NOW, obs or observed(), **args)


class GuardTest(unittest.TestCase):
    def test_ampere_quantization_matches_firmware(self):
        self.assertEqual([mod.deciamps(x) for x in (4., 4.2, 4.4)], [174, 183, 191])
        for invalid in (-1, 0, float('nan'), float('inf'), True):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                mod.deciamps(invalid)

    def test_proposal_only_without_actuation(self):
        result = offer()
        self.assertEqual((result.status, result.action, result.target_raw,
                          result.original_raw), ("offer", "reduce", 165, 183))
        self.assertTrue(result.requires_user_approval)

    def test_explicit_modes_block(self):
        for mode in ("MANUAL", "PAUSE", "RECONCILE", "CHARGE_NOW", "unknown"):
            with self.subTest(mode=mode):
                self.assertEqual(offer(observed(user_mode=mode)).reason,
                                 "user_mode_not_auto")

    def test_missing_telemetry_and_faults_block(self):
        for changes in ({"ble_connected": None}, {"telemetry_fresh": False},
                        {"wallbox_fault": True}, {"dpm_active": None},
                        {"connected": None}, {"charging": False},
                        {"meter_valid": False}, {"session_id": None}):
            with self.subTest(changes=changes):
                self.assertEqual(offer(observed(**changes)).status, "blocked")

    def test_stale_and_future_readback_block(self):
        for time in (NOW - timedelta(seconds=121), NOW + timedelta(seconds=1)):
            self.assertEqual(offer(observed(observed_at=time)).status, "blocked")

    def test_request_not_conferred_as_approval(self):
        r = offer(observed(requested_kw=3.8))
        self.assertEqual(r.reason, "request_not_ble_confirmed")

    def test_physical_dpm_differs_from_virtual_configuration(self):
        self.assertEqual(offer(observed(dpm_confirmed_kw=4.8)).reason,
                         "dpm_limit_changed_or_paused")
        self.assertEqual(offer(observed(dpm_confirmed_kw=0.)).status, "blocked")
        self.assertEqual(offer(expected_dpm_kw=None).status, "blocked")

    def test_planner_veto_and_unapproved_steps(self):
        self.assertEqual(offer(planner_allows=False).status, "blocked")
        for cap in (3.5, 1.2, 4.4, float('nan')):
            self.assertEqual(offer(proposed_kw=cap).status, "blocked")

    def test_cannot_restore_without_verified_ownership(self):
        self.assertEqual(offer(action="restore", proposed_kw=4.2).reason,
                         "no_owned_limit_to_adjust_or_restore")

    def test_owned_cap_restores_only_original(self):
        lease = mod.LimitLease("session-A", 183, 165, 165, 165)
        obs = observed(requested_kw=3.8, confirmed_kw=3.8)
        r = offer(obs, lease, action="restore", proposed_kw=4.2)
        self.assertEqual((r.status, r.target_raw, r.original_raw),
                         ("offer", 183, 183))
        self.assertEqual(offer(obs, lease, action="restore", proposed_kw=4.0).reason,
                         "restore_not_original_limit")

    def test_manual_change_blocks_restore(self):
        lease = mod.LimitLease("session-A", 183, 165, 165, 165)
        self.assertEqual(offer(observed(), lease, action="restore", proposed_kw=4.2).reason,
                         "manual_override_or_readback_mismatch")

    def test_cross_session_and_unconfirmed_previous_command_block(self):
        lease = mod.LimitLease("session-B", 183, 165, 165, 165)
        self.assertEqual(offer(observed(requested_kw=3.8, confirmed_kw=3.8), lease).reason,
                         "session_changed")
        lease = mod.LimitLease("session-A", 183, 165, 165, 174)
        self.assertEqual(offer(observed(requested_kw=3.8, confirmed_kw=3.8), lease).reason,
                         "previous_command_unconfirmed")

    def test_restart_even_with_matching_readback_never_autorestore(self):
        lease = mod.LimitLease("session-A", 183, 165, 165, 165, recovered=True)
        obs = observed(requested_kw=3.8, confirmed_kw=3.8)
        self.assertEqual(offer(obs, lease, action="restore", proposed_kw=4.2).reason,
                         "restart_requires_explicit_reconciliation")
        self.assertEqual(mod.reconcile_after_restart(obs, lease, NOW,
            expected_dpm_kw=4.4).reason, "restart_requires_explicit_reconciliation")

    def test_restart_with_different_confirmed_readback_disputes_ownership(self):
        lease = mod.LimitLease("session-A", 183, 165, 165, 165)
        r = mod.reconcile_after_restart(observed(), lease, NOW, expected_dpm_kw=4.4)
        self.assertEqual(r.reason, "ownership_disputed_manual_intervention_possible")

    def test_no_ha_bluetooth_or_persistence_dependencies(self):
        source = PATH.read_text()
        for forbidden in ("homeassistant", "services.async_call(", "bleak",
                          "write_text", "open(", "_storage.Store"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
