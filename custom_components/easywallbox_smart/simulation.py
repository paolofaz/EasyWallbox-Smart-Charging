"""Read-only bridge between HA state entities and generic load scenarios."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import isfinite

from .load_scenario import LoadScenario, evaluate_load

MAX_DYNAMIC_AGE_S = 300


@dataclass(frozen=True)
class Decision:
    code: str
    requested_kw: float | None = None
    confirmed_kw: float | None = None
    actual_kw: float | None = None
    suggested_kw: float | None = None
    load_state: str | None = None
    expected_extra_peak_kw: float | None = None
    expected_minutes: int | None = None
    lost_grid_kwh: float | None = None
    energy_margin_kwh: float | None = None
    confirmed_state: str = "not_configured"
    note: str = "simulation_only_no_commands"


def _numeric_kw(hass, entity_id: str | None, now: datetime,
                require_new_reading: bool) -> float | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        return None
    if require_new_reading:
        timestamp = getattr(state, "last_reported", None) or state.last_updated
        age = (now.astimezone(timezone.utc) - timestamp).total_seconds()
        if not 0 <= age <= MAX_DYNAMIC_AGE_S:
            return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    if not isfinite(value) or value < 0:
        return None
    unit = state.attributes.get("unit_of_measurement")
    if unit not in ("W", "kW"):
        return None
    return value / (1000 if unit == "W" else 1)


def load_event_inputs(config: dict) -> set[str]:
    return {
        config[key] for key in (
            "ev_requested_limit", "ev_confirmed_limit", "load_active_entity"
        )
        if isinstance(config.get(key), str) and config[key]
    }


def evaluate(hass, config: dict, preview, now: datetime) -> Decision:
    """No recommendation without confirmed EV cap and trustworthy SOC/deadline."""
    requested = _numeric_kw(
        hass, config.get("ev_requested_limit"), now, False
    )
    confirmed = _numeric_kw(
        hass, config.get("ev_confirmed_limit"), now, False
    )
    actual = _numeric_kw(
        hass, config.get("ev_power_sensor"), now, True
    )
    power_quality = (
        "confirmed" if confirmed is not None
        else "not_configured" if not config.get("ev_confirmed_limit")
        else "confirmed_unavailable"
    )

    def advice(code, **kw):
        return Decision(
            code, requested, confirmed, actual,
            confirmed_state=power_quality, **kw
        )

    if requested is not None and confirmed is not None and (
        abs(requested - confirmed) > 0.25
    ):
        return advice("requested_confirmed_mismatch")
    if confirmed is None or confirmed < 1.4:
        return advice("confirmed_limit_required")
    active_id = config.get("load_active_entity")
    if not active_id:
        return advice("no_load_configured")
    entity = hass.states.get(active_id)
    if entity is None:
        return advice("load_unknown", load_state="missing")
    state = entity.state.lower()
    if state not in ("on", "off"):
        return advice("load_unknown", load_state=state)
    if state == "off":
        return advice("load_inactive", load_state="off")
    if preview.demand is None or preview.demand.status not in (
        "ok", "target_estimated_reached"
    ) or preview.house_kw is None or preview.departure is None:
        return advice("planning_data_unavailable", load_state="on")
    if preview.demand.status == "target_estimated_reached":
        return advice("target_reached", load_state="on")

    try:
        site = float(config["continuous_kw"])
        peak = float(config["load_peak_kw"])
        minutes = int(config["load_duration_minutes"])
    except (ValueError, TypeError, KeyError):
        return advice("load_configuration_invalid", load_state="on")
    recommendation = evaluate_load(LoadScenario(
        available_site_kw=site,
        observed_house_kw=preview.house_kw,
        confirmed_ev_limit_kw=confirmed,
        missing_battery_kwh=(
            preview.demand.required_grid_kw
            * preview.demand.usable_hours * 0.90
        ),
        efficiency=0.90,
        remaining_usable_hours=preview.demand.usable_hours,
        active=True,
        additional_peak_kw=peak,
        estimated_active_minutes=minutes,
    ))
    return advice(
        recommendation.code,
        suggested_kw=recommendation.proposed_ev_limit_kw,
        load_state="on", expected_extra_peak_kw=peak,
        expected_minutes=minutes,
        lost_grid_kwh=recommendation.lost_grid_kwh,
        energy_margin_kwh=recommendation.grid_energy_margin_kwh,
    )


class SimulationSession:
    """Only memory of *hypothetical* changes; resets on restart/unplug.

    A physical user change of requested power cancels any hypothetical
    automatic restoration. No HA services/actions are ever called.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Drop hypothetical session state on disconnect/restart/unknown."""
        self.was_active = False
        self.original_kw = None
        self.planned_kw = None
        self.overridden = False

    def update(self, current: Decision) -> Decision:
        if current.load_state not in ("on", "off"):
            self.reset()
            return current
        if current.load_state == "on":
            if not self.was_active:
                self.original_kw = current.requested_kw
                self.planned_kw = None
                self.overridden = False
            elif (
                self.original_kw is not None and current.requested_kw is not None
                and abs(self.original_kw - current.requested_kw) > 0.19
            ):
                self.overridden = True
                self.planned_kw = None
            if not self.overridden and (
                current.code == "temporary_reduction_possible"
            ):
                self.planned_kw = current.suggested_kw
            self.was_active = True
            if self.overridden:
                return replace(current, code="manual_override_respected",
                               suggested_kw=None)
            return current
        if (
            self.was_active and not self.overridden
            and self.planned_kw is not None
            and self.original_kw is not None
            and current.requested_kw is not None
            and abs(self.original_kw - current.requested_kw) <= 0.19
        ):
            # The recommendation was NEVER sent; restoration is also
            # purely hypothetical. Do not imply a real reduction occurred.
            output = replace(
                current, code="hypothetical_restoration_after_load",
                suggested_kw=self.original_kw,
            )
        else:
            output = current
        self.reset()
        return output
