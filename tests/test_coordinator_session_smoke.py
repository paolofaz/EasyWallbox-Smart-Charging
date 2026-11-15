"""Integration coordinator contract tested with isolated fake HA event APIs.

No network, wallbox, HA services or recorder. The real HA runtime still
requires separate on-device testing before the first public release.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

COMP = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PACKAGE = "_ew_coordinator_session_smoke"


class FakeState:
    def __init__(self, value, unit=None):
        self.state = value
        self.attributes = {"unit_of_measurement": unit}
        self.last_updated = datetime.now(timezone.utc)
        self.last_reported = self.last_updated


class FakeHass:
    def __init__(self, states):
        self.states = states
        self.config = types.SimpleNamespace(time_zone="Europe/Rome")
        self.listeners = []
        self.timers = []

    def watch(self, entities, callback):
        tag = {"entities": set(entities), "active": True}
        self.listeners.append(tag)
        return lambda: tag.update(active=False)

    def track(self, callback, at):
        tag = {"at": at, "active": True}
        self.timers.append(tag)
        return lambda: tag.update(active=False)


def fixture(connected=True, charging=False):
    on = "on" if connected else "off"
    states = {
        "sensor.downstairs": FakeState("1900", "W"),
        "sensor.upstairs": FakeState("350", "W"),
        "sensor.ev": FakeState("3000" if charging else "0", "W"),
        "binary_sensor.wallbox_connected": FakeState(on),
        "binary_sensor.wallbox_charging": FakeState("on" if charging else "off"),
        "binary_sensor.fresh": FakeState("on"),
        "number.limit_requested": FakeState("4.0", "kW"),
        "sensor.limit_confirmed": FakeState("4.0", "kW"),
        "binary_sensor.kia_cable": FakeState(on),
        "binary_sensor.fiat_cable": FakeState("off"),
        "sensor.kia_soc": FakeState("40", "%"),
        "sensor.fiat_soc": FakeState("65", "%"),
    }
    data = {
        "house_downstairs": "sensor.downstairs",
        "house_upstairs": "sensor.upstairs",
        "ev_power": "sensor.ev",
        "wallbox_connected": "binary_sensor.wallbox_connected",
        "wallbox_charging": "binary_sensor.wallbox_charging",
        "telemetry_fresh": "binary_sensor.fresh",
        "requested_limit": "number.limit_requested",
        "confirmed_limit": "sensor.limit_confirmed",
        "dpm_model_kw": 4.3,
        "vehicles": [
            dict(name="Kia EV3", cable="binary_sensor.kia_cable",
                 soc="sensor.kia_soc", target_default=80,
                 capacity_kwh=77, sustainable_kw=4.0, efficiency=.9,
                 departure_weekday="07:00", departure_weekend="08:00"),
            dict(name="Fiat 500e", cable="binary_sensor.fiat_cable",
                 soc="sensor.fiat_soc", target_default=80,
                 capacity_kwh=37, sustainable_kw=3.0, efficiency=.9,
                 departure_weekday="07:00", departure_weekend="08:00"),
        ],
    }
    entry = types.SimpleNamespace(data=data, options={}, entry_id="example-1")
    return FakeHass(states), entry


class TestCoordinatorSessionSmoke(TestCase):
    @classmethod
    def setUpClass(cls):
        homeassistant = types.ModuleType("homeassistant")
        homeassistant.__path__ = []
        ha_core = types.ModuleType("homeassistant.core")
        ha_core.HomeAssistant = FakeHass
        ha_core.callback = lambda fn: fn
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        event = types.ModuleType("homeassistant.helpers.event")
        event.async_track_state_change_event = lambda hass, ids, cb: hass.watch(ids, cb)
        event.async_track_point_in_utc_time = lambda hass, cb, at: hass.track(cb, at)
        cls._module_patch = patch.dict(sys.modules, {
            "homeassistant": homeassistant,
            "homeassistant.core": ha_core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.event": event,
        })
        cls._module_patch.start()
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(COMP)]
        sys.modules[PACKAGE] = package
        spec = importlib.util.spec_from_file_location(
            PACKAGE + ".coordinator", COMP / "coordinator.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.Implementation = module.SimulationCoordinator

    @classmethod
    def tearDownClass(cls):
        cls._module_patch.stop()
        for name in tuple(sys.modules):
            if name == PACKAGE or name.startswith(PACKAGE + "."):
                del sys.modules[name]

    def setup(self, *, connected=True, charging=False):
        hass, entry = fixture(connected=connected, charging=charging)
        coordinator = self.Implementation(hass, entry)
        coordinator.start()
        self.addCleanup(coordinator.close)
        return hass, coordinator

    def setstate(self, hass, entity, value, unit=None):
        hass.states[entity] = FakeState(value, unit)

    def test_boot_connected_requires_mode_confirmation(self):
        _, c = self.setup()
        self.assertEqual(c.control.mode, "RECONCILE")
        self.assertEqual(c.advice.action, "insufficient_data")
        self.assertEqual(c.quality, "session_requires_confirmation")
        self.assertEqual(c.proposal.action, "inactive")

    def test_disconnected_boot_auto_on_next_plug(self):
        h, c = self.setup(connected=False)
        self.assertEqual(c.control.phase, "DISCONNECTED")
        self.setstate(h, "binary_sensor.kia_cable", "on")
        self.setstate(h, "binary_sensor.wallbox_connected", "on")
        c.refresh()
        self.assertEqual(c.control.mode, "AUTO")
        self.assertFalse(c.control.requires_confirmation)

    def test_manual_survives_temporary_unavailable(self):
        h, c = self.setup()
        c.choose_mode("MANUAL")
        self.setstate(h, "binary_sensor.kia_cable", "unavailable")
        c.refresh()
        self.assertEqual((c.control.mode, c.control.phase), ("MANUAL", "UNKNOWN"))
        self.setstate(h, "binary_sensor.kia_cable", "on")
        c.refresh()
        self.assertEqual(c.control.mode, "MANUAL")
        self.assertEqual(c.advice.action, "manual")

    def test_pause_does_not_claim_real_charge_stopped(self):
        h, c = self.setup()
        c.choose_mode("PAUSE")
        self.setstate(h, "binary_sensor.wallbox_charging", "on")
        self.setstate(h, "sensor.ev", "3000", "W")
        c.refresh()
        self.assertEqual(c.control.mode, "PAUSE")
        self.assertEqual(c.control.phase, "CHARGING")
        self.assertTrue(c.session.charging)
        self.assertEqual(c.advice.action, "paused")
        self.assertEqual(c.proposal.action, "inactive")

    def test_charge_now_is_only_virtual_recommendation(self):
        _, c = self.setup()
        c.choose_mode("CHARGE_NOW")
        self.assertEqual(c.control.mode, "CHARGE_NOW")
        self.assertEqual(c.proposal.action, "inactive")
        self.assertEqual(c.advice.action, "start_now")
        self.assertTrue(c.advice.simulation_only)

    def test_explicit_disconnect_clears_pause(self):
        h, c = self.setup()
        c.choose_mode("PAUSE")
        self.setstate(h, "binary_sensor.kia_cable", "off")
        self.setstate(h, "binary_sensor.wallbox_connected", "off")
        c.refresh()
        self.assertEqual((c.control.mode, c.control.phase), ("AUTO", "DISCONNECTED"))
        self.setstate(h, "binary_sensor.kia_cable", "on")
        self.setstate(h, "binary_sensor.wallbox_connected", "on")
        c.refresh()
        self.assertEqual(c.control.mode, "AUTO")

    def test_second_car_without_disconnect_stays_unresolved(self):
        h, c = self.setup()
        c.choose_mode("MANUAL")
        self.setstate(h, "binary_sensor.kia_cable", "off")
        self.setstate(h, "binary_sensor.fiat_cable", "on")
        c.refresh()
        self.assertEqual(c.control.mode, "RECONCILE")
        self.assertTrue(c.control.requires_confirmation)

    def test_house_stream_only_when_actual_charging(self):
        h, c = self.setup()
        # Still connected but stationary: no subscription to two Shellys.
        self.assertIsNone(c._house_unsub)
        self.setstate(h, "binary_sensor.wallbox_charging", "on")
        self.setstate(h, "sensor.ev", "3000", "W")
        c.refresh()
        self.assertIsNotNone(c._house_unsub)
        self.setstate(h, "binary_sensor.wallbox_charging", "off")
        self.setstate(h, "sensor.ev", "0", "W")
        c.refresh()
        self.assertIsNone(c._house_unsub)

    def test_unavailable_cable_does_not_count_as_confirmed_disconnect(self):
        h, c = self.setup()
        c.choose_mode("PAUSE")
        self.setstate(h, "binary_sensor.kia_cable", "unknown")
        self.setstate(h, "binary_sensor.wallbox_connected", "off")
        c.refresh()
        self.assertEqual(c.control.mode, "PAUSE")
        self.assertEqual(c.control.phase, "UNKNOWN")

    def test_mode_selection_requires_known_connection(self):
        h, c = self.setup()
        self.setstate(h, "binary_sensor.kia_cable", "unknown")
        c.refresh()
        with self.assertRaises(ValueError):
            c.choose_mode("AUTO")

if __name__ == "__main__":
    main()
