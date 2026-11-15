"""Fresh Home Assistant setup for EasyWallbox Smart Charging v0.1 simulation.

An installation starts with an empty integration config entry and the GUI.
No migration, no device commands, no storage writes or external control.
"""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import DOMAIN, PLATFORMS
from .coordinator import SimulationCoordinator
from .validation import validate


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Start a simulation from an explicitly configured set of HA entities."""
    result = validate(entry.data, entry.options)
    if not result.ready:
        raise ConfigEntryError(
            "EasyWallbox Smart Charging: invalid configuration ("
            + ", ".join(result.issues)
            + "). Review the integration's selected entities and options."
        )
    coordinator = SimulationCoordinator(hass, entry)
    try:
        coordinator.start()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        coordinator.close()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unload read-only entities, then release local event subscriptions."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        coordinator.close()
