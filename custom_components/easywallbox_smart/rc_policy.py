"""RC charging stabilizer: pure, bounded and deterministic EV limit decisions.

This module is an advisory algorithm, NOT an electrical safety controller.
It never accesses HA, BLE, storage, hardware, or services.
All pressure figures are nominal-kW approximations of firmware amperes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import floor, isfinite

BASE_KW = 4.0
BOOST_KW = 4.2
MIN_KW = 1.4
STEP_KW = 0.2
STRONG_PRESSURE = 0.6
ADJUST_PRESSURE = 0.25
MODERATE_PRESSURE = 0.1
MAX_GAP = timedelta(seconds=150)
WINDOW = timedelta(minutes=17)


def valid(value: float | None) -> bool:
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and isfinite(value) and value >= 0)


def step_down(value: float) -> float:
    return round(floor((value + 1e-8) / STEP_KW) * STEP_KW, 1)


@dataclass(frozen=True)
class Observation:
    at: datetime
    session_id: str
    connected: bool
    charging: bool
    auto: bool
    trusted: bool
    house_kw: float | None
    house_at: datetime | None
    dpm_kw: float | None
    current_kw: float | None
    margin_minutes: float | None
    remaining_budget_kwh: float | None
    max_kw: float = BASE_KW
    boost_max_kw: float = BOOST_KW


@dataclass(frozen=True)
class State:
    session_id: str = ""
    phase: str = "NORMAL"
    cap_kw: float = BASE_KW
    baseline_kw: float = BASE_KW
    kind: str = "normal"
    last_change: datetime | None = None
    last_sample: datetime | None = None
    last_busy: datetime | None = None
    strong_since: datetime | None = None
    moderate_since: datetime | None = None
    quiet_since: datetime | None = None
    boost_since: datetime | None = None
    boost_margin_since: datetime | None = None
    cooldown_until: datetime | None = None
    observations: tuple[tuple[datetime, float, float], ...] = ()
    recheck_count: int = 0
    spent_budget_kwh: float = 0.0
    evaluated_at: datetime | None = None


@dataclass(frozen=True)
class Decision:
    action: str
    target_kw: float | None
    reason: str
    phase: str
    kind: str
    simulation_only: bool = True


def _decision(st: State, action: str, reason: str, value=None):
    return st, Decision(action, value, reason, st.phase, st.kind)


def _shift(st: State, now: datetime, cap: float, kind: str, why: str):
    phase = ("LIMITED" if cap < st.baseline_kw - .11 else
             "BOOST" if cap > st.baseline_kw + .11 else "NORMAL")
    st = replace(st, phase=phase, kind=kind, cap_kw=cap,
                 last_change=now, quiet_since=None, strong_since=None,
                 moderate_since=None, boost_since=None,
                 boost_margin_since=None, last_busy=None,
                 observations=(), recheck_count=(st.recheck_count + 1 if kind == "adjust" else 0),
                 cooldown_until=now + timedelta(minutes=10) if kind in ("normal", "restore") else st.cooldown_until)
    return _decision(st, "set_limit", why, cap)


def _seconds_covered(items, now, predicate, interval_minutes, *, tolerance_seconds=150):
    """Count *observed* intervals, never fill missing Shelly reports as quiet."""
    cutoff = now - timedelta(minutes=interval_minutes)
    total = 0.0
    for (t0, value0, pressure0), (t1, _, _) in zip(items, items[1:]):
        if t1 <= t0 or (t1-t0).total_seconds() > tolerance_seconds or t1 <= cutoff:
            continue
        if predicate(value0, pressure0):
            total += (t1-max(t0, cutoff)).total_seconds()
    return total


def strong_p75_cap(items, now, *, dpm_kw: float, base_kw: float) -> float:
    """Discrete 75th percentile of HIGH reports in the latest 3 minutes.

    Use the observed high-load history rather than a single instant at the
    triggering timestamp. Output is a nominal kW UI setpoint.
    """
    candidates = sorted(
        h for t, h, _ in items
        if t >= now-timedelta(minutes=3)
        and max(0.0, h+base_kw-dpm_kw) >= STRONG_PRESSURE
    )
    if not candidates:
        return base_kw
    index = max(0, (3*len(candidates)+3)//4-1)
    high_p75 = candidates[index]
    return max(MIN_KW, step_down(dpm_kw-high_p75-.2))


def intermittent_pressure_area(items, now, base_kw, dpm_kw):
    """Observed kW*minutes above the strong entry threshold, no gap fill."""
    area = 0.0
    cutoff = now-timedelta(minutes=5)
    for (at, house, _), (end, _, _) in zip(items, items[1:]):
        dt = (end-at).total_seconds()
        if dt <= 0 or dt > MAX_GAP.total_seconds() or end <= cutoff:
            continue
        pressure = max(0.0, house+base_kw-dpm_kw)
        if pressure >= STRONG_PRESSURE:
            area += pressure*(end-max(at,cutoff)).total_seconds()/60
    return area


def evaluate(o: Observation, previous: State | None = None):
    """Proposal for one *observed charging* session, never direct actuation.

    Timers may request evaluation, but never manufacture a fresh house report.
    An unexpected change of session resets all remembered budgets and loads.
    """
    st = (previous if previous and previous.session_id == o.session_id else
          State(session_id=o.session_id, cap_kw=o.max_kw,
                baseline_kw=o.max_kw))
    if not (o.auto and o.connected and o.charging and o.trusted and
            valid(o.house_kw) and valid(o.dpm_kw) and o.dpm_kw >= 1.4 and
            valid(o.current_kw) and o.current_kw >= MIN_KW and
            valid(o.max_kw) and 1.4 <= o.max_kw <= 6.0 and
            valid(o.boost_max_kw) and o.max_kw <= o.boost_max_kw <= 6.0 and
            isinstance(o.at, datetime) and o.at.tzinfo is not None and
            isinstance(o.house_at, datetime) and o.house_at.tzinfo is not None and
            timedelta(0) <= o.at-o.house_at <= timedelta(minutes=3)):
        return _decision(st, "none", "invalid_session_or_source")
    if st.evaluated_at and o.at < st.evaluated_at:
        return _decision(st, "none", "non_monotonic_time")
    if st.evaluated_at and st.phase == "LIMITED" and st.last_change:
        hours = min(max(0, (o.at-st.evaluated_at).total_seconds()) / 3600, 24)
        st = replace(st, spent_budget_kwh=st.spent_budget_kwh +
                     max(0, o.max_kw-st.cap_kw)*hours)
    st = replace(st, evaluated_at=o.at)
    if o.house_at == st.last_sample:
        return _decision(st, "none", "waiting_for_new_shelly_report")
    if st.last_sample and (o.house_at < st.last_sample or
                          o.house_at-st.last_sample > MAX_GAP):
        st = replace(st, observations=(), strong_since=None,
                     moderate_since=None, quiet_since=None, boost_since=None,
                     boost_margin_since=None)
    st = replace(st, last_sample=o.house_at)

    # Nothing discretionary if a real session has insufficient remaining time.
    urgent = o.margin_minutes is None or not isfinite(o.margin_minutes) or o.margin_minutes <= 45
    budget = (o.remaining_budget_kwh if valid(o.remaining_budget_kwh) else 0)
    pressure_baseline = max(0.0, o.house_kw+o.max_kw-o.dpm_kw)
    pressure_current = max(0.0, o.house_kw+o.current_kw-o.dpm_kw)
    items = tuple((t, h, p) for t, h, p in st.observations if o.house_at-t <= WINDOW)
    items += ((o.house_at, o.house_kw, pressure_current),)
    st = replace(st, observations=items)

    if st.phase == "LIMITED":
        if abs(o.current_kw-st.cap_kw) > .11:
            return _decision(st, "none", "limit_changed_externally_reconcile")
        if urgent or st.spent_budget_kwh >= budget:
            return _shift(st, o.at, o.max_kw, "restore", "departure_or_budget_priority")
        # Full original cap is available with nonnegative headroom for 15 documented min.
        quiet = o.dpm_kw-o.house_kw-o.max_kw >= -0.02
        if quiet and st.last_change and o.at-st.last_change >= timedelta(minutes=15):
            if _seconds_covered(items, o.house_at,
                                lambda h, p: o.dpm_kw-h-o.max_kw >= -0.02,
                                15) >= 15*60-1:
                return _shift(st, o.at, o.max_kw, "restore", "fifteen_minutes_headroom")
        if st.last_change and o.at-st.last_change >= timedelta(minutes=10):
            elapsed = _seconds_covered(items, o.house_at,
                                       lambda h, p: p >= ADJUST_PRESSURE, 7)
            if pressure_current >= ADJUST_PRESSURE and elapsed >= 300 and st.recheck_count < 2:
                target = max(MIN_KW, round(st.cap_kw-0.4, 1))
                if st.cap_kw-target >= 0.39 and budget-st.spent_budget_kwh >= (
                        st.cap_kw-target)*.25:
                    return _shift(st, o.at, target, "adjust", "persistent_pressure_5_of_7")
        return _decision(st, "none", "limited_holding")

    # Never change limit to correct a manual external value. The real
    # controller must establish session ownership before calling here.
    if abs(o.current_kw - st.cap_kw) > .11 and st.last_change is not None:
        return _decision(st, "none", "limit_changed_externally_reconcile")

    if st.phase == "BOOST":
        if urgent is False and o.margin_minutes >= 75:
            if st.boost_margin_since is None:
                st = replace(st, boost_margin_since=o.house_at)
            if o.house_at-st.boost_margin_since >= timedelta(minutes=5):
                return _shift(st, o.at, o.max_kw, "normal", "boost_slack_recovered")
        else:
            st = replace(st, boost_margin_since=None)
        if o.house_kw > 0.2:
            return _shift(st, o.at, o.max_kw, "normal", "boost_house_exceeds_200w")
        return _decision(st, "none", "boost_holding")

    if st.cooldown_until and o.at < st.cooldown_until:
        return _decision(st, "none", "post_change_cooldown")

    if not urgent and pressure_baseline >= STRONG_PRESSURE:
        since = st.strong_since or o.house_at
        st = replace(st, strong_since=since)
        # Continuous evidence, or two bursts with >=120 observed busy seconds.
        continuous = o.house_at-since >= timedelta(minutes=2)
        busy_seconds = _seconds_covered(items, o.house_at,
                                       lambda h, p: max(0,h+o.max_kw-o.dpm_kw) >= STRONG_PRESSURE, 5)
        transitions = sum(
            max(0,h+o.max_kw-o.dpm_kw) >= STRONG_PRESSURE and
            (idx == 0 or max(0,items[idx-1][1]+o.max_kw-o.dpm_kw) < STRONG_PRESSURE)
            for idx, (t,h,p) in enumerate(items))
        intermittent = (transitions >= 2 and busy_seconds >= 120
                        and intermittent_pressure_area(
                            items, o.house_at, o.max_kw, o.dpm_kw) >= 2.4)
        if continuous or intermittent:
            target = strong_p75_cap(items, o.house_at,
                                    dpm_kw=o.dpm_kw, base_kw=o.max_kw)
            if o.max_kw-target >= .4 and budget-st.spent_budget_kwh >= (o.max_kw-target)*.25:
                return _shift(st, o.at, target, "strong", "strong_confirmed")
        return _decision(st, "none", "strong_accumulating")
    st = replace(st, strong_since=None)

    # Moderate: 10 observed minutes over the latest 12 and still relevant now.
    moderate = .45 <= o.house_kw <= 1.1 and pressure_baseline >= MODERATE_PRESSURE
    if not urgent and moderate:
        seconds = _seconds_covered(items, o.house_at,
                                   lambda h,p: .45 <= h <= 1.1 and
                                   max(0,h+o.max_kw-o.dpm_kw) >= MODERATE_PRESSURE, 12)
        if seconds >= 600:
            target = round(max(MIN_KW, o.max_kw-.4), 1)
            if o.max_kw-target >= .39 and budget-st.spent_budget_kwh >= .1:
                return _shift(st, o.at, target, "moderate", "moderate_ten_of_twelve")
    # Boost only when the planner is close to deadline, not when ample slack.
    if (o.margin_minutes is not None and isfinite(o.margin_minutes)
            and o.margin_minutes <= 60 and o.house_kw < .15
            and st.phase == "NORMAL"):
        if st.boost_since is None:
            st = replace(st, boost_since=o.house_at)
        if o.house_at - st.boost_since >= timedelta(minutes=15) and o.boost_max_kw > o.max_kw:
            return _shift(st, o.at, o.boost_max_kw, "boost", "boost_sixty_minutes_slack")
    else:
        st = replace(st, boost_since=None)
    return _decision(st, "none", "normal_monitoring")
