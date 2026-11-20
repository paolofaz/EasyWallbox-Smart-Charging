"""Per-session intent buttons. Pause button never sends a DPM command."""
from homeassistant.components.button import ButtonEntity
from homeassistant.core import callback
from .const import DOMAIN


BUTTONS = {
    "now": ("Carica subito", "mdi:flash"),
    "pause": ("Pausa esplicita (solo gestione)", "mdi:pause-circle-outline"),
    "clear_pause": ("Riprendi gestione", "mdi:play-circle-outline"),
    "clear_departure": ("Annulla eccezione partenza", "mdi:calendar-remove"),
}


async def async_setup_entry(hass, entry, add_entities):
    c = hass.data[DOMAIN][entry.entry_id]
    add_entities([RCButton(c, entry, kind) for kind in BUTTONS])


class RCButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller, entry, kind):
        self.controller, self.kind = controller, kind
        self._attr_name, self._attr_icon = BUTTONS[kind]
        self._attr_unique_id = entry.entry_id + "_button_" + kind

    async def async_press(self):
        if self.kind == "clear_departure":
            await self.controller.async_change("departure", None)
        else:
            await self.controller.async_change(self.kind, True)
