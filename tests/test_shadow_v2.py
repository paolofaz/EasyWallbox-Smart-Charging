"""Independent, simulation-only regressions for Johnny V2."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib
import sys
import types
import unittest

COMP = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PKG = "_ew_johnny_v2_tests"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(COMP)]
sys.modules[PKG] = pkg
module = importlib.import_module(PKG + ".shadow_lab")
core = importlib.import_module(PKG + ".core")

NOW = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)


def snapshot(minutes: int, kw: float | None, age=0):
    if kw is None:
        return core.HouseSnapshot(None, None, "unavailable")
    return core.HouseSnapshot(None, None, "ok",
        sources_kw=(kw,),
        observed_at=NOW + timedelta(minutes=minutes, seconds=-age))


def step(states, minute, kw, dpm=4.4, age=0):
    return module.simulate_shadow_v2(
        NOW + timedelta(minutes=minute), snapshot(minute, kw, age),
        dpm, 4.0, states)


class JohnnyV2ShadowTest(unittest.TestCase):

    def test_small_sustained_pressure_starts_single_buffer_after_three_minutes(self):
        st = None
        actions = []
        for m in range(8):
            st, d = step(st, m, .65)
            actions.append(d.action)
        self.assertEqual(st.kind, "buffer")
        self.assertEqual(st.mode, "LIMITED")
        self.assertAlmostEqual(st.cap_kw, 3.6)
        self.assertEqual(actions.count("reduce"), 1)
        self.assertEqual(actions.index("reduce"), 3)

    def test_no_buffer_when_dpm_has_real_headroom(self):
        st = None
        for m in range(15):
            st, dec = step(st, m, .65, dpm=4.8)
        self.assertEqual(st.mode, "NORMAL")
        self.assertNotEqual(dec.action, "reduce")

    def test_one_short_burst_not_a_buffer(self):
        st = None
        for m, kw in enumerate((.1, .65, .65, .1, .1, .65, .1)):
            st, d = step(st, m, kw)
            self.assertNotEqual(d.action, "reduce")
        self.assertEqual(st.mode, "NORMAL")

    def test_buffer_restores_only_after_ten_fresh_quiet_minutes(self):
        st = None
        for m in range(4):
            st, _ = step(st, m, .65)
        self.assertEqual(st.kind, "buffer")
        for m in range(4, 14):
            st, d = step(st, m, .20)
            self.assertEqual(st.kind, "buffer")
        st, d = step(st, 14, .20)
        self.assertEqual(d.action, "restore")
        self.assertEqual(st.mode, "NORMAL")
        self.assertAlmostEqual(st.cap_kw, 4.0)

    def test_strong_entry_then_one_limited_downward_adjustment(self):
        st = None
        events = []
        for m in range(22):
            kw = 1.8 if m < 5 else 2.7
            st, d = step(st, m, kw)
            if d.action in ("reduce", "adjust", "restore"):
                events.append((m, d.action, d.proposed_cap_kw))
        self.assertTrue(any(a == "reduce" for _, a, _ in events))
        self.assertTrue(any(a == "adjust" for _, a, _ in events), events)
        first = next(c for _, a, c in events if a == "reduce")
        adj = next(c for _, a, c in events if a == "adjust")
        self.assertAlmostEqual(first-adj, .4)
        self.assertLessEqual(sum(1 for _, a, _ in events if a == "adjust"), 2)
        self.assertEqual(st.kind, "strong")

    def test_duplicate_or_stale_report_cannot_start_buffer(self):
        st = None
        st, _ = step(st, 0, .65)
        for m in (1, 2, 3, 4):
            st, d = step(st, m, .65, age=60*m)
            self.assertNotEqual(d.action, "reduce")
        self.assertEqual(st.mode, "NORMAL")

    def test_changed_dpm_reference_discards_old_virtual_state(self):
        st = None
        for m in range(4):
            st, _ = step(st, m, .65)
        self.assertEqual(st.kind, "buffer")
        st, d = step(st, 4, .65, dpm=4.8)
        self.assertEqual(st.kind, "normal")
        self.assertEqual(st.cap_kw, 4.0)
        self.assertEqual(d.reason, "dpm_reference_changed")

    def test_no_physical_actuation_or_storage_code(self):
        source = (COMP / "shadow_v2.py").read_text()
        for forbidden in ("homeassistant", "async_call", "bleak",
                          "open(", "write_text", "requests"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
