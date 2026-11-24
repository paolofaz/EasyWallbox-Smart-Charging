"""Persistent physical-plug archive, tested without wallbox commands."""
import asyncio
import unittest
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta, timezone

import test_controller_smoke as rig
from easywallbox_test_package.session_archive import SessionArchive


class ArchiveIntegration(unittest.IsolatedAsyncioTestCase):
    def make_archive(self, hass, entry=None):
        cfg = rig.setup(hass)
        cfg[rig.const.CONF_SESSION_ENERGY] = "sensor.session_energy"
        cfg[rig.const.CONF_SESSION_DURATION] = "sensor.session_duration"
        hass.states["sensor.session_energy"] = rig.FakeState("0", "kWh")
        hass.states["sensor.session_duration"] = rig.FakeState("0", "min")
        entry = entry or rig.FakeEntry(cfg)
        return SessionArchive(hass, entry, cfg, lambda: None)

    @staticmethod
    def counters(hass, energy, minutes):
        hass.states["sensor.session_energy"].publish(str(energy))
        hass.states["sensor.session_duration"].publish(str(minutes))

    @staticmethod
    def disconnect(hass, archive):
        cfg = archive.cfg
        hass.states[cfg[rig.const.CONF_WALLBOX_CHARGING]].publish("off")
        hass.states[cfg[rig.const.CONF_WALLBOX_CONNECTED]].publish("off")
        hass.states[cfg[rig.const.CONF_CHARGE_STATE]].publish("Cable Unplugged")
        archive._observe()

    async def test_independent_counters_are_never_lost_to_stamp_skew(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            await archive.async_load()
            archive.start()
            # A minute counter can update while kWh is stable for >4 sec.
            # The next kWh update can similarly arrive with old minutes.
            energy = hass.states["sensor.session_energy"]
            duration = hass.states["sensor.session_duration"]
            duration.publish("6")
            energy.last_reported -= timedelta(seconds=20)
            archive._observe()
            self.assertEqual(archive._active["counters"]["duration"]["total"], 6)
            energy.publish("0.5")
            duration.last_reported -= timedelta(seconds=20)
            archive._observe()
            self.assertAlmostEqual(
                archive._active["counters"]["energy"]["total"], .5)
            duration.publish("7")
            archive._observe()
            self.disconnect(hass, archive)
            self.assertEqual(archive.total, 1)
            self.assertEqual(archive.sessions[0]["energy_kwh"], .5)
            self.assertEqual(archive.sessions[0]["duration_min"], 7)
            self.assertEqual(archive.status()["last_outcome"],
                             "record_saved_on_verified_unplug")
            await archive.async_close()

    async def test_only_one_counter_resets_other_continues(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            await archive.async_load()
            archive.start()
            self.counters(hass, 2.4, 55)
            archive._observe()
            # Energy reset by wallbox but duration does not reset yet.
            hass.states["sensor.session_energy"].publish(".1")
            archive._observe()
            self.counters(hass, .8, 70)
            archive._observe()
            self.disconnect(hass, archive)
            self.assertEqual(archive.total, 1)
            self.assertAlmostEqual(archive.sessions[0]["energy_kwh"], 3.2)
            self.assertEqual(archive.sessions[0]["duration_min"], 70)
            self.assertEqual(archive.sessions[0]["segments"], 2)
            await archive.async_close()

    async def test_initial_nonzero_counters_do_not_duplicate_previous_session(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            self.counters(hass, 17.0, 205)
            await archive.async_load()
            archive.start()
            self.assertEqual(archive._active["counters"]["energy"]["total"], 0)
            self.counters(hass, 18.2, 227)
            archive._observe()
            self.disconnect(hass, archive)
            self.assertEqual(archive.sessions[0]["energy_kwh"], 1.2)
            self.assertEqual(archive.sessions[0]["duration_min"], 22)
            self.assertEqual(archive.sessions[0]["quality"], "partial_observed")
            await archive.async_close()

    async def test_archive_disabled_has_diagnostic_reason(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            archive.cfg.pop(rig.const.CONF_SESSION_DURATION)
            archive.enabled = False
            self.assertEqual(archive.status()["reason_if_disabled"],
                             "missing_session_energy_or_duration")

    async def test_reset_and_pause_sum_only_after_unplug(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            await archive.async_load()
            archive.start()
            cfg = archive.cfg
            archive.note_vehicle(cfg[rig.const.CONF_VEHICLES][0][rig.const.CONF_NAME])
            self.counters(hass, 11.6, 207)
            archive._observe()
            hass.states[cfg[rig.const.CONF_CHARGE_STATE]].publish("Pause")
            hass.states[cfg[rig.const.CONF_WALLBOX_CHARGING]].publish("off")
            archive._observe()
            self.assertEqual(archive.page()["count"], 0)
            # Two counters can reset on two separate HA state callbacks.
            hass.states["sensor.session_energy"].publish("0")
            archive._observe()
            self.assertEqual(archive._active["segments"], 0)
            hass.states["sensor.session_duration"].publish("0")
            archive._observe()
            self.assertEqual(archive._active["segments"], 1)
            self.assertEqual(archive.page()["count"], 0)
            self.counters(hass, 3.2, 70)
            archive._observe()
            self.assertEqual(archive.page()["count"], 0)
            self.disconnect(hass, archive)
            self.assertEqual(archive.page()["count"], 1)
            row = archive.sessions[0]
            self.assertEqual((row["energy_kwh"], row["duration_min"]), (14.8, 277))
            self.assertEqual(row["segments"], 2)
            self.assertEqual(row["completion"], "physical_cable_unplug")
            self.assertEqual(row["vehicle"], cfg[rig.const.CONF_VEHICLES][0][rig.const.CONF_NAME])
            self.assertEqual(hass.services.calls, [])
            await archive.async_close()

    async def test_multiple_resets_and_no_duplicate_unplug(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            await archive.async_load()
            archive.start()
            self.counters(hass, 2.1, 40)
            archive._observe()
            self.counters(hass, 0.1, 1)
            archive._observe()
            self.counters(hass, 1.3, 25)
            archive._observe()
            self.counters(hass, 0.0, 0)
            archive._observe()
            self.counters(hass, 0.8, 17)
            archive._observe()
            self.disconnect(hass, archive)
            archive._observe()
            self.assertEqual(archive.total, 1)
            self.assertEqual(archive.sessions[0]["energy_kwh"], 4.2)
            self.assertEqual(archive.sessions[0]["duration_min"], 82)
            self.assertEqual(archive.sessions[0]["segments"], 3)
            await archive.async_close()

    async def test_unplug_resets_duration_before_final_archiving(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            await archive.async_load()
            archive.start()
            self.counters(hass, 2.2, 57)
            archive._observe()
            hass.states["sensor.session_duration"].publish("0")
            self.disconnect(hass, archive)
            self.assertEqual(archive.sessions[0]["energy_kwh"], 2.2)
            self.assertEqual(archive.sessions[0]["duration_min"], 57)
            await archive.async_close()

    async def test_restart_keeps_unfinished_parts_and_historical_rows(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            await archive.async_load()
            archive.start()
            self.counters(hass, 3.0, 50)
            archive._observe()
            self.counters(hass, 0.0, 0)
            archive._observe()
            self.counters(hass, 1.0, 19)
            archive._observe()
            await archive.async_close()
            saved = dict(archive._store.content)
            self.assertIsNotNone(saved["active"])
            second = SessionArchive(hass, archive.entry, archive.cfg, lambda: None)
            second._store.async_load = lambda: asyncio.sleep(0, result=saved)
            await second.async_load()
            second.start()
            self.assertEqual(second.total, 0)
            self.counters(hass, 2.0, 35)
            second._observe()
            self.disconnect(hass, second)
            self.assertEqual(second.sessions[0]["energy_kwh"], 5.0)
            self.assertEqual(second.sessions[0]["duration_min"], 85)
            self.assertEqual(second.sessions[0]["quality"], "partial_observed")
            await second.async_close()
            third = SessionArchive(hass, archive.entry, archive.cfg, lambda: None)
            third._store.async_load = lambda: asyncio.sleep(0, result=second._store.content)
            await third.async_load()
            self.assertEqual(third.total, 1)
            self.assertEqual(third.sessions[0]["energy_kwh"], 5.0)
            await third.async_close()

    async def test_ble_outage_does_not_lose_or_finalize(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            await archive.async_load()
            archive.start()
            self.counters(hass, 2.0, 37)
            archive._observe()
            cfg = archive.cfg
            hass.states[cfg[rig.const.CONF_BLE_CONNECTED]].publish("off")
            archive._observe()
            hass.states[cfg[rig.const.CONF_WALLBOX_CONNECTED]].publish("off")
            hass.states[cfg[rig.const.CONF_CHARGE_STATE]].publish("Cable Unplugged")
            hass.states[cfg[rig.const.CONF_WALLBOX_CHARGING]].publish("off")
            archive._observe()
            self.assertEqual(archive.total, 0)
            self.assertIsNotNone(archive._active)
            hass.states[cfg[rig.const.CONF_BLE_CONNECTED]].publish("on")
            archive._observe()
            self.assertEqual(archive.total, 1)
            self.assertEqual(archive.sessions[0]["quality"], "partial_observed")
            await archive.async_close()

    async def test_legacy_reset_only_rows_not_misrepresented(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            legacy = {
                "sessions": [
                    {"energy_kwh": 11.6, "duration_min": 207},
                    {"completion": "physical_cable_unplug",
                     "energy_kwh": 7.5, "duration_min": 123},
                ],
                "total": 2,
            }
            archive._store.async_load = lambda: asyncio.sleep(0, result=legacy)
            await archive.async_load()
            self.assertEqual(archive.total, 1)
            self.assertEqual(archive.sessions[0]["energy_kwh"], 7.5)
            await archive.async_close()

    async def test_previous_car_stale_counters_not_in_new_session(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            cfg = archive.cfg
            hass.states[cfg[rig.const.CONF_WALLBOX_CHARGING]].publish("off")
            hass.states[cfg[rig.const.CONF_CHARGE_STATE]].publish("Vehicle ready")
            self.counters(hass, 8.0, 190)
            await archive.async_load()
            archive.start()
            self.assertEqual(archive._active["peak_kwh"], 0)
            hass.states[cfg[rig.const.CONF_WALLBOX_CHARGING]].publish("on")
            archive._observe()
            self.assertEqual(archive._active["peak_kwh"], 0)
            self.counters(hass, 0, 0)
            archive._observe()
            self.counters(hass, 1.4, 31)
            archive._observe()
            self.disconnect(hass, archive)
            self.assertEqual(archive.sessions[0]["energy_kwh"], 1.4)
            self.assertEqual(archive.sessions[0]["duration_min"], 31)
            await archive.async_close()

    async def test_late_unplug_after_hours_with_stable_ble_and_charging_off(self):
        # Connection and Charging can remain unchanged for hours after
        # target SOC is reached; they are states, not periodic samples.
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            await archive.async_load()
            archive.start()
            self.counters(hass, 18.5, 310)
            archive._observe()
            cfg = archive.cfg
            now = datetime.now(timezone.utc)
            old = now - timedelta(hours=4)
            hass.states[cfg[rig.const.CONF_BLE_CONNECTED]].last_reported = old
            hass.states[cfg[rig.const.CONF_WALLBOX_CHARGING]].publish("off")
            hass.states[cfg[rig.const.CONF_WALLBOX_CHARGING]].last_reported = old
            hass.states[cfg[rig.const.CONF_WALLBOX_CONNECTED]].last_reported = old
            archive._observe()
            self.assertIsNotNone(archive._active)
            self.assertFalse(archive._active["continuity_uncertain"])
            hass.states[cfg[rig.const.CONF_WALLBOX_CONNECTED]].publish("off")
            hass.states[cfg[rig.const.CONF_CHARGE_STATE]].publish("Cable Unplugged")
            archive._observe()
            self.assertEqual(archive.total, 1)
            self.assertEqual(archive.sessions[0]["energy_kwh"], 18.5)
            self.assertEqual(archive.sessions[0]["duration_min"], 310)
            await archive.async_close()

    async def test_unplug_without_measured_charge_is_not_history(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            archive = self.make_archive(hass)
            self.counters(hass, 0.0, 0)
            await archive.async_load()
            archive.start()
            archive._observe()
            self.disconnect(hass, archive)
            self.assertEqual(archive.total, 0)
            await archive.async_close()


if __name__ == "__main__":
    unittest.main()
