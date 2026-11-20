"""Private JSONL output is tested only in temporary directories."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest

FILE = (Path(__file__).resolve().parents[1] /
        "custom_components/easywallbox_smart/shadow_log.py")
spec = importlib.util.spec_from_file_location("_ew_shadow_log_tests", FILE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def entry(time, wide="hold"):
    return {"time_local": time, "model": "synthetic_always_charging",
            "house_kw": 2.345, "dpm_model_source": "configured_model",
            "wide": {"action": wide}, "medium": {"action": "hold"}}


class TestShadowLog(unittest.TestCase):
    def test_append_and_local_day_rotation(self):
        with tempfile.TemporaryDirectory() as root:
            count, name = module.append_shadow_rows(root, [
                entry("2026-11-16T23:59:10+01:00"),
                entry("2026-11-17T00:00:00+01:00", "reduce"),
            ])
            self.assertEqual(count, 2)
            self.assertEqual(name, "shadow_2026-11-17.jsonl")
            paths = list(Path(root).glob("*.jsonl"))
            self.assertEqual(len(paths), 2)
            data = json.loads(
                (Path(root) / "shadow_2026-11-17.jsonl").read_text())
            self.assertEqual(data["wide"]["action"], "reduce")
            count2, _ = module.append_shadow_rows(root, [
                entry("2026-11-17T00:01:00+01:00", "restore")])
            self.assertEqual(count2, 1)
            self.assertEqual(len((Path(root) /
                "shadow_2026-11-17.jsonl").read_text().splitlines()), 2)

    def test_v2_separate_file_and_safe_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            count, name = module.append_shadow_rows(
                root, [entry("2026-11-19T10:00:00+01:00")], "shadow_v2")
            self.assertEqual(count, 1)
            self.assertEqual(name, "shadow_v2_2026-11-19.jsonl")
            self.assertTrue((Path(root) / name).is_file())
            with self.assertRaises(ValueError):
                module.append_shadow_rows(
                    root, [entry("2026-11-19T10:00:00+01:00")], "../bad")

    def test_v2_model_comparison_is_append_only(self):
        with tempfile.TemporaryDirectory() as root:
            a = entry("2026-11-20T10:00:00+01:00")
            a["v2"] = {"action":"hold","cap_kw":4.2}
            a["v2_dpm46"] = {"action":"hold","cap_kw":4.2}
            count, name = module.append_shadow_rows(root,[a],"shadow_v2_compare")
            self.assertEqual(count,1)
            self.assertEqual(name,"shadow_v2_compare_2026-11-20.jsonl")
            count, _ = module.append_shadow_rows(root,[a],"shadow_v2_compare")
            self.assertEqual(count,1)
            self.assertEqual(len((Path(root)/name).read_text().splitlines()),2)

    def test_empty_is_noop(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(module.append_shadow_rows(root, []), (0, ""))
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_invalid_file_date_not_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                module.append_shadow_rows(root, [entry("../illegal")])
            self.assertFalse(list(Path(root).glob("*.jsonl")))

    def test_bounds_file_size_and_no_truncate(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "shadow_2026-11-16.jsonl"
            path.write_bytes(b"x" * (module.MAX_DAILY_BYTES - 5))
            with self.assertRaises(OSError):
                module.append_shadow_rows(root, [
                    entry("2026-11-16T18:00:00+01:00")
                ])
            self.assertEqual(path.stat().st_size,
                             module.MAX_DAILY_BYTES - 5)

    def test_non_finite_samples_not_logged_as_invalid_json(self):
        with tempfile.TemporaryDirectory() as root:
            wrong = entry("2026-11-16T19:00:00+01:00")
            wrong["house_kw"] = float("nan")
            with self.assertRaises(ValueError):
                module.append_shadow_rows(root, [wrong])



class TestShadowLogSampler(unittest.TestCase):
    START = datetime(2026, 11, 16, 17, 48, tzinfo=timezone.utc)

    def record(self, when, power=.58, quality="ok", dpm=4.8):
        return {
            "time_local": when.isoformat(timespec="seconds"),
            "house_kw": power if quality == "ok" else None,
            "house_data_quality": quality,
            "house_report_local": when.isoformat(),
            "dpm_observed_kw": dpm,
            "dpm_model_kw": dpm,
            "dpm_model_source": "confirmed_sensor",
            "ev_baseline_kw": 4.0,
            "model": "continuous_two_band_no_real_vehicle",
            "wide": {"action": "hold", "cap_kw": 4.0, "state": "NORMAL"},
            "medium": {"action": "hold", "cap_kw": 4.0, "state": "NORMAL"},
        }

    def test_43_reports_in_three_minutes_become_three_rows_and_final_flush(self):
        sampler = module.ShadowLogSampler()
        rows = []
        for n in range(43):
            when = self.START + timedelta(seconds=4*n)
            row = sampler.observe(
                when, when, self.record(when, .58 + (n % 7) / 100),
                (("wide", "hold", "NORMAL", 4.0),),
            )
            if row is not None:
                rows.append(row)
        self.assertEqual([r["log_kind"] for r in rows],
                         ["start", "periodic", "periodic"])
        final = sampler.finish(self.START + timedelta(minutes=3))
        self.assertEqual(final["log_kind"], "end")
        self.assertEqual(
            sum(r["house_window"]["samples"] for r in rows + [final]), 43,
        )
        self.assertAlmostEqual(rows[1]["house_window"]["min_kw"], .58)
        self.assertAlmostEqual(rows[1]["house_window"]["max_kw"], .64)
        self.assertGreater(rows[1]["house_window"]["mean_kw"], .58)

    def test_repeated_timestamp_is_not_another_sample_or_log(self):
        sampler = module.ShadowLogSampler()
        first = self.record(self.START)
        self.assertEqual(
            sampler.observe(self.START, self.START, first, ("normal",))["log_kind"],
            "start",
        )
        later = self.START + timedelta(seconds=10)
        self.assertIsNone(sampler.observe(later, self.START,
                                         self.record(later, .66), ("normal",)))
        changed = sampler.observe(
            later, self.START, self.record(later, .66), ("limited",),
        )
        self.assertEqual(changed["log_kind"], "change")
        self.assertEqual(changed["house_window"]["samples"], 0)
        self.assertIsNone(sampler.finish(later))

    def test_decision_data_quality_and_dpm_change_are_immediate(self):
        sampler = module.ShadowLogSampler()
        base = self.record(self.START)
        sampler.observe(self.START, self.START, base, ("hold",))
        one = self.START + timedelta(seconds=5)
        reduced = sampler.observe(one, one, self.record(one, 2.0),
                                  ("reduce", "LIMITED", 2.2))
        self.assertEqual(reduced["log_kind"], "change")
        self.assertEqual(reduced["house_window"]["max_kw"], 2.0)
        stale = one + timedelta(seconds=5)
        change = sampler.observe(stale, None,
                                 self.record(stale, quality="unavailable"),
                                 ("reduce", "LIMITED", 2.2))
        self.assertEqual(change["log_kind"], "change")
        self.assertEqual(change["house_data_quality"], "unavailable")
        new_dpm = stale + timedelta(seconds=5)
        change = sampler.observe(new_dpm, None, self.record(new_dpm, dpm=4.4),
                                 ("reduce", "LIMITED", 2.2))
        self.assertEqual(change["log_kind"], "change")
        self.assertEqual(change["dpm_observed_kw"], 4.4)

    def test_local_day_rollover_and_file_size_estimate(self):
        sampler = module.ShadowLogSampler()
        rows = []
        # 24 hours of Shelly events at 5-second intervals, no actual changes.
        for seconds in range(0, 24 * 3600, 5):
            when = self.START + timedelta(seconds=seconds)
            row = sampler.observe(
                when, when, self.record(when), ("hold",),
            )
            if row:
                rows.append(row)
        self.assertLessEqual(len(rows), 1441)
        self.assertGreaterEqual(len(rows), 1440)
        self.assertTrue(any(r["log_kind"] == "day_rollover" for r in rows))
        encoded = sum(len(json.dumps(row, separators=(",", ":")).encode()) + 1
                      for row in rows)
        self.assertLess(encoded, module.MAX_DAILY_BYTES)

if __name__ == "__main__":
    unittest.main()
