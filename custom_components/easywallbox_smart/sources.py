"""Pure state normalizers used by the HA adapter; no Home Assistant dependency."""
from __future__ import annotations
from datetime import datetime, time, timedelta
from math import isfinite


def finite_number(raw) -> float | None:
    if isinstance(raw, bool):
        return None
    try:
        result = float(raw)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def power_kw(raw, unit: str | None) -> float | None:
    v = finite_number(raw)
    if v is None or v < 0:
        return None
    if unit in ("W", "w"):
        return v / 1000.0
    if unit in ("kW", "kw"):
        return v
    return None


def on(raw) -> bool | None:
    if raw in ("on", "true", True, "1"):
        return True
    if raw in ("off", "false", False, "0"):
        return False
    return None


def number_with_unit(raw, unit: str | None) -> float | None:
    return power_kw(raw, unit)


def next_departure(now: datetime, weekday: str, weekend: str) -> datetime | None:
    """Use target day's weekday, never the connection day's weekday."""
    if now.tzinfo is None or now.utcoffset() is None:
        return None
    try:
        for offset in range(8):
            date = now.date() + timedelta(days=offset)
            hh, mm = map(int, (weekend if date.weekday() >= 5 else weekday).split(":"))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                return None
            result = datetime.combine(date, time(hour=hh, minute=mm), tzinfo=now.tzinfo)
            if result > now:
                return result
    except (TypeError, ValueError):
        return None
    return None
