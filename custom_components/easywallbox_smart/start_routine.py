"""Pure BENCH simulator for Automatic vs Manual and pre-plug DPM arming.

No imports from Home Assistant, no BLE, service calls, or persistence.
An offered action requires a separately authorized and validated executor;
neither a proposal nor a UI state means any electrical change occurred.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import floor, isfinite


def nominal_deciamps(kw: float, *, zero: bool = False) -> int:
    """Use ESPHome's nominal 230 V / 0.1 A coding, not actual Shelly watts."""
    if (isinstance(kw, bool) or not isinstance(kw, (float, int))
            or not isfinite(kw) or kw < 0 or (kw == 0 and not zero)):
        raise ValueError("invalid_nominal_kw")
    return floor(kw / 0.230 * 10 + .5)


def ev_step_ok(kw: float) -> bool:
    return (isinstance(kw, (float, int)) and not isinstance(kw, bool)
            and isfinite(kw) and kw >= 1.4
            and abs((kw - 1.4)/.2 - round((kw - 1.4)/.2)) < 1e-6)


def _aware(value: datetime | None) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class BenchInputs:
    now: datetime
    mode: str                      # AUTO | MANUAL | PAUSE | CHARGE_NOW | RECONCILE
    wallbox_cable: bool | None
    vehicle_cable: bool | None    # all configured EV identities reconciled externally
    session_id: str | None
    vehicle_id: str | None
    target_reached: bool | None  # a FRESH source, not assumed False for unknown
    ble_ready: bool
    data_valid: bool              # adapter must check *all* source ages
    wallbox_fault: bool | None
    dpm_active: bool | None       # DPM physical enable, separate from 0-A pause
    dpm_confirmed_kw: float | None
    dpm_original_kw: float | None # confirmed positive baseline before arming
    ev_requested_kw: float | None
    ev_confirmed_kw: float | None
    ev_session_max_kw: float
    charging: bool | None
    arm_owner: str = "none"       # none | johnny | external | unknown
    auto_park_enabled: bool = False  # explicit opt-in, not a permanent idle loop
    arm_attempted: bool = False     # durable future adapter must track attempts
    user_override: bool = False
    preferred_start_at: datetime | None = None
    latest_safe_start_at: datetime | None = None


@dataclass(frozen=True)
class BenchAdvice:
    phase: str
    action: str                    # none | offer_park | offer_ev_limit | offer_resume
    reason: str
    target_kw: float | None = None
    simulation_only: bool = True
    requires_explicit_authorization: bool = True


def _none(phase: str, reason: str) -> BenchAdvice:
    return BenchAdvice(phase, "none", reason)


