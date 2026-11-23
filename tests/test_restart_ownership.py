"""prior iterations: restart reconciliation, LIMITED restoration, ESPHome-owned range and predispatch veto."""
from __future__ import annotations
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import unittest
import test_controller_smoke as rig
import test_power_policy as policy_rig

C = rig.const
P = rig.policy


class RCFourteenRestartTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.hass = rig.FakeHass(self.tmp.name)
        self.cfg = rig.setup(self.hass, cable=True, charging=True, soc="70")
        self.c = rig.controller.ChargingController(self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        await self.c.async_load()
        self.c.real_enabled = False
        self.c.refresh()
        self.c._refresh_due = None
        self.c._refresh_issued = True
        self.c._refresh_requested_at = None
        self.c._connect_since = datetime.now(timezone.utc)-timedelta(minutes=1)
        self.others = []

    async def asyncTearDown(self):
        for c in self.others:
            await c.async_close()
        await self.c.async_close()
        self.tmp.cleanup()

    def physical_limit(self, kw):
        self.hass.states[self.cfg[C.CONF_REQUESTED_LIMIT]].publish(str(kw))
        self.hass.states[self.cfg[C.CONF_CONFIRMED_LIMIT]].publish(str(kw))

    async def restart(self):
        await self.c._save()
        stored = dict(self.c._store.content)
        other = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        other._store.async_load = lambda: asyncio.sleep(0, result=stored)
        await other.async_load()
        other.real_enabled = False  # Reconcile without any possible electrical action.
        other.refresh()
        self.others.append(other)
        return other

    def service_writes(self):
        return [(x[0], x[1], x[2]) for x in self.hass.services.calls
                if x[0] in ("number", "switch")]


    async def test_two_ha_restarts_preserve_unresolved_limited_proof(self):
        self.physical_limit(2.8)
        self.c._owned_limit = 2.8
        self.c._power_state = P.State(
            session_id=self.c._session_id, phase="LIMITED",
            cap_kw=2.8, baseline_kw=4.0, kind="strong",
            last_change=datetime.now(timezone.utc)-timedelta(minutes=20))
        await self.c._save()
        saved = dict(self.c._store.content)
        proof = dict(saved["power_session"])
        boot_a = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        boot_a._store.async_load = lambda: asyncio.sleep(0, result=saved)
        await boot_a.async_load()
        self.others.append(boot_a)
        self.assertIsNone(boot_a._trace_session)
        self.assertEqual(boot_a._restart_power, proof)
        # A harmless setting save before cable/car reconciliation.
        await boot_a._save()
        self.assertEqual(boot_a._store.content["power_session"], proof)
        self.assertEqual(boot_a._store.content["power_session"]["stored_at"],
                         proof["stored_at"])  # TTL not extended.

        boot_b = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        saved_again = dict(boot_a._store.content)
        boot_b._store.async_load = lambda: asyncio.sleep(0, result=saved_again)
        await boot_b.async_load()
        boot_b.real_enabled = False
        boot_b.refresh()
        self.others.append(boot_b)
        self.assertIsNone(boot_b._restart_power)
        self.assertEqual(boot_b._power_state.phase, "LIMITED")
        self.assertAlmostEqual(boot_b._owned_limit, 2.8)
        self.assertEqual(self.service_writes(), [])

    async def test_save_while_cable_known_but_car_unknown_preserves_proof(self):
        self.physical_limit(2.8)
        self.c._owned_limit = 2.8
        self.c._power_state = P.State(
            session_id=self.c._session_id, phase="LIMITED",
            cap_kw=2.8, baseline_kw=4.0)
        await self.c._save()
        saved = dict(self.c._store.content)
        proof = dict(saved["power_session"])
        car_id = self.cfg[C.CONF_VEHICLES][0][C.CONF_CABLE]
        self.hass.states[car_id].publish("off")
        boot = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        boot._store.async_load = lambda: asyncio.sleep(0, result=saved)
        await boot.async_load()
        boot.real_enabled = False
        self.others.append(boot)
        boot.refresh()  # Physical cable true, cloud identity missing
        self.assertIsNotNone(boot._trace_session)
        self.assertIsNone(boot._session_id)
        # While restart evidence is unresolved, do not accept a fresh user
        # slider preference that the later reconciliation would overwrite.
        with self.assertRaises(ValueError):
            await boot.async_set_session_power(3.2)
        await boot._save()
        self.assertEqual(boot._store.content["power_session"], proof)
        self.hass.states[car_id].publish("on")
        boot.refresh()
        self.assertIsNone(boot._restart_power)
        self.assertEqual(boot._power_state.phase, "LIMITED")
        self.assertEqual(self.service_writes(), [])

    async def test_confirmed_unplug_erases_pending_restart_proof(self):
        self.physical_limit(2.8)
        self.c._owned_limit = 2.8
        self.c._power_state = P.State(
            session_id=self.c._session_id, phase="LIMITED",
            cap_kw=2.8, baseline_kw=4.0)
        await self.c._save()
        saved = dict(self.c._store.content)
        boot = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        boot._store.async_load = lambda: asyncio.sleep(0, result=saved)
        await boot.async_load()
        boot.real_enabled = False
        self.others.append(boot)
        self.hass.states[self.cfg[C.CONF_WALLBOX_CHARGING]].publish("off")
        self.hass.states[self.cfg[C.CONF_EV_POWER]].publish("0")
        self.hass.states[self.cfg[C.CONF_WALLBOX_CONNECTED]].publish("off")
        self.hass.states[self.cfg[C.CONF_VEHICLES][0][C.CONF_CABLE]].publish("off")
        boot.refresh()
        self.assertIsNone(boot._restart_power)
        await boot._save()
        self.assertIsNone(boot._store.content["power_session"])
        self.assertEqual(self.service_writes(), [])

    async def test_restart_recovers_owned_limited_without_writing(self):
        self.physical_limit(2.8)
        self.c._owned_limit = 2.8
        self.c._power_state = P.State(
            session_id=self.c._session_id, phase="LIMITED",
            cap_kw=2.8, baseline_kw=4.0, kind="strong",
            last_change=datetime.now(timezone.utc)-timedelta(minutes=20))
        recovered = await self.restart()
        self.assertIsNone(recovered._restart_power)
        self.assertEqual(recovered._power_state.phase, "LIMITED")
        self.assertAlmostEqual(recovered._owned_limit, 2.8)
        self.assertEqual(recovered.session_power_kw, 4.0)
        self.assertIsNone(recovered._power_state.last_sample)
        self.assertEqual(self.service_writes(), [])

    async def test_recovered_limited_restores_after_fresh_quiet_evidence(self):
        self.physical_limit(2.8)
        self.c._owned_limit = 2.8
        self.c._power_state = P.State(
            session_id=self.c._session_id, phase="LIMITED",
            cap_kw=2.8, baseline_kw=4.0, kind="strong",
            last_change=datetime.now(timezone.utc)-timedelta(minutes=30))
        recovered = await self.restart()
        state = recovered._power_state
        start = datetime.now(timezone.utc)
        for minute in range(18):
            observation = P.Observation(
                at=start+timedelta(minutes=minute),
                session_id=recovered._session_id, connected=True,
                charging=True, auto=True, trusted=True,
                house_kw=.2, house_at=start+timedelta(minutes=minute),
                dpm_kw=4.4, current_kw=2.8, margin_minutes=120,
                remaining_budget_kwh=1.0, max_kw=4.0)
            state, decision = P.evaluate(observation, state)
            if minute < 15:
                self.assertEqual(decision.action, "none")
            if decision.action == "set_limit":
                break
        self.assertEqual(decision.action, "set_limit")
        self.assertEqual(decision.target_kw, 4.0)
        self.assertEqual(state.phase, "NORMAL")

    async def test_missing_limited_timestamp_starts_conservative_new_hold(self):
        self.physical_limit(2.8)
        self.c._owned_limit = 2.8
        self.c._power_state = P.State(
            session_id=self.c._session_id, phase="LIMITED",
            cap_kw=2.8, baseline_kw=4.0, kind="strong",
            last_change=None)
        other = await self.restart()
        self.assertEqual(other._power_state.phase, "LIMITED")
        self.assertIsNotNone(other._power_state.last_change)
        self.assertLess((datetime.now(timezone.utc)-
                         other._power_state.last_change).total_seconds(), 5)
        self.assertEqual(self.service_writes(), [])

    async def test_restart_keeps_user_lower_session_choice(self):
        await self.c.async_set_session_power(2.0)
        self.physical_limit(2.0)
        self.c._owned_limit = 2.0
        self.c._power_state = P.State(
            session_id=self.c._session_id, phase="NORMAL",
            cap_kw=2.0, baseline_kw=2.0)
        other = await self.restart()
        self.assertEqual(other.session_power_kw, 2.0)
        self.assertEqual(other._owned_limit, 2.0)
        self.assertEqual(other._power_state.phase, "NORMAL")
        self.assertEqual(self.service_writes(), [])

    async def test_restart_mismatch_is_blocked_no_automatic_normalization(self):
        self.physical_limit(2.8)
        self.c._owned_limit = 2.8
        self.c._power_state = P.State(
            session_id=self.c._session_id, phase="LIMITED",
            cap_kw=2.8, baseline_kw=4.0)
        await self.c._save()
        self.physical_limit(3.2)  # Physical state no longer matches saved ACK.
        recovered = await self.restart()
        self.assertEqual(recovered._blocked, "restart_cap_mismatch_no_write")
        self.assertFalse(recovered.real_enabled)
        self.assertEqual(self.service_writes(), [])

    async def test_aborted_initial_power_not_falsely_owned_and_reconsidered(self):
        self.physical_limit(3.6)
        self.c._owned_limit = None
        self.c._power_state = P.State(
            session_id=self.c._session_id, cap_kw=4.0, baseline_kw=4.0)
        original = self.c._save
        async def before_dispatch():
            await original()
            # Make one decision-evidence value change deterministically
            # across the await, as a concurrent HA callback could do.
            self.c._scheduled_at = datetime.now(timezone.utc)+timedelta(hours=1)
        self.c._save = before_dispatch
        self.c.real_enabled = True
        await self.c._actuate(self.c._session_id)
        self.assertEqual(self.service_writes(), [])
        self.assertIsNone(self.c._pending)
        self.assertIsNone(self.c._owned_limit)  # Key prior iterations regression.
        self.c._save = original
        await self.c._actuate(self.c._session_id)
        self.assertEqual(len(self.service_writes()), 1)
        self.assertEqual(self.service_writes()[0][2]["value"], 4.0)

    async def test_esphome_max_above_six_is_not_silently_clamped(self):
        number = self.hass.states[self.cfg[C.CONF_REQUESTED_LIMIT]]
        number.attributes["max"] = 7.0
        self.assertEqual(self.c.session_power_range()[1], 7.0)
        self.assertTrue(self.c._valid_session_power(6.4))
        await self.c.async_set_session_power(6.4)
        self.assertEqual(self.c.session_power_kw, 6.4)
        self.assertEqual(self.service_writes(), [])
        st, decision = P.evaluate(P.Observation(
            at=datetime.now(timezone.utc), session_id="high_limit",
            connected=True, charging=True, auto=True, trusted=True,
            house_kw=.2, house_at=datetime.now(timezone.utc)-timedelta(seconds=1),
            dpm_kw=4.4, current_kw=6.4, margin_minutes=-10,
            remaining_budget_kwh=0.0, max_kw=6.4))
        self.assertNotEqual(decision.reason, "invalid_session_or_source")

    async def test_partial_gap_margin_warning_is_advisory_only(self):
        self.c.charging_verified = True
        self.c.departure = datetime.now(timezone.utc)+timedelta(hours=2)
        self.c._eta_remaining_ac_kwh = None
        self.c.margin_minutes = -10
        self.c.planning_rate_kw = 3.2
        self.c._update_notice(datetime.now(timezone.utc))
        self.assertIn("dati EV parziali", self.c.notice)
        self.assertEqual(self.service_writes(), [])


if __name__ == "__main__":
    unittest.main()
