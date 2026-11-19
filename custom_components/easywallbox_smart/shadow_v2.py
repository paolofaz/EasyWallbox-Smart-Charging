"""Johnny V2: third independent, read-only shadow candidate.

Uses the existing wide-band entry/quiet policy as a baseline, with a
moderate persistent-load buffer and a rare downward correction. Never sends
commands, writes storage, or assumes the physical wallbox followed a cap.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import floor

from .core import Config, HouseSnapshot, LimitSnapshot, SessionSnapshot
from .johnny_policy import JohnnyState, evaluate

BUFFER_MIN_KW = 0.5
BUFFER_MAX_KW = 1.1
BUFFER_CONFIRM = timedelta(minutes=3)
BUFFER_STEP_KW = 0.4
BUFFER_QUIET_KW = 0.35
BUFFER_QUIET = timedelta(minutes=10)
COOLDOWN = timedelta(minutes=10)
RECHECK_PRESSURE_KW = 0.25
RECHECK_CONFIRM = timedelta(minutes=5)
RECHECK_GAP = timedelta(minutes=10)
RECHECK_STEP_KW = 0.4
MAX_RECHECKS = 2
FRESH = timedelta(minutes=3)
MAX_GAP = timedelta(seconds=150)


@dataclass(frozen=True)
class V2State:
    base: JohnnyState | None = None
    mode: str = "NORMAL"
    kind: str = "normal"  # normal, buffer, strong
    cap_kw: float = 4.0
    original_kw: float = 4.0
    last_sample_at: datetime | None = None
    last_good_at: datetime | None = None
    buffer_since: datetime | None = None
    quiet_since: datetime | None = None
    recheck_since: datetime | None = None
    last_adjust_at: datetime | None = None
    recheck_count: int = 0
    cooldown_until: datetime | None = None
    last_transition_reason: str | None = None
    last_transition_at: datetime | None = None
    model_dpm_kw: float | None = None


@dataclass(frozen=True)
class V2Decision:
    action: str
    reason: str
    proposed_cap_kw: float


def _decision(st: V2State, action: str, reason: str, now: datetime):
    if action in ("reduce", "adjust", "restore"):
        st = replace(st, last_transition_reason=reason, last_transition_at=now)
    return st, V2Decision(action, reason, st.cap_kw)


def _normal(st: V2State, now: datetime, reason: str):
    return _decision(replace(
        st, mode="NORMAL", kind="normal", cap_kw=st.original_kw,
        buffer_since=None, quiet_since=None, recheck_since=None,
        recheck_count=0, last_adjust_at=None,
        cooldown_until=now + COOLDOWN,
    ), "restore", reason, now)


def evaluate_v2(now: datetime, session: SessionSnapshot,
                house: HouseSnapshot, dpm_kw: float, max_ev_kw: float,
                previous: V2State | None = None) -> tuple[V2State, V2Decision]:
    """Evaluate on *new* Shelly timestamps; timer callbacks don't confirm load.

    The inherited Johnny wide state has unlimited budget only when called
    from the explicitly synthetic, continuously charging shadow lab.
    """
    st = previous or V2State(cap_kw=max_ev_kw, original_kw=max_ev_kw,
                             model_dpm_kw=dpm_kw)
    if st.model_dpm_kw is not None and abs(st.model_dpm_kw-dpm_kw) > .11:
        # A changed DPM reference invalidates old evidence: virtual reset.
        st = V2State(cap_kw=max_ev_kw, original_kw=max_ev_kw,
                     model_dpm_kw=dpm_kw)
        reset_reason = "dpm_reference_changed"
    elif abs(st.original_kw-max_ev_kw) > .11:
        st = V2State(cap_kw=max_ev_kw, original_kw=max_ev_kw,
                     model_dpm_kw=dpm_kw)
        reset_reason = "ev_baseline_changed"
    else:
        reset_reason = None

    old_base = st.base or JohnnyState(
        session_id=session.session_id, locked_budget_kwh=1_000_000.0,
    )
    base, base_proposal = evaluate(
        now, session, house,
        LimitSnapshot(requested_kw=max_ev_kw, confirmed_kw=max_ev_kw,
                      dpm_kw=dpm_kw),
        old_base, Config(dpm_model_kw=dpm_kw),
    )
    st = replace(st, base=base)

    at = house.observed_at
    value = house.kw
    valid = (value is not None and at is not None and at.tzinfo is not None
             and timedelta(0) <= now-at <= FRESH)
    is_new = (valid and
              (st.last_sample_at is None or at > st.last_sample_at))
    gap = (at - st.last_sample_at if is_new and st.last_sample_at else None)
    if is_new:
        st = replace(st, last_sample_at=at, last_good_at=at)
    elif not valid:
        # After the wide base retires on prolonged data loss, release only
        # this hypothetical cap, never a physical charging setting.
        if st.kind == "strong" and base.mode != "LIMITED":
            return _normal(st, now, "strong_base_released_or_untrusted")
        if (st.kind == "buffer" and st.last_good_at is not None
                and now-st.last_good_at >= timedelta(minutes=8)):
            return _normal(st, now, "virtual_buffer_telemetry_timeout")
        return _decision(st, "insufficient_data", "house_data_not_trusted", now)

    if reset_reason:
        return _decision(st, "hold", reset_reason, now)

    if base.mode == "LIMITED":
        if st.kind != "strong":
            cap = min(st.cap_kw, base.cap_kw or max_ev_kw)
            st = replace(
                st, mode="LIMITED", kind="strong", cap_kw=cap,
                buffer_since=None, quiet_since=None, recheck_since=None,
                last_adjust_at=now, recheck_count=0,
            )
            return _decision(st, "reduce" if cap < max_ev_kw else "hold",
                             "strong_wide_entry", now)
        if not is_new:
            return _decision(st, "hold", "waiting_for_new_house_sample", now)
        pressure = max(0.0, value + st.cap_kw - dpm_kw)
        if gap is not None and gap > MAX_GAP:
            st = replace(st, recheck_since=None)
        if pressure < RECHECK_PRESSURE_KW:
            return _decision(replace(st, recheck_since=None), "hold",
                             "strong_cap_adequate", now)
        since = st.recheck_since or at
        st = replace(st, recheck_since=since)
        if (st.recheck_count >= MAX_RECHECKS
                or st.last_adjust_at is None
                or at-st.last_adjust_at < RECHECK_GAP
                or at-since < RECHECK_CONFIRM):
            return _decision(st, "hold", "strong_pressure_under_observation", now)
        cap = max(1.4, round(st.cap_kw-RECHECK_STEP_KW, 2))
        # Do not propose a non-useful step when already at floor.
        if st.cap_kw-cap < 0.19:
            return _decision(st, "hold", "strong_at_minimum_cap", now)
        st = replace(st, cap_kw=cap, last_adjust_at=at,
                     recheck_since=None, recheck_count=st.recheck_count+1)
        return _decision(st, "adjust", "strong_persistent_pressure_step", now)

    if st.kind == "strong":
        # The original wide policy owns end-of-episode quiet handling.
        return _normal(st, now, "strong_wide_"+base_proposal.reason)

    if not is_new:
        return _decision(st, "hold", "waiting_for_new_house_sample", now)

    if st.kind == "buffer":
        if gap is not None and gap > MAX_GAP:
            st = replace(st, quiet_since=None)
        if value > BUFFER_QUIET_KW:
            return _decision(replace(st, quiet_since=None), "hold",
                             "buffer_house_not_quiet", now)
        since = st.quiet_since or at
        st = replace(st, quiet_since=since)
        if at-since >= BUFFER_QUIET:
            return _normal(st, now, "buffer_documented_quiet")
        return _decision(st, "hold", "buffer_waiting_for_quiet", now)

    if st.cooldown_until is not None and now < st.cooldown_until:
        return _decision(replace(st, buffer_since=None), "hold",
                         "cooldown", now)
    # A small, persistent positive DPM pressure is the *only* buffer goal;
    # it is not a fast electrical safety margin for sudden oven loads.
    buffer_candidate = (
        BUFFER_MIN_KW <= value <= BUFFER_MAX_KW
        and value + max_ev_kw - dpm_kw >= 0.1
        and max_ev_kw - 1.4 >= BUFFER_STEP_KW-1e-8
    )
    if not buffer_candidate:
        return _decision(replace(st, buffer_since=None), "hold",
                         "buffer_not_needed", now)
    since = st.buffer_since if gap is None or gap <= MAX_GAP else None
    since = since or at
    st = replace(st, buffer_since=since)
    if at-since < BUFFER_CONFIRM:
        return _decision(st, "hold", "buffer_accumulating_evidence", now)
    cap = round(max_ev_kw-BUFFER_STEP_KW, 2)
    st = replace(st, mode="LIMITED", kind="buffer", cap_kw=cap,
                 buffer_since=None, quiet_since=None)
    return _decision(st, "reduce", "buffer_persistent_small_pressure", now)
