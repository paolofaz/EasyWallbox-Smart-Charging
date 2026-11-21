"""EasyWallbox Smart Charging RC — explicit real-control opt-in."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import entity_registry as er

from .const import *
from .rc_controller import RCController


def _remove_superseded_controls(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove only this entry's six retired UI controls, not user entities.

    No direct changes to HA .storage, and no deletion of real ESPHome
    switch or other users' entity registry entries.
    """
    reg = er.async_get(hass)
    retired = [
        ("switch", entry.entry_id + "_real"),
        ("button", entry.entry_id + "_button_now"),
        ("button", entry.entry_id + "_button_pause"),
        ("button", entry.entry_id + "_button_clear_pause"),
        ("button", entry.entry_id + "_button_clear_departure"),
        ("datetime", entry.entry_id + "_departure_override"),
    ]
    for domain, unique_id in retired:
        entity_id = reg.async_get_entity_id(domain, DOMAIN, unique_id)
        if entity_id:
            found = reg.async_get(entity_id)
            if found is not None and found.config_entry_id == entry.entry_id:
                reg.async_remove(entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Only new RC config entries have the required proof/command sources."""
    required = (
        CONF_HOUSE_SOURCES, CONF_EV_POWER, CONF_WALLBOX_CONNECTED,
        CONF_WALLBOX_CHARGING, CONF_TELEMETRY_FRESH, CONF_DPM_ACTIVE,
        CONF_WALLBOX_FAULT, CONF_CHARGE_ENABLED, CONF_START_STOP,
        CONF_COMMAND_STATUS, CONF_REQUESTED_LIMIT, CONF_CONFIRMED_LIMIT,
        CONF_DPM_CONFIRMED, CONF_WALLBOX_REFRESH, CONF_EXPECTED_DPM, CONF_BASE_KW,
        CONF_BOOST_KW, CONF_VEHICLES,
    )
    cfg = {**entry.data, **entry.options}
    if any(k not in cfg for k in required):
        raise ConfigEntryError(
            "RC requires a new GUI configuration including Start-Stop, DPM "
            "confirmation, command status, DPM Active and Wallbox Fault. "
            "Never migrate an old beta by guessing missing entities."
        )
    coordinator = RCController(hass, entry)
    await coordinator.async_load()
    try:
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        coordinator.start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _remove_superseded_controls(hass, entry)
    except Exception:
        await coordinator.async_close()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.async_close()
    return ok
