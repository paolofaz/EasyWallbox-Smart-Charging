"""Clean v0.1 config-entry lifecycle tested with isolated HA stubs.

This is not a Home Assistant runtime test. The entry is newly created through
the UI; no migration or access to the user's HA installation is involved.
"""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PKG = "_ew_fresh_entry_test"


def valid_entry():
    return {
        "house_downstairs": "sensor.down",
        "house_upstairs": "sensor.up",
        "ev_power": "sensor.ev",
        "wallbox_connected": "binary_sensor.wb_connected",
        "wallbox_charging": "binary_sensor.wb_charging",
        "telemetry_fresh": "binary_sensor.wb_fresh",
        "requested_limit": "number.limit",
        "confirmed_limit": "sensor.confirmed",
        "dpm_model_kw": 4.3,
        "vehicles": [{
            "name": "Car", "cable": "binary_sensor.car",
            "soc": "sensor.soc", "target_default": 80,
            "capacity_kwh": 37, "efficiency": .9,
            "sustainable_kw": 3.2,
            "departure_weekday": "07:00",
            "departure_weekend": "08:00",
        }],
    }


class FakeConfigEntries:
    def __init__(self):
        self.forwarded = []
        self.unloaded = []
        self.fail_forward = False
        self.fail_unload = False

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry, tuple(platforms)))
        if self.fail_forward:
            raise RuntimeError("mock forwarding failure")

    async def async_unload_platforms_or_raise(self, entry, platforms):
        self.unloaded.append((entry, tuple(platforms)))
        if self.fail_unload:
            raise RuntimeError("mock unload failure")


class FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = FakeConfigEntries()
        self.created = []


class FakeCoordinator:
    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self.started = False
        self.closed = False
        hass.created.append(self)

    def start(self):
        self.started = True

    def close(self):
        self.closed = True


class TestEntryGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        homeassistant = types.ModuleType("homeassistant")
        homeassistant.__path__ = []
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = FakeHass
        entries = types.ModuleType("homeassistant.config_entries")
        entries.ConfigEntry = object
        exceptions = types.ModuleType("homeassistant.exceptions")
        exceptions.ConfigEntryError = type("ConfigEntryError", (Exception,), {})
        package = types.ModuleType(PKG)
        package.__path__ = [str(ROOT)]
        coordinator = types.ModuleType(PKG + ".coordinator")
        coordinator.SimulationCoordinator = FakeCoordinator
        cls.patch = patch.dict(sys.modules, {
            "homeassistant": homeassistant,
            "homeassistant.core": core,
            "homeassistant.config_entries": entries,
            "homeassistant.exceptions": exceptions,
            PKG: package,
            PKG + ".coordinator": coordinator,
        })
        cls.patch.start()
        spec = importlib.util.spec_from_file_location(PKG + ".__init__", ROOT / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.module = module
        cls.ConfigEntryError = exceptions.ConfigEntryError

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        for name in tuple(sys.modules):
            if name == PKG or name.startswith(PKG + "."):
                del sys.modules[name]

    def entry(self, data):
        return types.SimpleNamespace(
            entry_id="example", version=3, data=data, options={},
        )

    def test_empty_or_malformed_setup_never_starts(self):
        hass = FakeHass()
        entry = self.entry({})
        with self.assertRaises(self.ConfigEntryError):
            asyncio.run(self.module.async_setup_entry(hass, entry))
        self.assertEqual(hass.created, [])
        self.assertEqual(hass.config_entries.forwarded, [])

    def test_invalid_options_do_not_start_adapter(self):
        entry = self.entry(valid_entry())
        entry.options = {"vehicle_overrides": {
            "binary_sensor.not_configured": {"target_default": 70}
        }}
        hass = FakeHass()
        with self.assertRaises(self.ConfigEntryError):
            asyncio.run(self.module.async_setup_entry(hass, entry))
        self.assertEqual(hass.created, [])

    def test_invalid_new_config_is_refused_before_listeners(self):
        cfg = valid_entry()
        cfg["ev_power"] = cfg["house_downstairs"]
        entry, hass = self.entry(cfg), FakeHass()
        with self.assertRaises(self.ConfigEntryError):
            asyncio.run(self.module.async_setup_entry(hass, entry))
        self.assertEqual(hass.created, [])
        self.assertEqual(hass.data, {})

    def test_valid_new_only_creates_simulated_runtime(self):
        entry, hass = self.entry(valid_entry()), FakeHass()
        asyncio.run(self.module.async_setup_entry(hass, entry))
        self.assertEqual(len(hass.created), 1)
        self.assertTrue(hass.created[0].started)
        self.assertIn(entry.entry_id, hass.data["easywallbox_smart"])
        self.assertEqual(len(hass.config_entries.forwarded), 1)
        asyncio.run(self.module.async_unload_entry(hass, entry))
        self.assertTrue(hass.created[0].closed)
        self.assertEqual(hass.data["easywallbox_smart"], {})

    def test_partial_forward_failure_closes_coordinator(self):
        entry, hass = self.entry(valid_entry()), FakeHass()
        hass.config_entries.fail_forward = True
        with self.assertRaises(RuntimeError):
            asyncio.run(self.module.async_setup_entry(hass, entry))
        self.assertTrue(hass.created[0].closed)
        self.assertEqual(hass.data["easywallbox_smart"], {})

    def test_unload_failure_does_not_abandon_live_listeners(self):
        entry, hass = self.entry(valid_entry()), FakeHass()
        asyncio.run(self.module.async_setup_entry(hass, entry))
        hass.config_entries.fail_unload = True
        with self.assertRaises(RuntimeError):
            asyncio.run(self.module.async_unload_entry(hass, entry))
        # Keep reference until unload is actually complete.
        self.assertFalse(hass.created[0].closed)
        self.assertIn(entry.entry_id, hass.data["easywallbox_smart"])


if __name__ == "__main__":
    unittest.main()
