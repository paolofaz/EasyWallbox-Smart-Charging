"""Graphical setup of the RC without hard-coded device, car or meter IDs."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector, EntitySelectorConfig,
    NumberSelector, NumberSelectorConfig, NumberSelectorMode,
    TextSelector,
)
from .const import *


def entity(domains, multiple=False):
    return EntitySelector(EntitySelectorConfig(domain=domains, multiple=multiple))


def number(low, high, step=.1):
    return NumberSelector(NumberSelectorConfig(
        min=low, max=high, step=step, mode=NumberSelectorMode.BOX))


def power_step(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return 1.4 <= v <= 6.0 and abs(v * 5 - round(v * 5)) < 1e-6


def clock(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    try:
        h, m = (int(x) for x in value.split(":"))
        return 0 <= h <= 23 and 0 <= m <= 59
    except ValueError:
        return False


WALLBOX = vol.Schema({
    vol.Required(CONF_HOUSE_SOURCES): entity("sensor", True),
    vol.Required(CONF_EV_POWER): entity("sensor"),
    vol.Required(CONF_WALLBOX_CONNECTED): entity("binary_sensor"),
    vol.Required(CONF_WALLBOX_CHARGING): entity("binary_sensor"),
    vol.Required(CONF_TELEMETRY_FRESH): entity("binary_sensor"),
    vol.Required(CONF_DPM_ACTIVE): entity("binary_sensor"),
    vol.Required(CONF_WALLBOX_FAULT): entity("binary_sensor"),
    vol.Required(CONF_CHARGE_ENABLED): entity("binary_sensor"),
    vol.Required(CONF_START_STOP): entity("switch"),
    vol.Required(CONF_COMMAND_STATUS): entity("sensor"),
    vol.Required(CONF_REQUESTED_LIMIT): entity("number"),
    vol.Required(CONF_CONFIRMED_LIMIT): entity("sensor"),
    vol.Required(CONF_DPM_CONFIRMED): entity("sensor"),
    vol.Required(CONF_WALLBOX_REFRESH): entity("button"),
    vol.Required(CONF_EXPECTED_DPM, default=DEFAULT_DPM_KW): number(1.4, 6.0, .1),
    vol.Required(CONF_BASE_KW, default=DEFAULT_BASE_KW): number(1.4, 6.0, .2),
    vol.Required(CONF_BOOST_KW, default=DEFAULT_BOOST_KW): number(1.4, 6.0, .2),
    vol.Required(CONF_LEGACY_DISABLED, default=False): bool,
})
VEHICLE = vol.Schema({
    vol.Required(CONF_NAME): TextSelector(),
    vol.Required(CONF_CABLE): entity("binary_sensor"),
    vol.Required(CONF_SOC): entity("sensor"),
    vol.Optional(CONF_VEHICLE_REFRESH): entity("button"),
    vol.Optional(CONF_VEHICLE_LAST_UPDATE): entity(["sensor", "datetime"]),
    vol.Required(CONF_CAPACITY): number(10, 200, .1),
    vol.Required("planning_rate_kw", default=2.4): number(1.4, 6.0, .2),
    vol.Required(CONF_EFFICIENCY, default=.90): number(.5, 1, .01),
    vol.Required(CONF_DEPARTURE_WEEKDAY, default="07:00"): TextSelector(),
    vol.Required(CONF_DEPARTURE_WEEKEND, default="08:00"): TextSelector(),
    vol.Required(CONF_ADD_ANOTHER, default=False): bool,
})


def check_wallbox(x):
    ids = [*x.get(CONF_HOUSE_SOURCES, [])]
    if not ids or len(set(ids)) != len(ids) or x.get(CONF_EV_POWER) in ids:
        return "invalid_meter_sources"
    other = [
        x.get(CONF_EV_POWER), x.get(CONF_WALLBOX_CONNECTED),
        x.get(CONF_WALLBOX_CHARGING), x.get(CONF_TELEMETRY_FRESH),
        x.get(CONF_DPM_ACTIVE), x.get(CONF_WALLBOX_FAULT),
        x.get(CONF_CHARGE_ENABLED), x.get(CONF_START_STOP),
        x.get(CONF_COMMAND_STATUS), x.get(CONF_REQUESTED_LIMIT),
        x.get(CONF_CONFIRMED_LIMIT), x.get(CONF_DPM_CONFIRMED),
    ]
    if x.get(CONF_WALLBOX_REFRESH):
        other.append(x[CONF_WALLBOX_REFRESH])
    if len(set(other)) != len(other) or set(ids) & set(other):
        return "duplicate_entities"
    if (not power_step(x.get(CONF_BASE_KW))
            or not power_step(x.get(CONF_BOOST_KW))
            or float(x[CONF_BOOST_KW]) < float(x[CONF_BASE_KW])
            or float(x[CONF_BOOST_KW])-float(x[CONF_BASE_KW]) > .4+1e-6):
        return "invalid_power"
    return None


class EasyWallboxSmartConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self):
        self._wallbox = {}
        self._vehicles = []
        self._pending = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return EasyWallboxSmartOptionsFlow()

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        errors = {}
        if user_input is not None:
            reason = check_wallbox(user_input)
            if reason:
                errors["base"] = reason
            else:
                await self.async_set_unique_id("easywallbox_rc_local")
                self._abort_if_unique_id_configured()
                self._wallbox = dict(user_input)
                return await self.async_step_vehicle()
        return self.async_show_form(step_id="user", data_schema=WALLBOX, errors=errors)

    async def async_step_vehicle(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not clock(user_input[CONF_DEPARTURE_WEEKDAY]) or not clock(user_input[CONF_DEPARTURE_WEEKEND]):
                errors["base"] = "invalid_clock"
            elif user_input[CONF_CABLE] in [v[CONF_CABLE] for v in self._vehicles]:
                errors["base"] = "duplicate_vehicle"
            elif user_input[CONF_NAME].casefold() in [v[CONF_NAME].casefold() for v in self._vehicles]:
                errors["base"] = "duplicate_vehicle"
            else:
                self._pending = dict(user_input)
                return await self.async_step_target_method()
        return self.async_show_form(step_id="vehicle", data_schema=VEHICLE, errors=errors)

    def _finish_vehicle(self, target_mapping):
        """Persist the fully configured car; no ambiguous optional targets."""
        car = {k: v for k, v in self._pending.items() if k != CONF_ADD_ANOTHER}
        car.update(target_mapping)
        self._vehicles.append(car)
        if self._pending[CONF_ADD_ANOTHER]:
            return self.async_show_form(
                step_id="vehicle", data_schema=VEHICLE)
        return self.async_create_entry(
            title="EasyWallbox Smart Charging",
            data={**self._wallbox, CONF_VEHICLES: self._vehicles},
        )

    async def async_step_target_method(self, user_input=None):
        """Make it impossible to submit a missing or conflicting SOC target."""
        if user_input is not None:
            method = user_input["target_method"]
            if method == "entity":
                return await self.async_step_target_entity()
            return await self.async_step_target_fixed()
        return self.async_show_form(
            step_id="target_method",
            data_schema=vol.Schema({
                vol.Required("target_method", default="fixed"): vol.In(
                    {"fixed": "Percentuale fissa", "entity": "Entità Home Assistant"})
            }),
        )

    async def async_step_target_entity(self, user_input=None):
        if user_input is not None:
            return self._finish_vehicle({
                CONF_TARGET_ENTITY: user_input[CONF_TARGET_ENTITY]})
        return self.async_show_form(
            step_id="target_entity",
            data_schema=vol.Schema({
                vol.Required(CONF_TARGET_ENTITY): entity(
                    ["sensor", "number", "input_number"]),
            }),
        )

    async def async_step_target_fixed(self, user_input=None):
        if user_input is not None:
            target = user_input[CONF_TARGET_FIXED]
            if 1 <= float(target) <= 100:
                return self._finish_vehicle({CONF_TARGET_FIXED: target})
            return self.async_show_form(
                step_id="target_fixed",
                data_schema=vol.Schema({
                    vol.Required(CONF_TARGET_FIXED, default=80):
                        number(1, 100, 1)}),
                errors={"base": "invalid_target"},
            )
        return self.async_show_form(
            step_id="target_fixed",
            data_schema=vol.Schema({
                vol.Required(CONF_TARGET_FIXED, default=80): number(1, 100, 1),
            }),
        )


class EasyWallboxSmartOptionsFlow(OptionsFlowWithReload):
    """Editable sources, car schedules and lab; never the currently active lease."""

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["wallbox", "choose_vehicle"])

    async def async_step_wallbox(self, user_input=None):
        existing = {**self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            combined = {**existing, **user_input}
            reason = check_wallbox(combined)
            if reason:
                errors["base"] = reason
            else:
                return self.async_create_entry(
                    data={**self.config_entry.options, **user_input})
        schema = vol.Schema({
            vol.Required(CONF_HOUSE_SOURCES, default=existing[CONF_HOUSE_SOURCES]): entity("sensor", True),
            vol.Required(CONF_EV_POWER, default=existing[CONF_EV_POWER]): entity("sensor"),
            vol.Required(CONF_WALLBOX_CONNECTED, default=existing[CONF_WALLBOX_CONNECTED]): entity("binary_sensor"),
            vol.Required(CONF_WALLBOX_CHARGING, default=existing[CONF_WALLBOX_CHARGING]): entity("binary_sensor"),
            vol.Required(CONF_TELEMETRY_FRESH, default=existing[CONF_TELEMETRY_FRESH]): entity("binary_sensor"),
            vol.Required(CONF_DPM_ACTIVE, default=existing[CONF_DPM_ACTIVE]): entity("binary_sensor"),
            vol.Required(CONF_WALLBOX_FAULT, default=existing[CONF_WALLBOX_FAULT]): entity("binary_sensor"),
            vol.Required(CONF_CHARGE_ENABLED, default=existing[CONF_CHARGE_ENABLED]): entity("binary_sensor"),
            vol.Required(CONF_START_STOP, default=existing[CONF_START_STOP]): entity("switch"),
            vol.Required(CONF_COMMAND_STATUS, default=existing[CONF_COMMAND_STATUS]): entity("sensor"),
            vol.Required(CONF_REQUESTED_LIMIT, default=existing[CONF_REQUESTED_LIMIT]): entity("number"),
            vol.Required(CONF_CONFIRMED_LIMIT, default=existing[CONF_CONFIRMED_LIMIT]): entity("sensor"),
            vol.Required(CONF_DPM_CONFIRMED, default=existing[CONF_DPM_CONFIRMED]): entity("sensor"),
            vol.Required(CONF_WALLBOX_REFRESH, default=existing[CONF_WALLBOX_REFRESH]): entity("button"),
            vol.Required(CONF_EXPECTED_DPM, default=existing[CONF_EXPECTED_DPM]): number(1.4, 6, .1),
            vol.Required(CONF_BASE_KW, default=existing[CONF_BASE_KW]): number(1.4, 6, .2),
            vol.Required(CONF_BOOST_KW, default=existing[CONF_BOOST_KW]): number(1.4, 6, .2),
            vol.Required(CONF_LEGACY_DISABLED, default=existing.get(CONF_LEGACY_DISABLED, False)): bool,
        })
        return self.async_show_form(step_id="wallbox", data_schema=schema, errors=errors)

    async def async_step_choose_vehicle(self, user_input=None):
        vehicles = self.config_entry.data[CONF_VEHICLES]
        choices = {v[CONF_CABLE]: v[CONF_NAME] for v in vehicles}
        if user_input is not None:
            self._chosen_cable = user_input["vehicle"]
            return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="choose_vehicle",
            data_schema=vol.Schema({vol.Required("vehicle"): vol.In(choices)}))

    async def async_step_vehicle(self, user_input=None):
        car = next((v for v in self.config_entry.data[CONF_VEHICLES]
                    if v[CONF_CABLE] == getattr(self, "_chosen_cable", None)), None)
        if car is None:
            return await self.async_step_choose_vehicle()
        options = self.config_entry.options
        old = {**car, **options.get("vehicle_schedules", {}).get(car[CONF_CABLE], {})}
        errors = {}
        if user_input is not None:
            if not clock(user_input[CONF_DEPARTURE_WEEKDAY]) or not clock(user_input[CONF_DEPARTURE_WEEKEND]):
                errors["base"] = "invalid_clock"
            else:
                saved = dict(options.get("vehicle_schedules", {}))
                saved[car[CONF_CABLE]] = dict(user_input)
                return self.async_create_entry(data={**options, "vehicle_schedules": saved})
        return self.async_show_form(
            step_id="vehicle", errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_DEPARTURE_WEEKDAY, default=old[CONF_DEPARTURE_WEEKDAY]): TextSelector(),
                vol.Required(CONF_DEPARTURE_WEEKEND, default=old[CONF_DEPARTURE_WEEKEND]): TextSelector(),
            }))
