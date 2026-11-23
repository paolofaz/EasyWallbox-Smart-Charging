"""Field-trial gates, independent physical confirmations and local audit trail."""
import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import test_controller_smoke as rig

C = rig.const
now = lambda: datetime.now(timezone.utc)


class FieldTrial(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.hass = rig.FakeHass(self.tmp.name)
        self.cfg = rig.setup(self.hass)
        self.controller = rig.controller.ChargingController(self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        await self.controller.async_load()

    async def asyncTearDown(self):
        await self.controller.async_close()
        self.tmp.cleanup()

    def publish(self, key, value):
        self.hass.states[self.cfg[key]].publish(value)

    async def settle(self):
        await asyncio.sleep(.01)

    async def start_charging(self):
        self.controller.start()
        # These dispatcher tests presume the one-shot vehicle cloud
        # refresh has already been handled for this synthetic session.
        self.controller._refresh_due = None
        self.controller._refresh_issued = True
        self.controller._connect_since = now() - timedelta(minutes=1)
        await self.settle()

    async def trigger_power(self):
        self.publish(C.CONF_REQUESTED_LIMIT, 3.6)
        self.publish(C.CONF_CONFIRMED_LIMIT, 3.6)
        await self.start_charging()
        self.assertEqual(self.controller._pending.kind, "power")

    async def rows(self):
        await self.controller._journal.async_flush()
        return [json.loads(line) for file in sorted(Path(self.tmp.name).rglob("*.jsonl"))
                for line in file.read_text().splitlines()]

    async def test_cable_alone_does_not_refresh_cloud_vehicle(self):
        self.publish(C.CONF_WALLBOX_CHARGING, "off")
        self.publish(C.CONF_EV_POWER, 0.0)
        self.controller.start()
        await self.settle()
        self.assertTrue(self.controller._trace_session)
        self.assertIsNone(self.controller._refresh_due)
        await self.controller._request_one_shot_updates()
        self.assertEqual(self.hass.services.calls, [])

    async def test_verified_charge_start_requests_once_after_debounce(self):
        self.publish(C.CONF_WALLBOX_CHARGING, "off")
        self.publish(C.CONF_EV_POWER, 0.0)
        self.controller.start()
        self.assertIsNone(self.controller._refresh_due)
        # The cloud Fiat cable marker may still be stale after charging began.
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.publish(C.CONF_WALLBOX_CHARGING, "on")
        self.publish(C.CONF_EV_POWER, 2.1)
        self.controller.refresh()
        self.assertIsNotNone(self.controller._refresh_due)
        await self.controller._request_one_shot_updates()
        self.assertEqual(self.hass.services.calls, [])  # debounce
        self.controller._refresh_due = now() - timedelta(seconds=1)
        await self.controller._request_one_shot_updates()
        calls = self.hass.services.calls
        self.assertTrue(calls)
        self.assertTrue(all(c[0:2] == ("button","press") for c in calls))
        self.assertTrue(self.controller._refresh_issued)
        await self.controller._request_one_shot_updates()
        self.assertEqual(self.hass.services.calls, calls)
        self.publish(C.CONF_WALLBOX_CHARGING, "off")
        self.publish(C.CONF_EV_POWER, 0.0)
        self.controller.refresh()
        self.publish(C.CONF_WALLBOX_CHARGING, "on")
        self.publish(C.CONF_EV_POWER, 2.1)
        self.controller.refresh()
        self.assertTrue(self.controller._refresh_issued)
        self.assertEqual(self.hass.services.calls, calls)

    async def test_refresh_aborted_when_charging_stops_before_debounce(self):
        self.publish(C.CONF_WALLBOX_CHARGING, "off")
        self.publish(C.CONF_EV_POWER, 0.0)
        self.controller.start()
        self.publish(C.CONF_WALLBOX_CHARGING, "on")
        self.publish(C.CONF_EV_POWER, 2.1)
        self.controller.refresh()
        self.controller._refresh_due = now() - timedelta(seconds=1)
        self.publish(C.CONF_WALLBOX_CHARGING, "off")
        self.publish(C.CONF_EV_POWER, 0.0)
        await self.controller._request_one_shot_updates()
        self.assertEqual(self.hass.services.calls, [])
        self.assertFalse(self.controller._refresh_issued)

    async def test_capped_ev_history_cannot_poison_dpm_only_forecast(self):
        self.publish(C.CONF_REQUESTED_LIMIT, 2.0)
        self.publish(C.CONF_CONFIRMED_LIMIT, 2.0)
        self.controller.start()
        base = now()
        for i in range(7):
            self.controller._house_history.append(
                (base - timedelta(minutes=6-i), .2))
        for i in range(21):
            self.controller._ev_history.append(
                (base - timedelta(minutes=20-i), 1.93))
        self.controller._snapshot(now())
        # With the 2 kW cap in force, a 20-minute series of 1.93 kW
        # actual delivery must not make the hypothetical 4 kW limit
        # appear limited to 1.93 kW in the departure forecast.
        self.assertGreater(self.controller.planning_rate_kw, 3.5)

    async def test_manual_persists_across_reboot_and_auto_never_starts_car(self):
        self.controller.start()
        await self.controller.async_change("mode", "manual")
        saved = dict(self.controller._store.content)
        self.assertEqual(saved["mode"], "manual")
        other = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        async def restore():
            return saved
        other._store.async_load = restore
        await other.async_load()
        self.assertEqual(other.mode, "manual")
        other.start()
        await self.settle()
        self.assertFalse(any(call[0] in ("switch", "number")
                             for call in self.hass.services.calls))
        await other.async_change("mode", "automatic")
        await self.settle()
        self.assertFalse(any(call[0] == "switch"
                             for call in self.hass.services.calls))
        await other.async_close()

    async def test_offline_and_idle_only_observe_wakeup_entities(self):
        self.publish(C.CONF_BLE_CONNECTED, "off")
        with patch.object(self.controller, "_snapshot", side_effect=AssertionError("idle snapshot")):
            self.controller.start()
            for _ in range(10):
                self.controller.refresh()
            self.assertIsNone(self.controller._cable_unsub)
            self.publish(C.CONF_BLE_CONNECTED, "on")
            self.publish(C.CONF_WALLBOX_CONNECTED, "off")
            self.controller.refresh()
            self.assertIsNotNone(self.controller._cable_unsub)
            self.assertIsNone(self.controller._connected_unsub)
            self.assertIsNone(self.controller._timer_unsub)
        self.assertEqual(await self.rows(), [])
        self.assertEqual(self.hass.services.calls, [])

    async def test_legacy_entities_can_be_entirely_absent(self):
        for key in (C.CONF_TELEMETRY_FRESH, C.CONF_CHARGE_ENABLED, C.CONF_DPM_ACTIVE,
                    C.CONF_COMMAND_STATUS, C.CONF_WALLBOX_REFRESH):
            self.hass.states.pop(self.controller.cfg.pop(key))
        await self.trigger_power()
        self.assertEqual(len(self.hass.services.calls), 1)

    async def test_slider_or_status_alone_never_ack_reconstructable_timeout(self):
        await self.trigger_power()
        self.publish(C.CONF_REQUESTED_LIMIT, 4.0)
        self.publish(C.CONF_COMMAND_STATUS, "Verified charge power")
        self.controller.refresh()
        self.assertIsNotNone(self.controller._pending)
        self.controller._pending.since -= rig.controller.ACK_TIMEOUT
        self.controller.refresh()
        self.controller.refresh()
        await self.settle()
        rows = await self.rows()
        events = [(row["event"], row.get("operation")) for row in rows
                  if row["event"] in ("intent", "dispatched", "unconfirmed", "confirmed")]
        self.assertEqual([event for event, _ in events], ["intent", "dispatched", "unconfirmed"])
        self.assertEqual(len({operation for _, operation in events}), 1)
        self.assertEqual(len(self.hass.services.calls), 1)
        self.assertIn("no_retry", rows[[r["event"] for r in rows].index("unconfirmed")]["reason"])

    async def test_stale_readback_matching_late_value_cannot_ack(self):
        await self.trigger_power()
        p = self.controller._pending
        self.publish(C.CONF_REQUESTED_LIMIT, 4)
        self.publish(C.CONF_CONFIRMED_LIMIT, 4)
        confirmed = self.hass.states[self.cfg[C.CONF_CONFIRMED_LIMIT]]
        confirmed.last_reported = p.since - timedelta(milliseconds=1)
        self.controller.refresh()
        self.assertIs(self.controller._pending, p)
        self.publish(C.CONF_CONFIRMED_LIMIT, 4)
        self.controller.refresh()
        self.assertIsNone(self.controller._pending)
        rows = await self.rows()
        ack = next(row for row in rows if row["event"] == "confirmed")
        self.assertEqual(ack["operation"], p.operation)
        self.assertEqual(ack["confirmed_kw"], 4)
        self.assertTrue(ack["charging_flag"])
        self.assertEqual(len(self.hass.services.calls), 1)

    async def test_stale_meter_unknown_charge_state_or_contradictory_charging_vetoes(self):
        self.publish(C.CONF_CONFIRMED_LIMIT, 3.6)
        self.publish(C.CONF_REQUESTED_LIMIT, 3.6)
        self.publish(C.CONF_CHARGE_STATE, "unknown")
        await self.start_charging()
        self.publish(C.CONF_CHARGE_STATE, "Charging")
        self.publish(C.CONF_EV_POWER, 0)
        self.controller.refresh()
        await self.settle()
        self.publish(C.CONF_EV_POWER, 3.3)
        self.hass.states[self.cfg[C.CONF_EV_POWER]].last_reported -= timedelta(minutes=5)
        self.controller.refresh()
        await self.settle()
        self.assertEqual(self.hass.services.calls, [])
        self.assertIsNone(self.controller.charging_verified)
        rows = await self.rows()
        self.assertTrue(any("charge_state_unverified" in row.get("facts", {}).get("issues", [])
                            for row in rows))

    async def test_cable_lost_while_persisting_prevents_dispatch(self):
        # Open the session first: otherwise the separate deadline persistence
        # could trigger the injected outage before the electrical intent.
        await self.start_charging()
        # Simulate first ownership acquisition from the 3.6 kW register;
        # otherwise the earlier fixture session owns 4.0 and rightly vetoes
        # the external change before reaching the persistence race.
        self.controller._owned_limit = None
        save = self.controller._save
        async def interrupted():
            await save()
            self.publish(C.CONF_WALLBOX_CONNECTED, "off")
        self.controller._save = interrupted
        self.publish(C.CONF_REQUESTED_LIMIT, 3.6)
        self.publish(C.CONF_CONFIRMED_LIMIT, 3.6)
        self.controller.refresh()
        await self.settle()
        self.assertEqual(self.hass.services.calls, [])
        self.assertTrue(any(row["event"] == "cancelled" for row in await self.rows()))

    async def test_unconfirmed_intent_survives_reload_without_retry(self):
        await self.trigger_power()
        saved = dict(self.controller._store.content)
        self.assertIn("operation", saved["unresolved_command"])
        other = rig.controller.ChargingController(self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        async def load():
            return saved
        other._store.async_load = load
        await other.async_load()
        other.start()
        await self.settle()
        self.assertEqual(other._blocked, "previous_command_unconfirmed_no_retry")
        self.assertFalse(other.real_enabled)
        self.assertEqual(len(self.hass.services.calls), 1)
        await other.async_close()

    async def test_full_preplug_delay_and_release_one_write_each(self):
        c=self.controller
        c.start()
        self.publish(C.CONF_WALLBOX_CONNECTED,"off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.publish(C.CONF_WALLBOX_CHARGING,"off")
        self.publish(C.CONF_EV_POWER,0)
        c.refresh()
        from zoneinfo import ZoneInfo
        local=now().astimezone(ZoneInfo(self.hass.config.time_zone))
        clock=(local+timedelta(hours=1)).time().replace(second=0,microsecond=0)
        await c.async_change("time",clock)
        await c.async_change("delay",True)
        self.assertEqual(c._pending.kind,"delay_arm")
        self.publish(C.CONF_DPM_CONFIRMED,0)
        self.publish(C.CONF_START_STOP,"off")
        c.refresh()
        self.assertIsNone(c._pending)
        self.assertEqual(c._dpm_lease,4.4)
        self.assertTrue(c.delay_enabled)
        # Plugging in the car must not cancel a confirmed delayed start.
        self.publish(C.CONF_WALLBOX_CONNECTED,"on")
        c.refresh()
        self.assertTrue(c.delay_enabled)
        c._scheduled_at=now()-timedelta(seconds=1)
        c._saved_delay_lease["start"]=c._scheduled_at.isoformat()
        c.refresh()
        await self.settle()
        self.assertEqual(c._pending.kind,"delay_release")
        self.publish(C.CONF_DPM_CONFIRMED,4.4)
        self.publish(C.CONF_START_STOP,"on")
        c.refresh()
        await self.settle()
        self.assertIsNone(c._pending)
        self.assertFalse(c.delay_enabled)
        self.assertEqual([x[:2] for x in self.hass.services.calls],
                         [("switch","turn_off"),("switch","turn_on")])
        rows=await self.rows()
        self.assertEqual([r["confirmed_kw"] for r in rows if r["event"]=="confirmed"],[0,4.4])
    async def test_stable_charge_state_uses_firmware_watchdog_not_two_minute_ttl(self):
        await self.start_charging()
        charge = self.hass.states[self.cfg[C.CONF_CHARGE_STATE]]
        self.controller._ble_since = now() - timedelta(minutes=35)
        charge.last_reported = now() - timedelta(minutes=20)
        self.assertEqual(self.controller._charge_state(now()), "Charging")
        self.publish(C.CONF_TELEMETRY_FRESH, "off")
        self.assertIsNone(self.controller._charge_state(now()))
        self.publish(C.CONF_TELEMETRY_FRESH, "on")
        self.controller._ble_since = now() - timedelta(minutes=1)
        self.assertIsNone(self.controller._charge_state(now()))
        self.publish(C.CONF_CHARGE_STATE, "Charging")
        self.assertEqual(self.controller._charge_state(now()), "Charging")
        self.publish(C.CONF_CHARGE_STATE, "unavailable")
        self.assertIsNone(self.controller._charge_state(now()))

    async def test_requested_number_older_than_ble_must_match_new_eeprom(self):
        await self.start_charging()
        self.controller._ble_since = now() - timedelta(minutes=2)
        number = self.hass.states[self.cfg[C.CONF_REQUESTED_LIMIT]]
        number.last_reported = now() - timedelta(minutes=10)
        self.publish(C.CONF_CONFIRMED_LIMIT, 4.0)
        self.assertEqual(self.controller._setting(C.CONF_REQUESTED_LIMIT, now()), 4.0)
        self.publish(C.CONF_CONFIRMED_LIMIT, 3.6)
        self.assertIsNone(self.controller._setting(C.CONF_REQUESTED_LIMIT, now()))
        self.publish(C.CONF_REQUESTED_LIMIT, "unavailable")
        self.assertIsNone(self.controller._setting(C.CONF_REQUESTED_LIMIT, now()))
        self.publish(C.CONF_REQUESTED_LIMIT, 3.6)
        self.assertEqual(self.controller._setting(C.CONF_REQUESTED_LIMIT, now()), 3.6)

    async def test_failed_cloud_button_does_not_latch_after_verified_kia_update(self):
        await self.start_charging()
        car = self.cfg[C.CONF_VEHICLES][1]
        self.controller._connect_since = now() - timedelta(minutes=3)
        self.controller._refresh_requested_at = now() - timedelta(minutes=2)
        self.controller._refresh_due = None
        self.controller._refresh_issued = True
        self.controller._refresh_error = "vehicle_refresh_command_failed"
        self.hass.states[car[C.CONF_SOC]].last_reported = now() - timedelta(minutes=3)
        self.assertFalse(self.controller._car_update_ready(now(), car))
        self.hass.states[car[C.CONF_SOC]].publish("44")
        self.assertTrue(self.controller._car_update_ready(now(), car))
        self.assertIsNone(self.controller._refresh_error)

    async def test_five_minute_diagnostic_heartbeat_without_new_ble_calls(self):
        await self.start_charging()
        rows = await self.rows()
        count = sum(row["event"] == "diagnostic" for row in rows)
        self.assertEqual(count, 1)
        calls = len(self.hass.services.calls)
        self.controller.refresh()
        self.assertEqual(sum(x["event"] == "diagnostic" for x in await self.rows()), 1)
        self.controller._last_diagnostic_at = now() - timedelta(minutes=6)
        self.controller.refresh()
        rows = await self.rows()
        diagnostic = [x for x in rows if x["event"] == "diagnostic"]
        self.assertEqual(len(diagnostic), 2)
        self.assertIn("source_issues", diagnostic[-1])
        self.assertEqual(len(self.hass.services.calls), calls)

    async def test_600w_moderate_for_10_of_12_can_request_limited(self):
        from easywallbox_test_package.power_policy import Observation, evaluate
        start = now() - timedelta(minutes=12)
        state = None
        decisions = []
        for minute in range(12):
            stamp = start + timedelta(minutes=minute)
            state, decision = evaluate(Observation(
                at=stamp, session_id="kia_600w", connected=True,
                charging=True, auto=True, trusted=True,
                house_kw=0.6, house_at=stamp, dpm_kw=4.4,
                current_kw=4.0, margin_minutes=180,
                remaining_budget_kwh=2.0, max_kw=4.0), state)
            decisions.append(decision)
        self.assertEqual([(d.action, d.target_kw) for d in decisions
                          if d.action == "set_limit"], [("set_limit", 3.6)])

    async def test_passive_registers_stay_valid_on_continuous_ble_only(self):
        self.hass.states[self.cfg[C.CONF_BLE_CONNECTED]].last_changed -= timedelta(hours=5)
        await self.start_charging()
        key = C.CONF_DPM_CONFIRMED
        self.hass.states[self.cfg[key]].last_reported -= timedelta(hours=4)
        self.assertEqual(self.controller._setting(key, now()), 4.4)
        self.publish(C.CONF_BLE_CONNECTED, "off")
        self.controller.refresh()
        self.publish(C.CONF_BLE_CONNECTED, "on")
        self.controller.refresh()
        self.assertIsNone(self.controller._setting(key, now()))
        self.publish(key, 4.4)
        self.assertEqual(self.controller._setting(key, now()), 4.4)

    async def test_unchanged_report_does_not_duplicate_policy_or_entity_publication(self):
        await self.start_charging()
        writes = []
        self.controller.add_listener(lambda: writes.append(True), lambda: self.controller.status)
        before = await self.rows()
        for _ in range(10):
            self.controller.refresh()
            await self.settle()
        self.assertEqual(await self.rows(), before)
        self.assertEqual(writes, [])
        self.publish(C.CONF_WALLBOX_CONNECTED, "off")
        self.controller.refresh()
        self.assertEqual(writes, [True])
        self.assertEqual((await self.rows())[-1]["event"], "session_close")
        for row in await self.rows():
            self.assertNotIn("binary_sensor.", str(row))
            self.assertNotIn("sensor.floor", str(row))

    async def test_disabled_diagnostics_option_produces_no_decision_files(self):
        cfg = {**self.cfg, C.CONF_DIAGNOSTIC_LOGGING: False}
        controller = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(cfg), rig.VERSION)
        await controller.async_load()
        controller.start()
        self.assertTrue(controller._trace_session)
        await controller.async_close()
        self.assertFalse(list(Path(self.tmp.name).rglob("*.jsonl")))

    async def test_pending_preplug_arm_is_not_confirmed_if_car_plugs_in(self):
        c=self.controller
        c.start()
        self.publish(C.CONF_WALLBOX_CONNECTED,"off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.publish(C.CONF_WALLBOX_CHARGING,"off")
        self.publish(C.CONF_EV_POWER,0)
        c.refresh()
        from zoneinfo import ZoneInfo
        local=now().astimezone(ZoneInfo(self.hass.config.time_zone))
        await c.async_change("time",(local+timedelta(hours=1)).time().replace(second=0,microsecond=0))
        await c.async_change("delay",True)
        self.assertEqual(c._pending.kind,"delay_arm")
        self.publish(C.CONF_WALLBOX_CONNECTED,"on")
        self.publish(C.CONF_DPM_CONFIRMED,0)
        self.publish(C.CONF_START_STOP,"off")
        c.refresh()
        self.assertFalse(c.real_enabled)
        self.assertIsNone(c._dpm_lease)
        self.assertFalse(any(r["event"]=="confirmed" for r in await self.rows()))
    async def test_out_of_range_number_is_vetoed_and_explained(self):
        self.hass.states[self.cfg[C.CONF_REQUESTED_LIMIT]].attributes["max"] = 3.8
        self.publish(C.CONF_REQUESTED_LIMIT, 3.6)
        self.publish(C.CONF_CONFIRMED_LIMIT, 3.6)
        await self.start_charging()
        self.assertFalse(self.hass.services.calls)
        self.assertTrue(any(r["reason"] == "ev_number_range_or_step_unverified"
                            for r in await self.rows()))

    async def test_journal_day_rollover_and_append_preserve_existing_lines(self):
        from easywallbox_test_package.decision_journal import _append
        folder = Path(self.tmp.name, "log")
        rows = [{"time_local": "2026-11-21T23:59:59+01:00", "seq": 1},
                {"time_local": "2026-11-22T00:00:00+01:00", "seq": 2},
                {"time_local": "2026-11-22T00:00:01+01:00", "seq": 3}]
        _append(folder, rows[:2])
        _append(folder, rows[2:])
        self.assertEqual([json.loads(line) for f in sorted(folder.glob("*.jsonl"))
                          for line in f.read_text().splitlines()], rows)
        self.assertEqual((folder / "decisions_2026-11-21.jsonl").stat().st_mode & 0o077, 0)

    async def test_journal_disk_failure_warns_once_and_reports_gap_on_recovery(self):
        journal = self.controller._journal
        with patch("easywallbox_test_package.decision_journal._append", side_effect=OSError("disk full")):
            with self.assertLogs("easywallbox_test_package.decision_journal", level="WARNING") as messages:
                journal.record("one", "decision", "initial")
                await journal.async_flush()
                journal.record("one", "decision", "next")
                self.assertEqual(len(messages.output), 1)
        journal._retry_after = now()-timedelta(seconds=1)
        journal.record("one", "decision", "recovered")
        saved = await self.rows()
        self.assertEqual(saved[0]["preceding_records_unverified"], 2)
        self.assertEqual(self.hass.services.calls, [])
