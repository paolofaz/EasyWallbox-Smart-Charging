"""Meaningful session sensors; ETA publication is explicitly rate limited.

These do not duplicate Shelly power/energy, BLE cable or DPM readings.
No polling, countdown state, or high-frequency Recorder attributes.
"""
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_track_point_in_utc_time

from .const import DOMAIN
from .device import controller_device_info


SENSORS = {
    "state": ("Stato ricarica", "mdi:car-electric"),
    "planner": ("Avviso ricarica", "mdi:information-outline"),
    "vehicle": ("Veicolo rilevato", "mdi:car"),
    "phase": ("Stabilizzatore", "mdi:chart-bell-curve"),
    "energy": ("Energia residua stimata", "mdi:battery-charging"),
    "finish": ("Fine carica prevista", "mdi:clock-check-outline"),
    "history": ("Sessioni archiviate", "mdi:history"),
}


async def async_setup_entry(hass, entry, add_entities):
    c = hass.data[DOMAIN][entry.entry_id]
    add_entities([ChargingSensor(c, entry, kind) for kind in SENSORS
                  if kind != "history" or c.session_history.enabled])


class ChargingSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller, entry, kind):
        self.c, self.kind = controller, kind
        self._finish_last = None
        self._finish_published = None
        self._finish_timer_cancel = None
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
        if self.kind == "finish":
            self._finish_published = self._finish_snapshot()
            self._finish_last = (datetime.now(timezone.utc)
                                 if self.native_value is not None else None)
            self.async_on_remove(self._cancel_finish_timer)
        self.async_on_remove(self.c.add_listener(
            self._update, lambda: (self.native_value, self.extra_state_attributes)))

    def _finish_snapshot(self):
        return (self.native_value, tuple(sorted(self.extra_state_attributes.items())))

    def _cancel_finish_timer(self):
        if self._finish_timer_cancel is not None:
            self._finish_timer_cancel()
            self._finish_timer_cancel = None

    @callback
    def _finish_due(self, _time):
        self._finish_timer_cancel = None
        self._update()  # Coalesce to the latest controller forecast.

    @callback
    def _update(self):
        if self.kind != "finish":
            self.async_write_ha_state()
            return
        candidate = self._finish_snapshot()
        if candidate == self._finish_published:
            self._cancel_finish_timer()
            return
        now = datetime.now(timezone.utc)
        if (self._finish_last is not None and
                now-self._finish_last < timedelta(seconds=60)):
            if self._finish_timer_cancel is None:
                due = self._finish_last + timedelta(seconds=60)
                self._finish_timer_cancel = async_track_point_in_utc_time(
                    self.hass, self._finish_due, due)
            return
        self._cancel_finish_timer()
        self._finish_published = candidate
        self._finish_last = now
        self.async_write_ha_state()

    @property
    def native_value(self):
        if self.kind == "state":
            return self.c.status
        if self.kind == "planner":
            return self.c.notice
        if self.kind == "vehicle":
            return self.c.vehicle_name or "Nessuna"
        if self.kind == "history":
            return self.c.session_history.total
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
        if self.kind == "history":
            # One record only: large tables are fetched paginated over WS.
            archive = self.c.session_history
            return {"ultima_sessione": archive.sessions[-1] if archive.sessions else None,
                    "totale_osservate": archive.total_observed}
        if self.kind == "finish":
            return {"qualita_previsione": self.c._forecast_quality,
                    "potenza_stimata_kw": self.c._forecast_rate_kw}
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
