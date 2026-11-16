"""Private JSONL output is tested only in temporary directories."""
from datetime import datetime
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


if __name__ == "__main__":
    unittest.main()
