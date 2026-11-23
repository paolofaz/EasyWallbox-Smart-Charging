"""Validate manually selected ESPHome roles without guessing entity names."""
from .const import (CONF_CHARGE_STATE, CONF_WALLBOX_POWER_SWITCH, CONF_SESSION_ENERGY,
                    CONF_SESSION_DURATION, CONF_START_STOP, CONF_VEHICLES,
                    CONF_VEHICLE_REFRESH, CONF_TELEMETRY_FRESH, WALLBOX_ENTITIES)


def mapping_error(hass, config):
    """Commands and their independent readbacks must belong to one wallbox."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    anchor = registry.async_get(config.get(CONF_START_STOP, ""))
    if anchor is None or not anchor.device_id:
        return "invalid_wallbox_mapping"
    if len({config.get(key) for key in WALLBOX_ENTITIES}) != len(WALLBOX_ENTITIES):
        return "invalid_wallbox_mapping"
    for key, domain in WALLBOX_ENTITIES.items():
        entity_id = config.get(key)
        item = registry.async_get(entity_id) if entity_id else None
        if (item is None or item.disabled_by is not None or
                item.device_id != anchor.device_id or item.platform != "esphome" or
                item.domain != domain):
            return "invalid_wallbox_mapping"
    optional_sensors = [
        config.get(key) for key in
        (CONF_CHARGE_STATE, CONF_SESSION_ENERGY, CONF_SESSION_DURATION)
        if config.get(key)]
    if len(set(optional_sensors)) != len(optional_sensors):
        return "invalid_wallbox_mapping"
    for sensor in optional_sensors:
        state_item = registry.async_get(sensor)
        if (state_item is None or state_item.disabled_by is not None or
                state_item.device_id != anchor.device_id or
                state_item.platform != "esphome" or state_item.domain != "sensor" or
                sensor in (config.get(key) for key in WALLBOX_ENTITIES)):
            return "invalid_wallbox_mapping"
    telemetry = config.get(CONF_TELEMETRY_FRESH)
    if telemetry:
        item = registry.async_get(telemetry)
        if (item is None or item.disabled_by is not None or
                item.device_id != anchor.device_id or
                item.platform != "esphome" or item.domain != "binary_sensor" or
                telemetry in (config.get(key) for key in WALLBOX_ENTITIES)):
            return "invalid_wallbox_mapping"
    relay = config.get(CONF_WALLBOX_POWER_SWITCH)
    if relay:
        item = registry.async_get(relay)
        if (item is None or item.disabled_by is not None or
                item.domain != "switch" or item.device_id is None or
                item.device_id == anchor.device_id or
                relay in (config.get(key) for key in WALLBOX_ENTITIES)):
            return "invalid_wallbox_power_switch"
    for car in config.get(CONF_VEHICLES, ()):
        button = car.get(CONF_VEHICLE_REFRESH)
        if button:
            item = registry.async_get(button)
            if item is None or item.disabled_by is not None or item.domain != "button" or item.device_id == anchor.device_id:
                return "vehicle_refresh_is_not_vehicle_button"
    return None
