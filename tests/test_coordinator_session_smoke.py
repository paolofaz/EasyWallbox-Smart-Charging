"""Integration coordinator contract tested with isolated fake HA event APIs.

No network, wallbox, HA services or recorder. The real HA runtime still
requires separate on-device testing before the first public release.
"""
from __future__ import annotations

import importlib.util
import sys
import types
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

COMP = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
PACKAGE = "_ew_coordinator_session_smoke"


class FakeState:
    def __init__(self, value, unit=None):
        self.state = value
        self.attributes = {"unit_of_measurement": unit}
        self.last_updated = datetime.now(timezone.utc)
        self.last_reported = self.last_updated


class FakeHass:
    def __init__(self, states):
        self.states = states
        self.config = types.SimpleNamespace(time_zone="Europe/Rome")
        self.listeners = []
        self.timers = []

    def watch(self, entities, callback):
        tag = {"entities": set(entities), "active": True}
        self.listeners.append(tag)
        return lambda: tag.update(active=False)

    def track(self, callback, at):
        tag = {"at": at, "active": True}
        self.timers.append(tag)
        return lambda: tag.update(active=False)


def fixture(connected=True, charging=False):
    on = "on" if connected else "off"
    states = {
        "sensor.downstairs": FakeState("1900", "W"),
        "sensor.upstairs": FakeState("350", "W"),
        "sensor.ev": FakeState("3000" if charging else "0", "W"),
        "binary_sensor.wallbox_connected": FakeState(on),
        "binary_sensor.wallbox_charging": FakeState("on" if charging else "off"),
        "binary_sensor.fresh": FakeState("on"),
        "number.limit_requested": FakeState("4.0", "kW"),
        "sensor.limit_confirmed": FakeState("4.0", "kW"),
        "binary_sensor.kia_cable": FakeState(on),
        "binary_sensor.fiat_cable": FakeState("off"),
        "sensor.kia_soc": FakeState("40", "%"),
        "sensor.fiat_soc": FakeState("65", "%"),
    }
    data = {
        "house_downstairs": "sensor.downstairs",
        "house_upstairs": "sensor.upstairs",
        "ev_power": "sensor.ev",
        "wallbox_connected": "binary_sensor.wallbox_connected",
        "wallbox_charging": "binary_sensor.wallbox_charging",
        "telemetry_fresh": "binary_sensor.fresh",
        "requested_limit": "number.limit_requested",
        "confirmed_limit": "sensor.limit_confirmed",
        "dpm_model_kw": 4.3,
        "vehicles": [
            dict(name="Kia EV3", cable="binary_sensor.kia_cable",
                 soc="sensor.kia_soc", target_default=80,
                 capacity_kwh=77, sustainable_kw=4.0, efficiency=.9,
                 departure_weekday="07:00", departure_weekend="08:00"),
            dict(name="Fiat 500e", cable="binary_sensor.fiat_cable",
                 soc="sensor.fiat_soc", target_default=80,
                 capacity_kwh=37, sustainable_kw=3.0, efficiency=.9,
                 departure_weekday="07:00", departure_weekend="08:00"),
        ],
    }
    entry = types.SimpleNamespace(data=data, options={}, entry_id="example-1")
    return FakeHass(states), entry


