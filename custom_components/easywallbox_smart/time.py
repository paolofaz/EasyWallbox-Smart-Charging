"""User-selected not-before time for a one-shot delayed charge."""
from homeassistant.components.time import TimeEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN
from .device import controller_device_info


async def async_setup_entry(hass, entry, add_entities):
    add_entities([PreferredStartTime(hass.data[DOMAIN][entry.entry_id], entry)])


class PreferredStartTime(TimeEntity):
    _attr_has_entity_name = True
    _attr_name = "Inizia non prima delle"
    _attr_icon = "mdi:clock-outline"
    _attr_should_poll = False

    def __init__(self, controller, entry):
        self.controller = controller
        self._attr_device_info = controller_device_info(entry)
        self._attr_unique_id = entry.entry_id + "_preferred_start"

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.add_listener(self._update))

    @callback
    def _update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self.controller.preferred_start

    async def async_set_value(self, value):
        try:
            await self.controller.async_change("time", value)
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error
