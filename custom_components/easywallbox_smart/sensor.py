"""Meaningful session sensors, updated on semantic changes only.

These do not duplicate Shelly power/energy, BLE cable or DPM readings.
No polling, countdown state, or high-frequency Recorder attributes.
"""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .device import controller_device_info


SENSORS = {
    "state": ("Stato ricarica", "mdi:car-electric"),
    "planner": ("Avviso ricarica", "mdi:information-outline"),
    "vehicle": ("Veicolo rilevato", "mdi:car"),
    "phase": ("Stabilizzatore", "mdi:chart-bell-curve"),
    "energy": ("Energia residua stimata", "mdi:battery-charging"),
    "finish": ("Fine carica prevista", "mdi:clock-check-outline"),
}


async def async_setup_entry(hass, entry, add_entities):
    c = hass.data[DOMAIN][entry.entry_id]
    add_entities([RCSensor(c, entry, kind) for kind in SENSORS])


class RCSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller, entry, kind):
        self.c, self.kind = controller, kind
        self._attr_device_info = controller_device_info(entry)
        self._attr_unique_id = entry.entry_id + "_rc_" + kind
        self._attr_name, self._attr_icon = SENSORS[kind]
        if kind in ("state", "planner"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif kind == "energy":
            self._attr_native_unit_of_measurement = "kWh"
            self._attr_device_class = SensorDeviceClass.ENERGY
        elif kind == "finish":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.c.add_listener(self._update))

    @callback
    def _update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        if self.kind == "state":
            return self.c.status
        if self.kind == "planner":
            return self.c.notice
        if self.kind == "vehicle":
            return self.c.vehicle_name or "Nessuna"
        if self.kind == "phase":
            return (self.c._power_state.phase if
                    self.c.charging_verified is True and
                    self.c._power_state is not None else "INATTIVO")
        if self.kind == "energy":
            return self.c._energy_display
        if self.kind == "finish":
            return self.c._finish_display
        return None

    @property
    def extra_state_attributes(self):
        if self.kind == "state":
            return {
                "reason": self.c.reason,
                "quality": self.c.quality,
                "mode": self.c.mode,
                "automatic_control_configured": self.c.real_enabled,
                "session_vehicle": self.c.vehicle_name,
                "soc_stop_enabled_for_vehicle": self.c.stop_at_target_enabled,
                "soc_stop_verified_this_session": self.c._soc_stop_done,
                "last_command": self.c.last_command,
                "last_verified_command": self.c.last_ack,
                "pending_command": self.c._pending.kind if self.c._pending else None,
                "reconciliation_required": self.c._blocked,
            }
        return {}
