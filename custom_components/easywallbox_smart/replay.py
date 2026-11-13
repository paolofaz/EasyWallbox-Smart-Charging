"""Pure replay of fixed EV power against an *ideal* instantaneous DPM.

No Home Assistant calls, and not a physical model of DPM response time.
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite


@dataclass(frozen=True)
class PowerPoint:
    when: datetime
    observed_house_kw: float | None


@dataclass(frozen=True)
class ReplayResult:
    requested_ev_kw: float
    theoretical_ev_kwh: float
    theoretical_curtailed_kwh: float
    theoretical_limited_minutes: float
    theoretical_limit_periods: int
    valid_minutes: float
    missing_minutes: float


def replay(
    samples: list[PowerPoint],
    start: datetime,
    end: datetime,
    *,
    site_limit_kw: float,
    other_home_kw: float,
    requested_ev_kw: float,
    stale_after_seconds: int = 300,
) -> ReplayResult:
    """Replay filtered power history, excluding missing or stale intervals."""
    if (
        start.tzinfo is None or end.tzinfo is None
        or start.utcoffset() is None or end.utcoffset() is None
        or start >= end
    ):
        raise ValueError("invalid time window")
    if not samples or any(
        point.when.tzinfo is None or point.when.utcoffset() is None
        for point in samples
    ):
        raise ValueError("missing/naive samples")
    inputs = (site_limit_kw, other_home_kw, requested_ev_kw)
    if any(
        not isinstance(x, (int, float)) or isinstance(x, bool)
        or not isfinite(x) for x in inputs
    ):
        raise ValueError("invalid power values")
    if (
        site_limit_kw <= 0 or other_home_kw < 0 or requested_ev_kw <= 0
        or not isinstance(stale_after_seconds, int)
        or stale_after_seconds <= 0
    ):
        raise ValueError("invalid parameters")
    if any(a.when >= b.when for a, b in zip(samples, samples[1:])):
        raise ValueError("samples must be strictly ascending")

    cuts = {start, end}
    for point in samples:
        for when in (
            point.when, point.when + timedelta(seconds=stale_after_seconds)
        ):
            if start < when < end:
                cuts.add(when)
    timeline = sorted(cuts)
    timestamps = [point.when for point in samples]
    energy = lost = clipped = valid = missing = 0.0
    periods = 0
    was_clipped = False
    for a, b in zip(timeline, timeline[1:]):
        minutes = (b - a).total_seconds() / 60
        index = bisect_right(timestamps, a) - 1
        point = samples[index] if index >= 0 else None
        house = point.observed_house_kw if point else None
        if (
            point is None
            or (a - point.when).total_seconds() >= stale_after_seconds
            or house is None
            or not isinstance(house, (int, float))
            or not isfinite(house)
            or house < 0
        ):
            missing += minutes
            was_clipped = False
            continue
        valid += minutes
        available = max(0.0, site_limit_kw - other_home_kw - house)
        actual = min(requested_ev_kw, available)
        energy += actual * minutes / 60
        lost += (requested_ev_kw - actual) * minutes / 60
        is_clipped = available + 1e-9 < requested_ev_kw
        if is_clipped:
            clipped += minutes
            if not was_clipped:
                periods += 1
        was_clipped = is_clipped

    return ReplayResult(
        requested_ev_kw,
        round(energy, 3),
        round(lost, 3),
        round(clipped, 1),
        periods,
        round(valid, 1),
        round(missing, 1),
    )
