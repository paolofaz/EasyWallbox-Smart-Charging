"""prior iterations regression for optional Shelly supply ownership and unlimited history.

All observations are synthetic, no BLE or electrical hardware is used.
"""
import asyncio
import types
import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import test_controller_smoke as rig
from easywallbox_test_package.session_archive import SessionArchive

C = rig.const


class OptionalSupply(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.hass = rig.FakeHass(self.tmp.name)
        self.cfg = rig.setup(self.hass, cable=False, charging=False)
        self.cfg[C.CONF_WALLBOX_POWER_SWITCH] = "switch.shelly_supply"
        self.hass.states["switch.shelly_supply"] = rig.FakeState("on")
        self.hass.states[self.cfg[C.CONF_START_STOP]].publish("off")
        self.hass.states[self.cfg[C.CONF_DPM_CONFIRMED]].publish("0")
        self.c = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        await self.c.async_load()
        self.c.real_enabled = True
        self.c.start()

    async def asyncTearDown(self):
        await self.c.async_close()
        self.tmp.cleanup()

    def event(self, entity, old, new):
        self.hass.states[entity].publish(new)
        self.c._on_event(types.SimpleNamespace(data={
            "entity_id": entity, "old_state": rig.FakeState(old),
            "new_state": rig.FakeState(new)}))

    async def _real_cycle(self):
        relay = self.cfg[C.CONF_WALLBOX_POWER_SWITCH]
        ble = self.cfg[C.CONF_BLE_CONNECTED]
        self.event(relay, "on", "off")
        self.event(ble, "on", "off")
        self.c._supply_off_since = datetime.now(timezone.utc)-timedelta(seconds=8)
        self.event(relay, "off", "on")
        self.assertIsNotNone(self.c._supply_restore_candidate)
        self.event(ble, "off", "on")
        self.assertTrue(self.c._supply_ble_rejoined)

    async def _fresh_unplug(self):
        # Real ESPHome re-publishes AD flags and EEPROM after BLE reconnect.
        charge = self.cfg[C.CONF_CHARGE_STATE]
        self.hass.states[self.cfg[C.CONF_WALLBOX_CONNECTED]].publish("off")
        self.hass.states[self.cfg[C.CONF_WALLBOX_CHARGING]].publish("off")
        self.hass.states[self.cfg[C.CONF_DPM_CONFIRMED]].publish("0")
        self.hass.states[charge].publish("Cable Unplugged")
        self.c.refresh()
        self.assertIsNotNone(self.c._unplug_since)
        self.c._unplug_since = datetime.now(timezone.utc)-timedelta(seconds=70)
        self.hass.states[charge].publish("Cable Unplugged")
        self.c.refresh()
        await asyncio.sleep(.05)

    async def test_power_cycle_requires_actual_shelly_off_on_and_ble_down(self):
        self.c.refresh()
        await asyncio.sleep(.01)
        self.assertEqual(self.hass.services.calls, [])
        # BLE reconnect while Shelly remains ON is not a power cycle.
        self.event(self.cfg[C.CONF_BLE_CONNECTED], "on", "off")
        self.event(self.cfg[C.CONF_BLE_CONNECTED], "off", "on")
        await asyncio.sleep(.01)
        self.assertIsNone(self.c._supply_restore_candidate)
        self.assertEqual(self.hass.services.calls, [])
        # A Shelly OFF/ON without witnessing the wallbox BLE offline also fails closed.
        relay = self.cfg[C.CONF_WALLBOX_POWER_SWITCH]
        self.event(relay, "on", "off")
        self.c._supply_off_since = datetime.now(timezone.utc)-timedelta(seconds=8)
        self.event(relay, "off", "on")
        self.assertIsNone(self.c._supply_restore_candidate)
        self.assertEqual(self.hass.services.calls, [])

    async def test_actual_shelly_cycle_restores_once_only_after_verified_unplug(self):
        await self._real_cycle()
        self.c.refresh()
        self.assertEqual(self.hass.services.calls, [])  # Not after one AD report
        await self._fresh_unplug()
        self.assertEqual(
            [x[:2] for x in self.hass.services.calls if x[0] == "switch"],
            [("switch", "turn_on")])
        self.assertEqual(self.c._pending.kind, "supply_restore")
        self.hass.states[self.cfg[C.CONF_DPM_CONFIRMED]].publish("4.4")
        self.hass.states[self.cfg[C.CONF_START_STOP]].publish("on")
        self.c.refresh()
        await asyncio.sleep(.02)
        self.assertIsNone(self.c._pending)
        self.assertIsNone(self.c._supply_restore_candidate)
        self.c.refresh()
        await asyncio.sleep(.02)
        self.assertEqual(
            sum(x[0] == "switch" and x[1] == "turn_on"
                for x in self.hass.services.calls), 1)

    async def test_cycle_cannot_start_an_attached_vehicle(self):
        await self._real_cycle()
        self.hass.states[self.cfg[C.CONF_WALLBOX_CONNECTED]].publish("on")
        self.hass.states[self.cfg[C.CONF_CHARGE_STATE]].publish("Pause")
        self.c.refresh()
        await asyncio.sleep(.02)
        self.assertFalse(any(x[:2] == ("switch", "turn_on")
                             for x in self.hass.services.calls))

    async def test_owned_session_is_not_blocked_during_69s_state3_confirmation(self):
        # A real charge had previously written an EV limit. The first
        # unplug AD report must NOT trigger "session_continuity_unverified"
        # while the positive physical unplug debounce is running.
        self.c._trace_session = "old-charging-session"
        self.c._last_cable = True
        self.c._owned_limit = 3.0
        self.c._soc_stop_done = True
        self.c._standby_restore_due = True
        self.c.real_enabled = True
        self.c.refresh()
        self.assertIsNotNone(self.c._unplug_since)
        self.assertTrue(self.c._unplug_interruption)
        self.assertIsNone(self.c._blocked)
        self.assertTrue(self.c.real_enabled)
        # If a cable comes back BEFORE the second AD / hold, no old
        # session ownership may carry across to the newly plugged EV.
        self.hass.states[self.cfg[C.CONF_WALLBOX_CONNECTED]].publish("on")
        self.c.refresh()
        self.assertEqual(self.c._blocked, "replug_before_unplug_confirmation")
        self.assertFalse(self.c.real_enabled)
        self.assertFalse(any(x[:2] == ("switch", "turn_on")
                             for x in self.hass.services.calls))

    async def test_nonconfigured_relay_means_no_restore(self):
        self.c.cfg.pop(C.CONF_WALLBOX_POWER_SWITCH)
        await self._real_cycle_without_assertion()
        self.assertIsNone(self.c._supply_restore_candidate)
        self.assertFalse(any(x[:2] == ("switch", "turn_on")
                             for x in self.hass.services.calls))

    async def _real_cycle_without_assertion(self):
        relay = "switch.shelly_supply"
        self.event(relay, "on", "off")
        self.event(self.cfg[C.CONF_BLE_CONNECTED], "on", "off")
        self.event(relay, "off", "on")
        self.event(self.cfg[C.CONF_BLE_CONNECTED], "off", "on")


class ArchivePagination(unittest.IsolatedAsyncioTestCase):
    async def test_unlimited_storage_pagination_and_explicit_prune(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            cfg = rig.setup(hass, cable=False, charging=False)
            cfg[C.CONF_SESSION_ENERGY] = "sensor.energy"
            cfg[C.CONF_SESSION_DURATION] = "sensor.duration"
            archive = SessionArchive(hass, rig.FakeEntry(cfg), cfg, lambda: None)
            await archive.async_load()
            archive.sessions = [
                {"energy_kwh": float(i), "duration_min": i*5,
                 "detected_reset_at": f"2026-11-22T{i%24:02d}:00:00+00:00"}
                for i in range(1, 102)]
            archive.total = 101
            archive.total_observed = 101
            page = archive.page(offset=20, limit=10)
            self.assertEqual((page["count"],len(page["sessions"])), (101, 10))
            self.assertEqual(page["sessions"][0]["energy_kwh"], 81)
            self.assertTrue(page["has_more"])
            self.assertEqual(archive.page(offset=99,limit=10)["has_more"], False)
            result = await archive.async_prune(50)
            self.assertEqual(result, {"removed":51,"retained":50,"total_observed":101})
            self.assertEqual(archive.sessions[0]["energy_kwh"],52)
            self.assertEqual(len(archive._store.content["sessions"]),50)
            again = await archive.async_prune(50)
            self.assertEqual(again["removed"],0)
            with self.assertRaises(ValueError):
                await archive.async_prune(0)
            reloaded = SessionArchive(hass, rig.FakeEntry(cfg), cfg, lambda: None)
            reloaded._store.async_load = lambda: asyncio.sleep(0, result=archive._store.content)
            await reloaded.async_load()
            self.assertEqual(reloaded.total,50)
            self.assertEqual(reloaded.total_observed,101)

    async def test_rc7_storage_migrates_without_deleting_twelve_records(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            cfg = rig.setup(hass)
            cfg[C.CONF_SESSION_ENERGY] = "sensor.energy"
            cfg[C.CONF_SESSION_DURATION] = "sensor.duration"
            obj = SessionArchive(hass, rig.FakeEntry(cfg), cfg, lambda: None)
            records = [{"energy_kwh":1.0,"duration_min":10} for _ in range(12)]
            obj._store.async_load = lambda: asyncio.sleep(
                0,result={"total":35,"sessions":records})
            await obj.async_load()
            self.assertEqual(obj.total,12)  # 12 retained, not invented 35
            self.assertEqual(obj.total_observed,35)
            self.assertEqual(len(obj.sessions),12)


if __name__ == "__main__":
    unittest.main()
