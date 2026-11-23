"""Read-only native session history: only a witnessed paired counter reset."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone

import test_controller_smoke as rig
from easywallbox_test_package.session_archive import JointResetDetector, CounterPair, SessionArchive

T = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)


def report(minute, kwh, duration):
    t = T + timedelta(minutes=minute)
    return CounterPair(kwh, duration, t,
                       (t, t+timedelta(milliseconds=10)))


class JointReset(unittest.TestCase):
    def test_real_reset_archives_last_pre_reset_values_not_startup(self):
        d = JointResetDetector()
        self.assertIsNone(d.observe(report(0, 9.6, 180), True))
        self.assertIsNone(d.observe(report(1, 9.8, 181), True))
        self.assertIsNone(d.observe(report(2, 9.8, 181), True))  # Pause: no reset
        row = d.observe(report(3, .1, 1), True)
        self.assertEqual((row["energy_kwh"], row["duration_min"]), (9.8, 181))
        self.assertIn("detected_reset_at", row)
        self.assertIsNone(d.observe(report(3, .1, 1), True))  # Duplicate
        self.assertIsNone(d.observe(report(4, .2, 2), True))  # Same new session

    def test_missing_one_counter_does_not_archive_or_drop_peak(self):
        d = JointResetDetector()
        d.observe(report(0, 9, 100), True)
        d.observe(report(1, 9.2, 101), True)
        self.assertIsNone(d.observe(report(2, .1, 101), True))
        self.assertIsNone(d.observe(report(3, .1, 101), True))
        row = d.observe(report(4, .1, 0), True)
        self.assertEqual(row["energy_kwh"], 9.2)
        self.assertEqual(row["duration_min"], 101)

    def test_ble_dropout_and_restart_cannot_manufacture_completion(self):
        d = JointResetDetector()
        d.observe(report(0, 11, 220), True)
        d.observe(report(1, 11.1, 221), True)
        self.assertIsNone(d.observe(None, False))  # BLE outage
        self.assertIsNone(d.observe(report(2, 0, 0), True))
        self.assertIsNone(d.observe(report(3, 0.1, 1), True))

    def test_counter_jitter_not_joint_reset(self):
        d = JointResetDetector()
        d.observe(report(0, 10, 200), True)
        d.observe(report(1, 10.1, 201), True)
        self.assertIsNone(d.observe(report(2, 10.0, 200), True))


class Persistence(unittest.IsolatedAsyncioTestCase):
    async def test_duration_resets_on_unplug_energy_only_next_plug(self):
        """Archive at cable-off from LAST connected AD, not next joint reset."""
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            cfg = rig.setup(hass)
            cfg[rig.const.CONF_SESSION_ENERGY] = "sensor.session_energy"
            cfg[rig.const.CONF_SESSION_DURATION] = "sensor.session_duration"
            hass.states["sensor.session_energy"] = rig.FakeState("1.2", "kWh")
            hass.states["sensor.session_duration"] = rig.FakeState("31", "min")
            archive = SessionArchive(hass, rig.FakeEntry(cfg), cfg, lambda: None)
            await archive.async_load()
            archive.start()  # Real cable connected and counters measurable.
            archive._observe()
            # Pause is NOT the end, despite Charging switching OFF.
            hass.states[cfg[rig.const.CONF_WALLBOX_CHARGING]].publish("off")
            archive._observe()
            self.assertEqual(archive.total, 0)
            # AD may report a zero duration BEFORE archive receives cable off.
            hass.states["sensor.session_duration"].publish("0")
            hass.states[cfg[rig.const.CONF_WALLBOX_CONNECTED]].publish("off")
            hass.states[cfg[rig.const.CONF_CHARGE_STATE]].publish("Cable Unplugged")
            archive._observe()
            await archive.async_close()
            self.assertEqual(archive.total, 1)
            self.assertEqual(archive.sessions[0]["duration_min"], 31)
            self.assertEqual(archive.sessions[0]["energy_kwh"], 1.2)
            self.assertEqual(archive.sessions[0]["completion"],
                             "physical_cable_unplug")

    async def test_unplug_archive_survives_later_counter_reset_and_no_duplicates(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            cfg = rig.setup(hass)
            cfg[rig.const.CONF_SESSION_ENERGY] = "sensor.session_energy"
            cfg[rig.const.CONF_SESSION_DURATION] = "sensor.session_duration"
            hass.states["sensor.session_energy"] = rig.FakeState("1.4", "kWh")
            hass.states["sensor.session_duration"] = rig.FakeState("26", "min")
            entry = rig.FakeEntry(cfg)
            archive = SessionArchive(hass, entry, cfg, lambda: None)
            await archive.async_load()
            archive.start()
            hass.states["sensor.session_energy"].publish("1.5")
            hass.states["sensor.session_duration"].publish("27")
            archive._observe()
            hass.states[cfg[rig.const.CONF_WALLBOX_CHARGING]].publish("off")
            hass.states[cfg[rig.const.CONF_WALLBOX_CONNECTED]].publish("off")
            hass.states[cfg[rig.const.CONF_CHARGE_STATE]].publish("Cable Unplugged")
            archive._observe()
            self.assertEqual(archive.total, 1)
            # Next connection resets energy only, minutes were already zero.
            hass.states["sensor.session_duration"].publish("0")
            hass.states["sensor.session_energy"].publish("0")
            hass.states[cfg[rig.const.CONF_WALLBOX_CONNECTED]].publish("on")
            hass.states[cfg[rig.const.CONF_CHARGE_STATE]].publish("Vehicle ready")
            archive._observe()
            self.assertEqual(archive.total, 1)
            await archive.async_close()
            self.assertEqual(archive._store.content["total"], 1)
            boot = SessionArchive(hass, entry, cfg, lambda: None)
            boot._store.async_load = lambda: asyncio.sleep(0, result=archive._store.content)
            await boot.async_load()
            self.assertEqual(boot.total, 1)
            await boot.async_close()

    async def test_unknown_cable_and_ble_loss_cannot_archive_session(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            cfg = rig.setup(hass)
            cfg[rig.const.CONF_SESSION_ENERGY] = "sensor.session_energy"
            cfg[rig.const.CONF_SESSION_DURATION] = "sensor.session_duration"
            hass.states["sensor.session_energy"] = rig.FakeState("1.4", "kWh")
            hass.states["sensor.session_duration"] = rig.FakeState("29", "min")
            archive = SessionArchive(hass, rig.FakeEntry(cfg), cfg, lambda: None)
            await archive.async_load()
            archive.start()
            hass.states[cfg[rig.const.CONF_BLE_CONNECTED]].publish("off")
            hass.states[cfg[rig.const.CONF_WALLBOX_CONNECTED]].publish("off")
            hass.states[cfg[rig.const.CONF_CHARGE_STATE]].publish("Cable Unplugged")
            archive._observe()
            self.assertEqual(archive.total, 0)
            await archive.async_close()

    async def test_archive_survives_restart_without_duplicate(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as wd:
            hass = rig.FakeHass(wd)
            cfg = rig.setup(hass)
            cfg[rig.const.CONF_SESSION_ENERGY] = "sensor.session_energy"
            cfg[rig.const.CONF_SESSION_DURATION] = "sensor.session_duration"
            hass.states["sensor.session_energy"] = rig.FakeState("2.0", "kWh")
            hass.states["sensor.session_duration"] = rig.FakeState("25", "min")
            entry = rig.FakeEntry(cfg)
            archive = SessionArchive(hass, entry, cfg, lambda: None)
            await archive.async_load()
            archive.start()
            hass.states["sensor.session_energy"].publish("2.1")
            hass.states["sensor.session_duration"].publish("26")
            archive._observe()
            hass.states["sensor.session_energy"].publish("0")
            hass.states["sensor.session_duration"].publish("0")
            archive._observe()
            await archive.async_close()
            self.assertEqual(archive.total, 1)
            self.assertEqual(archive.sessions[0]["energy_kwh"], 2.1)
            self.assertEqual(archive.sessions[0]["duration_min"], 26)
            persisted = dict(archive._store.content)
            second = SessionArchive(hass, entry, cfg, lambda: None)
            second._store.async_load = lambda: asyncio.sleep(0, result=persisted)
            await second.async_load()
            self.assertEqual(second.total, 1)
            second.start()  # A restored stale zero must not create a session.
            self.assertEqual(second.total, 1)
            await second.async_close()
            self.assertEqual(hass.services.calls, [])


if __name__ == "__main__":
    unittest.main()
