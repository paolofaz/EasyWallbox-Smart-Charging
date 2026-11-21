"""Event-driven real charging controller with one exclusive command owner.

Automatic control is opt-in via integration Options and can survive reboot.
All electrical writes still require current BLE, cable and meter validation.
A Home Assistant service success is not a BLE acknowledgement.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import *
from .sources import finite_number, on, power_kw, next_departure
from .rc_policy import Observation, State, evaluate
from .planner_rate import estimate_ac_kw, margin_minutes as estimate_margin
from .delay_window import validate_delay

_LOGGER = logging.getLogger(__name__)
WALLBOX_TTL = timedelta(minutes=2)
DPM_TTL = timedelta(minutes=5)
SHELLY_TTL = timedelta(minutes=3)
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


class RCController:
    """Single local controller with no blind retry and no retained action lease."""

    def __init__(self, hass: HomeAssistant, entry):
        self.hass, self.entry = hass, entry
        self.cfg = {**entry.data, **entry.options}
        self.house_ids = tuple(self.cfg[CONF_HOUSE_SOURCES])
        self.mode = "automatic"
        self.real_enabled = False        # loaded from explicit config opt-in
        self.delay_enabled = False
        self.preferred_start = time(23, 0)
        self.departure_override = None
        self.charge_now = False
        self.explicit_pause = False
        self.status = "Pronto, controllo reale disabilitato"
        self.reason = "manual_enable_required_after_startup"
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
        self.planning_rate_kw = None
        self._house_history = deque(maxlen=48)
        self._ev_history = deque(maxlen=48)
        self.house_kw = None
        self.last_command = None
        self.last_ack = None
        self._connection = False
        self._session_id = None
        self._seq = 0
        self._active_departure = None
        self._scheduled_at = None
        self._delay_pause_attempted = False
        self._last_cable = None
        self._connect_since = None
        self._disconnect_since = None
        self._ev_idle_since = None
        self._park_attempted = False
        self._park_owned = False
        self._soc_stop_done = False
        self._soc_stop_refresh_at = None
        self._soc_stop_baseline = None
        self._soc_stop_last_error = None
        self._fixed_target_overrides = {}
        self._refresh_due = None
        self._refresh_issued = False
        self._refresh_requested_at = None
        self._refresh_deadline = None
        self._refresh_targets = ()
        self._refresh_error = None
        self._prepared_session = None
        self._wallbox_refresh_sent = False
        self._start_refresh_attempted = False
        self._start_refresh_at = None
        self._power_state: State | None = None
        self._owned_limit: float | None = None
        self._dpm_lease: float | None = None
        self._saved_delay_lease = None
        self._pending: Pending | None = None
        self._blocked = None
        self._last_key = None
        self._listeners = set()
        self._sensor_unsub = None
        self._house_unsub = None
        self._timer_unsub = None
        self._task = None
        self._refresh_task = None
        self._lock = asyncio.Lock()
        self._store = Store(hass, 1, "easywallbox_smart_rc_" + entry.entry_id)

    async def async_load(self):
        saved = await self._store.async_load() or {}
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
        self._fixed_target_overrides = (saved.get("fixed_target_overrides", {})
                                        if isinstance(saved.get("fixed_target_overrides", {}), dict)
                                        else {})
        # A persisted proven parking intent is not a fresh DPM readback.
        self._park_owned = saved.get("park_owned") is True
        lease = saved.get("delayed_lease")
        self._saved_delay_lease = lease if isinstance(lease, dict) else None
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
        # Opt-in is persistent in HA config, not an extra UI switch.
        # A restart changes no physical wallbox state: read it back first.
        self.real_enabled = bool(self.cfg.get(CONF_AUTOMATIC_CONTROL_ENABLED, False))
        self._owned_limit = self._dpm_lease = self._pending = None
        self._blocked = None

    async def _save(self):
        await self._store.async_save({
            "mode": self.mode, "delay": self.delay_enabled,
            "park_owned": self._park_owned,
            "delayed_lease": self._saved_delay_lease,
            "fixed_target_overrides": self._fixed_target_overrides,
            "start": self.preferred_start.isoformat(timespec="minutes"),
            "scheduled_at": (self._scheduled_at.isoformat()
                             if self.delay_enabled and self._scheduled_at else None),
            "departure": self.departure_override.isoformat()
            if self.departure_override else None,
        })

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
        self._fixed_target_overrides[cable] = {
            "configured": car[CONF_TARGET_FIXED], "value": int(value)}
        await self._save()
        self.refresh()

    def _raw(self, entity):
        return self.hass.states.get(entity) if entity else None

    @staticmethod
    def _age(state):
        return getattr(state, "last_reported", None) or state.last_updated

    def _fresh(self, entity, now, ttl):
        state = self._raw(entity)
        if state is None or state.state in ("unknown", "unavailable", ""):
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
        connection = self.cfg.get(CONF_BLE_CONNECTED)
        if connection:
            state = self._raw(connection)
            return on(state.state) if state and state.state not in (
                "unavailable", "unknown", "") else None
        return self._binary(self.cfg[CONF_TELEMETRY_FRESH], now)

    def _wallbox_cable(self, now):
        """A stable OFF remains valid while an independent BLE ON confirms it."""
        if self._ble_online(now) is not True:
            return None
        state = self._raw(self.cfg[CONF_WALLBOX_CONNECTED])
        return on(state.state) if state and state.state not in (
            "unavailable", "unknown", "") else None

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
        self.entry.async_create_background_task(
            self.hass, self._save(), "EasyWallbox RC save verified parking")

    def _status_acks(self, now, cable):
        p = self._pending
        if p is None:
            return
        if p.kind == "park" and cable is not False:
            self._blocked = "park_interrupted_or_cable_unknown"
            self._pending = None
            self.real_enabled = False
            return
        if cable is not True and p.kind != "park":
            self._blocked = "pending_command_cable_lost"
            self._pending = None
            self.real_enabled = False
            return
        status = self._raw(self.cfg[CONF_COMMAND_STATUS])
        if status is None or status.last_updated <= p.since:
            status = None
        flag = status.state if status else ""
        confirmed_ev = self._power(self.cfg[CONF_CONFIRMED_LIMIT], now)
        confirmed_dpm = self._power(self.cfg[CONF_DPM_CONFIRMED], now, DPM_TTL)
        charge_enabled = self._binary(self.cfg[CONF_CHARGE_ENABLED], now)
        valid = False
        if p.kind in ("power", "prepare"):
            requested = self._power(self.cfg[CONF_REQUESTED_LIMIT], now)
            valid = (flag in ("Verified charge power", "Confirmed charge power") and confirmed_ev is not None
                     and requested is not None and abs(confirmed_ev-p.target) <= .11
                     and abs(requested-p.target) <= .11)
        elif p.kind in ("pause", "park", "soc_stop", "delay_pause"):
            valid = (flag in ("Verified DPM", "Confirmed DPM") and confirmed_dpm is not None
                     and confirmed_dpm <= .06 and charge_enabled is False)
            if p.kind in ("soc_stop", "delay_pause"):
                observed = self._binary(self.cfg[CONF_WALLBOX_CHARGING], now)
                ev = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
                valid = valid and observed is False and ev is not None and ev < .03
        elif p.kind == "resume":
            valid = (flag in ("Verified DPM", "Confirmed DPM") and
                     confirmed_dpm is not None and
                     abs(confirmed_dpm-p.target) <= .11 and charge_enabled is True)
        if valid:
            if p.kind in ("power", "prepare"):
                self._owned_limit = p.target
                if p.next_state is not None:
                    self._power_state = p.next_state
                if p.kind == "prepare":
                    self._prepared_session = self._session_id
            elif p.kind in ("pause", "delay_pause"):
                self._dpm_lease = p.target
                if p.kind == "delay_pause" and self._scheduled_at is not None:
                    self._saved_delay_lease = {
                        "vehicle": self._connection,
                        "start": self._scheduled_at.isoformat(),
                        "dpm": p.target,
                    }
                    self._schedule_save()
            elif p.kind == "soc_stop":
                self._soc_stop_done = True
                self._park_owned = True
                self._schedule_save()
            elif p.kind == "park":
                self._park_owned = True
                self._schedule_save()
            elif p.kind == "resume":
                self._dpm_lease = None
                self._saved_delay_lease = None
                self._park_owned = False
                self._schedule_save()
            self.last_ack = now.isoformat(timespec="seconds")
            self._pending = None
            self.reason = "confirmed_" + p.kind
            return
        if now-p.since >= ACK_TIMEOUT:
            if p.kind == "park":
                self._park_owned = False
                self._schedule_save()
            self._blocked = "unconfirmed_" + p.kind + "_no_retry"
            self._pending = None
            self.real_enabled = False

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

    def _recover_verified_delay_lease(self, snapshot):
        """Restore previous ownership only from matching, current BLE facts.

        A saved lease is not evidence: cable, EV identity, DPM0,
        Charge Enabled OFF, Charging OFF and Shelly idle are required.
        Never adopt an external/manual DPM0 pause.
        """
        saved = self._saved_delay_lease
        if not isinstance(saved, dict) or self._dpm_lease is not None:
            return False
        car = snapshot["car"]
        if not self.delay_enabled or self._scheduled_at is None or car is None:
            return False
        try:
            valid = (saved.get("vehicle") == car[CONF_CABLE] and
                     saved.get("start") == self._scheduled_at.isoformat() and
                     abs(float(saved.get("dpm")) -
                         float(self.cfg[CONF_EXPECTED_DPM])) <= .11 and
                     snapshot["dpm_parked"] is True and
                     snapshot["charging"] is False and
                     snapshot["ev_kw"] is not None and
                     snapshot["ev_kw"] < .03 and
                     snapshot["telemetry"] is True and
                     snapshot["active"] is True and snapshot["fault"] is False)
        except (ValueError, TypeError):
            return False
        if valid:
            self._dpm_lease = float(saved["dpm"])
            return True
        return False

    def _car_update_ready(self, now, car):
        """A refresh button press is NOT new vehicle data.

        When a per-car source timestamp is configured, demand a truly newer
        upstream update. Otherwise require a new SOC report after plugging.
        """
        if self._connect_since is None:
            return False
        if self._refresh_due is not None and not self._refresh_issued:
            return False
        if self._refresh_error:
            return False
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
                     and stamp >= since)
        else:
            state = self._raw(car[CONF_SOC])
            ready = bool(state and self._age(state) >= since)
        if ready:
            return True
        if self._refresh_deadline and now >= self._refresh_deadline:
            self._refresh_error = "car_update_not_confirmed_after_one_request"
            self.status, self.reason = "In attesa dati auto", self._refresh_error
            self._notify()
        return False

    async def _request_one_shot_updates(self):
        """20 s after plug; one cloud button per selected/unknown vehicle.

        Cloud refresh is not an electrical command. Failure is diagnostic;
        there are NO blind retries and NO electrical writes.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            if (not self.real_enabled or self.mode != "automatic" or
                    self._connect_since is None or
                    self._refresh_due is None or self._refresh_issued or
                    now < self._refresh_due or
                    self._wallbox_cable(now) is not True):
                return
            self._refresh_issued = True
            self._refresh_requested_at = now
            self._refresh_deadline = now + timedelta(seconds=120)
            selected = self._select_vehicle(now, True)
            cars = [selected] if selected is not None else self.cfg[CONF_VEHICLES]
            self._refresh_targets = tuple(c[CONF_CABLE] for c in cars)
            for car in cars:
                button = car.get(CONF_VEHICLE_REFRESH)
                if not button:
                    continue
                # Recheck the wallbox cavo immediately before each request.
                if self._wallbox_cable(datetime.now(timezone.utc)) is not True:
                    return
                try:
                    await self.hass.services.async_call(
                        "button", "press", {"entity_id": button}, blocking=True)
                except Exception as error:
                    _LOGGER.warning("RC vehicle refresh rejected (%s), no retry",
                                    type(error).__name__)
                    self._refresh_error = "vehicle_refresh_command_failed"
                    break
            # Optional one-shot read of BLE registers 158/174 to refresh an
            # old DPM0 readback. No frequent read loop or new ESPHome code.
            wallbox_button = self.cfg.get(CONF_WALLBOX_REFRESH)
            if (wallbox_button and self._wallbox_cable(datetime.now(timezone.utc)) is True):
                try:
                    await self.hass.services.async_call(
                        "button", "press",
                        {"entity_id": wallbox_button}, blocking=True)
                except Exception as error:
                    _LOGGER.warning("RC wallbox register refresh failed (%s)",
                                    type(error).__name__)
            self.refresh()

    def _house(self, now):
        values, times = [], []
        for eid in self.house_ids:
            state = self._fresh(eid, now, SHELLY_TTL)
            if state is None:
                return None, None
            value = power_kw(state.state, state.attributes.get("unit_of_measurement"))
            if value is None:
                return None, None
            values.append(value)
            times.append(self._age(state))
        return sum(values), max(times)

    def _departure(self, now, car):
        if self.departure_override is not None:
            return self.departure_override
        if self._active_departure is not None:
            return self._active_departure
        settings = self.entry.options.get("vehicle_schedules", {}).get(car[CONF_CABLE], {})
        weekday = settings.get(CONF_DEPARTURE_WEEKDAY, car[CONF_DEPARTURE_WEEKDAY])
        weekend = settings.get(CONF_DEPARTURE_WEEKEND, car[CONF_DEPARTURE_WEEKEND])
        self._active_departure = next_departure(
            now.astimezone(ZoneInfo(self.hass.config.time_zone)), weekday, weekend)
        return self._active_departure

    def _planned_start(self, now):
        """Read the validated absolute date/time saved with the session."""
        return self._scheduled_at

    def _record_planning_power(self, now, house, house_at, ev_kw, charging):
        """Keep bounded samples in RAM, without additional HA entities."""
        if house is not None and house_at is not None:
            if (not self._house_history or
                    house_at > self._house_history[-1][0] + timedelta(seconds=45)):
                self._house_history.append((house_at, house))
        if charging is True and ev_kw is not None and ev_kw >= .2:
            state = self._fresh(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
            if state:
                measured_at = self._age(state)
                if (not self._ev_history or
                        measured_at > self._ev_history[-1][0] + timedelta(seconds=45)):
                    self._ev_history.append((measured_at, ev_kw))
        cutoff = now-timedelta(minutes=21)
        for history in (self._house_history, self._ev_history):
            while history and history[0][0] < cutoff:
                history.popleft()

    def _latest_start(self, now):
        if (self.departure is None or self.remaining_kwh is None or
                self.planning_rate_kw is None):
            return None
        return self.departure-timedelta(
            minutes=30+60*self.remaining_kwh/self.planning_rate_kw)

    def _safe_start_due(self, now):
        """Explicit start time has priority over a departure estimate."""
        return (not self.delay_enabled or
                (self._scheduled_at is not None and now >= self._scheduled_at))

    def _snapshot(self, now):
        cable = self._wallbox_cable(now)
        car = self._select_vehicle(now, cable)
        enabled = self._binary(self.cfg[CONF_CHARGE_ENABLED], now)
        active = self._binary(self.cfg[CONF_DPM_ACTIVE], now)
        fault = self._binary(self.cfg[CONF_WALLBOX_FAULT], now)
        telemetry = self._binary(self.cfg[CONF_TELEMETRY_FRESH], now)
        charging_flag = self._binary(self.cfg[CONF_WALLBOX_CHARGING], now)
        ev_kw = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
        if charging_flag is True and ev_kw is not None and ev_kw >= .10:
            charging = True
        elif charging_flag is False and ev_kw is not None and ev_kw < .10:
            charging = False
        else:
            charging = None
        dpm = self._power(self.cfg[CONF_DPM_CONFIRMED], now, DPM_TTL)
        actual_limit = self._power(self.cfg[CONF_CONFIRMED_LIMIT], now)
        requested = self._power(self.cfg[CONF_REQUESTED_LIMIT], now)
        house, house_at = self._house(now)
        self._record_planning_power(now, house, house_at, ev_kw, charging)

        self.house_kw = round(house, 3) if house is not None else None
        self.quality = "ok" if (cable is True and car and telemetry is True and
                fault is False and active is True and charging is not None
                and house is not None and dpm is not None) else "incomplete"
        self.vehicle_name = car[CONF_NAME] if car else None
        self.charging_verified = charging
        self.stop_at_target_enabled = bool(car.get(CONF_STOP_AT_TARGET)) if car else None
        self.soc = self.target_soc = self.margin_minutes = self.remaining_kwh = None
        self._energy_display = None
        self._finish_display = None
        self.planning_rate_kw = estimate_ac_kw(
            now=now, dpm_kw=float(self.cfg[CONF_EXPECTED_DPM]),
            ev_base_kw=float(self.cfg[CONF_BASE_KW]),
            house_samples=self._house_history,
            charging_ev_samples=self._ev_history if charging is True else ())
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
                self.remaining_kwh = round(remaining, 2)
                self.margin_minutes = estimate_margin(
                    now=now, departure=departure,
                    remaining_kwh=remaining, rate_kw=self.planning_rate_kw)
                self._energy_display = round(remaining, 1)
                if self.planning_rate_kw is not None:
                    estimate = now + timedelta(hours=remaining/self.planning_rate_kw)
                    # 10-minute publication buckets, no per-minute countdown.
                    rounded = round(estimate.timestamp()/600)*600
                    self._finish_display = datetime.fromtimestamp(
                        rounded, timezone.utc)
                else:
                    self._finish_display = None
        # The positive configured limit is the *mathematical* DPM reference.
        # Observed zero means parked, NOT a zero power budget for the stabilizer.
        expected_dpm = float(self.cfg[CONF_EXPECTED_DPM])
        dpm_normal = dpm is not None and abs(dpm-expected_dpm) <= .11
        dpm_parked = dpm is not None and dpm <= .06 and enabled is False
        dpm_owned = self._park_owned or self._dpm_lease is not None
        conditions = (cable is True and car is not None and
                      telemetry is True and active is True and fault is False and
                      enabled is not None and
                      (dpm_normal or (dpm_parked and dpm_owned)) and
                      actual_limit is not None and requested is not None and
                      house is not None and house_at is not None and
                      target_reached is not None)
        return dict(cable=cable, car=car, charging=charging,
                    enabled=enabled, active=active, fault=fault,
                    telemetry=telemetry, house=house, house_at=house_at,
                    dpm=dpm, dpm_normal=dpm_normal, dpm_parked=dpm_parked,
                    actual=actual_limit, requested=requested,
                    trusted=conditions, target_reached=target_reached,
                    ev_kw=ev_kw)

    def _fingerprint(self):
        # Recorder: publish only status/decision transitions, never raw 1s watts.
        return (self.status, self.reason, self.notice,
                self._energy_display,
                self._finish_display.isoformat() if self._finish_display else None,
                self.charging_verified,
                self.mode, self.real_enabled,
                self.delay_enabled,
                self.vehicle_name, self.quality, self.stop_at_target_enabled, self._soc_stop_done,
                self.departure.isoformat() if self.departure else None,
                self.target_soc, self._blocked, self._pending.kind if self._pending else None,
                self._power_state.phase if self._power_state else "NORMAL",
                self._power_state.cap_kw if self._power_state else None,
                self.last_ack, self.last_command,
                "unknown" if self.margin_minutes is None else
                "urgent" if self.margin_minutes <= 60 else
                "wide" if self.margin_minutes >= 75 else "medium")

    def _notify(self):
        key = self._fingerprint()
        if key != self._last_key:
            self._last_key = key
            for listener in tuple(self._listeners):
                listener()

    def _update_notice(self, now):
        if self._user_warning:
            self.notice = self._user_warning
            return
        if self._blocked:
            self.notice = "Controllo sospeso: " + self._blocked
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
        if self._pending:
            due_dates.append(self._pending.since + ACK_TIMEOUT)
        if self._disconnect_since is not None and not connected:
            due_dates.append(self._disconnect_since + timedelta(seconds=30))
        if self._refresh_due and connected and not self._refresh_issued:
            due_dates.append(self._refresh_due)
        if self._refresh_deadline and connected:
            due_dates.append(self._refresh_deadline)
        due_dates = [dt for dt in due_dates if dt > now + timedelta(milliseconds=200)]
        if due_dates:
            self._timer_unsub = async_track_point_in_utc_time(
                self.hass, self._on_timer, min(due_dates))

    @callback
    def _on_timer(self, _time):
        self._timer_unsub = None
        self.refresh()

    @callback
    def _on_event(self, _event):
        self.refresh()

    def refresh(self):
        now = datetime.now(timezone.utc)
        if self._ble_online(now) is not True:
            # Do not interpret physical power-off as an unplug or a fault.
            # A fresh BLE ON event will trigger a new full snapshot.
            self._last_cable = None
            self._house_subscribe(False)
            self._status_acks(now, None)
            self.status, self.reason = ("Wallbox non disponibile",
                                        "ble_offline_normal")
            self.notice = "Wallbox spenta o BLE non collegato"
            self.charging_verified = None
            self._finish_display = None
            self._energy_display = None
            self.vehicle_name = None
            self.quality = "offline"
            self._reschedule(now, False)
            self._notify()
            return
        snapshot = self._snapshot(now)
        cable = snapshot["cable"]
        # Only a true ON->OFF transition may arm one delayed parked command.
        # Do not interpret startup OFF or a transient unavailable state as
        # an unplug event.
        if cable is not None and cable != self._last_cable:
            if cable is True:
                self._connect_since = now
                self._disconnect_since = None
                self._ev_idle_since = None
                self._park_attempted = False
                self._refresh_due = now + timedelta(seconds=20)
                self._refresh_issued = False
                self._refresh_requested_at = None
                self._refresh_deadline = None
                self._refresh_targets = ()
                self._refresh_error = None
                self._wallbox_refresh_sent = False
                self._start_refresh_attempted = False
                self._start_refresh_at = None
                self._soc_stop_done = False
                self._soc_stop_refresh_at = None
                self._soc_stop_baseline = None
                self._soc_stop_last_error = None
            elif self._last_cable is True:
                self._disconnect_since = now
                self._ev_idle_since = (now if snapshot["ev_kw"] is not None
                                      and snapshot["ev_kw"] < .03 else None)
                self._park_attempted = False
                self._refresh_due = None
                self._refresh_deadline = None
            self._last_cable = cable
        self._status_acks(now, cable)
        # The user-facing delayed-start switch is a ONE-SHOT request:
        # clear only after the scheduled time AND confirmed charging,
        # or when the cable is unplugged (handled above).
        if (self.delay_enabled and self._scheduled_at is not None
                and now >= self._scheduled_at and
                snapshot["charging"] is True and self._pending is None
                and self._dpm_lease is None):
            self.delay_enabled = False
            self._scheduled_at = None
            self._delay_pause_attempted = False
            self._schedule_save()
        if cable is False and self._disconnect_since is not None:
            if snapshot["ev_kw"] is not None and snapshot["ev_kw"] < .03:
                if self._ev_idle_since is None:
                    self._ev_idle_since = now
            else:
                self._ev_idle_since = None
        self._house_subscribe(cable is True)
        if cable is False:
            # Session-only departure never carries over to another car,
            # even when HA restarted with the cable already unplugged.
            if self.departure_override is not None:
                self.departure_override = None
                self._active_departure = None
                self._schedule_save()
            # Reset Manual to AUTO at confirmed unplug, but a session's
            # physical actuation lease is never reconstituted from guesses.
            if self._connection:
                changed = (self.mode == "manual" or self.delay_enabled or
                           self.departure_override is not None)
                self.mode = "automatic"
                self.delay_enabled = False
                self._scheduled_at = None
                self._delay_pause_attempted = False
                self.departure_override = None
                if changed:
                    self._schedule_save()
            self._session_id = None
            self._connection = False
            self._power_state = None
            self._owned_limit = None
            self._dpm_lease = None
            self._saved_delay_lease = None
            self._active_departure = None
            self._scheduled_at = None
            self._prepared_session = None
            self.charge_now = False
            self.explicit_pause = False
            # Keep pending park until verified or timed out; otherwise it
            # would disappear before ESPHome responded with DPM=0.
            if self._pending and self._pending.kind != "park":
                self._blocked = "session_ended_with_pending_command"
                self._pending = None
                self.real_enabled = False
            if snapshot["dpm"] is not None and snapshot["dpm"] <= .06:
                self.status = "Scollegata — DPM 0 A"
                self.reason = ("park_confirmed" if self._park_owned
                               else "dpm_zero_no_proven_owner")
            elif self._disconnect_since is not None:
                self.status = "Scollegata — attesa 30 W / 30 s"
                self.reason = "disconnect_debounce_before_park"
            else:
                self.status = "Scollegata"
                self.reason = "no_cable_transition_to_park"
            if self._blocked and self._blocked.startswith("unconfirmed_"):
                self.status, self.reason = "Bloccata", self._blocked
        elif cable is None or snapshot["car"] is None:
            self.status = "Da riconciliare"
            self.reason = "cable_or_vehicle_ambiguous"
        else:
            identity = snapshot["car"][CONF_CABLE]
            if not self._connection or self._session_id is None or identity != self._connection:
                self._seq += 1
                self._session_id = f"{self.entry.entry_id}:{self._seq}:{identity}"
                self._connection = identity
                self._power_state = State(session_id=self._session_id,
                                          cap_kw=float(self.cfg[CONF_BASE_KW]),
                                          baseline_kw=float(self.cfg[CONF_BASE_KW]))
                self._owned_limit = None
                self._dpm_lease = None
                if self._pending and self._pending.kind == "park":
                    self.real_enabled = False
                    self._blocked = "park_command_interrupted_by_reconnection"
                self._pending = None
                self._active_departure = None
                if not self.delay_enabled:
                    self._scheduled_at = None
                self._delay_pause_attempted = False
                self._prepared_session = None
                self._soc_stop_done = False
                self.charge_now = False
            # On boot, a previously ACKed delayed pause may be recovered
            # only from live matching BLE/Shelly facts.
            self._recover_verified_delay_lease(snapshot)
            # A persisted lease for another vehicle or another delay cannot
            # legitimize the observed 0 A. Fail closed, never adopt it.
            if (self._saved_delay_lease is not None and
                    self._dpm_lease is None and
                    snapshot["dpm_parked"] is True and
                    (self._saved_delay_lease.get("vehicle") != identity or
                     not self.delay_enabled or self._scheduled_at is None or
                     self._saved_delay_lease.get("start") !=
                         self._scheduled_at.isoformat())):
                self._blocked = "saved_delay_lease_mismatch"
                self.real_enabled = False
            if (self._pending is None and
                    snapshot["dpm"] is not None and
                    snapshot["dpm"] <= .06 and
                    self._dpm_lease is None and not self._park_owned and
                    self._saved_delay_lease is None and
                    self._blocked in (None, "startup_requires_explicit_reenable")):
                # Never inherit an ESPHome/user DPM=0 as our own pause.
                self._blocked = "dpm_zero_without_proven_rc_lease"
                self.real_enabled = False
            if self.mode == "manual" or self.explicit_pause:
                self.status = "Manuale" if self.mode == "manual" else "Pausa gestione"
                self.reason = "user_owns_wallbox"
            elif self._blocked:
                self.status, self.reason = "Bloccata", self._blocked
            elif self._soc_stop_done:
                self.status = "Carica terminata — limite SOC raggiunto"
                self.reason = "soc_target_stop_verified"
            elif snapshot["target_reached"] is True and snapshot["charging"] is not True:
                cap = self._power_state.cap_kw if self._power_state else None
                base = float(self.cfg[CONF_BASE_KW])
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
                      self._planned_start(now) > now):
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
        if (self.real_enabled and cable is True and
                self.mode == "automatic" and
                self._refresh_due is not None and
                now >= self._refresh_due and not self._refresh_issued):
            if self._refresh_task is None or self._refresh_task.done():
                self._refresh_task = self.entry.async_create_background_task(
                    self.hass, self._request_one_shot_updates(),
                    "EasyWallbox RC vehicle data refresh")
        self._notify()
        if (self.real_enabled and cable is False and
                self._disconnect_since is not None and
                self._ev_idle_since is not None and
                not self._park_attempted and not self._park_owned and
                self._pending is None and not self._blocked and
                now-self._disconnect_since >= timedelta(seconds=30) and
                now-self._ev_idle_since >= timedelta(seconds=30)):
            if self._task is None or self._task.done():
                self._task = self.entry.async_create_background_task(
                    self.hass, self._park_after_unplug(), "EasyWallbox RC park")
        if (self.real_enabled and cable is True and self.mode == "automatic"
                and not self._blocked and self._pending is None):
            if self._task is None or self._task.done():
                self._task = self.entry.async_create_background_task(
                    self.hass, self._actuate(snapshot, now), "EasyWallbox RC evaluate",
                )

    async def _park_after_unplug(self):
        """One verified OFF transition only. This is the sole unplugged write."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            if (not self.real_enabled or self._park_attempted or
                    not self.cfg.get(CONF_LEGACY_DISABLED, False) or
                    self._pending is not None or self._blocked or
                    self._disconnect_since is None or self._ev_idle_since is None or
                    now-self._disconnect_since < timedelta(seconds=30) or
                    now-self._ev_idle_since < timedelta(seconds=30)):
                return
            # Never trust a cached "zero watt" or an uncertain cable state.
            if (self._wallbox_cable(now) is not False or
                    self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL) is None or
                    self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL) >= .03 or
                    self._binary(self.cfg[CONF_TELEMETRY_FRESH], now) is not True or
                    self._binary(self.cfg[CONF_DPM_ACTIVE], now) is not True or
                    self._binary(self.cfg[CONF_WALLBOX_FAULT], now) is not False or
                    self._binary(self.cfg[CONF_CHARGE_ENABLED], now) is not True):
                return
            dpm = self._power(self.cfg[CONF_DPM_CONFIRMED], now, DPM_TTL)
            if dpm is None or abs(dpm-float(self.cfg[CONF_EXPECTED_DPM])) > .11:
                self.status, self.reason = ("Da riconciliare",
                                            "dpm_not_expected_before_park")
                self._notify()
                return
            self._park_attempted = True
            await self._send("park", dpm, None)

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
                or current["charging"] is not True or self._soc_stop_done):
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
            try:
                await self.hass.services.async_call(
                    "button", "press", {"entity_id": button}, blocking=True)
            except Exception as error:
                _LOGGER.warning("SOC refresh failed (%s), never retry blindly",
                                type(error).__name__)
                self._blocked = "soc_refresh_failed_no_retry"
                self.real_enabled = False
                self.status, self.reason = "Bloccata", self._blocked
                self._notify()
            return True
        if not self._soc_stop_fresh(car, now):
            self.status, self.reason = ("In carica — verifica SOC",
                                       "waiting_recent_soc_for_stop")
            self._notify()
            return True if soc >= target else False
        if soc >= target:
            if (current["dpm_normal"] is not True or
                    current["enabled"] is not True):
                self.status, self.reason = ("Da riconciliare",
                                            "soc_target_dpm_not_normal")
                self._notify()
                return True
            await self._send("soc_stop", 0.0, None)
            return True
        return False

    async def _actuate(self, snap, now):
        async with self._lock:
            # Recheck immediately before dispatch; an old callback is not
            # permission to command a car which may already be unplugged.
            current = self._snapshot(datetime.now(timezone.utc))
            if (self.mode != "automatic" or not self.real_enabled
                    or self.explicit_pause or self._pending is not None
                    or self._blocked or current["cable"] is not True
                    or current["car"] is None or current["charging"] is None
                    or not self.cfg.get(CONF_LEGACY_DISABLED, False)):
                return
            if (current["dpm"] is None and
                    (self._park_owned or self._dpm_lease is not None) and
                    current["charging"] is False and
                    self._car_update_ready(datetime.now(timezone.utc), current["car"])):
                # A readback from the initial plug-in would be stale after
                # a multi-hour scheduled wait. One additional BLE register
                # read is justified precisely when starting is due.
                now_ready = datetime.now(timezone.utc)
                if self._safe_start_due(now_ready):
                    if not self._start_refresh_attempted:
                        self._start_refresh_attempted = True
                        self._start_refresh_at = now_ready
                        try:
                            await self.hass.services.async_call(
                                "button", "press",
                                {"entity_id": self.cfg[CONF_WALLBOX_REFRESH]},
                                blocking=True)
                        except Exception as error:
                            _LOGGER.warning("One-shot DPM refresh failed: %s",
                                            type(error).__name__)
                            self._blocked = "dpm_refresh_service_failed"
                        self.refresh()
                    elif (self._start_refresh_at is not None and
                            now_ready-self._start_refresh_at >= ACK_TIMEOUT):
                        self._blocked = "dpm_refresh_no_new_readback"
                        self.status, self.reason = "Bloccata", self._blocked
                        self._notify()
                return
            if current["trusted"] is not True:
                return
            if not self._car_update_ready(datetime.now(timezone.utc), current["car"]):
                return
            if self._soc_stop_done:
                return
            if current["target_reached"] is True and current["charging"] is not True:
                # The car already stopped. Latest user rule explicitly
                # forbids changing the EV number while not charging.
                return
            if (current["dpm"] is None or current["dpm"] < 0
                    or current["actual"] is None or current["requested"] is None
                    or abs(current["actual"]-current["requested"]) > .11):
                return

            # A charge in progress may ONLY change the EV limit, NEVER
            # operate the Start/Stop switch, including for a delayed start.
            if current["charging"] is True:
                # Explicit user command, not a planner-generated pause.
                # This is a separate exception from opt-in SOC stop.
                if (self.delay_enabled and self._scheduled_at is not None
                        and datetime.now(timezone.utc) < self._scheduled_at):
                    if self._dpm_lease is None and not self._delay_pause_attempted:
                        self._delay_pause_attempted = True
                        await self._send("delay_pause", current["dpm"], None)
                    return
                if self._dpm_lease is not None:
                    self._blocked = "unexpected_charge_during_owned_pause"
                    self.status, self.reason = "Bloccata", self._blocked
                    self._notify()
                    return
                if self._owned_limit is not None and abs(current["actual"]-self._owned_limit) > .11:
                    self._blocked = "external_ev_limit_change"
                    self.status, self.reason = "Bloccata", self._blocked
                    self._notify()
                    return
                if await self._maybe_stop_at_soc(
                        current, datetime.now(timezone.utc)):
                    return
                base = float(self.cfg[CONF_BASE_KW])
                if current["target_reached"] is True:
                    # Restore ONLY an optional cap genuinely owned by this
                    # session and only while Charging is still confirmed.
                    if (self._owned_limit is not None
                            and self._power_state is not None
                            and self._power_state.phase in ("LIMITED", "BOOST")
                            and abs(self._owned_limit-current["actual"]) <= .11
                            and abs(base-current["actual"]) >= .11):
                        await self._send("power", base, State(
                            session_id=self._session_id, cap_kw=base,
                            baseline_kw=base))
                    return
                if self._power_state is None:
                    self._power_state = State(session_id=self._session_id, cap_kw=base, baseline_kw=base)
                # Initial real-mode activation assumes responsibility only
                # after the user enabled it and all configured checks pass.
                if self._owned_limit is None:
                    self._owned_limit = current["actual"]
                    if abs(current["actual"]-base) > .11:
                        await self._send("power", base, None)
                        return
                o = Observation(
                    at=datetime.now(timezone.utc), session_id=self._session_id,
                    connected=True, charging=True, auto=True, trusted=current["trusted"],
                    house_kw=current["house"], house_at=current["house_at"],
                    dpm_kw=float(self.cfg[CONF_EXPECTED_DPM]), current_kw=current["actual"],
                    margin_minutes=self.margin_minutes,
                    remaining_budget_kwh=(
                        max(0.0, (self.margin_minutes-45)/60 *
                            self.planning_rate_kw * .25)
                        if self.margin_minutes is not None and
                           self.margin_minutes > 45 and
                           self.planning_rate_kw is not None else 0.0),
                    max_kw=base, boost_max_kw=float(self.cfg[CONF_BOOST_KW]),
                )
                state, decision = evaluate(o, self._power_state)
                if decision.action == "set_limit" and decision.target_kw is not None:
                    # Recompute from the exact fresh source immediately prior
                    # to a write. No boost with stale or unknown SOC.
                    if abs(decision.target_kw-current["actual"]) >= .11:
                        await self._send("power", decision.target_kw, state)
                else:
                    self._power_state = state
                return

            # Connected but confirmed NOT charging: the normal parked-DPM
            # lifecycle can start only after vehicle update and planning.
            if (current["ev_kw"] is None or current["ev_kw"] >= .03 or
                    current["target_reached"] is not False):
                return
            if not (current["dpm_parked"] and
                    (self._park_owned or self._dpm_lease is not None)):
                return

            if not self._car_update_ready(datetime.now(timezone.utc), current["car"]):
                return
            now_decision = datetime.now(timezone.utc)
            if not self._safe_start_due(now_decision):
                self.status, self.reason = "In attesa", "delayed_start_ready"
                self._notify()
                return

            base = float(self.cfg[CONF_BASE_KW])
            if self._prepared_session != self._session_id:
                if (abs(current["actual"]-base) <= .11 and
                        abs(current["requested"]-base) <= .11):
                    self._prepared_session = self._session_id
                else:
                    await self._send("prepare", base, None)
                    return
            if self._prepared_session == self._session_id:
                await self._send("resume", float(self.cfg[CONF_EXPECTED_DPM]), None)

    async def _send(self, kind: str, target: float, next_state: State | None):
        """One command, never retry, with separately timed BLE verification."""
        if self._pending is not None or not self.real_enabled:
            return
        # Double-check one last time before every irreversible request.
        now = datetime.now(timezone.utc)
        cable = self._wallbox_cable(now)
        if (self._ble_online(now) is not True or
                self._binary(self.cfg[CONF_TELEMETRY_FRESH], now) is not True or
                self._binary(self.cfg[CONF_DPM_ACTIVE], now) is not True or
                self._binary(self.cfg[CONF_WALLBOX_FAULT], now) is not False):
            return
        observed_charging = self._binary(self.cfg[CONF_WALLBOX_CHARGING], now)
        ev_kw = self._power(self.cfg[CONF_EV_POWER], now, SHELLY_TTL)
        if kind == "park":
            if (cable is not False or self._disconnect_since is None or
                    self._ev_idle_since is None or
                    now-self._disconnect_since < timedelta(seconds=30) or
                    now-self._ev_idle_since < timedelta(seconds=30) or
                    ev_kw is None or ev_kw >= .03 or
                    self._binary(self.cfg[CONF_CHARGE_ENABLED], now) is not True):
                return
        else:
            car = self._select_vehicle(now, True)
            if cable is not True or car is None:
                return
            if kind == "delay_pause":
                if (not self.delay_enabled or self._scheduled_at is None or
                        now >= self._scheduled_at or
                        self.mode != "automatic" or
                        observed_charging is not True or ev_kw is None or
                        ev_kw < .10 or
                        self._binary(self.cfg[CONF_CHARGE_ENABLED], now) is not True):
                    return
                dpm = self._power(self.cfg[CONF_DPM_CONFIRMED], now, DPM_TTL)
                if dpm is None or abs(dpm-float(self.cfg[CONF_EXPECTED_DPM])) > .11:
                    return
            if kind == "soc_stop":
                if (not car.get(CONF_STOP_AT_TARGET, False) or
                        self._soc_stop_done or
                        self.mode != "automatic" or self.explicit_pause or
                        not self.cfg.get(CONF_LEGACY_DISABLED, False) or
                        observed_charging is not True or
                        ev_kw is None or ev_kw < .10 or
                        self._binary(self.cfg[CONF_CHARGE_ENABLED], now) is not True or
                        not self._soc_stop_fresh(car, now) or
                        self._number(car[CONF_SOC], now, SOC_STOP_TTL) is None):
                    return
                fresh_soc = self._number(car[CONF_SOC], now, SOC_STOP_TTL)
                target = (self._number(car.get(CONF_TARGET_ENTITY), now, None)
                          if car.get(CONF_TARGET_ENTITY) else self.fixed_target(car))
                if target is None or fresh_soc < target:
                    return
                live_dpm = self._power(self.cfg[CONF_DPM_CONFIRMED], now, DPM_TTL)
                if live_dpm is None or abs(live_dpm-float(self.cfg[CONF_EXPECTED_DPM])) > .11:
                    return
            if (kind == "power" and observed_charging is not True) or (
                    kind in ("pause", "resume", "prepare") and
                    (observed_charging is not False or ev_kw is None or ev_kw >= .03)):
                return
            if kind == "prepare" and not (self._park_owned or self._dpm_lease):
                return
            if kind == "resume" and not (self._park_owned or self._dpm_lease):
                return
        self._pending = Pending(kind, target, now, next_state)
        self.last_command = f"{kind}:{target:.1f}"
        self.reason = f"requested_{kind}_not_yet_confirmed"
        self._notify()
        try:
            if kind in ("power", "prepare"):
                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self.cfg[CONF_REQUESTED_LIMIT], "value": target},
                    blocking=True,
                )
            elif kind in ("pause", "park", "soc_stop", "delay_pause"):
                await self.hass.services.async_call(
                    "switch", "turn_off",
                    {"entity_id": self.cfg[CONF_START_STOP]}, blocking=True,
                )
            else:
                await self.hass.services.async_call(
                    "switch", "turn_on",
                    {"entity_id": self.cfg[CONF_START_STOP]}, blocking=True,
                )
        except Exception as error:
            _LOGGER.warning("Wallbox RC command %s failed (%s); no automatic retry",
                            kind, type(error).__name__)
            self._blocked = "service_error_" + kind
            self._pending = None
            self.real_enabled = False
        self.refresh()

    def add_listener(self, cb):
        self._listeners.add(cb)
        return lambda: self._listeners.discard(cb)

    async def async_change(self, field, value):
        if field == "mode" and value in ("automatic", "manual"):
            self.mode = value
            # Manual overrides automatic action for the ENTIRE session.
            # Preserve consent to park after a confirmed unplug, at which
            # point the session returns to AUTO.
            if value == "manual":
                self.reason = "manual_session_no_wallbox_commands"
        elif field == "real":
            if not value:
                self.real_enabled = False
                self._blocked = None
            elif (self.mode == "automatic"
                  and self.cfg.get(CONF_LEGACY_DISABLED, False)
                  and self._binary(self.cfg[CONF_WALLBOX_CONNECTED],
                                   datetime.now(timezone.utc)) is not None
                  and self._binary(self.cfg[CONF_TELEMETRY_FRESH],
                                   datetime.now(timezone.utc)) is True
                  and self._binary(self.cfg[CONF_DPM_ACTIVE],
                                   datetime.now(timezone.utc)) is True):
                # It is valid to arm AUTO with the cable unplugged; only a
                # subsequent real ON->OFF event may send the park command.
                self.real_enabled = True
                self._blocked = None
            else:
                raise ValueError("Enable only in AUTO with valid BLE and no competing automations")
        elif field == "delay":
            if value and self.delay_enabled:
                self.refresh()
                return
            if value:
                try:
                    candidate = validate_delay(
                        datetime.now(timezone.utc), self.preferred_start,
                        self.hass.config.time_zone)
                except ValueError:
                    self._user_warning = (
                        "Posticipo rifiutato: seleziona un orario futuro "
                        "non oltre 12 ore. Nessuna pausa inviata.")
                    self.refresh()
                    raise
                self._user_warning = None
                if not self.delay_enabled:
                    self._scheduled_at = candidate
                    self._delay_pause_attempted = False
                self.delay_enabled = True
            else:
                self._user_warning = None
                self.delay_enabled = False
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
            raise ValueError("invalid RC control")
        if field in ("mode", "delay", "time", "departure", "ready_by"):
            await self._save()
        self.refresh()

    def start(self):
        keys = (
            CONF_EV_POWER, CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING,
            CONF_TELEMETRY_FRESH, CONF_DPM_ACTIVE, CONF_WALLBOX_FAULT,
            CONF_CHARGE_ENABLED, CONF_START_STOP, CONF_COMMAND_STATUS,
            CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT, CONF_DPM_CONFIRMED,
        )
        ids = [self.cfg[k] for k in keys]
        if self.cfg.get(CONF_BLE_CONNECTED):
            ids.append(self.cfg[CONF_BLE_CONNECTED])
        for vehicle in self.cfg[CONF_VEHICLES]:
            ids.extend((vehicle[CONF_CABLE], vehicle[CONF_SOC]))
            if vehicle.get(CONF_TARGET_ENTITY):
                ids.append(vehicle[CONF_TARGET_ENTITY])
            if vehicle.get(CONF_VEHICLE_LAST_UPDATE):
                ids.append(vehicle[CONF_VEHICLE_LAST_UPDATE])
        self._sensor_unsub = async_track_state_change_event(
            self.hass, sorted(set(ids)), self._on_event)
        self.refresh()

    async def async_close(self):
        if self._timer_unsub:
            self._timer_unsub()
            self._timer_unsub = None
        if self._sensor_unsub:
            self._sensor_unsub()
            self._sensor_unsub = None
        self._house_subscribe(False)
        self.real_enabled = False
        if self._task:
            await self._task
        if self._refresh_task:
            await self._refresh_task
        self._listeners.clear()
