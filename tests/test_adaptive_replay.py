"""Offline deterministic replay checks, no HA, network, Recorder or BLE."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from importlib import import_module
from pathlib import Path
import sys
import types

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "easywallbox_smart"
package = types.ModuleType("_ew_replay_test_package")
package.__path__ = [str(BASE)]
sys.modules[package.__name__] = package
module = import_module("_ew_replay_test_package.adaptive_replay")
Scenario, HomePeriod = module.Scenario, module.HomePeriod
dishwasher_example, run_replay = module.dishwasher_example, module.run_replay
departure_slack_minutes = module.departure_slack_minutes


class TestAdaptiveReplay(unittest.TestCase):
    def test_dpm_only_fixed_and_adaptive_have_explicit_tradeoff(self):
        x = dishwasher_example()
        dpm = run_replay(x, 'dpm_only')
        fixed = run_replay(x, 'fixed_low')
        adaptive = run_replay(x, 'adaptive')
        self.assertEqual((dpm.alarm_episodes, fixed.alarm_episodes,
                          adaptive.alarm_episodes), (5, 0, 1))
        self.assertEqual((dpm.seconds_over_alarm, adaptive.seconds_over_alarm), (100, 20))
        self.assertEqual(adaptive.shortfall_kwh, 0.0)
        self.assertGreater(fixed.shortfall_kwh, 4)
        self.assertLess(dpm.reached_at, adaptive.reached_at)
        self.assertGreater(adaptive.cap_changes, 0)
        self.assertTrue(adaptive.no_commands_sent)

    def test_instantaneous_dpm_never_crosses_alarm(self):
        x = dishwasher_example(delay_seconds=0)
        dpm, adaptive = [run_replay(x, mode) for mode in ('dpm_only', 'adaptive')]
        self.assertEqual(dpm.alarm_episodes, 0)
        self.assertEqual(adaptive.alarm_episodes, 0)
        self.assertEqual(adaptive.cap_changes, 0)
        self.assertEqual(dpm.reached_at, adaptive.reached_at)
        self.assertLessEqual(dpm.max_modeled_total_kw, x.available_kw)

    def test_larger_dpm_delay_changes_hypothetical_alarms(self):
        x = dishwasher_example(delay_seconds=20)
        short = run_replay(x, 'adaptive')
        long = run_replay(replace(x, assumed_dpm_delay_seconds=40), 'adaptive')
        self.assertEqual(short.alarm_episodes, 1)
        self.assertEqual(long.alarm_episodes, 1)
        self.assertGreaterEqual(long.seconds_over_alarm, short.seconds_over_alarm)

    def test_urgent_planner_relaxes_optional_cap(self):
        safe = run_replay(dishwasher_example(battery_kwh=24), 'adaptive')
        urgent = run_replay(dishwasher_example(battery_kwh=27), 'adaptive')
        self.assertGreaterEqual(urgent.alarm_episodes, safe.alarm_episodes)
        self.assertEqual(urgent.shortfall_kwh, 0)
        self.assertTrue(any(action.action == 'restore' for action in urgent.first_actions))

    def test_already_no_energy_requires_no_command(self):
        x = replace(dishwasher_example(), battery_needed_kwh=0.0)
        for mode in ('dpm_only', 'fixed_low', 'adaptive'):
            r = run_replay(x, mode)
            self.assertEqual(r.alarm_episodes, 0)
            self.assertEqual(r.cap_changes, 0)
            self.assertEqual(r.shortfall_kwh, 0)
            self.assertIsNone(r.reached_at)

    def test_invalid_inputs_fail_closed(self):
        x = dishwasher_example()
        for bad in [
            replace(x, alarm_kw=3),
            replace(x, efficiency=1.1),
            replace(x, battery_needed_kwh=float('nan')),
            replace(x, departure=x.started),
            replace(x, started=x.started.replace(tzinfo=None)),
            replace(x, sample_seconds=13),
            replace(x, assumed_dpm_delay_seconds=15),
            replace(x, busy=(HomePeriod(10, 20, 2), HomePeriod(15, 35, 3))),
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    run_replay(bad, 'adaptive')

    def test_dst_slack_uses_absolute_time(self):
        rome = ZoneInfo('Europe/Rome')
        before = datetime(2026, 10, 25, 1, 30, tzinfo=rome)
        after = datetime(2026, 10, 25, 3, 30, tzinfo=rome)
        self.assertEqual(departure_slack_minutes(before, after, 0, .9, 3, 0), 180)

    def test_step_replay_does_not_write_anything(self):
        import inspect
        code = inspect.getsource(module)
        for banned in ('open(', 'write(', 'homeassistant.', 'requests.', 'async_call(', 'sqlite3', 'recorder'):
            self.assertNotIn(banned, code.lower())


if __name__ == '__main__':
    unittest.main()
