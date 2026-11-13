"""Pure read-only vehicle identification and SOC/energy assessment."""

from dataclasses import dataclass
from math import isfinite

SOC_MAX_AGE = 45 * 60


@dataclass(frozen=True)
class Source:
    """A string state and seconds since the source's latest reported reading."""

    value: str | None
    age_seconds: float | None


@dataclass(frozen=True)
class Snapshot:
    """None means unknown: never silently replace unknown values with zero."""

    vehicle: str | None
    soc: float | None
    target: int | None
    remaining_kwh: float | None
    quality: str


def _fresh(source: Source | None, max_age: float) -> bool:
    return (
        source is not None
        and isinstance(source.value, str)
        and source.age_seconds is not None
        and isfinite(source.age_seconds)
        and -5 <= source.age_seconds <= max_age
        and source.value.lower() not in ("unknown", "unavailable", "none", "")
    )


def _binary(source: Source | None) -> bool | None:
    """A persistent ON/OFF state does not expire merely because it is unchanged.

    Availability and stateful watchdogs are the source of truth.
    Numeric telemetry such as SOC is checked for age separately.
    """
    if source is None or not isinstance(source.value, str):
        return None
    value = source.value.lower()
    if value in ("on", "true", "connected"):
        return True
    if value in ("off", "false", "disconnected"):
        return False
    return None


def telemetry_diagnostic(source: Source | None) -> str:
    """Explain the ESPHome watchdog without inventing a time-based timeout."""
    if source is None or source.value is None:
        return "entity_not_found"
    if not isinstance(source.value, str):
        return "unexpected_state"
    if source.value.lower() in ("unknown", "unavailable", "none", ""):
        return "entity_unavailable"
    if _binary(source) is True:
        return "watchdog_on"
    if _binary(source) is False:
        return "telemetry_off"
    return "unexpected_state"


def _soc(source: Source | None) -> tuple[float | None, str]:
    if not _fresh(source, SOC_MAX_AGE):
        return None, "soc_missing_or_stale"
    try:
        val = float(source.value)
    except (TypeError, ValueError):
        return None, "soc_invalid"
    if not isfinite(val) or not 0 <= val <= 100:
        return None, "soc_invalid"
    return val, "ok"


def assess(config: dict, states: dict[str, Source]) -> Snapshot:
    """Require a wallbox connection and exactly one known connected vehicle.

    An unknown status on ANY configured vehicle can hide a second car, so do
    not guess. Estimates are battery-side kWh, without charging losses.
    """
    def unknown(reason: str) -> Snapshot:
        return Snapshot(None, None, None, None, reason)

    profiles = config.get("vehicles")
    if not isinstance(profiles, list) or not profiles:
        return unknown("no_vehicle_profiles")
    wallbox_id = config.get("wallbox_car_connected")
    if not wallbox_id:
        return unknown("wallbox_connection_unconfigured")
    freshness_id = config.get("wallbox_telemetry_fresh")
    if freshness_id and _binary(states.get(freshness_id)) is not True:
        return unknown("wallbox_telemetry_unavailable")
    plugged = _binary(states.get(wallbox_id))
    if plugged is None:
        return unknown("wallbox_connection_unavailable")
    if not plugged:
        return unknown("no_vehicle_at_wallbox")

    matches = []
    for profile in profiles:
        connected = _binary(states.get(profile.get("connected", "")))
        if connected is None:
            return unknown("vehicle_connection_unavailable")
        if connected:
            matches.append(profile)
    if len(matches) > 1:
        return unknown("ambiguous_vehicle")
    if not matches:
        return unknown("vehicle_not_identified")
    car = matches[0]
    name, target = car.get("name"), car.get("default_target_soc")
    if (
        not isinstance(name, str) or not name.strip()
        or isinstance(target, bool) or not isinstance(target, int)
        or not 1 <= target <= 100
    ):
        return unknown("invalid_vehicle_configuration")
    try:
        capacity = float(car.get("capacity_kwh"))
    except (ValueError, TypeError):
        return unknown("invalid_vehicle_configuration")
    if not isfinite(capacity) or not 1 <= capacity <= 250:
        return unknown("invalid_vehicle_configuration")

    soc, reason = _soc(states.get(car.get("soc", "")))
    if soc is None:
        return Snapshot(name, None, target, None, reason)
    energy = round(max(0.0, (target - soc) * capacity / 100), 2)
    return Snapshot(name, round(soc, 1), target, energy, "ok")
