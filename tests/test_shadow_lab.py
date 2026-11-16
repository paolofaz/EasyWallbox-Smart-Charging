"""Pure two-shadow comparison, no vehicle identity or Home Assistant needed."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import sys
import types
import unittest

COMP = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PKG = "_ew_shadow_lab_tests"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(COMP)]
sys.modules[PKG] = pkg
spec = importlib.util.spec_from_file_location(PKG + ".shadow_lab",
                                              COMP / "shadow_lab.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from importlib import import_module
core = import_module(PKG + ".core")
johnny = import_module(PKG + ".johnny_policy")

NOW = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)


def report(minute, kw, quality="ok", duplicate=None):
    return core.HouseSnapshot(None, None, quality,
                              sources_kw=(kw,),
                              observed_at=duplicate if duplicate is not None
                              else NOW + timedelta(minutes=minute))


class ShadowLabTest(unittest.TestCase):
    def test_two_infinite_sessions_have_independent_state_and_slack(self):
        states = None
        for minute in range(5):
            states, decisions = module.simulate_shadow(
                NOW + timedelta(minutes=minute),
                report(minute, 2.4), 4.4, 4., states,
            )
        self.assertEqual(set(states), {"wide", "medium"})
        self.assertEqual(set(decisions), {"wide", "medium"})
        self.assertEqual(states["wide"].session_id, "shadow-continuous-wide")
        self.assertEqual(states["medium"].session_id, "shadow-continuous-medium")
        self.assertEqual(johnny.margin_band(core.plan(
            NOW, core.SessionSnapshot(
                "x", "AUTO", "fake", False, True, 70., NOW, 80.,
                NOW + timedelta(minutes=30 + 60 + 180),
                36., .9, 4.),
        )), "wide")
        self.assertGreater(decisions["wide"].slack_minutes, 120)
        self.assertGreater(decisions["medium"].slack_minutes, 45)
        self.assertLessEqual(decisions["medium"].slack_minutes, 120)
        self.assertEqual(
            states["wide"].locked_budget_kwh,
            module.SHADOW_UNBOUNDED_BUDGET_KWH,
        )
        self.assertTrue(all(x.simulation_only for x in decisions.values()))

    def test_one_month_same_session_without_daily_or_budget_reset(self):
        states, _ = module.simulate_shadow(NOW, report(0, 2.4), 4.4, 4.)
        # Mid-month missing data must not inherit an artificial fresh report
        # or reset the synthetic session to a different vehicle.
        for offset in (1, 2, 180, 1_440, 4_320, 20_160, 43_200):
            when = NOW + timedelta(minutes=offset)
            states, decisions = module.simulate_shadow(
                when, core.HouseSnapshot(None, None, "unavailable"),
                4.4, 4., states)
            for band in ("wide", "medium"):
                self.assertEqual(states[band].session_id,
                                 f"shadow-continuous-{band}")
                self.assertNotEqual(decisions[band].reason,
                                    "session_budget_exhausted")

    def test_no_house_report_no_virtual_reduction(self):
        s, p = module.simulate_shadow(
            NOW, core.HouseSnapshot(None, None, "unavailable"), 4.4, 4.)
        self.assertEqual([x.action for x in p.values()],
                         ["insufficient_data", "insufficient_data"])

    def test_custom_max_applies_to_both_virtual_scenarios(self):
        states = None
        for minute in range(5):
            states, props = module.simulate_shadow(
                NOW+timedelta(minutes=minute), report(minute, 2.4),
                4.8, 3.8, states,
            )
        for band in ("wide", "medium"):
            self.assertLessEqual(states[band].original_kw, 3.8)
            if states[band].cap_kw is not None:
                self.assertLessEqual(states[band].cap_kw, 3.8)

    def test_bad_input_rejected_without_guessing(self):
        for kw, dpm in ((0., 4.4), (float("nan"), 4.4),
                        (4., 0.), (4., float("nan"))):
            with self.subTest(kw=kw, dpm=dpm):
                with self.assertRaises(ValueError):
                    module.simulate_shadow(NOW, report(0, .2), dpm, kw)

    def test_source_has_no_ha_device_commands_or_storage(self):
        txt = (COMP / "shadow_lab.py").read_text()
        for forbidden in ("homeassistant", "async_call", "bleak",
                          "open(", "requests", "write_text", "file_path"):
            self.assertNotIn(forbidden, txt)


if __name__ == "__main__":
    unittest.main()
