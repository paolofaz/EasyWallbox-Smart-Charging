"""Pure source normalization tests, no Home Assistant installation needed."""
import importlib.util
from datetime import datetime
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

F = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart/sources.py"
spec = importlib.util.spec_from_file_location("ew_sources_test", F)
source = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = source
spec.loader.exec_module(source)


class TestSources(unittest.TestCase):
    def test_unit_conversion_and_invalid(self):
        self.assertEqual(source.power_kw("1500", "W"), 1.5)
        self.assertEqual(source.power_kw("1.8", "kW"), 1.8)
        for x in ("unavailable", "unknown", "nan", "-50", None):
            self.assertIsNone(source.power_kw(x, "W"))
        self.assertIsNone(source.power_kw(5, "MW"))

    def test_binary_state_not_assumed(self):
        self.assertIs(source.on("on"), True)
        self.assertIs(source.on("off"), False)
        self.assertIsNone(source.on("unknown"))

    def test_departure_is_based_on_departure_day(self):
        tz = ZoneInfo("Europe/Rome")
        friday = datetime(2026, 11, 13, 20, 0, tzinfo=tz)
        result = source.next_departure(friday, "07:00", "08:00")
        self.assertEqual((result.weekday(), result.hour), (5, 8))

    def test_dst_transition_is_aware(self):
        tz = ZoneInfo("Europe/Rome")
        now = datetime(2026, 3, 28, 22, tzinfo=tz)
        result = source.next_departure(now, "07:00", "08:00")
        self.assertEqual(result.utcoffset().total_seconds(), 7200)
        self.assertEqual(result.hour, 8)

    def test_invalid_clock_returns_none(self):
        tz = ZoneInfo("Europe/Rome")
        self.assertIsNone(source.next_departure(datetime(2026, 11, 15, tzinfo=tz), "99:00", "99:00"))


if __name__ == "__main__":
    unittest.main()
