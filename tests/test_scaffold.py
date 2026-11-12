"""Offline static tests. Home Assistant runtime/config flow tests still required."""

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "easywallbox_smart"
STEP_FIELDS = {
    "user": {
        "wallbox_car_connected", "wallbox_charging", "wallbox_telemetry_fresh",
        "wallbox_ble_connection", "wallbox_fault",
    },
    "vehicle": {
        "name", "soc", "connected", "charging",
        "capacity_kwh", "default_target_soc",
    },
    "more": {"add_another"},
    "house_sources": {"house_power_sources", "ev_power_sensor"},
    "total_sources": {"site_total_power", "ev_power_sensor"},
}


class TestScaffold(unittest.TestCase):
    def test_python_syntax(self):
        for path in INTEGRATION.rglob("*.py"):
            with self.subTest(path=path):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_manifest(self):
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        self.assertEqual(manifest["domain"], INTEGRATION.name)
        self.assertEqual(manifest["version"], "0.0.5")
        self.assertEqual(manifest["integration_type"], "hub")
        self.assertEqual(manifest["iot_class"], "calculated")
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["requirements"], [])

    def test_translations_for_all_steps(self):
        for lang in ("it", "en"):
            with self.subTest(lang=lang):
                t = json.loads(
                    (INTEGRATION / "translations" / f"{lang}.json").read_text()
                )
                for step, keys in STEP_FIELDS.items():
                    self.assertEqual(
                        set(t["config"]["step"][step]["data"]), keys
                    )
                self.assertEqual(
                    set(t["options"]["step"]["edit_vehicle"]["data"]),
                    STEP_FIELDS["vehicle"]
                )
                self.assertIn("vehicles", t["options"]["step"])
                self.assertIn("energy_menu", t["config"]["step"])
                self.assertIn("energy_menu", t["options"]["step"])

    def test_config_entry_migration_present(self):
        text = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("async def async_migrate_entry(", text)
        self.assertIn("data.setdefault(CONF_VEHICLES, [])", text)
        self.assertIn("version=3", text)
        self.assertIn("migrate_legacy", text)

    def test_no_commands_or_control_entities(self):
        content = "\n".join(
            p.read_text(encoding="utf-8") for p in INTEGRATION.glob("*.py")
        )
        for expression in (
            ".services.async_call(", "switch.turn_off", "switch.turn_on",
            "button.press", "number.set_value"
        ):
            self.assertNotIn(expression, content)
        self.assertNotIn('"fiat_target"', content)
        self.assertNotIn('"kia_target"', content)


if __name__ == "__main__":
    unittest.main()
