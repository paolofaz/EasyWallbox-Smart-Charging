"""Pure, HA-independent vehicle profile handling.

No SOC readings, device commands or session state are implemented here.
"""

from uuid import uuid4

from .const import CONF_VEHICLES


def _check_profile(values: dict, others: list[dict], vehicle_id: str | None) -> None:
    """Reject duplicate vehicles and physically unusable nominal settings."""
    name = str(values.get("name", "")).strip()
    if not name:
        raise ValueError("invalid_vehicle_name")
    if any(
        v["name"].strip().casefold() == name.casefold()
        and v["id"] != vehicle_id
        for v in others
    ):
        raise ValueError("duplicate_vehicle")
    soc = values.get("soc")
    connected = values.get("connected")
    if not soc or not connected:
        raise ValueError("missing_vehicle_sensor")
    if any(
        v.get("soc") == soc and v["id"] != vehicle_id
        for v in others
    ):
        raise ValueError("duplicate_soc")
    capacity = float(values["capacity_kwh"])
    target = int(values["default_target_soc"])
    if not 1.0 <= capacity <= 250.0 or not 1 <= target <= 100:
        raise ValueError("invalid_vehicle_parameter")


def build_vehicle(
    values: dict, others: list[dict], *, vehicle_id: str | None = None
) -> dict:
    """Validate a form and return a stable-ID profile.

    The caller may reuse an existing ID when editing a saved profile.
    """
    _check_profile(values, others, vehicle_id)
    return {
        "id": vehicle_id or uuid4().hex,
        "name": values["name"].strip(),
        "soc": values["soc"],
        "connected": values["connected"],
        "charging": values.get("charging", ""),
        "capacity_kwh": float(values["capacity_kwh"]),
        "default_target_soc": int(values["default_target_soc"]),
    }


def profiles_from_entry(entry_data: dict) -> list[dict]:
    """Read new profiles; legacy v0.0.1 installs remain unchanged.

    A legacy entry has no usable capacity and must be reconfigured in the
    UI before any future planner is enabled. Never invent battery data.
    """
    return [dict(profile) for profile in entry_data.get(CONF_VEHICLES, [])]
