"""Johnny v1: slow dynamic-DPM supervisor, SIMULATION ONLY.

Pure deterministic reducer. One virtual cap per household episode, no ramp,
no BLE, no HA services, no file/storage IO. Physical DPM remains independent.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import floor, isfinite

from .core import Config, HouseSnapshot, LimitSnapshot, Plan, Proposal, SessionSnapshot, plan


def _valid(value, *, positive=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and isfinite(value) and (value > 0 if positive else value >= 0))


def _aware(t):
    return isinstance(t, datetime) and t.tzinfo is not None and t.utcoffset() is not None


def margin_band(p: Plan) -> str:
    """Three bands calculated from reachable SOC, departure and measured rate."""
    if p.reason != "flexible" or p.slack_minutes is None:
        return "urgent" if p.reason in ("at_risk", "target_reached") else "unknown"
    if p.slack_minutes > 120:
        return "wide"
    if p.slack_minutes > 45:
        return "medium"
    return "urgent"


@dataclass(frozen=True)
class JohnnyState:
    session_id: str | None = None
    mode: str = "NORMAL"
    cap_kw: float | None = None
    original_kw: float | None = None
    baseline_requested_kw: float | None = None
    baseline_confirmed_kw: float | None = None
    baseline_dpm_kw: float | None = None
    candidate_since: datetime | None = None
    last_evidence_at: datetime | None = None
    quiet_since: datetime | None = None
    cooldown_until: datetime | None = None
    cap_started_at: datetime | None = None
    last_at: datetime | None = None
    last_sample_at: datetime | None = None
    # Time of the last genuinely trusted household report, never an HA timer.
    last_good_house_at: datetime | None = None
    # Diagnostic history: only virtual, not a confirmed hardware transition.
    last_transition_reason: str | None = None
    last_transition_at: datetime | None = None
    # Last 3 minutes of independent household reports, for a robust high
    # percentile. No smoothing of the DPM itself or frequent write proposals.
    recent_loads: tuple[tuple[datetime, float], ...] = ()
    # Rolling entry memory: only intervals bounded by fresh independent
    # source reports, never assumed power during a missing-data gap.
    entry_last_at: datetime | None = None
    entry_last_busy: bool = False
    entry_last_pressure_kw: float = 0.0
    entry_busy_intervals: tuple[tuple[datetime, datetime, float], ...] = ()
    entry_burst_starts: tuple[datetime, ...] = ()
    spent_kwh_upper_bound: float = 0.0
    locked_budget_kwh: float | None = None


def _initial(session_id, now):
    return JohnnyState(session_id=session_id, last_at=now)


def _proposal(state, action, reason, p, due=None):
    if action in ("reduce", "restore", "retire"):
        state = replace(state, last_transition_reason=reason,
                        last_transition_at=state.last_at)
    return state, Proposal(
        action, state.mode, state.cap_kw, reason,
        state.locked_budget_kwh if state.locked_budget_kwh is not None
        else p.discretionary_budget_kwh,
        state.spent_kwh_upper_bound, p.slack_minutes,
        due,
    )


# The missing-data timeout is longer than one Shelly reporting gap; it is
# evaluated from the last trusted report, NOT from the first timer callback.
HOUSE_LOSS_RESTORE_MINUTES = 8
ENTRY_MEMORY_MINUTES = 5
ENTRY_SAMPLE_GAP_SECONDS = 150
ENTRY_BUSY_SECONDS = 120
ENTRY_PRESSURE_AREA = {"wide": 2.4, "medium": 3.2}  # kW × min


def _restored(st, now, cooldown_minutes):
    # Keep spent and initial budget for the entire physical EV session.
    return replace(
        st, mode="NORMAL", cap_kw=st.original_kw,
        candidate_since=None, last_evidence_at=None, quiet_since=None,
        cap_started_at=None,
        cooldown_until=now + timedelta(minutes=cooldown_minutes),
        recent_loads=(),
        entry_last_at=None, entry_last_busy=False,
        entry_last_pressure_kw=0.0,
        entry_busy_intervals=(), entry_burst_starts=(),
    )


def _clear_entry_memory(st: JohnnyState) -> JohnnyState:
    return replace(st, entry_last_at=None, entry_last_busy=False,
                   entry_last_pressure_kw=0.0,
                   entry_busy_intervals=(), entry_burst_starts=(),
                   candidate_since=None, last_evidence_at=None,
                   recent_loads=())


def _observe_entry_memory(st: JohnnyState, at: datetime,
                          pressure: float, trigger: float,
                          house_kw: float) -> tuple[JohnnyState, bool]:
    """Count only independent reports and bounded observed intervals.

    Previous busy power is assigned only between consecutive fresh reports
    <=150s apart. With missing input, the memory is reset, not extrapolated.
    """
    if st.entry_last_at is not None and at <= st.entry_last_at:
        return st, False
    cutoff = at - timedelta(minutes=ENTRY_MEMORY_MINUTES)
    intervals = list(st.entry_busy_intervals)
    bursts = list(st.entry_burst_starts)
    preceding = st.entry_last_at
    gap = (at-preceding).total_seconds() if preceding is not None else None
    if gap is not None and gap > ENTRY_SAMPLE_GAP_SECONDS:
        intervals, bursts = [], []
    elif gap is not None and st.entry_last_busy:
        intervals.append((preceding, at, st.entry_last_pressure_kw))
    intervals = [(max(a, cutoff), z, p) for a, z, p in intervals
                 if z > cutoff]
    bursts = [t for t in bursts if t >= cutoff]
    busy = pressure >= trigger
    if busy and (not st.entry_last_busy or gap is None
                 or gap > ENTRY_SAMPLE_GAP_SECONDS):
        bursts.append(at)
    high = tuple((t, v) for t, v in st.recent_loads
                 if timedelta(0) <= at-t <= timedelta(minutes=3))
    if busy:
        high += ((at, house_kw),)
    return replace(st, entry_last_at=at, entry_last_busy=busy,
                   entry_last_pressure_kw=pressure,
                   entry_busy_intervals=tuple(intervals),
                   entry_burst_starts=tuple(bursts),
                   recent_loads=high), True


def _entry_memory_ready(st: JohnnyState, at: datetime, band: str) -> bool:
    cutoff = at - timedelta(minutes=ENTRY_MEMORY_MINUTES)
    seconds = 0.0
    pressure_area = 0.0
    for start, end, pressure in st.entry_busy_intervals:
        elapsed = max(0.0, (end-max(start, cutoff)).total_seconds())
        seconds += elapsed
        pressure_area += pressure * elapsed / 60.0
    bursts = sum(x >= cutoff for x in st.entry_burst_starts)
    return (st.entry_last_busy and seconds >= ENTRY_BUSY_SECONDS
            and bursts >= 2 and pressure_area >= ENTRY_PRESSURE_AREA[band])


def evaluate(now: datetime, session: SessionSnapshot, house: HouseSnapshot,
             limits: LimitSnapshot, previous: JohnnyState | None = None,
             cfg: Config = Config()):
    """Decide one slow *virtual* cap; NEVER issue a device command.

    A fresh house report must have a new timestamp for entry confirmation;
    timer callbacks alone cannot turn a single transient into a reduce.
    Config values are experiment choices and not electrical safety limits.
    """
    if not _aware(now):
        raise ValueError("timezone-aware evaluation required")
    p = plan(now, session, cfg)
    band = margin_band(p)
    st = previous or _initial(session.session_id, now)
    if st.last_at is not None and now < st.last_at:
        return _proposal(st, "insufficient_data", "non_monotonic_clock", p)
    if st.session_id != session.session_id:
        # A cap proposed to an old EV session never belongs to a new one.
        if st.mode == "LIMITED":
            return _proposal(_initial(session.session_id, now), "retire",
                             "session_changed_requires_reconciliation", p)
        st = _initial(session.session_id, now)

    if st.mode == "LIMITED" and st.last_at is not None:
        cost_kw = max(0.0, (st.original_kw or 0) - (st.cap_kw or 0))
        st = replace(st, spent_kwh_upper_bound=st.spent_kwh_upper_bound
                     + cost_kw * (now - st.last_at).total_seconds() / 3600)
    st = replace(st, last_at=now)

    trustworthy_limit = (
        not limits.manual_owner
        and _valid(limits.requested_kw, positive=True)
        and _valid(limits.confirmed_kw, positive=True)
        and _valid(limits.dpm_kw, positive=True)
    )
    same_limit_owner = (
        trustworthy_limit and st.mode == "LIMITED"
        and abs(limits.requested_kw - st.baseline_requested_kw) <= .11
        and abs(limits.confirmed_kw - st.baseline_confirmed_kw) <= .11
        and abs(limits.dpm_kw - st.baseline_dpm_kw) <= .11
    )

    if st.mode == "LIMITED":
        # Explicit user modes, ambiguity and a new/unknown connection must
        # NEVER produce an automatic restore proposal for an old virtual cap.
        if (session.mode not in ("AUTO", "CHARGE_NOW")
                or not session.vehicle_id or session.vehicle_ambiguous):
            return _proposal(_initial(session.session_id, now), "retire",
                             "virtual_cap_requires_reconciliation", p)
        if not session.charging or session.mode == "CHARGE_NOW":
            if (not same_limit_owner or
                    (not session.charging and
                     (session.wallbox_reports_charging is not False
                      or session.wallbox_telemetry_fresh is not True))):
                return _proposal(_initial(session.session_id, now), "retire",
                                 "end_or_intent_unverified_requires_reconciliation", p)
            # A virtual cap is not an applied BLE setting. This is an
            # explicit *proposal*, with original limit and reason visible.
            restored = _restored(st, now, cfg.cooldown_minutes)
            why = ("charge_now_restore_proposed" if session.mode == "CHARGE_NOW"
                   else "target_reached_restore_proposed" if p.reason == "target_reached"
                   else "charging_stopped_restore_proposed")
            return _proposal(restored, "restore", why, p)

    if (session.mode != "AUTO" or not session.charging or
            not session.vehicle_id or session.vehicle_ambiguous):
        # In simulation the limit was never applied, but preserve the
        # explanation of its last virtual release while the session stays
        # identified. A new session discards the history.
        idle = replace(_initial(session.session_id, now),
                       last_transition_reason=st.last_transition_reason,
                       last_transition_at=st.last_transition_at)
        return _proposal(idle, "inactive",
                         "not_auto_or_no_confirmed_charge", p)

    if not trustworthy_limit:
        if st.mode == "LIMITED":
            why = ("dpm_zero_requires_reconciliation"
                   if limits.dpm_kw == 0 else "ownership_or_limits_lost")
            return _proposal(_initial(session.session_id, now), "retire", why, p)
        reason = ("dpm_zero_paused_or_unresolved" if limits.dpm_kw == 0
                  else "dpm_limit_unavailable"
                  if not _valid(limits.dpm_kw, positive=True)
                  and not limits.manual_owner
                  and _valid(limits.requested_kw, positive=True)
                  and _valid(limits.confirmed_kw, positive=True)
                  else "invalid_or_manual_limit")
        return _proposal(st, "insufficient_data", reason, p)

    # The selected DPM source, if present, must be fresh and valid.
    dpm = limits.dpm_kw
    if not _valid(dpm, positive=True):
        if st.mode == "LIMITED" and band in ("urgent", "unknown"):
            return _proposal(_restored(st, now, 10), "restore",
                             "planner_needs_full_power", p)
        return _proposal(st, "insufficient_data", "dpm_limit_unavailable", p)

    if st.mode == "LIMITED":
        if (abs(limits.requested_kw - st.baseline_requested_kw) > .11 or
                abs(limits.confirmed_kw - st.baseline_confirmed_kw) > .11 or
                abs(dpm - st.baseline_dpm_kw) > .11):
            return _proposal(_initial(session.session_id, now), "retire",
                             "external_limit_changed", p)
    elif abs(limits.requested_kw - limits.confirmed_kw) > .11:
        return _proposal(replace(st, candidate_since=None, last_evidence_at=None),
                         "insufficient_data", "limit_unconfirmed", p)

    value = house.kw
    observed = house.observed_at
    good_report = (
        value is not None and _aware(observed)
        and timedelta(0) <= now - observed <= timedelta(minutes=3)
    )
    # No synthetic fresh report on a timer callback. For pure replay every
    # sample must carry its own time, as the HA adapter already does.
    if not good_report:
        value = None
    elif (st.last_good_house_at is None
          or observed > st.last_good_house_at):
        st = replace(st, last_good_house_at=observed)

    # Pressure on the *physical DPM* before our optional virtual cap.
    pressure = max(0., value + limits.confirmed_kw - dpm) if value is not None else None
    if st.mode == "LIMITED":
        if band not in ("wide", "medium"):
            why = ("target_reached_restore_proposed" if p.reason == "target_reached"
                   else "planner_needs_full_power")
            return _proposal(_restored(st, now, cfg.cooldown_minutes),
                             "restore", why, p)
        if (st.locked_budget_kwh is not None
                and st.spent_kwh_upper_bound >= st.locked_budget_kwh):
            return _proposal(_restored(st, now, 10), "restore",
                             "session_budget_exhausted", p)

        if pressure is None:
            # Missing telemetry is not a quiet house. After a sustained
            # outage, release ONLY the virtual optional cap; the physical
            # DPM keeps protecting the circuit. In later control phases an
            # executor will still need ownership + BLE confirmation.
            if (st.last_good_house_at is not None
                    and now - st.last_good_house_at >= timedelta(
                        minutes=HOUSE_LOSS_RESTORE_MINUTES
                    )):
                return _proposal(_restored(st, now, cfg.cooldown_minutes),
                                 "restore", "house_telemetry_timeout_restore_proposed", p)
            due = (st.last_good_house_at + timedelta(
                minutes=HOUSE_LOSS_RESTORE_MINUTES
            ) if st.last_good_house_at is not None else None)
            return _proposal(replace(st, quiet_since=None), "insufficient_data",
                             "house_data_not_trusted", p, due)

        # The house is quiet only when the original EV limit would create
        # almost no DPM pressure. Small thermostat breaks are not enough.
        if pressure > .4:
            return _proposal(replace(st, quiet_since=None), "hold",
                             "house_episode_continues", p)
        start = st.quiet_since or now
        st = replace(st, quiet_since=start)
        quiet_minutes = 15 if band == "wide" else 10
        due = start + timedelta(minutes=quiet_minutes)
        if now >= due:
            return _proposal(_restored(st, now, 10), "restore",
                             "documented_quiet", p)
        return _proposal(st, "hold", "waiting_for_sustained_quiet", p, due)

    st = replace(st, cap_kw=limits.confirmed_kw, original_kw=limits.confirmed_kw)
    if band not in ("wide", "medium"):
        return _proposal(replace(st, candidate_since=None, last_evidence_at=None),
                         "hold", "no_safe_charge_margin", p)
    if pressure is None:
        return _proposal(_clear_entry_memory(st),
                         "insufficient_data", "house_data_not_trusted", p)
    if st.cooldown_until is not None and now < st.cooldown_until:
        return _proposal(_clear_entry_memory(st),
                         "hold", "cooldown", p, st.cooldown_until)

    trigger = .6 if band == "wide" else .8
    confirm_secs = 120 if band == "wide" else 180
    st, distinct = _observe_entry_memory(st, observed, pressure, trigger, value)
    busy = pressure >= trigger

    if not busy:
        # Stop the continuous timer, not the five-minute memory.
        st = replace(st, candidate_since=None, last_evidence_at=None)
        reason = ("remembering_intermittent_load"
                  if st.entry_burst_starts else "dpm_pressure_not_significant")
        return _proposal(st, "hold", reason, p)
    if not distinct:
        return _proposal(st, "hold", "waiting_for_new_house_sample", p)

    if (st.candidate_since is None or st.last_evidence_at is None
            or observed - st.last_evidence_at > timedelta(
                seconds=ENTRY_SAMPLE_GAP_SECONDS
            )):
        st = replace(st, candidate_since=observed)
    st = replace(st, last_evidence_at=observed)
    continuous = (st.candidate_since is not None and
                  observed >= st.candidate_since + timedelta(seconds=confirm_secs))
    rolling = _entry_memory_ready(st, observed, band)
    if not (continuous or rolling):
        return _proposal(st, "hold", "accumulating_load_evidence", p)

    # Busy, genuinely new samples only; quiet/off values do not dilute cap.
    # Retain the original 75th-percentile style for a stable single cap.
    loads = sorted(x for _, x in st.recent_loads)
    if not loads:
        return _proposal(st, "hold", "no_busy_level_for_cap", p)
    basis = loads[(3*(len(loads)-1)) // 4]
    margin = .2 if band == "wide" else .1
    raw_cap = floor((dpm - basis - margin + 1e-9) / .2) * .2
    # A strong household load must not make Johnny give up. Cap at the
    # *minimum useful EV setting*, leaving any further reduction to DPM.
    cap = round(max(cfg.min_cap_kw, raw_cap), 6)
    if limits.confirmed_kw - cap < cfg.minimum_useful_reduction_kw - 1e-8:
        return _proposal(_clear_entry_memory(st), "hold",
                         "no_useful_cap_dpm_handles_peaks", p)

    # Energy upper bound: assume DPM was not limiting and lose the full
    # difference for every minute of a cap, even across missing telemetry.
    fraction = .25 if band == "wide" else .10
    budget = max(0., p.slack_minutes / 60 * session.sustainable_kw * fraction)
    locked = st.locked_budget_kwh if st.locked_budget_kwh is not None else budget
    minimum_episode = 15 if band == "wide" else 10
    cost_bound = (limits.confirmed_kw - cap) * minimum_episode / 60
    if st.spent_kwh_upper_bound + cost_bound > locked:
        return _proposal(_clear_entry_memory(st), "hold",
                         "insufficient_episode_budget", p)

    st = replace(st, mode="LIMITED", cap_kw=cap,
                 baseline_requested_kw=limits.requested_kw,
                 baseline_confirmed_kw=limits.confirmed_kw,
                 baseline_dpm_kw=dpm, locked_budget_kwh=locked,
                 candidate_since=None, last_evidence_at=None,
                 quiet_since=None, cap_started_at=now, recent_loads=(),
                 entry_last_at=None, entry_last_busy=False,
                 entry_last_pressure_kw=0.0,
                 entry_busy_intervals=(), entry_burst_starts=())
    return _proposal(st, "reduce", "dynamic_stable_episode_cap", p)
