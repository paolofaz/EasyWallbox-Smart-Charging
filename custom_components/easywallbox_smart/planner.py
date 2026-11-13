"""Read-only deadline planning core: no Home Assistant services or BLE calls."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite


@dataclass(frozen=True)
class Request:
    now: datetime
    departure: datetime
    battery_kwh: float
    contract_kw: float
    continuous_kw: float
    house_reference_kw: float
    vehicle_cap_kw: float
    efficiency: float
    reserve_minutes: int
    preferred_start: datetime | None = None


@dataclass(frozen=True)
class Plan:
    status: str
    reason: str
    estimated_ev_kw: float | None
    required_hours: float | None
    latest_start: datetime | None
    recommended_start: datetime | None
    estimated_finish: datetime | None


def _valid(value, allow_zero=False):
    return (
        isinstance(value, (float, int)) and not isinstance(value, bool)
        and isfinite(value) and (value >= 0 if allow_zero else value > 0)
    )


def plan(request: Request) -> Plan:
    """All feasibility results are estimates, never charging guarantees."""
    def invalid(reason):
        return Plan("insufficient_data", reason, None, None, None, None, None)

    times = (request.now, request.departure)
    if request.preferred_start is not None:
        times += (request.preferred_start,)
    if any(t.tzinfo is None or t.utcoffset() is None for t in times):
        return invalid("timezone_required")
    if request.departure <= request.now:
        return invalid("departure_not_future")
    if not all(_valid(v) for v in (
        request.contract_kw, request.continuous_kw,
        request.vehicle_cap_kw, request.efficiency
    )) or request.efficiency > 1:
        return invalid("invalid_power_or_efficiency")
    if not _valid(request.house_reference_kw, allow_zero=True):
        return invalid("house_reference_required")
    if not _valid(request.battery_kwh, allow_zero=True):
        return invalid("battery_energy_required")
    if (
        isinstance(request.reserve_minutes, bool)
        or not isinstance(request.reserve_minutes, int)
        or not 0 <= request.reserve_minutes <= 24 * 60
    ):
        return invalid("invalid_reserve")

    if request.battery_kwh == 0:
        return Plan("target_estimated_reached", "no_energy_required", 0, 0,
                    request.now, request.now, request.now)

    # Temporary meter overload tolerance is deliberately never used.
    ev_kw = min(request.vehicle_cap_kw,
                request.continuous_kw - request.house_reference_kw)
    if ev_kw <= 0:
        return invalid("no_continuous_headroom")
    duration = request.battery_kwh / (ev_kw * request.efficiency)
    if not isfinite(duration) or duration > 1e5:
        return invalid("unrealistic_duration")
    runtime = timedelta(hours=duration)
    latest = request.departure - runtime - timedelta(
        minutes=request.reserve_minutes
    )
    if latest < request.now:
        start, status, reason = (
            request.now, "deadline_at_risk", "not_enough_time_with_reserve"
        )
    elif request.preferred_start is not None and (
        request.now < request.preferred_start <= latest
    ):
        start, status, reason = (
            request.preferred_start, "feasible_estimate",
            "preferred_window_compatible"
        )
    else:
        start, status = request.now, "feasible_estimate"
        reason = ("preferred_window_too_late" if request.preferred_start
                  and request.preferred_start > latest else "start_now")
    return Plan(status, reason, round(ev_kw, 3), round(duration, 3),
                latest, start, start + runtime)
