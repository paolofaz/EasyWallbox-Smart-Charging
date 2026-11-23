"""prior iterations: only genuinely owned non-default caps require review after 24h.

A small RTC/NTP skew is tolerated consistently in idle expiry and active
reconciliation, without changing stored_at and without automatic BLE.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import unittest
import test_controller_smoke as rig

C = rig.const
P = rig.policy


class RC17RestartReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.hass = rig.FakeHass(self.tmp.name)
        self.cfg = rig.setup(self.hass, cable=True, charging=True, soc="70")
        self.original = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        await self.original.async_load()
        self.original.real_enabled = False
        self.original.refresh()
        self.original._owned_limit = 2.8
        self.original._power_state = P.State(
            session_id=self.original._session_id, phase="LIMITED",
            cap_kw=2.8, baseline_kw=4.0, kind="strong",
            last_change=datetime.now(timezone.utc)-timedelta(minutes=30))
        self.physical_limit(2.8)
        await self.original._save()
        self.saved = dict(self.original._store.content)
        self.booted = []
        # Simulate a connected but not charging vehicle.
        self.hass.states[self.cfg[C.CONF_WALLBOX_CHARGING]].publish("off")
        self.hass.states[self.cfg[C.CONF_EV_POWER]].publish("0")

    def physical_limit(self, kw):
        self.hass.states[self.cfg[C.CONF_REQUESTED_LIMIT]].publish(str(kw))
        self.hass.states[self.cfg[C.CONF_CONFIRMED_LIMIT]].publish(str(kw))

    async def asyncTearDown(self):
        for ctl in self.booted:
            await ctl.async_close()
        await self.original.async_close()
        self.tmp.cleanup()

    async def boot(self, saved, *, base_override=None):
        ctl = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        ctl._store.async_load = lambda: asyncio.sleep(0, result=saved)
        await ctl.async_load()
        if base_override is not None:
            ctl.cfg[C.CONF_BASE_KW] = base_override
        self.booted.append(ctl)
        ctl.refresh()
        return ctl

    def saved_with(self, **changes):
        record = dict(self.saved["power_session"])
        record.update(changes)
        return {**self.saved, "power_session": record}

    def calls(self):
        return [x for x in self.hass.services.calls
                if x[0] in ("number", "switch")]

    def old_time(self):
        return (datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()

    def future_time(self, hours):
        return (datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat()

    async def test_expired_normal_default_does_not_disable_real_control(self):
        saved = self.saved_with(
            phase="NORMAL", confirmed_kw=4.0, cap_kw=4.0, baseline_kw=4.0,
            desired_kw=4.0, default_kw=4.0, stored_at=self.old_time())
        ctl = await self.boot(saved)
        self.assertIsNone(ctl._restart_power)
        self.assertIsNone(ctl._blocked)
        self.assertTrue(ctl.real_enabled)
        await ctl._save()
        self.assertNotEqual(ctl._store.content["power_session"],
                            saved["power_session"])
        self.assertEqual(self.calls(), [])

    async def test_expired_review_fence_survives_another_ha_restart(self):
        saved = self.saved_with(stored_at=self.old_time())
        first = await self.boot(saved)
        self.assertTrue(first._restart_review)
        self.assertFalse(first.real_enabled)
        await first._save()
        self.assertTrue(first._store.content["restart_review"])
        self.assertIsNone(first._store.content["power_session"])
        second = await self.boot(dict(first._store.content))
        self.assertTrue(second._restart_review)
        self.assertEqual(second._blocked,
                         "restart_power_evidence_expired_manual_review")
        self.assertFalse(second.real_enabled)
        self.assertIsNone(second._restart_power)
        self.assertEqual(self.calls(), [])

    async def test_user_explicitly_reenables_after_review_and_clears_fence(self):
        first = await self.boot(self.saved_with(stored_at=self.old_time()))
        self.assertTrue(first._restart_review)
        await first.async_change("real", True)
        self.assertFalse(first._restart_review)
        self.assertIsNone(first._blocked)
        self.assertTrue(first.real_enabled)
        self.assertFalse(first._store.content["restart_review"])
        second = await self.boot(dict(first._store.content))
        self.assertFalse(second._restart_review)
        self.assertIsNone(second._blocked)
        self.assertEqual(self.calls(), [])

    async def test_verified_unplug_retires_expired_review_across_reboot(self):
        first = await self.boot(self.saved_with(stored_at=self.old_time()))
        self.assertTrue(first._restart_review)
        self.hass.states[self.cfg[C.CONF_WALLBOX_CONNECTED]].publish("off")
        self.hass.states[self.cfg[C.CONF_VEHICLES][0][C.CONF_CABLE]].publish("off")
        first.refresh()
        self.assertFalse(first._restart_review)
        self.assertIsNone(first._blocked)
        await first._save()
        self.assertFalse(first._store.content["restart_review"])
        second = await self.boot(dict(first._store.content))
        self.assertFalse(second._restart_review)
        self.assertEqual(self.calls(), [])

    async def test_expired_normal_default_does_not_create_unowned_future_proof(self):
        saved = self.saved_with(
            phase="NORMAL", confirmed_kw=4.0, cap_kw=4.0, baseline_kw=4.0,
            desired_kw=4.0, default_kw=4.0, stored_at=self.old_time())
        first = await self.boot(saved)
        self.assertIsNone(first._blocked)
        await first._save()
        self.assertIsNone(first._store.content["power_session"])
        second = await self.boot(dict(first._store.content))
        self.assertIsNone(second._restart_power)
        self.assertTrue(second.real_enabled)
        self.assertEqual(self.calls(), [])

    async def test_user_override_without_ack_is_still_saved_for_session(self):
        self.original._owned_limit = None
        self.original.session_power_kw = 2.0
        await self.original._save()
        proof = self.original._store.content["power_session"]
        self.assertIsInstance(proof, dict)
        self.assertAlmostEqual(proof["desired_kw"], 2.0)
        self.assertIsNone(proof["confirmed_kw"])
        self.assertFalse(self.original._restart_review)
        self.assertEqual(self.calls(), [])

    async def test_expired_normal_user_override_still_requires_review(self):
        saved = self.saved_with(
            phase="NORMAL", confirmed_kw=2.0, cap_kw=2.0, baseline_kw=2.0,
            desired_kw=2.0, default_kw=4.0, stored_at=self.old_time())
        ctl = await self.boot(saved)
        self.assertEqual(ctl._blocked, "restart_power_evidence_expired_manual_review")
        self.assertFalse(ctl.real_enabled)
        self.assertEqual(self.calls(), [])

    async def test_expired_limited_is_fenced_even_when_cap_equals_default(self):
        saved = self.saved_with(
            phase="LIMITED", confirmed_kw=4.0, cap_kw=4.0,
            baseline_kw=5.0, desired_kw=5.0, default_kw=4.0,
            stored_at=self.old_time())
        ctl = await self.boot(saved)
        self.assertEqual(ctl._blocked, "restart_power_evidence_expired_manual_review")
        self.assertFalse(ctl.real_enabled)
        self.assertEqual(self.calls(), [])

    async def test_changed_default_makes_prior_normal_cap_non_default(self):
        saved = self.saved_with(
            phase="NORMAL", confirmed_kw=4.0, cap_kw=4.0,
            baseline_kw=4.0, default_kw=4.0, stored_at=self.old_time())
        ctl = await self.boot(saved, base_override=4.2)
        self.assertFalse(ctl.real_enabled)
        self.assertEqual(ctl._blocked, "restart_power_evidence_expired_manual_review")
        self.assertEqual(self.calls(), [])

    async def test_future_timestamp_within_two_hours_waits_without_block(self):
        saved = self.saved_with(stored_at=self.future_time(1))
        ctl = await self.boot(saved)
        self.assertIsNotNone(ctl._restart_power)
        self.assertIsNone(ctl._blocked)
        self.assertTrue(ctl.real_enabled)
        self.assertIn("Riconciliazione dopo riavvio in attesa", ctl.notice)
        await ctl._save()
        self.assertEqual(ctl._store.content["power_session"]["stored_at"],
                         saved["power_session"]["stored_at"])
        self.assertEqual(self.calls(), [])

    async def test_future_timestamp_within_two_hours_recovers_limited(self):
        saved = self.saved_with(stored_at=self.future_time(1))
        # Fresh, already charging car after HA boot.
        self.hass.states[self.cfg[C.CONF_WALLBOX_CHARGING]].publish("on")
        self.hass.states[self.cfg[C.CONF_EV_POWER]].publish("2.4")
        ctl = await self.boot(saved)
        self.assertIsNone(ctl._restart_power)
        self.assertIsNone(ctl._blocked)
        self.assertEqual(ctl._power_state.phase, "LIMITED")
        self.assertAlmostEqual(ctl._owned_limit, 2.8)
        self.assertEqual(self.calls(), [])

    async def test_future_timestamp_beyond_two_hours_blocks_limited(self):
        saved = self.saved_with(stored_at=self.future_time(3))
        ctl = await self.boot(saved)
        self.assertIsNone(ctl._restart_power)
        self.assertEqual(ctl._blocked, "restart_power_evidence_expired_manual_review")
        self.assertFalse(ctl.real_enabled)
        self.assertEqual(self.calls(), [])

    async def test_future_timestamp_beyond_two_hours_does_not_block_normal_default(self):
        saved = self.saved_with(
            phase="NORMAL", confirmed_kw=4.0, cap_kw=4.0,
            baseline_kw=4.0, default_kw=4.0, stored_at=self.future_time(3))
        ctl = await self.boot(saved)
        self.assertIsNone(ctl._restart_power)
        self.assertIsNone(ctl._blocked)
        self.assertTrue(ctl.real_enabled)
        self.assertEqual(self.calls(), [])

    async def test_time_skew_does_not_renew_original_ttl(self):
        saved = self.saved_with(stored_at=self.future_time(1))
        now = datetime.now(timezone.utc)
        ctl = await self.boot(saved)
        self.assertEqual(ctl._restart_record_age(now, saved["power_session"]),
                         timedelta(0))
        real_timestamp = datetime.fromisoformat(saved["power_session"]["stored_at"])
        self.assertGreater(
            ctl._restart_record_age(real_timestamp+timedelta(hours=24,seconds=1),
                                    saved["power_session"]), timedelta(hours=24))
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
