"""Home Assistant read-only simulated planner; never sends device commands."""
from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN, PLATFORMS, CONF_VEHICLES, CONF_DOWNSTAIRS, CONF_UPSTAIRS,
    CONF_EV_POWER, CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING,
    CONF_TELEMETRY_FRESH, CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT,
    CONF_DPM_MODEL,
)
from .coordinator import SimulationCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one simulated integration from its UI configuration."""
    required = (
        CONF_VEHICLES, CONF_DOWNSTAIRS, CONF_UPSTAIRS, CONF_EV_POWER,
        CONF_WALLBOX_CONNECTED, CONF_WALLBOX_CHARGING, CONF_TELEMETRY_FRESH,
        CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT, CONF_DPM_MODEL,
    )
    if any(key not in entry.data for key in required) or not entry.data.get(CONF_VEHICLES):
        # No destructive migration of the legacy 0.0.13 config entry.
        raise ConfigEntryNotReady(
            "Existing configuration requires a guided migration; no data was changed"
        )
    coordinator = SimulationCoordinator(hass, entry)
    coordinator.start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        coordinator.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unsubscribe timers and listeners before returning to idle."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        coordinator.close()
    return True
