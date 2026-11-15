"""M3 pure session semantics; no HA, no device, no persistence."""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart/session_policy.py"
SPEC = importlib.util.spec_from_file_location("ew_session_policy_tests", FILE)
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)


def connected(previous=None, sid="vehicle-a:1", charging=False, target=False):
    return policy.observe(previous, session_id=sid, connection=True,
                          charging=charging, target_reached=target)


class TestSessionControl(unittest.TestCase):
    def test_first_connected_after_restart_must_not_autoresume(self):
        s = connected()
        self.assertEqual((s.mode, s.phase), ("RECONCILE", "RECONCILE"))
        self.assertTrue(s.requires_confirmation)

    def test_boot_disconnected_then_plug_in_auto(self):
        d = policy.observe(None, session_id=None, connection=False, charging=False)
        self.assertEqual(d.mode, "AUTO")
        s = connected(d)
        self.assertEqual((s.mode, s.phase), ("AUTO", "CONNECTED_NOT_CHARGING"))
        self.assertFalse(s.requires_confirmation)

    def test_invalid_unknown_boot_does_not_autorearm(self):
        missing = policy.observe(None, session_id=None, connection=None, charging=False)
        self.assertEqual(missing.mode, "RECONCILE")
        s = connected(missing)
        self.assertEqual(s.mode, "RECONCILE")

    def test_unknown_sensor_does_not_reset_explicit_pause(self):
        s = policy.user_select_mode(connected(), "PAUSE")
        uncertain = policy.observe(s, session_id=None, connection=None, charging=False)
        self.assertEqual((uncertain.mode, uncertain.phase), ("PAUSE", "UNKNOWN"))
        self.assertEqual(connected(uncertain).mode, "PAUSE")

    def test_pause_never_falsifies_electric_charging(self):
        s = policy.user_select_mode(connected(charging=True), "PAUSE")
        after = connected(s, charging=True)
        self.assertEqual(after.phase, "CHARGING")
        self.assertEqual(after.reason, "virtual_pause_does_not_stop_real_charge")

    def test_manual_persists_through_wait_and_charge(self):
        s = policy.user_select_mode(connected(), "MANUAL")
        for actual in (False, True, False, True):
            s = connected(s, charging=actual)
            self.assertEqual(s.mode, "MANUAL")
        self.assertEqual(s.phase, "CHARGING")

    def test_pause_persists_through_target_and_clock(self):
        s = policy.user_select_mode(connected(), "PAUSE")
        s = connected(s, target=True)
        self.assertEqual((s.mode, s.phase), ("PAUSE", "TARGET_REACHED"))

    def test_explicit_auto_unpauses(self):
        s = policy.user_select_mode(connected(), "PAUSE")
        s = policy.user_select_mode(s, "AUTO")
        self.assertEqual(s.mode, "AUTO")
        self.assertFalse(s.requires_confirmation)

    def test_explicit_charge_now_can_override_pause(self):
        s = policy.user_select_mode(connected(), "PAUSE")
        s = policy.user_select_mode(s, "CHARGE_NOW")
        self.assertEqual(s.mode, "CHARGE_NOW")
        self.assertEqual(s.reason, "explicit_user_charge_now_simulation_only")

    def test_charge_now_stays_until_disconnect(self):
        s = policy.user_select_mode(connected(), "CHARGE_NOW")
        s = connected(s, charging=True)
        self.assertEqual(s.mode, "CHARGE_NOW")
        s = policy.observe(s, session_id=None, connection=False, charging=False)
        self.assertEqual((s.mode, s.phase, s.session_id), ("AUTO", "DISCONNECTED", None))

    def test_next_session_reverts_auto_after_clean_disconnect(self):
        s = policy.user_select_mode(connected(), "MANUAL")
        d = policy.observe(s, session_id=None, connection=False, charging=False)
        self.assertEqual(connected(d, "vehicle-b:2").mode, "AUTO")

    def test_switch_vehicle_without_disconnect_requires_reconciliation(self):
        s = policy.user_select_mode(connected(), "MANUAL")
        b = connected(s, "vehicle-b:2")
        self.assertEqual((b.mode, b.phase), ("RECONCILE", "RECONCILE"))

    def test_ambiguous_vehicle_preserves_mode_but_fences_evaluation(self):
        s = policy.user_select_mode(connected(), "PAUSE")
        u = policy.observe(s, session_id=None, connection=None,
                           charging=False, ambiguous=True)
        self.assertEqual((u.mode, u.phase), ("PAUSE", "UNKNOWN"))

    def test_no_ui_selection_without_reliable_session(self):
        disconnected = policy.observe(None, session_id=None, connection=False, charging=False)
        with self.assertRaises(ValueError):
            policy.user_select_mode(disconnected, "PAUSE")
        s = policy.user_select_mode(connected(), "PAUSE")
        unknown = policy.observe(s, session_id=None, connection=None, charging=False)
        with self.assertRaises(ValueError):
            policy.user_select_mode(unknown, "AUTO")

    def test_initial_reconciliation_can_be_resolved_with_manual_or_pause(self):
        for mode in ("AUTO", "MANUAL", "PAUSE", "CHARGE_NOW"):
            with self.subTest(mode=mode):
                s = policy.user_select_mode(connected(), mode)
                self.assertEqual(s.mode, mode)
                self.assertFalse(s.requires_confirmation)

    def test_invalid_command_and_observation_rejected(self):
        with self.assertRaises(ValueError):
            policy.user_select_mode(connected(), "STOP_WALLBOX")
        with self.assertRaises(ValueError):
            policy.observe(None, session_id="a", connection="yes", charging=False)
        with self.assertRaises(ValueError):
            policy.observe(None, session_id="a", connection=True, charging=1)

    def test_pure_mode_has_no_external_api_dependencies(self):
        src = FILE.read_text()
        for forbidden in ("homeassistant", "bleak", "services.", "open(", "write_text"):
            self.assertNotIn(forbidden, src)

if __name__ == "__main__":
    unittest.main()
