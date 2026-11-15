"""Fast offline M2 contract checks, including GUI and local brand assets."""
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "easywallbox_smart"


class TestM2Contract(unittest.TestCase):
    def test_configurable_vehicle_options_and_reload(self):
        flow = (INTEGRATION / "config_flow.py").read_text()
        coordinator = (INTEGRATION / "coordinator.py").read_text()
        self.assertIn("OptionsFlowWithReload", flow)
        self.assertIn("async_get_options_flow", flow)
        self.assertIn("self.config_entry.options", flow)
        self.assertIn("CONF_VEHICLE_OVERRIDES", coordinator)
        self.assertIn("per_car.get(identity, {})", coordinator)

    def test_waiting_planner_is_connected_and_time_bounded(self):
        coordinator = (INTEGRATION / "coordinator.py").read_text()
        self.assertIn("advise_departure(", coordinator)
        self.assertIn("self.advice.next_check_at", coordinator)
        self.assertIn("self.session.soc_at", coordinator)
        self.assertIn("EV_REPORT_AGE", coordinator)
        self.assertIn("_observe_house_only_in_charge(self.session.charging)", coordinator)
        self.assertNotIn("async_track_time_interval", coordinator)

    def test_canonical_english_strings_and_translations(self):
        strings = json.loads((INTEGRATION / "strings.json").read_text())
        english = json.loads((INTEGRATION / "translations/en.json").read_text())
        italian = json.loads((INTEGRATION / "translations/it.json").read_text())
        self.assertEqual(strings, english)
        for document in (english, italian):
            self.assertIn("config", document)
            self.assertIn("options", document)
            self.assertIn("vehicle", document["options"]["step"])
            self.assertIn("plan", document["entity"]["sensor"])

    def test_manifest_keys_are_hassfest_ordered(self):
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        keys = list(manifest)
        self.assertEqual(keys[:2], ["domain", "name"])
        self.assertEqual(keys[2:], sorted(keys[2:]))

    def test_brand_icon_is_real_square_png(self):
        data = (INTEGRATION / "brand/icon.png").read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (256, 256))


if __name__ == "__main__":
    unittest.main()
