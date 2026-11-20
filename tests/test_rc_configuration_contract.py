"""Public-facing RC configuration contract: no legacy simulation mapping."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components/easywallbox_smart"


class RCConfigContract(unittest.TestCase):
    def test_any_positive_number_of_independent_household_meters(self):
        code = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('vol.Required(CONF_HOUSE_SOURCES): entity("sensor", True)', code)
        self.assertIn('if not ids or len(set(ids)) != len(ids)', code)
        self.assertNotIn("house_downstairs", code)
        self.assertNotIn("house_upstairs", code)
        self.assertNotIn("CONF_DOWNSTAIRS", code)
        self.assertNotIn("CONF_UPSTAIRS", code)

    def test_target_soc_is_chosen_in_separate_required_path(self):
        code = (COMP / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('menu_options=["target_entity", "target_fixed"]', code)
        self.assertIn('vol.Required(CONF_TARGET_ENTITY): entity(', code)
        self.assertIn('vol.Required(CONF_TARGET_FIXED, default=80):', code)
        self.assertIn('number(80, 100, 5) if stop else number(1, 100, 1)', code)
        self.assertNotIn("target_default", code)
        self.assertNotIn("sustainable_kw", code)
        self.assertNotIn('"planning_rate_kw"', code)
        parsed = ast.parse(code)
        methods = {
            node.name for node in ast.walk(parsed)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name in ("async_step_target_method", "async_step_target_fixed",
                     "async_step_target_entity", "async_step_vehicle"):
            self.assertIn(name, methods)

    def test_complete_vehicle_management_flow(self):
        code = (COMP / "config_flow.py").read_text(encoding="utf-8")
        for key in ("async_step_add_vehicle", "async_step_edit_vehicle",
                    "async_step_remove_vehicle", "async_step_confirm_remove",
                    "async_step_edit_target_fixed", "async_step_edit_target_entity"):
            self.assertIn(key,code)
        self.assertIn("CONF_VEHICLES] = cars",code)
        self.assertIn("OptionsFlowWithReload",code)

    def test_no_simulation_or_johnny_in_ui_and_runtime(self):
        for path in (COMP / "config_flow.py", COMP / "sensor.py",
                     COMP / "switch.py", COMP / "select.py",
                     COMP / "rc_controller.py", COMP / "strings.json",
                     COMP / "translations" / "it.json"):
            content = path.read_text(encoding="utf-8").casefold()
            with self.subTest(file=path.name):
                self.assertNotIn("laboratorio", content)
                self.assertNotIn("shadow_", content)
                self.assertNotIn("johnny", content)
                self.assertNotIn("solo simulazione", content)
        switches=(COMP/"switch.py").read_text(encoding="utf-8")
        self.assertEqual(switches.count('"real": ('),1)
        self.assertEqual(switches.count('"delay": ('),1)

    def test_config_labels_describe_target_and_planner_rate(self):
        obj=json.loads((COMP/"translations"/"it.json").read_text(encoding="utf-8"))
        step=obj["config"]["step"]
        self.assertIn("target_method",step)
        self.assertIn("target_fixed",step)
        self.assertIn("target_entity",step)
        vehicle=step["vehicle"]["data"]
        self.assertNotIn("planning_rate_kw",vehicle)
        self.assertIn("edit_vehicle",obj["options"]["step"])
        self.assertIn("add_vehicle",obj["options"]["step"]["init"]["menu_options"])
        self.assertIn("remove_vehicle",obj["options"]["step"]["init"]["menu_options"])
        self.assertIn("house_power_sources",step["user"]["data"])

    def test_ui_no_hardcoded_house_floor_or_car_brand(self):
        code=(COMP/"config_flow.py").read_text(encoding="utf-8").casefold()
        for forbidden in ("shelly_piano", "house_downstairs", "house_upstairs",
                          "fiat_500e", "kia_ev3", "paolofaz"):
            self.assertNotIn(forbidden,code)


if __name__=="__main__":
    unittest.main()
