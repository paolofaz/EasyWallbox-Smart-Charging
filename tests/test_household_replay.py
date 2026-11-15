"""Offline replay tests for intermittent domestic load (e.g. an iron).

All numbers are SYNTHETIC. Real household traces must never be committed to
a public repository. All EV and limit fields are hypothetical simulations.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
T = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


core = load("_ew_iron_core", ROOT / "custom_components/easywallbox_smart/core.py")
replay = load("_ew_iron_trace", ROOT / "tests/household_replay.py")


def simulated_car(now, *, charging=True, mode="AUTO"):
    # Do not confuse synthetic EV charging with actual wallbox observations.
    age = int((now - T).total_seconds() // 60)
    observed = T + timedelta(minutes=(age // 15) * 15)
    return core.SessionSnapshot(
        session_id="synthetic_example", mode=mode, vehicle_id="hypothetical_car",
        vehicle_ambiguous=False, charging=charging, soc=40, soc_at=observed,
        target_soc=80, departure_at=T + timedelta(hours=15),
        usable_capacity_kwh=77, ac_efficiency=.9, sustainable_kw=4,
    )


def csv_trace(items):
    lines = ["timestamp,power,unit,quality"]
    for minute, kw, quality in items:
        stamp = (T + timedelta(minutes=minute)).isoformat()
        value = "" if kw is None else str(kw)
        lines.append(f"{stamp},{value},kW,{quality}")
    return "\n".join(lines) + "\n"


def actions(items, *, charging=True):
    trace = replay.read_household_csv(csv_trace(items))
    return replay.replay_trace(
        trace, core, lambda now: simulated_car(now, charging=charging)
    )


class TestHouseholdReplay(unittest.TestCase):
    def test_periodic_iron_does_not_oscillate_cap(self):
        # The hot plate cycles: 3 min on, 4 min off. Not an actual recording.
        items = [(m, 2.1 if m % 7 < 3 else .35, "ok") for m in range(61)]
        out = actions(items)
        proposals = [p for _, p in out]
        self.assertEqual(sum(p.action == "reduce" for p in proposals), 1)
        self.assertFalse(any(p.action == "restore" for p in proposals))
        self.assertTrue(all(p.simulation_only for p in proposals))

    def test_long_real_quiet_interval_allows_one_restore(self):
        items = [(0, 2.1, "ok"), (1, 2.1, "ok"),
                 (2, .25, "ok"), (6, .25, "ok"), (12, .25, "ok")]
        props = [p for _, p in actions(items)]
        self.assertEqual([p.action for p in props].count("reduce"), 1)
        self.assertEqual([p.action for p in props].count("restore"), 1)
        self.assertEqual(props[-1].reason, "documented_quiet")

    def test_unknown_power_is_not_zero_or_quiet(self):
        items = [(0, 2.1, "ok"), (1, 2.1, "ok"), (2, .25, "ok"),
                 (5, None, "unavailable"), (8, .25, "ok"), (12, .25, "ok")]
        out = actions(items)
        self.assertEqual(out[3][0].kw, None)
        self.assertEqual(out[3][1].reason, "house_data_not_trusted")
        self.assertEqual([p.action for _, p in out].count("restore"), 0)

    def test_stale_numeric_value_is_ignored(self):
        trace = replay.read_household_csv(csv_trace([
            (0, 2.1, "ok"), (1, 2.1, "stale")
        ]))
        self.assertIsNone(trace[1].kw)
        out = replay.replay_trace(trace, core, simulated_car)
        self.assertEqual(out[-1][1].action, "insufficient_data")

    def test_old_sample_gap_cannot_fake_60_second_trigger(self):
        items = [(0, 2.1, "ok"), (4, 2.1, "ok")]
        out = actions(items)
        self.assertEqual(sum(p.action == "reduce" for _, p in out), 0)
        self.assertEqual(out[-1][1].reason, "confirming_house_load")

    def test_real_house_pattern_without_charging_is_inactive(self):
        items = [(0, 2.1, "ok"), (1, 2.1, "ok")]
        out = actions(items, charging=False)
        self.assertTrue(all(p.action == "inactive" for _, p in out))

    def test_watt_and_kilowatt_unit_conversion(self):
        csv = ("timestamp,power,unit,quality\n"
               f"{T.isoformat()},2200,W,ok\n"
               f"{(T + timedelta(minutes=1)).isoformat()},0.4,kW,ok\n")
        samples = replay.read_household_csv(csv)
        self.assertEqual([s.kw for s in samples], [2.2, .4])

    def test_explicit_zero_is_valid_not_missing(self):
        trace = replay.read_household_csv(csv_trace([(0, 0.0, "ok")]))
        self.assertEqual(trace[0].kw, 0.0)
        self.assertEqual(trace[0].quality, "ok")

    def test_strict_timestamp_and_quality_validation(self):
        malformed = [
            "timestamp,power,unit,quality\n2026-11-15T21:00:00,2000,W,ok\n",
            csv_trace([(0, 2.0, "ok"), (0, 2.5, "ok")]),
            csv_trace([(0, None, "ok")]),
            csv_trace([(0, 2.5, "incorrect")]),
            csv_trace([(0, -3.0, "ok")]),
            csv_trace([(0, float("nan"), "ok")]),
            "timestamp,power,unit,quality\n" + T.isoformat() + ",2000,MW,ok\n",
            "timestamp,power\n" + T.isoformat() + ",2000\n",
        ]
        for n, csv in enumerate(malformed):
            with self.subTest(case=n), self.assertRaises(ValueError):
                replay.read_household_csv(csv)

    def test_no_device_calls_and_no_io(self):
        source=(ROOT / "tests/household_replay.py").read_text()
        for forbidden in (
            "homeassistant", "async_call(", "requests", "urlopen(",
            "write_text(", "open(", "bleak", "mqtt", "api_key"
        ):
            self.assertNotIn(forbidden, source)

if __name__ == "__main__":
    unittest.main()
