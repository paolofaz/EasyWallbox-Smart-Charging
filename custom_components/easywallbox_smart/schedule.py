"""Pure calendar helper for the next configured local departure."""

from datetime import datetime, time, timedelta


def next_departure(now: datetime, weekday_hhmm: str, weekend_hhmm: str) -> datetime:
    """Find the next future departure, including across midnight and weekends."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_required")
    def parse(value: str) -> time:
        if not isinstance(value, str) or len(value) != 5:
            raise ValueError("invalid_departure_time")
        try:
            parsed = time.fromisoformat(value)
        except ValueError as err:
            raise ValueError("invalid_departure_time") from err
        if parsed.tzinfo is not None or value != parsed.strftime("%H:%M"):
            raise ValueError("invalid_departure_time")
        return parsed
    weekday, weekend = parse(weekday_hhmm), parse(weekend_hhmm)
    for days in range(8):
        day = (now + timedelta(days=days)).date()
        clock = weekend if day.weekday() >= 5 else weekday
        candidate = datetime.combine(day, clock, tzinfo=now.tzinfo)
        if candidate > now:
            return candidate
    raise ValueError("no_future_departure")
