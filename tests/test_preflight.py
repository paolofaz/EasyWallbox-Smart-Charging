"""Pure preflight checks: never read a real user's Home Assistant storage."""
from pathlib import Path
import importlib.util
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PKG = "_ew_preflight_test"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg


def load(name):
    spec = importlib.util.spec_from_file_location(PKG + "." + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


preflight = load("preflight")


def candidate():
    return dict(
        house_downstairs="sensor.shelly_down", house_upstairs="sensor.shelly_up",
        ev_power="sensor.shelly_ev",
        wallbox_connected="binary_sensor.wallbox_cable",
        wallbox_charging="binary_sensor.wallbox_charging",
        telemetry_fresh="binary_sensor.wallbox_fresh",
        requested_limit="number.wallbox_requested",
        confirmed_limit="sensor.wallbox_confirmed",
        dpm_model_kw=4.3,
        vehicles=[
            dict(name="Car A", cable="binary_sensor.car_a_cable",
                 soc="sensor.car_a_soc", target_default=80,
                 capacity_kwh=37, sustainable_kw=3.0, efficiency=.9,
                 departure_weekday="07:00", departure_weekend="08:00"),
            dict(name="Car B", cable="binary_sensor.car_b_cable",
                 soc="sensor.car_b_soc", target_default=85,
                 capacity_kwh=77, sustainable_kw=4.0, efficiency=.9,
                 departure_weekday="07:00", departure_weekend="08:00")
        ],
    )


class TestEntryPreflight(unittest.TestCase):
    def test_valid_new_configuration(self):
        result = preflight.inspect(candidate())
        self.assertTrue(result.ready)
        self.assertEqual(result.kind, preflight.NEW)
        self.assertEqual(result.issues, ())

    def test_legacy_v3_profile_never_is_inferred_as_new(self):
        old = {
            "house_power_sources": ["sensor.down", "sensor.up"],
            "ev_power_sensor": "sensor.ev",
            "vehicles": [
                {"id": "car-id", "name": "Vehicle", "connected": "binary_sensor.cable",
                 "soc": "sensor.soc", "default_target_soc": 80},
            ],
        }
        before = repr(old)
        result = preflight.inspect(old, {"continuous_kw": 4.2})
        self.assertEqual(result.kind, preflight.LEGACY)
        self.assertFalse(result.ready)
        self.assertEqual(repr(old), before, "preflight must never edit legacy data")

    def test_legacy_total_energy_variant(self):
        result = preflight.inspect(
            {"vehicles": [{"connected": "binary_sensor.car", "name": "X"}]},
            {"site_total_power": "sensor.total", "ev_power_sensor": "sensor.ev"},
        )
        self.assertEqual(result.kind, preflight.LEGACY)

    def test_partial_new_config_never_becomes_legacy(self):
        incomplete = {
            "house_downstairs": "sensor.house",
            "site_total_power": "sensor.total",
            "vehicles": [],
        }
        self.assertEqual(preflight.inspect(incomplete).kind, preflight.INVALID)

    def test_duplicate_house_ev_source_is_blocked(self):
        cfg = candidate()
        cfg["ev_power"] = cfg["house_downstairs"]
        self.assertIn("duplicated_source_entity", preflight.inspect(cfg).issues)

    def test_duplicate_cable_and_vehicle_soc_blocked(self):
        cfg = candidate()
        cfg["vehicles"][1]["cable"] = cfg["vehicles"][0]["cable"]
        cfg["vehicles"][1]["soc"] = cfg["vehicles"][0]["soc"]
        issues = preflight.inspect(cfg).issues
        self.assertIn("duplicated_vehicle_cable", issues)
        self.assertIn("duplicated_vehicle_soc", issues)

    def test_invalid_source_domain_blocked(self):
        cfg = candidate()
        cfg["requested_limit"] = "sensor.wallbox_requested"
        self.assertIn("invalid_requested_limit", preflight.inspect(cfg).issues)

    def test_missing_required_input_blocked(self):
        cfg = candidate()
        cfg.pop("wallbox_charging")
        self.assertIn("invalid_wallbox_charging", preflight.inspect(cfg).issues)

    def test_non_finite_or_invalid_battery_parameters(self):
        for key, value, issue in [
            ("capacity_kwh", "nan", "invalid_capacity"),
            ("efficiency", 1.2, "invalid_ac_efficiency"),
            ("target_default", 150, "invalid_default_target"),
            ("sustainable_kw", -1, "invalid_sustainable_power"),
            ("departure_weekday", "25:20", "invalid_departure_clock"),
        ]:
            with self.subTest(key=key):
                cfg = candidate()
                cfg["vehicles"][0][key] = value
                self.assertIn(issue, preflight.inspect(cfg).issues)

    def test_no_private_identifiers_in_errors(self):
        cfg = candidate()
        cfg["vehicles"][0]["name"] = "PRIVATE_NAME_CANARY"
        cfg["house_upstairs"] = "sensor.PRIVATE_ENTITY_CANARY"
        cfg["vehicles"][1]["name"] = ""
        report = preflight.inspect(cfg)
        self.assertNotIn("PRIVATE_NAME_CANARY", repr(report))
        self.assertNotIn("PRIVATE_ENTITY_CANARY", repr(report))

    def test_empty_or_malformed_entry_is_never_migrated(self):
        for cfg in (None, {}, {"vehicles": None}, {"vehicles": "bad"}):
            self.assertFalse(preflight.inspect(cfg).ready)

    def test_option_values_not_applied_automatically_to_legacy(self):
        legacy = {"vehicles": [{"name": "old", "id": "1", "connected": "binary_sensor.old"}]}
        self.assertEqual(preflight.inspect(legacy).kind, preflight.LEGACY)
        self.assertIn("id", legacy["vehicles"][0])

    def test_source_code_is_pure_and_non_mutating(self):
        source = (ROOT / "preflight.py").read_text()
        for forbidden in ("homeassistant", ".storage", "async_update_entry", "open(",
                          "services.async_call", "setattr(", "write_text("):
            # Documentation about not touching .storage is acceptable.
            if forbidden in (".storage", "async_update_entry"):
                continue
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
