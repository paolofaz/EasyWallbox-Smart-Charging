"""Independent AI review regressions for prior iterations.

Synthetic observations only. No HA services or BLE commands are invoked.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import test_controller_smoke as rig
import test_power_policy as sample_rig


class BudgetRegressions(unittest.TestCase):
    def test_new_setup_has_only_one_session_power_default(self):
        self.assertEqual(rig.const.DEFAULT_BASE_KW,4.2)
        self.assertFalse(hasattr(rig.const,"CONF_BOOST_KW"))


    def _enter_limited(self):
        points = [{"minute": minute, "house": 2.2, "budget": 3.0}
                  for minute in range(3)]
        out = sample_rig.run_many(points)
        self.assertEqual(out[-1][1].phase, "LIMITED")
        return out[-1][1], out[-1][2].target_kw

    def test_updated_margin_must_not_subtract_sacrificed_energy_twice(self):
        state, cap = self._enter_limited()
        # The available budget already shrank as real charging time was lost.
        # Retained spent is an audit figure, not another debit from this budget.
        state = replace(state, spent_budget_kwh=0.8)
        state, decision = sample_rig.policy.evaluate(
            sample_rig.sample(3, house=0.1, current=cap,
                              margin=70, budget=0.25), state)
        self.assertEqual(state.phase, "LIMITED")
        self.assertEqual(decision.action, "none")
        self.assertNotEqual(decision.reason, "restore_opportunity_exhausted")

    def test_observed_gap_restores_only_if_cap_now_reduces_opportunity(self):
        state, cap = self._enter_limited()
        state, decision = sample_rig.policy.evaluate(
            sample_rig.sample(6, house=.1, current=cap,
                              margin=80, budget=1.0), state)
        self.assertEqual((decision.action, decision.target_kw, decision.reason),
                         ("set_limit", 4.0, "restore_after_house_report_gap"))

    def test_observed_gap_never_restores_while_dpm_already_binding(self):
        state, cap = self._enter_limited()
        state, decision = sample_rig.policy.evaluate(
            sample_rig.sample(6, house=2.2, current=cap,
                              margin=80, budget=1.0), state)
        self.assertEqual(state.phase, "LIMITED")
        self.assertEqual(decision.action, "none")
        self.assertEqual(decision.reason, "limited_dpm_bottleneck")

    def test_urgent_cyclic_load_never_starts_ble_cap(self):
        state = None
        writes = []
        for minute in range(30):
            # Typical heater/induction pattern: 3 minutes high, 7 low.
            house = 2.0 if minute % 10 < 3 else 0.1
            state, decision = sample_rig.policy.evaluate(
                sample_rig.sample(minute, house=house, margin=20,
                                  budget=0.0, current=4.0), state)
            if decision.action == "set_limit":
                writes.append((minute, decision.target_kw))
        self.assertEqual(writes, [])
        self.assertEqual(state.phase, "NORMAL")

    def test_pending_periodic_samples_never_manufacture_quiet(self):
        state, cap = self._enter_limited()
        # A gap >150s cannot be used as observed 15-minute quiet.
        # When the cap actually becomes binding, a single fresh sample
        # should restore rather than waiting forever for quiet evidence.
        state, decision = sample_rig.policy.evaluate(
            sample_rig.sample(6.1, house=.08, current=cap,
                              margin=90, budget=1.0), state)
        self.assertEqual(decision.reason, "restore_after_house_report_gap")


class MarginAndMeterRegressions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        self.hass = rig.FakeHass(self.temp.name)
        self.cfg = rig.setup(self.hass, cable=True, charging=True, soc="60")
        self.controller = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        await self.controller.async_load()
        self.t0 = datetime.now(timezone.utc)
        self.controller._active_departure = self.t0 + timedelta(hours=5)
        self.controller._active_departure_vehicle = "binary_sensor.fiat"

    async def asyncTearDown(self):
        await self.controller.async_close()
        self.temp.cleanup()

    def _advance(self, minutes):
        at = self.t0 + timedelta(minutes=minutes)
        for entity in ("sensor.floor_a", "sensor.floor_b",
                       "sensor.ev", "sensor.wallbox_charge_state"):
            state = self.hass.states[entity]
            state.last_reported = at
            state.last_updated = at
        return at

    def test_combined_house_timestamp_is_oldest_branch_not_newest(self):
        t = self.t0
        self.hass.states["sensor.floor_a"].last_reported = t
        self.hass.states["sensor.floor_b"].last_reported = t - timedelta(seconds=90)
        house, reported_at = self.controller._house(t)
        self.assertAlmostEqual(house, .2)
        self.assertEqual(reported_at, t - timedelta(seconds=90))
        self.hass.states["sensor.floor_b"].last_reported = (
            t - timedelta(seconds=151))
        self.assertEqual(self.controller._house(t), (None, None))

    def test_unplug_timer_reset_reason_logged_once_without_ble_write(self):
        self.controller._soc_stop_done = True
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        now = datetime.now(timezone.utc)
        with patch.object(self.controller, "_record") as journal:
            self.assertIsNone(self.controller._wallbox_cable(now))
            self.assertIsNotNone(self.controller._unplug_since)
            self.hass.states["binary_sensor.ble_connection"].publish("off")
            self.assertIsNone(self.controller._wallbox_cable(now + timedelta(seconds=4)))
            self.assertIsNone(self.controller._unplug_since)
            self.controller._wallbox_cable(now + timedelta(seconds=5))
            self.assertEqual(journal.call_count, 1)
            self.assertEqual(journal.call_args.args[:2],
                             ("unplug_evidence_reset", "ble_disconnected"))
        self.assertEqual(self.hass.services.calls, [])

    def test_margin_uses_observed_ac_during_cloud_soc_plateau(self):
        # EV consumes a constant 3.2 kW. Old SOC remains 60% for 8 min.
        # With a 3.2kW prudent rate the true slack should stay almost flat.
        with patch.object(rig.controller, "estimate_ac_kw", return_value=3.2):
            self.controller._snapshot(self._advance(0))
            initial = self.controller.margin_minutes
            self.assertIsNotNone(initial)
            for minute in (2, 4, 6, 8):
                self.controller._snapshot(self._advance(minute))
            self.assertIsNotNone(self.controller.margin_minutes)
            self.assertLess(abs(self.controller.margin_minutes-initial), 1.1)
            self.assertGreater(self.controller._delivered_ev_kwh, .39)
            self.assertAlmostEqual(self.controller._margin_energy_kwh,
                                   self.controller._eta_remaining_ac_kwh, places=5)

            # Lost Shelly interval: no fake delivery is credited.
            # A conservative (lower-bound) departure margin survives.
            self.controller._snapshot(self._advance(12))  # 4-minute gap
            self.assertIsNotNone(self.controller.margin_minutes)
            self.assertIsNotNone(self.controller._margin_energy_kwh)
            self.assertIsNotNone(self.controller._eta_remaining_ac_kwh)
            self.assertEqual(self.controller._forecast_quality,"provvisoria")
            self.assertEqual(self.controller._margin_quality,"observed_partial_gap")
            self.assertTrue(self.controller._delivery_gap)

            # A genuinely new SOC report reanchors the AC integrator.
            self.hass.states["sensor.fiat_soc"].publish("61")
            soc_state = self.hass.states["sensor.fiat_soc"]
            soc_state.last_reported = self.t0 + timedelta(minutes=14)
            soc_state.last_updated = soc_state.last_reported
            self.controller._snapshot(self._advance(14))
            self.assertFalse(self.controller._delivery_gap)
            self.assertIsNotNone(self.controller.margin_minutes)
