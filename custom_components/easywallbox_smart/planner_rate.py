"""Pure, bounded planner estimate from measured household and EV power.

No manually entered 'sustainable kW' and no constant hidden substitute.
Only real, time-stamped readings enter the forecast; a provisional house
reading is not treated as a forecast of an entire night.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import dataclass
from math import isfinite
from statistics import median

MIN_AC_KW = 1.4
HEADROOM_KW = 0.2
MAX_SAMPLE_GAP = timedelta(minutes=3)
MAX_AGE = timedelta(minutes=3)
WINDOW = timedelta(minutes=20)
MIN_SPAN = timedelta(minutes=6)


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



def estimate_forecast_ac_kw(*, now: datetime, dpm_kw: float,
                            ev_base_kw: float, house_samples,
                            charging_ev_samples=()):
    """Advisory ETA rate, separate from the deliberately cautious safety rate.

    Average observed house load over as much as one hour, rather than treating
    the highest 25% of only 20 minutes as the entire remaining night.
    Requires >=3 real distinct samples over >=2 minutes; no invented baseline.
    This value MUST NOT be used for real power or deadline policy decisions.
    """
    if (not isfinite(dpm_kw) or not isfinite(ev_base_kw)
            or dpm_kw <= 0 or ev_base_kw < MIN_AC_KW
            or now.tzinfo is None):
        return None
    recent = sorted({t: float(v) for t, v in house_samples
                     if isinstance(t, datetime) and t.tzinfo is not None
                     and isinstance(v, (float, int)) and not isinstance(v, bool)
                     and isfinite(v) and v >= 0 and
                     now-timedelta(minutes=60) <= t <= now}.items())
    if (len(recent) < 3 or
            recent[-1][0]-recent[0][0] < timedelta(minutes=2) or
            now-recent[-1][0] > MAX_AGE or
            any(b[0]-a[0] > MAX_SAMPLE_GAP for a,b in zip(recent, recent[1:]))):
        return None
    mean_house = sum(v for _,v in recent)/len(recent)
    rate = min(ev_base_kw, max(0, dpm_kw-mean_house-HEADROOM_KW))
    if rate < MIN_AC_KW:
        return None
    # Compare to observed uncapped EV capability when available. Do not use
    # the station's own LIMITED cap to forecast the hypothetical full rate.
    ev = sorted({t: float(v) for t,v in charging_ev_samples
                 if isinstance(t, datetime) and t.tzinfo is not None
                 and isinstance(v, (int,float)) and not isinstance(v, bool)
                 and isfinite(v) and v >= 0
                 and now-timedelta(minutes=60) <= t <= now}.items())
    if (len(ev) >= 3 and ev[-1][0]-ev[0][0] >= timedelta(minutes=2)
            and now-ev[-1][0] <= timedelta(minutes=30)):
        powers = sorted(v for _,v in ev if v >= MIN_AC_KW)
        if len(powers) >= 3:
            observed_p75 = powers[(3*(len(powers)-1))//4]
            rate = min(rate, observed_p75)
    return round(rate, 2)


# ETA is informational only: NEVER feed this estimate to the charging policy.
ETA_NEAR_MINUTES = 30
ETA_FREE_MIN_SAMPLES = 20
ETA_FREE_MIN_SPAN = timedelta(minutes=10)


@dataclass(frozen=True)
class ChargeETA:
    """Forecast in seconds from now, without a false precise-time promise."""
    seconds: float
    earliest_seconds: float
    free_kw: float
    now_kw: float | None
    average_kw: float
    quality: str


def _recent_power(samples, now, window, minimum=3, min_span=2):
    """Use independent timestamped reports; ignore gaps and old readings."""
    ordered = sorted({
        at: float(value) for at, value in samples
        if isinstance(at, datetime) and at.tzinfo is not None
        and isinstance(value, (int, float)) and not isinstance(value, bool)
        and isfinite(value) and value >= 0
        and now-window <= at <= now
    }.items())
    if (len(ordered) < minimum or
            ordered[-1][0]-ordered[0][0] < timedelta(minutes=min_span) or
            now-ordered[-1][0] > MAX_AGE):
        return None
    if any(b[0]-a[0] > MAX_SAMPLE_GAP
           for a, b in zip(ordered, ordered[1:])):
        return None
    return [value for _, value in ordered]


def estimate_charge_eta(*, now: datetime, remaining_kwh: float,
                        base_kw: float, contracted_kw: float,
                        free_ev_samples=(), recent_ev_samples=(),
                        energy_calibrated=False) -> ChargeETA | None:
    """Two-regime advisory forecast with a verified free-rate reference.

    - P_free is the median of genuinely measured, uncapped, low-house EV
      samples in the SAME physical session. Without enough independent
      samples, a provisional 96% of requested base is used (bounded by
      contracted power minus the pre-existing 0.2 kW reserve).
    - P_now is the observed EV mean in the latest 10 minutes, INCLUDING
      a verified zero-power DPM pause. Only the first 30 forecast minutes
      use P_now; the rest use P_free. A pause never causes a divide-by-zero.
    - The conservative deadline margin is deliberately NOT affected.
    This model makes no prediction of future domestic appliance usage.
    """
    if (now.tzinfo is None or not isfinite(remaining_kwh)
            or remaining_kwh < 0 or not isfinite(base_kw)
            or not isfinite(contracted_kw) or base_kw < MIN_AC_KW
            or contracted_kw <= MIN_AC_KW):
        return None
    provisional = min(base_kw * .96, contracted_kw-HEADROOM_KW)
    if provisional <= 0:
        return None
    free_valid = sorted({
        at: float(value) for at, value in free_ev_samples
        if isinstance(at, datetime) and at.tzinfo is not None
        and isinstance(value, (float, int)) and not isinstance(value, bool)
        and isfinite(value) and MIN_AC_KW <= value <= base_kw+.15
        and now-timedelta(hours=4) <= at <= now
    }.items())
    measured_free = (
        len(free_valid) >= ETA_FREE_MIN_SAMPLES and
        free_valid[-1][0]-free_valid[0][0] >= ETA_FREE_MIN_SPAN and
        now-free_valid[-1][0] <= timedelta(hours=4)
    )
    free_kw = (median(value for _, value in free_valid)
               if measured_free else provisional)
    free_kw = min(base_kw, max(.1, free_kw))
    recent = _recent_power(recent_ev_samples, now, timedelta(minutes=10))
    current = min(free_kw, sum(recent)/len(recent)) if recent is not None else None
    near_kw = free_kw if current is None else max(0, current)
    near_hours = ETA_NEAR_MINUTES/60
    first_energy = near_kw*near_hours
    if remaining_kwh <= 0:
        elapsed_h = 0.0
    elif near_kw > .01 and remaining_kwh <= first_energy:
        elapsed_h = remaining_kwh/near_kw
    else:
        elapsed_h = near_hours + max(0.0, remaining_kwh-first_energy)/free_kw
    seconds = 3600 * elapsed_h
    return ChargeETA(
        seconds=seconds,
        earliest_seconds=3600*remaining_kwh/free_kw,
        free_kw=round(free_kw, 3),
        now_kw=(round(current, 3) if current is not None else None),
        average_kw=(round(3600*remaining_kwh/seconds, 3)
                    if seconds > 0 else round(free_kw, 3)),
        quality=("consolidata" if measured_free and recent is not None
                 and energy_calibrated else "provvisoria"),
    )


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
