"""Register bundled history card as a resource; do not create any dashboard."""
from __future__ import annotations

from homeassistant.components import frontend
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
from homeassistant.exceptions import HomeAssistantError

RESOURCE_PATH = "/easywallbox_smart/session-history-card.js"
RESOURCE_URL = RESOURCE_PATH + "?v=0.9.0b1"


async def async_register_card_resource(hass) -> None:
    """Register once, preserving unrelated user resources and dashboard views."""
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None:
        raise HomeAssistantError("Lovelace is not initialized")
    if lovelace.resource_mode != MODE_STORAGE:
        # Resource YAML mode is read-only: load module via HA frontend, no YAML edit.
        frontend.add_extra_js_url(hass, RESOURCE_URL)
        return
    resources = lovelace.resources
    # Explicitly load lazily stored resources before writing anything.
    await resources.async_get_info()
    matches = [item for item in resources.async_items()
               if item.get("url", "").split("?", 1)[0] == RESOURCE_PATH]
    if matches:
        first = matches[0]
        if first.get("url") != RESOURCE_URL or first.get("type") != "module":
            await resources.async_update_item(
                first["id"], {"url": RESOURCE_URL, "res_type": "module"})
    else:
        await resources.async_create_item(
            {"url": RESOURCE_URL, "res_type": "module"})
