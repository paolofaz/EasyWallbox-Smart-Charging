"""Only the clean v0.1 configuration layout is supported."""
from pathlib import Path
import importlib.util
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PKG = "_ew_new_validation_test"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg
spec = importlib.util.spec_from_file_location(PKG + ".validation", ROOT / "validation.py")
validation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validation
spec.loader.exec_module(validation)


def example():
    return dict(
        house_downstairs="sensor.house_down", house_upstairs="sensor.house_up",
        ev_power="sensor.ev",
        wallbox_connected="binary_sensor.wb_connected",
        wallbox_charging="binary_sensor.wb_charging",
        telemetry_fresh="binary_sensor.wb_fresh",
        requested_limit="number.charge_power",
        confirmed_limit="sensor.power_set",
        dpm_model_kw=4.3,
        vehicles=[
            dict(name="Fiat", cable="binary_sensor.fiat_cable",
                 soc="sensor.fiat_soc", target_default=80, capacity_kwh=37,
                 sustainable_kw=3.0, efficiency=.9,
                 departure_weekday="07:00", departure_weekend="08:00"),
            dict(name="Kia", cable="binary_sensor.kia_cable",
                 soc="sensor.kia_soc", target_default=90, capacity_kwh=77,
                 sustainable_kw=4.0, efficiency=.9,
                 departure_weekday="07:00", departure_weekend="08:00"),
        ],
    )


