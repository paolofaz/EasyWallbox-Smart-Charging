"""Pure preflight for a *future* supervised EV-limit adapter.

This module does not issue commands, approve them, or write persistent state.
Its output is only an offer for a separately authorized human-in-the-loop
workflow. Neither V2's infinite virtual car nor a UI switch constitutes
an authorization to actuate a wallbox.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import floor, isfinite

MIN_EV_KW = 1.4
EV_STEP_KW = 0.2
MAX_OBSERVATION_AGE = timedelta(seconds=120)


def deciamps(display_kw: float) -> int:
    """Convert ESPHome's kW display convention to 0.1 A BLE units.

    Not an estimate of active watts, DPM sensor current or Shelly power.
    """
    if (isinstance(display_kw, bool) or not isinstance(display_kw, (int, float))
            or not isfinite(display_kw) or display_kw <= 0):
        raise ValueError("invalid_positive_limit")
    return floor(display_kw / 0.230 * 10 + 0.5)


def _valid_ev_step(kw: float) -> bool:
    return (isinstance(kw, (int, float)) and not isinstance(kw, bool)
            and isfinite(kw) and kw >= MIN_EV_KW
            and abs((kw - MIN_EV_KW) / EV_STEP_KW
                    - round((kw - MIN_EV_KW) / EV_STEP_KW)) < 1e-6)


@dataclass(frozen=True)
class ElectricalObservation:
    """A timestamped readback; all facts must be independently observed.

    requested_kw: ESPHome number, a *request* only.
    confirmed_kw: ESPHome Power set BLE-confirmed EV limit.
    dpm_confirmed_kw: ESPHome DPM-confirmed house limit; must be > 0.
    meter_valid: fresh, plausible dedicated Shelly wallbox measurement.
    """
    session_id: str | None
    user_mode: str
    connected: bool | None
    charging: bool | None
    ble_connected: bool | None
    telemetry_fresh: bool | None
    wallbox_fault: bool | None
    dpm_active: bool | None
    requested_kw: float | None
    confirmed_kw: float | None
    dpm_confirmed_kw: float | None
    meter_valid: bool
    observed_at: datetime | None


@dataclass(frozen=True)
class LimitLease:
    """Journal record for a command confirmed in a *future* adapter.

    Creating this record is NOT evidence that any BLE command was sent.
    After HA restarts, recovered=True must be set by the new process and
    every change needs explicit re-arming; no automatic restores on boot.
    """
    session_id: str
    baseline_raw: int
    owned_raw: int
    last_requested_raw: int
    last_confirmed_raw: int
    recovered: bool = False


@dataclass(frozen=True)
class Offer:
    """An offer is never an executable instruction."""
    status: str  # blocked | no_change | offer
    reason: str
    action: str | None = None
    target_raw: int | None = None
    original_raw: int | None = None
    requires_user_approval: bool = True


def _blocked(reason: str) -> Offer:
    return Offer("blocked", reason)


def _observed(obs: ElectricalObservation, now: datetime,
              expected_dpm_kw: float | None) -> str | None:
    if not isinstance(now, datetime) or now.tzinfo is None:
        return "clock_not_trusted"
    if (obs.observed_at is None or obs.observed_at.tzinfo is None
            or not timedelta(0) <= now - obs.observed_at <= MAX_OBSERVATION_AGE):
        return "electrical_observation_stale"
    if not obs.session_id or obs.connected is not True:
        return "session_not_confirmed"
    if obs.ble_connected is not True or obs.telemetry_fresh is not True:
        return "ble_or_telemetry_untrusted"
    if obs.wallbox_fault is not False:
        return "wallbox_fault_or_unknown"
    if obs.dpm_active is not True:
        return "dpm_not_confirmed_active"
    if obs.charging is not True:
        return "not_observed_charging"
    if obs.meter_valid is not True:
        return "ev_meter_not_trusted"
    try:
        if expected_dpm_kw is None:
            return "dpm_expected_limit_missing"
        dpm_raw = deciamps(obs.dpm_confirmed_kw)
        expected_dpm_raw = deciamps(expected_dpm_kw)
        requested_raw = deciamps(obs.requested_kw)
        confirmed_raw = deciamps(obs.confirmed_kw)
    except (TypeError, ValueError):
        return "readback_invalid"
    if dpm_raw != expected_dpm_raw:
        return "dpm_limit_changed_or_paused"
    if requested_raw != confirmed_raw:
        return "request_not_ble_confirmed"
    return None


def assess_limit_offer(
    now: datetime,
    observation: ElectricalObservation,
    *,
    expected_dpm_kw: float | None,
    action: str,
    proposed_kw: float,
    planner_allows: bool,
    lease: LimitLease | None = None,
) -> Offer:
    """Preflight for a proposal, with zero side effects and no dispatch.

    Only AUTO+charging, independently confirmed observations and a positive
    planner budget may offer a reduction. Restores require a previously
    confirmed owned cap; even a matching lease recovered from storage remains
    blocked pending an explicit recovery procedure and human authorization.
    """
    if observation.user_mode != "AUTO":
        return _blocked("user_mode_not_auto")
    problem = _observed(observation, now, expected_dpm_kw)
    if problem:
        return _blocked(problem)
    if planner_allows is not True:
        return _blocked("planner_budget_or_target_not_verified")
    if action not in ("reduce", "adjust", "restore"):
        return _blocked("unsupported_action")
    if not _valid_ev_step(proposed_kw):
        return _blocked("proposed_ev_step_invalid")

    current = deciamps(observation.confirmed_kw)
    requested = deciamps(observation.requested_kw)
    target = deciamps(proposed_kw)
    if lease is None:
        if action != "reduce":
            return _blocked("no_owned_limit_to_adjust_or_restore")
        if target >= current:
            return _blocked("reduction_not_lower_than_confirmed")
        return Offer("offer", "new_lease_requires_manual_approval", action,
                     target, current)

    if lease.recovered:
        return _blocked("restart_requires_explicit_reconciliation")
    if lease.session_id != observation.session_id:
        return _blocked("session_changed")
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0
           for v in (lease.baseline_raw, lease.owned_raw,
                     lease.last_requested_raw, lease.last_confirmed_raw)):
        return _blocked("lease_invalid")
    if lease.owned_raw != lease.last_requested_raw or lease.owned_raw != lease.last_confirmed_raw:
        return _blocked("previous_command_unconfirmed")
    if current != lease.owned_raw or requested != lease.owned_raw:
        return _blocked("manual_override_or_readback_mismatch")
    if lease.owned_raw > lease.baseline_raw:
        return _blocked("lease_above_authorized_original")
    if action == "restore":
        if target != lease.baseline_raw:
            return _blocked("restore_not_original_limit")
        if target < current:
            return _blocked("restore_would_reduce")
    elif target >= current:
        return _blocked("reduction_not_lower_than_confirmed")
    if target > lease.baseline_raw:
        return _blocked("target_above_authorized_original")
    if target == current:
        return Offer("no_change", "already_ble_confirmed")
    return Offer("offer", "owned_limit_requires_manual_approval", action,
                 target, lease.baseline_raw)


def reconcile_after_restart(observation: ElectricalObservation,
                            lease: LimitLease | None,
                            now: datetime,
                            *, expected_dpm_kw: float | None) -> Offer:
    """Return diagnostics only. Never automatically lift a cap on startup."""
    if lease is None:
        return _blocked("no_persisted_ownership_evidence")
    problem = _observed(observation, now, expected_dpm_kw)
    if problem:
        return _blocked(problem)
    if lease.session_id != observation.session_id:
        return _blocked("session_changed")
    if (deciamps(observation.confirmed_kw) != lease.last_confirmed_raw
            or deciamps(observation.requested_kw) != lease.last_requested_raw):
        return _blocked("ownership_disputed_manual_intervention_possible")
    return _blocked("restart_requires_explicit_reconciliation")
