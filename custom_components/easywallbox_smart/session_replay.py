"""Deterministic offline night replay: no Home Assistant imports or commands.

This idealised scenario is for comparing hypotheses, NEVER a real-time
safety controller or evidence that a household electrical branch is safe.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

HEATING_WINDOWS = ((4, 12), (21, 30), (64, 70))
MODES = ("dpm_only", "manual_restore", "manual_forget")


@dataclass(frozen=True)
class Night:
    started: datetime
    departure: datetime
    battery_needed_kwh: float
    effective_high_kw: float
    effective_low_kw: float
    ac_efficiency: float
    site_dpm_kw: float
    home_baseline_kw: float
    dishwasher_extra_peak_kw: float
    dishwasher_delay_minutes: int
    dishwasher_cycle_minutes: int


@dataclass(frozen=True)
class NightResult:
    mode: str
    target_reached_at: datetime | None
    minutes_until_target: float | None
    battery_kwh_at_departure: float
    shortfall_kwh_at_departure: float
    ideal_dpm_clipped_minutes: int
    no_commands_sent: bool = True


def _positive(v: object, allow_zero: bool = False) -> bool:
    return (
        isinstance(v, (float, int))
        and not isinstance(v, bool)
        and isfinite(v)
        and (v >= 0 if allow_zero else v > 0)
    )


def _validate(x: Night) -> tuple[int, int]:
    if (
        x.started.tzinfo is None or x.departure.tzinfo is None
        or x.started.utcoffset() is None or x.departure.utcoffset() is None
        or x.departure <= x.started
    ):
        raise ValueError("start/departure must be aware and ascending")
    values = (
        x.battery_needed_kwh, x.effective_high_kw, x.effective_low_kw,
        x.ac_efficiency, x.site_dpm_kw, x.home_baseline_kw,
        x.dishwasher_extra_peak_kw,
    )
    if not all(
        _positive(v, allow_zero=(index in (0, 5, 6)))
        for index, v in enumerate(values)
    ):
        raise ValueError("invalid replay power/energy")
    if (
        x.effective_low_kw > x.effective_high_kw
        or x.effective_low_kw < 1.4
        or x.ac_efficiency > 1
        or not isinstance(x.dishwasher_delay_minutes, int)
        or isinstance(x.dishwasher_delay_minutes, bool)
        or x.dishwasher_delay_minutes < 0
        or not isinstance(x.dishwasher_cycle_minutes, int)
        or isinstance(x.dishwasher_cycle_minutes, bool)
        or x.dishwasher_cycle_minutes < 1
    ):
        raise ValueError("invalid replay limits or dishwasher parameters")
    minutes = int((x.departure - x.started).total_seconds() // 60)
    horizon = max(minutes + 360, x.dishwasher_delay_minutes
                  + x.dishwasher_cycle_minutes + 120)
    if horizon > 365 * 24 * 60:
        raise ValueError("unbounded horizon")
    return minutes, horizon


def run_night(x: Night, mode: str) -> NightResult:
    """Simulate grid charging minute-by-minute under an IDEAL instantaneous DPM.

    A real DPM has dynamics; this does not simulate charging communication,
    BLE acknowledgements, circuit branch limits or protection trips.
    """
    if mode not in MODES:
        raise ValueError("unknown replay mode")
    deadline, horizon = _validate(x)
    if x.battery_needed_kwh == 0:
        return NightResult(mode, x.started, 0.0, 0.0, 0.0, 0)
    battery, reached, clipped, at_departure = 0.0, None, 0, 0.0
    for minute in range(horizon + 1):
        running = (
            x.dishwasher_delay_minutes <= minute <
            x.dishwasher_delay_minutes + x.dishwasher_cycle_minutes
        )
        relative = (
            (minute - x.dishwasher_delay_minutes)
            * 102 / x.dishwasher_cycle_minutes
        )
        heating = running and any(
            left <= relative < right for left, right in HEATING_WINDOWS
        )
        household_kw = x.home_baseline_kw + (
            x.dishwasher_extra_peak_kw if heating else 0.10 if running else 0.0
        )
        reduced = (
            (mode == "manual_forget" and minute >= x.dishwasher_delay_minutes)
            or (mode == "manual_restore" and running)
        )
        cap = x.effective_low_kw if reduced else x.effective_high_kw
        available = max(0.0, x.site_dpm_kw - household_kw)
        watts = min(cap, available)
        # This is a model assumption, NOT the actual electrical EVSE behavior.
        actual = watts if watts >= 1.4 else 0.0

        if minute == deadline:
            at_departure = min(battery, x.battery_needed_kwh)
        if minute == horizon or reached is not None:
            continue
        if actual > 0:
            if actual + 1e-4 < cap:
                clipped += 1
            gain = actual * x.ac_efficiency / 60
            if battery + gain >= x.battery_needed_kwh:
                fraction = (x.battery_needed_kwh - battery) / gain
                reached = minute + fraction
                battery = x.battery_needed_kwh
            else:
                battery += gain

    return NightResult(
        mode=mode,
        target_reached_at=(
            x.started + timedelta(minutes=reached)
            if reached is not None else None
        ),
        minutes_until_target=reached,
        battery_kwh_at_departure=round(at_departure, 4),
        shortfall_kwh_at_departure=round(
            max(0, x.battery_needed_kwh - at_departure), 4
        ),
        ideal_dpm_clipped_minutes=clipped,
    )


def kia_nov13_example() -> Night:
    """Recorded SOC/energy/time and illustrative, disclosed power assumptions."""
    from datetime import timezone
    rome = timezone(timedelta(hours=1))
    return Night(
        started=datetime(2026, 11, 13, 21, 13, tzinfo=rome),
        departure=datetime(2026, 11, 14, 8, 0, tzinfo=rome),
        battery_needed_kwh=27.69,
        effective_high_kw=3.85,  # assumption, NOT synchronized measurement
        effective_low_kw=3.0,
        ac_efficiency=.85,       # provisional, NOT proven EV3 efficiency
        site_dpm_kw=4.4,
        home_baseline_kw=.2,
        dishwasher_extra_peak_kw=2.1,
        dishwasher_delay_minutes=0,
        dishwasher_cycle_minutes=102,
    )
