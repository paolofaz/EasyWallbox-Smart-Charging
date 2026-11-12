"""Read-only Home Assistant sensors for a first vehicle-status simulation."""

from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import DOMAIN
from .snapshot import Source, assess


FIELDS = {
    "active_vehicle": ("Active vehicle", None, None),
    "current_soc": ("Current SOC", "%", SensorStateClass.MEASUREMENT),
    "target_soc": ("Target SOC", "%", SensorStateClass.MEASUREMENT),
    "remaining_energy": ("Battery energy needed", "kWh", SensorStateClass.MEASUREMENT),
    "data_quality": ("Data quality", None, None),
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
        self.entities: list[SmartSensor] = []
        self.snapshot = None
        self.refresh()

    @callback
    def refresh(self, event=None) -> None:
        now = datetime.now(timezone.utc)
        states = {name: _source(self.hass, name, now) for name in self.dependency_ids}
        self.snapshot = assess(self.config, states)
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
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="EasyWallbox Smart Charging",
            manufacturer="EasyWallbox Smart Charging",
            model="Read-only observation",
        )

    @property
    def native_value(self) -> str | float | int | None:
        result = self._monitor.snapshot
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
    def extra_state_attributes(self) -> dict[str, str]:
        result = self._monitor.snapshot
        return {
            "operating_mode": "simulation_only",
            "data_quality": result.quality if result else "initializing",
        }


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
