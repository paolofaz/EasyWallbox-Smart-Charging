"""Deterministic, simulation-only EasyWallbox planner and slow stabilizer.

No Home Assistant imports, BLE, device commands, persistent storage or I/O.
The physical DPM always remains the fast independent electrical controller.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import floor, isfinite


def _valid(value, *, positive=False):
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and isfinite(value) and (value > 0 if positive else value >= 0))


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    mode: str  # AUTO, MANUAL, PAUSE
    vehicle_id: str | None
    vehicle_ambiguous: bool
    charging: bool  # Actual observed charging, NOT a UI switch
    soc: float | None
    soc_at: datetime | None
    target_soc: float | None
    departure_at: datetime | None
    usable_capacity_kwh: float | None
    ac_efficiency: float | None
    sustainable_kw: float | None
    reserve_minutes: float = 30.0
    wallbox_reports_charging: bool | None = None


@dataclass(frozen=True)
class HouseSnapshot:
    downstairs_kw: float | None
    upstairs_kw: float | None
    quality: str  # ok, unavailable, stale, incoherent
    # The source adapter must attest quality and synchronization; a constant
    # value is valid only while source health is independently trusted.
    # "sources_kw" replaces the old fixed downstairs/upstairs layout.
    # Positional fields are retained for compatibility with pure-core tests.
    sources_kw: tuple[float | None, ...] | None = None

    @property
    def kw(self) -> float | None:
        if self.quality != "ok":
            return None
        values = (self.downstairs_kw, self.upstairs_kw) if self.sources_kw is None else self.sources_kw
        if not values or not all(_valid(v) for v in values):
            return None
        return sum(values)


@dataclass(frozen=True)
class LimitSnapshot:
    requested_kw: float | None
    confirmed_kw: float | None
    manual_owner: bool = False


@dataclass(frozen=True)
class Config:
    # INTERNAL REPLAY CANDIDATES, not production settings or electrical limits.
    dpm_model_kw: float = 4.3
    min_cap_kw: float = 1.4
    step_kw: float = 0.2
    trigger_kw: float = 1.5
    quiet_kw: float = 1.0
    trigger_seconds: int = 60
    quiet_minutes: int = 10
    cooldown_minutes: int = 10
    margin_wide_kw: float = 0.4
    margin_medium_kw: float = 0.2
    minimum_useful_reduction_kw: float = 0.6
    min_slack_minutes: float = 45.0
    wide_slack_minutes: float = 120.0
    budget_fraction_of_slack: float = 0.25
    soc_max_age_minutes: float = 30.0
    max_trigger_gap_seconds: int = 180

    def __post_init__(self):
        powers = (self.dpm_model_kw, self.min_cap_kw, self.step_kw,
                  self.trigger_kw, self.quiet_kw, self.minimum_useful_reduction_kw)
        if (not all(_valid(v, positive=True) for v in powers)
                or self.trigger_kw <= self.quiet_kw
                or not _valid(self.margin_wide_kw) or not _valid(self.margin_medium_kw)
                or not _valid(self.budget_fraction_of_slack)
                or self.budget_fraction_of_slack > 1
                or self.quiet_minutes <= 0 or self.trigger_seconds <= 0
                or self.max_trigger_gap_seconds < self.trigger_seconds
                or self.cooldown_minutes < 0 or self.soc_max_age_minutes <= 0):
            raise ValueError("invalid offline policy parameters")


@dataclass(frozen=True)
class Plan:
    reason: str
    remaining_grid_kwh: float | None = None
    required_minutes: float | None = None
    slack_minutes: float | None = None
    discretionary_budget_kwh: float = 0.0


def plan(now: datetime, s: SessionSnapshot, cfg: Config = Config()) -> Plan:
    """Conservative, explicit planner. Not a completion guarantee."""
    if not _aware(now) or not s.vehicle_id or s.vehicle_ambiguous:
        return Plan("unidentified_vehicle")
    if (not _valid(s.soc) or not _valid(s.target_soc)
            or s.soc > 100 or s.target_soc > 100 or not _aware(s.soc_at)
            or not _aware(s.departure_at) or s.soc_at > now
            or now - s.soc_at > timedelta(minutes=cfg.soc_max_age_minutes)
            or not _valid(s.usable_capacity_kwh, positive=True)
            or not _valid(s.ac_efficiency, positive=True)
            or s.ac_efficiency > 1
            or not _valid(s.reserve_minutes)):
        return Plan("insufficient_planner_data")
    remaining = max(0.0, s.target_soc - s.soc) * s.usable_capacity_kwh / (100.0 * s.ac_efficiency)
    if remaining <= 1e-9:
        # Reaching the target can be recognized without a measured charging
        # rate (e.g. the car is unplugged and the Shelly reads zero).
        return Plan("target_reached", 0.0, 0.0, 0.0)
    if not _valid(s.sustainable_kw, positive=True):
        # Required energy can still be estimated from SOC and usable capacity
        # without pretending a charging speed has been observed.
        return Plan("power_estimate_unavailable", remaining)
    required = remaining / s.sustainable_kw * 60.0
    slack = ((s.departure_at - now).total_seconds() / 60.0
             - s.reserve_minutes - required)
    # This 25% allocation is an OFFLINE TEST CANDIDATE, not production default.
    budget = (max(0.0, slack) / 60.0 * s.sustainable_kw
              * cfg.budget_fraction_of_slack)
    reason = "at_risk" if slack <= cfg.min_slack_minutes else "flexible"
    return Plan(reason, remaining, required, slack, budget if reason == "flexible" else 0.0)


@dataclass(frozen=True)
class CoreState:
    session_id: str | None = None
    mode: str = "NORMAL"  # NORMAL | LIMITED; unrelated to user mode
    cap_kw: float | None = None  # VIRTUAL; NEVER hardware confirmation
    original_kw: float | None = None
    baseline_requested_kw: float | None = None
    baseline_confirmed_kw: float | None = None
    candidate_since: datetime | None = None
    last_busy_at: datetime | None = None
    quiet_since: datetime | None = None
    cooldown_until: datetime | None = None
    last_at: datetime | None = None
    spent_kwh_upper_bound: float = 0.0


@dataclass(frozen=True)
class Proposal:
    action: str  # inactive, hold, reduce, restore, retire, insufficient_data
    state: str
    proposed_cap_kw: float | None
    reason: str
    budget_kwh: float
    spent_kwh_upper_bound: float
    slack_minutes: float | None
    next_check_at: datetime | None = None
    simulation_only: bool = True


def _result(state: CoreState, action: str, reason: str, p: Plan,
            next_check_at: datetime | None = None):
    return state, Proposal(action, state.mode, state.cap_kw, reason,
                           p.discretionary_budget_kwh, state.spent_kwh_upper_bound,
                           p.slack_minutes, next_check_at)


def _reset(session_id, now):
    return CoreState(session_id=session_id, last_at=now)


def evaluate(now: datetime, session: SessionSnapshot, house: HouseSnapshot,
             limits: LimitSnapshot, previous: CoreState | None = None,
             cfg: Config = Config()) -> tuple[CoreState, Proposal]:
    """One event-driven transition. Calling this cannot actuate anything."""
    if not _aware(now):
        raise ValueError("timezone-aware evaluation time required")
    p = plan(now, session, cfg)
    state = previous or _reset(session.session_id, now)
    if state.session_id != session.session_id:
        state = _reset(session.session_id, now)
    if state.last_at is not None and now < state.last_at:
        return _result(state, "insufficient_data", "non_monotonic_clock", p)

    if session.mode != "AUTO" or not session.charging or not session.vehicle_id or session.vehicle_ambiguous:
        # No restore: a virtual cap never existed in the real wallbox.
        state = _reset(session.session_id, now)
        reason = (
            "charge_now_disables_optional_cap" if session.mode == "CHARGE_NOW"
            else "reconciliation_required" if session.mode == "RECONCILE"
            else "manual_or_paused" if session.mode != "AUTO"
            else "not_charging_or_unidentified"
        )
        return _result(state, "inactive", reason, p)

    if (limits.manual_owner or not _valid(limits.confirmed_kw, positive=True)
            or not _valid(limits.requested_kw, positive=True)):
        if state.mode == "LIMITED":
            return _result(_reset(session.session_id, now), "retire", "ownership_lost", p)
        return _result(replace(state, last_at=now), "insufficient_data", "invalid_or_manual_limit", p)

    if state.mode == "LIMITED":
        # Account conservatively for ALL elapsed time, including missing data.
        # Do not confuse this upper bound with actual AC energy lost to the DPM.
        elapsed_hours = max(0.0, (now - state.last_at).total_seconds() / 3600.0)
        state = replace(state, last_at=now,
                        spent_kwh_upper_bound=state.spent_kwh_upper_bound +
                        max(0.0, state.original_kw - state.cap_kw) * elapsed_hours)
        if (abs(limits.requested_kw - state.baseline_requested_kw) > 0.11
                or abs(limits.confirmed_kw - state.baseline_confirmed_kw) > 0.11):
            return _result(_reset(session.session_id, now), "retire", "external_limit_changed", p)
        if p.reason != "flexible" or state.spent_kwh_upper_bound >= p.discretionary_budget_kwh:
            restored = replace(state, mode="NORMAL", cap_kw=state.original_kw,
                               candidate_since=None, quiet_since=None,
                               last_busy_at=None,
                               cooldown_until=now + timedelta(minutes=cfg.cooldown_minutes))
            return _result(restored, "restore", "planner_needs_full_power", p)
        value = house.kw
        if value is None:
            return _result(replace(state, quiet_since=None), "insufficient_data", "house_data_not_trusted", p)
        if value >= cfg.trigger_kw:
            state = replace(state, last_busy_at=now, quiet_since=None)
            return _result(state, "hold", "busy_home_keep_cap", p)
        if value <= cfg.quiet_kw:
            if state.quiet_since is None:
                state = replace(state, quiet_since=now)
            due = state.quiet_since + timedelta(minutes=cfg.quiet_minutes)
            if now >= due:
                restored = replace(state, mode="NORMAL", cap_kw=state.original_kw,
                                   candidate_since=None, quiet_since=None,
                                   last_busy_at=None,
                                   cooldown_until=now + timedelta(minutes=cfg.cooldown_minutes))
                return _result(restored, "restore", "documented_quiet", p)
            return _result(state, "hold", "waiting_for_quiet", p, due)
        # Mid-band is not evidence of a quiet interval.
        state = replace(state, quiet_since=None)
        return _result(state, "hold", "house_in_hysteresis_band", p)

    state = replace(state, last_at=now, cap_kw=limits.confirmed_kw,
                    original_kw=limits.confirmed_kw)
    if abs(limits.requested_kw - limits.confirmed_kw) > 0.11:
        return _result(replace(state, candidate_since=None), "insufficient_data",
                       "limit_unconfirmed", p)
    if p.reason != "flexible":
        return _result(replace(state, candidate_since=None), "hold", p.reason, p)
    if state.cooldown_until is not None and now < state.cooldown_until:
        return _result(replace(state, candidate_since=None), "hold", "cooldown", p, state.cooldown_until)
    value = house.kw
    if value is None:
        return _result(replace(state, candidate_since=None), "insufficient_data", "house_data_not_trusted", p)
    if value < cfg.trigger_kw:
        return _result(replace(state, candidate_since=None), "hold", "house_not_busy", p)
    if state.candidate_since is None:
        due = now + timedelta(seconds=cfg.trigger_seconds)
        return _result(replace(state, candidate_since=now), "hold", "confirming_house_load", p, due)
    if now - state.candidate_since > timedelta(seconds=cfg.max_trigger_gap_seconds):
        due = now + timedelta(seconds=cfg.trigger_seconds)
        return _result(replace(state, candidate_since=now), "hold", "confirming_house_load", p, due)
    due = state.candidate_since + timedelta(seconds=cfg.trigger_seconds)
    if now < due:
        return _result(state, "hold", "confirming_house_load", p, due)
    margin = cfg.margin_wide_kw if p.slack_minutes >= cfg.wide_slack_minutes else cfg.margin_medium_kw
    raw = cfg.dpm_model_kw - value - margin
    cap = round(floor((raw + 1e-9) / cfg.step_kw) * cfg.step_kw, 6)
    if (cap < cfg.min_cap_kw or limits.confirmed_kw - cap < cfg.minimum_useful_reduction_kw - 1e-8):
        return _result(replace(state, candidate_since=None), "hold", "no_useful_cap_dpm_handles_load", p)
    # A candidate must afford at least one full quiet-window equivalent.
    expected_cost = (limits.confirmed_kw - cap) * cfg.quiet_minutes / 60.0
    if expected_cost + state.spent_kwh_upper_bound > p.discretionary_budget_kwh:
        return _result(replace(state, candidate_since=None), "hold", "insufficient_budget", p)
    state = replace(state, mode="LIMITED", cap_kw=cap, original_kw=limits.confirmed_kw,
                    baseline_requested_kw=limits.requested_kw,
                    baseline_confirmed_kw=limits.confirmed_kw,
                    candidate_since=None, last_busy_at=now, quiet_since=None)
    return _result(state, "reduce", "stable_optional_cap", p)
