"""Power topology tests (no HA installation needed)."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "easywallbox_smart"
package = types.ModuleType("_ew_power_test")
package.__path__ = [str(BASE)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(
    "_ew_power_test.power_model", BASE / "power_model.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
P, H, T = module.Reading, module.MODE_HOUSE, module.MODE_TOTAL


class TestPowerSources(unittest.TestCase):
    def test_any_number_of_house_sources(self):
        for count in (1, 2, 5):
            ids = [f"sensor.h{i}" for i in range(count)]
            cfg = module.normalise(H, {"house_power_sources": ids})
            r = module.calculate(cfg, {i: P(200, "W", True) for i in ids})
            self.assertAlmostEqual(r.house_kw, 0.2 * count)
            self.assertEqual(r.quality, "house_only")

    def test_mixed_shelly_house_esphome_ev(self):
        cfg = module.normalise(H, {
            "house_power_sources": ["sensor.a", "sensor.b"],
            "ev_power_sensor": "sensor.ev",
        })
        value = module.calculate(cfg, {
            "sensor.a": P(550, "W", True),
            "sensor.b": P(0.45, "kW", True),
            "sensor.ev": P(3.1, "kW", True),
        })
        self.assertEqual(value.quality, "ok")
        self.assertAlmostEqual(value.house_kw, 1.0)
        self.assertAlmostEqual(value.total_kw, 4.1)

    def test_total_minus_ev(self):
        cfg = module.normalise(T, {
            "site_total_power": "sensor.dpm",
            "ev_power_sensor": "sensor.ev",
        })
        val = module.calculate(cfg, {
            "sensor.dpm": P(4.4, "kW", True),
            "sensor.ev": P(3200, "W", True),
        })
        self.assertAlmostEqual(val.house_kw, 1.2)
        self.assertEqual(val.quality, "ok")
        bad = module.calculate(cfg, {
            "sensor.dpm": P(1, "kW", True),
            "sensor.ev": P(3, "kW", True),
        })
        self.assertIsNone(bad.house_kw)
        self.assertEqual(bad.quality, "inconsistent_total_ev")

    def test_unavailable_is_not_zero(self):
        cfg = module.normalise(H, {"house_power_sources": ["sensor.a"]})
        for p in (P(None, "W", True), P(20, "W", False),
                  P(-1, "W", True), P(3, "kWh", True),
                  P(float("nan"), "W", True)):
            self.assertEqual(
                module.calculate(cfg, {"sensor.a": p}).quality,
                "house_unavailable"
            )

    def test_duplicates_and_missing_sources(self):
        for mode, fields in (
            (H, {"house_power_sources": []}),
            (H, {"house_power_sources": ["sensor.x", "sensor.x"]}),
            (H, {"house_power_sources": ["sensor.x"], "ev_power_sensor": "sensor.x"}),
            (T, {"site_total_power": "sensor.x", "ev_power_sensor": "sensor.x"}),
        ):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    module.normalise(mode, fields)

    def test_legacy_complete_only(self):
        v = module.migrate_legacy({
            "power_ground": "sensor.g", "power_first_floor": "sensor.f",
            "power_wallbox": "sensor.ev",
        })
        self.assertEqual(v["house_power_sources"], ["sensor.g", "sensor.f"])
        self.assertEqual(v["ev_power_sensor"], "sensor.ev")
        self.assertEqual(module.migrate_legacy({"power_ground": "sensor.g"}),
                         {"energy_mode": module.MODE_NONE})


if __name__ == "__main__":
    unittest.main()
