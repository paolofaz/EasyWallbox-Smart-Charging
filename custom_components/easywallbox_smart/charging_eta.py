"""Actual-power charging ETA: one estimate, no wallbox control.

Battery kWh are battery-side; EV power is grid-side. Both are required.
The result describes an unchanged-rate scenario, not a guaranteed deadline.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite

POWER_MAX_AGE_SECONDS = 300
ASSUMED_AC_EFFICIENCY = 0.90
MIN_MEANINGFUL_CHARGE_KW = 0.15


@dataclass(frozen=True)
class ChargeETA:
    status: str
    finish: datetime | None
    hours_remaining: float | None
    ev_grid_kw: float | None


def estimate(
    now: datetime, battery_kwh: float | None, ev_grid_kw: float | None,
    efficiency: float = ASSUMED_AC_EFFICIENCY,
) -> ChargeETA:
    """ETA based on measured charging power only, never site headroom."""
    if now.tzinfo is None or now.utcoffset() is None:
        return ChargeETA("invalid_time", None, None, None)
    if (
        isinstance(battery_kwh, bool)
        or not isinstance(battery_kwh, (float, int))
        or not isfinite(battery_kwh) or battery_kwh < 0
        or isinstance(efficiency, bool)
        or not isinstance(efficiency, (float, int))
        or not isfinite(efficiency) or not 0 < efficiency <= 1
    ):
        return ChargeETA("battery_data_unavailable", None, None, None)
    if battery_kwh == 0:
        return ChargeETA("target_reached", now, 0.0, 0.0)
    if (
        isinstance(ev_grid_kw, bool)
        or not isinstance(ev_grid_kw, (float, int))
        or not isfinite(ev_grid_kw) or ev_grid_kw < 0
    ):
        return ChargeETA("charging_power_unavailable", None, None, None)
    if ev_grid_kw <= MIN_MEANINGFUL_CHARGE_KW:
        return ChargeETA("not_charging", None, None, ev_grid_kw)
    hours = battery_kwh / (ev_grid_kw * efficiency)
    if not isfinite(hours) or hours > 7 * 24:
        return ChargeETA("unrealistic_duration", None, None, ev_grid_kw)
    return ChargeETA("ok", now + timedelta(hours=hours), round(hours, 2),
                     round(ev_grid_kw, 3))


def evaluate(hass, config: dict, snapshot, now: datetime) -> ChargeETA:
    """Read only the already configured, fresh EV power sensor."""
    if snapshot.quality != "ok" or snapshot.remaining_kwh is None:
        return ChargeETA("vehicle_" + snapshot.quality, None, None, None)
    power_id = config.get("ev_power_sensor")
    if not isinstance(power_id, str) or not power_id:
        return ChargeETA("charging_power_source_not_configured", None, None, None)
    source = hass.states.get(power_id)
    if source is None:
        return ChargeETA("charging_power_unavailable", None, None, None)
    stamp = getattr(source, "last_reported", None) or source.last_updated
    if stamp is None or stamp.tzinfo is None or stamp.utcoffset() is None:
        return ChargeETA("charging_power_stale", None, None, None)
    age = (now.astimezone(timezone.utc) - stamp).total_seconds()
    if not 0 <= age <= POWER_MAX_AGE_SECONDS:
        return ChargeETA("charging_power_stale", None, None, None)
    if source.state in ("unknown", "unavailable", ""):
        return ChargeETA("charging_power_unavailable", None, None, None)
    try:
        value = float(source.state)
    except (TypeError, ValueError):
        return ChargeETA("charging_power_invalid", None, None, None)
    unit = source.attributes.get("unit_of_measurement")
    if unit == "W":
        value /= 1000
    elif unit != "kW":
        return ChargeETA("charging_power_invalid_unit", None, None, None)
    return estimate(now, snapshot.remaining_kwh, value)
