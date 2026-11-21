"""Bounded one-shot local-time delayed-start scheduling.

A stored wall-clock time is only a candidate. The selected next
occurrence must be strictly in the future and no more than 12 hours
away when the user activates or modifies an active delay.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

MAX_DELAY = timedelta(hours=12)


def next_occurrence(now: datetime, selected: time, time_zone: str) -> datetime:
    if (not isinstance(now, datetime) or now.utcoffset() is None
            or not isinstance(selected, time)):
        raise ValueError("invalid_delay_time")
    tz = ZoneInfo(time_zone)
    local = now.astimezone(tz)
    target = datetime.combine(local.date(), selected.replace(tzinfo=None), tzinfo=tz)
    if target <= local:
        target = datetime.combine(local.date() + timedelta(days=1),
                                  selected.replace(tzinfo=None), tzinfo=tz)
    return target


def validate_delay(now: datetime, selected: time, time_zone: str) -> datetime:
    """Never return a 23-hour wait for a clock that has just passed."""
    target = next_occurrence(now, selected, time_zone)
    delta = target.astimezone(ZoneInfo("UTC")) - now.astimezone(ZoneInfo("UTC"))
    if not timedelta(0) < delta <= MAX_DELAY:
        raise ValueError("delayed_start_must_be_within_12_hours")
    return target
