"""Resolve ESPHome wallbox telemetry by Home Assistant device registry.

Only the Start-Stop entity and Shelly meters are selected by the user.
Look up required sensor names from the SAME ESPHome device. Never
infer across devices, choose the first ambiguous match, or disable
an electrical safety check just to make configuration shorter.
"""
from __future__ import annotations

import re
from .const import (
    CONF_BLE_CONNECTED, CONF_CHARGE_ENABLED, CONF_COMMAND_STATUS,
    CONF_CONFIRMED_LIMIT, CONF_DPM_ACTIVE, CONF_DPM_CONFIRMED,
    CONF_REQUESTED_LIMIT, CONF_START_STOP, CONF_TELEMETRY_FRESH,
    CONF_WALLBOX_CHARGING, CONF_WALLBOX_CONNECTED, CONF_WALLBOX_FAULT,
    CONF_WALLBOX_REFRESH,
)

ESP_NAMED = {
    CONF_WALLBOX_CONNECTED: ("binary_sensor", "Car Connected"),
    CONF_BLE_CONNECTED: ("binary_sensor", "Connection"),
    CONF_WALLBOX_CHARGING: ("binary_sensor", "Charging"),
    CONF_TELEMETRY_FRESH: ("binary_sensor", "Telemetry Fresh"),
    CONF_DPM_ACTIVE: ("binary_sensor", "DPM Active"),
    CONF_WALLBOX_FAULT: ("binary_sensor", "Wallbox Fault"),
    CONF_CHARGE_ENABLED: ("binary_sensor", "Charge Enabled"),
    CONF_COMMAND_STATUS: ("sensor", "BLE Command Status"),
    CONF_REQUESTED_LIMIT: ("number", "Charge power"),
    CONF_CONFIRMED_LIMIT: ("sensor", "Power set"),
    CONF_DPM_CONFIRMED: ("sensor", "Limit house power set -DPM-"),
    CONF_WALLBOX_REFRESH: ("button", "Refresh Data"),
}
OPTIONAL = frozenset({CONF_BLE_CONNECTED})


class DiscoveryError(ValueError):
    """Cannot safely resolve a required or unique ESPHome entity."""


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _matches(entry, domain: str, label: str) -> bool:
    if getattr(entry, "domain", entry.entity_id.split(".", 1)[0]) != domain:
        return False
    candidates = [
        getattr(entry, "original_name", None),
        getattr(entry, "original_name_unprefixed", None),
    ]
    exact = _normal(label)
    for raw in candidates:
        if not raw:
            continue
        val = _normal(raw)
        if val == exact or val == "wallbox" + exact:
            return True
    # Last resort for firmware revisions with no original_name: entity ID
    # can have a device prefix, but must match the complete trailing slug.
    if not any(candidates):
        tail = _normal(entry.entity_id.rsplit(".", 1)[1])
        return tail == exact or tail == "wallbox" + exact
    return False


def resolve_from_entries(start_stop: str, entries: list) -> dict[str, str]:
    """Pure helper that rejects ambiguous or missing required fields."""
    out = {CONF_START_STOP: start_stop}
    for key, (domain, name) in ESP_NAMED.items():
        possible = [
            item.entity_id for item in entries
            if getattr(item, "disabled_by", None) is None
            and _matches(item, domain, name)
        ]
        if not possible and key in OPTIONAL:
            continue
        if len(possible) != 1:
            raise DiscoveryError(
                "Ambiguous or missing ESPHome entity " + name + ": "
                + str(len(possible)) + " matches"
            )
        out[key] = possible[0]
    if len(set(out.values())) != len(out):
        raise DiscoveryError("Duplicate ESPHome entity mapping")
    return out


def discover_from_start_stop(hass, switch_id: str) -> dict[str, str]:
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    anchor = registry.async_get(switch_id)
    if (anchor is None or anchor.domain != "switch"
            or not anchor.device_id or anchor.disabled_by is not None):
        raise DiscoveryError("Start-Stop has no usable ESPHome device")
    entries = [
        x for x in er.async_entries_for_device(registry, anchor.device_id)
        if x.platform == anchor.platform
    ]
    found = resolve_from_entries(switch_id, entries)
    return found
