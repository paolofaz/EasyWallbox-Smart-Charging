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
from .vehicle_profiles import configured_vehicles, upsert_vehicle, remove_vehicle
from .wallbox_discovery import discover_from_start_stop, DiscoveryError


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
    vol.Optional(CONF_BLE_CONNECTED): entity("binary_sensor"),
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
})
VEHICLE = vol.Schema({
    vol.Required(CONF_NAME): TextSelector(),
    vol.Required(CONF_CABLE): entity("binary_sensor"),
    vol.Required(CONF_SOC): entity("sensor"),
    vol.Optional(CONF_VEHICLE_REFRESH): entity("button"),
    vol.Optional(CONF_VEHICLE_LAST_UPDATE): entity(["sensor", "datetime"]),
    vol.Required(CONF_STOP_AT_TARGET, default=False): bool,
    vol.Required(CONF_CAPACITY): number(10, 200, .1),
    vol.Required(CONF_EFFICIENCY, default=.90): number(.5, 1, .01),
    vol.Required(CONF_DEPARTURE_WEEKDAY, default="07:00"): TextSelector(),
    vol.Required(CONF_DEPARTURE_WEEKEND, default="08:00"): TextSelector(),
    vol.Required(CONF_ADD_ANOTHER, default=False): bool,
})


# Basic first: the firmware reports everything else via the same ESPHome device.
# The full manual mapping remains available for alternate firmware revisions.
BASIC_WALLBOX = vol.Schema({
    vol.Required(CONF_HOUSE_SOURCES): entity("sensor", True),
    vol.Required(CONF_EV_POWER): entity("sensor"),
    vol.Required(CONF_START_STOP): entity("switch"),
    vol.Required(CONF_EXPECTED_DPM, default=DEFAULT_DPM_KW): number(1.4, 6.0, .1),
    vol.Required(CONF_BASE_KW, default=DEFAULT_BASE_KW): number(1.4, 6.0, .2),
    vol.Required(CONF_BOOST_KW, default=DEFAULT_BOOST_KW): number(1.4, 6.0, .2),
})


