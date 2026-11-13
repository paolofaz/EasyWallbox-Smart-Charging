"""Conservative, read-only appraisal of one optional anticipatable home load.

The function NEVER sends commands. Results are hypothetical and do not
replace the wallbox DPM, which handles the immediate electrical peaks.
"""

from dataclasses import dataclass
from math import floor, isfinite


@dataclass(frozen=True)
class LoadScenario:
    available_site_kw: float
    observed_house_kw: float
    confirmed_ev_limit_kw: float
    missing_battery_kwh: float
    efficiency: float
    remaining_usable_hours: float
    active: bool | None
    additional_peak_kw: float
    estimated_active_minutes: float


@dataclass(frozen=True)
class Advice:
    code: str
    proposed_ev_limit_kw: float | None
    current_ev_limit_kw: float | None
    worst_house_kw: float | None
    lost_grid_kwh: float | None
    grid_energy_margin_kwh: float | None


def evaluate_load(s: LoadScenario) -> Advice:
    """Assess a single active-load event without chasing instantaneous spikes.

    The configured peak is assumed ADDITIONAL to the observed house load,
    deliberately conservative and potentially double-counting a peak that
    is already visible. A recommendation is ONLY hypothetical.

    Missing/unknown/invalid readings yield no new recommendation.
    """
    def result(code, proposed=None, base=None, worst=None, loss=None, margin=None):
        return Advice(code, proposed, base, worst, loss, margin)

    values = (
        s.available_site_kw, s.observed_house_kw, s.confirmed_ev_limit_kw,
        s.missing_battery_kwh, s.efficiency, s.remaining_usable_hours,
        s.additional_peak_kw, s.estimated_active_minutes,
    )
    if (
        any(isinstance(v, bool) or not isinstance(v, (float, int))
            or not isfinite(v) for v in values)
        or s.available_site_kw <= 0 or s.observed_house_kw < 0
        or s.confirmed_ev_limit_kw < 1.4 or s.missing_battery_kwh < 0
        or not 0 < s.efficiency <= 1 or s.remaining_usable_hours <= 0
        or s.additional_peak_kw <= 0 or s.estimated_active_minutes <= 0
    ):
        return result("insufficient_data")
    if s.active is None:
        return result("load_state_unknown")
    if not s.active:
        return result("load_inactive")

    # Not a high-speed DPM calculation: scenario at a deliberately
    # hypothetical worst-case house load, based on an extra load peak.
    worst_house = s.observed_house_kw + s.additional_peak_kw
    baseline_kw = min(
        s.confirmed_ev_limit_kw,
        max(0, s.available_site_kw - s.observed_house_kw),
    )
    if baseline_kw < 1.4:
        return result("dpm_handles_peak", None, round(baseline_kw, 2),
                      round(worst_house, 2))
    required_grid_kwh = s.missing_battery_kwh / s.efficiency
    margin_kwh = baseline_kw * s.remaining_usable_hours - required_grid_kwh
    if margin_kwh <= 0:
        return result("priority_departure_keep_limit", None,
                      round(baseline_kw, 2), round(worst_house, 2),
                      None, round(margin_kwh, 2))

    # Firmware slider: 1.4 kW minimum in 0.2 kW steps. Only evaluate
    # reductions on that grid; DO NOT write a number entity.
    safe_kw = max(
        0, s.available_site_kw - worst_house
    )
    target_kw = floor((safe_kw + 1e-8) / 0.2) * 0.2
    target_kw = round(target_kw, 1)
    if target_kw < 1.4:
        return result("dpm_handles_peak", None,
                      round(baseline_kw, 2), round(worst_house, 2),
                      None, round(margin_kwh, 2))
    if target_kw >= baseline_kw - 0.19:
        return result("keep_limit_no_meaningful_reduction", None,
                      round(baseline_kw, 2), round(worst_house, 2),
                      0.0, round(margin_kwh, 2))

    hours = min(s.remaining_usable_hours, s.estimated_active_minutes / 60)
    loss = (baseline_kw - target_kw) * hours
    if loss > margin_kwh + 1e-8:
        return result("priority_departure_keep_limit", None,
                      round(baseline_kw, 2), round(worst_house, 2),
                      round(loss, 2), round(margin_kwh, 2))
    return result("temporary_reduction_possible", target_kw,
                  round(baseline_kw, 2), round(worst_house, 2),
                  round(loss, 2), round(margin_kwh, 2))
