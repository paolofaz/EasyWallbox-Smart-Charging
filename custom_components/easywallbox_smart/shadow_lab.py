"""Dual-band, infinite-car read-only laboratory for live household Shelly samples.

Never receives actual EV charging flags, SOC, vehicle IDs or electrical commands.
The budget is deliberately unlimited in this *diagnostic* model: comparing two
margin bands continuously over days would otherwise exhaust the fake session.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from math import isfinite

from .core import Config, HouseSnapshot, LimitSnapshot, SessionSnapshot
from .johnny_policy import JohnnyState, evaluate

SHADOW_SLACK_MINUTES = {"wide": 180, "medium": 90}
SHADOW_UNBOUNDED_BUDGET_KWH = 1_000_000.0


def simulate_shadow(
    now: datetime, house: HouseSnapshot, dpm_kw: float,
    max_ev_kw: float, previous: dict[str, JohnnyState] | None = None,
) -> tuple[dict[str, JohnnyState], dict]:
    """Return (two persistent virtual states, two proposals); no I/O.

    Synthetic battery SOC is *fixed*, its departure moves with now and is
    never compared to actual car data. 4 kWh is assumed remaining so that
    the slack bands stay wide/medium for every minute of the field trial.
    """
    if (not isinstance(max_ev_kw, (int, float)) or isinstance(max_ev_kw, bool)
            or not isfinite(max_ev_kw) or max_ev_kw < 1.4
            or not isinstance(dpm_kw, (int, float))
            or isinstance(dpm_kw, bool) or not isfinite(dpm_kw) or dpm_kw <= 0):
        raise ValueError("shadow input requires a positive model and EV limit")
    states, proposals = {}, {}
    for band, slack in SHADOW_SLACK_MINUTES.items():
        session = SessionSnapshot(
            session_id=f"shadow-continuous-{band}",
            mode="AUTO", vehicle_id=f"synthetic-{band}",
            vehicle_ambiguous=False, charging=True,
            soc=70., soc_at=now, target_soc=80.,
            departure_at=now + timedelta(
                minutes=30 + (4.0 / max_ev_kw * 60) + slack
            ),
            usable_capacity_kwh=36., ac_efficiency=.90,
            sustainable_kw=max_ev_kw,
            wallbox_reports_charging=True,
            wallbox_telemetry_fresh=True,
        )
        old = (previous or {}).get(band)
        if old is None:
            old = JohnnyState(session_id=session.session_id,
                              locked_budget_kwh=SHADOW_UNBOUNDED_BUDGET_KWH)
        state, proposal = evaluate(
            now, session, house,
            LimitSnapshot(requested_kw=max_ev_kw, confirmed_kw=max_ev_kw,
                          dpm_kw=dpm_kw),
            old, Config(dpm_model_kw=dpm_kw),
        )
        states[band] = state
        proposals[band] = proposal
    return states, proposals
