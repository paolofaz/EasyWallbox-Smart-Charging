"""Read-only Home Assistant simulation lifecycle with non-destructive entry guard.

No migration is attempted here. A legacy 0.0.13 config entry with an old
vehicle/energy layout stays intact, even if the new code is mistakenly copied
onto an existing HA installation.
"""
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryError
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import SimulationCoordinator
from .preflight import inspect, LEGACY


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Start a simulation only when the entry has an explicitly valid mapping."""
    report = inspect(entry.data, entry.options)
    if report.kind == LEGACY:
        raise ConfigEntryError(
            "EasyWallbox Smart Charging 0.0.13 configuration was preserved. "
            "Automatic migration is intentionally disabled. "
            "Use the documented backup and guided reconfiguration procedure."
        )
    if not report.ready:
        # Issue codes describe categories only, never user entity IDs.
        raise ConfigEntryError(
            "EasyWallbox Smart Charging simulation mapping is incomplete or "
            "invalid (" + ", ".join(report.issues) + "). "
            "No configuration was changed."
        )
    coordinator = SimulationCoordinator(hass, entry)
    try:
        coordinator.start()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        # Release any listeners/timers allocated before a setup failure.
        coordinator.close()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unload platforms first, then release read-only listeners and timers."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        coordinator.close()
