"""Validation for new EasyWallbox Smart Charging configurations only.

The integration is installed afresh. No legacy version handling, migration,
Home Assistant imports, device access or storage writes live in this module.
Issues contain field codes, not user-provided names or entity IDs.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .const import (
    CONF_DOWNSTAIRS, CONF_UPSTAIRS, CONF_EV_POWER,
    CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_TELEMETRY_FRESH,
    CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT, CONF_DPM_MODEL,
    CONF_VEHICLES, CONF_NAME, CONF_CABLE, CONF_SOC,
    CONF_TARGET_ENTITY, CONF_TARGET_DEFAULT, CONF_CAPACITY,
    CONF_SUSTAINABLE, CONF_EFFICIENCY, CONF_VEHICLE_OVERRIDES,
    CONF_DEPARTURE_WEEKDAY, CONF_DEPARTURE_WEEKEND,
)
from .sources import finite_number

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
OPTION_KEYS = frozenset({
    CONF_TARGET_DEFAULT, CONF_DEPARTURE_WEEKDAY, CONF_DEPARTURE_WEEKEND,
    CONF_SUSTAINABLE, CONF_EFFICIENCY,
})


@dataclass(frozen=True)
class Validation:
    issues: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.issues


def _entity(value: object, expected: str | tuple[str, ...]) -> bool:
    if not isinstance(value, str) or value.count(".") != 1:
        return False
    domain, entity = value.split(".", 1)
    allowed = (expected,) if isinstance(expected, str) else expected
    return domain in allowed and bool(entity) and " " not in entity


def _range(value: object, low: float, high: float) -> bool:
    number = finite_number(value)
    return number is not None and low <= number <= high


def _clock(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    hour, minute = value[:2], value[3:]
    return (hour.isascii() and minute.isascii() and hour.isdigit()
            and minute.isdigit() and int(hour) < 24 and int(minute) < 60)


def validate(data: Mapping | None, options: Mapping | None = None) -> Validation:
    """Validate one *fresh* config entry and its per-car optional overrides.

    The UI enforces basic selector types; this additional check rejects
    incomplete or inconsistent persisted data without guessing missing fields.
    """
    if not isinstance(data, Mapping):
        return Validation(("data_not_mapping",))
    if options is None:
        options = {}
    if not isinstance(options, Mapping):
        return Validation(("options_not_mapping",))
    issues: set[str] = set()
    for field, domain in SOURCES.items():
        if not _entity(data.get(field), domain):
            issues.add("invalid_" + field)
    # Distinct physical channels must not be counted twice.
    source_ids = [data.get(key) for key in SOURCES]
    known = [x for x in source_ids if isinstance(x, str)]
    if len(known) != len(set(known)):
        issues.add("duplicated_source_entity")
    if not _range(data.get(CONF_DPM_MODEL), 1.4, 20.0):
        issues.add("invalid_dpm_model")

    cars = data.get(CONF_VEHICLES)
    cables: set[str] = set()
    names: set[str] = set()
    soc_ids: set[str] = set()
    if not isinstance(cars, list) or not cars:
        issues.add("missing_vehicles")
    else:
        for car in cars:
            if not isinstance(car, Mapping):
                issues.add("invalid_vehicle_record")
                continue
            name = car.get(CONF_NAME)
            if not isinstance(name, str) or not name.strip():
                issues.add("invalid_vehicle_name")
            elif name.strip().casefold() in names:
                issues.add("duplicated_vehicle_name")
            else:
                names.add(name.strip().casefold())
            cable = car.get(CONF_CABLE)
            if not _entity(cable, "binary_sensor"):
                issues.add("invalid_vehicle_cable")
            elif cable in cables:
                issues.add("duplicated_vehicle_cable")
            else:
                cables.add(cable)
            soc = car.get(CONF_SOC)
            if not _entity(soc, "sensor"):
                issues.add("invalid_vehicle_soc")
            elif soc in soc_ids:
                issues.add("duplicated_vehicle_soc")
            else:
                soc_ids.add(soc)
            target = car.get(CONF_TARGET_ENTITY)
            if target is not None and not _entity(
                target, ("sensor", "number", "input_number")
            ):
                issues.add("invalid_target_source")
            if not _range(car.get(CONF_TARGET_DEFAULT), 1, 100):
                issues.add("invalid_default_target")
            if not _range(car.get(CONF_CAPACITY), 10, 200):
                issues.add("invalid_capacity")
            if not _range(car.get(CONF_SUSTAINABLE), 1.4, 22.0):
                issues.add("invalid_sustainable_power")
            if not _range(car.get(CONF_EFFICIENCY), 0.5, 1.0):
                issues.add("invalid_ac_efficiency")
            if not all(_clock(car.get(key)) for key in CLOCK_KEYS):
                issues.add("invalid_departure_clock")
    if cables.intersection(known):
        issues.add("vehicle_cable_matches_wallbox_source")
    overrides = options.get(CONF_VEHICLE_OVERRIDES, {})
    if not isinstance(overrides, Mapping):
        issues.add("invalid_overrides")
    else:
        for cable, settings in overrides.items():
            if cable not in cables or not isinstance(settings, Mapping):
                issues.add("invalid_override_vehicle")
                continue
            if set(settings).difference(OPTION_KEYS):
                issues.add("unknown_override_fields")
            if (CONF_TARGET_DEFAULT in settings
                    and not _range(settings[CONF_TARGET_DEFAULT], 1, 100)):
                issues.add("invalid_override_target")
            if (CONF_SUSTAINABLE in settings
                    and not _range(settings[CONF_SUSTAINABLE], 1.4, 22)):
                issues.add("invalid_override_power")
            if (CONF_EFFICIENCY in settings
                    and not _range(settings[CONF_EFFICIENCY], 0.5, 1)):
                issues.add("invalid_override_efficiency")
            if any(key in settings and not _clock(settings[key]) for key in CLOCK_KEYS):
                issues.add("invalid_override_clock")
    return Validation(tuple(sorted(issues)))