def _full_basic(hass, data, previous=None):
    """Compose minimal user input with unambiguous ESPHome registry evidence."""
    result = dict(data)
    anchor = data[CONF_START_STOP]
    try:
        resolved = discover_from_start_stop(hass, anchor)
    except DiscoveryError:
        # Existing verified mappings may be retained only if the SAME
        # Start-Stop entity is selected; never cross-match another device.
        if previous is None or previous.get(CONF_START_STOP) != anchor:
            raise
        required = [k for k in (
            CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING,
            CONF_TELEMETRY_FRESH, CONF_DPM_ACTIVE, CONF_WALLBOX_FAULT,
            CONF_CHARGE_ENABLED, CONF_COMMAND_STATUS, CONF_REQUESTED_LIMIT,
            CONF_CONFIRMED_LIMIT, CONF_DPM_CONFIRMED, CONF_WALLBOX_REFRESH,
        ) if not previous.get(k)]
        if required:
            raise
        resolved = {k: previous[k] for k in (
            CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING,
            CONF_TELEMETRY_FRESH, CONF_DPM_ACTIVE, CONF_WALLBOX_FAULT,
            CONF_CHARGE_ENABLED, CONF_COMMAND_STATUS, CONF_REQUESTED_LIMIT,
            CONF_CONFIRMED_LIMIT, CONF_DPM_CONFIRMED, CONF_WALLBOX_REFRESH,
        )}
        if previous.get(CONF_BLE_CONNECTED):
            resolved[CONF_BLE_CONNECTED] = previous[CONF_BLE_CONNECTED]
    result.update(resolved)
    return result


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
    if x.get(CONF_BLE_CONNECTED):
        other.append(x[CONF_BLE_CONNECTED])
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

    async def _accept_wallbox(self, config):
        reason = check_wallbox(config)
        if reason:
            return reason
        await self.async_set_unique_id("easywallbox_rc_local")
        self._abort_if_unique_id_configured()
        self._wallbox = config
        return None

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        errors = {}
        if user_input is not None:
            try:
                resolved = _full_basic(self.hass, user_input)
            except DiscoveryError:
                # Alternate ESPHome builds can still be configured explicitly.
                return await self.async_step_advanced_user()
            failure = await self._accept_wallbox(resolved)
            if failure:
                errors["base"] = failure
            else:
                return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="user", data_schema=BASIC_WALLBOX, errors=errors)

    async def async_step_advanced_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        errors = {}
        if user_input is not None:
            failure = await self._accept_wallbox(dict(user_input))
            if failure:
                errors["base"] = failure
            else:
                return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="advanced_user", data_schema=WALLBOX, errors=errors)

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
        """Exactly one target pathway, displayed as two localized choices."""
        return self.async_show_menu(
            step_id="target_method",
            menu_options=["target_entity", "target_fixed"])

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
            stop = self._pending.get(CONF_STOP_AT_TARGET, False)
            allowed = ((80 <= float(target) <= 100 and float(target) % 5 == 0)
                       if stop else 1 <= float(target) <= 100)
            if allowed:
                return self._finish_vehicle({CONF_TARGET_FIXED: target})
            return self.async_show_form(
                step_id="target_fixed",
                data_schema=vol.Schema({
                    vol.Required(CONF_TARGET_FIXED, default=80):
                        number(80, 100, 5) if stop else number(1, 100, 1)}),
                errors={"base": "invalid_target"},
            )
        return self.async_show_form(
            step_id="target_fixed",
            data_schema=vol.Schema({
                vol.Required(CONF_TARGET_FIXED, default=80):
                    number(80, 100, 5) if self._pending.get(CONF_STOP_AT_TARGET, False) else number(1, 100, 1),
            }),
        )


