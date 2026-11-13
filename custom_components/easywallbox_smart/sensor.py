"""Minimal, read-only HA charging view; no actuation and no duplicate meters."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .charging_eta import ASSUMED_AC_EFFICIENCY, evaluate as charging_eta
from .const import DOMAIN
from .schedule import next_departure
from .snapshot import Source, assess, telemetry_diagnostic

# Only values useful to the owner in everyday operation.
FIELDS = {
    "active_vehicle": ("Veicolo", None, None),
    "current_soc": ("SOC attuale", "%", SensorStateClass.MEASUREMENT),
    "target_soc": ("Obiettivo SOC", "%", SensorStateClass.MEASUREMENT),
    "remaining_energy": ("Energia necessaria", "kWh", SensorStateClass.MEASUREMENT),
    "departure_time": ("Prossima partenza", None, None),
    "estimated_finish": ("Fine stimata alla potenza attuale", None, None),
    "data_quality": ("Qualità dati", None, None),
}

# Remove only old generated entities belonging to THIS config entry.
# These were experimental formulas already available in ESPHome/Shelly or
# duplicative previews. No source entity or user-owned entity is touched.
RETIRED_KINDS = (
    "house_power", "required_mean_power", "recommended_start",
    "plan_status", "demo_plan", "simulated_decision",
)

CHECK_INTERVAL = timedelta(minutes=2)


def _source(hass: HomeAssistant, entity_id: str, now: datetime) -> Source:
    state = hass.states.get(entity_id)
    if state is None:
        return Source(None, None)
    stamp = getattr(state, "last_reported", None) or state.last_updated
    return Source(state.state, (now - stamp).total_seconds() if stamp else None)


def _next_departure(hass: HomeAssistant, config: dict, now: datetime):
    """Departure alone needs user settings, not home power or a live car."""
    try:
        local = now.astimezone(ZoneInfo(hass.config.time_zone))
        weekday = config.get("departure_weekday")
        weekend = config.get("departure_weekend")
        if not weekday or not weekend:
            return None
        return next_departure(local, weekday, weekend)
    except (ValueError, TypeError, KeyError):
        return None


class Monitor:
    """Read HA sensor states and cache one coherent update for all entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.config = {**entry.data, **entry.options}
        self.dependency_ids: set[str] = set()
        for key in ("wallbox_car_connected", "wallbox_telemetry_fresh",
                    "ev_power_sensor"):
            value = self.config.get(key)
            if isinstance(value, str) and value:
                self.dependency_ids.add(value)
        for car in self.config.get("vehicles", []):
            for key in ("connected", "soc"):
                entity_id = car.get(key)
                if isinstance(entity_id, str) and entity_id:
                    self.dependency_ids.add(entity_id)
        self.entities: list[SmartSensor] = []
        self.snapshot = None
        self.telemetry_source = None
        self.departure = None
        self.eta = None
        self.refresh()

    @callback
    def refresh(self, event=None) -> None:
        now = datetime.now(timezone.utc)
        states = {name: _source(self.hass, name, now) for name in self.dependency_ids}
        self.snapshot = assess(self.config, states)
        telemetry_id = self.config.get("wallbox_telemetry_fresh")
        self.telemetry_source = states.get(telemetry_id) if telemetry_id else None
        self.departure = _next_departure(self.hass, self.config, now)
        self.eta = charging_eta(self.hass, self.config, self.snapshot, now)
        for entity in self.entities:
            if entity.hass is not None:
                entity.async_write_ha_state()


class SmartSensor(SensorEntity):
    """Main session readings plus one separate diagnostic entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, monitor: Monitor, entry: ConfigEntry, kind: str) -> None:
        self._monitor = monitor
        self._kind = kind
        _fallback_name, unit, state_class = FIELDS[kind]
        self._attr_translation_key = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        if kind in ("departure_time", "estimated_finish"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        if kind == "data_quality":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="EasyWallbox Smart Charging",
            manufacturer="EasyWallbox Smart Charging",
            model="Read-only planning",
        )

    @property
    def native_value(self):
        snapshot = self._monitor.snapshot
        if self._kind == "departure_time":
            return self._monitor.departure
        if self._kind == "estimated_finish":
            eta = self._monitor.eta
            return eta.finish if eta and eta.status in (
                "ok", "target_reached"
            ) else None
        if snapshot is None:
            return None
        return {
            "active_vehicle": snapshot.vehicle,
            "current_soc": snapshot.soc,
            "target_soc": snapshot.target,
            "remaining_energy": snapshot.remaining_kwh,
            "data_quality": snapshot.quality,
        }[self._kind]

    @property
    def extra_state_attributes(self) -> dict:
        snapshot = self._monitor.snapshot
        if self._kind == "estimated_finish":
            eta = self._monitor.eta
            attrs = {
                "simulation_only": True,
                "status": eta.status if eta else "initializing",
                "source": self._monitor.config.get("ev_power_sensor"),
                "measured_charging_kw": eta.ev_grid_kw if eta else None,
                "remaining_hours": eta.hours_remaining if eta else None,
                "assumed_ac_efficiency": ASSUMED_AC_EFFICIENCY,
                "basis": "charging_power_held_constant",
            }
            if eta and eta.finish is not None and self._monitor.departure:
                attrs["estimated_minutes_before_departure"] = round(
                    (self._monitor.departure - eta.finish).total_seconds() / 60
                )
            return attrs
        if self._kind == "data_quality":
            sensor_id = self._monitor.config.get("wallbox_telemetry_fresh")
            source = self._monitor.telemetry_source
            return {
                "telemetry_entity": sensor_id,
                "telemetry_state": source.value if source else None,
                "telemetry_age_seconds": (
                    round(source.age_seconds, 1)
                    if source and source.age_seconds is not None else None
                ),
                "telemetry_diagnostic": (
                    telemetry_diagnostic(source) if sensor_id else "not_configured"
                ),
                "charging_eta_status": (
                    self._monitor.eta.status if self._monitor.eta else None
                ),
                "simulation_only": True,
            }
        return {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register only the useful entities; clean up this entry's old previews."""
    registry = er.async_get(hass)
    for kind in RETIRED_KINDS:
        old_entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{kind}"
        )
        if old_entity_id is not None:
            registry.async_remove(old_entity_id)

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
