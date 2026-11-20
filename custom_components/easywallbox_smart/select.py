"""Two principal session modes. Other actions live on dedicated controls."""
from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN


async def async_setup_entry(hass, entry, add_entities):
    add_entities([ModeSelect(hass.data[DOMAIN][entry.entry_id], entry)])


class ModeSelect(SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Modalità di ricarica"
    _attr_icon = "mdi:car-cog"
    _attr_options = ["automatic", "manual"]
    _attr_should_poll = False

    def __init__(self, controller, entry):
        self.controller = controller
        self._attr_unique_id = entry.entry_id + "_mode"

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.add_listener(self._update))

    @callback
    def _update(self):
        self.async_write_ha_state()

    @property
    def current_option(self):
        return self.controller.mode

    async def async_select_option(self, option):
        if option not in self.options:
            raise HomeAssistantError("Modalità non valida")
        await self.controller.async_change("mode", option)
