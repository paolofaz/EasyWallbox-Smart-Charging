"""SOC target source policy, independent of a Home Assistant installation."""
from pathlib import Path
import importlib.util
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]/"custom_components/easywallbox_smart"
PKG="_ew_soc_target_tests"
pkg=types.ModuleType(PKG)
pkg.__path__=[str(ROOT)]
sys.modules[PKG]=pkg
spec=importlib.util.spec_from_file_location(PKG+".target_policy",ROOT/"target_policy.py")
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)


class FakeState:
    def __init__(self,value,unit=None):
        self.state=value
        self.attributes={"unit_of_measurement":unit}


class TestSocTargetPolicy(unittest.TestCase):
    def test_entity_mode_ignores_stale_fixed_field(self):
        cfg={"target_mode":"entity","target_entity":"sensor.kia_limit",
             "target_default":90}
        self.assertEqual(module.resolved_target(cfg, FakeState("80","%")),80)
        self.assertIsNone(module.resolved_target(cfg,FakeState("unavailable","%")))
        self.assertIsNone(module.resolved_target(cfg,None))

    def test_entity_must_be_percentage_range(self):
        cfg={"target_mode":"entity","target_entity":"sensor.kia_limit"}
        for raw,unit in [("0","%"),("101","%"),("nan","%"),("80","kWh"),("unknown",None)]:
            with self.subTest(raw=raw,unit=unit):
                self.assertIsNone(module.resolved_target(cfg,FakeState(raw,unit)))
        self.assertEqual(module.resolved_target(cfg,FakeState("90",None)),90)

    def test_fixed_mode_ignores_entity_state(self):
        cfg={"target_mode":"fixed","target_default":85,
             "target_entity":"sensor.old_limit"}
        self.assertEqual(module.resolved_target(cfg,FakeState("65","%")),85)

    def test_bad_mode_is_never_assumed_fixed(self):
        for mode in ["mystery",{},["entity"],None]:
            with self.subTest(mode=str(mode)):
                cfg={"target_mode":mode,"target_default":80,
                     "target_entity":"sensor.target"}
                self.assertIsNone(module.selected_mode(cfg))
                self.assertIsNone(module.resolved_target(cfg,FakeState("80","%")))

    def test_0_1_0_compatibility_infers_source_precedence(self):
        old_both={"target_entity":"sensor.target","target_default":90}
        self.assertEqual(module.selected_mode(old_both),"entity")
        self.assertEqual(module.resolved_target(old_both,FakeState("80","%")),80)
        self.assertIsNone(module.resolved_target(old_both,None))
        old_fixed={"target_default":75}
        self.assertEqual(module.selected_mode(old_fixed),"fixed")
        self.assertEqual(module.resolved_target(old_fixed,None),75)

    def test_no_home_assistant_or_writes(self):
        src=(ROOT/"target_policy.py").read_text()
        for forbidden in ("homeassistant","services.","async_update_entry","write_text("):
            self.assertNotIn(forbidden,src)


if __name__=="__main__":
    unittest.main()
