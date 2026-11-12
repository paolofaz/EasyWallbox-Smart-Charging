"""SOC policy tests: standalone, without Home Assistant dependencies."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "easywallbox_smart"
package_name = "_easywallbox_soc_test"
package = types.ModuleType(package_name)
package.__path__ = [str(PACKAGE)]
sys.modules[package_name] = package
spec = importlib.util.spec_from_file_location(
    f"{package_name}.soc_policy", PACKAGE / "soc_policy.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assess_target = module.assess_target


class TestTargetPolicy(unittest.TestCase):
    def test_full_charge_never_proposes_pause(self):
        for soc in (20, 80, 99, 99.9, 100):
            with self.subTest(soc=soc):
                state = assess_target(soc, 100, is_fresh_and_valid=True)
                self.assertFalse(state.pause_candidate)
                self.assertEqual(state.reason, "full_charge_managed_by_vehicle")
                self.assertEqual(state.target_reached, soc >= 100)

    def test_sub_100_target(self):
        for soc, target, expected in (
            (78, 80, False), (80, 80, True), (82, 80, True),
            (98, 99, False), (100, 99, True)
        ):
            with self.subTest(soc=soc, target=target):
                result = assess_target(soc, target, is_fresh_and_valid=True)
                self.assertEqual(result.pause_candidate, expected)

    def test_missing_stale_invalid_soc_never_proposes_pause(self):
        for soc, fresh in (
            (None, True), (float("nan"), True), (float("inf"), True),
            (-1, True), (101, True), ("80", True), (True, True), (90, False)
        ):
            with self.subTest(soc=soc, fresh=fresh):
                state = assess_target(soc, 80, is_fresh_and_valid=fresh)
                self.assertIsNone(state.target_reached)
                self.assertFalse(state.pause_candidate)

    def test_target_outside_bounds(self):
        for target in (0, -1, 101, 80.5, True):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    assess_target(50, target, is_fresh_and_valid=True)


if __name__ == "__main__":
    unittest.main()
