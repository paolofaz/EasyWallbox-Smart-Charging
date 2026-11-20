"""Pure, bounded planner estimate from measured household and EV power.

No manually entered 'sustainable kW' and no constant hidden substitute.
Only real, time-stamped readings enter the forecast; a provisional house
reading is not treated as a forecast of an entire night.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite

MIN_AC_KW = 1.4
HEADROOM_KW = 0.2
MAX_SAMPLE_GAP = timedelta(minutes=3)
MAX_AGE = timedelta(minutes=3)
WINDOW = timedelta(minutes=20)
MIN_SPAN = timedelta(minutes=8)


def _validated_window(samples, now: datetime):
    if now.tzinfo is None or now.utcoffset() is None:
        return None
    ordered = sorted((t, float(v)) for t, v in samples
                     if isinstance(t, datetime) and t.tzinfo is not None
                     and isinstance(v, (int, float)) and not isinstance(v, bool)
                     and isfinite(v) and v >= 0
                     and now-WINDOW <= t <= now)
    # Replacing equal timestamps is intentional: duplicate HA state
    # callbacks do not count as two independent measurements.
    dedup = {t: v for t, v in ordered}
    ordered = sorted(dedup.items())
    if len(ordered) < 6 or ordered[-1][0]-ordered[0][0] < MIN_SPAN:
        return None
    if now-ordered[-1][0] > MAX_AGE:
        return None
    if any(t2-t1 > MAX_SAMPLE_GAP for (t1, _), (t2, _) in zip(ordered, ordered[1:])):
        return None
    return [v for _, v in ordered]


def estimate_ac_kw(*, now: datetime, dpm_kw: float, ev_base_kw: float,
                   house_samples, charging_ev_samples=()):
    """Estimate sustainable AC kW, or None when history is not reliable.

    DPM is the configured POSITIVE budget even when its sensor reads 0 A.
    75th-percentile household consumption favors prudent time planning.
    While charging, a reliable history of *actual* EV power can further
    lower the predicted rate; it never artificially increases capacity.
    """
    if (not isfinite(dpm_kw) or not isfinite(ev_base_kw) or
            dpm_kw <= 0 or ev_base_kw < MIN_AC_KW):
        return None
    house = _validated_window(house_samples, now)
    if house is None:
        return None
    ordered = sorted(house)
    p75 = ordered[(3*(len(ordered)-1))//4]
    budget = min(ev_base_kw, max(0, dpm_kw-p75-HEADROOM_KW))
    if budget < MIN_AC_KW:
        return None

    ev = _validated_window(charging_ev_samples, now)
    if ev is not None:
        # A persistent lower actual rate is evidence of a real bottleneck.
        # Never use 0 W from an idle/paused wallbox as available charging.
        measured_mean = sum(ev)/len(ev)
        if measured_mean < MIN_AC_KW:
            return None
        budget = min(budget, measured_mean)
    return round(budget, 2)


def margin_minutes(*, now: datetime, departure: datetime | None,
                   remaining_kwh: float | None, rate_kw: float | None,
                   reserve_minutes: float = 30):
    """Positive means spare time; unknown rate must remain unknown."""
    if (departure is None or departure.tzinfo is None or
            now.tzinfo is None or rate_kw is None or
            remaining_kwh is None or
            not isfinite(rate_kw) or not isfinite(remaining_kwh) or
            rate_kw < MIN_AC_KW or remaining_kwh < 0):
        return None
    return ((departure-now).total_seconds()/60 - reserve_minutes
            - 60*remaining_kwh/rate_kw)
