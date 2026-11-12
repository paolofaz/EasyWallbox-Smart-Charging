"""Graphical entity mapping, without commands to wallbox or vehicles."""

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import CAR_FIELDS, DOMAIN, POWER_FIELDS, WALLBOX_FIELDS


def _entity_schema(fields: dict[str, list[str]]) -> vol.Schema:
    """Build a UI-only schema for existing HA entities."""
    return vol.Schema(
        {
            vol.Optional(key): EntitySelector(EntitySelectorConfig(domain=domains))
            for key, domains in fields.items()
        }
    )


class EasyWallboxSmartConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one configuration entry using three short UI steps."""

    VERSION = 1

    def __init__(self) -> None:
        """Hold selected entity IDs until the last step."""
        self._selected: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select read-only wallbox state sources."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            self._selected.update(user_input)
            return await self.async_step_cars()
        return self.async_show_form(
            step_id="user", data_schema=_entity_schema(WALLBOX_FIELDS)
        )

    async def async_step_cars(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select the car sensors and SOC targets."""
        if user_input is not None:
            self._selected.update(user_input)
            return await self.async_step_power()
        return self.async_show_form(
            step_id="cars", data_schema=_entity_schema(CAR_FIELDS)
        )

    async def async_step_power(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select the three power sources and complete setup."""
        if user_input is not None:
            self._selected.update(user_input)
            return self.async_create_entry(
                title="EasyWallbox Smart Charging", data=self._selected
            )
        return self.async_show_form(
            step_id="power", data_schema=_entity_schema(POWER_FIELDS)
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> config_entries.OptionsFlow:
        """Allow existing mappings to be edited after installation."""
        return EasyWallboxSmartOptionsFlow()


class EasyWallboxSmartOptionsFlow(config_entries.OptionsFlowWithReload):
    """Override mapped entity IDs and reload when options are saved."""

    def __init__(self) -> None:
        """Collect each options page; empty strings explicitly clear old fields."""
        self._selected: dict[str, str] = {}

    def _current(self) -> dict[str, str]:
        """Use options as authoritative, falling back to original setup data."""
        return {**self.config_entry.data, **self.config_entry.options}

    def _capture(
        self, fields: dict[str, list[str]], user_input: dict[str, Any]
    ) -> None:
        """Include blank values to let users clear previous selections."""
        for key in fields:
            self._selected[key] = user_input.get(key, "")

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit wallbox sources."""
        if user_input is not None:
            self._capture(WALLBOX_FIELDS, user_input)
            return await self.async_step_cars()
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _entity_schema(WALLBOX_FIELDS), self._current()
            ),
        )

    async def async_step_cars(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit vehicle sources."""
        if user_input is not None:
            self._capture(CAR_FIELDS, user_input)
            return await self.async_step_power()
        return self.async_show_form(
            step_id="cars",
            data_schema=self.add_suggested_values_to_schema(
                _entity_schema(CAR_FIELDS), self._current()
            ),
        )

    async def async_step_power(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit power measurements and save all options."""
        if user_input is not None:
            self._capture(POWER_FIELDS, user_input)
            return self.async_create_entry(data=self._selected)
        return self.async_show_form(
            step_id="power",
            data_schema=self.add_suggested_values_to_schema(
                _entity_schema(POWER_FIELDS), self._current()
            ),
        )
