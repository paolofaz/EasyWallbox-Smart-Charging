"""Entity-selector setup for one wallbox and an arbitrary number of cars."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    DOMAIN, CONF_HOUSE_SOURCES, CONF_SESSION_ENERGY, CONF_SESSION_DURATION,
    CONF_DOWNSTAIRS, CONF_UPSTAIRS, CONF_EV_POWER,
    CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_TELEMETRY_FRESH,
    CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT, CONF_DPM_MODEL,
    CONF_VEHICLES, CONF_NAME, CONF_CABLE, CONF_SOC, CONF_TARGET_ENTITY,
    CONF_TARGET_MODE,
    CONF_TARGET_DEFAULT, CONF_CAPACITY, CONF_SUSTAINABLE, CONF_EFFICIENCY,
    CONF_DEPARTURE_WEEKDAY, CONF_DEPARTURE_WEEKEND, CONF_ADD_ANOTHER,
    CONF_VEHICLE_OVERRIDES, CONF_DPM_CONFIRMED,
    CONF_INITIAL_CHARGE_KW, CONF_MAX_CHARGE_KW, CONF_SHADOW_LAB_ENABLED,
    DEFAULT_INITIAL_CHARGE_KW, DEFAULT_MAX_CHARGE_KW,
)
from .validation import validate
from .target_policy import ENTITY, FIXED, selected_mode


def entity(domain: str | list[str], *, multiple: bool = False) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domain, multiple=multiple))


def number(minimum: float, maximum: float, step: float = 0.1) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=minimum, max=maximum,
                     step=step, mode=NumberSelectorMode.BOX))


WALLBOX_SCHEMA = vol.Schema({
    vol.Required(CONF_HOUSE_SOURCES): entity("sensor", multiple=True),
    vol.Required(CONF_EV_POWER): entity("sensor"),
    vol.Optional(CONF_SESSION_ENERGY): entity("sensor"),
    vol.Optional(CONF_SESSION_DURATION): entity("sensor"),
    vol.Required(CONF_WALLBOX_CONNECTED): entity("binary_sensor"),
    vol.Required(CONF_WALLBOX_CHARGING): entity("binary_sensor"),
    vol.Required(CONF_TELEMETRY_FRESH): entity("binary_sensor"),
    vol.Required(CONF_REQUESTED_LIMIT): entity("number"),
    vol.Required(CONF_CONFIRMED_LIMIT): entity("sensor"),
    vol.Required(CONF_DPM_MODEL, default=4.4): number(1.4, 20.0),
    vol.Optional(CONF_DPM_CONFIRMED): entity("sensor"),
    vol.Required(CONF_INITIAL_CHARGE_KW, default=DEFAULT_INITIAL_CHARGE_KW):
        number(1.4, 6., .2),
    vol.Required(CONF_MAX_CHARGE_KW, default=DEFAULT_MAX_CHARGE_KW):
        number(1.4, 6., .2),
})

VEHICLE_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): TextSelector(),
    vol.Required(CONF_CABLE): entity("binary_sensor"),
    vol.Required(CONF_SOC): entity("sensor"),
    vol.Required(CONF_TARGET_MODE, default=ENTITY): SelectSelector(SelectSelectorConfig(
        options=[ENTITY, FIXED],
        translation_key="target_mode",
        mode=SelectSelectorMode.DROPDOWN,
    )),
    vol.Required(CONF_CAPACITY): number(10, 200),
    vol.Required(CONF_EFFICIENCY, default=0.90): number(0.5, 1.0, 0.01),
    vol.Required(CONF_DEPARTURE_WEEKDAY, default="07:00"): TextSelector(),
    vol.Required(CONF_DEPARTURE_WEEKEND, default="08:00"): TextSelector(),
    vol.Required(CONF_ADD_ANOTHER, default=False): bool,
})


def valid_clock(value: str) -> bool:
    try:
        h, m = value.split(":")
        return len(h) == 2 and len(m) == 2 and 0 <= int(h) < 24 and 0 <= int(m) < 60
    except (ValueError, AttributeError):
        return False


class EasyWallboxSmartConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Prevent multiple owners for the same local wallbox integration."""
    # Brand-new integration entry; no legacy conversion or migration.
    VERSION = 1

    def __init__(self) -> None:
        self._wallbox: dict = {}
        self._vehicles: list[dict] = []
        self._pending_vehicle: dict | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Offer editable vehicle planning settings without device commands."""
        return EasyWallboxSmartOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None):
        # One configured wallbox/integration instance per Home Assistant.
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        errors = {}
        if user_input is not None:
            source_ids = user_input[CONF_HOUSE_SOURCES]
            if (not isinstance(source_ids, list) or not source_ids):
                errors["base"] = "invalid_mapping"
            elif (len(set(source_ids)) != len(source_ids)
                  or user_input[CONF_EV_POWER] in source_ids):
                errors["base"] = "duplicate_sources"
            elif (CONF_SESSION_ENERGY in user_input) != (CONF_SESSION_DURATION in user_input):
                errors["base"] = "incomplete_counters"
            elif (user_input.get(CONF_DPM_CONFIRMED)
                  in (set(source_ids) | {user_input[CONF_EV_POWER]})):
                errors["base"] = "duplicate_sources"
            elif (float(user_input.get(
                    CONF_INITIAL_CHARGE_KW, DEFAULT_INITIAL_CHARGE_KW)) >
                  float(user_input.get(
                      CONF_MAX_CHARGE_KW, DEFAULT_MAX_CHARGE_KW))):
                errors["base"] = "invalid_power_range"
            else:
                await self.async_set_unique_id("one_local_wallbox")
                self._abort_if_unique_id_configured()
                self._wallbox = {
                    CONF_INITIAL_CHARGE_KW: DEFAULT_INITIAL_CHARGE_KW,
                    CONF_MAX_CHARGE_KW: DEFAULT_MAX_CHARGE_KW,
                    **dict(user_input),
                }
                return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="user", data_schema=WALLBOX_SCHEMA, errors=errors
        )

    async def async_step_vehicle(self, user_input: dict | None = None):
        """Configure vehicle identity and planning; target comes next."""
        errors = {}
        if user_input is not None:
            if (not valid_clock(user_input[CONF_DEPARTURE_WEEKDAY])
                    or not valid_clock(user_input[CONF_DEPARTURE_WEEKEND])):
                errors["base"] = "invalid_clock"
            elif user_input[CONF_CABLE] in {v[CONF_CABLE] for v in self._vehicles}:
                errors["base"] = "duplicate_cable"
            elif user_input[CONF_NAME].strip().casefold() in {
                    v[CONF_NAME].strip().casefold() for v in self._vehicles}:
                errors["base"] = "duplicate_vehicle"
            elif user_input[CONF_TARGET_MODE] not in (ENTITY, FIXED):
                errors["base"] = "invalid_mapping"
            else:
                self._pending_vehicle = dict(user_input)
                return await self.async_step_target()
        return self.async_show_form(
            step_id="vehicle", data_schema=VEHICLE_SCHEMA, errors=errors
        )

    async def async_step_target(self, user_input: dict | None = None):
        """Ask for exactly the chosen SOC target source; no hidden fallback."""
        pending = self._pending_vehicle
        if pending is None:
            return await self.async_step_vehicle()
        mode = pending[CONF_TARGET_MODE]
        target_field = CONF_TARGET_ENTITY if mode == ENTITY else CONF_TARGET_DEFAULT
        errors = {}
        if user_input is not None:
            value = user_input.get(target_field)
            if value is None:
                errors["base"] = "invalid_mapping"
            else:
                car = {key: value for key, value in pending.items()
                       if key != CONF_ADD_ANOTHER}
                car[target_field] = value
                self._vehicles.append(car)
                if pending[CONF_ADD_ANOTHER]:
                    self._pending_vehicle = None
                    return await self.async_step_vehicle()
                data = {**self._wallbox, CONF_VEHICLES: list(self._vehicles)}
                if validate(data).ready:
                    self._pending_vehicle = None
                    return self.async_create_entry(
                        title="EasyWallbox Smart Charging — Simulation",
                        data=data,
                    )
                self._vehicles.pop()
                errors["base"] = "invalid_mapping"
        schema = vol.Schema({
            vol.Required(target_field):
                entity(["sensor", "number", "input_number"])
                if mode == ENTITY else number(1, 100, 1),
        })
        return self.async_show_form(
            step_id="target", data_schema=schema, errors=errors
        )

class EasyWallboxSmartOptionsFlow(OptionsFlowWithReload):
    """Edit one vehicle's planning settings and reload the read-only adapter.

    Session modes are deliberately NOT persistent options: manual and pause
    must be session-scoped so they cannot silently leak to another EV session.
    """

    def __init__(self):
        self._chosen_cable: str | None = None
        self._pending_settings: dict | None = None

    async def async_step_init(self, user_input: dict | None = None):
        """Choose meter sources or per-vehicle planning settings."""
        if not validate(self.config_entry.data, self.config_entry.options).ready:
            return self.async_abort(reason="invalid_configuration")
        return self.async_show_menu(
            step_id="init",
            menu_options=["sources", "choose_vehicle", "shadow_lab"],
        )

    async def async_step_shadow_lab(self, user_input: dict | None = None):
        """Configure hypothetical EV limits and opt in to a field shadow log.

        Options apply after reload. No wallbox action is ever issued.
        """
        data, options = self.config_entry.data, self.config_entry.options
        initial = options.get(
            CONF_INITIAL_CHARGE_KW,
            data.get(CONF_INITIAL_CHARGE_KW, DEFAULT_INITIAL_CHARGE_KW),
        )
        maximum = options.get(
            CONF_MAX_CHARGE_KW,
            data.get(CONF_MAX_CHARGE_KW, DEFAULT_MAX_CHARGE_KW),
        )
        enabled = options.get(CONF_SHADOW_LAB_ENABLED, False)
        model = options.get(CONF_DPM_MODEL, data.get(CONF_DPM_MODEL, 4.4))
        errors = {}
        if user_input is not None:
            updated = {**dict(options), **dict(user_input)}
            if validate(data, updated).ready:
                return self.async_create_entry(data=updated)
            errors["base"] = "invalid_power_range"
        schema = vol.Schema({
            vol.Required(CONF_INITIAL_CHARGE_KW, default=initial):
                number(1.4, 6.0, .2),
            vol.Required(CONF_MAX_CHARGE_KW, default=maximum):
                number(1.4, 6.0, .2),
            vol.Required(CONF_DPM_MODEL, default=model):
                number(1.4, 20.0, .1),
            vol.Required(CONF_SHADOW_LAB_ENABLED, default=enabled): bool,
        })
        return self.async_show_form(
            step_id="shadow_lab", data_schema=schema, errors=errors,
        )

    async def async_step_choose_vehicle(self, user_input: dict | None = None):
        vehicles = self.config_entry.data.get(CONF_VEHICLES, [])
        choices = {v[CONF_CABLE]: v[CONF_NAME] for v in vehicles}
        if not choices:
            return self.async_abort(reason="no_vehicles")
        if user_input is not None:
            self._chosen_cable = user_input["vehicle"]
            return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="choose_vehicle",
            data_schema=vol.Schema({vol.Required("vehicle"): vol.In(choices)}),
        )

    async def async_step_sources(self, user_input: dict | None = None):
        """Reconfigure home Shelly sources and optional wallbox counters."""
        data, options = self.config_entry.data, self.config_entry.options
        existing = options.get(
            CONF_HOUSE_SOURCES,
            data.get(CONF_HOUSE_SOURCES, [
                data.get(CONF_DOWNSTAIRS), data.get(CONF_UPSTAIRS),
            ]),
        )
        initial = {
            CONF_HOUSE_SOURCES: [v for v in existing if v],
            CONF_SESSION_ENERGY: options.get(
                CONF_SESSION_ENERGY, data.get(CONF_SESSION_ENERGY)
            ),
            CONF_SESSION_DURATION: options.get(
                CONF_SESSION_DURATION, data.get(CONF_SESSION_DURATION)
            ),
            CONF_DPM_CONFIRMED: options.get(
                CONF_DPM_CONFIRMED, data.get(CONF_DPM_CONFIRMED)
            ),
        }
        errors = {}
        if user_input is not None:
            updated = dict(options)
            updated[CONF_HOUSE_SOURCES] = list(user_input[CONF_HOUSE_SOURCES])
            # Both counters can be removed, without inheriting stale data.
            updated[CONF_SESSION_ENERGY] = user_input.get(CONF_SESSION_ENERGY)
            updated[CONF_SESSION_DURATION] = user_input.get(CONF_SESSION_DURATION)
            updated[CONF_DPM_CONFIRMED] = user_input.get(CONF_DPM_CONFIRMED)
            check = validate(data, updated)
            if check.ready:
                return self.async_create_entry(data=updated)
            errors["base"] = "invalid_mapping"
        schema = {
            vol.Required(CONF_HOUSE_SOURCES, default=initial[CONF_HOUSE_SOURCES]):
                entity("sensor", multiple=True),
        }
        for key in (CONF_SESSION_ENERGY, CONF_SESSION_DURATION, CONF_DPM_CONFIRMED):
            marker = (vol.Optional(key, default=initial[key])
                      if initial[key] is not None else vol.Optional(key))
            schema[marker] = entity("sensor")
        return self.async_show_form(
            step_id="sources", data_schema=vol.Schema(schema), errors=errors,
        )

    async def async_step_vehicle(self, user_input: dict | None = None):
        """Edit vehicle schedule and explicitly choose one target method."""
        if not validate(self.config_entry.data, self.config_entry.options).ready:
            return self.async_abort(reason="invalid_configuration")
        vehicle = next(
            (v for v in self.config_entry.data[CONF_VEHICLES]
             if v[CONF_CABLE] == self._chosen_cable), None
        )
        if vehicle is None:
            return self.async_abort(reason="no_vehicles")
        overrides = self.config_entry.options.get(CONF_VEHICLE_OVERRIDES, {})
        current = {**vehicle, **overrides.get(self._chosen_cable, {})}
        errors = {}
        if user_input is not None:
            if (not valid_clock(user_input[CONF_DEPARTURE_WEEKDAY])
                    or not valid_clock(user_input[CONF_DEPARTURE_WEEKEND])):
                errors["base"] = "invalid_clock"
            elif user_input.get(CONF_TARGET_MODE) not in (ENTITY, FIXED):
                errors["base"] = "invalid_mapping"
            else:
                self._pending_settings = {
                    k: v for k, v in user_input.items()
                    if k in (CONF_TARGET_MODE, CONF_DEPARTURE_WEEKDAY,
                             CONF_DEPARTURE_WEEKEND, CONF_EFFICIENCY)
                }
                return await self.async_step_target()
        schema = vol.Schema({
            vol.Required(
                CONF_TARGET_MODE, default=selected_mode(current)
            ): SelectSelector(SelectSelectorConfig(
                options=[ENTITY, FIXED],
                translation_key="target_mode",
                mode=SelectSelectorMode.DROPDOWN,
            )),
            vol.Required(
                CONF_DEPARTURE_WEEKDAY, default=current[CONF_DEPARTURE_WEEKDAY]
            ): TextSelector(),
            vol.Required(
                CONF_DEPARTURE_WEEKEND, default=current[CONF_DEPARTURE_WEEKEND]
            ): TextSelector(),
            vol.Required(
                CONF_EFFICIENCY, default=current[CONF_EFFICIENCY]
            ): number(0.5, 1.0, 0.01),
        })
        return self.async_show_form(
            step_id="vehicle", data_schema=schema, errors=errors
        )

    async def async_step_target(self, user_input: dict | None = None):
        """Persist only the chosen target in per-car options, then reload."""
        if self._pending_settings is None or self._chosen_cable is None:
            return self.async_abort(reason="no_vehicles")
        mode = self._pending_settings[CONF_TARGET_MODE]
        field = CONF_TARGET_ENTITY if mode == ENTITY else CONF_TARGET_DEFAULT
        vehicle = next(
            (v for v in self.config_entry.data[CONF_VEHICLES]
             if v[CONF_CABLE] == self._chosen_cable), None
        )
        if vehicle is None:
            return self.async_abort(reason="no_vehicles")
        overrides = self.config_entry.options.get(CONF_VEHICLE_OVERRIDES, {})
        current = {**vehicle, **overrides.get(self._chosen_cable, {})}
        errors = {}
        if user_input is not None:
            value = user_input.get(field)
            if value is None:
                errors["base"] = "invalid_mapping"
            else:
                updated = dict(overrides.get(self._chosen_cable, {}))
                updated.update(self._pending_settings)
                updated.pop(CONF_TARGET_ENTITY if mode == FIXED else CONF_TARGET_DEFAULT, None)
                updated[field] = value
                all_overrides = {k: dict(v) for k, v in overrides.items()}
                all_overrides[self._chosen_cable] = updated
                options = {
                    **dict(self.config_entry.options),
                    CONF_VEHICLE_OVERRIDES: all_overrides,
                }
                if validate(self.config_entry.data, options).ready:
                    return self.async_create_entry(data=options)
                errors["base"] = "invalid_mapping"
        marker = (
            vol.Required(field, default=current[field])
            if current.get(field) is not None else vol.Required(field)
        )
        schema = vol.Schema({
            marker: entity(["sensor", "number", "input_number"])
                    if mode == ENTITY else number(1, 100, 1),
        })
        return self.async_show_form(
            step_id="target", data_schema=schema, errors=errors
        )
