"""Read-only paginated session archive API and explicit administrator pruning.

The WebSocket endpoint returns only one page; never push the full archive into
a Home Assistant entity/Recorder. A separate admin action prunes on demand.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN


def _archive(hass, entry_id=None):
    entries = hass.data.get(DOMAIN, {})
    if entry_id:
        c = entries.get(entry_id)
    else:
        c = next(iter(entries.values())) if len(entries) == 1 else None
    return c.session_history if c is not None and c.session_history.enabled else None


@websocket_api.websocket_command({
    vol.Required("type"): DOMAIN + "/sessions",
    vol.Optional("entry_id"): str,
    vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("limit", default=20): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
})
@websocket_api.async_response
async def ws_sessions(hass, connection, msg):
    """Return at most 100 rows after user authentication via HA WebSocket."""
    archive = _archive(hass, msg.get("entry_id"))
    if archive is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND,
                              "Session archive not configured or entry ambiguous")
        return
    connection.send_result(msg["id"], archive.page(
        offset=msg["offset"], limit=msg["limit"]))


def register_archive_endpoints(hass):
    websocket_api.async_register_command(hass, ws_sessions)

    async def prune(call):
        archive = _archive(hass, call.data.get("entry_id"))
        if archive is None:
            raise ServiceValidationError("Session archive not configured or entry ambiguous")
        result = await archive.async_prune(call.data["keep_last"])
        return result if call.return_response else None

    async_register_admin_service(
        hass, DOMAIN, "prune_session_history", prune,
        schema=vol.Schema({
            vol.Required("keep_last"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100000)),
            vol.Optional("entry_id"): str,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
