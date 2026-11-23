"""Boundary tests for explicit delay; never silently choose next day >12h."""
from __future__ import annotations
from datetime import datetime,time,timedelta
from zoneinfo import ZoneInfo
import importlib.util, sys, unittest
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"custom_components/easywallbox_smart/delay_window.py"
spec=importlib.util.spec_from_file_location("rc_delay_window",p)
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)
TZ=ZoneInfo("Europe/Rome")

class DelayWindowTest(unittest.TestCase):
    def now(self,h,minute=0):
        return datetime(2026,11,21,h,minute,tzinfo=TZ)
    def test_20_00_with_19_00_is_23_hours_and_rejected(self):
        with self.assertRaisesRegex(ValueError,"within_12_hours"):
            m.validate_delay(self.now(20),time(19),"Europe/Rome")
    def test_20_00_with_01_00_is_next_day_five_hours(self):
        dt=m.validate_delay(self.now(20),time(1),"Europe/Rome")
        self.assertEqual((dt.day,dt.hour),(22,1))
        self.assertEqual(dt-self.now(20),timedelta(hours=5))
    def test_20_00_to_08_00_is_exact_twelve_hours_allowed(self):
        dt=m.validate_delay(self.now(20),time(8),"Europe/Rome")
        self.assertEqual(dt-self.now(20),timedelta(hours=12))
    def test_20_00_to_08_01_exceeds_twelve(self):
        with self.assertRaisesRegex(ValueError,"within_12_hours"):
            m.validate_delay(self.now(20),time(8,1),"Europe/Rome")
    def test_same_clock_minute_does_not_wait_full_day(self):
        with self.assertRaisesRegex(ValueError,"within_12_hours"):
            m.validate_delay(self.now(20),time(20),"Europe/Rome")
    def test_23_00_to_00_30_crosses_midnight(self):
        target=m.validate_delay(self.now(23),time(0,30),"Europe/Rome")
        self.assertEqual(target-self.now(23),timedelta(minutes=90))
    def test_bound_checked_against_real_utc_elapsed_time(self):
        now=datetime(2026,10,24,20,0,tzinfo=TZ)
        target=m.validate_delay(now,time(7),"Europe/Rome")
        # October DST end: 11 wall-clock hours but 12 real hours.
        self.assertEqual(target.astimezone(ZoneInfo("UTC"))-
                         now.astimezone(ZoneInfo("UTC")),timedelta(hours=12))

if __name__=="__main__":
    unittest.main()
