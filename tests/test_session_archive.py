"""Firmware totals, physical session boundaries, and persisted HA snapshots."""
import asyncio
import unittest
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta, timezone

import test_controller_smoke as rig
from easywallbox_test_package.session_archive import SessionArchive

C = rig.const


class ArchiveIntegration(unittest.IsolatedAsyncioTestCase):
    def make_archive(self, hass, *, cable=True, report=None):
        cfg = rig.setup(hass, cable=cable, charging=cable)
        cfg[C.CONF_SESSION_ENERGY] = "sensor.session_energy"
        cfg[C.CONF_SESSION_DURATION] = "sensor.session_duration"
        hass.states["sensor.session_energy"] = rig.FakeState("0", "kWh")
        hass.states["sensor.session_duration"] = rig.FakeState("0", "min")
        return SessionArchive(hass, rig.FakeEntry(cfg), cfg, lambda: None, report)

    @staticmethod
    def counters(hass, energy, minutes):
        hass.states["sensor.session_energy"].publish(str(energy))
        hass.states["sensor.session_duration"].publish(str(minutes))

    @staticmethod
    def publish(hass, archive, key, value):
        hass.states[archive.cfg[key]].publish(value)

    def unplug(self, hass, archive):
        for key, value in ((C.CONF_CHARGE_STATE, "Cable Unplugged"),
                           (C.CONF_WALLBOX_CHARGING, "off"),
                           (C.CONF_WALLBOX_CONNECTED, "off")):
            self.publish(hass, archive, key, value)
            archive._observe()

    def replug(self, hass, archive):
        for key, value in ((C.CONF_CHARGE_STATE, "Vehicle ready"),
                           (C.CONF_WALLBOX_CONNECTED, "on")):
            self.publish(hass, archive, key, value)
            archive._observe()

    def offline(self, hass, archive):
        for key, value in ((C.CONF_BLE_CONNECTED, "off"),
                           (C.CONF_TELEMETRY_FRESH, "off"),
                           (C.CONF_CHARGE_STATE, "Unavailable"),
                           (C.CONF_WALLBOX_CONNECTED, "unknown"),
                           (C.CONF_WALLBOX_CHARGING, "unknown")):
            self.publish(hass, archive, key, value)
            archive._observe()

    def reset(self, hass, archive):
        hass.states["sensor.session_energy"].publish("0")
        archive._observe()
        hass.states["sensor.session_duration"].publish("0")
        archive._observe()

    async def test_absolute_totals_pause_and_separate_reset_reports(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            events = []
            a = self.make_archive(hass, report=lambda *args, **kw: events.append((args, kw)))
            await a.async_load()
            a.start()
            a.note_vehicle("Kia")
            self.counters(hass, 11.6, 207)
            a._observe()
            self.publish(hass, a, C.CONF_CHARGE_STATE, "Pause")
            self.publish(hass, a, C.CONF_WALLBOX_CHARGING, "off")
            a._observe()
            self.counters(hass, 14.8, 277)
            a._observe()
            self.assertEqual(a.status()["active_energy_kwh"], 14.8)
            self.assertEqual(a.status()["active_duration_min"], 277)
            self.unplug(hass, a)
            self.assertEqual(a.total, 0)
            unplug_at = a._active["unplug_at"]
            self.assertTrue(a.status()["awaiting_firmware_reset"])
            hass.states["sensor.session_energy"].publish("0")
            a._observe()
            self.assertEqual(a.total, 0)
            self.assertEqual(a.status()["active_energy_kwh"], 14.8)
            hass.states["sensor.session_duration"].publish("0")
            a._observe()
            self.assertEqual(a.total, 1)
            row = a.sessions[0]
            self.assertEqual((row["energy_kwh"], row["duration_min"]), (14.8, 277))
            self.assertEqual(row["vehicle"], "Kia")
            self.assertEqual(row["completed_at"], unplug_at)
            self.assertEqual(row["completion"], "physical_cable_unplug")
            self.assertEqual(a.status()["last_outcome"], "record_saved_on_firmware_reset")
            self.assertEqual(events[0][0], ("archive", "firmware_session_closed"))
            a._observe()
            self.assertEqual(a.total, 1)
            self.assertEqual(hass.services.calls, [])
            await a.async_close()

    async def test_brief_replug_does_not_create_row_or_double_count(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            await a.async_load()
            a.start()
            self.counters(hass, 5.0, 90)
            a._observe()
            self.unplug(hass, a)
            self.assertEqual(a.total, 0)
            self.replug(hass, a)
            self.assertFalse(a.status()["awaiting_firmware_reset"])
            self.counters(hass, 7.0, 130)
            a._observe()
            self.unplug(hass, a)
            self.reset(hass, a)
            self.assertEqual(a.total, 1)
            self.assertEqual((a.sessions[0]["energy_kwh"], a.sessions[0]["duration_min"]),
                             (7.0, 130))
            await a.async_close()

    async def test_offline_after_unplug_waits_for_firmware_zero(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            await a.async_load()
            a.start()
            self.counters(hass, 6.2, 102)
            a._observe()
            self.unplug(hass, a)
            self.offline(hass, a)
            self.assertEqual(a.total, 0)
            self.assertTrue(a.status()["awaiting_firmware_reset"])
            a._observe()
            self.assertEqual(a.total, 0)
            self.reset(hass, a)
            self.assertEqual(a.total, 1)
            self.assertEqual(a.sessions[0]["completion"], "unplug_telemetry_timeout")
            self.assertEqual(a.sessions[0]["quality"], "partial_observed")
            self.assertEqual(a.sessions[0]["energy_kwh"], 6.2)
            await a.async_close()

    async def test_ble_offline_without_unplug_cannot_close_session(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            a.start()
            self.counters(hass, 8.0, 140)
            a._observe()
            self.offline(hass, a)
            self.reset(hass, a)  # even an unexpected zero is not unplug proof
            self.assertEqual(a.total, 0)
            self.assertEqual(a.status()["active_energy_kwh"], 8.0)
            self.assertFalse(a.status()["awaiting_firmware_reset"])
            await a.async_close()

    async def test_explicit_error_revokes_unplug_evidence(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            a.start()
            self.counters(hass, 2.0, 30)
            a._observe()
            self.unplug(hass, a)
            self.publish(hass, a, C.CONF_CHARGE_STATE, "Error")
            a._observe()
            self.offline(hass, a)
            self.reset(hass, a)
            self.assertEqual(a.total, 0)
            self.assertFalse(a.status()["awaiting_firmware_reset"])
            await a.async_close()

    async def test_restart_retains_pending_snapshot_and_no_duplicate(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            a.start()
            self.counters(hass, 4.5, 67)
            a._observe()
            self.unplug(hass, a)
            await a.async_close()
            saved = a._store.content
            b = SessionArchive(hass, a.entry, a.cfg, lambda: None)
            b._store.async_load = lambda: asyncio.sleep(0, result=saved)
            await b.async_load()
            b.start()
            self.assertEqual(b.total, 0)
            self.assertEqual(b.status()["active_energy_kwh"], 4.5)
            self.reset(hass, b)
            self.assertEqual(b.total, 1)
            self.assertEqual(b.sessions[0]["duration_min"], 67)
            await b.async_close()
            c = SessionArchive(hass, a.entry, a.cfg, lambda: None)
            c._store.async_load = lambda: asyncio.sleep(0, result=b._store.content)
            await c.async_load()
            c.start()
            self.assertEqual(c.total, 1)
            await c.async_close()

    async def test_startup_mid_session_uses_full_firmware_totals(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            self.counters(hass, 17.0, 205)
            a.start()
            self.counters(hass, 18.2, 227)
            a._observe()
            self.unplug(hass, a)
            self.reset(hass, a)
            self.assertEqual(a.sessions[0]["energy_kwh"], 18.2)
            self.assertEqual(a.sessions[0]["duration_min"], 227)
            await a.async_close()

    async def test_old_completed_records_preserved_but_rc_active_not_added(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            old = {"sessions": [
                {"energy_kwh": 11.6, "duration_min": 207},
                {"completion": "physical_cable_unplug", "energy_kwh": 7.5,
                 "duration_min": 123}],
                "total": 2,
                "active": {"connected_seen": True, "counters": {
                    "energy": {"total": 20}, "duration": {"total": 300}}}}
            a._store.async_load = lambda: asyncio.sleep(0, result=old)
            await a.async_load()
            self.assertEqual(a.total, 1)
            self.assertIsNone(a._active)
            self.assertEqual(a.status()["last_outcome"], "legacy_active_not_migrated")
            self.counters(hass, 3.5, 65)
            a.start()
            self.unplug(hass, a)
            self.reset(hass, a)
            self.assertEqual(a.total, 2)
            self.assertEqual(a.sessions[-1]["energy_kwh"], 3.5)
            await a.async_close()

    async def test_unexpected_decrease_while_connected_is_not_summed(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            a.start()
            self.counters(hass, 5.0, 90)
            a._observe()
            self.counters(hass, 4.0, 80)
            a._observe()
            self.assertEqual(a.total, 0)
            self.assertTrue(a.status()["active_partial"])
            self.counters(hass, 6.0, 100)
            a._observe()
            self.unplug(hass, a)
            self.reset(hass, a)
            self.assertEqual(a.sessions[0]["energy_kwh"], 6.0)
            self.assertEqual(a.sessions[0]["quality"], "partial_observed")
            await a.async_close()

    async def test_stable_totals_after_hours_and_late_unplug(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            a.start()
            self.counters(hass, 18.5, 310)
            a._observe()
            old = datetime.now(timezone.utc)-timedelta(hours=4)
            for key in (C.CONF_BLE_CONNECTED, C.CONF_WALLBOX_CONNECTED,
                        C.CONF_WALLBOX_CHARGING, C.CONF_SESSION_ENERGY,
                        C.CONF_SESSION_DURATION):
                hass.states[a.cfg[key]].last_reported = old
            self.unplug(hass, a)
            self.reset(hass, a)
            self.assertEqual(a.sessions[0]["energy_kwh"], 18.5)
            self.assertEqual(a.sessions[0]["duration_min"], 310)
            await a.async_close()

    async def test_unavailable_or_restored_is_not_zero(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            a.start()
            self.counters(hass, 4.2, 60)
            a._observe()
            self.unplug(hass, a)
            self.counters(hass, 0, 0)
            hass.states["sensor.session_duration"].attributes["restored"] = True
            a._observe()
            self.assertEqual(a.total, 0)
            hass.states["sensor.session_duration"].attributes.pop("restored")
            hass.states["sensor.session_duration"].publish("unavailable")
            a._observe()
            self.assertEqual(a.total, 0)
            hass.states["sensor.session_duration"].publish("0")
            a._observe()
            self.assertEqual(a.total, 1)
            await a.async_close()

    async def test_no_charge_no_history_and_new_session_independent(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass, cable=False)
            a.start()
            self.replug(hass, a)
            self.unplug(hass, a)
            self.assertEqual(a.total, 0)
            self.replug(hass, a)
            self.counters(hass, 1.4, 31)
            a._observe()
            self.unplug(hass, a)
            self.reset(hass, a)
            self.replug(hass, a)
            self.counters(hass, 2.2, 57)
            a._observe()
            self.unplug(hass, a)
            self.reset(hass, a)
            self.assertEqual([x["energy_kwh"] for x in a.sessions], [1.4, 2.2])
            await a.async_close()

    async def test_archive_disabled_has_diagnostic_reason(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            a.enabled = False
            self.assertEqual(a.status()["reason_if_disabled"],
                             "missing_session_energy_or_duration")

    async def test_native_units_converted_without_arithmetic_accumulation(self):
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            a = self.make_archive(hass)
            a.start()
            hass.states["sensor.session_energy"].attributes["unit_of_measurement"] = "Wh"
            hass.states["sensor.session_duration"].attributes["unit_of_measurement"] = "h"
            self.counters(hass, 4500, 1.5)
            a._observe()
            self.unplug(hass, a)
            self.reset(hass, a)
            self.assertEqual((a.sessions[0]["energy_kwh"], a.sessions[0]["duration_min"]),
                             (4.5, 90))
            await a.async_close()


if __name__ == "__main__":
    unittest.main()
