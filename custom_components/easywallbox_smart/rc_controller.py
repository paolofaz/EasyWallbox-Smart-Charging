"""Home Assistant RC adapter: one owner, event-driven, fail-closed actuation.

Hardware writes are intentionally opt-in (never enabled on boot/reload).
No action without positive and unique cable confirmation; no rapid DPM control.
A Home Assistant service success is not a BLE acknowledgement.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import *
from .sources import finite_number, on, power_kw, next_departure
from .rc_policy import Observation, State, evaluate

_LOGGER = logging.getLogger(__name__)
WALLBOX_TTL = timedelta(minutes=2)
DPM_TTL = timedelta(minutes=5)
SHELLY_TTL = timedelta(minutes=3)
CAR_TTL = timedelta(minutes=30)
ACK_TIMEOUT = timedelta(minutes=3)


@dataclass
class Pending:
    kind: str
    target: float
    since: datetime
    next_state: State | None = None


def _append_lab(root: str, row: dict) -> None:
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    filename = path / ("rc_shadow_" + row["at"][:10] + ".jsonl")
    if filename.exists() and filename.stat().st_size > 2_000_000:
        return
    with filename.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")


class RCController:
    """Single local controller with no blind retry and no retained action lease."""

    def __init__(self, hass: HomeAssistant, entry):
        self.hass, self.entry = hass, entry
        self.cfg = {**entry.data, **entry.options}
        self.house_ids = tuple(self.cfg[CONF_HOUSE_SOURCES])
        self.mode = "automatic"
        self.real_enabled = False        # NEVER persist automatic authorization
        self.delay_enabled = False
        self.preferred_start = time(23, 0)
        self.departure_override = None
        self.lab_enabled = False
        self.charge_now = False
        self.explicit_pause = False
        self.status = "Pronto, controllo reale disabilitato"
        self.reason = "manual_enable_required_after_startup"
        self.quality = "unknown"
        self.vehicle_name = None
        self.departure = None
        self.soc = None
        self.target_soc = None
        self.margin_minutes = None
        self.remaining_kwh = None
        self.house_kw = None
        self.last_command = None
        self.last_ack = None
        self._connection = False
        self._session_id = None
        self._seq = 0
        self._power_state: State | None = None
        self._owned_limit: float | None = None
        self._dpm_lease: float | None = None
        self._pending: Pending | None = None
        self._blocked = None
        self._last_key = None
        self._listeners = set()
        self._sensor_unsub = None
        self._house_unsub = None
        self._timer_unsub = None
        self._task = None
        self._lock = asyncio.Lock()
        self._store = Store(hass, 1, "easywallbox_smart_rc_" + entry.entry_id)
        self._lab_state = None
        self._lab_last_at = None
        self._lab_virtual_cap = float(self.cfg[CONF_BASE_KW])
        self._lab_write_task = None
        self._lab_buffer = []

    async def async_load(self):
        saved = await self._store.async_load() or {}
        self.mode = saved.get("mode") if saved.get("mode") in ("automatic", "manual") else "automatic"
        self.delay_enabled = bool(saved.get("delay", False))
        self.lab_enabled = bool(saved.get("lab", False))
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
        # Never resurrect permission or an electrical lease across a restart.
        self.real_enabled = False
        self._owned_limit = self._dpm_lease = self._pending = None
        self._blocked = "startup_requires_explicit_reenable"

    async def _save(self):
        await self._store.async_save({
            "mode": self.mode, "delay": self.delay_enabled,
            "lab": self.lab_enabled,
            "start": self.preferred_start.isoformat(timespec="minutes"),
            "departure": self.departure_override.isoformat()
            if self.departure_override else None,
        })

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

    def _power(self, entity, now, ttl=WALLBOX_TTL):
        state = self._fresh(entity, now, ttl)
        return (power_kw(state.state, state.attributes.get("unit_of_measurement"))
                if state else None)

    def _number(self, entity, now, ttl=CAR_TTL):
        s = self._fresh(entity, now, ttl)
        return finite_number(s.state) if s else None

    def _status_acks(self, now, cable):
        p = self._pending
        if p is None:
            return
        if cable is not True:
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
        if p.kind == "power":
            requested = self._power(self.cfg[CONF_REQUESTED_LIMIT], now)
            valid = (flag == "Verified charge power" and confirmed_ev is not None
                     and requested is not None and abs(confirmed_ev-p.target) <= .11
                     and abs(requested-p.target) <= .11)
        elif p.kind == "pause":
            valid = (flag == "Verified DPM" and confirmed_dpm is not None
                     and confirmed_dpm <= .06 and charge_enabled is False)
        elif p.kind == "resume":
            valid = (flag == "Verified DPM" and confirmed_dpm is not None
                     and abs(confirmed_dpm-p.target) <= .11 and charge_enabled is True)
        if valid:
            if p.kind == "power":
                self._owned_limit = p.target
                if p.next_state is not None:
                    self._power_state = p.next_state
            elif p.kind == "pause":
                self._dpm_lease = p.target  # remembers ORIGINAL positive DPM
            elif p.kind == "resume":
                self._dpm_lease = None
            self.last_ack = now.isoformat(timespec="seconds")
            self._pending = None
            self.reason = "confirmed_" + p.kind
            return
        if now-p.since >= ACK_TIMEOUT:
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
        if (self.departure_override is not None and
                self.departure_override > now):
            return self.departure_override
        settings = self.entry.options.get("vehicle_schedules", {}).get(car[CONF_CABLE], {})
        weekday = settings.get(CONF_DEPARTURE_WEEKDAY, car[CONF_DEPARTURE_WEEKDAY])
        weekend = settings.get(CONF_DEPARTURE_WEEKEND, car[CONF_DEPARTURE_WEEKEND])
        return next_departure(now.astimezone(ZoneInfo(self.hass.config.time_zone)),
                              weekday, weekend)

    def _planned_start(self, now):
        local = now.astimezone(ZoneInfo(self.hass.config.time_zone))
        scheduled = datetime.combine(local.date(), self.preferred_start,
                                     tzinfo=local.tzinfo)
        if scheduled <= local:
            return local  # Time passed today; NEVER defer to tomorrow automatically.
        return scheduled

    def _snapshot(self, now):
        cable = self._binary(self.cfg[CONF_WALLBOX_CONNECTED], now)
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
        house, house_at = self._house(now) if (cable is True or self.lab_enabled) else (None, None)

        self.house_kw = round(house, 3) if house is not None else None
        self.quality = "ok" if (cable is True and car and telemetry is True and
                fault is False and active is True and charging is not None
                and house is not None and dpm is not None) else "incomplete"
        self.vehicle_name = car[CONF_NAME] if car else None
        self.soc = self.target_soc = self.margin_minutes = self.remaining_kwh = None
        self.departure = None
        target_reached = None
        if car:
            soc = self._number(car[CONF_SOC], now, CAR_TTL)
            target = (self._number(car.get(CONF_TARGET_ENTITY), now, CAR_TTL)
                      if car.get(CONF_TARGET_ENTITY) else car.get(CONF_TARGET_FIXED))
            self.soc, self.target_soc = soc, target
            departure = self._departure(now, car)
            self.departure = departure
            if (soc is not None and target is not None
                    and 0 <= soc <= 100 and 1 <= target <= 100):
                target_reached = soc >= target
                remaining = max(0, target-soc) / 100 * float(car[CONF_CAPACITY]) / float(car[CONF_EFFICIENCY])
                self.remaining_kwh = round(remaining, 2)
                # User-configured conservative planning rate, NOT inferred
                # from the instantaneous DPM-limited vehicle power.
                rate = float(car.get("planning_rate_kw", 2.4))
                if departure and rate >= 1.4:
                    duration_minutes = remaining / rate * 60
                    self.margin_minutes = ((departure-now).total_seconds()/60
                                           - 30 - duration_minutes)
        conditions = (cable is True and car is not None and
                      telemetry is True and active is True and fault is False and
                      enabled is not None and dpm is not None
                      and actual_limit is not None and requested is not None
                      and abs(float(self.cfg[CONF_EXPECTED_DPM])-
                              (self._dpm_lease if dpm <= .06 and self._dpm_lease is not None
                               else dpm)) <= .11 and
                      target_reached is not None and self.margin_minutes is not None)
        return dict(cable=cable, car=car, charging=charging,
                    enabled=enabled, active=active, fault=fault,
                    telemetry=telemetry, house=house, house_at=house_at,
                    dpm=dpm, actual=actual_limit, requested=requested,
                    trusted=conditions, target_reached=target_reached,
                    ev_kw=ev_kw)

    def _fingerprint(self):
        # Recorder: publish only status/decision transitions, never raw 1s watts.
        return (self.status, self.reason, self.mode, self.real_enabled,
                self.delay_enabled, self.lab_enabled,
                self.vehicle_name, self.quality,
                self.departure.isoformat() if self.departure else None,
                self.target_soc, self._blocked, self._pending.kind if self._pending else None,
                self._power_state.phase if self._power_state else "NORMAL",
                self._power_state.cap_kw if self._power_state else None,
                self.last_ack, self.last_command)

    def _notify(self):
        key = self._fingerprint()
        if key != self._last_key:
            self._last_key = key
            for listener in tuple(self._listeners):
                listener()

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
        if connected:
            # Slow one-minute tick for schedule/timeout, never BLE polling.
            due = now + timedelta(minutes=1)
            self._timer_unsub = async_track_point_in_utc_time(
                self.hass, self._on_timer, due)

    @callback
    def _on_timer(self, _time):
        self._timer_unsub = None
        self.refresh()

    @callback
    def _on_event(self, _event):
        self.refresh()

    def refresh(self):
        now = datetime.now(timezone.utc)
        snapshot = self._snapshot(now)
        cable = snapshot["cable"]
        self._house_subscribe(cable is True or self.lab_enabled)
        if cable is False:
            self._session_id = None
            self._connection = False
            self._power_state = None
            self._owned_limit = None
            self._dpm_lease = None
            self._pending = None
            self.charge_now = False
            self.explicit_pause = False
            self._blocked = None
            self.status = "Scollegata"
            self.reason = "cable_disconnected_no_commands"
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
                                          cap_kw=float(self.cfg[CONF_BASE_KW]))
                self._owned_limit = None
                self._dpm_lease = None
                self._pending = None
                self.charge_now = False
            self._status_acks(now, True)
            if self._blocked:
                self.status, self.reason = "Bloccata", self._blocked
            elif self.mode == "manual" or self.explicit_pause:
                self.status, self.reason = "Manuale", "user_owns_wallbox"
            elif snapshot["target_reached"] is True:
                self.status, self.reason = "Completata", "soc_target_reached"
            elif snapshot["charging"] is True:
                self.status = "In carica"
                self.reason = "normal_or_limited"
            elif snapshot["charging"] is False:
                self.status = "Collegata, non in carica"
                self.reason = "waiting_or_stopped"
            else:
                self.status, self.reason = "Da riconciliare", "charging_unverified"
        self._reschedule(now, cable is True)
        self._lab(now, snapshot)
        self._notify()
        if (self.real_enabled and cable is True and self.mode == "automatic"
                and not self._blocked and self._pending is None):
            if self._task is None or self._task.done():
                self._task = self.entry.async_create_background_task(
                    self.hass, self._actuate(snapshot, now), "EasyWallbox RC evaluate",
                )

    async def _actuate(self, snap, now):
        async with self._lock:
            # Recheck immediately before dispatch; an old callback is not
            # permission to command a car which may already be unplugged.
            current = self._snapshot(datetime.now(timezone.utc))
            if (self.mode != "automatic" or not self.real_enabled
                    or self.explicit_pause or self._pending is not None
                    or self._blocked or current["cable"] is not True
                    or current["car"] is None or current["charging"] is None
                    or current["trusted"] is not True
                    or not self.cfg.get(CONF_LEGACY_DISABLED, False)):
                return
            if current["target_reached"] is True:
                return
            if (current["dpm"] is None or current["dpm"] < 0
                    or current["actual"] is None or current["requested"] is None
                    or abs(current["actual"]-current["requested"]) > .11):
                return

            # A charge in progress may ONLY change the EV limit, NEVER
            # operate the Start/Stop switch, including for a delayed start.
            if current["charging"] is True:
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
                base = float(self.cfg[CONF_BASE_KW])
                if self._power_state is None:
                    self._power_state = State(session_id=self._session_id, cap_kw=base)
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
                    dpm_kw=current["dpm"], current_kw=current["actual"],
                    margin_minutes=self.margin_minutes,
                    remaining_budget_kwh=(
                        max(0.0, self.margin_minutes/60 * 2.4 * .25)
                        if self.margin_minutes is not None and self.margin_minutes > 45
                        else 0.0),
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

            # Only a disconnected *charging state* (cable still ON) may
            # request Start/Stop, and exclusively for scheduled waiting.
            if not self.delay_enabled:
                return
            if (current["ev_kw"] is None or current["ev_kw"] >= .10
                    or self.margin_minutes is None):
                return
            start = self._planned_start(datetime.now(timezone.utc))
            # Waiting is advisory; never deliberately miss a departure.
            latest = self.departure - timedelta(
                minutes=30 + (self.remaining_kwh / max(
                    1.4, float(current["car"].get("planning_rate_kw", 2.4)))) * 60
            ) if self.departure is not None and self.remaining_kwh is not None else None
            should_wait = (not self.charge_now and latest is not None and
                           latest > datetime.now(timezone.utc) and
                           start > datetime.now(timezone.utc))
            if should_wait:
                if (self._dpm_lease is None and current["dpm"] > 1.4
                        and current["enabled"] is True):
                    await self._send("pause", current["dpm"], None)
                return
            if (self._dpm_lease is not None and current["dpm"] <= .06
                    and current["enabled"] is False):
                await self._send("resume", self._dpm_lease, None)

    async def _send(self, kind: str, target: float, next_state: State | None):
        """One command, never retry, with separately timed BLE verification."""
        if self._pending is not None or not self.real_enabled:
            return
        # Double-check one last time before every irreversible request.
        now = datetime.now(timezone.utc)
        if (self._binary(self.cfg[CONF_WALLBOX_CONNECTED], now) is not True
                or self._select_vehicle(now, True) is None
                or self._binary(self.cfg[CONF_TELEMETRY_FRESH], now) is not True
                or self._binary(self.cfg[CONF_DPM_ACTIVE], now) is not True
                or self._binary(self.cfg[CONF_WALLBOX_FAULT], now) is not False):
            return
        observed_charging = self._binary(self.cfg[CONF_WALLBOX_CHARGING], now)
        if (kind == "power" and observed_charging is not True) or (
                kind in ("pause", "resume") and observed_charging is not False):
            return
        if kind == "resume" and self._dpm_lease is None:
            return
        self._pending = Pending(kind, target, now, next_state)
        self.last_command = f"{kind}:{target:.1f}"
        self.reason = f"requested_{kind}_not_yet_confirmed"
        self._notify()
        try:
            if kind == "power":
                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self.cfg[CONF_REQUESTED_LIMIT], "value": target},
                    blocking=True,
                )
            elif kind == "pause":
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

    def _lab(self, now, snap):
        if not self.lab_enabled or snap["house"] is None or snap["house_at"] is None:
            return
        at = snap["house_at"]
        if self._lab_last_at and at <= self._lab_last_at:
            return
        self._lab_last_at = at
        obs = Observation(
            at=now, session_id="virtual_24h", connected=True, charging=True,
            auto=True, trusted=True, house_kw=snap["house"], house_at=at,
            dpm_kw=float(self.cfg[CONF_EXPECTED_DPM]),
            current_kw=self._lab_virtual_cap, margin_minutes=90,
            remaining_budget_kwh=9999.,
            max_kw=float(self.cfg[CONF_BASE_KW]),
            boost_max_kw=float(self.cfg[CONF_BOOST_KW]),
        )
        self._lab_state, decision = evaluate(obs, self._lab_state)
        if decision.action == "set_limit":
            self._lab_virtual_cap = decision.target_kw
        row = {"at": at.astimezone(ZoneInfo(self.hass.config.time_zone)).isoformat(),
               "house_kw": round(snap["house"], 3), "dpm_assumption_kw": self.cfg[CONF_EXPECTED_DPM],
               "ev_virtual_cap_kw": self._lab_virtual_cap, "decision": decision.action,
               "reason": decision.reason, "phase": decision.phase,
               "car": "artificial_24h", "mode": "simulation_only"}
        self._lab_buffer.append(row)
        if self._lab_write_task is None or self._lab_write_task.done():
            self._lab_write_task = self.entry.async_create_background_task(
                self.hass, self._flush_lab(), "EasyWallbox RC lab log",
            )

    async def _flush_lab(self):
        while self._lab_buffer:
            rows, self._lab_buffer = self._lab_buffer, []
            for row in rows:
                try:
                    await self.hass.async_add_executor_job(
                        _append_lab, self.hass.config.path("easywallbox_smart_lab"), row)
                except (OSError, ValueError) as error:
                    _LOGGER.warning("RC laboratory file write failed: %s", type(error).__name__)
                    self.lab_enabled = False
                    return

    def add_listener(self, cb):
        self._listeners.add(cb)
        return lambda: self._listeners.discard(cb)

    async def async_change(self, field, value):
        if field == "mode" and value in ("automatic", "manual"):
            self.mode = value
            if value == "manual":
                self.real_enabled = False
                self._blocked = "manual_mode_no_automatic_restore"
        elif field == "real":
            if not value:
                self.real_enabled = False
                self._blocked = None
            elif (self.mode == "automatic"
                  and self.cfg.get(CONF_LEGACY_DISABLED, False)
                  and self._binary(self.cfg[CONF_WALLBOX_CONNECTED],
                                   datetime.now(timezone.utc)) is True):
                self.real_enabled = True
                self._blocked = None
            else:
                raise ValueError("Enable only in AUTO with cable connected and legacy automations disabled")
        elif field == "delay":
            self.delay_enabled = bool(value)
        elif field == "time":
            if not isinstance(value, time):
                raise ValueError("time required")
            self.preferred_start = value
        elif field == "departure":
            if value is not None and (not isinstance(value, datetime)
                                       or value.utcoffset() is None):
                raise ValueError("timezone aware departure required")
            self.departure_override = value
        elif field == "lab":
            self.lab_enabled = bool(value)
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
        if field in ("mode", "delay", "time", "departure", "lab"):
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
        for vehicle in self.cfg[CONF_VEHICLES]:
            ids.extend((vehicle[CONF_CABLE], vehicle[CONF_SOC]))
            if vehicle.get(CONF_TARGET_ENTITY):
                ids.append(vehicle[CONF_TARGET_ENTITY])
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
        if self._lab_write_task:
            await self._lab_write_task
        if self._lab_buffer:
            await self._flush_lab()
        self._listeners.clear()
