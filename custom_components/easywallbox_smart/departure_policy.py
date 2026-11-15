"""Pure, read-only recommendation of EV start vs waiting until departure.

This module only *advises*. It never starts/stops a wallbox, changes power
limits, or interprets simulated commands as electrical confirmation.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

from .core import HouseSnapshot, Plan, SessionSnapshot


@dataclass(frozen=True)
class DepartureAdvice:
    action: str  # inactive, insufficient_data, paused, manual, complete, charging, wait, start_now
    reason: str
    latest_safe_start: datetime | None = None
    next_check_at: datetime | None = None
    simulation_only: bool = True


def advise_departure(
    now: datetime,
    session: SessionSnapshot,
    planned: Plan,
    house: HouseSnapshot,
    *,
    busy_threshold_kw: float = 1.5,
    check_minutes: int = 5,
    minimum_slack_minutes: float = 45.0,
) -> DepartureAdvice:
    """Explain the next *virtual* step based on remaining time and domestic load.

    - Never wait beyond latest_safe_start.
    - No tariffs, named appliances, DPM imitation, or guaranteed finish.
    - House measurements never determine assumed long-term EV power.
    - During a confirmed charging state, do not propose a fresh start.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if (not isinstance(check_minutes, int) or isinstance(check_minutes, bool)
            or check_minutes < 1 or not isinstance(busy_threshold_kw, (int, float))
            or not isfinite(busy_threshold_kw) or busy_threshold_kw <= 0
            or not isinstance(minimum_slack_minutes, (int, float))
            or not isfinite(minimum_slack_minutes) or minimum_slack_minutes < 0):
        raise ValueError("invalid offline planner settings")
    if session.mode == "PAUSE":
        return DepartureAdvice("paused", "explicit_user_pause")
    if session.mode == "MANUAL":
        return DepartureAdvice("manual", "manual_session_owned_by_user")
    if session.mode == "RECONCILE":
        return DepartureAdvice("insufficient_data", "explicit_mode_confirmation_required")
    if session.mode not in ("AUTO", "CHARGE_NOW"):
        return DepartureAdvice("insufficient_data", "unknown_session_mode")
    if session.vehicle_ambiguous:
        return DepartureAdvice("insufficient_data", "ambiguous_vehicle")
    if not session.vehicle_id:
        return DepartureAdvice("inactive", "no_identified_vehicle")
    # An observed real charge at SOC target (especially 100%) may be
    # vehicle-controlled balancing; never claim that charging stopped.
    if planned.reason == "target_reached" and session.charging:
        return DepartureAdvice("charging", "vehicle_may_be_balancing")
    if planned.reason == "target_reached":
        return DepartureAdvice("complete", "target_reached")
    if (planned.reason in ("unidentified_vehicle", "insufficient_planner_data")
            or planned.required_minutes is None or planned.slack_minutes is None
            or session.departure_at is None or session.departure_at.tzinfo is None
            or session.departure_at.utcoffset() is None):
        return DepartureAdvice("insufficient_data", "planner_missing_or_stale")
    if session.charging:
        return DepartureAdvice("charging", "charging_in_progress")

    latest = session.departure_at - timedelta(
        minutes=planned.required_minutes + session.reserve_minutes
    )
    if session.mode == "CHARGE_NOW":
        # This is a UI preference in v0.1, NOT a wallbox start command.
        return DepartureAdvice("start_now", "explicit_charge_now_simulation_only", latest)
    if (latest <= now or planned.slack_minutes <= minimum_slack_minutes):
        return DepartureAdvice("start_now", "departure_priority_dpm_remains_active", latest)

    # Unknown household data must not be read as an idle (0 kW) house.
    home = house.kw
    if home is None:
        return DepartureAdvice(
            "insufficient_data", "house_data_missing_or_incoherent",
            latest_safe_start=latest,
            next_check_at=latest,
        )
    if home >= busy_threshold_kw:
        due = min(latest, now + timedelta(minutes=check_minutes))
        return DepartureAdvice(
            "wait", "house_busy_slack_available", latest, due
        )
    return DepartureAdvice("start_now", "house_quiet", latest)
