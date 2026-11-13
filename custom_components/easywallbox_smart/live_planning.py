"""Passive HA adapter: compute provisional previews from configured entities."""

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from math import isfinite

from .planner import DepartureDemand, Plan, Request, departure_demand, plan
from .power_model import Reading, calculate, migrate_legacy
from .schedule import next_departure

FRESH_SECONDS = 300
ASSUMED_EFFICIENCY = 0.90
ASSUMED_RESERVE_MINUTES = 45


@dataclass(frozen=True)
class Preview:
    status: str
    reason: str
    departure: datetime | None
    house_kw: float | None
    power_quality: str
    result: Plan | None
    demand: DepartureDemand | None = None


@dataclass(frozen=True)
class DemoSOC:
    quality: str
    remaining_kwh: float


def dependency_ids(config: dict) -> set[str]:
    """Only read explicitly configured HA power sensors."""
    result = set()
    house = config.get("house_power_sources", [])
    if isinstance(house, list):
        result.update(v for v in house if isinstance(v, str) and v)
    for key in ("site_total_power", "ev_power_sensor"):
        value = config.get(key)
        if isinstance(value, str) and value:
            result.add(value)
    return result


def evaluate(hass, config: dict, snapshot, now: datetime | None = None) -> Preview:
    """Report independent site data even if vehicle/telemetry is unavailable.

    No missing or stale reading is silently interpreted as zero watts.
    """
    try:
        zone = ZoneInfo(hass.config.time_zone)
        current = (now or datetime.now(timezone.utc)).astimezone(zone)
    except (ValueError, TypeError, KeyError):
        return Preview("unavailable", "invalid_timezone", None, None,
                       "not_evaluated", None)

    readings = {}
    for entity_id in dependency_ids(config):
        state = hass.states.get(entity_id)
        if state is None:
            continue
        stamp = getattr(state, "last_reported", None) or state.last_updated
        age = (current.astimezone(timezone.utc) - stamp).total_seconds()
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            value = None
        readings[entity_id] = Reading(
            value, state.attributes.get("unit_of_measurement", ""),
            0 <= age <= FRESH_SECONDS,
        )
    topology = {**config, **migrate_legacy(config)}
    power = calculate(topology, readings)
    house_kw = round(power.house_kw, 3) if power.house_kw is not None else None

    required = ("continuous_kw", "departure_weekday", "departure_weekend")
    if not all(config.get(key) is not None for key in required):
        return Preview("unconfigured", "planning_options_required",
                       None, house_kw, power.quality, None)
    try:
        departure = next_departure(
            current, config["departure_weekday"], config["departure_weekend"]
        )
        capacity = float(config["continuous_kw"])
        if not isfinite(capacity) or capacity <= 0:
            raise ValueError("invalid_capacity")
    except (ValueError, TypeError, KeyError):
        return Preview("unavailable", "invalid_planning_options",
                       None, house_kw, power.quality, None)

    # Demand is independent of current domestic load. This is a useful
    # deadline metric even when power sensors are unknown or house is busy.
    if snapshot.quality != "ok" or snapshot.remaining_kwh is None:
        return Preview("unavailable", "vehicle_" + snapshot.quality,
                       departure, house_kw, power.quality, None)
    demand = departure_demand(
        current, departure, snapshot.remaining_kwh,
        ASSUMED_EFFICIENCY, ASSUMED_RESERVE_MINUTES,
    )
    if demand.status != "ok" and demand.status != "target_estimated_reached":
        return Preview("unavailable", "deadline_" + demand.status,
                       departure, house_kw, power.quality, None, demand)
    if (
        demand.required_grid_kw is not None
        and demand.required_grid_kw > capacity
    ):
        return Preview(
            "deadline_unreachable_even_without_house_load",
            "required_average_exceeds_site_limit",
            departure, house_kw, power.quality, None, demand,
        )
    if power.house_kw is None:
        return Preview("unavailable", "house_power_" + power.quality,
                       departure, None, power.quality, None, demand)

    # ONLY a hypothetical scenario: current house load remains constant.
    # This is not a forecast of the actual future household demand.
    estimate = plan(Request(
        now=current, departure=departure,
        battery_kwh=snapshot.remaining_kwh,
        continuous_kw=capacity,
        house_reference_kw=power.house_kw,
        vehicle_cap_kw=capacity,
        efficiency=ASSUMED_EFFICIENCY,
        reserve_minutes=ASSUMED_RESERVE_MINUTES,
    ))
    if estimate.status == "feasible_estimate":
        status = "current_load_scenario_feasible"
    elif estimate.status == "deadline_at_risk":
        status = "current_load_scenario_at_risk"
    else:
        status = estimate.status
    return Preview(
        status, estimate.reason,
        departure, house_kw, power.quality, estimate, demand,
    )


def demo_scenarios(hass, config: dict, now: datetime | None = None) -> list[dict]:
    """Preview every configured car at hypothetical 30% SOC, even unplugged."""
    scenarios = []
    for vehicle in config.get("vehicles", []):
        try:
            capacity = float(vehicle["capacity_kwh"])
            target = int(vehicle["default_target_soc"])
            name = vehicle["name"]
            if (not isfinite(capacity) or capacity <= 0
                or not 1 <= target <= 100
                or not isinstance(name, str) or not name):
                continue
        except (ValueError, TypeError, KeyError):
            continue
        battery_kwh = round(max(0, target - 30) / 100 * capacity, 2)
        preview = evaluate(hass, config, DemoSOC("ok", battery_kwh), now)
        prediction = preview.result
        scenarios.append({
            "vehicle": name,
            "scenario_soc": 30,
            "target_soc": target,
            "battery_kwh_needed": battery_kwh,
            "status": preview.status,
            "reason": preview.reason,
            "house_reference_kw": preview.house_kw,
            "estimated_ev_kw": (
                prediction.estimated_ev_kw if prediction else None
            ),
            "estimated_hours": (
                prediction.required_hours if prediction else None
            ),
            "required_mean_grid_kw": (
                preview.demand.required_grid_kw
                if preview.demand else None
            ),
            "recommended_start": (
                prediction.recommended_start.isoformat()
                if prediction and prediction.recommended_start else None
            ),
            "estimated_finish": (
                prediction.estimated_finish.isoformat()
                if prediction and prediction.estimated_finish else None
            ),
            "departure": (
                preview.departure.isoformat() if preview.departure else None
            ),
        })
    return scenarios
