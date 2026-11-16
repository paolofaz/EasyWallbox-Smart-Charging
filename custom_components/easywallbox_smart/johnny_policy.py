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
    # Last 3 minutes of independent household reports, for a robust high
    # percentile. No smoothing of the DPM itself or frequent write proposals.
    recent_loads: tuple[tuple[datetime, float], ...] = ()
    spent_kwh_upper_bound: float = 0.0
    locked_budget_kwh: float | None = None


def _initial(session_id, now):
    return JohnnyState(session_id=session_id, last_at=now)


def _proposal(state, action, reason, p, due=None):
    return state, Proposal(
        action, state.mode, state.cap_kw, reason,
        state.locked_budget_kwh if state.locked_budget_kwh is not None
        else p.discretionary_budget_kwh,
        state.spent_kwh_upper_bound, p.slack_minutes,
        due,
    )


def _restored(st, now, cooldown_minutes):
    # Keep spent and initial budget for the entire physical EV session.
    return replace(
        st, mode="NORMAL", cap_kw=st.original_kw,
        candidate_since=None, last_evidence_at=None, quiet_since=None,
        cap_started_at=None,
        cooldown_until=now + timedelta(minutes=cooldown_minutes),
        recent_loads=(),
    )


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
    if st.session_id != session.session_id:
        st = _initial(session.session_id, now)
    if st.last_at is not None and now < st.last_at:
        return _proposal(st, "insufficient_data", "non_monotonic_clock", p)

    if st.mode == "LIMITED" and st.last_at is not None:
        cost_kw = max(0.0, (st.original_kw or 0) - (st.cap_kw or 0))
        st = replace(st, spent_kwh_upper_bound=st.spent_kwh_upper_bound
                     + cost_kw * (now - st.last_at).total_seconds() / 3600)
    st = replace(st, last_at=now)

    if (session.mode != "AUTO" or not session.charging or
            not session.vehicle_id or session.vehicle_ambiguous):
        return _proposal(_initial(session.session_id, now), "inactive",
                         "not_auto_or_no_confirmed_charge", p)

    if (limits.manual_owner or not _valid(limits.requested_kw, positive=True)
            or not _valid(limits.confirmed_kw, positive=True)):
        if st.mode == "LIMITED":
            return _proposal(_initial(session.session_id, now), "retire",
                             "ownership_or_limits_lost", p)
        return _proposal(st, "insufficient_data", "invalid_or_manual_limit", p)

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

    # Pressure on the *physical DPM* before our optional virtual cap.
    pressure = max(0., value + limits.confirmed_kw - dpm) if value is not None else None
    if st.mode == "LIMITED":
        if band not in ("wide", "medium"):
            return _proposal(_restored(st, now, 10), "restore",
                             "planner_needs_full_power", p)
        if (st.locked_budget_kwh is not None
                and st.spent_kwh_upper_bound >= st.locked_budget_kwh):
            return _proposal(_restored(st, now, 10), "restore",
                             "session_budget_exhausted", p)

        if pressure is None:
            return _proposal(replace(st, quiet_since=None), "insufficient_data",
                             "house_data_not_trusted", p)

        # The house is quiet only when the original EV limit would create
        # almost no DPM pressure. Small thermostat breaks are not enough.
        if pressure > .4:
            return _proposal(replace(st, quiet_since=None), "hold",
                             "house_episode_continues", p)
        start = st.quiet_since or now
        st = replace(st, quiet_since=start)
        quiet_minutes = 18 if band == "wide" else 8
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
        return _proposal(replace(st, candidate_since=None, last_evidence_at=None),
                         "insufficient_data", "house_data_not_trusted", p)
    if st.cooldown_until is not None and now < st.cooldown_until:
        return _proposal(replace(st, candidate_since=None, last_evidence_at=None),
                         "hold", "cooldown", p, st.cooldown_until)

    trigger = .6 if band == "wide" else .8
    confirm_secs = 120 if band == "wide" else 180
    if pressure < trigger:
        return _proposal(replace(st, candidate_since=None, last_evidence_at=None,
                                 recent_loads=()), "hold",
                         "dpm_pressure_not_significant", p)

    # Prune old samples; an HA timer evaluating the same Shelly report must
    # NOT add another point of evidence.
    recent = tuple((t,v) for t,v in st.recent_loads
                   if timedelta(0) <= observed-t <= timedelta(minutes=3))
    distinct = st.last_evidence_at is None or observed > st.last_evidence_at
    if not distinct:
        return _proposal(st, "hold", "waiting_for_new_house_sample", p)
    if (st.candidate_since is None or st.last_evidence_at is None
            or observed-st.last_evidence_at > timedelta(seconds=150)):
        st = replace(st, candidate_since=observed, last_evidence_at=observed,
                     recent_loads=((observed, value),))
        return _proposal(st, "hold", "confirming_persistent_pressure", p)
    recent = (*recent, (observed, value))
    st = replace(st, last_evidence_at=observed, recent_loads=recent)
    due = st.candidate_since + timedelta(seconds=confirm_secs)
    if observed < due:
        return _proposal(st, "hold", "confirming_persistent_pressure", p)

    # Use an upper-quantile of recent confirmed loads, not just the last
    # low point or one unrepresentative peak: modest, episode-stable cap.
    loads = sorted(x for _,x in recent)
    basis = loads[(3*(len(loads)-1)) // 4]
    margin = .2 if band == "wide" else .1
    cap = floor((dpm - basis - margin + 1e-9) / .2) * .2
    cap = round(cap, 6)
    if (cap < cfg.min_cap_kw
            or limits.confirmed_kw - cap < cfg.minimum_useful_reduction_kw - 1e-8):
        return _proposal(replace(st, candidate_since=None, last_evidence_at=None,
                                 recent_loads=()), "hold",
                         "no_useful_cap_dpm_handles_peaks", p)

    # Energy upper bound: assume DPM was not limiting and lose the full
    # difference for every minute of a cap, even across missing telemetry.
    fraction = .25 if band == "wide" else .10
    budget = max(0., p.slack_minutes / 60 * session.sustainable_kw * fraction)
    locked = st.locked_budget_kwh if st.locked_budget_kwh is not None else budget
    minimum_episode = 18 if band == "wide" else 8
    cost_bound = (limits.confirmed_kw - cap) * minimum_episode / 60
    if st.spent_kwh_upper_bound + cost_bound > locked:
        return _proposal(replace(st, candidate_since=None, last_evidence_at=None),
                         "hold", "insufficient_episode_budget", p)

    st = replace(st, mode="LIMITED", cap_kw=cap,
                 baseline_requested_kw=limits.requested_kw,
                 baseline_confirmed_kw=limits.confirmed_kw,
                 baseline_dpm_kw=dpm, locked_budget_kwh=locked,
                 candidate_since=None, last_evidence_at=None,
                 quiet_since=None, cap_started_at=now, recent_loads=())
    return _proposal(st, "reduce", "dynamic_stable_episode_cap", p)
