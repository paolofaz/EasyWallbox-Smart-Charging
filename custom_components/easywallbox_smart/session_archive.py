"""Read-only, physical-plug charging archive with persistent counter segments.

Neither a DPM pause nor an ESPHome session counter reset completes a record.
Energy and duration are measured per counter epoch and summed on a verified
physical unplug. All partial progress survives HA restarts and BLE outages.
No wallbox service or additional BLE read is issued by this module.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite

from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_BLE_CONNECTED, CONF_SESSION_ENERGY, CONF_SESSION_DURATION,
    CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_CHARGE_STATE,
    CONF_VEHICLES, CONF_NAME,
)

MAX_COUNTER_AGE = timedelta(minutes=2)
FRAME_TOLERANCE = timedelta(seconds=4)
ENERGY_RESET_KWH = 0.15
DURATION_RESET_MIN = 1.5


@dataclass(frozen=True)
class CounterPair:
    kwh: float
    minutes: float
    at: datetime
    marker: tuple[datetime, datetime]


class SessionArchive:
    """Persist one active physical connection; expose only completed records."""

    def __init__(self, hass, entry, cfg, notify):
        self.hass, self.entry, self.cfg = hass, entry, cfg
        self.enabled = bool(cfg.get(CONF_SESSION_ENERGY) and
                            cfg.get(CONF_SESSION_DURATION) and
                            cfg.get(CONF_WALLBOX_CONNECTED))
        # Same key as 0.9: retain genuine physical-unplug rows; discard
        # counter-reset-only fragments which were never completed sessions.
        self._store = Store(hass, 1, "easywallbox_smart_rc_sessions_" + entry.entry_id)
        self.sessions: list[dict] = []
        self.total = 0
        self.total_observed = 0
        self._active: dict | None = None
        self._last_marker = None
        self._last_online = None
        self._write_lock = asyncio.Lock()
        self._unsubscribe = None
        self._tasks = set()
        self._notify = notify

    async def async_load(self):
        if not self.enabled:
            return
        saved = await self._store.async_load() or {}
        items = saved.get("sessions", [])
        if isinstance(items, list):
            self.sessions = [
                x for x in items if isinstance(x, dict) and
                x.get("completion") == "physical_cable_unplug"
            ]
        self.total = len(self.sessions)
        observed = saved.get("total")
        self.total_observed = (
            max(self.total, observed) if isinstance(observed, int)
            and observed >= 0 else self.total
        )
        active = saved.get("active")
        if isinstance(active, dict) and active.get("connected_seen") is True:
            # A restart may hide an unplug; retain data but mark the gap.
            self._active = dict(active)
            self._active["continuity_uncertain"] = True

    def start(self):
        if not self.enabled or self._unsubscribe:
            return
        tracked = [
            self.cfg[k] for k in (
                CONF_BLE_CONNECTED, CONF_SESSION_ENERGY, CONF_SESSION_DURATION,
                CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_CHARGE_STATE
            ) if self.cfg.get(k)
        ]
        self._unsubscribe = async_track_state_change_event(
            self.hass, sorted(set(tracked)), self._on_event)
        self._observe()

    @staticmethod
    def _stamp(st):
        return getattr(st, "last_reported", None) or st.last_updated

    def _recent(self, st):
        if st is None or st.attributes.get("restored") or st.state in (
                "unknown", "unavailable", ""):
            return False
        stamp = self._stamp(st)
        now = datetime.now(timezone.utc)
        return (stamp is not None and stamp.tzinfo is not None and
                timedelta(0) <= now-stamp <= MAX_COUNTER_AGE)

    def _pair(self):
        states = [self.hass.states.get(self.cfg[k]) for k in (
            CONF_SESSION_ENERGY, CONF_SESSION_DURATION)]
        if any(not self._recent(st) for st in states):
            return None
        try:
            energy, minutes = (float(st.state) for st in states)
        except (TypeError, ValueError):
            return None
        if (not isfinite(energy) or not isfinite(minutes) or
                energy < 0 or minutes < 0):
            return None
        stamps = tuple(self._stamp(st) for st in states)
        if abs(stamps[0]-stamps[1]) > FRAME_TOLERANCE:
            return None
        return CounterPair(energy, minutes, max(stamps), stamps)

    def _persist_background(self):
        task = self.entry.async_create_background_task(
            self.hass, self._persist(), "EasyWallbox persistent charge archive")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _new_active(self):
        return {
            "connected_seen": True,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "vehicle": None, "identity_conflict": False,
            "completed_kwh": 0.0, "completed_min": 0.0,
            "peak_kwh": 0.0, "peak_min": 0.0, "segments": 0,
            "last_pair_at": None, "continuity_uncertain": False,
        }

    def note_vehicle(self, name):
        """Use only the controller's confirmed cloud vehicle identification."""
        if not self.enabled or not isinstance(name, str):
            return
        known = {v.get(CONF_NAME) for v in self.cfg.get(CONF_VEHICLES, ())}
        if name not in known or self._active is None:
            return
        a = self._active
        if a.get("identity_conflict"):
            return
        if a.get("vehicle") is None:
            a["vehicle"] = name
            self._persist_background()
        elif a["vehicle"] != name:
            a["vehicle"] = None
            a["identity_conflict"] = True
            a["continuity_uncertain"] = True
            self._persist_background()

    def _observe_pair(self, pair):
        if pair is None or self._active is None or pair.marker == self._last_marker:
            return
        self._last_marker = pair.marker
        a = self._active
        prev_energy = float(a.get("peak_kwh", 0))
        prev_minutes = float(a.get("peak_min", 0))
        energy_reset = prev_energy-pair.kwh >= ENERGY_RESET_KWH
        time_reset = prev_minutes-pair.minutes >= DURATION_RESET_MIN
        if energy_reset and time_reset:
            # Joint reset is a new counter epoch, NOT a completed charge.
            a["completed_kwh"] += prev_energy
            a["completed_min"] += prev_minutes
            a["peak_kwh"] = pair.kwh
            a["peak_min"] = pair.minutes
            a["segments"] += 1
        elif energy_reset or time_reset:
            # AD's two sensors may publish non-atomically; never add a
            # fragment before both decreases are observed.
            return
        else:
            a["peak_kwh"] = max(prev_energy, pair.kwh)
            a["peak_min"] = max(prev_minutes, pair.minutes)
        a["last_pair_at"] = pair.at.isoformat()
        self._persist_background()

    def _finish(self):
        a = self._active
        if a is None:
            return
        energy = float(a["completed_kwh"])+float(a["peak_kwh"])
        minutes = float(a["completed_min"])+float(a["peak_min"])
        self._active = None
        self._last_marker = None
        if energy < .2 or minutes < 2:
            self._persist_background()
            return  # A cable insertion with no measurable charge.
        now = datetime.now(timezone.utc)
        row = {
            "completed_at": now.isoformat(),
            "detected_reset_at": now.isoformat(),  # Old card compatibility.
            "energy_kwh": round(energy, 1),
            "duration_min": int(round(minutes)),
            "vehicle": (a.get("vehicle") if not a.get("identity_conflict")
                        else None) or "Non identificata",
            "segments": int(a.get("segments", 0))+1,
            "completion": "physical_cable_unplug",
            "quality": ("partial_observed" if a.get("continuity_uncertain")
                        else "observed"),
        }
        self.sessions.append(row)
        self.total = len(self.sessions)
        self.total_observed += 1
        self._notify()
        self._persist_background()

    def _observe(self):
        if not self.enabled:
            return
        ble = self.hass.states.get(self.cfg[CONF_BLE_CONNECTED])
        online = bool(self._recent(ble) and ble.state in ("on", "true", "True"))
        if not online:
            if self._active is not None and not self._active.get("continuity_uncertain"):
                self._active["continuity_uncertain"] = True
                self._persist_background()
            self._last_online = False
            self._last_marker = None
            return
        self._last_online = True
        cable = self.hass.states.get(self.cfg[CONF_WALLBOX_CONNECTED])
        if not self._recent(cable) or cable.state not in ("on", "off"):
            return
        if cable.state == "on":
            if self._active is None:
                self._active = self._new_active()
                self._persist_background()
            self._observe_pair(self._pair())
            return

        # OFF alone is not enough: require the matching wallbox state and
        # charging OFF. Neither BLE unavailable nor a paused EV can finalize.
        if self._active is None:
            return
        state_id = self.cfg.get(CONF_CHARGE_STATE)
        state = self.hass.states.get(state_id) if state_id else None
        charging_id = self.cfg.get(CONF_WALLBOX_CHARGING)
        charging = self.hass.states.get(charging_id) if charging_id else None
        if (state_id and (not self._recent(state) or
                          state.state != "Cable Unplugged")):
            return
        if (charging_id and (not self._recent(charging) or
                             charging.state != "off")):
            return
        self._finish()

    def page(self, *, offset=0, limit=20):
        """Only completed physical connections appear in the history."""
        if not self.enabled:
            return {"count": 0, "total_observed": 0, "sessions": [],
                    "offset": offset, "limit": limit, "has_more": False}
        descending = list(reversed(self.sessions))
        return {"count": len(self.sessions), "total_observed": self.total_observed,
                "sessions": descending[offset:offset+limit],
                "offset": offset, "limit": limit,
                "has_more": offset+limit < len(self.sessions)}

    async def _persist(self):
        async with self._write_lock:
            await self._store.async_save({
                "total": self.total_observed,
                "sessions": self.sessions,
                "active": self._active,
            })

    async def async_prune(self, keep_last: int):
        if not self.enabled:
            raise ValueError("session_history_not_configured")
        if not isinstance(keep_last, int) or isinstance(keep_last, bool) or keep_last < 1:
            raise ValueError("keep_last_must_be_positive_integer")
        removed = max(0, len(self.sessions)-keep_last)
        if removed:
            self.sessions = self.sessions[-keep_last:]
            self.total = len(self.sessions)
            await self._persist()
            self._notify()
        return {"removed": removed, "retained": self.total,
                "total_observed": self.total_observed}

    def _on_event(self, event):
        self._observe()

    async def async_close(self):
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks))
        if self.enabled:
            await self._persist()
