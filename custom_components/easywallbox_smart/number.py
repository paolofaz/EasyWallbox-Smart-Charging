"""Optional fixed SOC target control, only for opted-in local-stop vehicles.

An existing HA input_number used as a target remains the source of truth:
no duplicate slider is created for that vehicle.
"""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_CABLE, CONF_NAME, CONF_STOP_AT_TARGET, CONF_TARGET_FIXED, CONF_VEHICLES, DOMAIN
from .device import controller_device_info


async def async_setup_entry(hass, entry, add_entities):
    controller = hass.data[DOMAIN][entry.entry_id]
    add_entities([
        FixedVehicleSOCTarget(controller, entry, car)
        for car in controller.cfg[CONF_VEHICLES]
        if car.get(CONF_STOP_AT_TARGET) is True and CONF_TARGET_FIXED in car
    ])


class FixedVehicleSOCTarget(NumberEntity):
    """User-controlled target for vehicles without an existing target entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_min_value = 80.0
    _attr_native_max_value = 100.0
    _attr_native_step = 5.0
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:battery-charging-80"

    def __init__(self, controller, entry, car):
        self.controller = controller
        self.cable = car[CONF_CABLE]
        self._attr_name = f"Limite SOC {car[CONF_NAME]}"
        self._attr_unique_id = f"{entry.entry_id}_soc_target_{self.cable}"
        self._attr_device_info = controller_device_info(entry)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.add_listener(self._update))

    @callback
    def _update(self):
        self.async_write_ha_state()

    @property
    def native_value(self):
        car = next((c for c in self.controller.cfg[CONF_VEHICLES]
                    if c[CONF_CABLE] == self.cable), None)
        return self.controller.fixed_target(car) if car else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.controller.async_set_fixed_target(self.cable, value)
        except ValueError as ex:
            raise HomeAssistantError(str(ex)) from ex
