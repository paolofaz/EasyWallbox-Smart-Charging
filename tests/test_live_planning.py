"""Offline planning tests: no HA installation, no cars or charging needed."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "easywallbox_smart"
PKG = "_ew_live_planning_test"
package = types.ModuleType(PKG)
package.__path__ = [str(BASE)]
sys.modules[PKG] = package
for name in ("planner", "power_model", "schedule", "live_planning"):
    spec = importlib.util.spec_from_file_location(PKG + "." + name, BASE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

evaluate = sys.modules[PKG + ".live_planning"].evaluate
next_departure = sys.modules[PKG + ".schedule"].next_departure
ROMA = ZoneInfo("Europe/Rome")
NOW = datetime(2026, 11, 13, 18, tzinfo=ROMA)


class FakeState:
    def __init__(self, value, watts, when=NOW):
        self.state = str(value)
        self.attributes = {"unit_of_measurement": watts}
        self.last_reported = when.astimezone(timezone.utc)
        self.last_updated = self.last_reported


class FakeHA:
    def __init__(self, states):
        self.config = types.SimpleNamespace(time_zone="Europe/Rome")
        self.states = types.SimpleNamespace(get=lambda entity: states.get(entity))


def settings():
    return {
        "continuous_kw": 4.4,
        "departure_weekday": "07:00",
        "departure_weekend": "08:00",
        "energy_mode": "house_sensors",
        "house_power_sources": ["sensor.h1", "sensor.h2"],
    }


def active(kwh=39):
    return types.SimpleNamespace(quality="ok", remaining_kwh=kwh)


class TestLivePlanning(unittest.TestCase):
    def test_next_departure_friday_evening_is_saturday(self):
        result = next_departure(NOW, "07:00", "08:00")
        self.assertEqual(result.date().isoformat(), "2026-11-14")
        self.assertEqual(result.hour, 8)

    def test_timeline_planning_from_fresh_shelly(self):
        ha = FakeHA({"sensor.h1": FakeState(500, "W"),
                     "sensor.h2": FakeState(100, "W")})
        result = evaluate(ha, settings(), active(), NOW.astimezone(timezone.utc))
        self.assertEqual(result.status, "current_load_scenario_feasible")
        self.assertAlmostEqual(result.house_kw, .6)
        self.assertAlmostEqual(result.result.estimated_ev_kw, 3.8)
        self.assertEqual(result.result.recommended_start, NOW)

    def test_missing_source_disables_estimate(self):
        ha = FakeHA({"sensor.h1": FakeState(500, "W")})
        result = evaluate(ha, settings(), active(), NOW.astimezone(timezone.utc))
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.result)
        self.assertIsNone(result.house_kw)

    def test_obsolete_source_disables_estimate(self):
        old = NOW - timedelta(minutes=20)
        ha = FakeHA({"sensor.h1": FakeState(500, "W", old),
                     "sensor.h2": FakeState(100, "W")})
        result = evaluate(ha, settings(), active(), NOW.astimezone(timezone.utc))
        self.assertEqual(result.status, "unavailable")

    def test_existing_entries_need_opt_in_to_planning(self):
        ha = FakeHA({})
        result = evaluate(ha, {}, active(), NOW.astimezone(timezone.utc))
        self.assertEqual(result.status, "unconfigured")

    def test_no_car_does_not_create_fake_vehicle_forecast(self):
        ha = FakeHA({"sensor.h1": FakeState(500, "W"),
                     "sensor.h2": FakeState(100, "W")})
        result = evaluate(
            ha, settings(), types.SimpleNamespace(
                quality="no_vehicle_at_wallbox", remaining_kwh=None
            ), NOW.astimezone(timezone.utc)
        )
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.result)

    def test_house_power_and_departure_survive_missing_wallbox_telemetry(self):
        ha = FakeHA({"sensor.h1": FakeState(500, "W"),
                     "sensor.h2": FakeState(100, "W")})
        unavailable = types.SimpleNamespace(
            quality="wallbox_telemetry_unavailable", remaining_kwh=None
        )
        result = evaluate(
            ha, settings(), unavailable, NOW.astimezone(timezone.utc)
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason, "vehicle_wallbox_telemetry_unavailable")
        self.assertAlmostEqual(result.house_kw, .6)
        self.assertEqual(result.departure.hour, 8)
        self.assertIsNone(result.result)

    def test_house_power_available_without_planning_options(self):
        ha = FakeHA({"sensor.h1": FakeState(500, "W"),
                     "sensor.h2": FakeState(100, "W")})
        config = settings()
        del config["continuous_kw"]
        result = evaluate(ha, config, active(), NOW.astimezone(timezone.utc))
        self.assertEqual(result.status, "unconfigured")
        self.assertEqual(result.house_kw, .6)
        self.assertIsNone(result.departure)

    def test_required_average_survives_missing_house_meter(self):
        ha = FakeHA({"sensor.h1": FakeState(500, "W")})
        result = evaluate(ha, settings(), active(31.98), NOW.astimezone(timezone.utc))
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.result)
        self.assertIsNotNone(result.demand)
        self.assertIsNotNone(result.demand.required_grid_kw)

    def test_busy_kitchen_is_only_a_current_load_scenario(self):
        time = datetime(2026, 11, 13, 19, 44, tzinfo=ROMA)
        ha = FakeHA({
            "sensor.h1": FakeState(1900, "W", time),
            "sensor.h2": FakeState(170, "W", time),
        })
        preview = evaluate(
            ha, settings(), active(31.98), time.astimezone(timezone.utc)
        )
        self.assertEqual(preview.status, "current_load_scenario_at_risk")
        self.assertAlmostEqual(preview.house_kw, 2.07)
        self.assertAlmostEqual(preview.demand.required_grid_kw, 3.086, places=2)
        self.assertEqual(preview.result.status, "deadline_at_risk")

    def test_impossible_even_with_zero_house_is_separate_status(self):
        ha = FakeHA({
            "sensor.h1": FakeState(500, "W"),
            "sensor.h2": FakeState(100, "W"),
        })
        changed = settings()
        changed["continuous_kw"] = 1.5
        preview = evaluate(
            ha, changed, active(31.98), NOW.astimezone(timezone.utc)
        )
        self.assertEqual(
            preview.status, "deadline_unreachable_even_without_house_load"
        )
        self.assertIsNone(preview.result)
        self.assertIsNotNone(preview.demand.required_grid_kw)

    def test_bad_time_is_rejected(self):
        with self.assertRaises(ValueError):
            next_departure(NOW, "25:00", "08:00")


if __name__ == "__main__":
    unittest.main()
