"""Offline pre-alpha checks; requires Python stdlib only.

These tests do NOT substitute for hassfest or an HA runtime smoke test.
"""

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "easywallbox_smart"
STEPS = {
    "user": (
        "wallbox_car_connected",
        "wallbox_charging",
        "wallbox_telemetry_fresh",
        "wallbox_ble_connection",
        "wallbox_fault",
    ),
    "cars": (
        "fiat_cable",
        "fiat_charging",
        "fiat_soc",
        "fiat_target",
        "kia_cable",
        "kia_charging",
        "kia_soc",
        "kia_target",
    ),
    "power": ("power_ground", "power_first_floor", "power_wallbox"),
}


class TestScaffold(unittest.TestCase):
    def test_python_syntax(self):
        for path in INTEGRATION.rglob("*.py"):
            with self.subTest(path=path):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_manifest(self):
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        self.assertEqual(manifest["domain"], INTEGRATION.name)
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["iot_class"], "calculated")
        self.assertEqual(manifest["requirements"], [])

    def test_translations_cover_all_fields(self):
        for lang in ("it", "en"):
            with self.subTest(lang=lang):
                t = json.loads(
                    (INTEGRATION / "translations" / (lang + ".json")).read_text()
                )
                for step, keys in STEPS.items():
                    config_keys = t["config"]["step"][step]["data"]
                    options_step = "init" if step == "user" else step
                    options_keys = t["options"]["step"][options_step]["data"]
                    self.assertEqual(set(config_keys), set(keys))
                    self.assertEqual(set(options_keys), set(keys))

    def test_no_control_calls(self):
        """A limited static guard: manually review future changes as well."""
        content = "\n".join(
            p.read_text(encoding="utf-8") for p in INTEGRATION.glob("*.py")
        )
        for expression in (".services.async_call(", "switch.turn_on", "switch.turn_off",
                           "button.press", "number.set_value"):
            self.assertNotIn(expression, content)


if __name__ == "__main__":
    unittest.main()
