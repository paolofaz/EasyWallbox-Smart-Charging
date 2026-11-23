"""prior iterations safety regressions from the real 500e 8 -> 7 -> 5 -> 3 episode."""
from __future__ import annotations
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import test_controller_smoke as rig
import test_power_policy as policy_rig
from easywallbox_test_package import planner_rate as planner

C = rig.const


class RC7StopRecovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tempfile import TemporaryDirectory
        self.tmp = TemporaryDirectory()
        self.hass = rig.FakeHass(self.tmp.name)
        self.cfg = rig.setup(self.hass)
        self.c = rig.controller.ChargingController(self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        await self.c.async_load()
        self.c.start()
        await asyncio.sleep(.01)

    async def asyncTearDown(self):
        await self.c.async_close()
        self.tmp.cleanup()

    def report(self, name, value):
        self.hass.states[self.cfg[name]].publish(value)

    async def test_state7_pause_do_not_release_soc_stop_and_real_state3_does(self):
        # A SOC stop write was dispatched before a temporary BLE state 7
        # and became an unresolved attempt in prior iterations persisted HA storage.
        self.c._saved_attempt = {"kind": "soc_stop", "operation": "stop-from-prior iterations"}
        self.c._blocked = "previous_command_unconfirmed_no_retry"
        self.c.real_enabled = False
        self.report(C.CONF_START_STOP, "off")
        self.report(C.CONF_DPM_CONFIRMED, "0")
        self.report(C.CONF_WALLBOX_CHARGING, "off")
        self.report(C.CONF_EV_POWER, "0.004")
        self.report(C.CONF_CHARGE_STATE, "Stato transitorio")
        self.report(C.CONF_WALLBOX_CONNECTED, "off")
        self.c.refresh()
        await asyncio.sleep(.01)
        self.assertIsNotNone(self.c._saved_attempt)
        self.assertIsNone(self.c._pending)
        self.assertFalse(any(x[:2] == ("switch", "turn_on") for x in self.hass.services.calls))
        self.report(C.CONF_CHARGE_STATE, "Pause")
        self.report(C.CONF_WALLBOX_CONNECTED, "on")
        self.c.refresh()
        self.assertIsNotNone(self.c._saved_attempt)
        self.report(C.CONF_CHARGE_STATE, "Cable Unplugged")
        self.report(C.CONF_WALLBOX_CONNECTED, "off")
        self.c.refresh()
        self.assertIsNotNone(self.c._unplug_since)
        self.assertIsNotNone(self.c._saved_attempt)
        # A stable 69-second state-3 period containing several real AD
        # messages is mimicked in the isolated test with a clock backdate.
        self.c._unplug_since = datetime.now(timezone.utc)-timedelta(seconds=70)
        self.report(C.CONF_CHARGE_STATE, "Cable Unplugged")  # New AD report
        self.c.refresh()
        await asyncio.sleep(.03)
        self.assertEqual(self.c._saved_attempt["kind"], "normalize_on")
        self.assertEqual(
            [x[:2] for x in self.hass.services.calls if x[0] == "switch"],
            [("switch", "turn_on")])
        self.assertIsNotNone(self.c._pending)
        self.assertEqual(self.c._pending.kind, "normalize_on")
        self.report(C.CONF_START_STOP, "on")
        self.report(C.CONF_DPM_CONFIRMED, "4.4")
        self.c.refresh()
        await asyncio.sleep(.02)
        self.assertIsNone(self.c._pending)
        self.assertFalse(self.c._standby_restore_due)

    async def test_eta_remains_stable_while_soc_is_unchanged_and_shelly_delivers(self):
        """15-min vehicle SOC hold must not shift ETA by 15 minutes."""
        self.c._delivery_last = self.c._soc_anchor = None
        self.c._delivered_ev_kwh = 0.0
        self.c._delivery_gap = False
        t = datetime.now(timezone.utc)-timedelta(minutes=11)
        car = self.c.cfg[C.CONF_VEHICLES][0]
        self.report(C.CONF_WALLBOX_CHARGING, "on")
        self.report(C.CONF_EV_POWER, 3.6)
        meter = self.hass.states[self.cfg[C.CONF_EV_POWER]]
        soc_source = self.hass.states[car[C.CONF_SOC]]
        soc_source.publish("85")
        soc_source.last_reported = soc_source.last_updated = t
        meter.last_reported = meter.last_updated = t
        remaining = (90-85)/100*42/.90
        self.c._record_ev_delivery(t, 3.6, True)
        first = self.c._energy_after_soc(t, car, 85., remaining)
        self.assertAlmostEqual(first, remaining)
        for minute in range(1,11):
            at = t + timedelta(minutes=minute)
            meter.last_reported = meter.last_updated = at
            self.c._record_ev_delivery(at, 3.6, True)
        last = self.c._energy_after_soc(t+timedelta(minutes=10), car, 85., remaining)
        self.assertAlmostEqual(last, remaining-.6, places=5)
        eta_before = t + timedelta(hours=first/3.6)
        eta_after = t+timedelta(minutes=10) + timedelta(hours=last/3.6)
        self.assertLess(abs((eta_after-eta_before).total_seconds()), 2)

    async def test_meter_gap_preserves_conservative_margin_until_new_soc(self):
        self.c._delivery_last = self.c._soc_anchor = None
        self.c._delivered_ev_kwh = 0.0
        self.c._delivery_gap = False
        t = datetime.now(timezone.utc)-timedelta(minutes=12)
        car = self.c.cfg[C.CONF_VEHICLES][0]
        meter = self.hass.states[self.cfg[C.CONF_EV_POWER]]
        soc_state = self.hass.states[car[C.CONF_SOC]]
        soc_state.publish("75")
        soc_state.last_reported = soc_state.last_updated = t
        meter.publish("3.5")
        meter.last_reported = meter.last_updated = t
        self.c._record_ev_delivery(t, 3.5, True)
        self.assertIsNotNone(self.c._energy_after_soc(t, car, 75, 7.0))
        gap = t+timedelta(minutes=6)
        meter.last_reported = meter.last_updated = gap
        self.c._record_ev_delivery(gap, 3.5, True)
        # The missing interval is never credited as delivered energy.
        # Conservative margin remains available; advisory ETA is suppressed
        # by _snapshot while the gap is unresolved.
        self.assertAlmostEqual(self.c._energy_after_soc(gap, car, 75, 7.0), 7.0)
        self.assertTrue(self.c._delivery_gap)
        # Only a genuinely changed SOC repairs the anchor.
        soc_state.publish("78")
        soc_state.last_reported = soc_state.last_updated = gap
        self.assertAlmostEqual(self.c._energy_after_soc(gap, car, 78, 6.0), 6.0)

    async def test_external_manual_dpm_zero_is_never_auto_restored(self):
        self.report(C.CONF_CHARGE_STATE, "Cable Unplugged")
        self.report(C.CONF_WALLBOX_CONNECTED, "off")
        self.report(C.CONF_WALLBOX_CHARGING, "off")
        self.report(C.CONF_EV_POWER, 0)
        self.report(C.CONF_DPM_CONFIRMED, 0)
        self.report(C.CONF_START_STOP, "off")
        self.c.refresh()
        await asyncio.sleep(.02)
        self.assertFalse(self.c._standby_restore_due)
        self.assertFalse(any(x[:2] == ("switch", "turn_on") for x in self.hass.services.calls))


    async def test_shelly_on_ble_reconnect_waits_for_valid_switch_then_one_on(self):
        """Power-on needs a real relay edge, BLE off->on, and fresh DPM0."""
        relay = "switch.shelly_wallbox"
        self.c.cfg[C.CONF_WALLBOX_POWER_SWITCH] = relay
        self.hass.states[relay] = rig.FakeState("off")
        self.report(C.CONF_BLE_CONNECTED, "off")
        self.c.refresh()
        self.c.mode = "automatic"
        self.report(C.CONF_WALLBOX_CONNECTED, "off")
        self.report(C.CONF_WALLBOX_CHARGING, "off")
        self.report(C.CONF_EV_POWER, "0")
        self.hass.states[relay].publish("on")
        self.c._on_event(SimpleNamespace(data={
            "entity_id": relay, "old_state": rig.FakeState("off"),
            "new_state": rig.FakeState("on")}))
        self.assertIsNotNone(self.c._supply_restore_candidate)
        self.report(C.CONF_BLE_CONNECTED, "on")
        self.c.refresh()
        self.report(C.CONF_WALLBOX_CONNECTED, "off")
        self.report(C.CONF_CHARGE_STATE, "Cable Unplugged")
        self.report(C.CONF_WALLBOX_CHARGING, "off")
        self.report(C.CONF_EV_POWER, "0")
        self.report(C.CONF_DPM_CONFIRMED, "0")
        self.report(C.CONF_START_STOP, "unavailable")
        self.c.refresh()
        await asyncio.sleep(.02)
        self.assertFalse(any(x[:2] == ("switch", "turn_on")
                             for x in self.hass.services.calls))
        self.report(C.CONF_START_STOP, "off")
        self.c.refresh()
        await asyncio.sleep(.03)
        self.assertEqual(self.c._pending.kind, "supply_restore")
        self.assertEqual([x[:2] for x in self.hass.services.calls
                          if x[0] == "switch"], [("switch", "turn_on")])
        self.report(C.CONF_DPM_CONFIRMED, "4.4")
        self.report(C.CONF_START_STOP, "on")
        self.c.refresh()
        self.assertIsNone(self.c._pending)
        self.c.refresh()
        await asyncio.sleep(.02)
        self.assertEqual(len([x for x in self.hass.services.calls
                              if x[:2] == ("switch", "turn_on")]), 1)

    async def test_shelly_power_on_without_ble_edge_or_after_deadline_does_not_write(self):
        relay = "switch.shelly_wallbox"
        self.c.cfg[C.CONF_WALLBOX_POWER_SWITCH] = relay
        self.hass.states[relay] = rig.FakeState("on")
        self.report(C.CONF_WALLBOX_CONNECTED, "off")
        self.report(C.CONF_WALLBOX_CHARGING, "off")
        self.report(C.CONF_CHARGE_STATE, "Cable Unplugged")
        self.report(C.CONF_EV_POWER, "0")
        self.report(C.CONF_DPM_CONFIRMED, "0")
        self.report(C.CONF_START_STOP, "off")
        self.c._on_event(SimpleNamespace(data={
            "entity_id": relay, "old_state": rig.FakeState("off"),
            "new_state": rig.FakeState("on")}))
        self.c.refresh()  # BLE was already ON: no OFF->ON seen.
        await asyncio.sleep(.02)
        self.assertFalse(self.c._supply_ble_rejoined)
        self.assertFalse(any(x[0] == "switch" for x in self.hass.services.calls))
        self.report(C.CONF_BLE_CONNECTED, "off")
        self.c.refresh()
        self.c._supply_restore_candidate = (
            datetime.now(timezone.utc) - timedelta(seconds=121))
        self.report(C.CONF_BLE_CONNECTED, "on")
        self.c.refresh()
        await asyncio.sleep(.02)
        self.assertFalse(any(x[0] == "switch" for x in self.hass.services.calls))

    async def test_manual_to_auto_issues_one_verified_on_if_off(self):
        self.report(C.CONF_WALLBOX_CHARGING, "off")
        self.report(C.CONF_CHARGE_STATE, "Vehicle ready")
        self.report(C.CONF_EV_POWER, "0")
        self.report(C.CONF_DPM_CONFIRMED, "0")
        self.report(C.CONF_START_STOP, "off")
        await self.c.async_change("mode", "manual")
        await self.c.async_change("mode", "automatic")
        self.assertEqual([x[:2] for x in self.hass.services.calls
                          if x[0] == "switch"], [("switch", "turn_on")])
        self.assertEqual(self.c._pending.kind, "mode_auto_on")
        self.report(C.CONF_DPM_CONFIRMED, "4.4")
        self.report(C.CONF_START_STOP, "on")
        self.c.refresh()
        self.assertIsNone(self.c._pending)
        await self.c.async_change("mode", "automatic")
        self.assertEqual(len([x for x in self.hass.services.calls
                              if x[:2] == ("switch", "turn_on")]), 1)

    async def test_manual_mode_returns_auto_on_unplug_then_on_after_69s(self):
        await self.c.async_change("mode", "manual")
        self.report(C.CONF_WALLBOX_CHARGING, "off")
        self.report(C.CONF_EV_POWER, "0")
        self.report(C.CONF_DPM_CONFIRMED, "0")
        self.report(C.CONF_START_STOP, "off")
        self.report(C.CONF_WALLBOX_CONNECTED, "off")
        self.report(C.CONF_CHARGE_STATE, "Cable Unplugged")
        self.c.refresh()
        self.assertEqual(self.c.mode, "automatic")
        self.assertIsNotNone(self.c._unplug_restore_since)
        self.assertIsNone(self.c._pending)
        self.c._unplug_restore_since = datetime.now(timezone.utc)-timedelta(seconds=70)
        self.report(C.CONF_CHARGE_STATE, "Cable Unplugged")
        self.c.refresh()
        await asyncio.sleep(.03)
        self.assertEqual(self.c._pending.kind, "normalize_on")
        self.assertEqual([x[:2] for x in self.hass.services.calls
                          if x[0] == "switch"], [("switch", "turn_on")])


class RC7Policy(unittest.TestCase):
    def test_urgent_strong_pressure_does_not_add_discretionary_cap(self):
        # prior iterations deliberately rejects a nominally zero-loss cap in urgency:
        # the DPM already throttles, while a cap would create a new BLE
        # write on high load and an immediate restore on the next low.
        sample = policy_rig.sample
        evaluate = policy_rig.policy.evaluate
        st = None
        for minute in (0, 1, 2):
            st, decision = evaluate(sample(minute, house=2.3, margin=-30,
                                           budget=0), st)
            self.assertEqual(decision.action, "none")
            self.assertEqual(decision.reason, "urgent_no_new_discretionary_cap")
        self.assertEqual(st.phase, "NORMAL")
        st, later = evaluate(sample(3, house=.1, current=4.0,
                                   margin=-30, budget=0), st)
        self.assertEqual(later.action, "none")

    def test_unknown_deadline_does_not_sacrifice_energy_under_strong_load(self):
        sample = policy_rig.sample
        evaluate = policy_rig.policy.evaluate
        st = None
        for minute in (0,1,2,3):
            st, decision = evaluate(sample(minute, house=2.3, margin=None, budget=0), st)
        self.assertEqual(st.phase, "NORMAL")


class RC7Forecast(unittest.TestCase):
    def test_provisional_eta_before_conservative_6_min_window(self):
        t = datetime(2026,11,22,0,0,tzinfo=timezone.utc)
        samples = [(t+timedelta(minutes=i), .15) for i in (0,1,2)]
        provisional = planner.estimate_forecast_ac_kw(
            now=t+timedelta(minutes=2), dpm_kw=4.4, ev_base_kw=4,
            house_samples=samples)
        conservative = planner.estimate_ac_kw(
            now=t+timedelta(minutes=2), dpm_kw=4.4, ev_base_kw=4,
            house_samples=samples)
        self.assertEqual(provisional, 4.0)
        self.assertIsNone(conservative)


if __name__=="__main__":
    unittest.main()
