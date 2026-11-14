"""Pure, simulation-only charging-cap policy; never controls Home Assistant or BLE.

The DPM remains the sole fast electrical regulator. A valid crossing of the
configured *alarm* threshold enables a discretionary cap; domestic readings
excluding the car govern the cap and its gradual return. No time-of-day rules.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import floor, isfinite

from .charging_window import ChargingWindow, Point

STEP_KW = 0.2
RISE_KW = 0.4
GUARD_KW = 0.2
RISE_INTERVAL = timedelta(minutes=5)
PEAK_MEMORY = timedelta(minutes=60)
PEAK_VALID_FOR = timedelta(seconds=60)
MIN_SLACK_MINUTES = 20.0  # Candidate M1 value, not production calibration.
DOMESTIC_CYCLE_QUIET = timedelta(minutes=35)  # Candidate from filtered 25-37m gaps.


def _good(value, allow_zero=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and isfinite(value) and (value >= 0 if allow_zero else value > 0))


def _floor_step(value):
    return round(floor((value + 1e-9) / STEP_KW) * STEP_KW, 3)


@dataclass(frozen=True)
class PolicyConfig:
    available_kw: float
    alarm_kw: float
    nominal_cap_kw: float
    minimum_cap_kw: float = 1.4

    def __post_init__(self):
        if not all(_good(v) for v in (self.available_kw, self.alarm_kw,
                                      self.nominal_cap_kw, self.minimum_cap_kw)):
            raise ValueError("invalid power configuration")
        if self.alarm_kw < self.available_kw or self.minimum_cap_kw > self.nominal_cap_kw:
            raise ValueError("invalid power bounds")


@dataclass(frozen=True)
class Proposal:
    action: str  # inactive / hold / reduce / raise / restore / insufficient_data
    cap_kw: float | None
    reason: str
    count_recent_peaks: int


class SimulatedCapPolicy:
    """Volatile event-driven policy. cap_kw is an IMAGINARY cap, not confirmed BLE.

    An eventual HA adapter must not treat proposals as executed/confirmed writes.
    Session lifecycle is explicit; every sample is discarded on stop.
    """

    def __init__(self, config: PolicyConfig):
        self.config = config
        self.window = ChargingWindow()
        self.cap_kw = config.nominal_cap_kw
        self._last_change: datetime | None = None
        self._last_peak: datetime | None = None
        self._recent_peaks: deque[datetime] = deque()
        self._pending_peak: Point | None = None
        self._over_alarm = False
        self._peak_house_kw: float | None = None
        self._last_domestic_busy: datetime | None = None

    def set_charging(self, charging: bool):
        self.window.set_charging(charging)
        if not charging:
            self.cap_kw = self.config.nominal_cap_kw
            self._last_change = None
            self._last_peak = None
            self._recent_peaks.clear()
            self._pending_peak = None
            self._over_alarm = False
            self._peak_house_kw = None
            self._last_domestic_busy = None

    def observe(self, at: datetime, house_kw: float | None,
                total_kw: float | None, coherent: bool = True) -> bool:
        """Observe coherent Shelly sample; only crossing BELOW->ABOVE arms peak.

        Incoherent samples do not rearm an already-high alarm. House explicitly
        excludes wallbox and is computed by a separate HA adapter.
        """
        if not self.window.add(at, house_kw, total_kw=total_kw, coherent=coherent):
            return False
        point = Point(at, float(house_kw), float(total_kw)) if (
            coherent and _good(house_kw, allow_zero=True) and
            _good(total_kw, allow_zero=True)
        ) else Point(at, None, None)
        if point.total_kw is not None and point.house_kw is not None:
            if (self.cap_kw < self.config.nominal_cap_kw
                    and self._peak_house_kw is not None
                    and point.house_kw >= max(1.0, self._peak_house_kw * .70)):
                self._last_domestic_busy = at
            above = point.total_kw >= self.config.alarm_kw
            if above and not self._over_alarm:
                self._pending_peak = point
                self._recent_peaks.append(at)
                self._last_peak = at
            self._over_alarm = above
        return True

    def evaluate(self, now: datetime, slack_minutes: float | None) -> Proposal:
        if not self.window.charging:
            return Proposal("inactive", None, "not_charging", 0)
        if (now.tzinfo is None or now.utcoffset() is None or
                (slack_minutes is not None and not _good(slack_minutes, allow_zero=True))):
            return Proposal("insufficient_data", None, "invalid_planning_data", 0)
        while self._recent_peaks and now - self._recent_peaks[0] > PEAK_MEMORY:
            self._recent_peaks.popleft()
        peaks = len(self._recent_peaks)
        pending = self._pending_peak
        self._pending_peak = None
        if (pending is not None and timedelta(0) <= now - pending.at <= PEAK_VALID_FOR):
            if slack_minutes is None:
                return Proposal("insufficient_data", None, "unknown_departure_slack", peaks)
            if slack_minutes >= MIN_SLACK_MINUTES:
                proposed = _floor_step(self.config.available_kw - pending.house_kw - GUARD_KW)
                if (self.config.minimum_cap_kw <= proposed < self.cap_kw and
                        (self._last_change is None or now - self._last_change >= timedelta(minutes=2))):
                    self.cap_kw = proposed  # Simulation ONLY.
                    self._peak_house_kw = pending.house_kw
                    self._last_domestic_busy = now
                    self._last_change = now
                    return Proposal("reduce", proposed, "single_verified_alarm", peaks)
                return Proposal("hold", self.cap_kw, "no_useful_extra_cap", peaks)
            return Proposal("hold", self.cap_kw, "planner_vetoes_extra_reduction", peaks)
        if slack_minutes is None:
            return Proposal("insufficient_data", None, "unknown_departure_slack", peaks)
        if self.cap_kw >= self.config.nominal_cap_kw:
            return Proposal("hold", self.cap_kw, "no_optional_cap_active", peaks)
        if not self.window.has_fresh_reading(now):
            return Proposal("insufficient_data", None, "stale_or_incoherent_source", peaks)
        if slack_minutes < MIN_SLACK_MINUTES:
            # Planned escape from our OWN cap only. Hardware DPM is not touched.
            self.cap_kw = self.config.nominal_cap_kw
            self._peak_house_kw = None
            self._last_domestic_busy = None
            self._last_change = now
            return Proposal("restore", self.cap_kw, "deadline_requires_normal_cap", peaks)
        if (self._last_domestic_busy and
                now - self._last_domestic_busy < DOMESTIC_CYCLE_QUIET):
            return Proposal("hold", self.cap_kw, "domestic_cycle_quiet_window", peaks)
        if (self._last_change and now - self._last_change < RISE_INTERVAL):
            return Proposal("hold", self.cap_kw, "cooldown", peaks)
        result = self.window.assess_rise(
            now, current_limit_kw=self.cap_kw,
            original_limit_kw=self.config.nominal_cap_kw,
            available_kw=self.config.available_kw,
            margin_kw=GUARD_KW, step_kw=STEP_KW, increment_kw=RISE_KW,
        )
        if result.status == "insufficient_data":
            return Proposal("insufficient_data", None, result.reason, peaks)
        if result.status == "raise" and result.proposed_limit_kw is not None:
            self.cap_kw = result.proposed_limit_kw  # Simulation ONLY.
            self._last_change = now
            return Proposal("raise", self.cap_kw, "whole_window_supports_raise", peaks)
        return Proposal("hold", self.cap_kw, result.reason, peaks)
