"""Read-only charging session archive, finalized by physical unplug.

ESPHome's duration can reset ON unplug, while energy may reset on the NEXT
plug-in. Cache the last jointly valid counters while attached, then save
on a witnessed physical cable disconnection, never on a charging pause.
Fallback joint-reset detection remains for older/missed observations.
No new BLE commands, polling, or fabricated energy/duration.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite

from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (CONF_BLE_CONNECTED, CONF_SESSION_ENERGY,
                    CONF_SESSION_DURATION, CONF_WALLBOX_CONNECTED,
                    CONF_WALLBOX_CHARGING, CONF_CHARGE_STATE)

MAX_COUNTER_AGE = timedelta(minutes=2)
FRAME_TOLERANCE = timedelta(seconds=4)


@dataclass(frozen=True)
class CounterPair:
    kwh: float
    minutes: float
    at: datetime
    marker: tuple[datetime, datetime]


class JointResetDetector:
    """Pure transition detector; only genuine pairs from one BLE epoch count."""

    def __init__(self):
        self.peak: CounterPair | None = None
        self.last_marker = None
        self.pair_count = 0
        self.online = False

    def observe(self, pair: CounterPair | None, ble_online: bool):
        if not ble_online:
            self.peak = None
            self.last_marker = None
            self.pair_count = 0
            self.online = False
            return None
        if pair is None or pair.marker == self.last_marker:
            return None
        self.last_marker = pair.marker
        if not self.online:
            self.online = True
            self.peak = pair
            self.pair_count = 1
            return None
        old = self.peak
        if old is None:
            self.peak, self.pair_count = pair, 1
            return None

        e_fall = old.kwh - pair.kwh >= .15
        t_fall = old.minutes - pair.minutes >= 1.5
        if e_fall and t_fall:
            # A reboot or a reconnect must not invent a new completed
            # session. Here we have >=2 real prior AD frames, and the
            # counters dropped together while BLE remained continuously on.
            accepted = (self.pair_count >= 2 and old.kwh >= .2 and
                        old.minutes >= 2 and pair.at > old.at)
            self.peak, self.pair_count = pair, 1
            if accepted:
                return {
                    "energy_kwh": round(old.kwh, 1),
                    "duration_min": int(round(old.minutes)),
                    "last_pre_reset_at": old.at.isoformat(),
                    "detected_reset_at": pair.at.isoformat(),
                }
            return None
        if e_fall or t_fall:
            # Both counters must decrease; do not adopt an inconsistent
            # report, and do not prematurely discard the earlier peak.
            return None
        self.peak = CounterPair(
            max(old.kwh, pair.kwh), max(old.minutes, pair.minutes),
            pair.at, pair.marker)
        self.pair_count += 1
        return None


class SessionArchive:
    """A small HA .storage archive with a single on-change output sensor."""

    def __init__(self, hass, entry, cfg, notify):
        self.hass, self.entry, self.cfg = hass, entry, cfg
        self.enabled = bool(cfg.get(CONF_SESSION_ENERGY) and
                            cfg.get(CONF_SESSION_DURATION))
        self._store = Store(hass, 1, "easywallbox_smart_rc_sessions_" + entry.entry_id)
        self._detector = JointResetDetector()
        self.sessions = []
        self.total = 0  # Currently retained records, exposed in HA
        self.total_observed = 0  # Historical count, never reduced by pruning
        self._write_lock = asyncio.Lock()
        self._unsubscribe = None
        self._tasks = set()
        self._notify = notify
        self._last_cable = None
        self._last_connected_pair: CounterPair | None = None
        self._unplug_candidate: CounterPair | None = None
        self._skip_next_joint_reset = False

    async def async_load(self):
        if not self.enabled:
            return
        saved = await self._store.async_load() or {}
        items = saved.get("sessions", [])
        if isinstance(items, list):
            # prior iterations kept 12. Keep those intact and never truncate new records.
            self.sessions = [x for x in items if isinstance(x, dict)]
        total = saved.get("total")
        self.total = len(self.sessions)
        self.total_observed = max(self.total, total) if isinstance(total, int) and total >= 0 else self.total
        self._skip_next_joint_reset = saved.get("unplug_archived_before_reset") is True

    def start(self):
        if not self.enabled or self._unsubscribe:
            return
        tracked = [self.cfg[k] for k in
                   (CONF_BLE_CONNECTED, CONF_SESSION_ENERGY,
                    CONF_SESSION_DURATION, CONF_WALLBOX_CONNECTED,
                    CONF_WALLBOX_CHARGING, CONF_CHARGE_STATE)
                   if self.cfg.get(k)]
        self._unsubscribe = async_track_state_change_event(
            self.hass, sorted(set(tracked)), self._on_event)
        self._observe()

    @staticmethod
    def _stamp(st):
        return getattr(st, "last_reported", None) or st.last_updated

    def _pair(self):
        states = [self.hass.states.get(self.cfg[k]) for k in
                  (CONF_SESSION_ENERGY, CONF_SESSION_DURATION)]
        now = datetime.now(timezone.utc)
        if any(st is None or st.attributes.get("restored") or
               st.state in ("unknown", "unavailable", "")
               for st in states):
            return None
        try:
            kw, minutes = [float(st.state) for st in states]
        except (TypeError, ValueError):
            return None
        if not (isfinite(kw) and isfinite(minutes) and
                kw >= 0 and minutes >= 0):
            return None
        stamps = tuple(self._stamp(st) for st in states)
        if (any(t is None or t.tzinfo is None or not
                timedelta(0) <= now-t <= MAX_COUNTER_AGE for t in stamps) or
                abs(stamps[0]-stamps[1]) > FRAME_TOLERANCE):
            return None
        return CounterPair(kw, minutes, max(stamps), stamps)

    def _persist_background(self):
        task = self.entry.async_create_background_task(
            self.hass, self._persist(),
            "EasyWallbox beta completed session archive")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _append(self, item):
        self.sessions.append(item)
        self.total = len(self.sessions)
        self.total_observed += 1
        self._notify()
        self._persist_background()

    def _observe(self):
        if not self.enabled:
            return
        ble = self.hass.states.get(self.cfg[CONF_BLE_CONNECTED])
        online = ble is not None and ble.state in ("on", "true", "True")
        pair = self._pair() if online else None
        reset = self._detector.observe(pair, online)
        if not online:
            self._last_cable = None
            self._last_connected_pair = None
            self._unplug_candidate = None
            return

        if reset is not None:
            if self._skip_next_joint_reset:
                # The previous physical unplug was ALREADY archived.
                self._skip_next_joint_reset = False
                self._persist_background()
            else:
                self._append(reset)

        cable_id = self.cfg.get(CONF_WALLBOX_CONNECTED)
        if not cable_id:
            return  # Legacy counter-reset-only setup.
        cable_state = self.hass.states.get(cable_id)
        cable = (
            True if cable_state and cable_state.state == "on" else
            False if cable_state and cable_state.state == "off" else None)
        if cable is None or (
                cable_state is not None and
                cable_state.attributes.get("restored")):
            return
        if cable is True:
            self._unplug_candidate = None
            self._last_cable = True
            if pair is not None and pair.kwh >= .2 and pair.minutes >= 2:
                # Cache only synchronized AD counters from a connected car.
                # The next AD on unplug may reset duration to zero first.
                self._last_connected_pair = pair
            return
        if self._last_cable is True and self._last_connected_pair is not None:
            self._unplug_candidate = self._last_connected_pair
        self._last_cable = False
        if self._unplug_candidate is None:
            return
        charge_id = self.cfg.get(CONF_CHARGE_STATE)
        charge_state = self.hass.states.get(charge_id) if charge_id else None
        if charge_id and (charge_state is None or
                          charge_state.state != "Cable Unplugged" or
                          charge_state.attributes.get("restored")):
            return  # Wait for the matching AD state-3 event.
        charging_id = self.cfg.get(CONF_WALLBOX_CHARGING)
        charging = self.hass.states.get(charging_id) if charging_id else None
        if charging_id and (charging is None or charging.state != "off"):
            return
        previous = self._unplug_candidate
        now = datetime.now(timezone.utc)
        if now-previous.at > MAX_COUNTER_AGE or previous.at > now:
            self._unplug_candidate = None
            self._last_connected_pair = None
            return  # No stale counters stored as a measured session.
        self._unplug_candidate = None
        self._last_connected_pair = None
        self._skip_next_joint_reset = True
        self._append({
            "energy_kwh": round(previous.kwh, 1),
            "duration_min": int(round(previous.minutes)),
            "last_pre_reset_at": previous.at.isoformat(),
            "detected_reset_at": now.isoformat(),
            "completion": "physical_cable_unplug",
            "completed_at": now.isoformat(),
        })

    def page(self, *, offset=0, limit=20):
        """Latest-first snapshot; only the requested page crosses WS."""
        if not self.enabled:
            return {"count": 0, "total_observed": 0, "sessions": [],
                    "offset": offset, "limit": limit, "has_more": False}
        count = len(self.sessions)
        descending = list(reversed(self.sessions))
        return {"count": count, "total_observed": self.total_observed,
                "sessions": descending[offset:offset+limit],
                "offset": offset, "limit": limit,
                "has_more": offset+limit < count}

    async def _persist(self):
        async with self._write_lock:
            await self._store.async_save({
                # Keep the old storage key for a lossless prior iterations migration.
                "total": self.total_observed,
                "sessions": self.sessions,
                "unplug_archived_before_reset": self._skip_next_joint_reset,
            })

    async def async_prune(self, keep_last: int):
        """Destructive, admin-only explicit action; no implied retention cap."""
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
