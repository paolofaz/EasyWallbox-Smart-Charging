"""Event-driven real charging controller with one exclusive command owner.

In ordinary sessions the wallbox starts charging autonomously.
Only an explicitly armed, pre-plug delay may change DPM Start-Stop before
vehicle identity becomes available. Safety readbacks remain independent.
A Home Assistant service success is not a BLE acknowledgement.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, time, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import *
from .decision_journal import DecisionJournal
from .session_archive import SessionArchive
from .sources import finite_number, on, power_kw, next_departure
from .power_policy import Observation, State, evaluate, dpm_only_kw
from .planner_rate import (estimate_ac_kw, estimate_forecast_ac_kw,
                           margin_minutes as estimate_margin)
from .delay_window import validate_delay

_LOGGER = logging.getLogger(__name__)
WALLBOX_TTL = timedelta(minutes=2)
DPM_TTL = timedelta(minutes=5)
SHELLY_TTL = timedelta(minutes=3)
HOUSE_MAX_SKEW = timedelta(seconds=150)  # Two independent Shelly clocks
CAR_TTL = timedelta(minutes=30)
ACK_TIMEOUT = timedelta(minutes=3)
SOC_STOP_TTL = timedelta(minutes=5)
SOC_STOP_REFRESH_INTERVAL = timedelta(minutes=20)


@dataclass
class Pending:
    kind: str
    target: float
    since: datetime
    next_state: State | None = None
    operation: str = ""
    session: str | None = None
    dispatched: bool = False
    readback_seen: bool = False
    cable: bool | None = None
    soc_stop_target: float | None = None
    vehicle: str | None = None
    cable_marker: str | None = None


class ChargingController:
    """Single local controller with no blind retry and no retained action lease."""

    def __init__(self, hass: HomeAssistant, entry, version: str):
        self.hass, self.entry = hass, entry
        # prior iterations's retired boost_kw may remain in older HA config-entry data.
        # Never read, restore or act on it. The only baseline is base_kw.
        self.cfg = {k: v for k, v in {**entry.data, **entry.options}.items()
                    if k != "boost_kw"}
        self.house_ids = tuple(self.cfg[CONF_HOUSE_SOURCES])
        self.session_power_kw = float(self.cfg[CONF_BASE_KW])  # Volatile, per physical plug-in
        self.mode = "automatic"
        self.real_enabled = False        # enabled by async_load after reconciliation
        self.delay_enabled = False
        self.preferred_start = time(23, 0)
        self.departure_override = None
        self.charge_now = False
        self.explicit_pause = False
        self.status = "Inizializzazione"
        self.reason = "startup"
        self.quality = "unknown"
        self.vehicle_name = None
        self.stop_at_target_enabled = None
        self.departure = None
        self.soc = None
        self.target_soc = None
        self.margin_minutes = None
        self.remaining_kwh = None
        self.charging_verified = None
        self.notice = "Nessun avviso"
        self._user_warning = None
        self._finish_display = None
        self._energy_display = None
        self._margin_energy_kwh = None  # Latest SOC adjusted by observed AC energy
        self.planning_rate_kw = None
        self._forecast_rate_kw = None
        self._forecast_quality = None
        self._house_history = deque(maxlen=96)
        self._ev_history = deque(maxlen=96)
        self._delivered_ev_kwh = 0.0  # Measured Shelly AC energy this session
        self._delivery_last = None  # (Shelly report timestamp, kW)
        self._delivery_gap = False
        self._soc_anchor = None  # (vehicle cable, SOC value, cumulative observed AC kWh)
        self._eta_remaining_ac_kwh = None
        self._margin_quality = None  # observed_complete | observed_partial_gap
        self._house_skew_seconds = None
        self._house_quality_reason = None
        self.house_kw = None
        self.last_command = None
        self.last_ack = None
        self._connection = False
        self._session_id = None
        self._journal = DecisionJournal(
            hass, entry, version,
            enabled=self.cfg.get(CONF_DIAGNOSTIC_LOGGING, DEFAULT_DIAGNOSTIC_LOGGING))
        self.session_history = SessionArchive(hass, entry, self.cfg, self._notify)
        self._trace_session = None
        self._gate_key = None
        self._last_diagnostic_at = None
        self._last_policy_reason = None
        self._facts = {}
        self._ble_since = None
        self._online = None
        self._closed = False
        self._cable_unsub = None
        self._connected_unsub = None
        self._saved_attempt = None
        self._save_lock = asyncio.Lock()
        self._save_tasks = set()
        self._active_departure = None
        self._active_departure_vehicle = None
        self._scheduled_at = None
        self._delay_pause_attempted = False
        self._last_cable = None
        self._unplug_since = None
        self._unplug_report_marker = None
        self._unplug_reports = 0
        self._unplug_interruption = False  # Positive state-3 awaiting second AD and 69s
        self._unplug_restore_pending = False  # Observed connected -> physically unplugged
        self._unplug_restore_since = None  # ON permitted only after 69s still unplugged
        # Optional, observed Shelly supply cycle. Never persisted/recovered from
        # HA startup, ESPHome restart, or BLE reconnect alone.
        self._supply_off_since = None
        self._supply_ble_off_seen = False
        self._supply_restore_candidate = None
        self._supply_ble_rejoined = False
        self._connect_since = None
        self._soc_stop_done = False
        self._soc_stop_latch = None
        self._standby_restore_due = False
        self._soc_resume_request = None
        self._soc_resume_refreshing = False
        self._soc_stop_refresh_at = None
        self._soc_stop_baseline = None
        self._fixed_target_overrides = {}
        self._refresh_due = None
        self._refresh_issued = False
        self._refresh_start_at = None
        self._refresh_count = 0
        self._refresh_requested_at = None
        self._refresh_deadline = None
        self._refresh_targets = ()
        self._refresh_error = None
        self._power_state: State | None = None
        self._owned_limit: float | None = None
        self._restart_power = None  # Persisted session evidence, never permission to command
        self._restart_review = False  # Persistent manual-review fence for an expired owned cap
        self._restart_review_info = None  # Previous ACK and expiry cause; not current BLE state
        self._dpm_lease: float | None = None
        self._saved_delay_lease = None
        self._pending: Pending | None = None
        self._blocked = None
        self._last_key = None
        self._listeners = set()
        self._sensor_unsub = None
        self._house_unsub = None
        self._idle_guard_unsub = None
        self._timer_unsub = None
        self._task = None
        self._refresh_task = None
        self._park_task = None
        self._park_required = False
        self._idle_park_trace = None
        self._lock = asyncio.Lock()
        self._store = Store(hass, 1, "easywallbox_smart_rc_" + entry.entry_id)

    async def async_load(self):
        saved = await self._store.async_load() or {}
        await self.session_history.async_load()
        self.mode = saved.get("mode") if saved.get("mode") in ("automatic", "manual") else "automatic"
        self.delay_enabled = bool(saved.get("delay", False))
        try:
            saved_schedule = saved.get("scheduled_at")
            value = datetime.fromisoformat(saved_schedule) if saved_schedule else None
            self._scheduled_at = value if value and value.utcoffset() is not None else None
        except (ValueError, TypeError):
            self._scheduled_at = None
        if self.delay_enabled and self._scheduled_at is None:
            self.delay_enabled = False
        try:
            active = saved.get("active_departure")
            value = datetime.fromisoformat(active) if active else None
            self._active_departure = value if value and value.utcoffset() is not None else None
            self._active_departure_vehicle = (
                saved.get("active_departure_vehicle")
                if self._active_departure is not None else None)
        except (ValueError, TypeError):
            self._active_departure = self._active_departure_vehicle = None
        self._fixed_target_overrides = (saved.get("fixed_target_overrides", {})
                                        if isinstance(saved.get("fixed_target_overrides", {}), dict)
                                        else {})
        lease = saved.get("delayed_lease")
        self._saved_delay_lease = lease if isinstance(lease, dict) else None
        soc_latch = saved.get("soc_stop_latch")
        self._soc_stop_latch = (soc_latch if isinstance(soc_latch, dict)
                                and soc_latch.get("vehicle") else None)
        self._soc_stop_done = self._soc_stop_latch is not None
        self._standby_restore_due = bool(saved.get("soc_stop_release_due", False))
        resume = saved.get("soc_resume_request")
        self._soc_resume_request = (resume if isinstance(resume, dict)
                                     and resume.get("vehicle") is not None
                                     and resume.get("target") is not None else None)
        if (self.delay_enabled and self._saved_delay_lease is None and
                not saved.get("unresolved_command")):
            # A scheduled flag without a proven prior OFF cannot block
            # ordinary charging across a restart.
            self.delay_enabled = False
            self._scheduled_at = None
        try:
            self.preferred_start = time.fromisoformat(saved.get("start", "23:00"))
        except (TypeError, ValueError):
            self.preferred_start = time(23, 0)
        try:
            override = saved.get("departure")
            value = datetime.fromisoformat(override) if override else None
            self.departure_override = value if value and value.utcoffset() is not None else None
        except (TypeError, ValueError):
            self.departure_override = None
        # Installing the integration starts automatic management by default.
        # No electrical command is allowed without fresh BLE/EV/Shelly facts.
        self.real_enabled = True
        self._owned_limit = self._dpm_lease = self._pending = None
        self._saved_attempt = saved.get("unresolved_command")
        recovery = saved.get("power_session")
        self._restart_review = saved.get("restart_review") is True
        info = saved.get("restart_review_info")
        self._restart_review_info = (
            info if self._restart_review and isinstance(info, dict) else None)
        self._restart_power = (
            recovery if isinstance(recovery, dict) and not self._restart_review
            else None)
        if self._saved_attempt:
            self._blocked = "previous_command_unconfirmed_no_retry"
            self.real_enabled = False
        elif self._restart_review:
            # The previous HA boot expired evidence for an owned cap.
            # An unrelated reboot must not silently clear that safety fence.
            self._blocked = "restart_power_evidence_expired_manual_review"
            self.real_enabled = False

    async def _save(self):
        async with self._save_lock:
            await self._save_locked()

    async def _save_locked(self):
        await self._store.async_save({
            "mode": self.mode, "delay": self.delay_enabled,
            "unresolved_command": self._saved_attempt,
            "delayed_lease": self._saved_delay_lease,
            "soc_stop_latch": self._soc_stop_latch,
            "soc_stop_release_due": self._standby_restore_due,
            "soc_resume_request": self._soc_resume_request,
            "fixed_target_overrides": self._fixed_target_overrides,
            "restart_review": self._restart_review,
            "restart_review_info": (
                self._restart_review_info if self._restart_review else None),
            # Preserve unresolved evidence without renewing the timestamp;
            # after a manual-review fence, do not reintroduce an unowned
            # synthetic record that could later evade the persisted block.
            "power_session": (
                None if self._restart_review else
                self._restart_power if self._restart_power is not None
                else self._saved_power_snapshot()),
            "active_departure": (
                self._active_departure.isoformat() if self._active_departure else None),
            "active_departure_vehicle": self._active_departure_vehicle,
            "start": self.preferred_start.isoformat(timespec="minutes"),
            "scheduled_at": (self._scheduled_at.isoformat()
                             if self._scheduled_at and
                             (self.delay_enabled or self._saved_delay_lease)
                             else None),
            "departure": self.departure_override.isoformat()
            if self.departure_override else None,
        })


    def _saved_power_snapshot(self):
        """Save preference plus ACK-confirmed cap, not an action lease."""
        if not self._trace_session or not self._connection:
            return None
        if (self._owned_limit is None and
                abs(self.session_power_kw-float(self.cfg[CONF_BASE_KW])) <= .051):
            # No owned cap and no user override: nothing to reconcile at boot.
            return None
        state = self._power_state if self._owned_limit is not None else None
        return {
            "vehicle": self._connection,
            "desired_kw": self.session_power_kw,
            "default_kw": float(self.cfg[CONF_BASE_KW]),
            "confirmed_kw": self._owned_limit,
            "phase": state.phase if state else None,
            "cap_kw": state.cap_kw if state else None,
            "baseline_kw": state.baseline_kw if state else None,
            "kind": state.kind if state else None,
            "last_change": state.last_change.isoformat()
            if state and state.last_change else None,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _restart_record_timing(now, saved):
        """Return effective age, raw signed age seconds, and expiry cause.

        A clock at most two hours behind the original saved timestamp is
        tolerated without changing stored_at or extending its real 24h TTL.
        Negative raw age distinguishes a clock problem from a stale record.
        """
        try:
            recorded_at = datetime.fromisoformat(saved.get("stored_at"))
        except (TypeError, ValueError):
            return None, None, "invalid_timestamp"
        if recorded_at.utcoffset() is None:
            return None, None, "invalid_timestamp"
        raw_age = now-recorded_at
        age_s = round(raw_age.total_seconds(), 1)
        if raw_age < -timedelta(hours=2):
            return None, age_s, "clock_skew"
        if raw_age > timedelta(hours=24):
            return raw_age, age_s, "stale"
        return max(timedelta(0), raw_age), age_s, None

    @staticmethod
    def _restart_record_age(now, saved):
        """Compatibility facade used by restart reconciliation/tests."""
        return ChargingController._restart_record_timing(now, saved)[0]

    def _expire_restart_power(self, now, cable):
        """Discard stale proof while idle; fence only non-default owned caps.

        A NORMAL cap that equals the unchanged configured default is already
        the expected starting state, so expiring its evidence does not need
        to disable real control. LIMITED, overrides or inconsistent history
        remain blocked until reviewed, never silently normalized.
        """
        saved = self._restart_power
        if saved is None or cable is None:
            return
        age, age_s, expiry_cause = self._restart_record_timing(now, saved)
        if expiry_cause is None:
            return
        self._restart_power = None
        old_cap = finite_number(saved.get("confirmed_kw"))
        original_default = finite_number(saved.get("default_kw"))
        original_baseline = finite_number(saved.get("baseline_kw"))
        current_default = float(self.cfg[CONF_BASE_KW])
        needs_review = (
            old_cap is not None and
            (saved.get("phase") != "NORMAL" or
             original_default is None or original_baseline is None or
             abs(old_cap-original_default) > .051 or
             abs(old_cap-current_default) > .051 or
             abs(old_cap-original_baseline) > .051))
        if cable is True and needs_review:
            self._restart_review = True
            self._restart_review_info = {
                "last_confirmed_kw": old_cap,
                "expiry_cause": expiry_cause,
                "age_s": age_s,
                "stored_at": saved.get("stored_at"),
            }
            # Never mask an older unresolved-command interlock.
            if self._blocked is None:
                self._blocked = "restart_power_evidence_expired_manual_review"
            self.real_enabled = False
            self._record("reconciliation", "restart_power_evidence_expired_manual_review",
                         previous_cap_kw=old_cap, previous_phase=saved.get("phase"),
                         previous_default_kw=original_default,
                         original_stored_at=saved.get("stored_at"),
                         age_s=age_s, expiry_cause=expiry_cause,
                         active_block=self._blocked)
        else:
            self._record("reconciliation", "expired_restart_power_discarded",
                         physical_cable=cable, previous_phase=saved.get("phase"),
                         original_stored_at=saved.get("stored_at"),
                         age_s=age_s, expiry_cause=expiry_cause,
                         safe_normal_default=(cable is True and old_cap is not None and
                                              not needs_review))
        self._schedule_save()

    def _reconcile_restart_power(self, snapshot, identity, now):
        """Recover LIMITED from verified readbacks; never replay BLE commands.

        Post-restart quiet intervals must be observed anew. When a prior
        observed cap is still confirmed, LIMITED can leave by the normal
        urgency/15-minute quiet rules, not a forced immediate normalization.
        """
        saved = self._restart_power
        if saved is None or self._saved_attempt is not None:
            return
        if (snapshot["charging"] is not True or not snapshot["trusted"] or
                not snapshot["dpm_normal"]):
            return  # Wait for all physical and car sources, no commands.
        self._restart_power = None
        desired = finite_number(saved.get("desired_kw"))
        cap = finite_number(saved.get("confirmed_kw"))
        previous_default = finite_number(saved.get("default_kw"))
        age = self._restart_record_age(now, saved)
        if (saved.get("vehicle") != identity or age is None or
                age > timedelta(hours=24) or previous_default is None or
                abs(previous_default-float(self.cfg[CONF_BASE_KW])) > .051 or
                desired is None or not self._valid_session_power(desired)):
            self._record("reconciliation", "restart_preference_not_proven")
            return
        # Preference belongs to this same vehicle/physical plug-in.
        self.session_power_kw = desired
        if cap is None:
            self._record("reconciliation", "restart_preference_without_owned_cap",
                         desired_kw=desired)
            self._schedule_save()
            return
        if (snapshot["actual"] is None or snapshot["requested"] is None or
                abs(snapshot["actual"]-cap) > .051 or
                abs(snapshot["requested"]-cap) > .051):
            self._blocked = "restart_cap_mismatch_no_write"
            self.real_enabled = False
            self._record("reconciliation", self._blocked,
                         saved_cap_kw=cap, current_cap_kw=snapshot["actual"])
            return
        phase = saved.get("phase")
        base = finite_number(saved.get("baseline_kw"))
        previous_cap = finite_number(saved.get("cap_kw"))
        if (phase not in ("NORMAL", "LIMITED") or
                base is None or previous_cap is None or
                abs(previous_cap-cap) > .051 or
                (phase == "LIMITED" and cap >= base-.11) or
                (phase == "NORMAL" and abs(cap-base) > .11)):
            self._blocked = "restart_previous_policy_state_invalid"
            self.real_enabled = False
            self._record("reconciliation", self._blocked)
            return
        try:
            last_change = (datetime.fromisoformat(saved["last_change"])
                           if saved.get("last_change") else None)
        except (ValueError, TypeError):
            last_change = None
        if last_change is not None and (
                last_change.utcoffset() is None or
                not timedelta(0) <= now-last_change):
            last_change = None
        if phase == "LIMITED" and last_change is None:
            # The policy's quiet exit requires a start marker. After an
            # incomplete timestamp, conservatively start the hold NOW:
            # never keep a legitimate LIMITED cap forever by accident.
            last_change = now
        # No write: only adopt an independently confirmed register.
        self._owned_limit = cap
        self._power_state = State(
            session_id=self._session_id, phase=phase, cap_kw=cap,
            baseline_kw=base, kind=saved.get("kind") or "normal",
            last_change=last_change)
        self._record("reconciliation", "owned_power_session_restored",
                     phase=phase, confirmed_cap_kw=cap, desired_kw=desired,
                     quiet_history="reset_requires_new_shelly_reports")
        self._schedule_save()

    def fixed_target(self, car):
        """A fixed SOC from HA options or the persisted 80..100% slider."""
        if not car or CONF_TARGET_FIXED not in car:
            return None
        baseline = car[CONF_TARGET_FIXED]
        saved = self._fixed_target_overrides.get(car[CONF_CABLE])
        if (isinstance(saved, dict) and saved.get("configured") == baseline
                and saved.get("value") in (80, 85, 90, 95, 100)):
            return saved["value"]
        return baseline

    async def async_set_fixed_target(self, cable, value):
        """Persist one manual SOC target change, without changing DPM."""
        if (not isinstance(value, (int, float)) or
                not 80 <= float(value) <= 100 or float(value) % 5 != 0):
            raise ValueError("Il limite deve essere 80–100%, a passi di 5")
        car = next((x for x in self.cfg[CONF_VEHICLES]
                    if x[CONF_CABLE] == cable), None)
        if (car is None or car.get(CONF_STOP_AT_TARGET) is not True
                or CONF_TARGET_FIXED not in car):
            raise ValueError("Target fisso gestito non disponibile")
        previous_target = self.fixed_target(car)
        self._fixed_target_overrides[cable] = {
            "configured": car[CONF_TARGET_FIXED], "value": int(value)}
        self._record("user_intent", "fixed_soc_target", target_soc=int(value),
                     previous_target=previous_target,
                     vehicle_slot=self.cfg[CONF_VEHICLES].index(car) + 1)
        pending_soc = (self._pending.soc_stop_target
                       if self._pending and self._pending.kind == "soc_stop"
                       else None)
        owning_stop = (self._soc_stop_latch is not None and
                       self._soc_stop_latch.get("vehicle") == cable)
        if owning_stop or pending_soc is not None:
            baseline = (self._soc_stop_latch.get("target", previous_target)
                        if owning_stop else pending_soc)
            if (int(value) > float(previous_target) and
                    int(value) > float(baseline)):
                self._soc_resume_request = {
                    "vehicle": cable, "target": int(value),
                    "old_target": previous_target,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                self._record("user_intent", "soc_stop_target_increased",
                             new_target=int(value), old_target=previous_target)
            else:
                self._soc_resume_request = None
        await self._save()
        if self._soc_resume_request and self._soc_resume_request.get("vehicle") == cable:
            await self._refresh_soc_for_explicit_resume_once(car)
        self.refresh()

    async def _refresh_soc_for_explicit_resume_once(self, car):
        """One optional cloud refresh if SOC is stale after user raised target.

        The refresh button is a car-provider request, NOT a BLE command.
        Service success alone is never proof of newer SOC.
        """
        now = datetime.now(timezone.utc)
        if (self._soc_resume_refreshing or not car
                or self._soc_resume_request is None or
                self._soc_resume_request.get("vehicle") != car[CONF_CABLE]
                or not car.get(CONF_VEHICLE_REFRESH)
                or self._soc_stop_fresh(car, now) or
                self._wallbox_cable(now) is not True or
                self.mode != "automatic"):
            return
        self._soc_resume_refreshing = True
        try:
            self._record("vehicle_refresh", "one_shot_after_target_increase")
            await self.hass.services.async_call(
                "button", "press",
                {"entity_id": car[CONF_VEHICLE_REFRESH]}, blocking=True)
        except Exception as error:
            _LOGGER.warning("SOC target increase cloud refresh failed (%s)",
                            type(error).__name__)
            self._record("vehicle_refresh_error", "soc_resume_cloud_refresh_failed")
        finally:
            self._soc_resume_refreshing = False
        self.refresh()

    def session_power_range(self):
        """Return ESPHome's actual number min/max/step, from cached HA state.

        The range is not guessed when ESPHome is unavailable or restored.
        There is no BLE polling or service invocation in this getter.
        """
        source = self._raw(self.cfg[CONF_REQUESTED_LIMIT])
        if (source is None or source.attributes.get("restored")
                or source.state in ("unknown", "unavailable", "")):
            return None
        low, high, step = (finite_number(source.attributes.get(key))
                           for key in ("min", "max", "step"))
        if low is None or high is None or step is None or high <= low or step <= 0:
            return None
        return low, high, step

    def _valid_session_power(self, value):
        bounds = self.session_power_range()
        if bounds is None or isinstance(value, bool):
            return False
        power = finite_number(value)
        if power is None:
            return False
        low, high, step = bounds
        return (low <= power <= high and
                abs((power-low)/step - round((power-low)/step)) < 1e-5)

    async def async_set_session_power(self, value):
        """Store a user override for this confirmed plug-in; never BLE here.

        The ordinary verified actuator will apply a new desired power when
        physically charging; idle/manual/paused state never dispatches it.
        """
        now = datetime.now(timezone.utc)
        if self._restart_power is not None:
            raise ValueError("Riconciliazione dopo riavvio in attesa: potenza sessione non modificabile")
        if (self._closed or self._trace_session is None or
                self._wallbox_cable(now) is not True or
                not self._valid_session_power(value)):
            raise ValueError("Potenza sessione non disponibile o fuori limiti ESPHome")
        desired = round(float(value), 4)
        if abs(desired-self.session_power_kw) < 1e-6:
            return
        old = self.session_power_kw
        self.session_power_kw = desired
        self._record("user_intent", "session_power_selected",
                     previous_kw=old, desired_kw=desired,
                     status="desired_not_confirmed")
        await self._save()
        self.refresh()

    def _raw(self, entity):
        return self.hass.states.get(entity) if entity else None

    @staticmethod
    def _age(state):
        return getattr(state, "last_reported", None) or state.last_updated

    def _fresh(self, entity, now, ttl):
        state = self._raw(entity)
        if state is None or state.attributes.get("restored") or state.state in ("unknown", "unavailable", ""):
            return None
        reported = self._age(state)
        if reported is None or not timedelta(0) <= now-reported <= ttl:
            return None
        return state

    def _binary(self, entity, now, ttl=WALLBOX_TTL):
        state = self._fresh(entity, now, ttl)
        return on(state.state) if state else None

    def _ble_online(self, now):
        """BLE OFF is normal: ESPHome/wallbox can be unpowered for days."""
        return self._reported_binary(self.cfg.get(CONF_BLE_CONNECTED))

    def _reported_binary(self, entity):
        state = self._raw(entity)
        if state is None or state.attributes.get("restored"):
            return None
        return on(state.state)

    def _telemetry_ok(self):
        """Use the firmware AD watchdog if mapped; never assume OFF is safe."""
        entity = self.cfg.get(CONF_TELEMETRY_FRESH)
        return entity is None or self._wallbox_flag(CONF_TELEMETRY_FRESH) is True

    def _charge_state(self, now):
        """Stable Charge State is valid within a live, confirmed BLE epoch.

        HA does not guarantee periodic last_reported for identical text.
        ESPHome invalidates this value on BLE loss; the optional AD watchdog
        independently vetoes the value when configured and OFF/unknown.
        """
        entity = self.cfg.get(CONF_CHARGE_STATE)
        value = self._raw(entity)
        if (value is None or value.attributes.get("restored")
                or value.state in ("unknown", "unavailable", "Unavailable", "")
                or self._ble_online(now) is not True or not self._telemetry_ok()):
            return None
        reported = self._age(value)
        if (reported is None or reported > now or
                (self._ble_since and reported < self._ble_since)):
            return None
        return value.state

    def _reset_unplug_evidence(self, now, reason):
        """Reset the positive unplug proof, with one journal row per reset."""
        if self._unplug_since is not None:
            self._record("unplug_evidence_reset", reason,
                         observed_seconds=max(0, round((now-self._unplug_since).total_seconds())),
                         observed_ad_reports=self._unplug_reports)
        self._unplug_since = self._unplug_report_marker = None
        self._unplug_reports = 0

    def _wallbox_cable(self, now):
        if self._ble_online(now) is not True:
            self._unplug_restore_pending = False
            self._unplug_restore_since = None
            self._reset_unplug_evidence(now, "ble_disconnected")
            return None
        cable = self._wallbox_flag(CONF_WALLBOX_CONNECTED)
        if cable is not False:
            if cable is True:
                self._unplug_restore_pending = False
                self._unplug_restore_since = None
            self._reset_unplug_evidence(now,
                                        "cable_replugged" if cable is True
                                        else "cable_not_confirmed")
            return cable
        if self._last_cable is True:
            self._unplug_restore_pending = True
        if self._charge_state(now) != "Cable Unplugged":
            self._reset_unplug_evidence(now, "charge_state_not_unplugged")
            return None
        # 69s and two independent AD observations are for cable removal,
        # not for the Shelly power-on path.
        stop_uncertain = (self._soc_stop_latch is not None or self._soc_stop_done or
                          (isinstance(self._saved_attempt, dict) and
                           self._saved_attempt.get("kind") == "soc_stop") or
                          (self._pending is not None and self._pending.kind == "soc_stop"))
        if stop_uncertain:
            state = self._raw(self.cfg.get(CONF_CHARGE_STATE))
            marker = self._age(state)
            if self._unplug_since is None:
                self._unplug_since = now
                self._unplug_report_marker = marker
                self._unplug_reports = 1
            elif marker > self._unplug_report_marker:
                # Require an additional AD report, not repeated timer callbacks.
                self._unplug_report_marker = marker
                self._unplug_reports += 1
            if (now-self._unplug_since < timedelta(seconds=69) or
                    self._unplug_reports < 2):
                return None
        return False

    def _wallbox_flag(self, key):
        # ESPHome invalidates these AD flags when its watchdog trips. A stable
        # healthy binary can legitimately have an old HA last_changed.
        entity = self.cfg.get(key)
        source = self._raw(entity)
        if source is None or (self._ble_since and self._age(source) < self._ble_since):
            return None
        return self._reported_binary(self.cfg[key])

    def _setting(self, key, now):
        # EEPROM 158/174 are settings, not samples from the cyclic AD poll.
        # Firmware invalidates their readbacks on disconnect. Reject restored
        # HA values and any reading left over from an earlier BLE epoch.
        source = self._raw(self.cfg[key])
        if (source is None or source.attributes.get("restored") or
                self._age(source) is None or self._age(source) > now):
            return None
        value = power_kw(source.state, source.attributes.get("unit_of_measurement"))
        if value is None:
            return None
        if self._ble_since and self._age(source) < self._ble_since:
            # The ESPHome template number is a UI setting. HA can retain
            # last_reported when unchanged after BLE reconnect. Reuse only
            # if independent EEPROM 174 readback in this epoch agrees.
            if key != CONF_REQUESTED_LIMIT:
                return None
            confirmed = self._setting(CONF_CONFIRMED_LIMIT, now)
            if confirmed is None or abs(value-confirmed) > .051:
                return None
        return value

    def _record(self, event, reason, **details):
        self._journal.record(self._trace_session or self._idle_park_trace, event, reason,
                             mode=self.mode, facts=self._facts, **details)

    def _gate(self, reason):
        self._last_policy_reason = reason
        key = (reason, self.mode, self._session_id)
        if key != self._gate_key:
            self._gate_key = key
            self._record("decision", reason, action="hold")

    def _power(self, entity, now, ttl=WALLBOX_TTL):
        state = self._fresh(entity, now, ttl)
        return (power_kw(state.state, state.attributes.get("unit_of_measurement"))
                if state else None)

    def _number(self, entity, now, ttl=CAR_TTL):
        # SOC is telemetry and must be recent. A user-maintained input_number
        # target is a setting and may legitimately remain unchanged for weeks.
        s = self._fresh(entity, now, ttl) if ttl is not None else self._raw(entity)
        if s is None or s.state in ("unknown", "unavailable", ""):
            return None
        return finite_number(s.state)

    def _schedule_save(self):
        task = self.entry.async_create_background_task(
            self.hass, self._save(), "EasyWallbox beta save session")
        self._save_tasks.add(task)
        task.add_done_callback(self._save_tasks.discard)

    def _status_acks(self, now, cable):
        """Correlate a confirmed EEPROM readback with a unique operation."""
        p = self._pending
        if p is None or not p.dispatched:
            return
        if p.kind in ("delay_arm", "delay_release", "normalize_on", "supply_restore", "mode_auto_on"):
            if p.session != self._idle_park_trace or cable is None:
                self._fail_command(p, "standby_command_ble_or_ownership_lost")
                return
            if p.kind == "delay_arm" and cable is not False:
                self._fail_command(p, "cable_connected_during_delay_arm")
                return
        else:
            if cable is not True or self._session_id != p.session:
                if (p.kind == "soc_stop" and cable is None and
                        self._unplug_since is not None):
                    return  # Physical unplug not proved; never auto-resume.
                self._fail_command(p, "pending_command_cable_or_session_lost")
                return
            if p.kind in ("soc_stop", "soc_resume"):
                # A Fiat can report CLOUD CABLE OFF immediately after DPM0.
                # Identity was proven BEFORE Stop; retain it only while the
                # wallbox's physical cable event has not changed.
                if (not p.vehicle or p.vehicle != self._connection or
                        not p.cable_marker or
                        p.cable_marker != self._continuity_marker(CONF_WALLBOX_CONNECTED)
                        or any(self._reported_binary(other[CONF_CABLE]) is True
                               for other in self.cfg[CONF_VEHICLES]
                               if other[CONF_CABLE] != p.vehicle)):
                    self._fail_command(p, "soc_command_physical_continuity_lost")
                    return
            else:
                car = self._select_vehicle(now, cable)
                if (p.kind == "power" and
                        (self._vehicle_conflict(now, cable) or
                         (p.cable_marker and
                          p.cable_marker != self._continuity_marker(CONF_WALLBOX_CONNECTED)))):
                    self._fail_command(p, "power_command_physical_continuity_lost")
                    return
                if p.kind != "power" and (
                        car is None or car[CONF_CABLE] != self._connection):
                    self._fail_command(p, "pending_vehicle_unverified")
                    return
        if now - p.since >= ACK_TIMEOUT:
            self._fail_command(p, "unconfirmed_" + p.kind + "_no_retry")
            return
        if self._charge_state(now) == "Error":
            self._fail_command(p, "active_charge_state_error_during_command")
            return
        is_power = p.kind == "power"
        # Independent post-command Charge Enabled readback confirms Start/Stop.
        # Smart Charging never reads or writes the numerical DPM register.
        key = CONF_CONFIRMED_LIMIT if is_power else CONF_CHARGE_ENABLED
        source = self._raw(self.cfg[key])
        confirmed = (self._setting(key, now) if is_power else
                     self._wallbox_flag(CONF_CHARGE_ENABLED))
        expected = (p.target if is_power else
                    p.kind not in ("delay_arm", "soc_stop"))
        if (source is None or confirmed is None or
                self._age(source) <= p.since or
                (abs(confirmed-expected) > .051 if is_power
                 else confirmed is not expected)):
            return
        if not p.readback_seen:
            p.readback_seen = True
            self._record("readback", "ev_register" if is_power else "charge_enabled",
                         operation=p.operation, kind=p.kind,
                         **({"confirmed_kw": confirmed} if is_power
                            else {"confirmed_enabled": confirmed}),
                         readback_at=self._age(source).isoformat())
        observed = self._wallbox_flag(CONF_WALLBOX_CHARGING)
        ev = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
        if is_power:
            requested = self._setting(CONF_REQUESTED_LIMIT, now)
            if requested is None or abs(requested-expected) > .051:
                return
            self._owned_limit = p.target
            if p.next_state is not None:
                self._power_state = p.next_state
        elif p.kind == "delay_arm":
            if (cable is not False or observed is not False or ev is None or ev >= .03
                    or self._reported_binary(self.cfg[CONF_START_STOP]) is not False):
                return
            self._dpm_lease = 1.0  # Switch-ON ownership sentinel, not DPM kW.
            self._saved_delay_lease = {
                "kind": "preplug", "start": self._scheduled_at.isoformat(),
                "switch": "off_confirmed"}
        elif p.kind in ("delay_release", "normalize_on", "soc_resume", "supply_restore", "mode_auto_on"):
            # DPM > 0 proves the switch was released, NOT that a car
            # immediately started charging. This works even with no car.
            if self._reported_binary(self.cfg[CONF_START_STOP]) is not True:
                return
            if p.kind == "delay_release":
                self._dpm_lease = None
                self._saved_delay_lease = None
                self.delay_enabled = False
                self._scheduled_at = None
            elif p.kind == "soc_resume":
                self._standby_restore_due = False
                self._soc_stop_latch = None
                self._soc_resume_request = None
                self._soc_stop_done = False
            elif p.kind == "supply_restore":
                self._supply_restore_candidate = None
                self._supply_ble_rejoined = False
            elif p.kind == "normalize_on" and cable is False:
                self._standby_restore_due = False
                self._soc_stop_latch = None
                self._soc_resume_request = None
                self._soc_stop_done = False
        elif p.kind == "soc_stop":
            ev_source = self._raw(self.cfg[CONF_EV_POWER])
            charging_source = self._raw(self.cfg[CONF_WALLBOX_CHARGING])
            if (ev is None or observed is not False or ev >= .03 or
                    self._age(ev_source) <= p.since or
                    self._age(charging_source) <= p.since):
                return
            self._soc_stop_done = True
            self._standby_restore_due = True
            self._soc_stop_latch = {
                "vehicle": self._connection, "target": p.soc_stop_target,
                "soc": self.soc, "confirmed_at": now.isoformat(),
                "cable_marker": p.cable_marker,
            }
            # Keep an explicit higher target set while stop was pending.
            # It can request ON only AFTER the stop is electrically ACKed.
        else:
            self._fail_command(p, "unknown_ack_kind")
            return
        self.last_ack = now.isoformat(timespec="seconds")
        self._pending = self._saved_attempt = None
        self._schedule_save()
        self._record("confirmed", "post_request_readback", operation=p.operation,
                     kind=p.kind,
                     **({"expected_kw": expected, "confirmed_kw": confirmed}
                        if is_power else {"expected_enabled": expected,
                                          "confirmed_enabled": confirmed}),
                     readback_at=self._age(source).isoformat(),
                     charging_flag=observed, ev_kw=ev)
        self.reason = "confirmed_" + p.kind
        if p.kind in ("delay_release", "normalize_on", "mode_auto_on"):
            self._idle_park_trace = None
            asyncio.get_running_loop().call_soon(self.refresh)
        elif p.kind == "soc_resume":
            asyncio.get_running_loop().call_soon(self.refresh)

    def _fail_command(self, p, reason):
        self._blocked = reason
        self.real_enabled = False
        self._pending = None
        self._record("unconfirmed", reason, operation=p.operation, kind=p.kind)
        # A failed command retains its persisted unresolved intent.

    def _vehicle_conflict(self, now, cable):
        """Two simultaneously ON cloud cable sensors are contradictory, not a guest."""
        return (cable is True and sum(
            self._binary(car[CONF_CABLE], now, CAR_TTL) is True
            for car in self.cfg[CONF_VEHICLES]) > 1)

    def _select_vehicle(self, now, cable):
        profile = None
        observed = []
        for car in self.cfg[CONF_VEHICLES]:
            state = self._binary(car[CONF_CABLE], now, CAR_TTL)
            observed.append(state)
            if state is True:
                profile = car if profile is None else False
        if (cable is not True or observed.count(True) != 1 or
                any(v is None for v in observed) or profile is False):
            return None
        return profile

    def _continuity_marker(self, key):
        source = self._raw(self.cfg[key])
        changed = getattr(source, "last_changed", None)
        return changed.isoformat() if changed else None

    def _recover_preplug_hold(self, now, cable):
        """Recover only an ACKed pre-plug lease with live DPM0 readback.

        An old prior iterations delay lease and a manual DPM=0 cannot be adopted.
        The Fiat/Kia cloud cable states are never involved here.
        """
        saved = self._saved_delay_lease
        if self._dpm_lease is not None or not isinstance(saved, dict):
            return
        if (saved.get("kind") != "preplug" or self._scheduled_at is None
                or saved.get("start") != self._scheduled_at.isoformat()
                or cable not in (True, False) or self._blocked
                or self._saved_attempt is not None):
            return
        # Legacy numeric leases are ignored. Independently confirmed OFF
        # and unchanged physical ownership suffice for the switch lease.
        if (self._wallbox_flag(CONF_CHARGE_ENABLED) is not False or
                self._reported_binary(self.cfg[CONF_START_STOP]) is not False or
                self._wallbox_flag(CONF_WALLBOX_CHARGING) is not False or
                self._charge_state(now) == "Error"):
            return
        ev = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
        if ev is not None and ev < .03:
            self._dpm_lease = 1.0  # Switch-ON ownership sentinel
            if self._idle_park_trace is None:
                self._idle_park_trace = uuid4().hex
            self._record("reconciliation", "saved_preplug_hold_verified")

    def _schedule_preplug_release(self, now, cable):
        """Release the verified pre-plug pause at due time or on cancellation."""
        if (self._closed or self.mode != "automatic" or not self.real_enabled
                or self.explicit_pause or self._blocked or self._pending is not None
                or self._saved_attempt is not None or
                self._dpm_lease is None or self._saved_delay_lease is None
                or cable not in (True, False) or
                (self.delay_enabled and (self._scheduled_at is None
                                         or now < self._scheduled_at))):
            return
        if self._park_task is None or self._park_task.done():
            self._park_task = self.entry.async_create_background_task(
                self.hass, self._release_preplug_hold(),
                "EasyWallbox prior iterations verified delayed start")

    async def _release_preplug_hold(self):
        async with self._lock:
            now = datetime.now(timezone.utc)
            if (self._dpm_lease is not None and
                    self._write_block("delay_release", self._dpm_lease,
                                      self._idle_park_trace, now) is None):
                await self._send("delay_release", self._dpm_lease, None,
                                 "explicit_preplug_appointment_or_cancellation")

    def _schedule_normal_on(self, now, cable):
        """ON only after verified physical unplug, never with a connected car."""
        if (self._closed or self.mode != "automatic" or not self.real_enabled
                or self.explicit_pause or self._blocked or self._pending is not None
                or self._saved_attempt is not None or
                self.delay_enabled or self._saved_delay_lease is not None
                or self._dpm_lease is not None or cable is not False or
                not (self._standby_restore_due or self._soc_stop_latch)):
            return
        if (self._reported_binary(self.cfg[CONF_START_STOP]) is not False or
                self._wallbox_flag(CONF_CHARGE_ENABLED) is not False or
                self._wallbox_flag(CONF_WALLBOX_CHARGING) is not False or
                self._charge_state(now) == "Error"):
            if (cable is False and (self._standby_restore_due or
                                    self._soc_stop_latch is not None) and
                    self._reported_binary(self.cfg[CONF_START_STOP]) is True and
                    self._wallbox_flag(CONF_CHARGE_ENABLED) is True):
                self._soc_stop_latch = None
                self._standby_restore_due = False
                self._soc_resume_request = None
                self._soc_stop_done = False
                self._schedule_save()
            return
        ev = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
        if ev is None or ev >= .03:
            return
        if self._park_task is None or self._park_task.done():
            self._park_task = self.entry.async_create_background_task(
                self.hass, self._normalize_on(),
                "EasyWallbox prior iterations verified standby ON")

    async def _normalize_on(self):
        async with self._lock:
            now = datetime.now(timezone.utc)
            if self._idle_park_trace is None:
                self._idle_park_trace = uuid4().hex
            if (self._write_block("normalize_on", 1.0,
                                  self._idle_park_trace, now) is None):
                await self._send("normalize_on", 1.0,
                                 None, "normal_on_after_idle_or_soc_unplug")

    def _schedule_supply_restore(self, now, cable):
        """One-shot standby normalization ONLY after an observed physical Shelly cycle."""
        relay = self.cfg.get(CONF_WALLBOX_POWER_SWITCH)
        if (not relay or self._supply_restore_candidate is None or
                now-self._supply_restore_candidate >= timedelta(minutes=2)):
            return
        if (self._closed or self.mode != "automatic" or not self.real_enabled
                or self.explicit_pause or self._blocked or self._pending
                or self._saved_attempt or self.delay_enabled
                or self._saved_delay_lease is not None or self._dpm_lease is not None
                or self._soc_stop_latch is not None or self._standby_restore_due
                or not self._supply_ble_rejoined or cable is not False
                or self._reported_binary(relay) is not True
                or self._charge_state(now) != "Cable Unplugged"):
            return
        state = self._raw(self.cfg.get(CONF_CHARGE_STATE))
        if state is None or self._age(state) <= self._supply_restore_candidate:
            return  # AD must come AFTER the Shelly power event.
        switch = self._reported_binary(self.cfg[CONF_START_STOP])
        dpm = self._wallbox_flag(CONF_CHARGE_ENABLED)
        if switch is True and dpm is True:
            self._record("power_supply", "already_on_after_power_cycle")
            self._supply_restore_candidate = None
            self._supply_ble_rejoined = False
            return
        if switch is not False or dpm is not False:
            return
        if (self._wallbox_flag(CONF_WALLBOX_CHARGING) is not False or
                (ev := self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)) is None
                or ev >= .03):
            return
        if self._park_task is None or self._park_task.done():
            self._park_task = self.entry.async_create_background_task(
                self.hass, self._restore_after_supply(),
                "EasyWallbox prior iterations verified Shelly power-cycle restore")

    async def _restore_after_supply(self):
        async with self._lock:
            now = datetime.now(timezone.utc)
            if self._idle_park_trace is None:
                self._idle_park_trace = uuid4().hex
            if self._write_block("supply_restore", 1.0,
                                 self._idle_park_trace, now) is None:
                await self._send("supply_restore", 1.0,
                                 None, "observed_shelly_off_on_unplugged_standby")

    def _car_update_ready(self, now, car):
        """A refresh button press is NOT new vehicle data.

        When a per-car source timestamp is configured, demand a truly newer
        upstream update. Otherwise require a new SOC report after plugging.
        """
        if self._connect_since is None:
            return False
        if self._refresh_due is not None and not self._refresh_issued:
            return False
        # A failed cloud button is diagnostic, not a permanent veto.
        # Independently verified newer vehicle data may recover the session.
        if car is None:
            return False
        if self._refresh_requested_at is not None:
            since = self._refresh_requested_at
        else:
            since = self._connect_since
        stamp_entity = car.get(CONF_VEHICLE_LAST_UPDATE)
        if stamp_entity:
            state = self._raw(stamp_entity)
            try:
                stamp = datetime.fromisoformat(state.state) if state else None
            except (ValueError, TypeError):
                stamp = None
            ready = (stamp is not None and stamp.utcoffset() is not None
                     and since <= stamp <= now and now - stamp <= CAR_TTL)
        else:
            state = self._raw(car[CONF_SOC])
            ready = bool(self._fresh(car[CONF_SOC], now, CAR_TTL) and since <= self._age(state) <= now)
        if ready:
            self._refresh_error = None
            return True
        if self._refresh_deadline and now >= self._refresh_deadline:
            self._refresh_error = "car_update_not_confirmed_after_one_request"
        return False

    async def _request_one_shot_updates(self):
        """Best-effort cloud identification: +15s, +1m..+4m, stop at +5m.

        A cloud failure never disables charging or electrical stabilization.
        An already identified vehicle gets just the initial data refresh.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            start, due, deadline = (self._refresh_start_at,
                                     self._refresh_due, self._refresh_deadline)
            if (not self.real_enabled or self.mode != "automatic" or
                    self._closed or start is None or due is None or
                    deadline is None or now < due or
                    self._wallbox_cable(now) is not True or
                    self._wallbox_flag(CONF_WALLBOX_CHARGING) is not True or
                    (self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
                     or 0.0) < .10):
                return
            if now >= deadline:
                self._refresh_due = None
                self._record("vehicle_refresh", "five_minute_identification_expired")
                return
            selected = self._select_vehicle(now, True)
            if self._refresh_issued and selected is not None:
                self._refresh_due = None
                return
            session = self._trace_session
            self._refresh_issued = True
            self._refresh_count += 1
            self._refresh_requested_at = now
            cars = [selected] if selected is not None else self.cfg[CONF_VEHICLES]
            # Anchor each retry to the ORIGINAL charging start, not to the
            # completion of a slow cloud call. No calls after +5 minutes.
            retry_at = start + timedelta(minutes=self._refresh_count)
            self._refresh_due = (
                retry_at if selected is None and retry_at < deadline else None)
            for car in cars:
                button = car.get(CONF_VEHICLE_REFRESH)
                if not button:
                    continue
                check = datetime.now(timezone.utc)
                if (self._closed or session != self._trace_session or
                        check >= deadline or not self.real_enabled or
                        self.mode != "automatic" or
                        self._wallbox_cable(check) is not True or
                        self._wallbox_flag(CONF_WALLBOX_CHARGING) is not True or
                        (self._power(self.cfg[CONF_EV_POWER], check, SHELLY_TTL)
                         or 0.0) < .10):
                    return
                # The other car may be disconnected: its cloud provider may
                # reject refresh; record that fact and carry on.
                try:
                    self._record("vehicle_refresh", "identification_attempt",
                                 attempt=self._refresh_count,
                                 vehicle_slot=self.cfg[CONF_VEHICLES].index(car) + 1)
                    await self.hass.services.async_call(
                        "button", "press", {"entity_id": button}, blocking=True)
                except Exception as error:
                    self._record("vehicle_refresh_error", "provider_refresh_failed",
                                 vehicle_slot=self.cfg[CONF_VEHICLES].index(car) + 1,
                                 error_type=type(error).__name__)
            self.refresh()

    def _house(self, now):
        values, times = [], []
        self._house_skew_seconds = None
        self._house_quality_reason = None
        for eid in self.house_ids:
            state = self._fresh(eid, now, SHELLY_TTL)
            if state is None:
                self._house_quality_reason = "house_source_missing_or_stale"
                return None, None
            value = power_kw(state.state, state.attributes.get("unit_of_measurement"))
            if value is None:
                self._house_quality_reason = "house_source_non_numeric"
                return None, None
            values.append(value)
            times.append(self._age(state))
        # Distinct Shelly sources are never made artificially synchronous.
        self._house_skew_seconds = round((max(times)-min(times)).total_seconds(), 1)
        if max(times)-min(times) > HOUSE_MAX_SKEW:
            self._house_quality_reason = "house_sources_not_synchronized"
            return None, None
        return sum(values), min(times)

    def _departure(self, now, car):
        if self.departure_override is not None:
            return self.departure_override
        if (self._active_departure is not None and
                self._active_departure_vehicle == car[CONF_CABLE]):
            return self._active_departure
        settings = self.entry.options.get("vehicle_schedules", {}).get(car[CONF_CABLE], {})
        weekday = settings.get(CONF_DEPARTURE_WEEKDAY, car[CONF_DEPARTURE_WEEKDAY])
        weekend = settings.get(CONF_DEPARTURE_WEEKEND, car[CONF_DEPARTURE_WEEKEND])
        self._active_departure = next_departure(
            now.astimezone(ZoneInfo(self.hass.config.time_zone)), weekday, weekend)
        self._active_departure_vehicle = car[CONF_CABLE]
        # Preserve the absolute deadline across a restart even after its clock
        # time has elapsed. A new deadline belongs to a new verified session.
        self._schedule_save()
        return self._active_departure

    def _planned_start(self, now):
        """Read the validated absolute date/time saved with the session."""
        return self._scheduled_at

    def _record_planning_power(self, now, house, house_at, ev_kw, charging, ev_limit):
        """Keep bounded samples in RAM, without additional HA entities."""
        if house is not None and house_at is not None:
            if (not self._house_history or
                    house_at > self._house_history[-1][0] + timedelta(seconds=45)):
                self._house_history.append((house_at, house))
        # EV samples recorded under our own cap cannot estimate the
        # unconstrained/DPM-only charge rate used for departure decisions.
        base = self.session_power_kw
        if (charging is True and ev_kw is not None and ev_kw >= .2
                and ev_limit is not None and ev_limit >= base-.11):
            state = self._fresh(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
            if state:
                measured_at = self._age(state)
                if (not self._ev_history or
                        measured_at > self._ev_history[-1][0] + timedelta(seconds=45)):
                    self._ev_history.append((measured_at, ev_kw))
        cutoff = now-timedelta(minutes=61)
        for history in (self._house_history, self._ev_history):
            while history and history[0][0] < cutoff:
                history.popleft()

    def _record_ev_delivery(self, now, ev_kw, charging):
        """Integrate ONLY independent actual Shelly reports, never timer ticks.

        A missing interval is NOT filled with a guessed EV power.
        This measures actual AC delivery for margin and ETA, never DPM safety.
        """
        source = self._fresh(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
        if charging is False and ev_kw is not None and ev_kw < .1:
            # A verified pause is not a valid positive-power interval.
            # Starting a new segment on resume avoids integrating across it.
            self._delivery_last = None
            return
        if (charging is not True or source is None or ev_kw is None or
                ev_kw < .1):
            # Telemetry discontinuity: never bridge an unknown interval
            # with the old and next instantaneous EV power values.
            if self._delivery_last is not None:
                self._delivery_gap = True
            self._delivery_last = None
            return
        measured_at = self._age(source)
        if self._delivery_last is not None:
            old_at, old_kw = self._delivery_last
            seconds = (measured_at-old_at).total_seconds()
            if seconds <= 0:
                return
            if seconds > 150:
                self._delivery_gap = True
            else:
                self._delivered_ev_kwh += ((old_kw+ev_kw)/2)*seconds/3600
        self._delivery_last = (measured_at, ev_kw)

    def _energy_after_soc(self, now, car, soc, remaining):
        """Conservative AC remaining using only measured delivery since SOC.

        A HA last_reported update with the SAME SOC does not establish a
        new battery measurement: never reset the energy anchor or a gap on it.
        Missing EV intervals contribute zero *observed* energy, making the
        resulting departure margin a model-based lower bound, not a false
        claim that the missing interval was measured. No commands here.
        """
        raw_soc = self._fresh(car[CONF_SOC], now, CAR_TTL)
        if raw_soc is None or remaining is None:
            return None
        marker = (car[CONF_CABLE], soc)
        anchor = self._soc_anchor
        if anchor is None or anchor[:2] != marker:
            # A different vehicle or genuinely different SOC reanchors.
            # An unchanged SOC republished by HA never clears a gap.
            self._soc_anchor = (*marker, self._delivered_ev_kwh)
            self._delivery_gap = False
        consumed = max(0.0, self._delivered_ev_kwh-self._soc_anchor[2])
        return max(0.0, remaining-consumed)

    def _latest_start(self, now):
        if (self.departure is None or self._margin_energy_kwh is None or
                self.planning_rate_kw is None):
            return None
        return self.departure-timedelta(
            minutes=30+60*self._margin_energy_kwh/self.planning_rate_kw)

    def _safe_start_due(self, now):
        """Explicit start time has priority over a departure estimate."""
        return (not self.delay_enabled or
                (self._scheduled_at is not None and now >= self._scheduled_at))

    def _snapshot(self, now):
        cable = self._wallbox_cable(now)
        car = self._select_vehicle(now, cable)
        charge_state = self._charge_state(now)
        charging_flag = self._wallbox_flag(CONF_WALLBOX_CHARGING)
        ev_kw = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
        if charging_flag is True and ev_kw is not None and ev_kw >= .10:
            charging = True
        elif charging_flag is False and ev_kw is not None and ev_kw < .10:
            charging = False
        else:
            charging = None
        dpm = self._wallbox_flag(CONF_CHARGE_ENABLED)
        actual_limit = self._setting(CONF_CONFIRMED_LIMIT, now)
        requested = self._setting(CONF_REQUESTED_LIMIT, now)
        house, house_at = self._house(now)
        self._record_planning_power(now, house, house_at, ev_kw, charging, actual_limit)
        self._record_ev_delivery(now, ev_kw, charging)
        if (charging is True and self._connect_since is not None
                and self._refresh_start_at is None):
            # Refresh once after 15 seconds and, only while unrecognized,
            # at +1m, +2m, +3m and +4m. Stop completely at +5m.
            self._refresh_start_at = now
            self._refresh_due = now + timedelta(seconds=15)
            self._refresh_deadline = now + timedelta(minutes=5)
            self._record("vehicle_refresh", "charging_start_detected")

        self.house_kw = round(house, 3) if house is not None else None
        self.vehicle_name = car[CONF_NAME] if car else (
            "Veicolo non identificato" if cable is True and charging is True else None)
        if cable is True:
            self.session_history.note_vehicle(self.vehicle_name)
        self.charging_verified = charging
        self.stop_at_target_enabled = bool(car.get(CONF_STOP_AT_TARGET)) if car else None
        self.soc = self.target_soc = self.margin_minutes = self.remaining_kwh = None
        self._energy_display = None
        self._margin_energy_kwh = None
        self._margin_quality = None
        self._finish_display = None
        self._eta_remaining_ac_kwh = None
        self.planning_rate_kw = estimate_ac_kw(
            now=now, dpm_kw=float(self.cfg[CONF_EXPECTED_DPM]),
            ev_base_kw=self.session_power_kw,
            house_samples=self._house_history,
            charging_ev_samples=(self._ev_history if charging is True
                                 and actual_limit is not None
                                 and actual_limit >= self.session_power_kw-.11
                                 else ()))
        self._forecast_rate_kw = estimate_forecast_ac_kw(
            now=now, dpm_kw=float(self.cfg[CONF_EXPECTED_DPM]),
            ev_base_kw=self.session_power_kw,
            house_samples=self._house_history, charging_ev_samples=self._ev_history)
        self._forecast_quality = ("consolidata" if self.planning_rate_kw is not None
                                  else "provvisoria" if self._forecast_rate_kw is not None
                                  else None)
        self.departure = None
        target_reached = None
        if car:
            soc = self._number(car[CONF_SOC], now, CAR_TTL)
            target = (self._number(car.get(CONF_TARGET_ENTITY), now, None)
                      if car.get(CONF_TARGET_ENTITY) else self.fixed_target(car))
            self.soc, self.target_soc = soc, target
            departure = self._departure(now, car)
            self.departure = departure
            if (soc is not None and target is not None
                    and 0 <= soc <= 100 and 1 <= target <= 100):
                target_reached = soc >= target
                remaining = max(0, target-soc) / 100 * float(car[CONF_CAPACITY]) / float(car[CONF_EFFICIENCY])
                # Decision margin uses only independently observed AC energy.
                # A gap retains a conservative observed-only bound; advisory
                # ETA stays unavailable rather than claiming precise timing.
                self.remaining_kwh = round(remaining, 2)
                self._energy_display = round(remaining, 1)
                if charging is True:
                    self._margin_energy_kwh = self._energy_after_soc(
                        now, car, soc, remaining)
                    self._margin_quality = (
                        "observed_partial_gap" if self._delivery_gap
                        else "observed_complete"
                    ) if self._margin_energy_kwh is not None else "unavailable"
                    self._eta_remaining_ac_kwh = (
                        self._margin_energy_kwh if not self._delivery_gap else None)
                else:
                    self._margin_energy_kwh = remaining
                    self._margin_quality = "soc_only_not_charging"
                self.margin_minutes = estimate_margin(
                    now=now, departure=departure,
                    remaining_kwh=self._margin_energy_kwh,
                    rate_kw=self.planning_rate_kw)
                if (charging is True and remaining > 0 and
                        self._forecast_rate_kw is not None and
                        self._eta_remaining_ac_kwh is not None):
                    estimate = now + timedelta(hours=self._eta_remaining_ac_kwh/self._forecast_rate_kw)
                    # 10-minute publication buckets, no per-minute countdown.
                    rounded = round(estimate.timestamp()/600)*600
                    self._finish_display = datetime.fromtimestamp(
                        rounded, timezone.utc)
                else:
                    self._finish_display = None
        # Configured contracted power is a mathematical planning reference.
        # The ON/OFF readback comes independently from ESPHome Charge Enabled.
        contracted_kw = float(self.cfg[CONF_EXPECTED_DPM])
        dpm_normal = dpm is True
        dpm_parked = dpm is False
        issues = []
        for ok, reason in (
            (cable is True, "cable_unknown"),
            (not self._vehicle_conflict(now, cable), "vehicle_identity_conflict"),
            (self._telemetry_ok(), "telemetry_not_fresh"),
            (not self.cfg.get(CONF_CHARGE_STATE) or charge_state in (
                "Charging", "Vehicle ready", "Pause", "Stato transitorio", "Pending",
                "Transition (7)", "Unknown (7)"), "charge_state_unverified"),
            (charging is not None, "charging_and_meter_unverified"),
            (house is not None, self._house_quality_reason or
             "house_meter_missing_or_stale"),
            (dpm_normal or dpm_parked, "charge_enabled_unverified"),
            (actual_limit is not None and requested is not None and
             abs(actual_limit-requested) <= .051, "ev_limit_unverified"),
        ):
            if not ok:
                issues.append(reason)
        self.quality = "incomplete" if issues else "ok"
        self._facts = dict(ble=True, cable=cable, charge_state=charge_state, charging_flag=charging_flag,
                           charging_verified=charging, ev_kw=ev_kw, house_kw=self.house_kw,
                           house_at=house_at.isoformat() if house_at else None,
                           house_skew_seconds=self._house_skew_seconds,
                           house_quality_reason=self._house_quality_reason,
                           requested_ev_kw=requested, confirmed_ev_kw=actual_limit,
                           session_power_desired_kw=self.session_power_kw,
                           session_power_default_kw=float(self.cfg[CONF_BASE_KW]),
                           charge_enabled_confirmed=dpm, contracted_power_kw=contracted_kw,
                           soc=self.soc, target_soc=self.target_soc,
                           remaining_kwh=self.remaining_kwh, margin_min=self.margin_minutes,
                           margin_energy_kwh=(round(self._margin_energy_kwh, 3)
                                              if self._margin_energy_kwh is not None else None),
                           margin_energy_source=(
                               "shelly_ac_observed_gap" if charging is True
                               and self._delivery_gap else
                               "shelly_ac_since_soc" if charging is True else
                               "reported_soc_only"),
                           margin_quality=self._margin_quality,
                           ev_delivery_gap=self._delivery_gap,
                           rate_kw=self.planning_rate_kw, forecast_rate_kw=self._forecast_rate_kw,
                           eta_remaining_kwh=self._eta_remaining_ac_kwh,
                           delivered_ev_kwh=round(self._delivered_ev_kwh, 3),
                           departure=self.departure.isoformat() if self.departure else None,
                           delay_until=self._scheduled_at.isoformat() if self._scheduled_at else None,
                           issues=issues)
        if car is not None:
            soc_state = self._raw(car[CONF_SOC])
            changed_at = getattr(soc_state, "last_changed", None) if soc_state else None
            self._facts["soc_last_changed_age_s"] = (
                round((now-changed_at).total_seconds())
                if isinstance(changed_at, datetime) and
                changed_at.utcoffset() is not None and
                timedelta(0) <= now-changed_at else None)
        report_sources = {"ev_meter": self.cfg[CONF_EV_POWER],
                          "confirmed_ev": self.cfg[CONF_CONFIRMED_LIMIT],
                          "charge_enabled": self.cfg[CONF_CHARGE_ENABLED]}
        if car:
            report_sources["soc"] = car[CONF_SOC]
            if car.get(CONF_VEHICLE_LAST_UPDATE):
                stamp = self._raw(car[CONF_VEHICLE_LAST_UPDATE])
                self._facts["vehicle_update_at"] = stamp.state if stamp else None
        for index, source in enumerate(self.house_ids, start=1):
            report_sources[f"house_{index}"] = source
        self._facts["reported_at"] = {
            role: self._age(state).isoformat()
            for role, source in report_sources.items() if (state := self._raw(source))
        }
        if car:
            self._facts["vehicle_slot"] = self.cfg[CONF_VEHICLES].index(car) + 1
        return dict(cable=cable, car=car, charging=charging, charge_state=charge_state,
                    house=house, house_at=house_at, dpm=dpm, dpm_normal=dpm_normal,
                    dpm_parked=dpm_parked, actual=actual_limit, requested=requested,
                    trusted=not issues, target_reached=target_reached, ev_kw=ev_kw)

    def _notify(self):
        for listener in tuple(self._listeners):
            listener()

    def _update_notice(self, now):
        if self._blocked and self._blocked != "restart_power_evidence_expired_manual_review":
            # Other interlocks, especially unresolved BLE commands, have priority.
            self.notice = "Controllo sospeso: " + self._blocked
            return
        if self._restart_review:
            info = self._restart_review_info or {}
            old_kw = finite_number(info.get("last_confirmed_kw"))
            confirmed = (f"Ultimo limite EV confermato {old_kw:.1f} kW "
                         if old_kw is not None else "Vecchio limite EV non noto ")
            self.notice = (
                "Controllo sospeso. " + confirmed +
                "(non è una lettura attuale): può essere ancora attivo sulla wallbox. "
                "Verifica il valore reale in ESPHome; il blocco termina solo "
                "dopo scollegamento confermato.")
            return
        if self._blocked:
            self.notice = "Controllo sospeso: " + self._blocked
            return
        if self._restart_power is not None:
            self.notice = ("Riconciliazione dopo riavvio in attesa: "
                           "potenza sessione non modificabile finché "
                           "la ricarica non è verificata o il cavo scollegato")
            return
        # If ESPHome exposes no range or the saved default is not aligned
        # with the actual number step, do not misrepresent the slider.
        if (self._trace_session is not None and self._online is True and
                not self._valid_session_power(self.session_power_kw)):
            self.notice = ("Potenza sessione non valida per i limiti/il passo "
                           "ESPHome: verifica Charge power e Opzioni")
            return
        if self._user_warning:
            self.notice = self._user_warning
            return
        if self.delay_enabled and self._scheduled_at is not None:
            target = self._scheduled_at.astimezone(
                ZoneInfo(self.hass.config.time_zone))
            latest = self._latest_start(now)
            if self.charging_verified is True and now < self._scheduled_at:
                self.notice = ("Posticipo richiesto: "
                               + ("attesa conferma pausa DPM 0 A"
                                  if self.real_enabled else
                                  "controllo automatico non abilitato"))
            elif latest is not None and target > latest:
                self.notice = (
                    "Avvio scelto " + target.strftime("%H:%M")
                    + "; per il target entro la partenza serviva iniziare "
                    + datetime.fromtimestamp(
                        round(latest.timestamp()/600)*600,
                        timezone.utc).astimezone(target.tzinfo).strftime("%H:%M")
                    + ". Non anticipo l'avvio.")
            else:
                self.notice = ("Posticipo richiesto per le "
                               + target.strftime("%H:%M"))
        else:
            self.notice = "Nessun avviso"
        # The estimate is advisory; do not change electrical commands here.
        if (self.charging_verified is True and self.departure is not None and
                self._eta_remaining_ac_kwh is not None and
                self._eta_remaining_ac_kwh > 0 and
                self._forecast_rate_kw is not None):
            finish = now + timedelta(hours=self._eta_remaining_ac_kwh/self._forecast_rate_kw)
            # Display in 10-minute buckets: notices cannot churn every
            # minute as the cloud SOC remains unchanged. Safety evaluates
            # on the original unrounded times, never on display buckets.
            shown = datetime.fromtimestamp(
                round(finish.timestamp()/600)*600, timezone.utc)
            local = ZoneInfo(self.hass.config.time_zone)
            deadline = self.departure.astimezone(local)
            if finish > self.departure:
                late_seconds = (finish-self.departure).total_seconds()
                late_minutes_bucket = max(10, ((int(late_seconds)+599)//600)*10)
                warning = ("Obiettivo a rischio: fine stimata " +
                           shown.astimezone(local).strftime("%H:%M") +
                           ", oltre la partenza delle " +
                           deadline.strftime("%H:%M") +
                           f" di circa {late_minutes_bucket} min")
            elif finish > self.departure-timedelta(minutes=30):
                warning = ("Margine di sicurezza sotto 30 min: fine stimata " +
                           shown.astimezone(local).strftime("%H:%M"))
            elif (self.margin_minutes is not None and
                  self.margin_minutes < -30):
                warning = ("Con il carico domestico attuale, il modello "
                           "prudente segnala un rischio per la partenza.")
            else:
                warning = None
            if warning is not None:
                self.notice = (self.notice + ". " + warning
                               if self.notice != "Nessun avviso" else warning)
        elif (self.charging_verified is True and self.departure is not None
              and self._eta_remaining_ac_kwh is None
              and self.margin_minutes is not None
              and self.margin_minutes <= 0
              and self.planning_rate_kw is not None):
            # Conservatively estimated margin after a telemetry gap;
            # alert only, no power raise, no DPM or Start/Stop action.
            warning = ("Margine teorico sotto 30 minuti con dati EV "
                       "parziali: verifica l'orario di partenza")
            self.notice = (self.notice + ". " + warning
                           if self.notice != "Nessun avviso" else warning)

    def _house_subscribe(self, on_now):
        if on_now and self._house_unsub is None:
            self._house_unsub = async_track_state_change_event(
                self.hass, list(self.house_ids), self._on_event)
        if not on_now and self._house_unsub:
            self._house_unsub()
            self._house_unsub = None

    def _reschedule(self, now, connected):
        if self._timer_unsub is not None:
            self._timer_unsub()
            self._timer_unsub = None
        due_dates = []
        if connected:
            due_dates.append(now + timedelta(minutes=1))
        if self._unplug_since and now < self._unplug_since + timedelta(seconds=69):
            due_dates.append(self._unplug_since + timedelta(seconds=69))
        if (self._unplug_restore_since is not None and
                now < self._unplug_restore_since + timedelta(seconds=69)):
            due_dates.append(self._unplug_restore_since + timedelta(seconds=69))
        if (self._supply_restore_candidate is not None and
                now < self._supply_restore_candidate + timedelta(minutes=2)):
            due_dates.append(self._supply_restore_candidate + timedelta(minutes=2))
        # Timer does not produce a new AD measurement: it only rechecks caches.
        if self._pending:
            due_dates.append(self._pending.since + ACK_TIMEOUT)
            # Short-lived local readback checks, no BLE or Shelly polling command.
            due_dates.append(now + timedelta(seconds=5))
        if self._refresh_due and connected:
            due_dates.append(self._refresh_due)
        if (self.delay_enabled and self._scheduled_at and
                self._saved_delay_lease):
            due_dates.append(self._scheduled_at)
        if self._refresh_deadline and connected and now < self._refresh_deadline:
            due_dates.append(self._refresh_deadline)
        due_dates = [dt for dt in due_dates if dt > now]
        if due_dates:
            self._timer_unsub = async_track_point_in_utc_time(
                self.hass, self._on_timer, min(due_dates))

    @callback
    def _on_timer(self, _time):
        self._timer_unsub = None
        self.refresh()

    def _observe_supply_event(self, event):
        """Shelly OFF->ON arms one ON after a BLE OFF->ON within two minutes."""
        relay = self.cfg.get(CONF_WALLBOX_POWER_SWITCH)
        if not relay:
            return
        data = getattr(event, "data", None) or {}
        if data.get("entity_id") != relay:
            return
        old, new = data.get("old_state"), data.get("new_state")
        if (old is None or new is None or
                old.attributes.get("restored") or new.attributes.get("restored")):
            return  # Not a real observed relay edge.
        before, after = on(old.state), on(new.state)
        if before is True and after is False:
            self._supply_restore_candidate = None
            self._supply_ble_rejoined = False
            self._record("power_supply", "physical_relay_went_off")
        elif before is False and after is True:
            # A power cut during a previously owned charging session can
            # temporarily disable real control as 'continuity_unverified'.
            # The physical OFF->ON may still arm restoration: the later
            # VERIFIED unplug clears that fence before any ON is dispatched.
            interrupted = self._blocked == "session_continuity_unverified"
            eligible = (self.mode == "automatic"
                        and (self.real_enabled or interrupted)
                        and not self.explicit_pause
                        and (not self._blocked or interrupted)
                        and self._saved_attempt is None and self._pending is None)
            self._supply_restore_candidate = (
                datetime.now(timezone.utc) if eligible else None)
            self._supply_ble_rejoined = False
            self._record("power_supply", "shelly_power_on_confirmed"
                         if eligible else "shelly_on_not_eligible_for_restore")

    @callback
    def _on_event(self, event):
        """An HA target-entity change can be explicit user intent.

        A SOC sensor update is never a request to resume charging.
        """
        self._observe_supply_event(event)
        latch = self._soc_stop_latch
        pending = self._pending
        if (latch is not None or
                (pending is not None and pending.kind == "soc_stop")):
            data = getattr(event, "data", None) or {}
            changed = data.get("entity_id")
            for car in self.cfg[CONF_VEHICLES]:
                if (not car.get(CONF_TARGET_ENTITY) or
                        car[CONF_TARGET_ENTITY] != changed or
                        (latch and car[CONF_CABLE] != latch.get("vehicle"))):
                    continue
                old, new = data.get("old_state"), data.get("new_state")
                earlier = finite_number(old.state) if old is not None else None
                latest = finite_number(new.state) if new is not None else None
                stop_target = (latch.get("target") if latch else pending.soc_stop_target)
                if earlier is None or latest is None or stop_target is None:
                    continue
                if latest > earlier and latest > float(stop_target):
                    self._soc_resume_request = {
                        "vehicle": car[CONF_CABLE], "target": latest,
                        "old_target": earlier,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    self._record("user_intent", "external_soc_target_increased",
                                 target_soc=latest, previous_target=earlier)
                    self._schedule_save()
                    self.entry.async_create_background_task(
                        self.hass, self._refresh_soc_for_explicit_resume_once(car),
                        "EasyWallbox beta one-shot Fiat SOC refresh")
                else:
                    self._soc_resume_request = None
                    self._schedule_save()
        self.refresh()

    def refresh(self):
        if self._closed:
            return
        now = datetime.now(timezone.utc)
        online = self._ble_online(now) is True
        if (self._supply_restore_candidate is not None and
                now-self._supply_restore_candidate >= timedelta(minutes=2)):
            self._record("power_supply", "restoration_window_expired")
            self._supply_restore_candidate = None
            self._supply_ble_rejoined = False
        if online and self._online is not True:
            if (self._online is False and self._supply_restore_candidate is not None
                    and now-self._supply_restore_candidate < timedelta(minutes=2)
                    and self._reported_binary(self.cfg.get(CONF_WALLBOX_POWER_SWITCH)) is True):
                self._supply_ble_rejoined = True
            link = self._raw(self.cfg[CONF_BLE_CONNECTED])
            self._ble_since = getattr(link, "last_changed", None) or self._age(link)
            # BLE reconnection never changes Start-Stop automatically.
        self._online = online
        cable = self._wallbox_cable(now) if online else None
        if (self._unplug_restore_pending and cable is False
                and self.mode == "manual"):
            self.mode = "automatic"
            self._record("reconciliation", "physical_unplug_returns_to_automatic")
            self._schedule_save()
        if cable is not True:
            # No charging session may exist; no invented electrical effects.
            self._expire_restart_power(now, cable)
        if cable is True and self._unplug_interruption:
            # State 3 had been observed while the station was connected,
            # but plugging back before positive unplug confirmation cannot
            # inherit the previous vehicle/stop ownership.
            self._unplug_interruption = False
            self._blocked = "replug_before_unplug_confirmation"
            self.real_enabled = False
            self._record("interrupted", "replug_before_unplug_confirmation")
        self._recover_preplug_hold(now, cable)
        self._subscriptions(online, cable is True)
        self._idle_guard_subscribe(online, cable)
        if cable is not True:
            self._idle(now, online, cable)
            self._schedule_preplug_release(now, cable)
            self._schedule_normal_on(now, cable)
            self._schedule_supply_restore(now, cable)
            return
        if self._trace_session is None:
            self._trace_session = uuid4().hex
            # Reset only at a newly observed physical cable connection.
            # A transient BLE disconnection does NOT erase session intent.
            self.session_power_kw = float(self.cfg[CONF_BASE_KW])
            self._connect_since = now
            self._refresh_due = None  # armed only by confirmed charging
            self._refresh_issued = False
            self._refresh_start_at = None
            self._refresh_count = 0
            self._refresh_requested_at = self._refresh_deadline = self._refresh_error = None
            self._last_diagnostic_at = None
            self._last_policy_reason = None
            self._facts = {"ble": True, "cable": True}
            self._record("session_open", "wallbox_cable_connected",
                         default_session_power_kw=self.session_power_kw,
                         pending_restart_reconciliation=bool(self._restart_power))
            if isinstance(self._saved_attempt, dict):
                self._record("reconciliation", "previous_command_unconfirmed_no_retry",
                             operation=self._saved_attempt.get("operation"),
                             previous_session=self._saved_attempt.get("session"))
        # Journal the expiration with an established physical-cable session id,
        # even if the car is plugged in but not charging.
        self._expire_restart_power(now, cable)
        self._last_cable = True
        if (self._session_id is None and self._soc_stop_latch is not None and
                self._saved_attempt is None and
                (owned := self._latched_soc_vehicle(now, cable)) is not None):
            self._session_id = self._trace_session
            self._connection = owned[CONF_CABLE]
            self._record("reconciliation", "soc_stop_identity_from_unchanged_wallbox_cable")
        snapshot = self._snapshot(now)
        self._status_acks(now, cable)
        # A brief BLE dropout must not terminate a charge. Re-arm the
        # stabilizer only if the same vehicle, DPM and independently reported
        # EV limit prove the same live session; otherwise remain blocked.
        if (self._blocked == "session_continuity_unverified"
                and not self._saved_attempt and self._dpm_lease is None
                and snapshot["car"] is not None
                and snapshot["car"][CONF_CABLE] == self._connection
                and snapshot["charging"] is True and snapshot["trusted"]
                and self._owned_limit is not None
                and abs(snapshot["actual"]-self._owned_limit) <= .051):
            self._blocked = None
            self.real_enabled = True
            self._record("reconciliation", "ble_recovered_same_charging_session")
        # The pre-plug delayed-start flag is retired by verified DPM
        # release, never by the wall-clock alone or cloud vehicle identity.
        self._house_subscribe(snapshot["charging"] is True)
        if (self._session_id is None and snapshot["charging"] is True
                and self._restart_power is None):
            # New physical charge: cloud identity is not needed for power
            # stabilization. An unresolved previous owned cap, however,
            # must be reconciled before starting a new controller session.
            self._session_id = self._trace_session
            self._power_state = State(
                session_id=self._session_id,
                cap_kw=self.session_power_kw, baseline_kw=self.session_power_kw)
        if snapshot["car"] is None:
            if snapshot["charging"] is True and not self._vehicle_conflict(now, cable):
                self.status, self.reason = ("In carica — veicolo non identificato",
                                            "guest_vehicle_unlimited_planning_budget")
            elif (self._soc_stop_latch is not None and
                    snapshot["charging"] is False and
                    self._soc_stop_latch.get("cable_marker") ==
                    self._continuity_marker(CONF_WALLBOX_CONNECTED)):
                self.status = "Carica terminata — limite SOC raggiunto"
                self.reason = "soc_target_stop_verified_cloud_disconnected"
            else:
                self.status, self.reason = "Da riconciliare", "cable_or_vehicle_ambiguous"
        else:
            identity = snapshot["car"][CONF_CABLE]
            if self._connection and identity != self._connection:
                self._blocked = "vehicle_changed_without_unplug"
                self.real_enabled = False
            if not self._connection:
                # Identification may arrive minutes AFTER physical charging
                # and AFTER a confirmed, guest-safe power regulation.
                self._connection = identity
                if self._restart_power is None:
                    self._schedule_save()
            if self._restart_power is not None:
                self._reconcile_restart_power(snapshot, identity, now)
            # With no explicit pre-plug postponement, DPM=0 is NOT
            # automatically restored. It may be a manual or old-beta stop.
            if self.mode == "manual" or self.explicit_pause:
                self.status = "Manuale" if self.mode == "manual" else "Pausa gestione"
                self.reason = "user_owns_wallbox"
            elif self._blocked:
                self.status, self.reason = "Bloccata", self._blocked
            elif self._pending:
                self.status, self.reason = "In attesa conferma", "awaiting_" + self._pending.kind
            elif self._soc_stop_done:
                self.status = "Carica terminata — limite SOC raggiunto"
                self.reason = "soc_target_stop_verified"
            elif (self._refresh_error and snapshot["charging"] is not True):
                self.status, self.reason = "In attesa dati auto", self._refresh_error
            elif (self._soc_stop_refresh_at and snapshot["charging"] is True and
                  self.soc is not None and self.target_soc is not None and
                  self.soc >= self.target_soc - 5 and
                  not self._soc_stop_fresh(snapshot["car"], now)):
                self.status, self.reason = "In carica — verifica SOC", "waiting_recent_soc_for_stop"
            elif snapshot["target_reached"] is True and snapshot["charging"] is not True:
                cap = self._power_state.cap_kw if self._power_state else None
                base = self.session_power_kw
                if (cap is not None and cap < base-.11 and
                        self._owned_limit is not None):
                    self.status, self.reason = ("Completata — limite da verificare",
                        "car_stopped_with_earlier_owned_ev_cap_manual_attention")
                else:
                    self.status, self.reason = "Completata", "soc_target_reached"
            elif snapshot["charging"] is True:
                if not snapshot["trusted"]:
                    self.status, self.reason = ("In carica — verifica dati",
                                                "source_stale_or_contradictory_no_write")
                elif (self.delay_enabled and self._dpm_lease is None and
                      self._scheduled_at is not None and self._scheduled_at > now):
                    self.status, self.reason = ("In carica — posticipo non applicato",
                                                "charging_began_before_safe_pause")
                elif snapshot["target_reached"] is True:
                    self.status, self.reason = ("In carica — target stimato",
                                                "possible_vehicle_balancing")
                else:
                    self.status, self.reason = "In carica", "normal_or_limited"
            elif snapshot["charging"] is False:
                self.status = "Collegata, non in carica"
                self.reason = "waiting_or_stopped"
            else:
                self.status, self.reason = "Da riconciliare", "charging_unverified"
        self._update_notice(now)
        self._reschedule(now, cable is True)
        self._schedule_preplug_release(now, cable)
        self._schedule_soc_resume(now, snapshot)
        self._schedule_normal_on(now, cable)
        if (self.real_enabled and cable is True and
                self.mode == "automatic" and
                not self.delay_enabled and self._saved_delay_lease is None and
                self._soc_stop_latch is None and
                self._refresh_due is not None and
                snapshot["charging"] is True and
                now >= self._refresh_due):
            if self._refresh_task is None or self._refresh_task.done():
                self._refresh_task = self.entry.async_create_background_task(
                    self.hass, self._request_one_shot_updates(),
                    "EasyWallbox beta vehicle data refresh")
        # Five-minute read-only heartbeat: repeated identical blockers
        # previously produced no log rows for the entire charging session.
        if (snapshot["charging"] is True and self._trace_session is not None
                and (self._last_diagnostic_at is None or
                     now-self._last_diagnostic_at >= timedelta(minutes=5))):
            self._last_diagnostic_at = now
            self._record("diagnostic", self._last_policy_reason or self.reason,
                         status=self.status,
                         phase=(self._power_state.phase if self._power_state else None),
                         source_issues=list(self._facts.get("issues", ())),
                         refresh_error=self._refresh_error,
                         control_enabled=self.real_enabled,
                         block=self._blocked)
        state_key = (self.status, self.reason, self.notice, tuple(self._facts["issues"]))
        if state_key != self._last_key:
            self._last_key = state_key
            self._record("state", self.reason, status=self.status, notice=self.notice)
        self._notify()
        if (self.real_enabled and self.mode == "automatic" and not self.explicit_pause
                and not self._blocked and self._pending is None
                and snapshot["charging"] is True and not self.delay_enabled
                and self._saved_delay_lease is None):
            if self._task is None or self._task.done():
                self._task = self.entry.async_create_background_task(
                    self.hass, self._actuate(self._session_id), "EasyWallbox beta evaluate")

    def _reconcile_terminal_soc_stop(self, now):
        """Clear only an already issued SOC stop after verified physical unplug.

        No BLE write: unrelated unresolved operations remain blocked.
        """
        attempt = self._saved_attempt
        if not isinstance(attempt, dict) or attempt.get("kind") != "soc_stop":
            return
        if (self._wallbox_cable(now) is not False or
                self._charge_state(now) != "Cable Unplugged" or
                self._wallbox_flag(CONF_WALLBOX_CHARGING) is not False):
            return
        ev = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
        if ev is None or ev >= .03:
            return
        switch = self._reported_binary(self.cfg[CONF_START_STOP])
        dpm = self._wallbox_flag(CONF_CHARGE_ENABLED)
        if switch is False and dpm is False:
            restore = True  # Controller previously dispatched the owned SOC stop.
        elif switch is True and dpm is True:
            restore = False  # A person already safely restored the empty station.
        else:
            return  # Never clear an indeterminate past write.
        self._record("reconciliation", ("soc_stop_terminal_unplug_confirmed"
                     if restore else "soc_stop_already_restored_manually"),
                     operation=attempt.get("operation"), ev_kw=ev, dpm_kw=dpm)
        self._saved_attempt = self._pending = None
        self._blocked = None
        self.real_enabled = True
        self._standby_restore_due = restore
        self._soc_stop_latch = None
        self._soc_resume_request = None
        self._schedule_save()

    def _idle(self, now, online, cable):
        """Only the BLE/cable wake-up listeners run outside a connected session."""
        self._house_subscribe(False)
        self._facts = {"ble": online, "cable": cable}
        self._status_acks(now, cable)
        if cable is False:
            self._reconcile_terminal_soc_stop(now)
            if self._unplug_restore_pending:
                self._unplug_restore_pending = False
                self._unplug_restore_since = now
                self._record("reconciliation", "observed_cable_unplug_wait_69s")
            if (self._unplug_restore_since is not None and
                    now-self._unplug_restore_since >= timedelta(seconds=69)):
                self._unplug_restore_since = None
                if not self.delay_enabled and self._saved_delay_lease is None:
                    self._standby_restore_due = True
                    self._record("reconciliation", "confirmed_cable_unplug_standby_on")
                self._schedule_save()
        self._reschedule(now, False)
        if cable is False:
            self._unplug_interruption = False
            if self._restart_review:
                # Positive unplug retires a historic cap's review fence.
                self._restart_review = False
                self._restart_review_info = None
                if self._blocked == "restart_power_evidence_expired_manual_review":
                    self._blocked = None
                    self.real_enabled = self._saved_attempt is None
                self._record("reconciliation", "restart_review_cleared_on_unplug")
                self._schedule_save()
            if self._restart_power is not None and self._trace_session is None:
                # Discard a stale proof on an independently verified unplug,
                # even if no active session was opened during this HA boot.
                self._restart_power = None
                self._schedule_save()
            if self._active_departure is not None:
                # Also retire a persisted deadline when HA was stopped
                # at the instant the physical cable was unplugged.
                self._active_departure = self._active_departure_vehicle = None
                self._schedule_save()
            if self._trace_session:
                self._record("session_close", "cable_unplugged")
                self.mode = "automatic"
                # A confirmed pre-plug delay belongs to the user's
                # appointment, not to a particular cloud vehicle session.
                # Unplugging must not cancel the explicit time or lease.
                # Keep unresolved commands fenced across unplug/restart.
                self._blocked = ("previous_command_unconfirmed_no_retry"
                                 if self._saved_attempt else None)
                self.real_enabled = self._saved_attempt is None
                self._active_departure = self._active_departure_vehicle = None
                self._schedule_save()
            elif self.departure_override is not None:
                self._schedule_save()
            self._trace_session = self._session_id = self._active_departure = None
            self.session_power_kw = float(self.cfg[CONF_BASE_KW])
            self._restart_power = None
            self.departure_override = self._owned_limit = None
            self._gate_key = self._last_key = self._power_state = None
            self._connection = False
            self._soc_stop_done = self._soc_stop_latch is not None
            self._delay_pause_attempted = False
            self.charge_now = self.explicit_pause = False
            self._soc_stop_refresh_at = self._soc_stop_baseline = None
            self._connect_since = self._refresh_due = self._refresh_deadline = None
            self._refresh_start_at = None
            self._refresh_count = 0
            self._house_history.clear()
            self._ev_history.clear()
            self._delivered_ev_kwh = 0.0
            self._delivery_last = None
            self._delivery_gap = False
            self._soc_anchor = None
            self._eta_remaining_ac_kwh = None
            self.status, self.reason = "Scollegata", "cable_unplugged"
            # No OFF command on unplug, ever.
        else:
            if self._trace_session and self._last_cable is True:
                if online and self._unplug_since is not None:
                    # State 3 was observed, but 69s / two AD reports are
                    # intentionally pending. Do not misclassify this as a
                    # BLE outage and disable the owned SOC-stop recovery.
                    self._unplug_interruption = True
                    self._record("decision", "physical_unplug_verification_pending",
                                 action="hold")
                else:
                    self._record("interrupted", "ble_offline" if not online else "cable_unknown")
                    # An actual unverified interruption retains the old fence.
                    if self._owned_limit is not None and self._blocked is None:
                        self._blocked = "session_continuity_unverified"
                        self.real_enabled = False
                self._house_history.clear()
                self._ev_history.clear()
            self.status, self.reason = (("Wallbox non disponibile", "ble_offline_normal")
                                        if not online else ("Da riconciliare", "cable_unknown"))
        self._last_cable = cable
        self.charging_verified = self.vehicle_name = self.departure = None
        self._finish_display = self._energy_display = self.stop_at_target_enabled = None
        self._margin_energy_kwh = self._margin_quality = None
        self.soc = self.target_soc = self.margin_minutes = self.remaining_kwh = None
        self.planning_rate_kw = self._forecast_rate_kw = self.house_kw = None
        self._forecast_quality = None
        self.quality = "offline" if not online else ("idle" if cable is False else "incomplete")
        self._update_notice(now)
        if not online and not self._user_warning and not self._blocked:
            self.notice = "Wallbox spenta o BLE non collegato"
        self._notify()

    def _soc_stop_fresh(self, car, now):
        """Require an independently recent vehicle report before a SOC stop."""
        sensor = self._fresh(car[CONF_SOC], now, SOC_STOP_TTL)
        if sensor is None or finite_number(sensor.state) is None:
            return False
        timestamp_source = car.get(CONF_VEHICLE_LAST_UPDATE)
        if timestamp_source:
            last = self._raw(timestamp_source)
            try:
                stamp = datetime.fromisoformat(last.state) if last else None
            except (ValueError, TypeError):
                stamp = None
            if (stamp is None or stamp.tzinfo is None or
                    not timedelta(0) <= now-stamp <= SOC_STOP_TTL):
                return False
        else:
            stamp = self._age(sensor)
        if self._soc_stop_refresh_at is not None:
            # The Fiat provider records timestamps to whole seconds. The
            # timestamp MUST change, but a fresh second may precede the
            # local button press by a fraction of a second.
            if stamp + timedelta(seconds=2) < self._soc_stop_refresh_at:
                return False
            if self._soc_stop_baseline is not None:
                if timestamp_source:
                    if stamp <= self._soc_stop_baseline:
                        return False
                elif stamp <= self._soc_stop_baseline:
                    return False
        return True

    async def _maybe_stop_at_soc(self, current, now):
        """Only an opted-in car may stop charging, once per session.

        Refresh only when near target, at most once in 20 minutes.
        Revalidate SOC after refresh: pressing a button is not proof
        of fresh vehicle telemetry.
        """
        car = current["car"]
        if (not car.get(CONF_STOP_AT_TARGET, False)
                or self.target_soc is None or self.target_soc >= 100
                or current["charging"] is not True or self._soc_stop_done):
            # At 100% the car owns balancing and charge termination.
            return False
        soc, target = self.soc, self.target_soc
        if (soc is None or target is None or not 0 <= soc <= 100
                or not 1 <= target <= 100 or soc < target-5):
            return False
        button = car.get(CONF_VEHICLE_REFRESH)
        if button and (self._soc_stop_refresh_at is None or
                       now-self._soc_stop_refresh_at >= SOC_STOP_REFRESH_INTERVAL):
            source = car.get(CONF_VEHICLE_LAST_UPDATE)
            before = self._raw(source) if source else self._raw(car[CONF_SOC])
            if source:
                try:
                    self._soc_stop_baseline = (
                        datetime.fromisoformat(before.state) if before else None)
                except (ValueError, TypeError):
                    self._soc_stop_baseline = None
            else:
                self._soc_stop_baseline = self._age(before) if before else None
            self._soc_stop_refresh_at = now
            self._record("vehicle_refresh", "verify_soc_near_target")
            try:
                await self.hass.services.async_call(
                    "button", "press", {"entity_id": button}, blocking=True)
            except Exception as error:
                _LOGGER.warning("SOC refresh failed (%s), never retry blindly",
                                type(error).__name__)
                self._record("vehicle_refresh_error",
                             "soc_refresh_failed_stop_not_authorized")
                # Never stop on unverified SOC, but do not disable the
                # otherwise independent power stabilizer.
            return True
        if not self._soc_stop_fresh(car, now):
            self.status, self.reason = ("In carica — verifica SOC",
                                       "waiting_recent_soc_for_stop")
            self._gate(self.reason)
            self._notify()
            return soc >= target
        if soc >= target:
            if current["dpm_normal"] is not True:
                self.status, self.reason = ("Da riconciliare",
                                            "soc_target_dpm_not_normal")
                self._notify()
                return True
            await self._send("soc_stop", 0.0, None, "fresh_soc_at_target")
            return True
        return False

    async def _actuate(self, session):
        async with self._lock:
            if (self._closed or self._session_id != session or
                    self._wallbox_cable(datetime.now(timezone.utc)) is not True):
                return
            # Recheck immediately before dispatch; an old callback is not
            # permission to command a car which may already be unplugged.
            current = self._snapshot(datetime.now(timezone.utc))
            if (self.mode != "automatic" or not self.real_enabled
                    or self._restart_power is not None
                    or self.explicit_pause or self._pending is not None
                    or self._blocked or current["cable"] is not True
                    or current["charging"] is None):
                return
            if current["trusted"] is not True:
                self._gate(",".join(self._facts["issues"]))
                return
            if self._soc_stop_done:
                return
            if current["target_reached"] is True and current["charging"] is not True:
                # Never restart a car whose target has already been reached.
                return
            if (current["dpm"] is None or current["dpm"] < 0
                    or current["actual"] is None or current["requested"] is None
                    or abs(current["actual"]-current["requested"]) > .051):
                return

            # A charge in progress may ONLY change the EV limit, NEVER
            # operate the Start/Stop switch, including for a delayed start.
            if current["charging"] is True:
                # Postponement cannot be activated during an active charge.
                # An explicitly opted-in SOC stop is the only other OFF path.
                if self._owned_limit is not None and abs(current["actual"]-self._owned_limit) > .11:
                    self._blocked = "external_ev_limit_change"
                    self.status, self.reason = "Bloccata", self._blocked
                    self._gate(self._blocked)
                    self._notify()
                    return
                if current["car"] is not None and await self._maybe_stop_at_soc(
                        current, datetime.now(timezone.utc)):
                    return
                base = self.session_power_kw
                if current["target_reached"] is True:
                    # Restore ONLY an optional cap genuinely owned by this
                    # session and only while Charging is still confirmed.
                    if (self._owned_limit is not None
                            and self._power_state is not None
                            and self._power_state.phase == "LIMITED"
                            and abs(self._owned_limit-current["actual"]) <= .11
                            and abs(base-current["actual"]) >= .11):
                        await self._send("power", base, State(
                            session_id=self._session_id, cap_kw=base,
                            baseline_kw=base), "target_reached_restore_owned_limit")
                    return
                # User's desired session power is the new NORMAL baseline.
                # A change is not a physical effect: an actual BLE write is
                # still fenced, serialized, and ACK-confirmed by _send().
                desired_state = State(
                    session_id=self._session_id, cap_kw=base, baseline_kw=base)
                if self._power_state is None:
                    self._power_state = desired_state
                if self._owned_limit is None:
                    # An unconfirmed intent gives NO ownership. Retain None
                    # on a cancelled pre-dispatch attempt so a later fresh
                    # observation can retry safely, never after an unknown ACK.
                    if abs(current["actual"]-base) > .11:
                        await self._send("power", base, desired_state,
                                         "session_initial_power")
                        return
                    self._owned_limit = current["actual"]  # already verified matching
                    self._power_state = desired_state
                    self._schedule_save()
                elif abs(self._power_state.baseline_kw-base) > .051:
                    # Explicit session override supersedes an older LIMITED
                    # cap; do not carry that cap to a changed baseline.
                    if abs(current["actual"]-base) > .11:
                        await self._send("power", base, desired_state,
                                         "session_power_override")
                        return
                    self._power_state = desired_state
                    self._record("reconciliation", "session_power_already_confirmed",
                                 confirmed_kw=current["actual"])
                o = Observation(
                    at=datetime.now(timezone.utc), session_id=self._session_id,
                    connected=True, charging=True, auto=True, trusted=current["trusted"],
                    house_kw=current["house"], house_at=current["house_at"],
                    dpm_kw=float(self.cfg[CONF_EXPECTED_DPM]), current_kw=current["actual"],
                    # No cloud identity/valid ETA: deliberately use unlimited
                    # planning flexibility for discretionary load reduction.
                    # Actual charging still requires BLE+DPM+Shelly evidence.
                    margin_minutes=(self.margin_minutes
                                    if self.margin_minutes is not None else 1_000_000.0),
                    remaining_budget_kwh=(
                        max(0.0, (self.margin_minutes-45)/60 *
                            self.planning_rate_kw)
                        if self.margin_minutes is not None and
                           self.margin_minutes > 45 and
                           self.planning_rate_kw is not None
                        else 1_000_000.0),
                    max_kw=base,
                )
                state, decision = evaluate(o, self._power_state)
                if decision.reason != "waiting_for_new_shelly_report":
                    self._last_policy_reason = decision.reason
                    self._gate_key = None
                    self._record("policy", decision.reason, action=decision.action,
                                 target_kw=decision.target_kw, phase=decision.phase,
                                 previous_phase=self._power_state.phase, kind=decision.kind,
                                 available_budget_kwh=o.remaining_budget_kwh,
                                 budget_unlimited=self.margin_minutes is None,
                                 spent_budget_kwh=state.spent_budget_kwh,
                                 dpm_only_estimated_kw=round(
                                     dpm_only_kw(o.house_kw, o.dpm_kw, base), 3),
                                 limited_cap_kw=round(state.cap_kw, 3),
                                 incremental_cap_cost_kw=round(max(
                                     0.0, dpm_only_kw(o.house_kw, o.dpm_kw, base)
                                     - state.cap_kw), 3),
                                 quiet_15min_worst_case_kwh=round(
                                     max(0.0, base-state.cap_kw)*.25, 3))
                if decision.action == "set_limit" and decision.target_kw is not None:
                    # Recompute from the exact fresh source immediately prior
                    # to a write. Never command with stale or unknown SOC.
                    if abs(decision.target_kw-current["actual"]) >= .11:
                        await self._send("power", decision.target_kw, state, decision.reason)
                    else:
                        self._power_state = state
                else:
                    self._power_state = state
                return

            # No automatic Start/Stop on connection or while idle.
            # The wallbox initiates a normal charge; no EV limit writes
            # are allowed until charging and vehicle data are confirmed.
            self._gate("idle_waiting_for_wallbox_or_car")
            return

    def _latched_soc_vehicle(self, now, cable):
        """Prove the original car is still physically at the wallbox.

        The Fiat cloud cable signal may read OFF while DPM=0. An
        uninterrupted wallbox Car Connected marker, not the Fiat cloud
        signal, is the ownership proof. Never adopt another car's ON.
        """
        latch = self._soc_stop_latch
        if cable is not True or not isinstance(latch, dict):
            return None
        vehicle = latch.get("vehicle")
        car = next((v for v in self.cfg[CONF_VEHICLES]
                    if v[CONF_CABLE] == vehicle), None)
        if car is None:
            return None
        marker = latch.get("cable_marker")
        if marker:
            if marker != self._continuity_marker(CONF_WALLBOX_CONNECTED):
                return None
        else:
            # A latch without the marker (test/legacy) is not enough
            # to restart unless cloud identity is independently proven.
            observed = self._select_vehicle(now, cable)
            if observed is None or observed[CONF_CABLE] != vehicle:
                return None
        if any(self._reported_binary(other[CONF_CABLE]) is True
               for other in self.cfg[CONF_VEHICLES]
               if other[CONF_CABLE] != vehicle):
            return None
        return car

    def _schedule_soc_resume(self, now, snapshot):
        """Only a user's raised SOC target can re-arm a stopped, plugged Fiat."""
        latch, request = self._soc_stop_latch, self._soc_resume_request
        if (self._closed or not self.real_enabled or self.mode != "automatic"
                or self.explicit_pause or self._blocked or self._pending
                or self._saved_attempt or self.delay_enabled or self._saved_delay_lease
                or latch is None or request is None or
                snapshot["cable"] is not True or snapshot["charging"] is not False
                or snapshot["charge_state"] == "Error" or not snapshot["dpm_parked"]
                or snapshot["ev_kw"] is None or snapshot["ev_kw"] >= .03
                or self._reported_binary(self.cfg[CONF_START_STOP]) is not False):
            return
        car = self._latched_soc_vehicle(now, snapshot["cable"])
        if car is None or car[CONF_CABLE] != request.get("vehicle"):
            return
        target = (self._number(car.get(CONF_TARGET_ENTITY), now, None)
                  if car.get(CONF_TARGET_ENTITY) else self.fixed_target(car))
        soc = self._number(car[CONF_SOC], now, CAR_TTL)
        if (target is None or target != request.get("target")
                or soc is None or soc >= target
                or not self._soc_stop_fresh(car, now)):
            return
        if self._park_task is None or self._park_task.done():
            self._park_task = self.entry.async_create_background_task(
                self.hass, self._resume_soc_stopped(),
                "EasyWallbox prior iterations user-authorized SOC restart")

    async def _resume_soc_stopped(self):
        async with self._lock:
            now = datetime.now(timezone.utc)
            if self._write_block("soc_resume", 1.0,
                                 self._session_id, now) is None:
                await self._send("soc_resume", 1.0,
                                 None, "explicitly_increased_target_after_soc_stop")

    def _write_block(self, kind, target, session, now):
        if not self._telemetry_ok():
            return "telemetry_not_fresh"
        if kind in ("delay_arm", "delay_release", "normalize_on", "supply_restore", "mode_auto_on"):
            cable = self._wallbox_cable(now)
            charging = self._wallbox_flag(CONF_WALLBOX_CHARGING)
            ev = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
            dpm = self._wallbox_flag(CONF_CHARGE_ENABLED)
            switch = self._reported_binary(self.cfg[CONF_START_STOP])
            if (self._closed or not self.real_enabled or self._blocked or
                    self.explicit_pause or self.mode != "automatic" or
                    self._ble_online(now) is not True or cable is None or
                    charging is not False or ev is None or ev >= .03 or
                    self._charge_state(now) == "Error" or
                    session != self._idle_park_trace or session is None):
                return "standby_electrical_interlocks_unverified"
            if kind == "delay_arm":
                if (cable is not False or not self.delay_enabled or
                        self._scheduled_at is None or now >= self._scheduled_at or
                        self._saved_delay_lease is not None or
                        self._dpm_lease is not None or
                        switch is not True or dpm is not True or target != 0.0):
                    return "delay_requires_unplugged_positive_dpm"
            elif kind == "delay_release":
                own = self._saved_delay_lease
                if (not isinstance(own, dict) or
                        own.get("kind") != "preplug" or
                        self._scheduled_at is None or
                        own.get("start") != self._scheduled_at.isoformat() or
                        self._dpm_lease is None or
                        abs(float(self._dpm_lease)-target) > .051 or
                        abs(target-1.0) > .051 or
                        dpm is not False or switch is not False or
                        (self.delay_enabled and now < self._scheduled_at)):
                    return "owned_preplug_release_not_verified"
            elif kind == "supply_restore":
                relay = self.cfg.get(CONF_WALLBOX_POWER_SWITCH)
                charge = self._raw(self.cfg.get(CONF_CHARGE_STATE))
                if (relay is None or not self._supply_restore_candidate
                        or now-self._supply_restore_candidate >= timedelta(minutes=2)
                        or not self._supply_ble_rejoined
                        or self._reported_binary(relay) is not True
                        or cable is not False
                        or self._charge_state(now) != "Cable Unplugged"
                        or charge is None or self._age(charge) <= self._supply_restore_candidate
                        or self.delay_enabled or self._saved_delay_lease is not None
                        or self._dpm_lease is not None or self._soc_stop_latch is not None
                        or self._standby_restore_due or dpm is not False or switch is not False
                        or abs(target-1.0) > .051):
                    return "supply_restore_requires_verified_power_cycle_and_unplug"
            elif kind == "mode_auto_on":
                if (self.delay_enabled or self._saved_delay_lease is not None
                        or self._dpm_lease is not None or self._soc_stop_latch is not None
                        or self._standby_restore_due or dpm is not False or
                        switch is not False or
                        abs(target-1.0) > .051):
                    return "manual_to_auto_requires_verified_idle_dpm0"
            else:  # normalize_on: only after a true state-3 unplug
                if (self.delay_enabled or self._saved_delay_lease is not None or
                        self._dpm_lease is not None or cable is not False or
                        not (self._standby_restore_due or self._soc_stop_latch) or
                        self._charge_state(now) != "Cable Unplugged" or
                        dpm is not False or switch is not False or
                        abs(target-1.0) > .051):
                    return "normal_on_requires_verified_unplug"
            return None
        if kind == "soc_resume":
            cable = self._wallbox_cable(now)
            car = self._latched_soc_vehicle(now, cable)
            soc = self._number(car[CONF_SOC], now, CAR_TTL) if car else None
            desired = (self._number(car.get(CONF_TARGET_ENTITY), now, None)
                       if car and car.get(CONF_TARGET_ENTITY) else self.fixed_target(car))
            latch, request = self._soc_stop_latch, self._soc_resume_request
            if (self._closed or not self.real_enabled or self._blocked or
                    self.mode != "automatic" or self.explicit_pause or
                    self.delay_enabled or self._saved_delay_lease is not None or
                    self._dpm_lease is not None or cable is not True or
                    car is None or self._session_id != session or
                    not session or latch is None or request is None or
                    car[CONF_CABLE] != latch.get("vehicle") or
                    car[CONF_CABLE] != request.get("vehicle") or
                    desired is None or desired != request.get("target") or
                    soc is None or soc >= desired or
                    not self._soc_stop_fresh(car, now) or
                    self._wallbox_flag(CONF_WALLBOX_CHARGING) is not False or
                    self._charge_state(now) == "Error" or
                    self._reported_binary(self.cfg[CONF_START_STOP]) is not False or
                    self._wallbox_flag(CONF_CHARGE_ENABLED) is not False or
                    (ev := self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)) is None or
                    ev >= .03 or
                    abs(target-1.0) > .051):
                return "soc_resume_not_explicit_or_not_electrically_safe"
            return None
        if kind not in ("power","soc_stop"):
            return "unknown_command"
        if (self._closed or not self.real_enabled or self._blocked or self.explicit_pause
                or self.mode != "automatic" or self._session_id != session or not session
                or self._wallbox_cable(now) is not True):
            return "session_no_longer_authorized"
        current = self._snapshot(now)
        car = current["car"]
        if (self._vehicle_conflict(now, current["cable"]) or
                (kind == "soc_stop" and
                 (car is None or car[CONF_CABLE] != self._connection)) or
                (car is not None and self._connection and
                 car[CONF_CABLE] != self._connection) or
                current["trusted"] is not True or current["charging"] is not True
                or not current["dpm_normal"] or
                self._reported_binary(self.cfg[CONF_START_STOP]) is not True):
            return "active_charge_not_verified"
        if kind == "power":
            number = self._raw(self.cfg[CONF_REQUESTED_LIMIT])
            limits = [finite_number(number.attributes.get(key)) for key in ("min", "max", "step")]
            low, high, step = limits
            if (None in limits or step <= 0 or not low <= target <= high or
                    abs((target-low)/step - round((target-low)/step)) > 1e-5):
                return "ev_number_range_or_step_unverified"
            if (self._owned_limit is not None and
                    abs(current["actual"]-self._owned_limit) > .051):
                return "external_ev_limit_change"
        elif kind == "soc_stop":
            if (not car.get(CONF_STOP_AT_TARGET) or self.target_soc is None
                    or self.target_soc >= 100 or not current["target_reached"]
                    or not self._soc_stop_fresh(car, now)):
                return "soc_stop_not_verified"
        return None

    async def _send(self, kind, target, next_state, reason):
        """Persist one intent and reread the interlocks after yielding to I/O."""
        if self._pending is not None or self._saved_attempt is not None:
            self._gate("another_operation_unresolved")
            return
        now = datetime.now(timezone.utc)
        session = (self._idle_park_trace if kind in ("delay_arm","delay_release","normalize_on","supply_restore","mode_auto_on")
                   else self._session_id)
        veto = self._write_block(kind, target, session, now)
        if veto:
            self._gate(veto)
            return
        expected_kw = target if kind in ("power","delay_release","normalize_on","soc_resume","supply_restore","mode_auto_on") else 0.0
        p = Pending(kind, target, now, next_state, uuid4().hex, session,
                    cable=self._wallbox_cable(now) if kind in ("delay_arm","delay_release","normalize_on","supply_restore","mode_auto_on") else None,
                    soc_stop_target=self.target_soc if kind == "soc_stop" else None,
                    vehicle=(self._connection if kind == "soc_stop" else
                             (self._soc_stop_latch or {}).get("vehicle")
                             if kind == "soc_resume" else None),
                    cable_marker=(self._continuity_marker(CONF_WALLBOX_CONNECTED)
                                  if kind in ("soc_stop","soc_resume","power") else None))
        self._pending = p
        self._saved_attempt = {"operation": p.operation, "kind": kind,
                               "session": session, "expected_kw": expected_kw}
        self._record("intent", reason, operation=p.operation, kind=kind, expected_kw=expected_kw)
        decision_evidence = (self._facts.get("house_at"), self.soc, self.target_soc,
                             self.departure, self._scheduled_at)
        try:
            await self._save()
        except Exception as error:
            self._fail_command(p, "command_intent_not_saved")
            _LOGGER.error("Intento beta non salvato (%s)", type(error).__name__)
            return
        now = datetime.now(timezone.utc)
        veto = self._write_block(kind, target, session, now)
        if (kind == "power" and next_state is not None and decision_evidence !=
                (self._facts.get("house_at"), self.soc, self.target_soc,
                 self.departure, self._scheduled_at)):
            veto = "decision_inputs_changed_before_dispatch"
        if veto or self._pending is not p:
            self._journal.record(self._trace_session or self._idle_park_trace, "cancelled", veto or "session_changed",
                                 operation=p.operation, kind=kind)
            if self._pending is p:
                self._pending = self._saved_attempt = None
                await self._save()
            # A cancelled pre-dispatch attempt does not produce a BLE write.
            return
        p.since, p.dispatched = now, True
        self.last_command = f"{kind}:{expected_kw:.1f}"
        self.reason = f"requested_{kind}_not_yet_confirmed"
        self._record("dispatched", reason, operation=p.operation, kind=kind,
                     expected_kw=expected_kw)
        self._notify()
        try:
            async with asyncio.timeout(ACK_TIMEOUT.total_seconds()):
                if kind == "power":
                    await self.hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": self.cfg[CONF_REQUESTED_LIMIT], "value": target},
                        blocking=True)
                else:
                    service = "turn_off" if kind in ("delay_arm","soc_stop") else "turn_on"
                    await self.hass.services.async_call(
                        "switch", service,
                        {"entity_id": self.cfg[CONF_START_STOP]}, blocking=True)
        except Exception as error:
            if self._pending is p:
                self._fail_command(p, "service_error_" + kind)
            _LOGGER.warning("Servizio beta %s fallito (%s)", kind, type(error).__name__)
        self.refresh()

    def add_listener(self, cb, value):
        """Write an HA entity only when its own public state or attributes change."""
        previous = value()

        def changed():
            nonlocal previous
            current = value()
            if current != previous:
                previous = current
                cb()

        self._listeners.add(changed)
        return lambda: self._listeners.discard(changed)

    async def async_change(self, field, value):
        previous_mode = self.mode
        if field == "mode" and value in ("automatic", "manual"):
            self.mode = value
            # Manual overrides automatic action for the ENTIRE session.
            # A confirmed unplug ends this session and returns the mode to AUTO.
            if value == "manual":
                self.reason = "manual_session_no_wallbox_commands"
        elif field == "real":
            if not value:
                self.real_enabled = False
                self._blocked = None
            elif (self.mode == "automatic" and not self._saved_attempt and
                  self._wallbox_cable(datetime.now(timezone.utc)) is not None and
                  self._charge_state(datetime.now(timezone.utc)) != "Error"):
                self.real_enabled = True
                self._blocked = None
                if self._restart_review:
                    self._record("reconciliation", "restart_review_acknowledged_by_user")
                    self._restart_review = False
                    self._restart_review_info = None
            else:
                raise ValueError("Enable only in AUTO with valid BLE and no competing automations")
        elif field == "delay":
            if value and self.delay_enabled:
                self.refresh()
                return
            if value:
                now = datetime.now(timezone.utc)
                try:
                    candidate = validate_delay(
                        now, self.preferred_start, self.hass.config.time_zone)
                except ValueError:
                    self._user_warning = (
                        "Posticipo rifiutato: orario futuro entro 12 ore.")
                    self.refresh()
                    raise
                # The user must explicitly arm OFF *before* plugging a car.
                # A charging/plugged car must not be interrupted by this UI.
                cable = self._wallbox_cable(now)
                charging = self._wallbox_flag(CONF_WALLBOX_CHARGING)
                ev = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
                dpm = self._wallbox_flag(CONF_CHARGE_ENABLED)
                if (not self.real_enabled or self.mode != "automatic" or
                        self.explicit_pause or self._blocked or
                        self._pending or self._saved_attempt or
                        self._soc_stop_latch is not None or cable is not False or
                        charging is not False or self._charge_state(now) == "Error" or
                        ev is None or ev >= .03 or
                        self._reported_binary(self.cfg[CONF_START_STOP]) is not True or
                        dpm is None or
                        dpm is not True):
                    self._user_warning = (
                        "Posticipo rifiutato: attivarlo prima di collegare "
                        "l'auto, con wallbox libera, DPM normale e BLE disponibile.")
                    self._record("user_intent_rejected", "preplug_delay_requires_idle_wallbox")
                    self.refresh()
                    raise ValueError("Posticipo disponibile solo prima di collegare l'auto")
                self._user_warning = None
                self._scheduled_at = candidate
                self.delay_enabled = True
                self._idle_park_trace = uuid4().hex
                await self._save()
                async with self._lock:
                    await self._send("delay_arm", 0.0, None,
                                     "user_armed_delayed_charge_before_plug")
                # A pre-dispatch veto must not leave a fake active delay.
                # A DISPATCHED but unconfirmed command instead stays fenced.
                if self._pending is None and self._saved_delay_lease is None and (
                        self._saved_attempt is None):
                    self.delay_enabled = False
                    self._scheduled_at = None
                    self._idle_park_trace = None
                    self._user_warning = "Posticipo non applicato: controlli cambiati"
                    await self._save()
                    self.refresh()
                    raise ValueError("Posticipo non applicato: nessun comando confermato")
            else:
                if (self._pending and self._pending.kind == "delay_arm"):
                    raise ValueError("Attendere la conferma del DPM0 per annullare il posticipo")
                self._user_warning = None
                self.delay_enabled = False
                # Retain the original absolute time and confirmed lease
                # until one verified ON has actually restored DPM.
                if self._saved_delay_lease is None:
                    self._scheduled_at = None
                self._delay_pause_attempted = False
        elif field == "time":
            if not isinstance(value, time):
                raise ValueError("time required")
            try:
                appointment = (validate_delay(
                    datetime.now(timezone.utc), value,
                    self.hass.config.time_zone) if self.delay_enabled else None)
            except ValueError:
                self._user_warning = (
                    "Nuovo orario rifiutato: deve essere futuro entro "
                    "12 ore. Posticipo precedente invariato.")
                self.refresh()
                raise
            self._user_warning = None
            self.preferred_start = value
            if self.delay_enabled:
                self._scheduled_at = appointment
                if (self._dpm_lease is not None and
                        isinstance(self._saved_delay_lease, dict)):
                    # The same confirmed pause has a new explicit resume
                    # appointment; keep its persisted provenance consistent.
                    self._saved_delay_lease["start"] = appointment.isoformat()
                self._delay_pause_attempted = False
        elif field == "ready_by":
            if not isinstance(value, time):
                raise ValueError("orario HH:MM richiesto")
            now_utc = datetime.now(timezone.utc)
            snap = self._snapshot(now_utc)
            if snap["cable"] is not True or snap["car"] is None:
                raise ValueError("Collega e identifica un'auto prima di scegliere la partenza")
            base = self._departure(now_utc, snap["car"])
            if base is None:
                raise ValueError("orario base dell'auto non disponibile")
            # A clock edit changes the deadline of the CURRENT session,
            # not the next day or the saved weekday/weekend car profile.
            local_base = base.astimezone(ZoneInfo(self.hass.config.time_zone))
            override = datetime.combine(
                local_base.date(), value.replace(tzinfo=None),
                tzinfo=local_base.tzinfo)
            if override <= now_utc.astimezone(local_base.tzinfo):
                raise ValueError("L'orario Auto pronta entro deve essere futuro")
            self.departure_override = override
        elif field == "departure":
            if value is not None and (not isinstance(value, datetime)
                                       or value.utcoffset() is None):
                raise ValueError("timezone aware departure required")
            self.departure_override = value
            if value is None:
                self._active_departure = None
        elif field == "now":
            self.charge_now = True
        elif field == "pause":
            # User intent, not a DPM command; actual stop is manual via ESPHome.
            self.explicit_pause = True
            self.real_enabled = False
        elif field == "clear_pause":
            self.explicit_pause = False
        else:
            raise ValueError("invalid beta control")
        self._record("user_intent", field, value=str(value))
        if field in ("mode", "real", "delay", "time", "departure", "ready_by"):
            await self._save()
        if (field == "mode" and previous_mode == "manual" and value == "automatic"
                and self._reported_binary(self.cfg[CONF_START_STOP]) is False):
            self._idle_park_trace = uuid4().hex
            async with self._lock:
                await self._send("mode_auto_on", 1.0,
                                 None, "user_changed_manual_to_automatic")
        self.refresh()

    def start(self):
        initial = [self.cfg[CONF_BLE_CONNECTED]]
        if self.cfg.get(CONF_WALLBOX_POWER_SWITCH):
            initial.append(self.cfg[CONF_WALLBOX_POWER_SWITCH])
        self._sensor_unsub = async_track_state_change_event(
            self.hass, initial, self._on_event)
        self.session_history.start()  # Read-only counters; no BLE traffic
        self.refresh()

    def _idle_guard_subscribe(self, online, cable):
        """Observe only transition-relevant cached HA states while idle.

        At BLE reconnection, DPM/AD fields may appear AFTER the cable
        already reports OFF. The cable can remain OFF unchanged for days.
        Temporarily listen for fresh DPM, fault, Charging, switch and EV
        reports until the confirmed idle OFF has been reconciled.
        No polling and no wallbox refresh command.
        """
        switch_state = self._reported_binary(self.cfg[CONF_START_STOP])
        monitor = (online and cable is False and self.real_enabled and
                   self.mode == "automatic" and not self._blocked and
                   (self.delay_enabled or self._saved_delay_lease is not None
                    or self._pending is not None or
                    self._supply_restore_candidate is not None or
                    self._standby_restore_due or switch_state is False))
        if monitor and self._idle_guard_unsub is None:
            ids = [self.cfg[k] for k in (
                CONF_WALLBOX_CHARGING,
                CONF_CHARGE_ENABLED, CONF_START_STOP, CONF_EV_POWER)]
            self._idle_guard_unsub = async_track_state_change_event(
                self.hass, ids, self._on_event)
        elif not monitor and self._idle_guard_unsub is not None:
            self._idle_guard_unsub()
            self._idle_guard_unsub = None

    def _subscriptions(self, online, connected):
        if online and self._cable_unsub is None:
            self._cable_unsub = async_track_state_change_event(
                self.hass, [self.cfg[CONF_WALLBOX_CONNECTED]] +
                ([self.cfg[CONF_CHARGE_STATE]] if self.cfg.get(CONF_CHARGE_STATE) else []),
                self._on_event)
        elif not online and self._cable_unsub:
            self._cable_unsub()
            self._cable_unsub = None
        if connected and self._connected_unsub is None:
            ids = {self.cfg[k] for k in (*WALLBOX_ENTITIES, CONF_EV_POWER)
                   if k not in (CONF_WALLBOX_CONNECTED, CONF_BLE_CONNECTED)}
            if self.cfg.get(CONF_CHARGE_STATE):
                ids.add(self.cfg[CONF_CHARGE_STATE])
            for car in self.cfg[CONF_VEHICLES]:
                ids.update(car[k] for k in (CONF_CABLE, CONF_SOC, CONF_TARGET_ENTITY,
                                            CONF_VEHICLE_LAST_UPDATE) if car.get(k))
            self._connected_unsub = async_track_state_change_event(
                self.hass, sorted(ids), self._on_event)
        elif not connected and self._connected_unsub:
            self._connected_unsub()
            self._connected_unsub = None

    async def async_close(self):
        self._closed = True
        self.real_enabled = False
        if self._timer_unsub:
            self._timer_unsub()
            self._timer_unsub = None
        if self._sensor_unsub:
            self._sensor_unsub()
            self._sensor_unsub = None
        self._subscriptions(False, False)
        self._idle_guard_subscribe(False, None)
        self._house_subscribe(False)
        if self._task:
            await self._task
        if self._refresh_task:
            await self._refresh_task
        if self._park_task:
            await self._park_task
        if self._save_tasks:
            await asyncio.gather(*tuple(self._save_tasks))
        if self._trace_session:
            self._record("unload", "controller_unloaded",
                         pending=self._pending.operation if self._pending else None)
        await self.session_history.async_close()
        await self._journal.async_flush()
        self._listeners.clear()
