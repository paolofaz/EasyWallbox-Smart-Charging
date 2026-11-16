"""Integration constants. No entity ID is tied to any particular home."""
DOMAIN = "easywallbox_smart"
PLATFORMS = ["sensor", "select"]
CONF_HOUSE_SOURCES = "house_power_sources"
CONF_SESSION_ENERGY = "session_energy"
CONF_SESSION_DURATION = "session_duration"
# Historical 0.1.0 fields are read only to support an existing config entry.
CONF_DOWNSTAIRS = "house_downstairs"
CONF_UPSTAIRS = "house_upstairs"
CONF_EV_POWER = "ev_power"
CONF_WALLBOX_CONNECTED = "wallbox_connected"
CONF_WALLBOX_CHARGING = "wallbox_charging"
CONF_TELEMETRY_FRESH = "telemetry_fresh"
CONF_REQUESTED_LIMIT = "requested_limit"
CONF_CONFIRMED_LIMIT = "confirmed_limit"
CONF_DPM_MODEL = "dpm_model_kw"
CONF_DPM_CONFIRMED = "dpm_confirmed"  # optional read-only ESPHome sensor
CONF_VEHICLES = "vehicles"
CONF_VEHICLE_OVERRIDES = "vehicle_overrides"
CONF_NAME = "name"
CONF_CABLE = "cable"
CONF_SOC = "soc"
CONF_TARGET_ENTITY = "target_entity"
CONF_TARGET_MODE = "target_mode"  # entity | fixed; absent in old 0.1.0 entries
CONF_TARGET_DEFAULT = "target_default"
CONF_CAPACITY = "capacity_kwh"
# Old 0.1.0 stored an estimated charge power; it is no longer used.
CONF_SUSTAINABLE = "sustainable_kw"
CONF_EFFICIENCY = "efficiency"
CONF_DEPARTURE_WEEKDAY = "departure_weekday"
CONF_DEPARTURE_WEEKEND = "departure_weekend"
CONF_ADD_ANOTHER = "add_another"
SIMULATION_LABEL = "SIMULAZIONE — NESSUN COMANDO"

# Options for upcoming supervised sessions (currently advisory/config only).
CONF_INITIAL_CHARGE_KW = "initial_charge_kw"
CONF_MAX_CHARGE_KW = "max_charge_kw"
DEFAULT_INITIAL_CHARGE_KW = 3.6
DEFAULT_MAX_CHARGE_KW = 4.0
# Explicit opt-in to an always-charging, two-band field shadow simulation.
CONF_SHADOW_LAB_ENABLED = "shadow_lab_enabled"
