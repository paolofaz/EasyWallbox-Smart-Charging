"""EasyWallbox Smart Charging passive simulation, no device commands."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_VEHICLES
from .power_model import migrate_legacy


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register the read-only sensor platform; no service or BLE calls."""
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload sensors; config entry callbacks are released automatically."""
    return await hass.config_entries.async_unload_platforms(entry, ["sensor"])

async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Upgrade old layouts without losing sensors, vehicles or user options."""
    if entry.version > 3:
        return False
    if entry.version in (1, 2):
        data = dict(entry.data)
        data.setdefault(CONF_VEHICLES, [])
        combined = {**data, **entry.options}
        data.update(migrate_legacy(combined))
        hass.config_entries.async_update_entry(
            entry, data=data, version=3, minor_version=1
        )
    return True
