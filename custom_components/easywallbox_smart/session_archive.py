"""Archive the cumulative physical-session totals published by ESPHome.

The firmware owns accounting and closure: it keeps totals across pauses and
brief replugs, then zeros both after a verified 60s unplug or the 5-minute
offline fallback following a verified unplug. HA stores snapshots, never
adds counter deltas, and never sends a command from this module.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_BLE_CONNECTED, CONF_SESSION_ENERGY, CONF_SESSION_DURATION,
    CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_CHARGE_STATE,
    CONF_TELEMETRY_FRESH, CONF_VEHICLES, CONF_NAME,
)

COUNTER_MODE = "firmware_totals_v1"
COMPLETIONS = {"physical_cable_unplug", "unplug_telemetry_timeout",
               "firmware_reset_after_unplug"}
PLUGGED_STATES = {"Charging", "Vehicle ready", "Pause", "Pending",
                  "Stato transitorio", "Transition (7)", "Unknown (7)"}


class SessionArchive:
    """Persist the latest absolute totals and wait for firmware closure."""

    def __init__(self, hass, entry, cfg, notify, report=None):
        self.hass, self.entry, self.cfg = hass, entry, cfg
        self.enabled = bool(cfg.get(CONF_SESSION_ENERGY) and
                            cfg.get(CONF_SESSION_DURATION) and
                            cfg.get(CONF_WALLBOX_CONNECTED))
        # Preserve the storage key and completed records from older releases.
        self._store = Store(hass, 1, "easywallbox_smart_rc_sessions_" + entry.entry_id)
        self.sessions: list[dict] = []
        self.total = 0
        self.total_observed = 0
        self._active: dict | None = None
        self._last_counter_status = {"energy": "awaiting_data",
                                     "duration": "awaiting_data"}
        self._last_outcome = "not_yet_closed"
        self._write_lock = asyncio.Lock()
        self._unsubscribe = None
        self._tasks = set()
        self._notify = notify
        self._report = report

    async def async_load(self):
        if not self.enabled:
            return
        saved = await self._store.async_load() or {}
        outcome = saved.get("last_outcome")
        if isinstance(outcome, str):
            self._last_outcome = outcome
        items = saved.get("sessions", [])
        if isinstance(items, list):
            self.sessions = [x for x in items if isinstance(x, dict) and
                             x.get("completion") in COMPLETIONS]
        self.total = len(self.sessions)
        observed = saved.get("total")
        self.total_observed = (
            max(self.total, observed) if isinstance(items, list)
            and len(self.sessions) == len(items)
            and isinstance(observed, int) and observed >= 0 else self.total)
        active = saved.get("active")
        if isinstance(active, dict):
            if active.get("counter_mode") == COUNTER_MODE:
                self._active = deepcopy(active)
                self._active["continuity_uncertain"] = True
            else:
                # RC5 used HA-side deltas. Adding them to firmware totals
                # would double count, and even choosing a max can mix sessions.
                self._last_outcome = "legacy_active_not_migrated"

    def start(self):
        if not self.enabled or self._unsubscribe:
            return
        tracked = [
            self.cfg[k] for k in (
                CONF_BLE_CONNECTED, CONF_SESSION_ENERGY, CONF_SESSION_DURATION,
                CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_CHARGE_STATE,
                CONF_TELEMETRY_FRESH,
            ) if self.cfg.get(k)
        ]
        self._unsubscribe = async_track_state_change_event(
            self.hass, sorted(set(tracked)), self._on_event)
        self._observe()

    def _state(self, key):
        entity = self.cfg.get(key)
        st = self.hass.states.get(entity) if entity else None
        if (st is None or st.attributes.get("restored") or
                str(st.state).lower() in ("unknown", "unavailable", "")):
            return None
        return st

    def _value(self, key):
        state = self._state(key)
        return state.state if state is not None else None

    def _counter(self, name):
        key = CONF_SESSION_ENERGY if name == "energy" else CONF_SESSION_DURATION
        st = self._state(key)
        if st is None:
            self._last_counter_status[name] = "unavailable_or_restored"
            return None
        try:
            value = float(st.state)
        except (TypeError, ValueError):
            self._last_counter_status[name] = "non_numeric"
            return None
        if not isfinite(value) or value < 0:
            self._last_counter_status[name] = "out_of_range"
            return None
        # HA may display the duration in hours or energy in Wh. Store kWh/min.
        unit = st.attributes.get("unit_of_measurement")
        conversions = ({"kWh": 1, "Wh": .001} if name == "energy"
                       else {"min": 1, "h": 60, "s": 1/60})
        if unit is not None and unit not in conversions:
            self._last_counter_status[name] = "invalid_unit"
            return None
        self._last_counter_status[name] = "ok"
        return value * conversions.get(unit, 1)

    def _persist_background(self):
        task = self.entry.async_create_background_task(
            self.hass, self._persist(), "EasyWallbox persistent charge archive")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _new_active(self):
        return {
            "counter_mode": COUNTER_MODE,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "vehicle": None, "identity_conflict": False,
            "energy": None, "duration": None, "unplug_at": None,
            "continuity_uncertain": False,
        }

    def note_vehicle(self, name):
        if not self.enabled or not isinstance(name, str) or self._active is None:
            return
        known = {v.get(CONF_NAME) for v in self.cfg.get(CONF_VEHICLES, ())}
        a = self._active
        if name not in known or a.get("identity_conflict") or a.get("unplug_at"):
            return
        if a.get("vehicle") is None:
            a["vehicle"] = name
            self._persist_background()
        elif a["vehicle"] != name:
            a["vehicle"] = None
            a["identity_conflict"] = True
            a["continuity_uncertain"] = True
            self._persist_background()

    def status(self):
        a = self._active or {}
        return {
            "enabled": self.enabled,
            "history_count": len(self.sessions),
            "active": self._active is not None,
            "active_energy_kwh": round(float(a.get("energy") or 0), 3),
            "active_duration_min": round(float(a.get("duration") or 0), 2),
            "active_partial": bool(a.get("continuity_uncertain")),
            "awaiting_firmware_reset": bool(a.get("unplug_at")),
            "counter_status": dict(self._last_counter_status),
            "counter_mode": COUNTER_MODE,
            "completion_gate": "verified_unplug_and_firmware_zero_pair",
            "last_outcome": self._last_outcome,
            "reason_if_disabled": (
                "missing_session_energy_or_duration" if not self.enabled
                else None),
        }

    def _finish(self, completion):
        a = self._active
        if a is None:
            return
        energy = a.get("energy")
        minutes = a.get("duration")
        self._active = None
        if energy is None or minutes is None or energy < .2 or minutes < 2:
            self._last_outcome = "discarded_insufficient_observed_counters"
        else:
            now = datetime.now(timezone.utc).isoformat()
            row = {
                # Display the observed unplug, not the delayed reset time.
                "completed_at": a.get("unplug_at") or now,
                "detected_reset_at": now,
                "energy_kwh": round(energy, 1),
                "duration_min": int(round(minutes)),
                "vehicle": (a.get("vehicle") if not a.get("identity_conflict")
                            else None) or "Non identificata",
                "completion": completion,
                "quality": ("partial_observed" if a.get("continuity_uncertain")
                            or completion != "physical_cable_unplug" else "observed"),
            }
            self.sessions.append(row)
            self._last_outcome = "record_saved_on_firmware_reset"
            self.total = len(self.sessions)
            self.total_observed += 1
            self._notify()
        # Closing and the completed row share the same persisted document.
        self._persist_background()
        if self._report is not None:
            self._report("archive", "firmware_session_closed",
                         completion=completion, **self.status())

    def _observe(self):
        if not self.enabled:
            return
        online = self._value(CONF_BLE_CONNECTED) in ("on", "true", "True")
        fresh = online and (not self.cfg.get(CONF_TELEMETRY_FRESH) or
                            self._value(CONF_TELEMETRY_FRESH) == "on")
        cable = self._value(CONF_WALLBOX_CONNECTED)
        charging = self._value(CONF_WALLBOX_CHARGING)
        state = self._value(CONF_CHARGE_STATE)
        state_mapped = bool(self.cfg.get(CONF_CHARGE_STATE))
        plugged = fresh and cable == "on" and (
            not state_mapped or state in PLUGGED_STATES)
        unplugged = fresh and cable == "off" and charging == "off" and (
            not state_mapped or state == "Cable Unplugged")
        ambiguous = fresh and state_mapped and state is not None and (
            state not in PLUGGED_STATES and state != "Cable Unplugged")

        values = {name: self._counter(name) for name in ("energy", "duration")}
        zero_pair = values["energy"] == 0 and values["duration"] == 0
        a = self._active
        changed = False
        if a is None:
            if not plugged:
                return
            a = self._active = self._new_active()
            changed = True

        if unplugged and not a.get("unplug_at"):
            a["unplug_at"] = datetime.now(timezone.utc).isoformat()
            self._last_outcome = "awaiting_firmware_reset"
            changed = True
        if ambiguous and a.get("unplug_at"):
            # Firmware itself revokes unplug evidence on explicit error/unknown.
            a["unplug_at"] = None
            a["continuity_uncertain"] = True
            changed = True

        if a.get("unplug_at") and zero_pair:
            # Both sensors are authoritative cumulative values. The firmware
            # emits zero only when it closes; no additional HA timeout.
            completion = ("physical_cable_unplug" if unplugged else
                          "unplug_telemetry_timeout" if not fresh else
                          "firmware_reset_after_unplug")
            self._finish(completion)
            if not plugged:
                return
            a = self._active = self._new_active()
            changed = True

        if not fresh:
            if not a.get("continuity_uncertain"):
                a["continuity_uncertain"] = True
                changed = True
        elif plugged:
            if a.get("unplug_at"):
                # Nonzero cumulative values at replug belong to the same
                # firmware session. No row until its actual zero boundary.
                a["unplug_at"] = None
                self._last_outcome = "session_resumed_before_reset"
                changed = True
            for name, value in values.items():
                if value is None:
                    continue
                old = a.get(name)
                if old is not None and value < old:
                    # Unexpected regression (e.g. lost checkpoint or missed
                    # reset/replug): never sum or guess missing energy.
                    a["continuity_uncertain"] = True
                    self._last_outcome = "unexpected_firmware_counter_decrease"
                if old != value:
                    a[name] = value
                    changed = True
        elif unplugged:
            # Firmware publishes energy and minutes separately. Keep the
            # preceding snapshot if just one has reached zero; never replace
            # the final record with a mixed old/zero pair.
            for name, value in values.items():
                if value is not None and value > 0 and value != a.get(name):
                    if a.get(name) is not None and value < a[name]:
                        a["continuity_uncertain"] = True
                    a[name] = value
                    changed = True
        if changed:
            self._persist_background()

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
                "sessions": deepcopy(self.sessions),
                "active": deepcopy(self._active),
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

    @callback
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