class TestCoordinatorSessionSmoke(TestCase):
    @classmethod
    def setUpClass(cls):
        homeassistant = types.ModuleType("homeassistant")
        homeassistant.__path__ = []
        ha_core = types.ModuleType("homeassistant.core")
        ha_core.HomeAssistant = FakeHass
        ha_core.callback = lambda fn: fn
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []
        components = types.ModuleType("homeassistant.components")
        components.__path__ = []
        select_component = types.ModuleType("homeassistant.components.select")
        class FakeSelectEntity:
            @property
            def options(self):
                return self._attr_options
        select_component.SelectEntity = FakeSelectEntity
        exceptions = types.ModuleType("homeassistant.exceptions")
        exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
        registry = types.ModuleType("homeassistant.helpers.device_registry")
        registry.DeviceInfo = lambda **kwargs: kwargs
        event = types.ModuleType("homeassistant.helpers.event")
        event.async_track_state_change_event = lambda hass, ids, cb: hass.watch(ids, cb)
        event.async_track_point_in_utc_time = lambda hass, cb, at: hass.track(cb, at)
        cls._module_patch = patch.dict(sys.modules, {
            "homeassistant": homeassistant,
            "homeassistant.core": ha_core,
            "homeassistant.components": components,
            "homeassistant.components.select": select_component,
            "homeassistant.exceptions": exceptions,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.device_registry": registry,
            "homeassistant.helpers.event": event,
        })
        cls._module_patch.start()
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(COMP)]
        sys.modules[PACKAGE] = package
        spec = importlib.util.spec_from_file_location(
            PACKAGE + ".coordinator", COMP / "coordinator.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.Implementation = module.SimulationCoordinator
        select_spec = importlib.util.spec_from_file_location(
            PACKAGE + ".select", COMP / "select.py"
        )
        select_module = importlib.util.module_from_spec(select_spec)
        sys.modules[select_spec.name] = select_module
        select_spec.loader.exec_module(select_module)
        cls.ModeSelect = select_module.SimulationModeSelect
        cls.SelectError = exceptions.HomeAssistantError

    @classmethod
    def tearDownClass(cls):
        cls._module_patch.stop()
        for name in tuple(sys.modules):
            if name == PACKAGE or name.startswith(PACKAGE + "."):
                del sys.modules[name]

    def setup(self, *, connected=True, charging=False):
        hass, entry = fixture(connected=connected, charging=charging)
        coordinator = self.Implementation(hass, entry)
        coordinator.start()
        self.addCleanup(coordinator.close)
        return hass, coordinator

    def setstate(self, hass, entity, value, unit=None):
        hass.states[entity] = FakeState(value, unit)

    def test_boot_connected_requires_mode_confirmation(self):
        _, c = self.setup()
        self.assertEqual(c.control.mode, "RECONCILE")
        self.assertEqual(c.advice.action, "insufficient_data")
        self.assertEqual(c.quality, "session_requires_confirmation")
        self.assertEqual(c.proposal.action, "inactive")

    def test_disconnected_boot_auto_on_next_plug(self):
        h, c = self.setup(connected=False)
        self.assertEqual(c.control.phase, "DISCONNECTED")
        self.setstate(h, "binary_sensor.kia_cable", "on")
        self.setstate(h, "binary_sensor.wallbox_connected", "on")
        c.refresh()
        self.assertEqual(c.control.mode, "AUTO")
        self.assertFalse(c.control.requires_confirmation)

    def test_manual_survives_temporary_unavailable(self):
        h, c = self.setup()
        c.choose_mode("MANUAL")
        self.setstate(h, "binary_sensor.kia_cable", "unavailable")
        c.refresh()
        self.assertEqual((c.control.mode, c.control.phase), ("MANUAL", "UNKNOWN"))
        self.setstate(h, "binary_sensor.kia_cable", "on")
        c.refresh()
        self.assertEqual(c.control.mode, "MANUAL")
        self.assertEqual(c.advice.action, "manual")

    def test_pause_does_not_claim_real_charge_stopped(self):
        h, c = self.setup()
        c.choose_mode("PAUSE")
        self.setstate(h, "binary_sensor.wallbox_charging", "on")
        self.setstate(h, "sensor.ev", "3000", "W")
        c.refresh()
        self.assertEqual(c.control.mode, "PAUSE")
        self.assertEqual(c.control.phase, "CHARGING")
        self.assertTrue(c.session.charging)
        self.assertEqual(c.advice.action, "paused")
        self.assertEqual(c.proposal.action, "inactive")

    def test_charge_now_is_only_virtual_recommendation(self):
        _, c = self.setup()
        c.choose_mode("CHARGE_NOW")
        self.assertEqual(c.control.mode, "CHARGE_NOW")
        self.assertEqual(c.proposal.action, "inactive")
        self.assertEqual(c.advice.action, "start_now")
        self.assertTrue(c.advice.simulation_only)

    def test_explicit_disconnect_clears_pause(self):
        h, c = self.setup()
        c.choose_mode("PAUSE")
        self.setstate(h, "binary_sensor.kia_cable", "off")
        self.setstate(h, "binary_sensor.wallbox_connected", "off")
        c.refresh()
        self.assertEqual((c.control.mode, c.control.phase), ("AUTO", "DISCONNECTED"))
        self.setstate(h, "binary_sensor.kia_cable", "on")
        self.setstate(h, "binary_sensor.wallbox_connected", "on")
        c.refresh()
        self.assertEqual(c.control.mode, "AUTO")

    def test_second_car_without_disconnect_stays_unresolved(self):
        h, c = self.setup()
        c.choose_mode("MANUAL")
        self.setstate(h, "binary_sensor.kia_cable", "off")
        self.setstate(h, "binary_sensor.fiat_cable", "on")
        c.refresh()
        self.assertEqual(c.control.mode, "RECONCILE")
        self.assertTrue(c.control.requires_confirmation)

    def test_house_stream_only_when_actual_charging(self):
        h, c = self.setup()
        # Still connected but stationary: no subscription to two Shellys.
        self.assertIsNone(c._house_unsub)
        self.setstate(h, "binary_sensor.wallbox_charging", "on")
        self.setstate(h, "sensor.ev", "3000", "W")
        c.refresh()
        self.assertIsNotNone(c._house_unsub)
        self.setstate(h, "binary_sensor.wallbox_charging", "off")
        self.setstate(h, "sensor.ev", "0", "W")
        c.refresh()
        self.assertIsNone(c._house_unsub)

    def test_unavailable_cable_does_not_count_as_confirmed_disconnect(self):
        h, c = self.setup()
        c.choose_mode("PAUSE")
        self.setstate(h, "binary_sensor.kia_cable", "unknown")
        self.setstate(h, "binary_sensor.wallbox_connected", "off")
        c.refresh()
        self.assertEqual(c.control.mode, "PAUSE")
        self.assertEqual(c.control.phase, "UNKNOWN")

    def test_three_house_meters_sum_without_ev(self):
        h, entry = fixture(connected=True, charging=True)
        entry.data["house_power_sources"] = [
            "sensor.downstairs", "sensor.upstairs", "sensor.extra_house",
        ]
        h.states["sensor.extra_house"] = FakeState("400", "W")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertAlmostEqual(c._house().kw, 2.65)
        self.assertEqual(len(c.house_sources), 3)
        self.assertEqual(len([x for x in h.listeners if x["active"]
                              and "sensor.extra_house" in x["entities"]]), 1)

    def test_measured_rate_ignores_old_configured_power(self):
        h, entry = fixture(connected=True, charging=True)
        entry.data["vehicles"][0]["sustainable_kw"] = 4.0
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.rate.source, "shelly_instant")
        self.assertEqual(c.session.sustainable_kw, 3.0)

    def test_session_counters_mature_rate_and_reset(self):
        h, entry = fixture(connected=True, charging=True)
        entry.data["session_energy"] = "sensor.session_energy"
        entry.data["session_duration"] = "sensor.session_duration"
        h.states["sensor.session_energy"] = FakeState("1.0", "kWh")
        h.states["sensor.session_duration"] = FakeState("30", "min")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.rate.source, "shelly_instant")
        self.setstate(h, "sensor.session_energy", "1.1", "kWh")
        self.setstate(h, "sensor.session_duration", "31", "min")
        c.refresh()
        self.assertEqual(c.rate.source, "mixed_session_mean")
        self.assertTrue(c.rate.kw < 3.0)
        self.setstate(h, "sensor.session_energy", "0.1", "kWh")
        self.setstate(h, "sensor.session_duration", "1", "min")
        c.refresh()
        self.assertEqual(c.rate.source, "shelly_instant")

    def test_unknown_house_source_never_becomes_zero(self):
        h, entry = fixture(connected=True, charging=True)
        entry.data["house_power_sources"] = [
            "sensor.downstairs", "sensor.upstairs", "sensor.missing",
        ]
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertIsNone(c._house().kw)
        self.assertEqual(c._house().quality, "unavailable_or_stale")

    def test_kia_target_from_ha_number_only(self):
        h, entry = fixture(connected=True, charging=False)
        kia = entry.data["vehicles"][0]
        kia["target_mode"] = "entity"
        kia["target_entity"] = "number.kia_target"
        kia.pop("target_default")
        h.states["number.kia_target"] = FakeState("85", "%")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.session.target_soc, 85)
        self.setstate(h, "number.kia_target", "90", "%")
        c.refresh()
        self.assertEqual(c.session.target_soc, 90)
        self.setstate(h, "number.kia_target", "unavailable", "%")
        c.refresh()
        self.assertIsNone(c.session.target_soc)
        self.assertEqual(c.planning.reason, "insufficient_planner_data")

    def test_old_0_1_0_entity_target_unavailable_no_default_fallback(self):
        h, entry = fixture(connected=True, charging=False)
        entry.data["vehicles"][0]["target_entity"] = "sensor.kia_target"
        h.states["sensor.kia_target"] = FakeState("80", "%")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.session.target_soc, 80)
        self.setstate(h, "sensor.kia_target", "unknown", "%")
        c.refresh()
        self.assertIsNone(c.session.target_soc)
        self.assertNotEqual(c.session.target_soc, entry.data["vehicles"][0]["target_default"])

    def test_0_1_0_option_switch_to_fixed_target(self):
        h, entry = fixture(connected=True, charging=False)
        entry.data["vehicles"][0]["target_entity"] = "sensor.kia_target"
        h.states["sensor.kia_target"] = FakeState("80", "%")
        entry.options={"vehicle_overrides":{
            "binary_sensor.kia_cable":{
                "target_mode":"fixed", "target_default":95,
            },
        }}
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.session.target_soc, 95)

    def test_options_entity_is_in_base_state_subscription(self):
        h, entry = fixture(connected=True, charging=False)
        entry.options = {"vehicle_overrides":{
            "binary_sensor.kia_cable": {
                "target_mode":"entity",
                "target_entity":"number.new_kia_target",
            },
        }}
        h.states["number.new_kia_target"] = FakeState("85","%")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.session.target_soc, 85)
        self.assertTrue(any(
            "number.new_kia_target" in tag["entities"]
            for tag in h.listeners if tag["active"]
        ))
        self.setstate(h, "number.new_kia_target", "90", "%")
        c.refresh()
        self.assertEqual(c.session.target_soc, 90)

    def test_options_fixed_mode_does_not_listen_old_ha_entity(self):
        h, entry = fixture(connected=True, charging=False)
        entry.data["vehicles"][0]["target_entity"] = "number.old_target"
        entry.options={"vehicle_overrides":{
            "binary_sensor.kia_cable": {"target_mode":"fixed","target_default":75},
        }}
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.session.target_soc, 75)
        self.assertFalse(any(
            "number.old_target" in tag["entities"]
            for tag in h.listeners if tag["active"]
        ))

    def test_target_with_wrong_unit_is_not_soc_percent(self):
        h, entry = fixture(connected=True, charging=False)
        kia=entry.data["vehicles"][0]
        kia["target_mode"]="entity"
        kia["target_entity"]="sensor.kia_target"
        kia.pop("target_default")
        h.states["sensor.kia_target"] = FakeState("80", "kWh")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertIsNone(c.session.target_soc)

    def test_confirmed_dpm_sensor_used_instead_of_manual_model(self):
        h, entry = fixture(connected=True, charging=True)
        entry.data["dpm_confirmed"] = "sensor.dpm_confirmed"
        entry.data["dpm_model_kw"] = 4.3
        h.states["sensor.dpm_confirmed"] = FakeState("4.4", "kW")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.dpm_limit_source, "sensor")
        self.assertAlmostEqual(c.dpm_limit_kw, 4.4)
        self.assertTrue(any(
            "sensor.dpm_confirmed" in tag["entities"]
            for tag in h.listeners if tag["active"]
        ))
        c.choose_mode("AUTO")
        h.states["sensor.dpm_confirmed"] = FakeState("unavailable", "kW")
        c.refresh()
        self.assertIsNone(c.dpm_limit_kw)
        self.assertEqual(c.proposal.action, "insufficient_data")
        self.assertEqual(c.proposal.reason, "dpm_limit_unavailable")

    def test_dpm_zero_is_unowned_pause_not_auto_restart(self):
        h, entry = fixture(connected=True, charging=False)
        entry.data["dpm_confirmed"] = "sensor.dpm_confirmed"
        h.states["sensor.dpm_confirmed"] = FakeState("0", "kW")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        c.choose_mode("AUTO")
        self.assertEqual(c.dpm_limit_kw, 0.0)
        self.assertEqual(c.advice.action, "insufficient_data")
        self.assertEqual(c.advice.reason, "dpm_zero_pause_origin_unverified")
        self.assertEqual(c.quality, "dpm_zero_pause_origin_unverified")
        self.assertNotIn(c.proposal.action, ("reduce", "restore"))
        self.assertTrue(c.proposal.simulation_only)

    def test_dpm_zero_does_not_override_manual_or_pause_intent(self):
        for mode in ("MANUAL", "PAUSE"):
            with self.subTest(mode=mode):
                h, entry = fixture(connected=True, charging=False)
                entry.data["dpm_confirmed"] = "sensor.dpm_confirmed"
                h.states["sensor.dpm_confirmed"] = FakeState("0", "kW")
                c = self.Implementation(h, entry)
                c.start()
                self.addCleanup(c.close)
                c.choose_mode(mode)
                self.assertEqual(c.advice.action, mode.lower()
                                 if mode == "MANUAL" else "paused")
                self.assertEqual(c.control.mode, mode)

    def test_positive_dpm_sensor_is_used_as_set_not_forced_to_4_4(self):
        h, entry = fixture(connected=True, charging=True)
        entry.data["dpm_confirmed"] = "sensor.dpm_confirmed"
        h.states["sensor.dpm_confirmed"] = FakeState("4.8", "kW")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        c.choose_mode("AUTO")
        self.assertAlmostEqual(c.dpm_limit_kw, 4.8)
        self.assertEqual(c.dpm_limit_source, "sensor")
        self.assertAlmostEqual(c.dpm_pressure_kw, max(0.0, 2.25+4.0-4.8))

    def test_old_entry_without_dpm_entity_uses_explicit_model_only(self):
        h, entry = fixture(connected=True, charging=True)
        entry.data["dpm_model_kw"] = 4.3
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.dpm_limit_source, "simulation_model")
        self.assertAlmostEqual(c.dpm_limit_kw, 4.3)

    def test_dpm_sensor_can_be_configured_in_options_without_device_write(self):
        h, entry = fixture(connected=True, charging=True)
        entry.options = {"dpm_confirmed": "sensor.new_dpm"}
        h.states["sensor.new_dpm"] = FakeState("4.4", "kW")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertEqual(c.dpm_limit_source, "sensor")
        self.assertEqual(c.dpm_limit_kw, 4.4)
        self.assertEqual(c.dpm_pressure_kw, max(0.0, 2.25 + 4. - 4.4))

    def _seed_virtual_limit(self, coordinator):
        from dataclasses import replace
        self.assertIsNotNone(coordinator.state)
        self.assertIsNotNone(coordinator.session.vehicle_id)
        coordinator.state = replace(
            coordinator.state, mode="LIMITED", cap_kw=2.8,
            original_kw=4.0, baseline_requested_kw=4.0,
            baseline_confirmed_kw=4.0,
            baseline_dpm_kw=coordinator.dpm_limit_kw,
            locked_budget_kwh=5.0,
        )

    def test_hass_confirmed_charge_stop_records_virtual_restore(self):
        h, c = self.setup(charging=True)
        c.choose_mode("AUTO")
        self._seed_virtual_limit(c)
        self.setstate(h, "binary_sensor.wallbox_charging", "off")
        self.setstate(h, "sensor.ev", "0", "W")
        c.refresh()
        self.assertEqual((c.proposal.action, c.proposal.reason),
                         ("restore", "charging_stopped_restore_proposed"))
        self.assertEqual(c.state.last_transition_reason, c.proposal.reason)
        c.refresh()
        self.assertEqual(c.proposal.action, "inactive")
        self.assertEqual(c.state.last_transition_reason,
                         "charging_stopped_restore_proposed")

    def test_hass_stale_telemetry_prevents_false_charge_end_restore(self):
        h, c = self.setup(charging=True)
        c.choose_mode("AUTO")
        self._seed_virtual_limit(c)
        self.setstate(h, "binary_sensor.wallbox_charging", "off")
        self.setstate(h, "binary_sensor.fresh", "off")
        self.setstate(h, "sensor.ev", "0", "W")
        c.refresh()
        self.assertEqual(c.proposal.action, "retire")
        self.assertEqual(c.proposal.reason,
                         "end_or_intent_unverified_requires_reconciliation")

    def test_hass_target_reached_cleans_virtual_cap(self):
        h, c = self.setup(charging=True)
        c.choose_mode("AUTO")
        self._seed_virtual_limit(c)
        self.setstate(h, "sensor.kia_soc", "80", "%")
        c.refresh()
        self.assertEqual((c.proposal.action, c.proposal.reason),
                         ("restore", "target_reached_restore_proposed"))

    def test_hass_ev_meter_zero_but_wallbox_charging_needs_reconciliation(self):
        h, c = self.setup(charging=True)
        c.choose_mode("AUTO")
        self._seed_virtual_limit(c)
        self.setstate(h, "sensor.ev", "0", "W")
        c.refresh()
        self.assertEqual(c.proposal.action, "retire")
        self.assertEqual(
            c.proposal.reason,
            "end_or_intent_unverified_requires_reconciliation",
        )

    def test_hass_confirmed_unplug_does_not_lose_old_virtual_cap(self):
        h, c = self.setup(charging=True)
        c.choose_mode("AUTO")
        self._seed_virtual_limit(c)
        self.setstate(h, "binary_sensor.kia_cable", "off")
        self.setstate(h, "binary_sensor.wallbox_connected", "off")
        self.setstate(h, "binary_sensor.wallbox_charging", "off")
        self.setstate(h, "sensor.ev", "0", "W")
        c.refresh()
        self.assertEqual(c.proposal.action, "retire")
        self.assertEqual(c.proposal.reason,
                         "session_changed_requires_reconciliation")
        self.assertIsNone(c.state.cap_kw)

    def test_hass_vehicle_swap_does_not_restore_previous_ev_cap(self):
        h, c = self.setup(charging=True)
        c.choose_mode("AUTO")
        self._seed_virtual_limit(c)
        self.setstate(h, "binary_sensor.kia_cable", "off")
        self.setstate(h, "binary_sensor.fiat_cable", "on")
        c.refresh()
        self.assertEqual(c.proposal.action, "retire")
        self.assertEqual(c.proposal.reason,
                         "session_changed_requires_reconciliation")
        self.assertEqual(c.session.vehicle_id, "binary_sensor.fiat_cable")

    def test_shelly_last_reported_expiry_has_a_timer_without_polling(self):
        h, entry = fixture(connected=True, charging=True)
        h.states["sensor.downstairs"] = FakeState("100", "W")
        h.states["sensor.upstairs"] = FakeState("100", "W")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        c.choose_mode("AUTO")
        active = [t["at"] for t in h.timers if t["active"]]
        self.assertEqual(len(active), 1)
        # Shelly report expires after 3m; EV after 5m. The earlier
        # event is precisely the Shelly deadline, not a repeating poll.
        due = min(
            h.states[x].last_reported + timedelta(minutes=3, seconds=1)
            for x in ("sensor.downstairs", "sensor.upstairs")
        )
        self.assertLess(abs((active[0] - due).total_seconds()), 20)
        self.assertTrue(all(l["active"] is False or l["entities"]
                            for l in h.listeners))

    def test_shelly_absence_schedules_bounded_virtual_cap_recovery(self):
        from importlib import import_module
        mod = import_module(PACKAGE + ".johnny_policy")
        h, entry = fixture(connected=True, charging=True)
        h.states["sensor.downstairs"] = FakeState("100", "W")
        h.states["sensor.upstairs"] = FakeState("100", "W")
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        c.choose_mode("AUTO")
        now = datetime.now(timezone.utc)
        # Missing reports do not create a timer that continually polls;
        # an existing virtual cap has one cleanup deadline at +8m.
        for id in ("sensor.downstairs", "sensor.upstairs"):
            h.states[id].last_reported = now - timedelta(minutes=6)
        c.state = mod.JohnnyState(
            session_id=c.session.session_id, mode="LIMITED",
            cap_kw=2.8, original_kw=4.0,
            last_good_house_at=now - timedelta(minutes=4),
            locked_budget_kwh=20.0,
        )
        c._schedule(now, c.proposal)
        active = [t["at"] for t in h.timers if t["active"]]
        self.assertEqual(len(active), 1)
        expected = now + timedelta(minutes=4, seconds=1)
        self.assertLess(abs((active[0] - expected).total_seconds()), 20)

    def test_opt_in_shadow_runs_unplugged_and_logs_private_jsonl(self):
        import asyncio
        import json
        with tempfile.TemporaryDirectory() as root:
            async def run():
                h, entry = fixture(connected=False, charging=False)
                entry.data["dpm_confirmed"] = "sensor.dpm_sensor"
                h.states["sensor.dpm_sensor"] = FakeState("0", "kW")
                entry.options = {
                    "shadow_lab_enabled": True,
                    "initial_charge_kw": 3.6,
                    "max_charge_kw": 4.0,
                    "dpm_model_kw": 4.8,
                }
                h.config.path = lambda folder: str(Path(root) / folder)
                h.async_add_executor_job = (
                    lambda fn, *args: asyncio.to_thread(fn, *args)
                )
                entry.async_create_background_task = (
                    lambda hass, coro, name: asyncio.create_task(coro, name=name)
                )
                c = self.Implementation(h, entry)
                c.start()
                self.assertFalse(c.session.charging)
                self.assertIsNotNone(c._house_unsub)
                self.assertEqual(set(c.shadow_decisions), {"wide", "medium"})
                self.assertIsNotNone(c.shadow_v2_state)
                self.assertIsNotNone(c.shadow_v2_decision)
                self.assertTrue(all(
                    prop.simulation_only for prop in c.shadow_decisions.values()
                ))
                await asyncio.sleep(.05)
                self.assertEqual(c.shadow_log_status, "ok")
                logdir = Path(root) / "easywallbox_smart_shadow"
                files = list(logdir.glob("shadow_*.jsonl"))
                self.assertEqual(len(files), 1)
                records = [json.loads(x) for x in files[0].read_text().splitlines()]
                self.assertTrue(records)
                first = records[0]
                self.assertIn("wide", first)
                self.assertIn("medium", first)
                self.assertIn("v2", first)
                self.assertTrue(first["virtual_state_reset_on_this_row"])
                self.assertTrue(first["shadow_run_started_local"])
                self.assertTrue(first["house_report_local"])
                self.assertEqual(first["model"],
                                 "continuous_three_candidate_no_real_vehicle")
                self.assertEqual(first["dpm_observed_kw"], 0.)
                self.assertEqual(first["dpm_model_kw"], 4.8)
                self.assertEqual(first["dpm_model_source"],
                                 "explicit_model_when_paused_or_unavailable")
                self.assertNotIn("vehicle_id", first)
                self.assertNotIn("soc", first)
                self.assertNotIn("password", first)
                await c.async_close()
                self.assertIsNone(c._house_unsub)
            asyncio.run(run())

    def test_shadow_disabled_does_not_subscribe_to_house_unplugged(self):
        h, entry = fixture(connected=False, charging=False)
        c = self.Implementation(h, entry)
        c.start()
        self.addCleanup(c.close)
        self.assertFalse(c.shadow_enabled)
        self.assertIsNone(c._house_unsub)
        self.assertEqual(c.shadow_decisions, {})
        self.assertEqual(c.shadow_log_status, "disabled")

    def test_select_entity_changes_only_virtual_mode(self):
        import asyncio
        _, coordinator = self.setup()
        entry = types.SimpleNamespace(entry_id="example-1")
        entity = self.ModeSelect(coordinator, entry)
        self.assertTrue(entity.available)
        self.assertIsNone(entity.current_option)
        self.assertEqual(
            entity.options, ["automatic", "manual", "pause", "charge_now"]
        )
        asyncio.run(entity.async_select_option("pause"))
        self.assertEqual((entity.current_option, coordinator.advice.action),
                         ("pause", "paused"))
        self.assertIn("NESSUN COMANDO", entity.extra_state_attributes["warning"])
        asyncio.run(entity.async_select_option("charge_now"))
        self.assertEqual(coordinator.advice.action, "start_now")
        self.assertTrue(coordinator.proposal.simulation_only)

    def test_select_entity_rejects_unknown_connection(self):
        import asyncio
        hass, coordinator = self.setup()
        entity = self.ModeSelect(
            coordinator, types.SimpleNamespace(entry_id="example-1")
        )
        self.setstate(hass, "binary_sensor.kia_cable", "unavailable")
        coordinator.refresh()
        self.assertFalse(entity.available)
        with self.assertRaises(self.SelectError):
            asyncio.run(entity.async_select_option("automatic"))

    def test_mode_selection_requires_known_connection(self):
        h, c = self.setup()
        self.setstate(h, "binary_sensor.kia_cable", "unknown")
        c.refresh()
        with self.assertRaises(ValueError):
            c.choose_mode("AUTO")

if __name__ == "__main__":
    main()
