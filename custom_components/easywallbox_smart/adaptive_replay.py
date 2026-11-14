"""Bounded deterministic *hypothesis* replay for the M1 adaptive cap.

Pure Python, synthetic loads only, no HA, storage, BLE, device commands or logs.
Ideal DPM for energy and an explicitly hypothetical delayed response for
transient alarm counts. Never infer real DPM response time from this model.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite

from .adaptive_policy import PolicyConfig, SimulatedCapPolicy

STRATEGIES = ("dpm_only", "fixed_low", "adaptive")


@dataclass(frozen=True)
class HomePeriod:
    start_minute: float
    end_minute: float
    house_kw: float


@dataclass(frozen=True)
class Scenario:
    started: datetime
    departure: datetime
    battery_needed_kwh: float
    household_baseline_kw: float
    busy: tuple[HomePeriod, ...]
    available_kw: float = 4.4
    alarm_kw: float = 5.0
    nominal_cap_kw: float = 4.0
    low_cap_kw: float = 2.0
    efficiency: float = 0.9
    planning_sustainable_kw: float = 3.2
    reserve_minutes: int = 30
    sample_seconds: int = 20
    assumed_dpm_delay_seconds: int = 20


@dataclass(frozen=True)
class Action:
    minute: float
    action: str
    new_cap_kw: float
    reason: str
    slack_minutes: float


@dataclass(frozen=True)
class ReplayResult:
    strategy: str
    battery_kwh_at_departure: float
    shortfall_kwh: float
    reached_at: datetime | None
    alarm_episodes: int
    seconds_over_alarm: int
    max_modeled_total_kw: float
    cap_changes: int
    first_actions: tuple[Action, ...]
    no_commands_sent: bool = True


def _number(value, allow_zero=False):
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and isfinite(value) and (value >= 0 if allow_zero else value > 0))


def _validate(x: Scenario):
    if (x.started.tzinfo is None or x.departure.tzinfo is None
            or x.started.utcoffset() is None or x.departure.utcoffset() is None
            or x.departure <= x.started
            or (x.departure.astimezone(timezone.utc) -
                x.started.astimezone(timezone.utc)) > timedelta(days=2)):
        raise ValueError("invalid replay time range")
    if not all(_number(v) for v in (
            x.available_kw, x.alarm_kw, x.nominal_cap_kw, x.low_cap_kw,
            x.efficiency, x.planning_sustainable_kw)) or not all(
                _number(v, allow_zero=True) for v in (
                    x.battery_needed_kwh, x.household_baseline_kw)):
        raise ValueError("invalid replay power/energy")
    if (x.efficiency > 1 or x.alarm_kw < x.available_kw
            or x.nominal_cap_kw < x.low_cap_kw or x.low_cap_kw < 1.4
            or not isinstance(x.reserve_minutes, int)
            or isinstance(x.reserve_minutes, bool) or not 0 <= x.reserve_minutes <= 1440
            or not isinstance(x.sample_seconds, int) or isinstance(x.sample_seconds, bool)
            or x.sample_seconds < 5 or x.sample_seconds > 60 or 60 % x.sample_seconds
            or not isinstance(x.assumed_dpm_delay_seconds, int)
            or isinstance(x.assumed_dpm_delay_seconds, bool)
            or x.assumed_dpm_delay_seconds < 0
            or x.assumed_dpm_delay_seconds > 180
            or x.assumed_dpm_delay_seconds % x.sample_seconds):
        raise ValueError("invalid replay limits or grid response assumption")
    last_end = 0.0
    for period in x.busy:
        if (not all(_number(v, allow_zero=True) for v in (
                period.start_minute, period.end_minute, period.house_kw))
                or period.start_minute < last_end
                or period.end_minute <= period.start_minute):
            raise ValueError("nonascending/overlapping home periods")
        last_end = period.end_minute


def departure_slack_minutes(
        at: datetime, departure: datetime, battery_remaining_kwh: float,
        efficiency: float, sustainable_kw: float, reserve_minutes: int) -> float:
    """Planning-only slack, using an EXPLICIT assumed sustainable EV power.

    Does not equate the present DPM headroom with night-long availability.
    Negative slack represents a deadline already under pressure.
    """
    return ((departure.astimezone(timezone.utc) - at.astimezone(timezone.utc)).total_seconds() / 60 - reserve_minutes
            - battery_remaining_kwh / (efficiency * sustainable_kw) * 60)


def _house_at(x: Scenario, minute: float) -> float:
    for period in x.busy:
        if period.start_minute <= minute < period.end_minute:
            return period.house_kw
    return x.household_baseline_kw


def run_replay(x: Scenario, strategy: str) -> ReplayResult:
    """Compare identical home schedules; models optional extra caps.

    A lagged DPM response is *only* a sensitivity hypothesis, not a claim about
    EasyWallbox electrical behavior. Modelled >alarm counts are NOT observed
    alarms. In the ideal zero-delay case the DPM prevents total >available.
    """
    _validate(x)
    if strategy not in STRATEGIES:
        raise ValueError("unknown strategy")
    policy = SimulatedCapPolicy(PolicyConfig(
        available_kw=x.available_kw, alarm_kw=x.alarm_kw,
        nominal_cap_kw=x.nominal_cap_kw)) if strategy == "adaptive" else None
    if policy:
        policy.set_charging(True)
    battery, reached, episodes, elapsed, max_total = 0.0, None, 0, 0, 0.0
    changes, first_actions, prev_alarm = 0, [], False
    horizon_seconds = (x.departure.astimezone(timezone.utc) -
                       x.started.astimezone(timezone.utc)).total_seconds()
    elapsed_seconds = 0
    while elapsed_seconds < horizon_seconds and battery < x.battery_needed_kwh:
        step = min(x.sample_seconds, horizon_seconds - elapsed_seconds)
        at = (x.started.astimezone(timezone.utc) + timedelta(seconds=elapsed_seconds)).astimezone(x.started.tzinfo)
        minute = elapsed_seconds / 60
        house = _house_at(x, minute)
        # Explicitly hypothetical DPM measurement lag, configured in steps.
        past_minute = max(0, elapsed_seconds - x.assumed_dpm_delay_seconds) / 60
        lagged_house = _house_at(x, past_minute)
        cap = (x.nominal_cap_kw if strategy == "dpm_only"
               else x.low_cap_kw if strategy == "fixed_low"
               else policy.cap_kw)
        ev = min(cap, max(0.0, x.available_kw - lagged_house))
        if ev < 1.4:
            ev = 0.0  # Modelling assumption, not verified charging behavior.
        total = house + ev
        max_total = max(max_total, total)
        alarm_now = total >= x.alarm_kw
        if alarm_now:
            elapsed += step
            if not prev_alarm:
                episodes += 1
        prev_alarm = alarm_now

        if policy:
            policy.observe(at, house, total_kw=total)
            remaining = max(0., x.battery_needed_kwh - battery)
            slack = departure_slack_minutes(
                at, x.departure, remaining, x.efficiency,
                x.planning_sustainable_kw, x.reserve_minutes)
            proposal = policy.evaluate(at, max(0.0, slack))
            if proposal.action in ("reduce", "raise", "restore"):
                changes += 1
                if len(first_actions) < 30:
                    first_actions.append(Action(
                        round(minute, 2), proposal.action, proposal.cap_kw,
                        proposal.reason, round(slack, 1)))

        gained = ev * step * x.efficiency / 3600
        if gained > 0 and battery + gained >= x.battery_needed_kwh:
            fraction = (x.battery_needed_kwh - battery) / gained
            reached = at + timedelta(seconds=step * fraction)
            battery = x.battery_needed_kwh
        else:
            battery += gained
        elapsed_seconds += step

    if policy:
        policy.set_charging(False)  # Drops all volatile state at end.
    return ReplayResult(
        strategy=strategy,
        battery_kwh_at_departure=round(battery, 3),
        shortfall_kwh=round(max(0.0, x.battery_needed_kwh - battery), 3),
        reached_at=reached,
        alarm_episodes=episodes,
        seconds_over_alarm=int(elapsed),
        max_modeled_total_kw=round(max_total, 3),
        cap_changes=changes,
        first_actions=tuple(first_actions),
    )


def dishwasher_example(*, delay_seconds=20, battery_kwh=24.0) -> Scenario:
    """Synthetic intermittent heating; no recorded household data included."""
    from zoneinfo import ZoneInfo
    rome = ZoneInfo("Europe/Rome")
    start = datetime(2026, 11, 13, 21, 13, tzinfo=rome)
    return Scenario(
        started=start,
        departure=datetime(2026, 11, 14, 8, 0, tzinfo=rome),
        battery_needed_kwh=battery_kwh,
        household_baseline_kw=0.35,
        busy=(HomePeriod(3, 11, 2.5), HomePeriod(28, 35, 2.5),
              HomePeriod(66, 73, 2.5), HomePeriod(108, 115, 2.5),
              HomePeriod(151, 157, 2.5)),
        assumed_dpm_delay_seconds=delay_seconds,
    )
