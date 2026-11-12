"""Configuration keys for the read-only EasyWallbox Smart pre-alpha."""

DOMAIN = "easywallbox_smart"
CONF_VEHICLES = "vehicles"

# Source sensors only: these fields never address actuators.
WALLBOX_FIELDS = {
    "wallbox_car_connected": ["binary_sensor", "sensor"],
    "wallbox_charging": ["binary_sensor"],
    "wallbox_telemetry_fresh": ["binary_sensor"],
    "wallbox_ble_connection": ["binary_sensor", "sensor"],
    "wallbox_fault": ["binary_sensor", "sensor"],
}

POWER_FIELDS = {
    "power_ground": ["sensor"],
    "power_first_floor": ["sensor"],
    "power_wallbox": ["sensor"],
}

# Profiles are not tied to vehicle makes/models.
VEHICLE_KEYS = (
    "name", "soc", "connected", "charging",
    "capacity_kwh", "default_target_soc",
)
