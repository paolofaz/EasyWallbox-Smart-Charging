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

    def async_show_menu(self, *, step_id, menu_options):
        return {"type": "menu", "step_id": step_id,
                "menu_options": menu_options}


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
        "house_power_sources": ["sensor.sotto", "sensor.sopra"], 
        "session_energy": "sensor.session_energy",
        "session_duration": "sensor.session_duration",
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
        "target_mode": "entity",
        "capacity_kwh": 37.0 if name == "Fiat" else 77.0,
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
                    "NumberSelectorConfig", "SelectSelector", "SelectSelectorConfig",
                    "TextSelector"):
            setattr(selector, key, FakeSelector)
        selector.NumberSelectorMode = types.SimpleNamespace(BOX="box")
        selector.SelectSelectorMode = types.SimpleNamespace(DROPDOWN="dropdown")
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
            asyncio.run(flow.async_step_vehicle(a))["step_id"], "target"
        )
        self.assertEqual(asyncio.run(flow.async_step_target(
            {"target_entity": "number.fiat_target"}))["step_id"], "vehicle")
        b = car("Kia", "binary_sensor.kia", "sensor.kia_soc")
        self.assertEqual(asyncio.run(flow.async_step_vehicle(b))["step_id"], "target")
        done = asyncio.run(flow.async_step_target(
            {"target_entity": "sensor.kia_target"}))
        self.assertEqual(done["type"], "create_entry")
        for vehicle in done["data"]["vehicles"]:
            self.assertEqual(vehicle["target_mode"], "entity")
            self.assertIn("target_entity", vehicle)
            self.assertNotIn("target_default", vehicle)
        self.assertEqual(len(done["data"]["vehicles"]), 2)
        self.assertTrue(
            self.module.validate(done["data"]).ready
        )
        self.assertNotIn("add_another", done["data"]["vehicles"][0])

    def test_reject_duplicate_house_and_ev_meters(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        chosen = entity_data()
        chosen["ev_power"] = chosen["house_power_sources"][0]
        response = asyncio.run(flow.async_step_user(chosen))
        self.assertEqual(response["errors"].get("base"), "duplicate_sources")

    def test_one_house_source_and_optional_counters(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        chosen = entity_data()
        chosen["house_power_sources"] = ["sensor.sotto"]
        chosen.pop("session_energy")
        chosen.pop("session_duration")
        self.assertEqual(asyncio.run(flow.async_step_user(chosen))["step_id"], "vehicle")
        self.assertEqual(asyncio.run(flow.async_step_vehicle(
            car("Fiat", "binary_sensor.fiat", "sensor.fiat_soc")
        ))["step_id"], "target")
        created = asyncio.run(flow.async_step_target(
            {"target_entity": "number.fiat_target"}))
        self.assertTrue(self.module.validate(created["data"]).ready)

    def test_session_counters_must_be_paired(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        chosen = entity_data()
        chosen.pop("session_duration")
        answer = asyncio.run(flow.async_step_user(chosen))
        self.assertEqual(answer["errors"]["base"], "incomplete_counters")

    def test_options_can_reconfigure_sources_on_existing_0_1_0(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        asyncio.run(flow.async_step_user(entity_data()))
        asyncio.run(flow.async_step_vehicle(
            car("Fiat", "binary_sensor.fiat", "sensor.fiat_soc")
        ))
        base = asyncio.run(flow.async_step_target(
            {"target_entity": "number.fiat_target"}))["data"]
        old = dict(base)
        old["vehicles"] = [{**v, "target_default": 80,
                            "target_mode": None} for v in base["vehicles"]]
        for v in old["vehicles"]:
            v.pop("target_mode", None)
        old["house_downstairs"] = "sensor.sotto"
        old["house_upstairs"] = "sensor.sopra"
        old.pop("house_power_sources")
        old.pop("session_energy")
        old.pop("session_duration")
        opts = self.module.EasyWallboxSmartOptionsFlow()
        opts.config_entry = types.SimpleNamespace(data=old, options={})
        initial = asyncio.run(opts.async_step_sources())
        self.assertEqual(initial["step_id"], "sources")
        updated = asyncio.run(opts.async_step_sources({
            "house_power_sources": ["sensor.sotto", "sensor.sopra", "sensor.extra"],
            "session_energy": "sensor.session_energy",
            "session_duration": "sensor.session_duration",
        }))
        self.assertEqual(updated["type"], "create_entry")
        self.assertTrue(self.module.validate(old, updated["data"]).ready)

    def test_shadow_opt_in_and_ev_limits_are_editable_on_existing_entry(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        asyncio.run(flow.async_step_user(entity_data()))
        asyncio.run(flow.async_step_vehicle(
            car("Fiat", "binary_sensor.fiat", "sensor.fiat_soc")
        ))
        data = asyncio.run(flow.async_step_target(
            {"target_entity": "number.fiat_target"}))["data"]
        opts = self.module.EasyWallboxSmartOptionsFlow()
        opts.config_entry = types.SimpleNamespace(data=data, options={})
        menu = asyncio.run(opts.async_step_init())
        self.assertIn("shadow_lab", menu["menu_options"])
        form = asyncio.run(opts.async_step_shadow_lab())
        self.assertEqual(form["step_id"], "shadow_lab")
        invalid = asyncio.run(opts.async_step_shadow_lab({
            "initial_charge_kw": 4.0, "max_charge_kw": 3.6,
            "dpm_model_kw": 4.8,
            "shadow_lab_enabled": True,
        }))
        self.assertEqual(invalid["errors"]["base"], "invalid_power_range")
        result = asyncio.run(opts.async_step_shadow_lab({
            "initial_charge_kw": 3.6, "max_charge_kw": 3.8,
            "dpm_model_kw": 4.8,
            "shadow_lab_enabled": True,
        }))
        self.assertEqual(result["type"], "create_entry")
        self.assertTrue(result["data"]["shadow_lab_enabled"])
        self.assertEqual(result["data"]["max_charge_kw"], 3.8)
        self.assertEqual(result["data"]["dpm_model_kw"], 4.8)
        self.assertTrue(self.module.validate(data, result["data"]).ready)
        self.assertEqual(data["initial_charge_kw"], 3.6)
        self.assertEqual(data["max_charge_kw"], 4.)

    def test_fixed_target_mode_stores_only_fixed_value(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        asyncio.run(flow.async_step_user(entity_data()))
        car_input = car("Fiat", "binary_sensor.fiat", "sensor.fiat_soc")
        car_input["target_mode"] = "fixed"
        self.assertEqual(asyncio.run(flow.async_step_vehicle(car_input))["step_id"], "target")
        done = asyncio.run(flow.async_step_target({"target_default": 85}))
        self.assertEqual(done["type"], "create_entry")
        saved = done["data"]["vehicles"][0]
        self.assertEqual(saved["target_mode"], "fixed")
        self.assertEqual(saved["target_default"], 85)
        self.assertNotIn("target_entity", saved)

    def test_options_can_switch_existing_fixed_target_to_entity(self):
        flow = self.module.EasyWallboxSmartConfigFlow()
        asyncio.run(flow.async_step_user(entity_data()))
        car_input = car("Fiat", "binary_sensor.fiat", "sensor.fiat_soc")
        car_input["target_mode"] = "fixed"
        asyncio.run(flow.async_step_vehicle(car_input))
        initial = asyncio.run(flow.async_step_target({"target_default": 80}))["data"]
        opts = self.module.EasyWallboxSmartOptionsFlow()
        opts.config_entry = types.SimpleNamespace(data=initial,options={})
        asyncio.run(opts.async_step_choose_vehicle({"vehicle": "binary_sensor.fiat"}))
        fields={"target_mode":"entity","departure_weekday":"07:00",
                "departure_weekend":"08:00","efficiency":.9}
        self.assertEqual(asyncio.run(opts.async_step_vehicle(fields))["step_id"], "target")
        result = asyncio.run(opts.async_step_target({"target_entity":"number.fiat_target"}))
        self.assertEqual(result["type"], "create_entry")
        selected=result["data"]["vehicle_overrides"]["binary_sensor.fiat"]
        self.assertEqual(selected["target_mode"],"entity")
        self.assertEqual(selected["target_entity"],"number.fiat_target")
        self.assertNotIn("target_default",selected)
        self.assertTrue(self.module.validate(initial,result["data"]).ready)

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
        asyncio.run(flow.async_step_vehicle(
            car("Fiat", "binary_sensor.fiat", "sensor.fiat_soc")
        ))
        initial = asyncio.run(flow.async_step_target(
            {"target_entity": "number.fiat_target"}))["data"]
        options = self.module.EasyWallboxSmartOptionsFlow()
        options.config_entry = types.SimpleNamespace(data=initial, options={})
        response = asyncio.run(options.async_step_init())
        self.assertEqual(response["step_id"], "init")
        self.assertEqual(response["type"], "menu")
        response = asyncio.run(options.async_step_choose_vehicle(
            {"vehicle": "binary_sensor.fiat"}
        ))
        self.assertEqual(response["step_id"], "vehicle")
        values = {
            "target_mode": "fixed",
            "departure_weekday": "06:30",
            "departure_weekend": "09:00",
            "efficiency": .9,
        }
        self.assertEqual(asyncio.run(options.async_step_vehicle(values))["step_id"], "target")
        result = asyncio.run(options.async_step_target({"target_default": 85}))
        self.assertEqual(result["type"], "create_entry")
        override = result["data"]["vehicle_overrides"]["binary_sensor.fiat"]
        self.assertEqual(override["target_default"], 85)
        self.assertEqual(override["target_mode"], "fixed")
        self.assertNotIn("target_entity", override)
        self.assertTrue(self.module.validate(initial, result["data"]).ready)


if __name__ == "__main__":
    unittest.main()
