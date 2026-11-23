"""Logical Home Assistant device for the charging controller.

The actual wallbox remains a separate ESPHome physical device. All entities
of this integration are grouped under one logical service device.
"""
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def controller_device_info(entry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="EasyWallbox Smart Charging",
        model="Home Assistant charging controller",
    )
