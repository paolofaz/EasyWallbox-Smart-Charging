"""Read-only, physical-plug charging archive with persistent counter segments.

Neither a DPM pause nor an ESPHome session counter reset completes a record.
Energy and duration are measured per counter epoch and summed on a verified
physical unplug. All partial progress survives HA restarts and BLE outages.
No wallbox service or additional BLE read is issued by this module.
"""
from __future__ import annotations

import asyncio
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
# Counter states are independent: wallbox reports share a BLE frame, but
# HA state_changed events need not be simultaneous or equally frequent.
ENERGY_RESET_KWH = 0.15
DURATION_RESET_MIN = 1.5


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
        self._last_online = None
        self._last_counter_status = {"energy": "awaiting_data",
                                     "duration": "awaiting_data"}
        self._last_outcome = "not_yet_closed"
        self._write_lock = asyncio.Lock()
        self._unsubscribe = None
        self._tasks = set()
        self._notify = notify

    async def async_load(self):
        if not self.enabled:
            return
        saved = await self._store.async_load() or {}
        outcome = saved.get("last_outcome")
        if isinstance(outcome, str) and len(outcome) <= 100:
            self._last_outcome = outcome
        items = saved.get("sessions", [])
        if isinstance(items, list):
            self.sessions = [
                x for x in items if isinstance(x, dict) and
                x.get("completion") == "physical_cable_unplug"
            ]
        self.total = len(self.sessions)
        observed = saved.get("total")
        # Old beta recorded phantom partial rows at a joint counter reset.
        # Historical total must never imply those were completed charges.
        old_items = saved.get("sessions", [])
        fully_completed = (isinstance(old_items, list) and
                           len(self.sessions) == len(old_items))
        self.total_observed = (
            max(self.total, observed) if fully_completed and
            isinstance(observed, int) and observed >= 0 else self.total
        )
        active = saved.get("active")
        if isinstance(active, dict) and active.get("connected_seen") is True:
            # A restart may hide an unplug; retain data but mark the gap.
            self._active = dict(active)
            self._active["continuity_uncertain"] = True
            if "counters" not in self._active:
                # Translate unfinished RC4 accumulators without discarding
                # energy when the integration upgrades while a car is plugged.
                old = self._active
                self._active["counters"] = {
                    "energy": {"total": float(old.get("completed_kwh", 0)) +
                                        float(old.get("peak_kwh", 0)),
                               "last": float(old.get("peak_kwh", 0)),
                               "seen_at": None},
                    "duration": {"total": float(old.get("completed_min", 0)) +
                                          float(old.get("peak_min", 0)),
                                 "last": float(old.get("peak_min", 0)),
                                 "seen_at": None},
                }

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

    def _counter(self, name):
        """A valid independent read; never require two HA stamps to match."""
        key = (CONF_SESSION_ENERGY if name == "energy"
               else CONF_SESSION_DURATION)
        st = self.hass.states.get(self.cfg[key])
        if not self._recent(st):
            self._last_counter_status[name] = "unavailable_or_stale"
            return None
        try:
            value = float(st.state)
        except (TypeError, ValueError):
            self._last_counter_status[name] = "non_numeric"
            return None
        if not isfinite(value) or value < 0:
            self._last_counter_status[name] = "out_of_range"
            return None
        self._last_counter_status[name] = "ok"
        return value, self._stamp(st)

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
            "counters": {
                "energy": {"total": 0.0, "last": None, "seen_at": None},
                "duration": {"total": 0.0, "last": None, "seen_at": None},
            },
            "segments": 0, "continuity_uncertain": False,
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

    def _observe_counters(self):
        """Accumulate monotonically *per sensor*, surviving asynchronous resets.

        Store the increment between successive actual reports. A freshly
        attached integration starts from observed counters, rather than
        claiming earlier energy as new; the archive will mark this partial.
        A reset cannot zero the accumulated progress. Sensor readings are
        independent; they do not need coincident HA timestamps.
        """
        a = self._active
        if a is None:
            return
        counters = a.setdefault("counters", self._new_active()["counters"])
        changed = False
        for name in ("energy", "duration"):
            reading = self._counter(name)
            if reading is None:
                continue
            value, stamp = reading
            c = counters[name]
            old = c.get("last")
            # HA last_reported changes even when a state value is identical.
            # The source timestamp is diagnostic, NOT a trigger for counting
            # time. Only the actual monotonic meter difference is counted.
            if old is None:
                c["last"] = value
                c["seen_at"] = stamp.isoformat()
                if value >= (.2 if name == "energy" else 2):
                    # Startup while a session is already underway: the
                    # historical part cannot be assigned without proof.
                    a["continuity_uncertain"] = True
                changed = True
                continue
            delta = value-float(old)
            tolerance = .015 if name == "energy" else .25
            reset = (
                delta <= -(ENERGY_RESET_KWH if name == "energy"
                           else DURATION_RESET_MIN)
                or (value <= tolerance and old > tolerance)
            )
            if reset:
                # New epoch can already have accumulated energy or minutes.
                # Preserve the old total and account for the new reading.
                c["total"] = float(c.get("total", 0)) + value
                c["last"] = value
                c["resets"] = int(c.get("resets", 0)) + 1
                # Both sensors resetting at slightly different times
                # is ONE new charge segment, not two.
                a["segments"] = max(int(a.get("segments", 0)), c["resets"])
                changed = True
            elif delta > tolerance:
                c["total"] = float(c.get("total", 0)) + delta
                c["last"] = value
                changed = True
            elif delta >= -tolerance and value > float(old):
                c["last"] = value
                changed = True
            c["seen_at"] = stamp.isoformat()
        if changed:
            self._persist_background()

    def status(self):
        """Small diagnostic record, never wallbox commands or secrets."""
        a = self._active
        counters = a.get("counters", {}) if a else {}
        return {
            "enabled": self.enabled,
            "history_count": len(self.sessions),
            "active": a is not None,
            "active_energy_kwh": round(float(
                counters.get("energy", {}).get("total", 0)), 3),
            "active_duration_min": round(float(
                counters.get("duration", {}).get("total", 0)), 2),
            "active_partial": bool(a and a.get("continuity_uncertain")),
            "counter_status": dict(self._last_counter_status),
            "completion_gate": "physical_unplug",
            "last_outcome": self._last_outcome,
            "reason_if_disabled": (
                "missing_session_energy_or_duration" if not self.enabled
                else None),
        }

    def _finish(self):
        a = self._active
        if a is None:
            return
        counters = a.get("counters", {})
        energy = float(counters.get("energy", {}).get("total", 0))
        minutes = float(counters.get("duration", {}).get("total", 0))
        self._active = None
        if energy < .2 or minutes < 2:
            self._last_outcome = "discarded_insufficient_observed_counters"
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
        self._last_outcome = "record_saved_on_verified_unplug"
        self.total = len(self.sessions)
        self.total_observed += 1
        self._notify()
        self._persist_background()

    def _observe(self):
        if not self.enabled:
            return
        ble = self.hass.states.get(self.cfg[CONF_BLE_CONNECTED])
        # BLE connection is a stable state, not a cyclic sample. ESPHome
        # invalidates it on disconnect; it need not be republished every 2m.
        online = bool(ble is not None and
                      not ble.attributes.get("restored") and
                      ble.state in ("on", "true", "True"))
        if not online:
            if self._active is not None and not self._active.get("continuity_uncertain"):
                self._active["continuity_uncertain"] = True
                self._persist_background()
            self._last_online = False
            return
        self._last_online = True
        cable = self.hass.states.get(self.cfg[CONF_WALLBOX_CONNECTED])
        # Car Connected is also a stable BLE-epoch flag. Duration/Energy
        # remain time-fenced in _pair(), but the physical state may have
        # remained ON since plug-in many hours ago.
        if (cable is None or cable.attributes.get("restored")
                or cable.state not in ("on", "off")):
            return
        if cable.state == "on":
            if self._active is None:
                self._active = self._new_active()
                self._persist_background()
            self._observe_counters()
            return

        # OFF alone is not enough: require the matching wallbox state and
        # charging OFF. Neither BLE unavailable nor a paused EV can finalize.
        if self._active is None:
            return
        state_id = self.cfg.get(CONF_CHARGE_STATE)
        state = self.hass.states.get(state_id) if state_id else None
        charging_id = self.cfg.get(CONF_WALLBOX_CHARGING)
        charging = self.hass.states.get(charging_id) if charging_id else None
        # An EV can stop charging at 04:20 and remain plugged until 08:30.
        # 'Charging=off' from that BLE epoch is still valid; rejecting it as
        # stale would silently lose the completed session. The firmware
        # invalidates its AD flags during a BLE loss.
        if (state_id and (state is None or state.attributes.get("restored")
                          or state.state != "Cable Unplugged")):
            return
        if (charging_id and (charging is None or
                             charging.attributes.get("restored") or
                             charging.state != "off")):
            return
        # The last independent counter reports may arrive at the same BLE
        # disconnect frame. Read them once more before closing.
        self._observe_counters()
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
                "has_more": offset+limit < len(self.sessions),
                "archive_status": self.status()}

    async def _persist(self):
        async with self._write_lock:
            await self._store.async_save({
                "total": self.total_observed,
                "sessions": self.sessions,
                "active": self._active,
                "last_outcome": self._last_outcome,
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
