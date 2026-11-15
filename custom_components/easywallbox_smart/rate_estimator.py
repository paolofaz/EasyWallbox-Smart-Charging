"""Conservative session-local EV power estimation for a read-only planner.

No history, storage, Home Assistant dependencies or device commands.

A new charging session first uses measured Shelly EV power. After 30 minutes
it may blend this with the wallbox's session energy/time mean, but only after
observing a consistent, advancing pair of wallbox counters in this session.
An untrusted/stale input MUST be passed as None by the Home Assistant adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

MIN_COUNTER_MINUTES = 30.0
MIN_COUNTER_SAMPLES = 2
MIN_EFFECTIVE_KW = 0.1
MAX_PLAUSIBLE_KW = 22.0


def _valid(value: object) -> bool:
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and isfinite(value) and value >= 0)


@dataclass(frozen=True)
class RateState:
    session_id: str | None = None
    last_energy_kwh: float | None = None
    last_duration_min: float | None = None
    counter_samples: int = 0
    last_at: datetime | None = None


@dataclass(frozen=True)
class RateEstimate:
    kw: float | None
    source: str  # unavailable, shelly_instant, mixed_session_mean
    session_mean_kw: float | None = None
    sample_minutes: float | None = None
    simulation_only: bool = True


def estimate(
    now: datetime,
    session_id: str | None,
    charging: bool,
    instantaneous_kw: float | None,
    session_energy_kwh: float | None,
    session_duration_min: float | None,
    confirmed_limit_kw: float | None,
    previous: RateState | None = None,
) -> tuple[RateState, RateEstimate]:
    """Estimate achievable power from observed current/session data.

    This is NOT a guaranteed future charging rate. The DPM, home load and
    vehicle can change. Never use a confirmed charge limit as measured power.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware timestamp required")
    if not isinstance(charging, bool):
        raise ValueError("charging must be a boolean")
    empty = RateEstimate(None, "unavailable")
    if not charging or not session_id:
        return RateState(), empty

    state = previous if previous and previous.session_id == session_id else RateState(session_id=session_id)
    if state.last_at is not None and now < state.last_at:
        return state, empty

    ceiling = confirmed_limit_kw if _valid(confirmed_limit_kw) and confirmed_limit_kw > 0 else None
    instant = None
    if _valid(instantaneous_kw) and MIN_EFFECTIVE_KW <= instantaneous_kw <= MAX_PLAUSIBLE_KW:
        instant = min(instantaneous_kw, ceiling) if ceiling is not None else instantaneous_kw

    energy_valid = _valid(session_energy_kwh)
    duration_valid = _valid(session_duration_min) and session_duration_min <= 7 * 24 * 60
    mean = None
    samples = state.counter_samples
    if energy_valid and duration_valid:
        if (state.last_energy_kwh is not None and
            (session_energy_kwh < state.last_energy_kwh - 0.05
             or session_duration_min < state.last_duration_min)):
            # Counter reset -> no cross-session averages. Restart trust chain.
            samples = 1
        elif state.last_energy_kwh is None:
            samples = 1
        elif (session_duration_min > state.last_duration_min
              and session_energy_kwh >= state.last_energy_kwh - 0.05):
            samples = min(3, samples + 1)
        state = RateState(session_id, session_energy_kwh, session_duration_min, samples, now)
        if (samples >= MIN_COUNTER_SAMPLES
                and session_duration_min >= MIN_COUNTER_MINUTES):
            candidate = 60.0 * session_energy_kwh / session_duration_min
            if MIN_EFFECTIVE_KW <= candidate <= MAX_PLAUSIBLE_KW:
                mean = min(candidate, ceiling) if ceiling is not None else candidate
    else:
        # Do not blend current readings with a counter that stopped reporting.
        state = RateState(session_id, None, None, 0, now)

    if instant is not None and mean is not None:
        # Current DPM conditions have more influence than older charging hours.
        value = 0.65 * instant + 0.35 * mean
        return state, RateEstimate(round(value, 3), "mixed_session_mean", mean, session_duration_min)
    if instant is not None:
        return state, RateEstimate(round(instant, 3), "shelly_instant")
    # A long-term average alone may be badly wrong if the DPM just reduced
    # power or charging stopped. Require actual Shelly power for a rate.
    return state, empty
