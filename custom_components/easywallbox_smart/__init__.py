"""EasyWallbox Smart Charging beta — supervised release candidate."""
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import config_validation as cv
from homeassistant.loader import async_get_loaded_integration

from .const import *
from .controller import ChargingController
from .session_api import register_archive_endpoints
from .lovelace_resources import async_register_card_resource
from .wallbox_mapping import mapping_error


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register authenticated history API and bundled card resource."""
    register_archive_endpoints(hass)
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            "/easywallbox_smart/session-history-card.js",
            Path(__file__).parent / "frontend" / "session-history-card.js",
            False,
        )
    ])
    await async_register_card_resource(hass)
    return True


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Only new beta config entries have the required proof/command sources."""
    required = (*WALLBOX_ENTITIES, CONF_HOUSE_SOURCES, CONF_EV_POWER,
                CONF_EXPECTED_DPM, CONF_BASE_KW, CONF_VEHICLES)
    cfg = {**entry.data, **entry.options}
    missing = any(not cfg.get(key) for key in required)
    reason = "incomplete_wallbox" if missing else mapping_error(hass, cfg)
    if reason == "vehicle_refresh_is_not_vehicle_button":
        raise ConfigEntryError(
            "Opzioni > Modifica auto: scegli un pulsante dati del veicolo "
            "oppure lascia vuota la selezione. Verifica che sia abilitato.")
    if reason:
        if not cfg.get(CONF_CHARGE_ENABLED):
            raise ConfigEntryError(
                "Aggiornamento 1.0: apri Opzioni > Wallbox e seleziona "
                "Charge Enabled di ESPHome (conferma indipendente Start-Stop). "
                "Il vecchio sensore numerico DPM non serve più. "
                "I profili delle auto restano conservati.")
        raise ConfigEntryError(
            "Verifica le sette associazioni obbligatorie ESPHome in Opzioni > Wallbox, "
            "incluse Connection e Charge Enabled. I profili delle auto sono conservati.")
    coordinator = ChargingController(hass, entry, str(async_get_loaded_integration(hass, DOMAIN).version))
    await coordinator.async_load()
    try:
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _remove_superseded_controls(hass, entry)
        coordinator.start()
    except Exception:
        await coordinator.async_close()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_close()
