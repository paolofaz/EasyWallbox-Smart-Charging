"""Three concise read-only entities, with no per-sample Recorder writes."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, SIMULATION_LABEL

KINDS = {
    "session": "Sessione",
    "plan": "Pianificatore",
    "stabilizer": "Stabilizzatore",
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SimulationSensor(coordinator, entry, kind) for kind in KINDS])


class SimulationSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator, entry, kind):
        self.coordinator = coordinator
        self.kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_translation_key = kind
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="EasyWallbox Smart Charging",
            manufacturer="EasyWallbox Smart Charging",
            model="Solo simulazione",
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.add_listener(self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        s = self.coordinator.session
        p = self.coordinator.planning
        d = self.coordinator.proposal
        if not s or not p or not d:
            return "inizializzazione"
        if self.kind == "session":
            if not s.vehicle_id:
                return "veicolo_ambiguo" if s.vehicle_ambiguous else "scollegata"
            return "in_carica" if s.charging else "collegata_non_in_carica"
        if self.kind == "plan":
            return p.reason
        return d.state.lower()

    @property
    def extra_state_attributes(self):
        s = self.coordinator.session
        p = self.coordinator.planning
        d = self.coordinator.proposal
        attrs = {"simulation_only": True, "warning": SIMULATION_LABEL}
        if not s or not p or not d:
            return attrs
        if self.kind == "session":
            attrs.update(
                vehicle=s.vehicle_id,
                vehicle_ambiguous=s.vehicle_ambiguous,
                soc=s.soc, target_soc=s.target_soc,
                departure=s.departure_at.isoformat() if s.departure_at else None,
                data_quality=self.coordinator.quality,
            )
        elif self.kind == "plan":
            attrs.update(
                remaining_grid_kwh=round(p.remaining_grid_kwh, 2) if p.remaining_grid_kwh is not None else None,
                required_minutes=round(p.required_minutes) if p.required_minutes is not None else None,
                slack_minutes=round(p.slack_minutes) if p.slack_minutes is not None else None,
                budget_kwh=round(p.discretionary_budget_kwh, 2),
                note="Stima prudenziale; il DPM puo ridurre la potenza effettiva",
            )
        else:
            attrs.update(
                action=d.action, reason=d.reason,
                cap_proposed_kw=d.proposed_cap_kw,
                budget_kwh=round(d.budget_kwh, 2),
                spent_upper_bound_kwh=round(d.spent_kwh_upper_bound, 2),
                next_check=d.next_check_at.isoformat() if d.next_check_at else None,
                note="Il limite proposto NON e stato inviato alla wallbox",
            )
        return attrs
