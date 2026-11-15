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
    CONF_VEHICLE_OVERRIDES,
)
from .departure_policy import DepartureAdvice, advise_departure
from .core import (
    Config, CoreState, HouseSnapshot, LimitSnapshot, Proposal,
    SessionSnapshot, evaluate, plan,
)
from .sources import finite_number, next_departure, on, power_kw

# Conservative lab candidates; staleness is not inferred from last_changed.
SHELLY_REPORT_AGE = timedelta(minutes=20)
EV_REPORT_AGE = timedelta(minutes=5)


class SimulationCoordinator:
    """One local wallbox, multiple vehicle profiles, no actuation."""

    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        self.config = dict(entry.data)
        self.policy = Config(dpm_model_kw=float(self.config[CONF_DPM_MODEL]))
        self.state: CoreState | None = None
        self.proposal: Proposal | None = None
        self.planning = None
        self.advice: DepartureAdvice | None = None
        self.session: SessionSnapshot | None = None
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

    def _make_session(self, now: datetime) -> SessionSnapshot:
        present = [v for v in self.config[CONF_VEHICLES] if self._on(v[CONF_CABLE]) is True]
        wallbox_connected = self._on(self.config[CONF_WALLBOX_CONNECTED])
        ambiguous = len(present) > 1 or wallbox_connected is None
        selected = present[0] if len(present) == 1 and wallbox_connected is True else None
        identity = selected[CONF_CABLE] if selected else None
        if selected is not None:
            # Options Flow edits the planner, never the underlying HA entities.
            # Only one vehicle at a time gets an override; keys remain stable.
            per_car = self.entry.options.get(CONF_VEHICLE_OVERRIDES, {})
            selected = {
                **selected,
                **per_car.get(identity, {}),
            }
        if identity != self._vehicle_id:
            self._session_seq += 1
            self._vehicle_id = identity
            self._active_departure = None
            self.state = None
        if selected:
            source = self._raw(selected[CONF_SOC])
            soc = finite_number(source.state) if source else None
            soc_at = ((getattr(source, "last_reported", None) or source.last_updated)
                      if source else None)
            target_id = selected.get(CONF_TARGET_ENTITY)
            target = self._number(target_id) if target_id else float(selected[CONF_TARGET_DEFAULT])
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
        return SessionSnapshot(
            session_id=f"{self.entry.entry_id}:{self._session_seq}", mode="AUTO",
            vehicle_id=identity, vehicle_ambiguous=ambiguous, charging=bool(charging),
            soc=soc, soc_at=soc_at, target_soc=target, departure_at=departure,
            usable_capacity_kwh=(float(selected[CONF_CAPACITY]) if selected else None),
            ac_efficiency=(float(selected[CONF_EFFICIENCY]) if selected else None),
            sustainable_kw=(float(selected[CONF_SUSTAINABLE]) if selected else None),
        )

    def _house(self) -> HouseSnapshot:
        downstairs = self._power(self.config[CONF_DOWNSTAIRS], SHELLY_REPORT_AGE)
        upstairs = self._power(self.config[CONF_UPSTAIRS], SHELLY_REPORT_AGE)
        quality = "ok" if downstairs is not None and upstairs is not None else "unavailable_or_stale"
        return HouseSnapshot(downstairs, upstairs, quality)

    def _limits(self) -> LimitSnapshot:
        return LimitSnapshot(
            self._power(self.config[CONF_REQUESTED_LIMIT]),
            self._power(self.config[CONF_CONFIRMED_LIMIT]),
        )

    def _observe_house_only_in_charge(self, charging: bool) -> None:
        if charging and self._house_unsub is None:
            watch = [self.config[CONF_DOWNSTAIRS], self.config[CONF_UPSTAIRS]]
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
            self.planning.reason
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

    def add_listener(self, listener):
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def start(self):
        keys = (
            CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_TELEMETRY_FRESH,
            CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT, CONF_EV_POWER,
        )
        entities = [self.config[key] for key in keys]
        for vehicle in self.config[CONF_VEHICLES]:
            entities.extend((vehicle[CONF_CABLE], vehicle[CONF_SOC]))
            if vehicle.get(CONF_TARGET_ENTITY):
                entities.append(vehicle[CONF_TARGET_ENTITY])
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
