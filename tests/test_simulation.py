"""Offline load recommendation tests: strictly hypothetical, no HA commands."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import importlib.util
import sys
import unittest

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "easywallbox_smart"
PKG = "_ew_simulator_tests"
package = ModuleType(PKG)
package.__path__ = [str(BASE)]
sys.modules[PKG] = package
for name in ("load_scenario", "simulation"):
    spec = importlib.util.spec_from_file_location(PKG + "." + name, BASE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
calc = sys.modules[PKG + ".load_scenario"]
impl = sys.modules[PKG + ".simulation"]
NOW = datetime(2026, 11, 13, 21, 13, tzinfo=timezone.utc)


@dataclass
class State:
    state: str
    attributes: dict
    last_reported: datetime = NOW
    last_updated: datetime = NOW


class HA:
    def __init__(self, state_dict):
        self.states = SimpleNamespace(get=lambda name: state_dict.get(name))


def settings():
    return {
        "continuous_kw": 4.4,
        "ev_requested_limit": "number.ev",
        "ev_confirmed_limit": "sensor.confirmed",
        "ev_power_sensor": "sensor.actual",
        "load_active_entity": "binary_sensor.load",
        "load_peak_kw": 2.1,
        "load_duration_minutes": 100,
    }


def source(requested="3.0", confirmed="3.0", active="on"):
    return {
        "number.ev": State(requested, {"unit_of_measurement": "kW"}),
        "sensor.confirmed": State(confirmed, {"unit_of_measurement": "kW"}),
        "sensor.actual": State("2.9", {"unit_of_measurement": "kW"}),
        "binary_sensor.load": State(active, {}),
    }


def preview(battery=27.69, hours=10.5, house=.2):
    return SimpleNamespace(
        house_kw=house,
        departure=NOW+timedelta(hours=hours),
        demand=SimpleNamespace(
            status="ok",
            usable_hours=hours,
            required_grid_kw=round(battery / (.90*hours), 3),
        ),
    )


class TestLoadScenario(unittest.TestCase):
    def test_kia_urgent_does_not_reduce_for_dishwasher(self):
        d = impl.evaluate(HA(source()), settings(), preview(), NOW)
        self.assertEqual(d.code, "priority_departure_keep_limit")
        self.assertIsNone(d.suggested_kw)
        self.assertEqual(d.confirmed_kw, 3.0)
        self.assertEqual(d.actual_kw, 2.9)
        self.assertGreater(d.lost_grid_kwh, d.energy_margin_kwh)

    def test_fiat_slack_permits_temporary_reduction(self):
        d = impl.evaluate(HA(source(requested="3.2", confirmed="3.2")),
                          settings(), preview(battery=6.0), NOW)
        self.assertEqual(d.code, "temporary_reduction_possible")
        self.assertEqual(d.suggested_kw, 2.0)
        self.assertGreater(d.energy_margin_kwh, d.lost_grid_kwh)

    def test_request_confirm_mismatch_does_not_hide_uncertainty(self):
        d = impl.evaluate(HA(source(requested="4.0", confirmed="3.2")),
                          settings(), preview(battery=6), NOW)
        self.assertEqual(d.code, "requested_confirmed_mismatch")
        self.assertIsNone(d.suggested_kw)

    def test_missing_confirmed_setpoint_blocks_action(self):
        states = source()
        states.pop("sensor.confirmed")
        d = impl.evaluate(HA(states), settings(), preview(battery=6), NOW)
        self.assertEqual(d.code, "confirmed_limit_required")
        self.assertIsNone(d.suggested_kw)

    def test_unknown_load_is_not_off(self):
        d = impl.evaluate(HA(source(active="unavailable")),
                          settings(), preview(battery=6), NOW)
        self.assertEqual(d.code, "load_unknown")
        self.assertEqual(d.load_state, "unavailable")
        self.assertIsNone(d.suggested_kw)

    def test_off_is_not_a_new_reduce_command(self):
        d = impl.evaluate(HA(source(active="off")),
                          settings(), preview(battery=6), NOW)
        self.assertEqual(d.code, "load_inactive")
        self.assertIsNone(d.suggested_kw)

    def test_very_large_peak_leaves_dpm_responsible(self):
        settings_kw = settings()
        settings_kw["load_peak_kw"] = 4.0
        d = impl.evaluate(HA(source()), settings_kw, preview(battery=6), NOW)
        self.assertEqual(d.code, "dpm_handles_peak")
        self.assertIsNone(d.suggested_kw)

    def test_session_shows_only_hypothetical_restoration(self):
        sim = impl.SimulationSession()
        on = impl.evaluate(HA(source(requested="3.2", confirmed="3.2")),
                           settings(), preview(battery=6), NOW)
        self.assertEqual(sim.update(on).code, "temporary_reduction_possible")
        off = impl.evaluate(HA(source(requested="3.2", confirmed="3.2", active="off")),
                            settings(), preview(battery=6), NOW)
        decision = sim.update(off)
        self.assertEqual(decision.code, "hypothetical_restoration_after_load")
        self.assertEqual(decision.suggested_kw, 3.2)
        self.assertEqual(decision.note, "simulation_only_no_commands")

    def test_manual_power_change_cancels_hypothetical_restoration(self):
        sim = impl.SimulationSession()
        on = impl.evaluate(HA(source(requested="3.2", confirmed="3.2")),
                           settings(), preview(battery=6), NOW)
        sim.update(on)
        changed = impl.evaluate(HA(source(requested="3.0", confirmed="3.0")),
                                settings(), preview(battery=6), NOW)
        self.assertEqual(sim.update(changed).code, "manual_override_respected")
        off = impl.evaluate(HA(source(requested="3.0", confirmed="3.0", active="off")),
                            settings(), preview(battery=6), NOW)
        self.assertEqual(sim.update(off).code, "load_inactive")

    def test_restart_or_unplug_forgets_hypothetical_restore(self):
        sim = impl.SimulationSession()
        on = impl.evaluate(
            HA(source(requested="3.2", confirmed="3.2")),
            settings(), preview(battery=6), NOW
        )
        self.assertEqual(sim.update(on).code, "temporary_reduction_possible")
        sim.reset()  # no state survived an HA restart or vehicle disconnect
        off = impl.evaluate(
            HA(source(requested="3.2", confirmed="3.2", active="off")),
            settings(), preview(battery=6), NOW
        )
        self.assertEqual(sim.update(off).code, "load_inactive")

    def test_old_actual_power_not_represented_as_current(self):
        states = source()
        states["sensor.actual"] = State(
            "2.0", {"unit_of_measurement": "kW"},
            NOW-timedelta(minutes=20), NOW-timedelta(minutes=20)
        )
        d = impl.evaluate(HA(states), settings(), preview(battery=6), NOW)
        self.assertIsNone(d.actual_kw)


if __name__ == "__main__":
    unittest.main()
