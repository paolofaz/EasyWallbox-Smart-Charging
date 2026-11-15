"""Pure per-connection user intent and observable session phase.

The state is RAM-only in v0.1. HA restart with a cable already connected
requires explicit reconciliation; an old PAUSE/MANUAL choice is never silently
assumed to have expired. User actions change *simulation intent* only.
No wallbox, vehicle, HA service, BLE, or file access is implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

AUTO = "AUTO"
MANUAL = "MANUAL"
PAUSE = "PAUSE"
CHARGE_NOW = "CHARGE_NOW"
RECONCILE = "RECONCILE"

USER_MODES = (AUTO, MANUAL, PAUSE, CHARGE_NOW)


@dataclass(frozen=True)
class SessionControl:
    session_id: str | None = None
    mode: str = AUTO
    phase: str = "DISCONNECTED"  # Observed, never inferred from UI intent
    reason: str = "no_connected_session"
    simulation_only: bool = True

    @property
    def requires_confirmation(self) -> bool:
        return self.mode == RECONCILE


def observe(
    previous: SessionControl | None,
    *,
    session_id: str | None,
    connection: bool | None,
    charging: bool,
    ambiguous: bool = False,
    target_reached: bool = False,
) -> SessionControl:
    """Reconcile a coherent physical observation with session-local intent.

    connection=False must mean **confirmed** disconnection from wallbox AND EV
    sensors. Unknown/unavailable/contradictory inputs must use connection=None.
    """
    if not isinstance(charging, bool) or not isinstance(ambiguous, bool):
        raise ValueError("invalid observed boolean")
    if connection is not None and not isinstance(connection, bool):
        raise ValueError("invalid connection observation")

    if connection is False:
        return SessionControl()
    if connection is None or ambiguous or not session_id:
        if previous is None:
            return SessionControl(mode=RECONCILE, phase="UNKNOWN",
                                  reason="startup_connection_not_trusted")
        return replace(previous, phase="UNKNOWN",
                       reason="connection_unavailable_or_ambiguous")

    if previous is None:
        # Cable found connected on HA bootstrap: previous user pause is unknown.
        mode, reason = RECONCILE, "startup_connected_requires_confirmation"
    elif previous.session_id != session_id:
        if previous.phase == "DISCONNECTED":
            mode, reason = AUTO, "new_connection_default_automatic"
        else:
            # Vehicle changed without a trusted disconnect between sessions.
            mode, reason = RECONCILE, "vehicle_changed_without_disconnect"
    else:
        mode, reason = previous.mode, "session_continues"

    if mode == RECONCILE:
        phase = "RECONCILE"
    elif charging:
        phase = "CHARGING"  # This is an observation, not a virtual command.
        if mode == PAUSE:
            reason = "virtual_pause_does_not_stop_real_charge"
    elif target_reached:
        phase = "TARGET_REACHED"
    else:
        phase = "CONNECTED_NOT_CHARGING"
    return SessionControl(session_id=session_id, mode=mode, phase=phase,
                          reason=reason)


def user_select_mode(state: SessionControl, requested: str) -> SessionControl:
    """Apply an explicit per-session UI choice, with no electrical effect."""
    if requested not in USER_MODES:
        raise ValueError("unsupported session mode")
    if state.session_id is None or state.phase in ("DISCONNECTED", "UNKNOWN"):
        raise ValueError("no reliably identified connected session")
    reason = {
        AUTO: "user_selected_automatic",
        MANUAL: "user_took_manual_ownership",
        PAUSE: "explicit_user_pause_simulation_only",
        CHARGE_NOW: "explicit_user_charge_now_simulation_only",
    }[requested]
    return replace(state, mode=requested, reason=reason)