class TestValidation(unittest.TestCase):
    def test_new_install_is_ready(self):
        self.assertTrue(validation.validate(example()).ready)

    def test_no_config_is_not_ready(self):
        for data in (None, {}, {"vehicles": []}, {"vehicles": "invalid"}):
            self.assertFalse(validation.validate(data).ready)

    def test_wrong_entity_domains_blocked(self):
        data = example()
        data["requested_limit"] = "sensor.charge_power"
        self.assertIn("invalid_requested_limit", validation.validate(data).issues)

    def test_ev_meter_cannot_be_house_meter(self):
        data = example()
        data["ev_power"] = data["house_upstairs"]
        self.assertIn("duplicated_source_entity", validation.validate(data).issues)

    def test_new_universal_house_sources(self):
        cfg = example()
        cfg.pop("house_downstairs")
        cfg.pop("house_upstairs")
        cfg["house_power_sources"] = ["sensor.one"]
        cfg["session_energy"] = "sensor.energy"
        cfg["session_duration"] = "sensor.duration"
        for number in (1, 3):
            with self.subTest(meters=number):
                cfg["house_power_sources"] = [
                    "sensor.house_" + str(i) for i in range(number)
                ]
                self.assertTrue(validation.validate(cfg).ready)

    def test_counters_must_be_paired_and_have_distinct_ids(self):
        cfg = example()
        cfg["session_energy"] = "sensor.energy"
        self.assertIn("incomplete_session_counters", validation.validate(cfg).issues)
        cfg["session_duration"] = "sensor.energy"
        self.assertIn("duplicated_source_entity", validation.validate(cfg).issues)

    def test_existing_v1_options_can_change_meter_sources(self):
        cfg = example()
        opts = {"house_power_sources": ["sensor.aux1", "sensor.aux2"],
                "session_energy": "sensor.energy",
                "session_duration": "sensor.duration"}
        self.assertTrue(validation.validate(cfg, opts).ready)
        opts["house_power_sources"].append("sensor.aux1")
        self.assertIn("duplicated_source_entity", validation.validate(cfg, opts).issues)

    def test_entity_target_is_only_active_source_in_new_config(self):
        data = example()
        car = data["vehicles"][0]
        car["target_mode"] = "entity"
        car["target_entity"] = "number.fiat_target"
        car.pop("target_default")
        self.assertTrue(validation.validate(data).ready)
        car["target_default"] = 90
        self.assertIn("multiple_target_sources", validation.validate(data).issues)

    def test_fixed_target_has_no_entity_field_in_new_config(self):
        data = example()
        car = data["vehicles"][0]
        car["target_mode"] = "fixed"
        self.assertTrue(validation.validate(data).ready)
        car["target_entity"] = "sensor.kia_limit"
        self.assertIn("multiple_target_sources", validation.validate(data).issues)

    def test_entity_mode_cannot_be_configured_without_entity(self):
        data = example()
        car = data["vehicles"][0]
        car["target_mode"] = "entity"
        car.pop("target_default")
        self.assertIn("invalid_target_source", validation.validate(data).issues)

    def test_explicit_invalid_mode_is_rejected(self):
        data = example()
        data["vehicles"][0]["target_mode"] = None
        self.assertIn("invalid_target_mode", validation.validate(data).issues)

    def test_0_1_0_with_both_fields_still_accepted(self):
        data = example()
        data["vehicles"][0]["target_entity"] = "sensor.old_target"
        self.assertTrue(validation.validate(data).ready)

    def test_options_can_switch_from_old_fixed_target_to_entity(self):
        data = example()
        options = {"vehicle_overrides": {
            "binary_sensor.fiat_cable": {
                "target_mode": "entity",
                "target_entity": "number.target",
                "departure_weekday": "07:00",
            }
        }}
        self.assertTrue(validation.validate(data, options).ready)

    def test_options_entity_mode_requires_valid_entity_even_with_old_fixed(self):
        data = example()
        options = {"vehicle_overrides": {
            "binary_sensor.fiat_cable": {"target_mode": "entity"}
        }}
        self.assertIn("invalid_override_target", validation.validate(data, options).issues)

    def test_cars_must_have_unique_identity_sensors(self):
        data = example()
        data["vehicles"][1]["cable"] = data["vehicles"][0]["cable"]
        data["vehicles"][1]["soc"] = data["vehicles"][0]["soc"]
        result = validation.validate(data)
        self.assertIn("duplicated_vehicle_cable", result.issues)
        self.assertIn("duplicated_vehicle_soc", result.issues)

    def test_empty_name_and_invalid_clock(self):
        data = example()
        data["vehicles"][0]["name"] = " "
        data["vehicles"][0]["departure_weekday"] = "99:00"
        issues = validation.validate(data).issues
        self.assertIn("invalid_vehicle_name", issues)
        self.assertIn("invalid_departure_clock", issues)

    def test_invalid_numeric_inputs_rejected(self):
        cases = [
            ("target_default", 120, "invalid_default_target"),
            ("capacity_kwh", "nan", "invalid_capacity"),
            ("efficiency", 1.5, "invalid_ac_efficiency"),
        ]
        for name, value, issue in cases:
            with self.subTest(name=name):
                data = example()
                data["vehicles"][0][name] = value
                self.assertIn(issue, validation.validate(data).issues)

    def test_options_override_must_match_known_vehicle(self):
        data = example()
        opts = {"vehicle_overrides": {
            "binary_sensor.unknown": {"target_default": 85},
        }}
        self.assertIn("invalid_override_vehicle",
                      validation.validate(data, opts).issues)

    def test_options_override_values_checked(self):
        data = example()
        opts = {"vehicle_overrides": {
            "binary_sensor.fiat_cable": {
                "target_default": -1,
                "departure_weekend": "not-a-clock",
                "efficiency": "nan",
                "wrong_key": 123,
            },
        }}
        issues = validation.validate(data, opts).issues
        self.assertIn("invalid_override_target", issues)
        self.assertIn("invalid_override_clock", issues)
        self.assertIn("invalid_override_efficiency", issues)
        self.assertIn("unknown_override_fields", issues)

    def test_valid_options_dont_modify_base_data(self):
        data = example()
        original = repr(data)
        opts = {"vehicle_overrides": {
            "binary_sensor.fiat_cable": {"target_default": 85},
        }}
        self.assertTrue(validation.validate(data, opts).ready)
        self.assertEqual(original, repr(data))

    def test_no_private_ids_or_names_in_issue_codes(self):
        data = example()
        data["vehicles"][0]["name"] = "SECRET_NAME"
        data["house_upstairs"] = "sensor.SECRET_VALUE"
        data["vehicles"][1]["name"] = ""
        issues = repr(validation.validate(data))
        self.assertNotIn("SECRET_NAME", issues)
        self.assertNotIn("SECRET_VALUE", issues)

    def test_is_pure_and_no_legacy_support(self):
        text = (ROOT / "validation.py").read_text()
        for forbidden in ("homeassistant", "async_update_entry", "write_text(",
                          "migrate_legacy(", "services.async_call("):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
