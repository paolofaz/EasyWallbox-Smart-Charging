"""Configuration keys and entity domains for read-only Home Assistant sources."""

DOMAIN = "easywallbox_smart"

# Only state sources are selectable. No switch, button or service-action targets.
# Everything is optional in the pre-alpha: no planner runs until later milestones.
WALLBOX_FIELDS = {
    "wallbox_car_connected": ["binary_sensor", "sensor"],
    "wallbox_charging": ["binary_sensor"],
    "wallbox_telemetry_fresh": ["binary_sensor"],
    "wallbox_ble_connection": ["binary_sensor", "sensor"],
    "wallbox_fault": ["binary_sensor", "sensor"],
}

CAR_FIELDS = {
    "fiat_cable": ["binary_sensor"],
    "fiat_charging": ["binary_sensor"],
    "fiat_soc": ["sensor"],
    "fiat_target": ["input_number", "number", "sensor"],
    "kia_cable": ["binary_sensor"],
    "kia_charging": ["binary_sensor"],
    "kia_soc": ["sensor"],
    "kia_target": ["number", "sensor"],
}

POWER_FIELDS = {
    "power_ground": ["sensor"],
    "power_first_floor": ["sensor"],
    "power_wallbox": ["sensor"],
}
