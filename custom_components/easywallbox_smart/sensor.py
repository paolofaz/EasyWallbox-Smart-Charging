"""Two event-driven diagnostic entities; never mirror fast Shelly watt streams."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN


async def async_setup_entry(hass, entry, add_entities):
    c = hass.data[DOMAIN][entry.entry_id]
    add_entities([RCSensor(c, entry, kind) for kind in ("state", "planner")])


class RCSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller, entry, kind):
        self.c, self.kind = controller, kind
        self._attr_unique_id = entry.entry_id + "_rc_" + kind
        self._attr_name = ("Johnny RC" if kind == "state" else "Pianificatore RC")
        self._attr_icon = ("mdi:car-electric" if kind == "state" else "mdi:calendar-clock")

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.c.add_listener(self._update))

    @callback
    def _update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self.c.status if self.kind == "state" else (
            "target_raggiunto" if self.c.soc is not None and
            self.c.target_soc is not None and self.c.soc >= self.c.target_soc
            else "stimato" if self.c.margin_minutes is not None
            else "dati_insufficienti"
        )

    @property
    def extra_state_attributes(self):
        if self.kind == "state":
            return {
                "reason": self.c.reason,
                "quality": self.c.quality,
                "mode": self.c.mode,
                "real_control_armed": self.c.real_enabled,
                "session_vehicle": self.c.vehicle_name,
                "last_command": self.c.last_command,
                "last_verified_command": self.c.last_ack,
                "pending_command": self.c._pending.kind if self.c._pending else None,
                "reconciliation_required": self.c._blocked,
                "johnny_phase": self.c._power_state.phase if self.c._power_state else None,
                "johnny_limit_kw": self.c._power_state.cap_kw if self.c._power_state else None,
                "hardware_safety": "physical_DPM_always_active",
            }
        return {
            "target_soc": self.c.target_soc,
            "departure_at": self.c.departure.isoformat() if self.c.departure else None,
            "departure_override": self.c.departure_override.isoformat()
                if self.c.departure_override else None,
            "remaining_grid_kwh": self.c.remaining_kwh,
            # Slack is intentionally not exposed as a constantly changing
            # attribute: Recorder only gets semantic transitions.
            "margin_band": ("unknown" if self.c.margin_minutes is None
                            else "urgent" if self.c.margin_minutes <= 60
                            else "wide" if self.c.margin_minutes >= 75
                            else "medium"),
            "delayed_start_enabled": self.c.delay_enabled,
            "preferred_start_time": self.c.preferred_start.isoformat(timespec="minutes"),
            "model_not_guarantee": True,
        }
