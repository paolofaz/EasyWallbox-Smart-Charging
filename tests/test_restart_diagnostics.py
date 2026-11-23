"""prior iterations: explain potentially retained limit; log source of expiry, not action."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import unittest

import test_controller_smoke as rig

C = rig.const
P = rig.policy


class RC18RestartDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.hass = rig.FakeHass(self.tmp.name)
        self.cfg = rig.setup(self.hass, cable=True, charging=True, soc="70")
        self.origin = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        await self.origin.async_load()
        self.origin.real_enabled = False
        self.origin.refresh()
        self.origin._owned_limit = 2.8
        self.origin._power_state = P.State(
            session_id=self.origin._session_id, phase="LIMITED",
            cap_kw=2.8, baseline_kw=4.0,
            last_change=datetime.now(timezone.utc)-timedelta(minutes=20))
        self.hass.states[self.cfg[C.CONF_REQUESTED_LIMIT]].publish("2.8")
        self.hass.states[self.cfg[C.CONF_CONFIRMED_LIMIT]].publish("2.8")
        await self.origin._save()
        self.saved = dict(self.origin._store.content)
        self.hass.states[self.cfg[C.CONF_WALLBOX_CHARGING]].publish("off")
        self.hass.states[self.cfg[C.CONF_EV_POWER]].publish("0")
        self.instances = []
        self.events = []

    async def asyncTearDown(self):
        for c in self.instances:
            await c.async_close()
        await self.origin.async_close()
        self.tmp.cleanup()

    def with_stamp(self, stamp, **updates):
        proof = dict(self.saved["power_session"])
        proof["stored_at"] = stamp
        proof.update(updates)
        return {**self.saved, "power_session": proof}

    def age_stamp(self, hours):
        return (datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()

    async def boot(self, saved):
        c = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        c._store.async_load = lambda: asyncio.sleep(0, result=saved)
        await c.async_load()
        self.instances.append(c)
        # The journal must have a concrete physical-plug session at expiry.
        c._journal.record = lambda session, event, reason, **details: (
            self.events.append((session, event, reason, details)))
        c.refresh()
        return c

    def service_writes(self):
        return [x for x in self.hass.services.calls
                if x[0] in ("number", "switch")]

    def expiry(self):
        return [row for row in self.events
                if row[1] == "reconciliation" and
                row[2] in ("restart_power_evidence_expired_manual_review",
                           "expired_restart_power_discarded")]

    async def test_stale_limited_has_useful_warning_journal_and_saved_evidence(self):
        c = await self.boot(self.with_stamp(self.age_stamp(25)))
        self.assertTrue(c._restart_review)
        self.assertFalse(c.real_enabled)
        self.assertIn("Ultimo limite EV confermato 2.8 kW", c.notice)
        self.assertIn("non è una lettura attuale", c.notice)
        self.assertIn("ancora attivo sulla wallbox", c.notice)
        self.assertIn("ESPHome", c.notice)
        self.assertLessEqual(len(c.notice), 255)
        info = c._restart_review_info
        self.assertEqual(info["expiry_cause"], "stale")
        self.assertGreater(info["age_s"], 24*3600)
        self.assertAlmostEqual(info["last_confirmed_kw"], 2.8)
        self.assertEqual(len(self.expiry()), 1)
        session, event, reason, details = self.expiry()[0]
        self.assertTrue(session)  # Before this fix the journal dropped this event.
        self.assertEqual(details["expiry_cause"], "stale")
        self.assertGreater(details["age_s"], 24*3600)
        self.assertEqual(self.service_writes(), [])

    async def test_diagnostics_survive_second_ha_restart_without_new_actions(self):
        first = await self.boot(self.with_stamp(self.age_stamp(25)))
        initial = dict(first._restart_review_info)
        await first._save()
        saved = dict(first._store.content)
        self.assertEqual(saved["restart_review_info"], initial)
        self.assertIsNone(saved["power_session"])
        self.events.clear()
        second = await self.boot(saved)
        self.assertEqual(second._restart_review_info, initial)
        self.assertIn("2.8 kW", second.notice)
        self.assertFalse(second.real_enabled)
        self.assertEqual(self.expiry(), [])  # Not classified a second time
        self.assertEqual(self.service_writes(), [])

    async def test_large_clock_skew_has_negative_raw_age_and_cause(self):
        c = await self.boot(self.with_stamp(self.age_stamp(-3)))
        self.assertTrue(c._restart_review)
        self.assertEqual(c._restart_review_info["expiry_cause"], "clock_skew")
        self.assertLess(c._restart_review_info["age_s"], -7200)
        self.assertEqual(self.expiry()[0][3]["expiry_cause"], "clock_skew")
        self.assertLess(self.expiry()[0][3]["age_s"], -7200)
        self.assertEqual(self.service_writes(), [])

    async def test_malformed_timestamp_is_diagnostic_without_fake_age(self):
        c = await self.boot(self.with_stamp("non-ISO-datetime"))
        self.assertTrue(c._restart_review)
        self.assertEqual(c._restart_review_info["expiry_cause"],
                         "invalid_timestamp")
        self.assertIsNone(c._restart_review_info["age_s"])
        self.assertIsNone(self.expiry()[0][3]["age_s"])
        self.assertEqual(self.service_writes(), [])

    async def test_small_negative_age_is_not_expired_or_rewritten(self):
        stamp = self.age_stamp(-1)
        c = await self.boot(self.with_stamp(stamp))
        self.assertIsNotNone(c._restart_power)
        self.assertFalse(c._restart_review)
        self.assertEqual(self.expiry(), [])
        await c._save()
        self.assertEqual(c._store.content["power_session"]["stored_at"], stamp)
        self.assertEqual(self.service_writes(), [])

    async def test_expired_normal_default_logs_discard_without_block(self):
        saved = self.with_stamp(
            self.age_stamp(25), phase="NORMAL", confirmed_kw=4.0,
            cap_kw=4.0, baseline_kw=4.0, desired_kw=4.0, default_kw=4.0)
        c = await self.boot(saved)
        self.assertFalse(c._restart_review)
        self.assertTrue(c.real_enabled)
        self.assertEqual(len(self.expiry()), 1)
        self.assertEqual(self.expiry()[0][2], "expired_restart_power_discarded")
        self.assertEqual(self.expiry()[0][3]["expiry_cause"], "stale")
        self.assertTrue(self.expiry()[0][0])
        self.assertEqual(self.service_writes(), [])

    async def test_other_safety_block_takes_precedence_over_warning(self):
        c = await self.boot(self.with_stamp(self.age_stamp(25)))
        c._blocked = "previous_command_unconfirmed_no_retry"
        c._update_notice(datetime.now(timezone.utc))
        self.assertIn("previous_command_unconfirmed_no_retry", c.notice)
        self.assertNotIn("Ultimo limite EV", c.notice)
        self.assertEqual(self.service_writes(), [])

    async def test_verified_unplug_clears_warning_and_persisted_info(self):
        c = await self.boot(self.with_stamp(self.age_stamp(25)))
        self.assertIsNotNone(c._restart_review_info)
        self.hass.states[self.cfg[C.CONF_WALLBOX_CONNECTED]].publish("off")
        self.hass.states[self.cfg[C.CONF_VEHICLES][0][C.CONF_CABLE]].publish("off")
        c.refresh()
        self.assertIsNone(c._restart_review_info)
        self.assertFalse(c._restart_review)
        await c._save()
        self.assertIsNone(c._store.content["restart_review_info"])
        self.assertFalse(c._store.content["restart_review"])
        self.assertEqual(self.service_writes(), [])

    async def test_internal_explicit_rearm_also_clears_warning_info(self):
        c = await self.boot(self.with_stamp(self.age_stamp(25)))
        await c.async_change("real", True)
        self.assertIsNone(c._restart_review_info)
        self.assertFalse(c._restart_review)
        self.assertTrue(c.real_enabled)
        self.assertIsNone(c._store.content["restart_review_info"])
        self.assertEqual(self.service_writes(), [])


if __name__ == "__main__":
    unittest.main()
