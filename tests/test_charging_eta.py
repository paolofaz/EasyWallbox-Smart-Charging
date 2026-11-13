"""Pure and HA-shaped tests for ETA based on actual grid charging power."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

FILE = Path(__file__).resolve().parents[1] / (
    "custom_components/easywallbox_smart/charging_eta.py"
)
spec = importlib.util.spec_from_file_location("_ew_charge_eta_tests", FILE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

estimate = module.estimate
evaluate = module.evaluate
NOW = datetime(2026, 11, 13, 21, 13, tzinfo=timezone.utc)


class FakeState:
    def __init__(self, value, unit="kW", timestamp=NOW):
        self.state = str(value)
        self.attributes = {"unit_of_measurement": unit}
        self.last_reported = timestamp
        self.last_updated = timestamp


class FakeHA:
    def __init__(self, states):
        self.states = SimpleNamespace(get=lambda name: states.get(name))


def car(energy=23.01, quality="ok"):
    return SimpleNamespace(remaining_kwh=energy, quality=quality)


class TestChargingEta(unittest.TestCase):
    def test_kia_etat_uses_actual_ev_grid_kw_not_house_headroom(self):
        result = estimate(NOW, 23.01, 3.0)
        self.assertEqual(result.status, "ok")
        self.assertAlmostEqual(result.hours_remaining, 8.52, places=2)
        self.assertLess(abs(
            (result.finish - NOW).total_seconds() / 3600 - 8.5222
        ), .01)

    def test_house_consumption_irrelevant(self):
        states = {
            "sensor.ev": FakeState(2995, "W"),
            "sensor.house": FakeState(200, "W"),
        }
        config = {"ev_power_sensor": "sensor.ev"}
        quiet = evaluate(FakeHA(states), config, car(), NOW)
        states["sensor.house"] = FakeState(2100, "W")
        busy = evaluate(FakeHA(states), config, car(), NOW)
        self.assertEqual(quiet.finish, busy.finish)
        self.assertEqual(quiet.ev_grid_kw, 2.995)

    def test_zero_or_paused_charging_never_gives_fake_eta(self):
        for power in (0, 0.1, 0.15):
            with self.subTest(power=power):
                result = estimate(NOW, 23.01, power)
                self.assertEqual(result.status, "not_charging")
                self.assertIsNone(result.finish)

    def test_missing_sensor_is_explained(self):
        result = evaluate(FakeHA({}), {}, car(), NOW)
        self.assertEqual(result.status, "charging_power_source_not_configured")
        self.assertIsNone(result.finish)

    def test_unknown_or_obsolete_power_is_not_zero(self):
        config = {"ev_power_sensor": "sensor.ev"}
        for state in (
            FakeState("unavailable"),
            FakeState("unknown"),
            FakeState(3000, "W", NOW-timedelta(minutes=15)),
            FakeState("bad"),
            FakeState(3, "not-a-unit"),
        ):
            with self.subTest(state=state.state):
                result = evaluate(FakeHA({"sensor.ev": state}), config, car(), NOW)
                self.assertIsNone(result.finish)

    def test_target_reached_and_no_vehicle(self):
        completed = evaluate(
            FakeHA({"sensor.ev": FakeState(0)}),
            {"ev_power_sensor": "sensor.ev"}, car(0), NOW
        )
        self.assertEqual(completed.status, "target_reached")
        self.assertEqual(completed.hours_remaining, 0)
        missing = evaluate(
            FakeHA({"sensor.ev": FakeState(3)}),
            {"ev_power_sensor": "sensor.ev"}, car(None, "no_vehicle_at_wallbox"), NOW
        )
        self.assertTrue(missing.status.startswith("vehicle_"))
        self.assertIsNone(missing.finish)

    def test_finite_safe_inputs(self):
        for missing in (-1, None, float("nan"), float("inf")):
            with self.subTest(energy=missing):
                self.assertIsNone(estimate(NOW, missing, 3).finish)
        self.assertEqual(estimate(NOW, 2, float("nan")).status,
                         "charging_power_unavailable")

    def test_no_departure_time_needed_to_estimate_completion(self):
        result = evaluate(
            FakeHA({"sensor.ev": FakeState(3)}),
            {"ev_power_sensor": "sensor.ev"}, car(), NOW
        )
        self.assertIsNotNone(result.finish)


if __name__ == "__main__":
    unittest.main()
