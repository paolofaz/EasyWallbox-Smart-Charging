"""Offline tests for vehicle matching, SOC freshness and battery energy."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "easywallbox_smart"
package = types.ModuleType("_ew_snapshot_test")
package.__path__ = [str(BASE)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(
    "_ew_snapshot_test.snapshot", BASE / "snapshot.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Source = module.Source
assess = module.assess


def config():
    return {
        "wallbox_car_connected": "binary_sensor.wallbox",
        "wallbox_telemetry_fresh": "binary_sensor.fresh",
        "vehicles": [
            {"id": "a", "name": "Fiat 500e", "soc": "sensor.soc_a",
             "connected": "binary_sensor.a", "capacity_kwh": 37.3,
             "default_target_soc": 80},
            {"id": "b", "name": "Kia EV3", "soc": "sensor.soc_b",
             "connected": "binary_sensor.b", "capacity_kwh": 78.0,
             "default_target_soc": 100},
        ],
    }


def readings():
    return {
        "binary_sensor.wallbox": Source("on", 20),
        "binary_sensor.fresh": Source("on", 5),
        "binary_sensor.a": Source("on", 40),
        "binary_sensor.b": Source("off", 40),
        "sensor.soc_a": Source("45", 60),
        "sensor.soc_b": Source("60", 60),
    }


class TestSnapshot(unittest.TestCase):
    def test_unique_car(self):
        result = assess(config(), readings())
        self.assertEqual(result.vehicle, "Fiat 500e")
        self.assertEqual(result.soc, 45)
        self.assertEqual(result.target, 80)
        self.assertAlmostEqual(result.remaining_kwh, 13.05)
        self.assertEqual(result.quality, "ok")

    def test_target_100_has_energy_estimate(self):
        data = readings()
        data["binary_sensor.a"] = Source("off", 40)
        data["binary_sensor.b"] = Source("on", 40)
        result = assess(config(), data)
        self.assertEqual(result.vehicle, "Kia EV3")
        self.assertEqual(result.target, 100)
        self.assertEqual(result.remaining_kwh, 31.2)
        data["sensor.soc_b"] = Source("100", 20)
        self.assertEqual(assess(config(), data).remaining_kwh, 0)

    def test_ambiguity_never_guesses(self):
        data = readings()
        data["binary_sensor.b"] = Source("on", 40)
        result = assess(config(), data)
        self.assertIsNone(result.vehicle)
        self.assertEqual(result.quality, "ambiguous_vehicle")
        self.assertIsNone(result.remaining_kwh)

    def test_missing_vehicle_status_blocks_match(self):
        data = readings()
        data["binary_sensor.b"] = Source("unavailable", None)
        self.assertEqual(
            assess(config(), data).quality, "vehicle_connection_unavailable"
        )

    def test_wallbox_unplugged_or_stale(self):
        data = readings()
        data["binary_sensor.wallbox"] = Source("off", 30)
        self.assertEqual(assess(config(), data).quality, "no_vehicle_at_wallbox")
        data["binary_sensor.wallbox"] = Source("on", 150)
        self.assertEqual(
            assess(config(), data).quality, "wallbox_connection_unavailable"
        )

    def test_telemetry_fresh_required_when_configured(self):
        data = readings()
        data["binary_sensor.fresh"] = Source("off", 1)
        self.assertEqual(
            assess(config(), data).quality, "wallbox_telemetry_unavailable"
        )

    def test_stale_soc_not_equal_zero(self):
        data = readings()
        data["sensor.soc_a"] = Source("80", 47 * 60)
        result = assess(config(), data)
        self.assertEqual(result.vehicle, "Fiat 500e")
        self.assertEqual(result.target, 80)
        self.assertEqual(result.quality, "soc_missing_or_stale")
        self.assertIsNone(result.soc)
        self.assertIsNone(result.remaining_kwh)

    def test_invalid_soc(self):
        data = readings()
        for bad in ("nan", "120", "-1", "not-numeric"):
            data["sensor.soc_a"] = Source(bad, 20)
            self.assertEqual(assess(config(), data).quality, "soc_invalid")

    def test_initial_config_incomplete(self):
        self.assertEqual(
            assess({"fiat_soc": "sensor.some"}, readings()).quality,
            "no_vehicle_profiles"
        )


if __name__ == "__main__":
    unittest.main()
