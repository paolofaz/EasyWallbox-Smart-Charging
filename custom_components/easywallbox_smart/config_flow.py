"""Read-only setup for any number of vehicles, not specific car makes."""

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import CONF_VEHICLES, DOMAIN, POWER_FIELDS, WALLBOX_FIELDS
from .vehicle import build_vehicle, profiles_from_entry


def _entities(fields: dict[str, list[str]]) -> vol.Schema:
    """Pick existing HA state entities in a graphical form."""
    return vol.Schema({
        vol.Optional(key): EntitySelector(EntitySelectorConfig(domain=domains))
        for key, domains in fields.items()
    })


def _vehicle_form() -> vol.Schema:
    """Vehicle identity and sources; no in-car target entity required."""
    return vol.Schema({
        vol.Required("name"): str,
        vol.Required("soc"): EntitySelector(EntitySelectorConfig(domain=["sensor"])),
        vol.Required("connected"): EntitySelector(
            EntitySelectorConfig(domain=["binary_sensor"])
        ),
        vol.Optional("charging"): EntitySelector(
            EntitySelectorConfig(domain=["binary_sensor"])
        ),
        vol.Required("capacity_kwh"): vol.All(
            vol.Coerce(float), vol.Range(min=1.0, max=250.0)
        ),
        vol.Required("default_target_soc", default=80): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
    })


def _remove_missing(data: dict, keys: dict, form: dict) -> None:
    """Save only present optional entity selectors, allowing removal."""
    for key in keys:
        if key in form:
            data[key] = form[key]
        else:
            data.pop(key, None)


class EasyWallboxSmartConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Wallbox -> one or more named vehicles -> power sources."""

    VERSION = 2

    def __init__(self) -> None:
        self._selected: dict[str, Any] = {}
        self._vehicles: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            self._selected.update(user_input)
            return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="user", data_schema=_entities(WALLBOX_FIELDS)
        )

    async def async_step_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                profile = build_vehicle(user_input, self._vehicles)
            except (ValueError, KeyError, TypeError):
                errors["base"] = "invalid_vehicle"
            else:
                self._vehicles.append(profile)
                return await self.async_step_more()
        return self.async_show_form(
            step_id="vehicle", data_schema=_vehicle_form(), errors=errors
        )

    async def async_step_more(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            if user_input["add_another"]:
                return await self.async_step_vehicle()
            return await self.async_step_power()
        return self.async_show_form(
            step_id="more",
            data_schema=vol.Schema({vol.Required("add_another", default=False): bool}),
        )

    async def async_step_power(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._selected.update(user_input)
            self._selected[CONF_VEHICLES] = self._vehicles
            return self.async_create_entry(
                title="EasyWallbox Smart Charging", data=self._selected
            )
        return self.async_show_form(
            step_id="power", data_schema=_entities(POWER_FIELDS)
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> config_entries.OptionsFlow:
        return EasyWallboxSmartOptionsFlow()


class EasyWallboxSmartOptionsFlow(config_entries.OptionsFlowWithReload):
    """Edit source entities and any number of named vehicle profiles."""

    def __init__(self) -> None:
        self._working: dict[str, Any] | None = None
        self._editing_id: str | None = None
        self._deleting_id: str | None = None

    def _data(self) -> dict[str, Any]:
        """Merge initial data with later full options, safely copying profiles."""
        if self._working is None:
            merged = {**self.config_entry.data, **self.config_entry.options}
            merged[CONF_VEHICLES] = profiles_from_entry(merged)
            self._working = merged
        return self._working

    def _profiles(self) -> list[dict]:
        return self._data()[CONF_VEHICLES]

    def _choices(self) -> dict[str, str]:
        return {v["id"]: v["name"] for v in self._profiles()}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._data()
        return self.async_show_menu(
            step_id="init",
            menu_options=["wallbox", "vehicles", "power", "finish"],
        )

    async def async_step_wallbox(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            _remove_missing(self._data(), WALLBOX_FIELDS, user_input)
            return await self.async_step_init()
        return self.async_show_form(
            step_id="wallbox",
            data_schema=self.add_suggested_values_to_schema(
                _entities(WALLBOX_FIELDS), self._data()
            ),
        )

    async def async_step_vehicles(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        menu = ["add_vehicle"]
        if self._profiles():
            menu.append("select_vehicle")
            if len(self._profiles()) > 1:
                menu.append("remove_vehicle")
        menu.append("init")
        return self.async_show_menu(step_id="vehicles", menu_options=menu)

    async def async_step_add_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                profile = build_vehicle(user_input, self._profiles())
            except (ValueError, KeyError, TypeError):
                errors["base"] = "invalid_vehicle"
            else:
                self._profiles().append(profile)
                return await self.async_step_vehicles()
        return self.async_show_form(
            step_id="add_vehicle", data_schema=_vehicle_form(), errors=errors
        )

    async def async_step_select_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._editing_id = user_input["vehicle_id"]
            return await self.async_step_edit_vehicle()
        return self.async_show_form(
            step_id="select_vehicle",
            data_schema=vol.Schema({
                vol.Required("vehicle_id"): vol.In(self._choices())
            }),
        )

    async def async_step_edit_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        old = next(
            v for v in self._profiles() if v["id"] == self._editing_id
        )
        errors = {}
        if user_input is not None:
            try:
                updated = build_vehicle(
                    user_input, self._profiles(), vehicle_id=old["id"]
                )
            except (ValueError, KeyError, TypeError):
                errors["base"] = "invalid_vehicle"
            else:
                self._profiles()[
                    next(i for i, v in enumerate(self._profiles())
                         if v["id"] == old["id"])
                ] = updated
                self._editing_id = None
                return await self.async_step_vehicles()
        defaults = dict(old)
        defaults.pop("id", None)
        return self.async_show_form(
            step_id="edit_vehicle",
            data_schema=self.add_suggested_values_to_schema(
                _vehicle_form(), defaults
            ),
            errors=errors,
        )

    async def async_step_remove_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if len(self._profiles()) <= 1:
            return await self.async_step_vehicles()
        if user_input is not None:
            self._deleting_id = user_input["vehicle_id"]
            return await self.async_step_confirm_remove()
        return self.async_show_form(
            step_id="remove_vehicle",
            data_schema=vol.Schema({
                vol.Required("vehicle_id"): vol.In(self._choices())
            }),
        )

    async def async_step_confirm_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            if user_input["confirm"]:
                self._data()[CONF_VEHICLES] = [
                    v for v in self._profiles() if v["id"] != self._deleting_id
                ]
            self._deleting_id = None
            return await self.async_step_vehicles()
        return self.async_show_form(
            step_id="confirm_remove",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
        )

    async def async_step_power(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            _remove_missing(self._data(), POWER_FIELDS, user_input)
            return await self.async_step_init()
        return self.async_show_form(
            step_id="power",
            data_schema=self.add_suggested_values_to_schema(
                _entities(POWER_FIELDS), self._data()
            ),
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self._profiles():
            return self.async_show_form(
                step_id="finish",
                data_schema=vol.Schema({}),
                errors={"base": "vehicle_required"},
            )
        return self.async_create_entry(data=self._data())
