"""Read-only HA event adapter. Never invokes device services or BLE commands."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)

from .const import (
    CONF_CABLE, CONF_CAPACITY, CONF_CONFIRMED_LIMIT, CONF_DEPARTURE_WEEKDAY,
    CONF_DEPARTURE_WEEKEND, CONF_DPM_MODEL, CONF_DOWNSTAIRS, CONF_EFFICIENCY,
    CONF_EV_POWER, CONF_REQUESTED_LIMIT, CONF_SOC, CONF_SUSTAINABLE,
    CONF_TARGET_DEFAULT, CONF_TARGET_ENTITY, CONF_TELEMETRY_FRESH, CONF_UPSTAIRS,
    CONF_VEHICLES, CONF_WALLBOX_CHARGING, CONF_WALLBOX_CONNECTED,
    CONF_VEHICLE_OVERRIDES, CONF_HOUSE_SOURCES,
    CONF_SESSION_ENERGY, CONF_SESSION_DURATION,
)
from .departure_policy import DepartureAdvice, advise_departure
from .session_policy import SessionControl, observe, user_select_mode
from .core import (
    Config, CoreState, HouseSnapshot, LimitSnapshot, Proposal,
    SessionSnapshot, evaluate, plan,
)
from .sources import finite_number, next_departure, on, power_kw
from .rate_estimator import RateState, RateEstimate, estimate
from .target_policy import resolved_target, selected_mode

# Conservative lab candidates; staleness is not inferred from last_changed.
SHELLY_REPORT_AGE = timedelta(minutes=20)
EV_REPORT_AGE = timedelta(minutes=5)
COUNTER_REPORT_AGE = timedelta(minutes=5)


class SimulationCoordinator:
    """One local wallbox, multiple vehicle profiles, no actuation."""

    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        self.config = dict(entry.data)
        # Saved 0.1.0 config entries remain usable: options can update the
        # meter list and counters without editing .storage or reinstalling.
        for field in (CONF_HOUSE_SOURCES, CONF_SESSION_ENERGY, CONF_SESSION_DURATION):
            if field in entry.options:
                self.config[field] = entry.options[field]
        self.house_sources = self.config.get(
            CONF_HOUSE_SOURCES,
            [self.config.get(CONF_DOWNSTAIRS), self.config.get(CONF_UPSTAIRS)],
        )
        self.policy = Config(dpm_model_kw=float(self.config[CONF_DPM_MODEL]))
        self.state: CoreState | None = None
        self.proposal: Proposal | None = None
        self.planning = None
        self.advice: DepartureAdvice | None = None
        self.session: SessionSnapshot | None = None
        self.control: SessionControl | None = None
        self.rate_state: RateState | None = None
        self.rate: RateEstimate = RateEstimate(None, "unavailable")
        self._vehicle_id = None
        self._active_departure = None  # Lock goal for session, even after deadline
        self._session_seq = 0
        self._base_unsub = None
        self._house_unsub = None
        self._timer_unsub = None
        self._listeners = set()
        self._charging = False
        self._fingerprint = None
        self.quality = "initializing"
        self.last_evaluation: datetime | None = None

    def _raw(self, entity_id: str | None):
        return self.hass.states.get(entity_id) if entity_id else None

    def _on(self, entity_id: str | None) -> bool | None:
        source = self._raw(entity_id)
        return on(source.state) if source else None

    def _number(self, entity_id: str | None) -> float | None:
        source = self._raw(entity_id)
        return finite_number(source.state) if source else None

    def _power(self, entity_id: str | None, max_age: timedelta | None = None) -> float | None:
        source = self._raw(entity_id)
        if source is None:
            return None
        if max_age is not None:
            reported = getattr(source, "last_reported", None) or source.last_updated
            if reported is None or datetime.now(timezone.utc) - reported > max_age:
                return None
        return power_kw(source.state, source.attributes.get("unit_of_measurement"))

    def _counter(self, entity_id: str | None, unit: str) -> float | None:
        """Read an ESPHome session counter only when recent and unit-matched."""
        source = self._raw(entity_id)
        if source is None or source.attributes.get("unit_of_measurement") != unit:
            return None
        reported = getattr(source, "last_reported", None) or source.last_updated
        if (reported is None
                or not timedelta(0) <= datetime.now(timezone.utc) - reported <= COUNTER_REPORT_AGE):
            return None
        value = finite_number(source.state)
        return value if value is not None and value >= 0 else None

    def _make_session(self, now: datetime) -> SessionSnapshot:
        cable_states = [
            (v, self._on(v[CONF_CABLE])) for v in self.config[CONF_VEHICLES]
        ]
        present = [v for v, connected in cable_states if connected is True]
        cable_unknown = any(connected is None for _, connected in cable_states)
        wallbox_connected = self._on(self.config[CONF_WALLBOX_CONNECTED])
        definite_disconnect = (
            wallbox_connected is False and not present and not cable_unknown
        )
        unique_connection = (
            wallbox_connected is True and len(present) == 1
            and not cable_unknown
        )
        connection = (
            False if definite_disconnect
            else True if unique_connection
            else None
        )
        ambiguous = not unique_connection and not definite_disconnect
        selected = present[0] if unique_connection else None
        identity = selected[CONF_CABLE] if selected else None
        if selected is not None:
            # Options Flow edits the planner, never the underlying HA entities.
            # Only one vehicle at a time gets an override; keys remain stable.
            per_car = self.entry.options.get(CONF_VEHICLE_OVERRIDES, {})
            selected = {
                **selected,
                **per_car.get(identity, {}),
            }
        if definite_disconnect:
            if self._vehicle_id is not None:
                self._session_seq += 1
            self._vehicle_id = None
            self._active_departure = None
            self.state = None
        elif identity is not None and identity != self._vehicle_id:
            self._session_seq += 1
            self._vehicle_id = identity
            self._active_departure = None
            self.state = None
        # UNKNOWN is NOT a confirmed unplug: preserve manual/paused intent.

        if selected:
            source = self._raw(selected[CONF_SOC])
            soc = finite_number(source.state) if source else None
            soc_at = ((getattr(source, "last_reported", None) or source.last_updated)
                      if source else None)
            # One active source only. A selected HA target that is unavailable,
            # invalid, or not a percentage NEVER falls back to old fixed data.
            target_id = selected.get(CONF_TARGET_ENTITY)
            target = resolved_target(selected, self._raw(target_id))
            if self._active_departure is None:
                self._active_departure = next_departure(
                    now.astimezone(ZoneInfo(self.hass.config.time_zone)),
                    selected[CONF_DEPARTURE_WEEKDAY], selected[CONF_DEPARTURE_WEEKEND],
                )
            # Preserve original departure throughout a session (evcc goal lock).
            # Missing the deadline must NOT advance it to tomorrow.
            departure = self._active_departure
        else:
            soc = soc_at = target = departure = None
        ev_kw = self._power(self.config[CONF_EV_POWER], EV_REPORT_AGE)
        charging = (selected is not None
                    and self._on(self.config[CONF_WALLBOX_CHARGING]) is True
                    and self._on(self.config[CONF_TELEMETRY_FRESH]) is True
                    and ev_kw is not None and ev_kw >= 0.10)
        self._charging = bool(charging)
        telemetry_trusted = self._on(self.config[CONF_TELEMETRY_FRESH]) is True
        sid = f"{self.entry.entry_id}:{self._session_seq}" if identity else None
        self.rate_state, self.rate = estimate(
            now, sid, bool(charging), ev_kw,
            self._counter(self.config.get(CONF_SESSION_ENERGY), "kWh")
                if telemetry_trusted else None,
            self._counter(self.config.get(CONF_SESSION_DURATION), "min")
                if telemetry_trusted else None,
            self._power(self.config[CONF_CONFIRMED_LIMIT]),
            self.rate_state,
        )
        target_known_reached = (
            soc is not None and target is not None and soc >= target
            and soc_at is not None
            and timedelta(0) <= now - soc_at <= timedelta(
                minutes=self.policy.soc_max_age_minutes
            )
        )
        self.control = observe(
            self.control,
            session_id=(
                f"{self.entry.entry_id}:{self._session_seq}"
                if identity is not None else None
            ),
            connection=connection,
            charging=bool(charging),
            ambiguous=ambiguous,
            target_reached=target_known_reached,
        )
        return SessionSnapshot(
            session_id=f"{self.entry.entry_id}:{self._session_seq}",
            mode=self.control.mode if connection is True else "RECONCILE",
            vehicle_id=identity, vehicle_ambiguous=ambiguous, charging=bool(charging),
            soc=soc, soc_at=soc_at, target_soc=target, departure_at=departure,
            usable_capacity_kwh=(float(selected[CONF_CAPACITY]) if selected else None),
            ac_efficiency=(float(selected[CONF_EFFICIENCY]) if selected else None),
            sustainable_kw=self.rate.kw if selected else None,
            wallbox_reports_charging=self._on(self.config[CONF_WALLBOX_CHARGING]),
        )

    def _house(self) -> HouseSnapshot:
        sources = tuple(self._power(entity_id, SHELLY_REPORT_AGE)
                        for entity_id in self.house_sources)
        quality = "ok" if sources and all(v is not None for v in sources) else "unavailable_or_stale"
        return HouseSnapshot(None, None, quality, sources_kw=sources)

    def _limits(self) -> LimitSnapshot:
        return LimitSnapshot(
            self._power(self.config[CONF_REQUESTED_LIMIT]),
            self._power(self.config[CONF_CONFIRMED_LIMIT]),
        )

    def _observe_house_only_in_charge(self, charging: bool) -> None:
        if charging and self._house_unsub is None:
            watch = list(self.house_sources)
            self._house_unsub = async_track_state_change_event(self.hass, watch, self._on_change)
        if not charging and self._house_unsub is not None:
            self._house_unsub()
            self._house_unsub = None

    def _clear_timer(self):
        if self._timer_unsub is not None:
            self._timer_unsub()
            self._timer_unsub = None

    @callback
    def _on_change(self, _event):
        self.refresh()

    @callback
    def _on_timer(self, _now):
        self._timer_unsub = None
        self.refresh()

    def _schedule(self, now: datetime, proposal: Proposal):
        """Only schedule useful future decisions for an identified session."""
        self._clear_timer()
        choices: list[datetime] = []
        # While the car is plugged in and waiting, re-check only at the next
        # advisory milestone (never sample continuously while disconnected).
        if self.advice and self.advice.next_check_at and self.advice.next_check_at > now:
            choices.append(self.advice.next_check_at)

        if self._charging:
            if proposal.next_check_at and proposal.next_check_at > now:
                choices.append(proposal.next_check_at)
            if self.state and self.state.mode == "LIMITED" and self.planning:
                cap, original = self.state.cap_kw, self.state.original_kw
                if cap is not None and original is not None and original > cap:
                    budget_left = (
                        self.planning.discretionary_budget_kwh
                        - self.state.spent_kwh_upper_bound
                    )
                    if budget_left > 0:
                        choices.append(
                            now + timedelta(hours=budget_left / (original - cap))
                        )
            if (proposal.slack_minutes is not None
                    and proposal.slack_minutes > self.policy.min_slack_minutes):
                choices.append(
                    now + timedelta(
                        minutes=proposal.slack_minutes - self.policy.min_slack_minutes
                    )
                )

        # A single freshness-deadline timer invalidates a stale SOC/EV value
        # even when no further HA state_changed event arrives. Never sample
        # disconnected sensors just to refresh a clock.
        if self.session and self.session.vehicle_id:
            soc_at = self.session.soc_at
            if soc_at is not None:
                soc_expires = soc_at + timedelta(
                    minutes=self.policy.soc_max_age_minutes, seconds=1
                )
                if soc_expires > now:
                    choices.append(soc_expires)
            if self._charging:
                ev_source = self._raw(self.config[CONF_EV_POWER])
                if ev_source is not None:
                    ev_at = (
                        getattr(ev_source, "last_reported", None)
                        or ev_source.last_updated
                    )
                    ev_expires = ev_at + EV_REPORT_AGE + timedelta(seconds=1)
                    if ev_expires > now:
                        choices.append(ev_expires)

        if choices:
            due = max(now + timedelta(seconds=10), min(choices))
            self._timer_unsub = async_track_point_in_utc_time(
                self.hass, self._on_timer, due.astimezone(timezone.utc),
            )

    def _signature(self):
        s, p, d = self.session, self.planning, self.proposal
        if not s or not p or not d:
            return None
        # Avoid Recorder writes on every real-time Shelly reading.
        return (
            s.vehicle_id, s.vehicle_ambiguous, s.charging,
            round(s.soc, 1) if s.soc is not None else None,
            s.target_soc, s.departure_at, p.reason,
            d.state, d.action, d.reason, d.proposed_cap_kw,
            self.advice.action if self.advice else None,
            self.advice.reason if self.advice else None,
            self.control.mode if self.control else None,
            self.control.phase if self.control else None,
            self.control.reason if self.control else None,
            self.rate.source, 
            (round(self.rate.kw * 2) / 2 if self.rate.kw is not None else None),
            self.quality,
        )

    @callback
    def refresh(self):
        now = datetime.now(timezone.utc)
        self.session = self._make_session(now)
        self._observe_house_only_in_charge(self.session.charging)
        self.planning = plan(now, self.session, self.policy)
        # In WAITING, read one snapshot when relevant; subscribe to Shelly
        # changes only if electrical charging is actually confirmed.
        house = (
            self._house() if self.session.vehicle_id
            else HouseSnapshot(None, None, "inactive")
        )
        self.advice = advise_departure(
            now, self.session, self.planning, house,
            busy_threshold_kw=self.policy.trigger_kw,
            minimum_slack_minutes=self.policy.min_slack_minutes,
        )
        supervising_house = (
            house if self.session.charging
            else HouseSnapshot(None, None, "inactive")
        )
        self.state, self.proposal = evaluate(
            now, self.session, supervising_house, self._limits(),
            self.state, self.policy,
        )
        self.quality = (
            "session_requires_confirmation"
            if self.control and self.control.requires_confirmation
            else "connection_unavailable_or_ambiguous"
            if self.control and self.control.phase == "UNKNOWN"
            else self.planning.reason
            if self.planning.reason != "flexible"
            else "house_data_not_trusted" if house.kw is None
            else "ready"
        )
        self.last_evaluation = now
        self._schedule(now, self.proposal)
        signature = self._signature()
        if signature != self._fingerprint:
            self._fingerprint = signature
            for listener in tuple(self._listeners):
                listener()

    @callback
    def choose_mode(self, mode: str) -> None:
        """Change ONLY the internal simulation mode of this EV session.

        This method never dispatches a Home Assistant service to another
        entity and never contacts ESPHome/BLE/the wallbox.
        """
        if self.control is None:
            raise ValueError("no active session")
        self.control = user_select_mode(self.control, mode)
        self.refresh()

    def add_listener(self, listener):
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def start(self):
        keys = (
            CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_TELEMETRY_FRESH,
            CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT, CONF_EV_POWER,
        )
        entities = [self.config[key] for key in keys]
        entities.extend(
            self.config[key] for key in (CONF_SESSION_ENERGY, CONF_SESSION_DURATION)
            if self.config.get(key)
        )
        overrides = self.entry.options.get(CONF_VEHICLE_OVERRIDES, {})
        for vehicle in self.config[CONF_VEHICLES]:
            entities.extend((vehicle[CONF_CABLE], vehicle[CONF_SOC]))
            # An Options Flow may change a car from a fixed target to an HA
            # entity (or replace the entity). Listen only to the effective
            # source, not to an obsolete base configuration value.
            effective = {**vehicle, **overrides.get(vehicle[CONF_CABLE], {})}
            if selected_mode(effective) == "entity" and effective.get(CONF_TARGET_ENTITY):
                entities.append(effective[CONF_TARGET_ENTITY])
        self._base_unsub = async_track_state_change_event(
            self.hass, sorted(set(entities)), self._on_change,
        )
        self.refresh()

    def close(self):
        self._clear_timer()
        self._observe_house_only_in_charge(False)
        if self._base_unsub:
            self._base_unsub()
            self._base_unsub = None
        self._listeners.clear()
