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
    TextSelector,
)

from .const import (
    DOMAIN, CONF_DOWNSTAIRS, CONF_UPSTAIRS, CONF_EV_POWER,
    CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_TELEMETRY_FRESH,
    CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT, CONF_DPM_MODEL,
    CONF_VEHICLES, CONF_NAME, CONF_CABLE, CONF_SOC, CONF_TARGET_ENTITY,
    CONF_TARGET_DEFAULT, CONF_CAPACITY, CONF_SUSTAINABLE, CONF_EFFICIENCY,
    CONF_DEPARTURE_WEEKDAY, CONF_DEPARTURE_WEEKEND, CONF_ADD_ANOTHER,
    CONF_VEHICLE_OVERRIDES,
)


def entity(domain: str | list[str]) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domain))


def number(minimum: float, maximum: float, step: float = 0.1) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=minimum, max=maximum,
                     step=step, mode=NumberSelectorMode.BOX))


WALLBOX_SCHEMA = vol.Schema({
    vol.Required(CONF_DOWNSTAIRS): entity("sensor"),
    vol.Required(CONF_UPSTAIRS): entity("sensor"),
    vol.Required(CONF_EV_POWER): entity("sensor"),
    vol.Required(CONF_WALLBOX_CONNECTED): entity("binary_sensor"),
    vol.Required(CONF_WALLBOX_CHARGING): entity("binary_sensor"),
    vol.Required(CONF_TELEMETRY_FRESH): entity("binary_sensor"),
    vol.Required(CONF_REQUESTED_LIMIT): entity("number"),
    vol.Required(CONF_CONFIRMED_LIMIT): entity("sensor"),
    vol.Required(CONF_DPM_MODEL, default=4.3): number(1.4, 20.0),
})

VEHICLE_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): TextSelector(),
    vol.Required(CONF_CABLE): entity("binary_sensor"),
    vol.Required(CONF_SOC): entity("sensor"),
    vol.Optional(CONF_TARGET_ENTITY): entity(["sensor", "number", "input_number"]),
    vol.Required(CONF_TARGET_DEFAULT, default=80): number(1, 100, 1),
    vol.Required(CONF_CAPACITY): number(10, 200),
    vol.Required(CONF_SUSTAINABLE, default=3.2): number(1.4, 22.0),
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
    VERSION = 1

    def __init__(self) -> None:
        self._wallbox: dict = {}
        self._vehicles: list[dict] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Offer editable vehicle planning settings without device commands."""
        return EasyWallboxSmartOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None):
        if user_input is not None:
            await self.async_set_unique_id("one_local_wallbox")
            self._abort_if_unique_id_configured()
            self._wallbox = user_input
            return await self.async_step_vehicle()
        return self.async_show_form(step_id="user", data_schema=WALLBOX_SCHEMA)

    async def async_step_vehicle(self, user_input: dict | None = None):
        errors = {}
        if user_input is not None:
            if not valid_clock(user_input[CONF_DEPARTURE_WEEKDAY]) or not valid_clock(user_input[CONF_DEPARTURE_WEEKEND]):
                errors["base"] = "invalid_clock"
            elif user_input[CONF_CABLE] in {v[CONF_CABLE] for v in self._vehicles}:
                errors["base"] = "duplicate_cable"
            elif user_input[CONF_NAME].strip().casefold() in {v[CONF_NAME].strip().casefold() for v in self._vehicles}:
                errors["base"] = "duplicate_vehicle"
            else:
                another = user_input.pop(CONF_ADD_ANOTHER)
                self._vehicles.append(user_input)
                if another:
                    return await self.async_step_vehicle()
                return self.async_create_entry(
                    title="EasyWallbox Smart Charging — Simulation",
                    data={**self._wallbox, CONF_VEHICLES: self._vehicles},
                )
        return self.async_show_form(step_id="vehicle", data_schema=VEHICLE_SCHEMA, errors=errors)


class EasyWallboxSmartOptionsFlow(OptionsFlowWithReload):
    """Edit one vehicle's planning settings and reload the read-only adapter.

    Session modes are deliberately NOT persistent options: manual and pause
    must be session-scoped so they cannot silently leak to another EV session.
    """

    def __init__(self):
        self._chosen_cable: str | None = None

    async def async_step_init(self, user_input: dict | None = None):
        """Pick the car whose target and departure plan should be revised."""
        vehicles = self.config_entry.data.get(CONF_VEHICLES, [])
        choices = {v[CONF_CABLE]: v[CONF_NAME] for v in vehicles}
        if not choices:
            return self.async_abort(reason="no_vehicles")
        if user_input is not None:
            self._chosen_cable = user_input["vehicle"]
            return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required("vehicle"): vol.In(choices)}),
        )

    async def async_step_vehicle(self, user_input: dict | None = None):
        """Save one vehicle override without rewriting the initial mapping."""
        choices = self.config_entry.data.get(CONF_VEHICLES, [])
        vehicle = next(
            (v for v in choices if v[CONF_CABLE] == self._chosen_cable), None
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
            else:
                updated = {
                    key: value for key, value in user_input.items()
                    if key in (
                        CONF_TARGET_DEFAULT, CONF_DEPARTURE_WEEKDAY,
                        CONF_DEPARTURE_WEEKEND, CONF_SUSTAINABLE, CONF_EFFICIENCY,
                    )
                }
                all_overrides = {
                    k: dict(v) for k, v in overrides.items()
                }
                all_overrides[self._chosen_cable] = updated
                return self.async_create_entry(
                    data={
                        **dict(self.config_entry.options),
                        CONF_VEHICLE_OVERRIDES: all_overrides,
                    }
                )
        schema = vol.Schema({
            vol.Required(
                CONF_TARGET_DEFAULT, default=current[CONF_TARGET_DEFAULT]
            ): number(1, 100, 1),
            vol.Required(
                CONF_DEPARTURE_WEEKDAY, default=current[CONF_DEPARTURE_WEEKDAY]
            ): TextSelector(),
            vol.Required(
                CONF_DEPARTURE_WEEKEND, default=current[CONF_DEPARTURE_WEEKEND]
            ): TextSelector(),
            vol.Required(
                CONF_SUSTAINABLE, default=current[CONF_SUSTAINABLE]
            ): number(1.4, 22.0),
            vol.Required(
                CONF_EFFICIENCY, default=current[CONF_EFFICIENCY]
            ): number(0.5, 1.0, 0.01),
        })
        return self.async_show_form(
            step_id="vehicle", data_schema=schema, errors=errors
        )
