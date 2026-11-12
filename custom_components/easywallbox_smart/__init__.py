"""EasyWallbox Smart Charging: configuration-only pre-alpha.

This milestone registers a config entry and MUST NOT call any device service.
No HA state listeners, polling or entities are installed yet.
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Accept a configuration entry without acting on any device."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the configuration-only integration."""
    return True
