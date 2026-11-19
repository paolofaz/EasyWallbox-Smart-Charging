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
    CONF_SESSION_ENERGY, CONF_SESSION_DURATION, CONF_DPM_CONFIRMED,
    CONF_INITIAL_CHARGE_KW, CONF_MAX_CHARGE_KW, CONF_SHADOW_LAB_ENABLED,
    DEFAULT_INITIAL_CHARGE_KW, DEFAULT_MAX_CHARGE_KW,
)
from .departure_policy import DepartureAdvice, advise_departure
from .session_policy import SessionControl, observe, user_select_mode
from .core import (
    Config, CoreState, HouseSnapshot, LimitSnapshot, Proposal,
    SessionSnapshot, plan,
)
from .sources import finite_number, next_departure, on, power_kw
from .rate_estimator import RateState, RateEstimate, estimate
from .target_policy import resolved_target, selected_mode
from .johnny_policy import JohnnyState, evaluate, margin_band, HOUSE_LOSS_RESTORE_MINUTES
from .shadow_lab import simulate_shadow, simulate_shadow_v2
from .shadow_log import ShadowLogSampler, append_shadow_rows

# Conservative lab candidates; staleness is not inferred from last_changed.
SHELLY_REPORT_AGE = timedelta(minutes=3)
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
        for field in (CONF_HOUSE_SOURCES, CONF_SESSION_ENERGY, CONF_SESSION_DURATION, CONF_DPM_CONFIRMED):
            if field in entry.options:
                self.config[field] = entry.options[field]
        self.house_sources = self.config.get(
            CONF_HOUSE_SOURCES,
            [self.config.get(CONF_DOWNSTAIRS), self.config.get(CONF_UPSTAIRS)],
        )
        self.policy = Config(dpm_model_kw=float(entry.options.get(
            CONF_DPM_MODEL, self.config[CONF_DPM_MODEL]
        )))
        self.state: JohnnyState | None = None
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
        self.margin_band = "unknown"
        self.dpm_limit_kw: float | None = None
        self.dpm_pressure_kw: float | None = None
        self.dpm_limit_source = "sensor" if self.config.get(CONF_DPM_CONFIRMED) else "simulation_model"
        self.last_evaluation: datetime | None = None
        # A separate, deliberately unbounded fake EV session in each band.
        # Defaults to OFF; no disk writes without explicit opt-in.
        self.shadow_enabled = bool(entry.options.get(
            CONF_SHADOW_LAB_ENABLED, False))
        self.initial_charge_kw = float(entry.options.get(
            CONF_INITIAL_CHARGE_KW, self.config.get(
                CONF_INITIAL_CHARGE_KW, DEFAULT_INITIAL_CHARGE_KW)))
        self.max_charge_kw = float(entry.options.get(
            CONF_MAX_CHARGE_KW, self.config.get(
                CONF_MAX_CHARGE_KW, DEFAULT_MAX_CHARGE_KW)))
        self.shadow_states = {}
        self.shadow_decisions = {}
        self.shadow_v2_state = None
        self.shadow_v2_decision = None
        self.shadow_dpm_source = None
        self._shadow_last_positive_dpm = None
        self.shadow_log_status = "disabled" if not self.shadow_enabled else "starting"
        self.shadow_log_file = None
        self.shadow_logged_rows = 0
        self._shadow_log_sampler = ShadowLogSampler(interval_seconds=60)
        self._shadow_rows = []
        self._shadow_flush_task = None
        self.shadow_run_started_at = datetime.now(timezone.utc).astimezone(
            ZoneInfo(self.hass.config.time_zone)
        ).isoformat(timespec="seconds")

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
            # Keep last virtual state until evaluate() can mark a cap
            # from the old EV session for reconciliation. Never inherit it.
        elif identity is not None and identity != self._vehicle_id:
            self._session_seq += 1
            self._vehicle_id = identity
            self._active_departure = None
            # The pure policy fences the old cap on the session-ID change.
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
            wallbox_telemetry_fresh=self._on(self.config[CONF_TELEMETRY_FRESH]),
        )

    def _house(self) -> HouseSnapshot:
        """Composite Shelly snapshot; timer callbacks cannot forge a new report."""
        sources = []
        timestamps = []
        for entity_id in self.house_sources:
            source = self._raw(entity_id)
            sources.append(self._power(entity_id, SHELLY_REPORT_AGE))
            if source is not None:
                timestamp = (
                    getattr(source, "last_reported", None) or source.last_updated
                )
                if timestamp is not None:
                    timestamps.append(timestamp)
        trusted = (bool(sources) and len(timestamps) == len(sources)
                   and all(v is not None for v in sources))
        return HouseSnapshot(
            None, None, "ok" if trusted else "unavailable_or_stale",
            sources_kw=tuple(sources),
            observed_at=max(timestamps) if trusted else None,
        )

    def _limits(self) -> LimitSnapshot:
        """Use the observed DPM value if configured; never silently fall back."""
        dpm_entity = self.config.get(CONF_DPM_CONFIRMED)
        dpm_kw = (
            self._power(dpm_entity, COUNTER_REPORT_AGE) if dpm_entity
            else self.policy.dpm_model_kw  # explicit simulation model only
        )
        return LimitSnapshot(
            self._power(self.config[CONF_REQUESTED_LIMIT]),
            self._power(self.config[CONF_CONFIRMED_LIMIT], COUNTER_REPORT_AGE),
            dpm_kw=dpm_kw,
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

        if self.shadow_enabled:
            # The real car can be unplugged: lab timers and household
            # subscriptions continue independently, event-driven.
            for band in ("wide", "medium"):
                prop = self.shadow_decisions.get(band)
                state = self.shadow_states.get(band)
                if prop and prop.next_check_at and prop.next_check_at > now:
                    choices.append(prop.next_check_at)
                if state and state.mode == "LIMITED" and state.last_good_house_at:
                    limit = (state.last_good_house_at +
                             timedelta(minutes=HOUSE_LOSS_RESTORE_MINUTES,
                                       seconds=1))
                    if limit > now:
                        choices.append(limit)
            if (self.shadow_v2_state is not None
                    and self.shadow_v2_state.mode == "LIMITED"
                    and self.shadow_v2_state.last_good_at is not None):
                due = (self.shadow_v2_state.last_good_at
                       + timedelta(minutes=8, seconds=1))
                if due > now:
                    choices.append(due)
            for entity_id in self.house_sources:
                src = self._raw(entity_id)
                if src is not None:
                    reported = getattr(src, "last_reported", None) or src.last_updated
                    if reported is not None:
                        due = reported + SHELLY_REPORT_AGE + timedelta(seconds=1)
                        if due > now:
                            choices.append(due)

        if self._charging:
            if proposal.next_check_at and proposal.next_check_at > now:
                choices.append(proposal.next_check_at)
            if self.state and self.state.mode == "LIMITED" and self.planning:
                cap, original = self.state.cap_kw, self.state.original_kw
                if cap is not None and original is not None and original > cap:
                    budget_left = (
                        (self.state.locked_budget_kwh or 0)
                        - self.state.spent_kwh_upper_bound
                    )
                    if budget_left > 0:
                        choices.append(
                            now + timedelta(hours=budget_left / (original - cap))
                        )
            # The Shelly must not look fresh forever if it stops sending
            # events. Re-evaluate once the trusted report actually expires.
            # While LIMITED, also enforce Johnny's bounded missing-data
            # recovery even without a new Home Assistant event.
            for entity_id in self.house_sources:
                source = self._raw(entity_id)
                if source is None:
                    continue
                reported = getattr(source, "last_reported", None) or source.last_updated
                if reported is None:
                    continue
                expires = reported + SHELLY_REPORT_AGE + timedelta(seconds=1)
                if expires > now:
                    choices.append(expires)
            if (self.state and self.state.mode == "LIMITED"
                    and self.state.last_good_house_at is not None):
                recovery = self.state.last_good_house_at + timedelta(
                    minutes=HOUSE_LOSS_RESTORE_MINUTES, seconds=1
                )
                if recovery > now:
                    choices.append(recovery)
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
            margin_band(p),
            self.dpm_limit_kw,
            self.rate.source,
            (round(self.rate.kw * 2) / 2 if self.rate.kw is not None else None),
            self.quality,
            self.shadow_enabled,
            tuple((band,
                   self.shadow_decisions[band].action,
                   self.shadow_decisions[band].reason,
                   self.shadow_decisions[band].proposed_cap_kw)
                  for band in ("wide", "medium")
                  if band in self.shadow_decisions),
            (
                self.shadow_v2_state.mode,
                self.shadow_v2_state.kind,
                self.shadow_v2_decision.action,
                self.shadow_v2_decision.proposed_cap_kw,
                self.shadow_v2_state.last_transition_reason,
            ) if self.shadow_v2_state and self.shadow_v2_decision else None,
            self.shadow_log_status,
        )

    @callback
    def refresh(self):
        now = datetime.now(timezone.utc)
        self.session = self._make_session(now)
        self._observe_house_only_in_charge(
            self.session.charging or self.shadow_enabled
        )
        self.planning = plan(now, self.session, self.policy)
        self.margin_band = margin_band(self.planning)
        # In WAITING, read one snapshot when relevant; subscribe to Shelly
        # changes only if electrical charging is actually confirmed.
        house = (
            self._house() if self.session.vehicle_id or self.shadow_enabled
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
        limits = self._limits()
        # DPM=0 is the wallbox pause method, NOT a 0 kW household ceiling
        # and never permission for an automatic BLE resume. We currently
        # cannot know whether a pause was initiated by the user or planner.
        if (self.session.vehicle_id and self.session.mode == "AUTO"
                and limits.dpm_kw == 0 and not self.session.charging):
            self.advice = DepartureAdvice(
                "insufficient_data", "dpm_zero_pause_origin_unverified"
            )
        self.dpm_limit_kw = limits.dpm_kw
        house_kw = supervising_house.kw
        self.dpm_pressure_kw = (
            max(0.0, house_kw + limits.confirmed_kw - limits.dpm_kw)
            if house_kw is not None and limits.confirmed_kw is not None
            and limits.dpm_kw is not None else None
        )
        self.state, self.proposal = evaluate(
            now, self.session, supervising_house, limits,
            self.state, self.policy,
        )
        self.quality = (
            "session_requires_confirmation"
            if self.control and self.control.requires_confirmation
            else "connection_unavailable_or_ambiguous"
            if self.control and self.control.phase == "UNKNOWN"
            else "dpm_zero_pause_origin_unverified"
            if self.session.vehicle_id and limits.dpm_kw == 0
            else self.planning.reason
            if self.planning.reason != "flexible"
            else "house_data_not_trusted" if house.kw is None
            else "ready"
        )
        self.last_evaluation = now
        if self.shadow_enabled:
            self._refresh_shadow(now, house, limits)
        self._schedule(now, self.proposal)
        signature = self._signature()
        if signature != self._fingerprint:
            self._fingerprint = signature
            for listener in tuple(self._listeners):
                listener()

    def _refresh_shadow(self, now: datetime, house: HouseSnapshot,
                        limits: LimitSnapshot) -> None:
        """Evaluate both hypothetical EVs even with the cable unplugged."""
        if limits.dpm_kw is not None and limits.dpm_kw > 0:
            effective_dpm = limits.dpm_kw
            self._shadow_last_positive_dpm = effective_dpm
            origin = ("confirmed_sensor" if self.config.get(CONF_DPM_CONFIRMED)
                      else "configured_model")
        elif self._shadow_last_positive_dpm is not None:
            effective_dpm = self._shadow_last_positive_dpm
            origin = "last_positive_confirmed_this_run"
        else:
            effective_dpm = self.policy.dpm_model_kw
            origin = "explicit_model_when_paused_or_unavailable"
        self.shadow_dpm_source = origin
        starting_new_virtual_run = not bool(self.shadow_states)
        self.shadow_states, self.shadow_decisions = simulate_shadow(
            now, house, effective_dpm, self.max_charge_kw, self.shadow_states,
        )
        self.shadow_v2_state, self.shadow_v2_decision = simulate_shadow_v2(
            now, house, effective_dpm, self.max_charge_kw,
            self.shadow_v2_state,
        )
        sample = house.observed_at if house.kw is not None else None
        # Meaningful policy transitions only. A changing 'hold' explanation
        # is still preserved in the minute summary, not as another disk row.
        decision_signature = tuple(
            (band, self.shadow_decisions[band].action,
             self.shadow_states[band].mode,
             self.shadow_decisions[band].proposed_cap_kw,
             self.shadow_states[band].last_transition_reason)
            for band in ("wide", "medium")
        ) + (("v2", self.shadow_v2_decision.action,
              self.shadow_v2_state.mode,
              self.shadow_v2_decision.proposed_cap_kw,
              self.shadow_v2_state.kind,
              self.shadow_v2_state.last_transition_reason),)
        record = {
            "time_local": now.astimezone(
                ZoneInfo(self.hass.config.time_zone)).isoformat(timespec="seconds"),
            "model": "continuous_three_candidate_no_real_vehicle", 
            "session_budget": "disabled_only_for_infinite_ev_lab",
            "shadow_run_started_local": self.shadow_run_started_at,
            "virtual_state_reset_on_this_row": starting_new_virtual_run,
            "house_report_local": (
                sample.astimezone(ZoneInfo(self.hass.config.time_zone))
                .isoformat(timespec="seconds") if sample is not None else None
            ),
            "house_kw": round(house.kw, 3) if house.kw is not None else None,
            "house_data_quality": house.quality,
            "dpm_observed_kw": limits.dpm_kw,
            "dpm_model_kw": round(effective_dpm, 3),
            "dpm_model_source": origin,
            "ev_baseline_kw": self.max_charge_kw,
            "wide": self._shadow_summary("wide"),
            "medium": self._shadow_summary("medium"),
            "v2": {
                "action": self.shadow_v2_decision.action,
                "reason": self.shadow_v2_decision.reason,
                "state": self.shadow_v2_state.mode,
                "kind": self.shadow_v2_state.kind,
                "cap_kw": self.shadow_v2_decision.proposed_cap_kw,
                "adjustments": self.shadow_v2_state.recheck_count,
                "last_event": self.shadow_v2_state.last_transition_reason,
            },
        }
        row = self._shadow_log_sampler.observe(
            now, sample, record, decision_signature,
        )
        if row is not None:
            self._queue_shadow_row(row)

    def _queue_shadow_row(self, record: dict) -> None:
        self._shadow_rows.append(record)
        if self._shadow_flush_task is None or self._shadow_flush_task.done():
            self._shadow_flush_task = self.entry.async_create_background_task(
                self.hass, self._flush_shadow(), "EasyWallbox shadow JSONL",
            )

    def _shadow_summary(self, band: str) -> dict:
        decision = self.shadow_decisions[band]
        state = self.shadow_states[band]
        return {
            "action": decision.action, "reason": decision.reason,
            "state": state.mode, "cap_kw": decision.proposed_cap_kw,
            "last_event": state.last_transition_reason,
        }

    async def _flush_shadow(self) -> None:
        """One serialized disk writer, always off the HA event loop."""
        try:
            # A single worker drains pending rows, preserving chronological
            # order and avoiding concurrent append operations across events.
            while self._shadow_rows:
                batch, self._shadow_rows = self._shadow_rows, []
                root = self.hass.config.path("easywallbox_smart_shadow")
                count, last_file = await self.hass.async_add_executor_job(
                    append_shadow_rows, root, batch, "shadow_v2",
                )
                self.shadow_logged_rows += count
                self.shadow_log_file = last_file
                self.shadow_log_status = "ok"
        except (OSError, ValueError, TypeError) as error:
            # No unbounded backlog if the HA config volume is read-only/full.
            self._shadow_rows.clear()
            self.shadow_log_status = "error_" + type(error).__name__

    async def async_close(self) -> None:
        """Drain a final partial minute and finish disk I/O on unload."""
        self.close()
        if self.shadow_enabled:
            final_at = datetime.now(timezone.utc).astimezone(
                ZoneInfo(self.hass.config.time_zone))
            final_row = self._shadow_log_sampler.finish(final_at)
            if final_row is not None:
                self._shadow_rows.append(final_row)
        if self._shadow_flush_task is not None:
            await self._shadow_flush_task
        if self._shadow_rows:
            await self._flush_shadow()

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
        if self.config.get(CONF_DPM_CONFIRMED):
            entities.append(self.config[CONF_DPM_CONFIRMED])
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
