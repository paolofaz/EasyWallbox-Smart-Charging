"""Exactly one effective SOC target source per vehicle.

Pure, read-only policy. Entries from Marketplace 0.1.0 had no target_mode
and could store both fields: infer the previous precedence, never silently
switch to a fixed target when a chosen HA entity is unavailable.
"""
from __future__ import annotations

from collections.abc import Mapping

from .const import CONF_TARGET_MODE, CONF_TARGET_ENTITY, CONF_TARGET_DEFAULT
from .sources import finite_number

ENTITY = "entity"
FIXED = "fixed"
MODES = frozenset((ENTITY, FIXED))


def selected_mode(vehicle: Mapping) -> str | None:
    """Infer mode only for older entries without an explicit selection."""
    mode = vehicle.get(CONF_TARGET_MODE)
    if mode is not None:
        return mode if isinstance(mode, str) and mode in MODES else None
    return ENTITY if vehicle.get(CONF_TARGET_ENTITY) else FIXED


def resolved_target(vehicle: Mapping, entity_state: object | None = None) -> float | None:
    """Read a valid percentage target, or return None (never guess/fallback).

    entity_state is a Home Assistant state object, supplied by the adapter.
    We accept entities without a unit (some car integrations publish raw
    percentages), or an explicit % unit, but reject unrelated measurements.
    """
    mode = selected_mode(vehicle)
    if mode == ENTITY:
        if not isinstance(vehicle.get(CONF_TARGET_ENTITY), str):
            return None
        if entity_state is None:
            return None
        attrs = getattr(entity_state, "attributes", None)
        unit = attrs.get("unit_of_measurement") if isinstance(attrs, Mapping) else None
        if unit not in (None, "", "%"):
            return None
        raw = getattr(entity_state, "state", None)
    elif mode == FIXED:
        raw = vehicle.get(CONF_TARGET_DEFAULT)
    else:
        return None
    value = finite_number(raw)
    if value is None or not 1 <= value <= 100:
        return None
    return value
