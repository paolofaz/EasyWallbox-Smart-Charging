"""Isolated fresh GUI installation test with fake Home Assistant flow API.

Exercises user-visible step transitions and persistence shape without needing
a live Home Assistant environment or making any device/service calls.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PACKAGE = "_ew_clean_config_flow_test"


class FakeConfigFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def _async_current_entries(self):
        return getattr(self, "_configured", [])

    async def async_set_unique_id(self, uid):
        self._unique_id = uid

    def _abort_if_unique_id_configured(self):
        return None

    def async_show_form(self, *, step_id, data_schema=None, errors=None):
        return {"type": "form", "step_id": step_id,
                "schema": data_schema, "errors": errors or {}}

    def async_create_entry(self, *, title=None, data=None):
        return {"type": "create_entry", "data": data, "title": title}

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}


class FakeOptionsFlowWithReload(FakeConfigFlow):
    def __init__(self):
        self.config_entry = None


class ConfigEntry:
    pass


class FakeSelector:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs


def vol_stub():
    mod = types.ModuleType("voluptuous")
    mod.Schema = lambda x: x
    mod.Required = lambda key, **kwargs: key
    mod.Optional = lambda key, **kwargs: key
    mod.In = lambda values: values
    return mod


def entity_data():
    return {
        "house_downstairs": "sensor.sotto",
        "house_upstairs": "sensor.sopra",
        "ev_power": "sensor.wallbox",
        "wallbox_connected": "binary_sensor.wb_car",
        "wallbox_charging": "binary_sensor.wb_charging",
        "telemetry_fresh": "binary_sensor.wb_fresh",
        "requested_limit": "number.charge_power",
        "confirmed_limit": "sensor.power_set",
        "dpm_model_kw": 4.3,
    }


def car(name, cable, soc, another=False):
    return {
        "name": name,
        "cable": cable,
        "soc": soc,
        "target_default": 80,
        "capacity_kwh": 37.0 if name == "Fiat" else 77.0,
        "sustainable_kw": 3.2,
        "efficiency": 0.9,
        "departure_weekday": "07:00",
        "departure_weekend": "08:00",
        "add_another": another,
    }


class TestCleanConfigFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        homeassistant = types.ModuleType("homeassistant")
        homeassistant.__path__ = []
        config_entries = types.ModuleType("homeassistant.config_entries")
        config_entries.ConfigFlow = FakeConfigFlow
        config_entries.ConfigEntry = ConfigEntry
        config_entries.OptionsFlowWithReload = FakeOptionsFlowWithReload
        core = types.ModuleType("homeassistant.core")
        core.callback = lambda func: func
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        selector = types.ModuleType("homeassistant.helpers.selector")
        for key in ("EntitySelector", "EntitySelectorConfig", "NumberSelector",
                    "NumberSelectorConfig", "TextSelector"):
            setattr(selector, key, FakeSelector)
        selector.NumberSelectorMode = types.SimpleNamespace(BOX="box")
        cls.patcher = patch.dict(sys.modules, {
            "homeassistant": homeassistant,
            "homeassistant.config_entries": config_entries,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.selector": selector,
            "voluptuous": vol_stub(),
        })
        cls.patcher.start()
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROOT)]
        sys.modules[PACKAGE] = package
        spec = importlib.util.spec_from_file_location(
            PACKAGE + ".config_flow", ROOT / "config_flow.py"
        )
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        for name in tuple(sys.modules):
            if name == PACKAGE or name.startswith(PACKAGE + "."):
                sys.modules.pop(name, None)

    def test_first_install_creates_v1_entry_with_two_cars(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        self.assertEqual(flow.VERSION, 1)
        self.assertEqual(
            asyncio.run(flow.async_step_user())["step_id"], "user"
        )
        out = asyncio.run(flow.async_step_user(entity_data()))
        self.assertEqual(out["step_id"], "vehicle")
        a = car("Fiat", "binary_sensor.fiat", "sensor.fiat_soc", another=True)
        self.assertEqual(
            asyncio.run(flow.async_step_vehicle(a))["step_id"], "vehicle"
        )
        b = car("Kia", "binary_sensor.kia", "sensor.kia_soc")
        done = asyncio.run(flow.async_step_vehicle(b))
        self.assertEqual(done["type"], "create_entry")
        self.assertEqual(len(done["data"]["vehicles"]), 2)
        self.assertTrue(
            self.module.validate(done["data"]).ready
        )
        self.assertNotIn("add_another", done["data"]["vehicles"][0])

    def test_reject_duplicate_house_and_ev_meters(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        chosen = entity_data()
        chosen["ev_power"] = chosen["house_downstairs"]
        response = asyncio.run(flow.async_step_user(chosen))
        self.assertEqual(response["errors"].get("base"), "duplicate_sources")

    def test_second_instance_does_not_create_entry(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        flow._configured = [object()]
        response = asyncio.run(flow.async_step_user(entity_data()))
        self.assertEqual(response, {"type": "abort", "reason": "already_configured"})

    def test_vehicle_with_invalid_time_is_not_saved(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        asyncio.run(flow.async_step_user(entity_data()))
        invalid = car("Kia", "binary_sensor.kia", "sensor.kia_soc")
        invalid["departure_weekday"] = "28:00"
        out = asyncio.run(flow.async_step_vehicle(invalid))
        self.assertEqual(out["errors"].get("base"), "invalid_clock")
        self.assertEqual(flow._vehicles, [])

    def test_options_flow_modifies_only_one_car(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        asyncio.run(flow.async_step_user(entity_data()))
        initial = asyncio.run(flow.async_step_vehicle(
            car("Fiat", "binary_sensor.fiat", "sensor.fiat_soc")
        ))["data"]
        options = self.module.EasyWallboxSmartOptionsFlow()
        options.config_entry = types.SimpleNamespace(data=initial, options={})
        response = asyncio.run(options.async_step_init())
        self.assertEqual(response["step_id"], "init")
        response = asyncio.run(options.async_step_init({"vehicle": "binary_sensor.fiat"}))
        self.assertEqual(response["step_id"], "vehicle")
        values = {
            "target_default": 85,
            "departure_weekday": "06:30",
            "departure_weekend": "09:00",
            "sustainable_kw": 3.2,
            "efficiency": .9,
        }
        result = asyncio.run(options.async_step_vehicle(values))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(
            result["data"]["vehicle_overrides"]["binary_sensor.fiat"]["target_default"],
            85,
        )
        self.assertTrue(self.module.validate(initial, result["data"]).ready)


if __name__ == "__main__":
    unittest.main()
