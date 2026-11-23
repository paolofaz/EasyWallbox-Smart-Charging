"""prior iterations: no indefinite slider lock after stale restart evidence."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import unittest
import test_controller_smoke as rig

C = rig.const
P = rig.policy


class RC16ExpiryTests(unittest.IsolatedAsyncioTestCase):
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
            session_id=self.original._session_id,
            phase="LIMITED", cap_kw=2.8, baseline_kw=4.0,
            last_change=datetime.now(timezone.utc)-timedelta(minutes=30))
        self.hass.states[self.cfg[C.CONF_REQUESTED_LIMIT]].publish("2.8")
        self.hass.states[self.cfg[C.CONF_CONFIRMED_LIMIT]].publish("2.8")
        await self.original._save()
        self.saved = dict(self.original._store.content)
        # A car is still plugged but is not actively charging when HA boots.
        self.hass.states[self.cfg[C.CONF_WALLBOX_CHARGING]].publish("off")
        self.hass.states[self.cfg[C.CONF_EV_POWER]].publish("0")
        self.extra = []

    async def asyncTearDown(self):
        for c in self.extra:
            await c.async_close()
        await self.original.async_close()
        self.tmp.cleanup()

    async def boot(self, saved):
        c = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        c._store.async_load = lambda: asyncio.sleep(0, result=saved)
        await c.async_load()
        self.extra.append(c)
        c.refresh()
        return c

    def calls(self):
        return [x for x in self.hass.services.calls
                if x[0] in ("number", "switch")]

    async def test_valid_pending_proof_reports_waiting_not_invalid_esphome(self):
        c = await self.boot(self.saved)
        self.assertIsNotNone(c._restart_power)
        self.assertTrue(c.real_enabled)
        self.assertIn("Riconciliazione dopo riavvio in attesa", c.notice)
        with self.assertRaisesRegex(ValueError, "Riconciliazione dopo riavvio"):
            await c.async_set_session_power(3.2)
        self.assertEqual(self.calls(), [])

    async def test_expired_proof_drops_without_charging_and_blocks_old_owned_cap(self):
        saved = dict(self.saved)
        proof = dict(saved["power_session"])
        proof["stored_at"] = (datetime.now(timezone.utc) -
                              timedelta(hours=25)).isoformat()
        saved["power_session"] = proof
        c = await self.boot(saved)
        self.assertIsNone(c._restart_power)
        self.assertEqual(c._blocked, "restart_power_evidence_expired_manual_review")
        self.assertFalse(c.real_enabled)
        self.assertIn("Ultimo limite EV confermato 2.8 kW", c.notice)
        await c._save()
        self.assertNotEqual(c._store.content["power_session"], proof)
        self.assertEqual(self.calls(), [])

    async def test_malformed_timestamp_is_discarded_with_safe_block(self):
        saved = dict(self.saved)
        proof = dict(saved["power_session"])
        proof["stored_at"] = "invalid"
        saved["power_session"] = proof
        c = await self.boot(saved)
        self.assertIsNone(c._restart_power)
        self.assertFalse(c.real_enabled)
        self.assertEqual(self.calls(), [])

    async def test_expired_proof_with_no_prior_cap_does_not_block(self):
        saved = dict(self.saved)
        proof = dict(saved["power_session"])
        proof["confirmed_kw"] = None
        proof["stored_at"] = (datetime.now(timezone.utc) -
                              timedelta(hours=25)).isoformat()
        saved["power_session"] = proof
        c = await self.boot(saved)
        self.assertIsNone(c._restart_power)
        self.assertIsNone(c._blocked)
        self.assertTrue(c.real_enabled)
        self.assertEqual(self.calls(), [])

    async def test_pending_proof_is_discarded_on_confirmed_unplug(self):
        c = await self.boot(self.saved)
        self.assertIsNotNone(c._restart_power)
        self.hass.states[self.cfg[C.CONF_WALLBOX_CONNECTED]].publish("off")
        self.hass.states[self.cfg[C.CONF_VEHICLES][0][C.CONF_CABLE]].publish("off")
        c.refresh()
        self.assertIsNone(c._restart_power)
        await c._save()
        self.assertIsNone(c._store.content["power_session"])
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
