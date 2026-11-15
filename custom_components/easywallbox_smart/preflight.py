"""Non-destructive, source-independent configuration preflight.

The legacy v0.0.13 layout and the new v0.1 simulation layout cannot be
silently converted: they have different source/vehicle semantics despite
sharing a Home Assistant domain. This module NEVER reads .storage or updates
a config entry. Issues contain public codes, not user entity IDs or secrets.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from .const import (
    CONF_DOWNSTAIRS, CONF_UPSTAIRS, CONF_EV_POWER,
    CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_TELEMETRY_FRESH,
    CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT, CONF_DPM_MODEL,
    CONF_VEHICLES, CONF_NAME, CONF_CABLE, CONF_SOC,
    CONF_TARGET_ENTITY, CONF_TARGET_DEFAULT, CONF_CAPACITY,
    CONF_SUSTAINABLE, CONF_EFFICIENCY,
    CONF_DEPARTURE_WEEKDAY, CONF_DEPARTURE_WEEKEND,
)
from .sources import finite_number

NEW = "new_simulation"
LEGACY = "legacy_0_0_13"
INVALID = "invalid_or_incomplete"

SOURCES = {
    CONF_DOWNSTAIRS: "sensor",
    CONF_UPSTAIRS: "sensor",
    CONF_EV_POWER: "sensor",
    CONF_WALLBOX_CONNECTED: "binary_sensor",
    CONF_WALLBOX_CHARGING: "binary_sensor",
    CONF_TELEMETRY_FRESH: "binary_sensor",
    CONF_REQUESTED_LIMIT: "number",
    CONF_CONFIRMED_LIMIT: "sensor",
}
CLOCK_KEYS = (CONF_DEPARTURE_WEEKDAY, CONF_DEPARTURE_WEEKEND)
NEW_MARKERS = frozenset(SOURCES) | {CONF_DPM_MODEL}
LEGACY_MARKERS = {
    "house_power_sources", "site_total_power", "ev_power_sensor",
    "power_source_mode", "continuous_kw", "power_mode",
}


@dataclass(frozen=True)
class Check:
    kind: str
    issues: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.kind == NEW and not self.issues


def _entity(value: object, expected: str | tuple[str, ...]) -> bool:
    if not isinstance(value, str) or value.count(".") != 1:
        return False
    domain, object_id = value.split(".", 1)
    allowed = (expected,) if isinstance(expected, str) else expected
    return domain in allowed and bool(object_id) and " " not in object_id


def _range(value: object, minimum: float, maximum: float) -> bool:
    number = finite_number(value)
    return number is not None and minimum <= number <= maximum


def _clock(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    h, m = value[:2], value[3:]
    return h.isascii() and m.isascii() and h.isdigit() and m.isdigit() and int(h) < 24 and int(m) < 60


def inspect(data: Mapping | None, options: Mapping | None = None) -> Check:
    """Classify an HA config entry and validate the new read-only mapping.

    Never guesses a migration mapping and never exposes actual entity IDs in
    the result. A partial new config is INVALID even if it has legacy keys.
    """
    if not isinstance(data, Mapping):
        return Check(INVALID, ("data_not_mapping",))
    if not isinstance(options or {}, Mapping):
        return Check(INVALID, ("options_not_mapping",))
    vehicles = data.get(CONF_VEHICLES)
    combined = {**data, **(options or {})}
    old_cars = isinstance(vehicles, list) and any(
        isinstance(v, Mapping) and (
            "connected" in v or "default_target_soc" in v or "id" in v
        ) for v in vehicles
    )
    old_source = bool(LEGACY_MARKERS.intersection(combined))
    new_source = bool(NEW_MARKERS.intersection(data))
    if (old_source or old_cars) and not new_source:
        return Check(LEGACY, ("manual_reconfiguration_required",))
    issues: set[str] = set()
    for key, domain in SOURCES.items():
        if not _entity(data.get(key), domain):
            issues.add("invalid_" + key)
    # Duplicating one Shelly in two roles makes the virtual household model
    # incorrect. No one can safely infer which source is the EV branch.
    sources = [data.get(key) for key in SOURCES]
    if len([v for v in sources if isinstance(v, str)]) != len(set(
        v for v in sources if isinstance(v, str)
    )):
        issues.add("duplicated_source_entity")
    if not _range(data.get(CONF_DPM_MODEL), 1.4, 20.0):
        issues.add("invalid_dpm_model")
    if not isinstance(vehicles, list) or not vehicles:
        issues.add("missing_vehicles")
    else:
        names: set[str] = set()
        cables: set[str] = set()
        soc_ids: set[str] = set()
        for vehicle in vehicles:
            if not isinstance(vehicle, Mapping):
                issues.add("invalid_vehicle_record")
                continue
            name = vehicle.get(CONF_NAME)
            if not isinstance(name, str) or not name.strip():
                issues.add("invalid_vehicle_name")
            elif name.strip().casefold() in names:
                issues.add("duplicated_vehicle_name")
            else:
                names.add(name.strip().casefold())
            cable = vehicle.get(CONF_CABLE)
            if not _entity(cable, "binary_sensor"):
                issues.add("invalid_vehicle_cable")
            elif cable in cables:
                issues.add("duplicated_vehicle_cable")
            else:
                cables.add(cable)
            soc = vehicle.get(CONF_SOC)
            if not _entity(soc, "sensor"):
                issues.add("invalid_vehicle_soc")
            elif soc in soc_ids:
                issues.add("duplicated_vehicle_soc")
            else:
                soc_ids.add(soc)
            target_source = vehicle.get(CONF_TARGET_ENTITY)
            if target_source is not None and not _entity(
                target_source, ("sensor", "number", "input_number")
            ):
                issues.add("invalid_target_source")
            if not _range(vehicle.get(CONF_TARGET_DEFAULT), 1, 100):
                issues.add("invalid_default_target")
            if not _range(vehicle.get(CONF_CAPACITY), 1, 250):
                issues.add("invalid_capacity")
            if not _range(vehicle.get(CONF_SUSTAINABLE), 1.4, 22):
                issues.add("invalid_sustainable_power")
            if not _range(vehicle.get(CONF_EFFICIENCY), 0.5, 1.0):
                issues.add("invalid_ac_efficiency")
            if not all(_clock(vehicle.get(key)) for key in CLOCK_KEYS):
                issues.add("invalid_departure_clock")
        if cables.intersection(sources):
            issues.add("vehicle_cable_matches_wallbox_source")
    if issues:
        return Check(INVALID, tuple(sorted(issues)))
    return Check(NEW)


def is_legacy(data: Mapping | None, options: Mapping | None = None) -> bool:
    return inspect(data, options).kind == LEGACY
