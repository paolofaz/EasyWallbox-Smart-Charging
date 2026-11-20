"""Exercise GUI vehicle forms against real voluptuous schemas, fake HA host."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"


class FakeSelector:
    def __init__(self, config=None):
        self.config = config

    def __call__(self, value):
        if value in ("", None):
            raise ValueError("required entity")
        return value


class EntitySelectorConfig:
    def __init__(self, domain=None, multiple=False):
        self.domain, self.multiple = domain, multiple


class NumberSelectorConfig:
    def __init__(self, min=None, max=None, step=None, mode=None):
        self.min, self.max, self.step, self.mode = min, max, step, mode


class NumberSelector(FakeSelector):
    def __call__(self, value):
        result = float(value)
        if not self.config.min <= result <= self.config.max:
            raise ValueError("number out of range")
        return result


class TextSelector(FakeSelector):
    def __call__(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("text required")
        return value


class FakeFlow:
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)

    def async_show_menu(self, step_id, menu_options, **kwargs):
        return {"type": "menu", "step_id": step_id,
                "menu_options": menu_options}

    def async_show_form(self, step_id, data_schema, errors=None, **kwargs):
        return {"type": "form", "step_id": step_id,
                "data_schema": data_schema, "errors": errors or {}}

    def async_create_entry(self, title=None, data=None):
        return {"type": "create_entry", "title": title, "data": data}

    def async_abort(self, reason):
        return {"type": "abort", "reason": reason}


def load_flow():
    import voluptuous
    previous = {}
    packages = ("homeassistant", "homeassistant.config_entries",
                "homeassistant.core", "homeassistant.helpers",
                "homeassistant.helpers.selector")
    for name in packages:
        previous[name] = sys.modules.get(name)
    try:
        ha = sys.modules.get("homeassistant") or types.ModuleType("homeassistant")
        ce = types.ModuleType("homeassistant.config_entries")
        ce.ConfigFlow = FakeFlow
        ce.OptionsFlowWithReload = FakeFlow
        ce.ConfigEntry = object
        core = sys.modules.get("homeassistant.core") or types.ModuleType("homeassistant.core")
        core.callback = lambda fn: fn
        helper = sys.modules.get("homeassistant.helpers") or types.ModuleType("homeassistant.helpers")
        sel = types.ModuleType("homeassistant.helpers.selector")
        sel.EntitySelector = FakeSelector
        sel.EntitySelectorConfig = EntitySelectorConfig
        sel.NumberSelector = NumberSelector
        sel.NumberSelectorConfig = NumberSelectorConfig
        sel.NumberSelectorMode = types.SimpleNamespace(BOX="box")
        sel.TextSelector = TextSelector
        sys.modules.update({
            "homeassistant": ha,
            "homeassistant.config_entries": ce,
            "homeassistant.core": core,
            "homeassistant.helpers": helper,
            "homeassistant.helpers.selector": sel,
        })
        ha.config_entries = ce
        pkg = sys.modules.get("test_rc_ui_pkg")
        if pkg is None:
            pkg = types.ModuleType("test_rc_ui_pkg")
            pkg.__path__ = [str(ROOT)]
            sys.modules[pkg.__name__] = pkg
        for modname in ("const", "vehicle_profiles"):
            name = pkg.__name__ + "." + modname
            if name not in sys.modules:
                spec = importlib.util.spec_from_file_location(
                    name, ROOT/(modname+".py"))
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
        name = pkg.__name__+".config_flow"
        sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location(
            name, ROOT/"config_flow.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def sample_car(name, cable):
    return {
        "name": name, "cable": cable,
        "soc": "sensor."+name.lower()+"_soc",
        "capacity_kwh": 42.0, "efficiency": .9,
        "departure_weekday": "07:00", "departure_weekend": "08:00",
        "target_fixed": 80,
    }


class TestVehicleConfigUI(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_flow()

    def options(self, cars=None, options=None):
        flow = self.app.EasyWallboxSmartOptionsFlow()
        flow.config_entry = types.SimpleNamespace(
            data={"vehicles": cars or [
                sample_car("Fiat", "binary_sensor.fiat"),
                sample_car("Kia", "binary_sensor.kia")
            ]}, options=options or {})
        return flow

    async def test_initial_setup_does_not_ask_rate(self):
        flow = self.app.EasyWallboxSmartConfigFlow()
        flow._wallbox = {"house_power_sources": ["sensor.house"]}
        form = await flow.async_step_vehicle()
        self.assertEqual(form["type"],"form")
        self.assertNotIn("planning_rate_kw",
                         [key.schema for key in form["data_schema"].schema])
        car = sample_car("Fiat", "binary_sensor.fiat")
        car.pop("target_fixed")
        car["add_another"] = False
        validated = form["data_schema"](car)
        menu = await flow.async_step_vehicle(validated)
        self.assertEqual(menu["step_id"], "target_method")
        saved = await flow.async_step_target_fixed({"target_fixed":80})
        self.assertEqual(saved["type"],"create_entry")
        self.assertNotIn("planning_rate_kw", saved["data"]["vehicles"][0])

    async def test_edit_all_vehicle_fields_and_soc_target(self):
        flow = self.options()
        menu = await flow.async_step_init()
        self.assertEqual(set(menu["menu_options"]),
                         {"wallbox","choose_vehicle","add_vehicle","remove_vehicle"})
        form = await flow.async_step_choose_vehicle({
            "vehicle": "binary_sensor.fiat"})
        self.assertEqual(form["step_id"],"edit_vehicle")
        update = sample_car("NuovaFiat", "binary_sensor.fiat")
        update.update({"soc":"sensor.changed","capacity_kwh":44,
                       "departure_weekday":"06:30"})
        update.pop("target_fixed")
        validated = form["data_schema"](update)
        next_step=await flow.async_step_edit_vehicle(validated)
        self.assertEqual(next_step["step_id"],"edit_target_method")
        saved = await flow.async_step_edit_target_entity({
            "target_entity":"number.fiat_target"})
        self.assertEqual(saved["type"],"create_entry")
        profiles=saved["data"]["vehicles"]
        self.assertEqual(len(profiles),2)
        self.assertEqual(profiles[0]["name"],"NuovaFiat")
        self.assertEqual(profiles[0]["capacity_kwh"],44)
        self.assertEqual(profiles[0]["departure_weekday"],"06:30")
        self.assertEqual(profiles[0]["target_entity"],"number.fiat_target")
        self.assertNotIn("target_fixed",profiles[0])

    async def test_add_third_vehicle_then_remove_one(self):
        flow=self.options()
        form=await flow.async_step_add_vehicle()
        self.assertEqual(form["step_id"],"edit_vehicle")
        new=sample_car("Terza","binary_sensor.third")
        new.pop("target_fixed")
        new=form["data_schema"](new)
        await flow.async_step_edit_vehicle(new)
        result=await flow.async_step_edit_target_fixed({"target_fixed":85})
        self.assertEqual(len(result["data"]["vehicles"]),3)
        next_flow=self.options(options=result["data"])
        selection=await next_flow.async_step_remove_vehicle({
            "vehicle":"binary_sensor.fiat"})
        self.assertEqual(selection["step_id"],"confirm_remove")
        removed=await next_flow.async_step_confirm_remove({"confirm":True})
        self.assertEqual(len(removed["data"]["vehicles"]),2)
        self.assertEqual([c["name"] for c in removed["data"]["vehicles"]],
                         ["Kia","Terza"])

    async def test_last_vehicle_cannot_be_removed(self):
        flow=self.options(cars=[sample_car("Fiat","binary_sensor.fiat")])
        result=await flow.async_step_remove_vehicle()
        self.assertEqual(result,{"type":"abort","reason":"cannot_remove_last"})

    async def test_duplicate_vehicle_error_is_shown_not_lost(self):
        flow=self.options()
        await flow.async_step_add_vehicle()
        candidate=sample_car("KIA","binary_sensor.new")
        candidate.pop("target_fixed")
        await flow.async_step_edit_vehicle(candidate)
        result=await flow.async_step_edit_target_fixed({"target_fixed":80})
        self.assertEqual(result["type"],"form")
        self.assertEqual(result["errors"]["base"],"duplicate_vehicle")


if __name__=="__main__":
    unittest.main()
