"""EasyWallbox Smart Charging: configuration-only pre-alpha.

This milestone registers a config entry and MUST NOT call any device service.
No HA state listeners, polling or entities are installed yet.
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_VEHICLES


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Accept a configuration entry without acting on any device."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the configuration-only integration."""
    return True

async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Upgrade v0.0.1 entries without guessing battery capacity or vehicle IDs.

    Keep legacy fields untouched; users can add complete vehicle profiles
    under Options. The read-only integration remains safe during migration.
    """
    if entry.version == 1:
        data = dict(entry.data)
        data.setdefault(CONF_VEHICLES, [])
        hass.config_entries.async_update_entry(
            entry, data=data, version=2, minor_version=1
        )
