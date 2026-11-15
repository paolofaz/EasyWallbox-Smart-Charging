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
            ("sustainable_kw", -2, "invalid_sustainable_power"),
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