def evaluate_bench(data: BenchInputs) -> BenchAdvice:
    """Evaluate one consolidated, fresh snapshot; NO side effects.

    Entry into AUTO_READY is an explicitly authorized one-shot pre-plug
    operation. On restart or manual modification, future adapter must mark
    ownership unknown, not keep issuing DPM=0. A prior unconfirmed arm is not
    retried. Start/stop logic is *not* implemented in this simulator.
    """
    if not _aware(data.now):
        return _none("BLOCKED", "invalid_clock")
    if data.mode == "MANUAL":
        return _none("MANUAL", "manual_controls_only")
    if data.mode == "PAUSE":
        return _none("PAUSED", "explicit_pause_not_overridden")
    if data.mode == "RECONCILE" or data.mode not in ("AUTO", "CHARGE_NOW"):
        return _none("RECONCILE", "mode_requires_confirmation")
    if data.user_override:
        return _none("RECONCILE", "external_manual_intervention")
    if (data.wallbox_cable is None or data.vehicle_cable is None
            or data.wallbox_cable != data.vehicle_cable):
        return _none("RECONCILE", "cable_connection_untrusted")
    if (data.ble_ready is not True or data.data_valid is not True
            or data.wallbox_fault is not False or data.dpm_active is not True):
        return _none("BLOCKED", "electrical_sources_untrusted")
    try:
        dpm = nominal_deciamps(data.dpm_confirmed_kw, zero=True)
    except (TypeError, ValueError):
        return _none("BLOCKED", "dpm_readback_unavailable")
    if data.arm_owner not in ("none", "johnny", "external", "unknown"):
        return _none("RECONCILE", "ownership_invalid")

    # Disconnected: the only potential offer is a single, opt-in arming
    # request. Never alter EV charge power or start/resume without a car.
    if data.wallbox_cable is False:
        if dpm == 0:
            return _none("AUTO_READY" if data.arm_owner == "johnny"
                         else "RECONCILE",
                         "preplug_pause_confirmed" if data.arm_owner == "johnny"
                         else "zero_dpm_without_proven_ownership")
        if data.arm_owner != "none":
            return _none("RECONCILE", "external_dpm_change_or_unreconciled_arm")
        if not data.auto_park_enabled:
            return _none("DISCONNECTED", "preplug_arm_not_selected")
        if data.arm_attempted:
            return _none("RECONCILE", "arm_attempt_pending_no_blind_retry")
        try:
            baseline = nominal_deciamps(data.dpm_original_kw)
        except (TypeError, ValueError):
            return _none("BLOCKED", "original_dpm_not_confirmed")
        if baseline != dpm:
            return _none("RECONCILE", "original_dpm_differs_from_readback")
        return BenchAdvice("DISCONNECTED", "offer_park",
                           "offer_one_preplug_dpm_zero", 0.0)

    # Connected, uniquely identified and fresh: session decisions begin here.
    if not data.session_id or not data.vehicle_id:
        return _none("RECONCILE", "vehicle_or_session_not_identified")
    if data.target_reached is None:
        return _none("BLOCKED", "soc_or_target_not_trusted")
    if data.target_reached is True:
        return _none("COMPLETED", "target_reached_no_automatic_restart")
    if dpm == 0 and data.charging is True:
        return _none("BLOCKED", "charging_conflicts_with_zero_dpm")
    if data.arm_owner in ("external", "unknown"):
        return _none("RECONCILE", "pause_or_limit_not_owned")

    # A preferred start time is soft: do not wait beyond latest safe start.
    if (data.mode != "CHARGE_NOW" and data.preferred_start_at is not None
            and _aware(data.preferred_start_at)
            and data.preferred_start_at > data.now
            and data.latest_safe_start_at is not None
            and _aware(data.latest_safe_start_at)
            and data.latest_safe_start_at > data.now):
        if dpm == 0 and data.arm_owner == "johnny":
            return _none("WAIT_SCHEDULE", "preplug_pause_holds_until_start")
        # If not armed, a charge may already have begun. Never claim otherwise.
        return _none("RECONCILE", "scheduled_wait_not_armed")
    if data.preferred_start_at is not None and not _aware(data.preferred_start_at):
        return _none("BLOCKED", "scheduled_start_invalid")

    if dpm > 0:
        if data.charging is True:
            return _none("CHARGING_NORMAL", "real_charge_observed_johnny_may_monitor")
        if data.charging is None:
            return _none("BLOCKED", "charging_state_untrusted")
        return _none("CONNECTED", "positive_dpm_no_blind_restart")

    # Resuming a DPM=0 pause is only possible with a provable Johnny lease.
    if data.arm_owner != "johnny":
        return _none("RECONCILE", "zero_dpm_without_proven_ownership")
    try:
        baseline = nominal_deciamps(data.dpm_original_kw)
        requested = nominal_deciamps(data.ev_requested_kw)
        confirmed = nominal_deciamps(data.ev_confirmed_kw)
        target = nominal_deciamps(data.ev_session_max_kw)
    except (TypeError, ValueError):
        return _none("BLOCKED", "baseline_or_ev_readback_untrusted")
    if not ev_step_ok(data.ev_session_max_kw):
        return _none("BLOCKED", "ev_max_outside_confirmed_step")
    if baseline <= 0:
        return _none("BLOCKED", "invalid_dpm_restore_baseline")
    if requested != confirmed:
        return _none("WAIT_ACK", "ev_limit_confirmation_pending")
    if confirmed != target:
        return BenchAdvice("PREPARE_CHARGE", "offer_ev_limit",
                           "set_ev_baseline_before_dpm_resume",
                           data.ev_session_max_kw)
    return BenchAdvice("PREPARE_CHARGE", "offer_resume",
                       "ev_limit_confirmed_resume_original_dpm",
                       data.dpm_original_kw)
