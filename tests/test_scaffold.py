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
        self.assertEqual(manifest["version"], "0.0.9")
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

    def test_energy_methods_clearly_alternative(self):
        for lang in ("it", "en"):
            with self.subTest(lang=lang):
                tr = json.loads(
                    (INTEGRATION / "translations" / f"{lang}.json").read_text()
                )
                for section in ("config", "options"):
                    step = tr[section]["step"]["energy_menu"]
                    self.assertIn("ONE" if lang == "en" else "UNA", step["description"])
                    expected = ("house_sources", "total_sources", "no_sources")
                    for letter, key in zip("ABC", expected):
                        self.assertTrue(step["menu_options"][key].startswith(letter + " · "))
                    self.assertIn("DPM", step["menu_options"]["total_sources"])
                    self.assertIn("EV" if lang == "en" else "ricarica",
                                  tr[section]["step"]["total_sources"]["description"])

    def test_optional_planning_flow_is_read_only(self):
        flow = (INTEGRATION / "config_flow.py").read_text()
        sensor = (INTEGRATION / "sensor.py").read_text()
        self.assertIn("async_step_planning", flow)
        self.assertIn("continuous_kw", flow)
        self.assertIn("departure_weekday", flow)
        self.assertIn("departure_weekend", flow)
        self.assertIn("SensorDeviceClass.TIMESTAMP", sensor)
        for lang in ("it", "en"):
            tr = json.loads(
                (INTEGRATION / "translations" / f"{lang}.json").read_text()
            )
            self.assertEqual(
                set(tr["options"]["step"]["planning"]["data"]),
                {"continuous_kw", "departure_weekday", "departure_weekend"}
            )

    def test_telemetry_diagnostics_without_safety_bypass(self):
        source = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
        self.assertIn("wallbox_telemetry_age_seconds", source)
        self.assertIn("wallbox_telemetry_diagnostic", source)
        self.assertIn("wallbox_telemetry_max_age_seconds", source)
        snapshot = (INTEGRATION / "snapshot.py").read_text(encoding="utf-8")
        self.assertIn("wallbox_telemetry_unavailable", snapshot)
        self.assertIn("WALLBOX_MAX_AGE = 120", snapshot)

    def test_config_entry_migration_present(self):
        text = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("async def async_migrate_entry(", text)
        self.assertIn("data.setdefault(CONF_VEHICLES, [])", text)
        self.assertIn("version=3", text)
        self.assertIn("migrate_legacy", text)

    def test_read_only_sensor_platform(self):
        sensor = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
        init = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('async_forward_entry_setups(entry, ["sensor"])', init)
        self.assertIn('async_unload_platforms(entry, ["sensor"])', init)
        self.assertIn("async_track_state_change_event", sensor)
        self.assertIn("async_track_time_interval", sensor)
        self.assertNotIn("hass.services", sensor)

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
