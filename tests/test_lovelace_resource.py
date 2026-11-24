"""prior iterations automatic Lovelace resource only, with manual card placement."""
import ast
import json
from pathlib import Path
import unittest

COMP = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"

class CardResourceRC10(unittest.TestCase):
    def test_manifest(self):
        manifest = json.loads((COMP / "manifest.json").read_text())
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertIn("lovelace", manifest["dependencies"])

    def test_resource_not_dashboard(self):
        source = (COMP / "lovelace_resources.py").read_text()
        ast.parse(source)
        self.assertIn("await resources.async_get_info()", source)
        self.assertIn('"res_type": "module"', source)
        for forbidden in ("LovelaceStorage", "async_register_built_in_panel",
                          "async_remove_panel", "ui-lovelace.yaml"):
            self.assertNotIn(forbidden, source)

    def test_automatic_registration(self):
        init = (COMP / "__init__.py").read_text()
        self.assertIn("await async_register_card_resource(hass)", init)
        self.assertNotIn("history_dashboard", init)

    def test_card_remains_user_placeable(self):
        script = (COMP / "frontend/session-history-card.js").read_text()
        self.assertIn("window.customCards", script)
        self.assertIn("easywallbox_smart/sessions", script)
