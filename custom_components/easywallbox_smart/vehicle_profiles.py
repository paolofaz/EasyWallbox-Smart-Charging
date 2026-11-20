"""Pure helpers for editing complete vehicle profiles after installation."""
from __future__ import annotations


LEGACY_RATE = "planning_rate_kw"


def clean_vehicle(vehicle: dict) -> dict:
    """Drop superseded per-car manual average; retain unknown metadata."""
    result = dict(vehicle)
    result.pop(LEGACY_RATE, None)
    return result


def configured_vehicles(data: dict, options: dict) -> list[dict]:
    """Read latest full vehicle list; also recognize older schedule-only options."""
    current = options.get("vehicles", data.get("vehicles", []))
    overrides = options.get("vehicle_schedules", {})
    return [
        {**clean_vehicle(car), **overrides.get(car["cable"], {})}
        for car in current
    ]


def valid_car(car: dict) -> bool:
    if not (isinstance(car.get("name"), str) and car["name"].strip()
            and isinstance(car.get("cable"), str) and car["cable"]
            and isinstance(car.get("soc"), str) and car["soc"]):
        return False
    has_entity = bool(car.get("target_entity"))
    has_fixed = car.get("target_fixed") is not None
    if has_entity == has_fixed:
        return False
    try:
        if has_fixed and not 1 <= float(car["target_fixed"]) <= 100:
            return False
        if not 10 <= float(car["capacity_kwh"]) <= 200:
            return False
        if not 0.5 <= float(car["efficiency"]) <= 1.0:
            return False
    except (TypeError, ValueError, KeyError):
        return False
    return True


def upsert_vehicle(vehicles: list[dict], candidate: dict,
                   original_cable: str | None = None) -> list[dict]:
    """Insert/update by original cable, checking uniqueness across the fleet."""
    new_car = clean_vehicle(candidate)
    if not valid_car(new_car):
        raise ValueError("invalid_vehicle")
    old = [clean_vehicle(car) for car in vehicles]
    if original_cable is not None and not any(
            car["cable"] == original_cable for car in old):
        raise ValueError("vehicle_missing")
    other = [car for car in old if car["cable"] != original_cable]
    if any(car["cable"] == new_car["cable"]
           or car["name"].strip().casefold() == new_car["name"].strip().casefold()
           for car in other):
        raise ValueError("duplicate_vehicle")
    if original_cable is None:
        return other + [new_car]
    return [
        new_car if car["cable"] == original_cable else car for car in old
    ]


def remove_vehicle(vehicles: list[dict], cable: str) -> list[dict]:
    if len(vehicles) <= 1:
        raise ValueError("cannot_remove_last")
    if not any(car["cable"] == cable for car in vehicles):
        raise ValueError("vehicle_missing")
    return [clean_vehicle(car) for car in vehicles if car["cable"] != cable]
