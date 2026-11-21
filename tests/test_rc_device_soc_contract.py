"""Static contracts for HA device grouping and explicitly opted-in SOC stop."""
from pathlib import Path
import ast
import json
import unittest

BASE = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"


class DeviceAndStopContract(unittest.TestCase):
    def test_each_exposed_platform_attaches_exactly_one_logical_device(self):
        device = (BASE/"device.py").read_text()
        self.assertIn("DeviceInfo(", device)
        self.assertIn("identifiers={(DOMAIN, entry.entry_id)}", device)
        for platform in ("sensor", "select", "switch", "time", "number"):
            with self.subTest(platform=platform):
                src=(BASE/f"{platform}.py").read_text()
                self.assertIn("controller_device_info(entry)",src)
                self.assertIn("_attr_unique_id",src)

    def test_only_two_diagnostic_sensors(self):
        src=(BASE/"sensor.py").read_text()
        self.assertIn('"state":',src)
        self.assertIn('"planner":',src)
        self.assertIn('if kind in ("state", "planner"):',src)
        self.assertIn('"vehicle":',src)
        self.assertIn('"phase":',src)
        self.assertIn('"energy":',src)
        self.assertIn('"finish":',src)
        self.assertIn("EntityCategory.DIAGNOSTIC",src)

    def test_soc_stop_is_opt_in_and_does_not_redefine_charging_start(self):
        conf=(BASE/"config_flow.py").read_text()
        self.assertIn("CONF_STOP_AT_TARGET, default=False",conf)
        self.assertIn("CONF_STOP_AT_TARGET, default=old.get(CONF_STOP_AT_TARGET, False)",conf)
        code=(BASE/"rc_controller.py").read_text()
        self.assertIn('if kind == "soc_stop":',code)
        self.assertIn('current["charging"] is True',code)
        self.assertIn("self._soc_stop_done = True",code)
        self.assertIn('if self._soc_stop_done:',code)
        self.assertIn("SOC_STOP_TTL = timedelta(minutes=5)",code)
        self.assertIn("SOC_STOP_REFRESH_INTERVAL = timedelta(minutes=20)",code)
        self.assertIn('observed is False and ev is not None and ev < .03',code)
        self.assertIn('self._blocked = "unconfirmed_" + p.kind + "_no_retry"',code)

    def test_fixed_slider_only_for_opted_in_fixed_target(self):
        src=(BASE/"number.py").read_text()
        self.assertIn("car.get(CONF_STOP_AT_TARGET) is True and CONF_TARGET_FIXED in car",src)
        self.assertIn("_attr_native_min_value = 80.0",src)
        self.assertIn("_attr_native_max_value = 100.0",src)
        self.assertIn("_attr_native_step = 5.0",src)
        self.assertIn("async_set_fixed_target",src)

    def test_no_hardcoded_family_ids_or_duplicated_integration_target(self):
        for src in BASE.glob("*.py"):
            text=src.read_text()
            self.assertNotIn("input_number.limite_carica_batteria_500",text)
            self.assertNotIn("button.fiat_500_deep_refresh",text)
            ast.parse(text)
        self.assertIn('"number"',(BASE/"const.py").read_text())

    def test_italian_and_english_stop_configuration_is_labeled(self):
        for path in ("strings.json","translations/it.json","translations/en.json"):
            obj=json.loads((BASE/path).read_text())
            self.assertIn("stop_at_target",obj["config"]["step"]["vehicle"]["data"])
            self.assertIn("stop_at_target",obj["options"]["step"]["edit_vehicle"]["data"])


if __name__=="__main__":
    unittest.main()
