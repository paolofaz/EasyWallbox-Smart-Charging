"""Preferred start clock for the current/next delayed session."""
from homeassistant.components.time import TimeEntity
from homeassistant.core import callback
from .const import DOMAIN


async def async_setup_entry(hass, entry, add_entities):
    add_entities([PreferredStartTime(hass.data[DOMAIN][entry.entry_id], entry)])


class PreferredStartTime(TimeEntity):
    _attr_has_entity_name = True
    _attr_name = "Ora inizio ricarica preferita"
    _attr_icon = "mdi:clock-outline"
    _attr_should_poll = False

    def __init__(self, controller, entry):
        self.controller = controller
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
        await self.controller.async_change("time", value)
