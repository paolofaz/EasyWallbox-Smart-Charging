"""Offline tests for the charging-only, disk-free M1 window."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "easywallbox_smart"
pkg = types.ModuleType("_ew_window_test_package")
pkg.__path__ = [str(BASE)]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location(
    "_ew_window_test_package.charging_window", BASE / "charging_window.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
ChargingWindow = module.ChargingWindow
peak_cap = module.peak_cap

T0 = datetime(2026, 11, 14, 20, tzinfo=timezone.utc)


def at(seconds: int):
    return T0 + timedelta(seconds=seconds)


def steady(window: ChargingWindow, *, kw=0.4, until=300, start=0):
    for s in range(start, until + 1, 20):
        window.add(at(s), kw, total_kw=kw + 2.0)


class TestVolatileWindow(unittest.TestCase):
    def test_idle_never_collects_and_switch_off_clears_memory(self):
        w = ChargingWindow()
        self.assertFalse(w.add(at(0), 0.4, total_kw=2.4))
        self.assertEqual(w.count, 0)
        self.assertEqual(
            w.assess_rise(at(300), current_limit_kw=2,
                          original_limit_kw=4, available_kw=4.4).status,
            "inactive",
        )
        w.set_charging(True)
        steady(w)
        self.assertGreater(w.count, 0)
        w.set_charging(False)
        self.assertEqual(w.count, 0)
        w.set_charging(True)
        self.assertEqual(
            w.assess_rise(at(300), current_limit_kw=2,
                          original_limit_kw=4, available_kw=4.4).reason,
            "empty_window",
        )

    def test_single_valid_peak_uses_house_excluding_ev(self):
        w = ChargingWindow()
        w.set_charging(True)
        w.add(at(0), 2.1, total_kw=5.1)
        peak = w.latest_trigger(at(1), 5.0)
        self.assertIsNotNone(peak)
        self.assertEqual(peak.house_kw, 2.1)
        self.assertEqual(
            peak_cap(available_kw=4.4, house_at_peak_kw=peak.house_kw,
                     authorized_limit_kw=4.0),
            2.0,
        )
        self.assertIsNone(w.latest_trigger(at(120), 5.0))
        self.assertIsNone(
            peak_cap(available_kw=4.4, house_at_peak_kw=2.1,
                     authorized_limit_kw=4, optional_reduction_allowed=False)
        )

    def test_last_low_value_does_not_erase_peak_in_five_minute_window(self):
        w = ChargingWindow()
        w.set_charging(True)
        for s in range(0, 601, 20):
            house = 2.5 if s == 280 else 0.4
            w.add(at(s), house, total_kw=house + 2.0)
            if s == 300:
                first = w.assess_rise(at(s), current_limit_kw=2.0,
                                      original_limit_kw=4, available_kw=4.4)
        self.assertEqual(first.status, "hold")
        self.assertEqual(first.house_peak_kw, 2.5)
        later = w.assess_rise(at(600), current_limit_kw=2.0,
                              original_limit_kw=4.0, available_kw=4.4)
        self.assertEqual(later.status, "raise")
        self.assertEqual(later.proposed_limit_kw, 2.4)
        self.assertEqual(later.safe_limit_kw, 3.8)

    def test_gaps_and_stale_values_never_allow_rise(self):
        w = ChargingWindow()
        w.set_charging(True)
        w.add(at(0), 0.3)
        w.add(at(300), 0.3)
        self.assertEqual(
            w.assess_rise(at(300), current_limit_kw=2,
                          original_limit_kw=4, available_kw=4.4).reason,
            "gap_in_window",
        )
        self.assertEqual(
            w.assess_rise(at(400), current_limit_kw=2,
                          original_limit_kw=4, available_kw=4.4).reason,
            "stale_source",
        )

    def test_incoherent_data_does_not_become_zero(self):
        w = ChargingWindow()
        w.set_charging(True)
        for s in range(0, 301, 30):
            w.add(at(s), 0.3 if s != 150 else 0.0,
                  total_kw=2.5, coherent=s != 150)
        assessment = w.assess_rise(
            at(300), current_limit_kw=2, original_limit_kw=4, available_kw=4.4
        )
        self.assertEqual(assessment.status, "insufficient_data")
        self.assertEqual(assessment.reason, "incoherent_house")
        self.assertIsNone(w.latest_trigger(at(150), 2.0))  # latest point lies in future

    def test_validated_window_allows_one_small_step_not_a_jump(self):
        w = ChargingWindow()
        w.set_charging(True)
        steady(w, kw=0.2)
        a = w.assess_rise(
            at(300), current_limit_kw=2.0, original_limit_kw=4,
            available_kw=4.4
        )
        self.assertEqual(a.proposed_limit_kw, 2.4)
        b = w.assess_rise(
            at(300), current_limit_kw=4.0, original_limit_kw=4,
            available_kw=4.4
        )
        self.assertEqual(b.status, "hold")  # original authorized cap reached
        self.assertEqual(b.reason, "insufficient_headroom")

    def test_dont_infer_a_stop_below_hardware_minimum(self):
        self.assertIsNone(peak_cap(
            available_kw=4.4, house_at_peak_kw=3.2, authorized_limit_kw=4
        ))
        self.assertIsNone(peak_cap(
            available_kw=4.4, house_at_peak_kw=None, authorized_limit_kw=4
        ))
        self.assertIsNone(peak_cap(
            available_kw=4.4, house_at_peak_kw=float("nan"), authorized_limit_kw=4
        ))

    def test_memory_is_time_and_count_bounded(self):
        w = ChargingWindow()
        w.set_charging(True)
        for s in range(1802):
            w.add(at(s), .4)
        self.assertLessEqual(w.count, module.MAX_POINTS)
        self.assertLessEqual(w.count, 1201)

    def test_out_of_order_invalid_timestamps_and_no_second_sample(self):
        w = ChargingWindow()
        w.set_charging(True)
        self.assertFalse(w.add(datetime(2026, 11, 14, 20), .2))
        self.assertTrue(w.add(at(10), .2))
        self.assertFalse(w.add(at(10), .2))
        self.assertFalse(w.add(at(5), .2))
        self.assertEqual(w.count, 1)


if __name__ == "__main__":
    unittest.main()
