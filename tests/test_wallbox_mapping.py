"""Manual ESPHome mapping and fail-closed contract tests."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"

def module(name):
    root = "test_discovery_pkg"
    pkg = sys.modules.get(root)
    if pkg is None:
        pkg = types.ModuleType(root)
        pkg.__path__ = [str(BASE)]
        sys.modules[root] = pkg
    fullname = root + "." + name
    if fullname not in sys.modules:
        spec = importlib.util.spec_from_file_location(fullname, BASE/(name+".py"))
        obj = importlib.util.module_from_spec(spec)
        sys.modules[fullname] = obj
        spec.loader.exec_module(obj)
    return sys.modules[fullname]

C = module("const")
M = module("wallbox_mapping")


class ManualMappingTests(unittest.TestCase):
    def setUp(self):
        self.config = {k: f"{domain}.{k}" for k, domain in C.WALLBOX_ENTITIES.items()}
        self.items = {eid: types.SimpleNamespace(domain=eid.split(".")[0], platform="esphome",
                      device_id="station", disabled_by=None) for eid in self.config.values()}

    def validate(self):
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.entity_registry = types.SimpleNamespace(async_get=lambda hass:
            types.SimpleNamespace(async_get=self.items.get))
        with patch.dict(sys.modules, {"homeassistant.helpers": helpers}):
            return M.mapping_error(None, self.config)

    def test_manual_names_are_not_guessed(self):
        self.assertIsNone(self.validate())

    def test_disallows_other_station_platform_domain_and_disabled_items(self):
        item = self.items[self.config[C.CONF_CONFIRMED_LIMIT]]
        for attribute, value in (("device_id", "other"), ("platform", "template"),
                                 ("domain", "number"), ("disabled_by", "user")):
            with self.subTest(attribute=attribute), patch.object(item, attribute, value):
                self.assertEqual(self.validate(), "invalid_wallbox_mapping")

    def test_missing_connection_in_previous_entry_is_repairable_from_options(self):
        del self.config[C.CONF_BLE_CONNECTED]
        self.assertEqual(self.validate(), "invalid_wallbox_mapping")
