"""Persistent preferences and volatile (re-arm after reboot) real control."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN


SWITCHES = {
    "real": ("Controllo reale", "mdi:shield-check"),
    "delay": ("Avvio posticipato", "mdi:clock-start"),
}


async def async_setup_entry(hass, entry, add_entities):
    c = hass.data[DOMAIN][entry.entry_id]
    add_entities([RCSwitch(c, entry, kind) for kind in SWITCHES])


class RCSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller, entry, kind):
        self.controller, self.kind = controller, kind
        self._attr_name, self._attr_icon = SWITCHES[kind]
        self._attr_unique_id = entry.entry_id + "_" + kind

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.add_listener(self._update))

    @callback
    def _update(self):
        self.async_write_ha_state()

    @property
    def is_on(self):
        return {"real": self.controller.real_enabled,
                "delay": self.controller.delay_enabled}[self.kind]

    async def async_turn_on(self, **kwargs):
        try:
            await self.controller.async_change(self.kind, True)
        except ValueError as ex:
            raise HomeAssistantError(str(ex)) from ex

    async def async_turn_off(self, **kwargs):
        await self.controller.async_change(self.kind, False)