class EasyWallboxSmartOptionsFlow(OptionsFlowWithReload):
    """Edit complete car profiles and wallbox sources; reload safely on save."""

    def _cars(self):
        return configured_vehicles(
            self.config_entry.data, self.config_entry.options)

    def _save_cars(self, cars):
        updated = dict(self.config_entry.options)
        updated[CONF_VEHICLES] = cars
        updated.pop("vehicle_schedules", None)
        return self.async_create_entry(data=updated)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["wallbox", "advanced_wallbox", "choose_vehicle",
                          "add_vehicle", "remove_vehicle"])

    def _wallbox_settings(self):
        return {**self.config_entry.data, **self.config_entry.options}

    def _without_old_flags(self):
        return {k: v for k, v in self.config_entry.options.items()
                if k not in (CONF_LEGACY_DISABLED, CONF_AUTOMATIC_CONTROL_ENABLED)}

    async def async_step_wallbox(self, user_input=None):
        existing = self._wallbox_settings()
        errors = {}
        if user_input is not None:
            try:
                resolved = _full_basic(self.hass, user_input, existing)
            except DiscoveryError:
                errors["base"] = "automatic_detection_failed"
            else:
                reason = check_wallbox(resolved)
                if reason:
                    errors["base"] = reason
                else:
                    return self.async_create_entry(
                        data={**self._without_old_flags(), **resolved})
        schema = vol.Schema({
            vol.Required(CONF_HOUSE_SOURCES,
                         default=existing[CONF_HOUSE_SOURCES]): entity("sensor", True),
            vol.Required(CONF_EV_POWER,
                         default=existing[CONF_EV_POWER]): entity("sensor"),
            vol.Required(CONF_START_STOP,
                         default=existing[CONF_START_STOP]): entity("switch"),
            vol.Required(CONF_EXPECTED_DPM,
                         default=existing[CONF_EXPECTED_DPM]): number(1.4, 6.0, .1),
            vol.Required(CONF_BASE_KW,
                         default=existing[CONF_BASE_KW]): number(1.4, 6.0, .2),
            vol.Required(CONF_BOOST_KW,
                         default=existing[CONF_BOOST_KW]): number(1.4, 6.0, .2),
        })
        return self.async_show_form(
            step_id="wallbox", data_schema=schema, errors=errors)

    async def async_step_advanced_wallbox(self, user_input=None):
        existing = self._wallbox_settings()
        errors = {}
        if user_input is not None:
            combined = {**existing, **user_input}
            reason = check_wallbox(combined)
            if reason:
                errors["base"] = reason
            else:
                return self.async_create_entry(
                    data={**self._without_old_flags(), **user_input})
        schema = vol.Schema({
            vol.Required(CONF_HOUSE_SOURCES, default=existing[CONF_HOUSE_SOURCES]): entity("sensor", True),
            vol.Required(CONF_EV_POWER, default=existing[CONF_EV_POWER]): entity("sensor"),
            vol.Required(CONF_WALLBOX_CONNECTED, default=existing[CONF_WALLBOX_CONNECTED]): entity("binary_sensor"),
            vol.Optional(CONF_BLE_CONNECTED, default=existing.get(CONF_BLE_CONNECTED)): entity("binary_sensor"),
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
        })
        return self.async_show_form(
            step_id="advanced_wallbox", data_schema=schema, errors=errors)

    async def async_step_choose_vehicle(self, user_input=None):
        if user_input is not None:
            self._original_cable = user_input["vehicle"]
            return await self.async_step_edit_vehicle()
        choices = {v[CONF_CABLE]: v[CONF_NAME] for v in self._cars()}
        return self.async_show_form(
            step_id="choose_vehicle",
            data_schema=vol.Schema({
                vol.Required("vehicle"): vol.In(choices)}))

    async def async_step_add_vehicle(self, user_input=None):
        self._original_cable = None
        return await self.async_step_edit_vehicle(user_input)

    @staticmethod
    def _required(key, old, selector):
        if key in old and old[key] is not None:
            return vol.Required(key, default=old[key]), selector
        return vol.Required(key), selector

    @staticmethod
    def _optional(key, old, selector):
        if old.get(key):
            return vol.Optional(key, default=old[key]), selector
        return vol.Optional(key), selector

    def _edit_schema(self, old):
        result = {}
        fields = [
            self._required(CONF_NAME, old, TextSelector()),
            self._required(CONF_CABLE, old, entity("binary_sensor")),
            self._required(CONF_SOC, old, entity("sensor")),
            self._optional(CONF_VEHICLE_REFRESH, old, entity("button")),
            self._optional(CONF_VEHICLE_LAST_UPDATE, old, entity(["sensor", "datetime"])),
            (vol.Required(CONF_STOP_AT_TARGET, default=old.get(CONF_STOP_AT_TARGET, False)), bool),
            self._required(CONF_CAPACITY, old, number(10, 200, .1)),
            self._required(CONF_EFFICIENCY, old, number(.5, 1, .01)),
            self._required(CONF_DEPARTURE_WEEKDAY, old, TextSelector()),
            self._required(CONF_DEPARTURE_WEEKEND, old, TextSelector()),
        ]
        for key, selector in fields:
            result[key] = selector
        return vol.Schema(result)

    async def async_step_edit_vehicle(self, user_input=None):
        selected = getattr(self, "_original_cable", None)
        old = next((v for v in self._cars() if v[CONF_CABLE] == selected), {})
        errors = {}
        if user_input is not None:
            if not clock(user_input[CONF_DEPARTURE_WEEKDAY]) or not clock(
                    user_input[CONF_DEPARTURE_WEEKEND]):
                errors["base"] = "invalid_clock"
            else:
                self._previous_target = {
                    k: old[k] for k in (CONF_TARGET_ENTITY, CONF_TARGET_FIXED)
                    if k in old
                }
                # Optional fields removed in the editor really are removed;
                # never preserve stale refresh/timestamp IDs from old config.
                self._pending_vehicle = dict(user_input)
                return await self.async_step_edit_target_method()
        return self.async_show_form(
            step_id="edit_vehicle", errors=errors,
            data_schema=self._edit_schema(old))

    async def async_step_edit_target_method(self, user_input=None):
        return self.async_show_menu(
            step_id="edit_target_method",
            menu_options=["edit_target_fixed", "edit_target_entity"])

    def _finish_edit(self, target):
        pending = dict(self._pending_vehicle)
        pending.update(target)
        try:
            vehicles = upsert_vehicle(
                self._cars(), pending,
                original_cable=getattr(self, "_original_cable", None))
        except ValueError as error:
            self._edit_error = str(error)
            return None
        return self._save_cars(vehicles)

    async def async_step_edit_target_fixed(self, user_input=None):
        old = getattr(self, "_previous_target", {})
        default = old.get(CONF_TARGET_FIXED, 80)
        errors = {}
        if user_input is not None:
            value = float(user_input[CONF_TARGET_FIXED])
            wants_stop = self._pending_vehicle.get(CONF_STOP_AT_TARGET, False)
            if wants_stop and (value < 80 or value > 100 or value % 5 != 0):
                return self.async_show_form(
                    step_id="edit_target_fixed", errors={"base": "invalid_target"},
                    data_schema=vol.Schema({vol.Required(CONF_TARGET_FIXED, default=80):
                                             number(80, 100, 5)}))
            result = self._finish_edit({
                CONF_TARGET_FIXED: user_input[CONF_TARGET_FIXED]})
            if result is not None:
                return result
            errors["base"] = getattr(self, "_edit_error", "invalid_vehicle")
        stop = self._pending_vehicle.get(CONF_STOP_AT_TARGET, False)
        if stop and (default < 80 or default > 100 or default % 5 != 0):
            default = 80
        return self.async_show_form(
            step_id="edit_target_fixed", errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_TARGET_FIXED, default=default):
                    number(80, 100, 5) if stop else number(1, 100, 1)}))

    async def async_step_edit_target_entity(self, user_input=None):
        old = getattr(self, "_previous_target", {})
        errors = {}
        if user_input is not None:
            result = self._finish_edit({
                CONF_TARGET_ENTITY: user_input[CONF_TARGET_ENTITY]})
            if result is not None:
                return result
            errors["base"] = getattr(self, "_edit_error", "invalid_vehicle")
        key = (vol.Required(CONF_TARGET_ENTITY,
                            default=old[CONF_TARGET_ENTITY])
               if old.get(CONF_TARGET_ENTITY)
               else vol.Required(CONF_TARGET_ENTITY))
        return self.async_show_form(
            step_id="edit_target_entity", errors=errors,
            data_schema=vol.Schema({
                key: entity(["sensor", "number", "input_number"])}))

    async def async_step_remove_vehicle(self, user_input=None):
        if len(self._cars()) <= 1:
            return self.async_abort(reason="cannot_remove_last")
        if user_input is not None:
            self._remove_cable = user_input["vehicle"]
            return await self.async_step_confirm_remove()
        choices = {v[CONF_CABLE]: v[CONF_NAME] for v in self._cars()}
        return self.async_show_form(
            step_id="remove_vehicle",
            data_schema=vol.Schema({
                vol.Required("vehicle"): vol.In(choices)}))

    async def async_step_confirm_remove(self, user_input=None):
        if user_input is not None:
            if user_input["confirm"]:
                try:
                    return self._save_cars(remove_vehicle(
                        self._cars(), self._remove_cable))
                except ValueError:
                    return self.async_abort(reason="cannot_remove_last")
            return await self.async_step_init()
        return self.async_show_form(
            step_id="confirm_remove",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}))
