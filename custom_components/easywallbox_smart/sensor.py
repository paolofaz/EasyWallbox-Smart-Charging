"""Read-only Home Assistant sensors for a first vehicle-status simulation."""

from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import DOMAIN
from .live_planning import ASSUMED_EFFICIENCY, ASSUMED_RESERVE_MINUTES, demo_scenarios, dependency_ids, evaluate
from .snapshot import Source, assess, telemetry_diagnostic
from .simulation import SimulationSession, evaluate as evaluate_simulation, load_event_inputs


FIELDS = {
    "active_vehicle": ("Active vehicle", None, None),
    "current_soc": ("Current SOC", "%", SensorStateClass.MEASUREMENT),
    "target_soc": ("Target SOC", "%", SensorStateClass.MEASUREMENT),
    "remaining_energy": ("Battery energy needed", "kWh", SensorStateClass.MEASUREMENT),
    "data_quality": ("Data quality", None, None),
    "house_power": ("House power preview", "kW", SensorStateClass.MEASUREMENT),
    "required_mean_power": (
        "Mean power needed by departure", "kW", SensorStateClass.MEASUREMENT
    ),
    "departure_time": ("Next departure preview", None, None),
    "recommended_start": ("Recommended start preview", None, None),
    "estimated_finish": ("Finish if home load stays constant", None, None),
    "plan_status": ("Current home load scenario", None, None),
    "demo_plan": ("Scenario 30% preview", None, None),
    "simulated_decision": ("Load decision simulation", None, None),
}
CHECK_INTERVAL = timedelta(minutes=2)


def _source(hass: HomeAssistant, entity_id: str, now: datetime) -> Source:
    """Use last_reported when a sensor publishes the same state repeatedly."""
    state = hass.states.get(entity_id)
    if state is None:
        return Source(None, None)
    stamp = getattr(state, "last_reported", None) or state.last_updated
    return Source(state.state, (now - stamp).total_seconds() if stamp else None)


