"""Volatile Shelly window for charging-only decisions (M1, simulation).

Pure Python: no Home Assistant imports, filesystem, logger, network, BLE or
service calls.  This module never records individual samples anywhere durable.
An HA adapter must still be implemented and tested before it can be used live.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import floor, isfinite

WINDOW = timedelta(minutes=5)
HISTORY = timedelta(minutes=20)
MAX_POINTS = 1200  # Explicit memory bound, even if a source floods updates.
MAX_GAP = timedelta(seconds=60)
FRESHNESS = timedelta(seconds=60)


@dataclass(frozen=True)
class Point:
    at: datetime
    house_kw: float | None
    total_kw: float | None


@dataclass(frozen=True)
class RiseAssessment:
    status: str
    reason: str
    house_peak_kw: float | None = None
    safe_limit_kw: float | None = None
    proposed_limit_kw: float | None = None
    samples: int = 0


def _valid(value, *, positive=False):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        and (value > 0 if positive else value >= 0)
    )


def _aware(when: datetime) -> bool:
    return isinstance(when, datetime) and when.tzinfo is not None and when.utcoffset() is not None


def _floor_step(kw: float, step_kw: float) -> float:
    return round(floor((kw + 1e-9) / step_kw) * step_kw, 3)


def peak_cap(
    *,
    available_kw: float,
    house_at_peak_kw: float | None,
    authorized_limit_kw: float,
    margin_kw: float = 0.2,
    step_kw: float = 0.2,
    min_limit_kw: float = 1.4,
    optional_reduction_allowed: bool = True,
) -> float | None:
    """Maximum *optional* charging cap from a validated domestic peak.

    None means no usable optional reduction; it NEVER means stop charging.
    The DPM stays active and is not controlled here. The departure planner must
    supply optional_reduction_allowed and validate its own energy assumptions.
    """
    values = (available_kw, authorized_limit_kw, step_kw, min_limit_kw)
    if not all(_valid(v, positive=True) for v in values):
        return None
    if not _valid(margin_kw) or not _valid(house_at_peak_kw):
        return None
    if not isinstance(optional_reduction_allowed, bool) or not optional_reduction_allowed:
        return None
    candidate = _floor_step(available_kw - house_at_peak_kw - margin_kw, step_kw)
    if candidate < min_limit_kw or candidate >= authorized_limit_kw - 1e-8:
        return None
    return candidate


class ChargingWindow:
    """Observe only while *actually charging*, using a bounded RAM deque.

    The upstream adapter must deliver coherent, time-stamped combinations of
    domestic sensors, explicitly excluding the wallbox. An asynchronous or
    unavailable combination should be pushed with coherent=False, never as 0.
    """

    def __init__(self) -> None:
        self._charging = False
        self._points: deque[Point] = deque()

    @property
    def charging(self) -> bool:
        return self._charging

    @property
    def count(self) -> int:
        return len(self._points)

    def set_charging(self, charging: bool) -> None:
        if not isinstance(charging, bool):
            raise ValueError("charging must be a boolean")
        if charging != self._charging or not charging:
            self._points.clear()
        self._charging = charging

    def add(
        self, at: datetime, house_kw: float | None,
        *, total_kw: float | None = None, coherent: bool = True,
    ) -> bool:
        """Add a volatile observation; False means no sample was accepted."""
        if not self._charging:
            return False
        if not _aware(at) or not isinstance(coherent, bool):
            return False
        if self._points and at <= self._points[-1].at:
            return False
        clean_house = float(house_kw) if coherent and _valid(house_kw) else None
        clean_total = float(total_kw) if coherent and _valid(total_kw) else None
        self._points.append(Point(at, clean_house, clean_total))
        cutoff = at - HISTORY
        while self._points and (self._points[0].at < cutoff or len(self._points) > MAX_POINTS):
            self._points.popleft()
        return True

    def has_fresh_reading(self, now: datetime) -> bool:
        """Never authorize an optional power change on missing/old data."""
        if not self._charging or not self._points or not _aware(now):
            return False
        last = self._points[-1]
        age = now - last.at
        return (timedelta(0) <= age <= FRESHNESS and
                last.house_kw is not None and last.total_kw is not None)

    def latest_trigger(self, now: datetime, alarm_kw: float) -> Point | None:
        """Return a fresh validated point at/over the *notification* threshold.

        This detects a candidate event, not a confirmed electrical overload.
        A future controller will own cooldown and command confirmation.
        """
        if not self._charging or not self._points or not _aware(now) or not _valid(alarm_kw, positive=True):
            return None
        point = self._points[-1]
        age = now - point.at
        if not timedelta(0) <= age <= FRESHNESS:
            return None
        if point.house_kw is None or point.total_kw is None:
            return None
        return point if point.total_kw >= alarm_kw else None

    def assess_rise(
        self, now: datetime, *, current_limit_kw: float,
        original_limit_kw: float, available_kw: float,
        margin_kw: float = 0.2, step_kw: float = 0.2,
        increment_kw: float = 0.4,
    ) -> RiseAssessment:
        """Propose at most one step, based on the WHOLE 5-minute window.

        The caller additionally enforces min time since last confirmed change,
        departure slack, manual ownership and anti-oscillation before acting.
        """
        if not self._charging:
            return RiseAssessment("inactive", "not_charging")
        if not _aware(now):
            return RiseAssessment("insufficient_data", "invalid_time")
        if not all(_valid(v, positive=True) for v in (
            current_limit_kw, original_limit_kw, available_kw,
            step_kw, increment_kw,
        )) or not _valid(margin_kw):
            return RiseAssessment("insufficient_data", "invalid_parameters")
        if not self._points:
            return RiseAssessment("insufficient_data", "empty_window")

        last = self._points[-1]
        if last.at > now or now - last.at > FRESHNESS:
            return RiseAssessment("insufficient_data", "stale_source")

        start = now - WINDOW
        # The sample at/before the boundary is the value held at window start.
        before = None
        within = []
        for point in self._points:
            if point.at <= start:
                before = point
            elif point.at <= now:
                within.append(point)
        if before is None or start - before.at > MAX_GAP:
            return RiseAssessment("insufficient_data", "window_not_covered")

        covered = [before, *within]
        if any(b.at - a.at > MAX_GAP for a, b in zip(covered, covered[1:])):
            return RiseAssessment("insufficient_data", "gap_in_window", samples=len(covered))
        if any(point.house_kw is None for point in covered):
            return RiseAssessment("insufficient_data", "incoherent_house", samples=len(covered))

        peak_house = max(point.house_kw for point in covered)
        safe = _floor_step(available_kw - peak_house - margin_kw, step_kw)
        next_cap = _floor_step(
            min(original_limit_kw, safe, current_limit_kw + increment_kw), step_kw
        )
        if next_cap <= current_limit_kw + 1e-8:
            return RiseAssessment("hold", "insufficient_headroom", peak_house,
                                  safe, None, len(covered))
        return RiseAssessment("raise", "window_allows_one_step", peak_house,
                              safe, next_cap, len(covered))
