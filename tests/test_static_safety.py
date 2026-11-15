"""Safety fence: zero actuation services and no periodic monitor loop."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"


class TestM2Safety(unittest.TestCase):
    def test_no_actuating_services_anywhere(self):
        for path in ROOT.glob("*.py"):
            content = path.read_text()
            for forbidden in ("services.async_call(", "services.call(",
                              "switch.turn_on", "switch.turn_off", "number.set_value",
                              "async_track_time_interval", "_storage.Store"):
                self.assertNotIn(forbidden, content, f"Unsafe token {forbidden} in {path.name}")

    def test_source_modules_are_independent_of_ha(self):
        for name in ("core.py", "sources.py"):
            tree = ast.parse((ROOT / name).read_text())
            imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertFalse(any(n and n.startswith("homeassistant") for n in imported))

    def test_no_high_frequency_state_reporting(self):
        text = (ROOT / "coordinator.py").read_text()
        self.assertIn("_observe_house_only_in_charge(self.session.charging)", text)
        self.assertIn("signature != self._fingerprint", text)
        self.assertNotIn("async_track_time_interval", text)


if __name__ == "__main__":
    unittest.main()
