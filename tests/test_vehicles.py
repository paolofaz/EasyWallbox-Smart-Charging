"""Pure profile tests; independent of Home Assistant packages."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "easywallbox_smart"


def load_profile_module():
    """Load the package's pure modules without importing HA's __init__.py."""
    pkg_name = "_easywallbox_test"
    package = types.ModuleType(pkg_name)
    package.__path__ = [str(PACKAGE)]
    sys.modules[pkg_name] = package
    for module_name in ("const", "vehicle"):
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.{module_name}", PACKAGE / f"{module_name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{pkg_name}.vehicle"]


vehicle = load_profile_module()


def profile(**overrides):
    values = {
        "name": "Fiat 500e",
        "soc": "sensor.soc_500",
        "connected": "binary_sensor.500_connected",
        "capacity_kwh": 37.3,
        "default_target_soc": 80,
    }
    values.update(overrides)
    return values


class TestVehicles(unittest.TestCase):
    def test_new_vehicle(self):
        v = vehicle.build_vehicle(profile(), [])
        self.assertTrue(v["id"])
        self.assertEqual(v["name"], "Fiat 500e")
        self.assertEqual(v["default_target_soc"], 80)
        self.assertEqual(v["capacity_kwh"], 37.3)
        self.assertEqual(v["charging"], "")

    def test_any_number_of_vehicles(self):
        cars = []
        for index in range(4):
            cars.append(vehicle.build_vehicle(
                profile(name=f"Vehicle {index}", soc=f"sensor.soc_{index}"), cars
            ))
        self.assertEqual(len({v["id"] for v in cars}), 4)

    def test_name_and_soc_must_be_unique(self):
        first = vehicle.build_vehicle(profile(), [])
        for values in (
            profile(name="  fiat 500E  ", soc="sensor.another"),
            profile(name="Kia", soc="sensor.soc_500"),
        ):
            with self.assertRaises(ValueError):
                vehicle.build_vehicle(values, [first])

    def test_edit_keeps_stable_id(self):
        first = vehicle.build_vehicle(profile(), [])
        changed = vehicle.build_vehicle(
            profile(name="My 500e", default_target_soc=95),
            [first], vehicle_id=first["id"]
        )
        self.assertEqual(first["id"], changed["id"])
        self.assertEqual(changed["default_target_soc"], 95)

    def test_invalid_values(self):
        for values in (
            profile(name="  "),
            profile(capacity_kwh=0),
            profile(default_target_soc=101),
            profile(soc=""),
        ):
            with self.assertRaises(ValueError):
                vehicle.build_vehicle(values, [])

    def test_legacy_profile_stays_uninvented(self):
        self.assertEqual(vehicle.profiles_from_entry({"fiat_soc": "sensor.a"}), [])
        self.assertEqual(vehicle.profiles_from_entry({"vehicles": []}), [])


if __name__ == "__main__":
    unittest.main()
