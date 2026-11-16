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
    "shadow_wide": "Johnny test — margine ampio",
    "shadow_medium": "Johnny test — margine intermedio",
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    kinds = ("session", "plan", "stabilizer")
    if coordinator.shadow_enabled:
        kinds += ("shadow_wide", "shadow_medium")
    async_add_entities([SimulationSensor(coordinator, entry, kind) for kind in kinds])


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
        if self.kind.startswith("shadow_"):
            band = self.kind.removeprefix("shadow_")
            state = self.coordinator.shadow_states.get(band)
            return state.mode.lower() if state else "inizializzazione"
        if self.kind == "session":
            control = self.coordinator.control
            if control and control.phase == "UNKNOWN":
                return "collegamento_non_verificato"
            if s.charging:
                return "in_carica"  # physical observation, not simulated pause
            if control and control.requires_confirmation:
                return "modalita_da_confermare"
            if not s.vehicle_id:
                return "veicolo_ambiguo" if s.vehicle_ambiguous else "scollegata"
            if control and control.phase == "TARGET_REACHED":
                return "target_raggiunto_stimato"
            return "collegata_non_in_carica"
        if self.kind == "plan":
            # Show the actual start/wait advice, never the generic slack class.
            advice = self.coordinator.advice
            return advice.action if advice else p.reason
        return d.state.lower()

    @property
    def extra_state_attributes(self):
        s = self.coordinator.session
        p = self.coordinator.planning
        d = self.coordinator.proposal
        attrs = {"simulation_only": True, "warning": SIMULATION_LABEL}
        if not s or not p or not d:
            return attrs
        if self.kind.startswith("shadow_"):
            band = self.kind.removeprefix("shadow_")
            shadow = self.coordinator.shadow_decisions.get(band)
            state = self.coordinator.shadow_states.get(band)
            attrs.update(
                hypothetical_ev_always_charging=True,
                real_wallbox_commands=0,
                shadow_budget_disabled=True,
                configured_initial_kw=self.coordinator.initial_charge_kw,
                hypothetical_ev_max_kw=self.coordinator.max_charge_kw,
                dpm_reference_source=self.coordinator.shadow_dpm_source,
                shadow_log_file=self.coordinator.shadow_log_file,
                shadow_log_status=self.coordinator.shadow_log_status,
                shadow_logged_rows=self.coordinator.shadow_logged_rows,
            )
            if shadow and state:
                attrs.update(
                    action=shadow.action, reason=shadow.reason,
                    cap_proposed_kw=shadow.proposed_cap_kw,
                    last_virtual_transition_reason=state.last_transition_reason,
                    last_virtual_transition_at=(
                        state.last_transition_at.isoformat()
                        if state.last_transition_at else None
                    ),
                    last_trusted_house_report=(
                        state.last_good_house_at.isoformat()
                        if state.last_good_house_at else None
                    ),
                )
            return attrs
        if self.kind == "session":
            control = self.coordinator.control
            attrs.update(
                user_mode=control.mode if control else None,
                observed_phase=control.phase if control else None,
                user_intent_reason=control.reason if control else None,
                requires_confirmation=(
                    control.requires_confirmation if control else False
                ),
                mode_is_simulation_only=True,
                vehicle=s.vehicle_id,
                vehicle_ambiguous=s.vehicle_ambiguous,
                soc=s.soc, target_soc=s.target_soc,
                departure=s.departure_at.isoformat() if s.departure_at else None,
                data_quality=self.coordinator.quality,
            )
        elif self.kind == "plan":
            advice = self.coordinator.advice
            attrs.update(
                planner_reason=p.reason,
                recommendation_reason=advice.reason if advice else None,
                estimated_charge_rate_kw=(
                    round(self.coordinator.rate.kw, 2)
                    if self.coordinator.rate.kw is not None else None
                ),
                estimated_rate_source=self.coordinator.rate.source,
                wallbox_session_average_kw=(
                    round(self.coordinator.rate.session_mean_kw, 2)
                    if self.coordinator.rate.session_mean_kw is not None else None
                ),
                rate_observation_minutes=self.coordinator.rate.sample_minutes,
                rate_is_observation_not_guarantee=True,
                latest_safe_start=(
                    advice.latest_safe_start.isoformat()
                    if advice and advice.latest_safe_start else None
                ),
                next_check=(
                    advice.next_check_at.isoformat()
                    if advice and advice.next_check_at else None
                ),
                recommendation_only=True,
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
                last_virtual_transition_reason=(
                    self.coordinator.state.last_transition_reason
                    if self.coordinator.state else None
                ),
                last_virtual_transition_at=(
                    self.coordinator.state.last_transition_at.isoformat()
                    if self.coordinator.state
                    and self.coordinator.state.last_transition_at else None
                ),
                last_trusted_house_report=(
                    self.coordinator.state.last_good_house_at.isoformat()
                    if self.coordinator.state
                    and self.coordinator.state.last_good_house_at else None
                ),
                margin_band=self.coordinator.margin_band,
                dpm_limit_kw=self.coordinator.dpm_limit_kw,
                dpm_limit_source=self.coordinator.dpm_limit_source,
                estimated_dpm_pressure_kw=(
                    round(self.coordinator.dpm_pressure_kw, 2)
                    if self.coordinator.dpm_pressure_kw is not None else None
                ),
                next_check=d.next_check_at.isoformat() if d.next_check_at else None,
                note="Il limite proposto NON e stato inviato alla wallbox",
            )
        return attrs