class Monitor:
    """Keep one immutable assessment for all entities; properties do no I/O."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.config = {**entry.data, **entry.options}
        self.dependency_ids: set[str] = set()
        for key in ("wallbox_car_connected", "wallbox_telemetry_fresh"):
            value = self.config.get(key)
            if isinstance(value, str) and value:
                self.dependency_ids.add(value)
        for car in self.config.get("vehicles", []):
            for key in ("connected", "soc"):
                value = car.get(key)
                if isinstance(value, str) and value:
                    self.dependency_ids.add(value)
        self.dependency_ids.update(dependency_ids(self.config))
        self.dependency_ids.update(load_event_inputs(self.config))
        self.entities: list[SmartSensor] = []
        self.snapshot = None
        self.telemetry_source = None
        self.preview = None
        self.demo_plans = []
        self._simulation_session = SimulationSession()
        self.decision = None
        self.refresh()

    @callback
    def refresh(self, event=None) -> None:
        now = datetime.now(timezone.utc)
        states = {name: _source(self.hass, name, now) for name in self.dependency_ids}
        self.snapshot = assess(self.config, states)
        telemetry_id = self.config.get("wallbox_telemetry_fresh")
        self.telemetry_source = states.get(telemetry_id) if telemetry_id else None
        self.preview = evaluate(self.hass, self.config, self.snapshot, now)
        self.demo_plans = demo_scenarios(self.hass, self.config, now)
        raw_decision = evaluate_simulation(self.hass, self.config, self.preview, now)
        # Clear in-memory suggestions on loss of the vehicle session.
        if self.snapshot.quality != "ok":
            self._simulation_session.reset()
        # After an HA restart, simulated decisions never imply actual
        # controller actions; no persistent commands or restoration.
        self.decision = self._simulation_session.update(raw_decision)
        for entity in self.entities:
            if entity.hass is not None:
                entity.async_write_ha_state()


class SmartSensor(SensorEntity):
    """Passive sensors, including a detailed reason when input is unavailable."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, monitor: Monitor, entry: ConfigEntry, kind: str) -> None:
        self._monitor = monitor
        self._kind = kind
        name, unit, state_class = FIELDS[kind]
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        if kind in ("departure_time", "recommended_start", "estimated_finish"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="EasyWallbox Smart Charging",
            manufacturer="EasyWallbox Smart Charging",
            model="Read-only observation",
        )

    @property
    def native_value(self):
        result = self._monitor.snapshot
        preview = self._monitor.preview
        if self._kind == "simulated_decision":
            return (
                self._monitor.decision.code
                if self._monitor.decision else "unavailable"
            )
        if self._kind == "demo_plan":
            if not self._monitor.demo_plans:
                return "unconfigured"
            if all(s["status"] == "unconfigured" for s in self._monitor.demo_plans):
                return "unconfigured"
            return "available" if any(s["status"] == "current_load_scenario_feasible"
                for s in self._monitor.demo_plans) else "review"
        if self._kind == "house_power":
            return preview.house_kw if preview else None
        if self._kind == "required_mean_power":
            demand = preview.demand if preview else None
            return demand.required_grid_kw if demand else None
        if self._kind == "departure_time":
            return preview.departure if preview else None
        if self._kind == "plan_status":
            return preview.status if preview else "unavailable"
        if self._kind in ("recommended_start", "estimated_finish"):
            p = preview.result if preview else None
            if p is None:
                return None
            return (p.recommended_start if self._kind == "recommended_start"
                    else p.estimated_finish)
        if result is None:
            return None
        return {
            "active_vehicle": result.vehicle,
            "current_soc": result.soc,
            "target_soc": result.target,
            "remaining_energy": result.remaining_kwh,
            "data_quality": result.quality,
        }[self._kind]

    @property
    def extra_state_attributes(self) -> dict:
        result = self._monitor.snapshot
        preview = self._monitor.preview
        attrs = {
            "operating_mode": "simulation_only",
            "data_quality": result.quality if result else "initializing",
            "no_device_commands": True,
        }
        if self._kind == "data_quality":
            sensor_id = self._monitor.config.get("wallbox_telemetry_fresh")
            source = self._monitor.telemetry_source
            attrs["wallbox_telemetry_entity"] = sensor_id or None
            attrs["wallbox_telemetry_state"] = (
                source.value if source is not None else None
            )
            attrs["wallbox_telemetry_age_seconds"] = (
                round(source.age_seconds, 1)
                if source is not None and source.age_seconds is not None
                else None
            )
            # An ON/OFF watchdog is a persistent state, not a numerical
            # sample requiring a fresh timestamp every 120 seconds.
            attrs["wallbox_telemetry_freshness_policy"] = "esphome_watchdog_state"
            attrs["wallbox_telemetry_age_is_timeout"] = False
            attrs["wallbox_telemetry_diagnostic"] = (
                telemetry_diagnostic(source) if sensor_id else "not_configured"
            )
        if self._kind == "simulated_decision":
            decision = self._monitor.decision
            if decision:
                attrs.update({
                    "requested_limit_kw": decision.requested_kw,
                    "confirmed_limit_kw": decision.confirmed_kw,
                    "actual_charging_kw": decision.actual_kw,
                    "suggested_limit_kw": decision.suggested_kw,
                    "load_state": decision.load_state,
                    "expected_additional_peak_kw": decision.expected_extra_peak_kw,
                    "expected_load_duration_min": decision.expected_minutes,
                    "theoretical_energy_delayed_kwh": decision.lost_grid_kwh,
                    "theoretical_energy_margin_kwh": decision.energy_margin_kwh,
                    "confirmed_limit_quality": decision.confirmed_state,
                    "all_recommendations_are_hypothetical": True,
                    "never_sent_any_command": True,
                })
        if self._kind == "demo_plan":
            attrs["scenario_description"] = "30_to_usual_target_without_car"
            attrs["vehicle_scenarios"] = self._monitor.demo_plans
        if preview and self._kind in (
            "plan_status", "house_power", "required_mean_power",
            "recommended_start", "estimated_finish"
        ):
            attrs.update({
                "reason": preview.reason,
                "power_quality": preview.power_quality,
                "forecast_basis": "current_house_power_held_constant",
                "scenario_not_a_prediction": True,
                "assumed_ac_efficiency": ASSUMED_EFFICIENCY,
                "assumed_reserve_minutes": ASSUMED_RESERVE_MINUTES,
            })
            if preview.demand is not None:
                attrs["required_mean_grid_kw"] = preview.demand.required_grid_kw
                attrs["required_mean_basis"] = "battery_kwh_divided_by_time_and_efficiency"
                attrs["time_until_departure_less_reserve_hours"] = (
                    preview.demand.usable_hours
                )
                attrs["deadline_demand_status"] = preview.demand.status
            if preview.result is not None:
                attrs["estimated_ev_kw"] = preview.result.estimated_ev_kw
                attrs["required_charge_hours"] = preview.result.required_hours
                attrs["latest_safe_start"] = (
                    preview.result.latest_start.isoformat()
                    if preview.result.latest_start else None
                )
        return attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Start HA subscriptions; HA entry unload releases all callbacks."""
    monitor = Monitor(hass, entry)
    sensors = [SmartSensor(monitor, entry, kind) for kind in FIELDS]
    monitor.entities = sensors
    async_add_entities(sensors)
    if monitor.dependency_ids:
        entry.async_on_unload(
            async_track_state_change_event(
                hass, sorted(monitor.dependency_ids), monitor.refresh
            )
        )
    entry.async_on_unload(
        async_track_time_interval(hass, monitor.refresh, CHECK_INTERVAL)
    )
