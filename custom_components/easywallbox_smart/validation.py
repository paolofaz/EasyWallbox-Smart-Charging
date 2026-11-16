"""Validation for new EasyWallbox Smart Charging configurations only.

The integration is installed afresh. No legacy version handling, migration,
Home Assistant imports, device access or storage writes live in this module.
Issues contain field codes, not user-provided names or entity IDs.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .const import (
    CONF_HOUSE_SOURCES, CONF_DOWNSTAIRS, CONF_UPSTAIRS, CONF_EV_POWER,
    CONF_SESSION_ENERGY, CONF_SESSION_DURATION,
    CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_TELEMETRY_FRESH,
    CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT, CONF_DPM_MODEL, CONF_DPM_CONFIRMED,
    CONF_VEHICLES, CONF_NAME, CONF_CABLE, CONF_SOC,
    CONF_TARGET_ENTITY, CONF_TARGET_DEFAULT, CONF_TARGET_MODE, CONF_CAPACITY,
    CONF_SUSTAINABLE, CONF_EFFICIENCY, CONF_VEHICLE_OVERRIDES,
    CONF_DEPARTURE_WEEKDAY, CONF_DEPARTURE_WEEKEND,
    CONF_INITIAL_CHARGE_KW, CONF_MAX_CHARGE_KW, CONF_SHADOW_LAB_ENABLED,
    DEFAULT_INITIAL_CHARGE_KW, DEFAULT_MAX_CHARGE_KW,
)
from .sources import finite_number
from .target_policy import ENTITY, FIXED, selected_mode

SOURCES = {
    CONF_EV_POWER: "sensor",
    CONF_WALLBOX_CONNECTED: "binary_sensor",
    CONF_WALLBOX_CHARGING: "binary_sensor",
    CONF_TELEMETRY_FRESH: "binary_sensor",
    CONF_REQUESTED_LIMIT: "number",
    CONF_CONFIRMED_LIMIT: "sensor",
}
CLOCK_KEYS = (CONF_DEPARTURE_WEEKDAY, CONF_DEPARTURE_WEEKEND)
OPTION_KEYS = frozenset({
    CONF_TARGET_DEFAULT, CONF_TARGET_ENTITY, CONF_TARGET_MODE,
    CONF_DEPARTURE_WEEKDAY, CONF_DEPARTURE_WEEKEND,
    CONF_EFFICIENCY, CONF_SUSTAINABLE,  # Ignored existing 0.1.0 option.
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
    # A 0.1.0 saved entry still has the original two house sensors.
    # A new entry uses an arbitrary list; options may change that list.
    household = options.get(CONF_HOUSE_SOURCES, data.get(CONF_HOUSE_SOURCES))
    if household is None and CONF_DOWNSTAIRS in data and CONF_UPSTAIRS in data:
        household = [data[CONF_DOWNSTAIRS], data[CONF_UPSTAIRS]]
    if not isinstance(household, (list, tuple)) or not household:
        issues.add("invalid_house_sources")
        household = []
    elif len(household) > 32 or any(not _entity(x, "sensor") for x in household):
        issues.add("invalid_house_sources")
    if len(household) != len(set(x for x in household if isinstance(x, str))):
        issues.add("duplicated_source_entity")
    if data.get(CONF_EV_POWER) in household:
        issues.add("duplicated_source_entity")
    # Verify session counters, if selected: both are required together.
    energy_id = options.get(CONF_SESSION_ENERGY, data.get(CONF_SESSION_ENERGY))
    duration_id = options.get(CONF_SESSION_DURATION, data.get(CONF_SESSION_DURATION))
    dpm_source = options.get(CONF_DPM_CONFIRMED, data.get(CONF_DPM_CONFIRMED))
    if dpm_source is not None and not _entity(dpm_source, "sensor"):
        issues.add("invalid_dpm_confirmed")
    if (energy_id is None) != (duration_id is None):
        issues.add("incomplete_session_counters")
    if energy_id is not None and not _entity(energy_id, "sensor"):
        issues.add("invalid_session_energy")
    if duration_id is not None and not _entity(duration_id, "sensor"):
        issues.add("invalid_session_duration")
    all_source_ids = list(household) + [
        data.get(k) for k in SOURCES
    ] + [energy_id, duration_id, dpm_source]
    valid_source_ids = [x for x in all_source_ids if isinstance(x, str)]
    if len(valid_source_ids) != len(set(valid_source_ids)):
        issues.add("duplicated_source_entity")
    if not _range(data.get(CONF_DPM_MODEL), 1.4, 20.0):
        issues.add("invalid_dpm_model")
    initial = options.get(
        CONF_INITIAL_CHARGE_KW,
        data.get(CONF_INITIAL_CHARGE_KW, DEFAULT_INITIAL_CHARGE_KW),
    )
    maximum = options.get(
        CONF_MAX_CHARGE_KW,
        data.get(CONF_MAX_CHARGE_KW, DEFAULT_MAX_CHARGE_KW),
    )
    for key, value in ((CONF_INITIAL_CHARGE_KW, initial),
                       (CONF_MAX_CHARGE_KW, maximum)):
        num = finite_number(value)
        if (num is None or not 1.4 <= num <= 6.0
                or abs(num * 5 - round(num * 5)) > 1e-5):
            issues.add("invalid_" + key)
    if (_range(initial, 1.4, 6.) and _range(maximum, 1.4, 6.)
            and float(initial) > float(maximum)):
        issues.add("initial_above_maximum")
    enabled = options.get(
        CONF_SHADOW_LAB_ENABLED, data.get(CONF_SHADOW_LAB_ENABLED, False)
    )
    if not isinstance(enabled, bool):
        issues.add("invalid_shadow_lab_enabled")

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
            mode = selected_mode(car)
            if mode not in (ENTITY, FIXED):
                issues.add("invalid_target_mode")
            elif mode == ENTITY:
                if not _entity(
                    car.get(CONF_TARGET_ENTITY), ("sensor", "number", "input_number")
                ):
                    issues.add("invalid_target_source")
                if CONF_TARGET_MODE in car and CONF_TARGET_DEFAULT in car:
                    issues.add("multiple_target_sources")
            else:
                if not _range(car.get(CONF_TARGET_DEFAULT), 1, 100):
                    issues.add("invalid_default_target")
                if CONF_TARGET_MODE in car and CONF_TARGET_ENTITY in car:
                    issues.add("multiple_target_sources")
            if not _range(car.get(CONF_CAPACITY), 10, 200):
                issues.add("invalid_capacity")
            if not _range(car.get(CONF_EFFICIENCY), 0.5, 1.0):
                issues.add("invalid_ac_efficiency")
            if not all(_clock(car.get(key)) for key in CLOCK_KEYS):
                issues.add("invalid_departure_clock")
    if cables.intersection(valid_source_ids):
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
            if CONF_TARGET_MODE in settings and selected_mode(settings) is None:
                issues.add("invalid_override_target_mode")
            # Check the effective source after merging base vehicle and
            # per-vehicle options. The new explicit mode suppresses the
            # unused field, including old 0.1.0 data stored in entry.data.
            vehicle = next((v for v in cars if isinstance(v, Mapping)
                            and v.get(CONF_CABLE) == cable), None) if isinstance(cars, list) else None
            if vehicle is not None:
                effective = {**vehicle, **settings}
                mode = selected_mode(effective)
                if mode == ENTITY:
                    if not _entity(
                        effective.get(CONF_TARGET_ENTITY),
                        ("sensor", "number", "input_number")
                    ):
                        issues.add("invalid_override_target")
                elif mode == FIXED:
                    if not _range(effective.get(CONF_TARGET_DEFAULT), 1, 100):
                        issues.add("invalid_override_target")
                else:
                    issues.add("invalid_override_target_mode")
            if (CONF_EFFICIENCY in settings
                    and not _range(settings[CONF_EFFICIENCY], 0.5, 1)):
                issues.add("invalid_override_efficiency")
            if any(key in settings and not _clock(settings[key]) for key in CLOCK_KEYS):
                issues.add("invalid_override_clock")
    return Validation(tuple(sorted(issues)))
