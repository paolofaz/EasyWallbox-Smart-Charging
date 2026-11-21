"""Static RC safety contracts and translation/config smoke checks (offline)."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components/easywallbox_smart"


class RCStructureTest(unittest.TestCase):
    def test_metadata_and_translations_load(self):
        for p in ("manifest.json", "strings.json",
                  "translations/en.json", "translations/it.json"):
            with (COMP/p).open(encoding="utf-8") as fp:
                obj=json.load(fp)
            self.assertIsInstance(obj,dict)
        version=json.loads((COMP/"manifest.json").read_text())["version"]
        self.assertIn("rc",version)

    def test_all_python_modules_compile(self):
        for src in COMP.glob("*.py"):
            with self.subTest(source=src.name):
                compile(src.read_text(encoding="utf-8"),str(src),"exec")

    def test_delayed_pause_does_not_allow_unplugged_command(self):
        text=(COMP/"rc_controller.py").read_text()
        self.assertIn('current["cable"] is not True',text)
        self.assertIn('self._wallbox_cable(now)',text)
        self.assertIn('observed_charging is not True',text)

    def test_only_one_real_service_dispatcher(self):
        sources=list(COMP.glob("*.py"))
        found=[]
        for src in sources:
            if "services.async_call(" in src.read_text():
                found.append(src.name)
        self.assertEqual(found,["rc_controller.py"])

    def test_no_legacy_shadow_and_no_unneeded_recording_entities(self):
        forbidden={"shadow_v2.py","shadow_lab.py","shadow_log.py","johnny_policy.py",
                   "control_guard.py","start_routine.py","coordinator.py","core.py"}
        self.assertFalse(forbidden.intersection({f.name for f in COMP.glob("*.py")}))
        text=(COMP/"sensor.py").read_text()
        self.assertIn('"state":',text)
        self.assertIn('"planner":',text)
        self.assertNotIn("house_kw",text)
        self.assertNotIn("async_update",text)

    def test_ui_exposes_requested_controls(self):
        required=["switch.py","select.py","time.py",
                  "sensor.py","config_flow.py"]
        for p in required:
            self.assertTrue((COMP/p).exists())

    def test_no_secret_user_ids_or_ha_storage_dumps(self):
        for p in COMP.glob("*.py"):
            text=p.read_text()
            self.assertNotIn("api_password",text)
            self.assertNotIn("wallbox_pin",text)
            self.assertNotIn("ssid:",text.lower())

    def test_no_start_stop_service_other_than_delayed_handshake(self):
        tree=ast.parse((COMP/"rc_controller.py").read_text())
        sends=[node for node in ast.walk(tree) if isinstance(node,ast.AsyncFunctionDef)
               and node.name=="_send"]
        self.assertEqual(len(sends),1)
        code=ast.get_source_segment((COMP/"rc_controller.py").read_text(),sends[0])
        self.assertIn('kind in ("pause", "park", "soc_stop", "delay_pause")',code)
        self.assertIn('self._park_owned or self._dpm_lease',code)


if __name__=="__main__":
    unittest.main()
