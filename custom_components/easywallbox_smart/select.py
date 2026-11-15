"""HA select for SIMULATED per-session user intent only.

Selecting an option cannot start, stop, pause, resume, or change a
physical wallbox. The state and warnings refer strictly to the planner.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, SIMULATION_LABEL
from .session_policy import AUTO, MANUAL, PAUSE, CHARGE_NOW

OPTION_TO_MODE = {
    "automatic": AUTO,
    "manual": MANUAL,
    "pause": PAUSE,
    "charge_now": CHARGE_NOW,
}
MODE_TO_OPTION = {mode: option for option, mode in OPTION_TO_MODE.items()}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SimulationModeSelect(coordinator, entry)])


class SimulationModeSelect(SelectEntity):
    """Per-vehicle-session mode; never a wallbox Start/Stop switch."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "session_mode"
    _attr_icon = "mdi:car-clock"

    def __init__(self, coordinator, entry):
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_session_mode"
        self._attr_options = list(OPTION_TO_MODE)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="EasyWallbox Smart Charging",
            manufacturer="EasyWallbox Smart Charging",
            model="Solo simulazione",
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.add_listener(self._changed))

    @callback
    def _changed(self):
        self.async_write_ha_state()

    @property
    def available(self):
        control = self.coordinator.control
        return bool(
            control
            and control.session_id
            and control.phase not in ("DISCONNECTED", "UNKNOWN")
        )

    @property
    def current_option(self) -> str | None:
        control = self.coordinator.control
        return MODE_TO_OPTION.get(control.mode) if control else None

    @property
    def extra_state_attributes(self):
        control = self.coordinator.control
        return {
            "simulation_only": True,
            "warning": SIMULATION_LABEL,
            "reconciliation_required": (
                control.requires_confirmation if control else False
            ),
            "observed_phase": control.phase if control else None,
            "user_intent": control.mode if control else None,
            "note": (
                "La selezione cambia solo la simulazione; "
                "non modifica la ricarica elettrica reale."
            ),
        }

    async def async_select_option(self, option: str) -> None:
        """Change an internal in-memory intent, not any device or HA source."""
        if option not in OPTION_TO_MODE:
            raise HomeAssistantError("Invalid simulation mode")
        try:
            self.coordinator.choose_mode(OPTION_TO_MODE[option])
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
