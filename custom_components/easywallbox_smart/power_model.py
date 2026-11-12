"""Source topology validation and power arithmetic (pure Python, no HA calls)."""

from dataclasses import dataclass
from math import isfinite
from numbers import Real

MODE_HOUSE = "house_sensors"
MODE_TOTAL = "total_minus_ev"
MODE_NONE = "unconfigured"
ENERGY_KEYS = ("energy_mode", "house_power_sources", "site_total_power", "ev_power_sensor")


def normalise(mode: str, values: dict) -> dict:
    """Require non-overlapping sources with no assumptions about the building."""
    if mode == MODE_NONE:
        return {"energy_mode": mode}
    ev = values.get("ev_power_sensor", "")
    if mode == MODE_HOUSE:
        house = values.get("house_power_sources", [])
        if not isinstance(house, list) or not house or any(
            not isinstance(item, str) or not item.startswith("sensor.")
            for item in house
        ) or len(set(house)) != len(house):
            raise ValueError("invalid_house_sources")
        if ev and (not isinstance(ev, str) or not ev.startswith("sensor.") or ev in house):
            raise ValueError("duplicate_ev")
        return {"energy_mode": mode, "house_power_sources": house,
                **({"ev_power_sensor": ev} if ev else {})}
    if mode == MODE_TOTAL:
        site = values.get("site_total_power", "")
        if not isinstance(site, str) or not site.startswith("sensor.") or (
            not isinstance(ev, str) or not ev.startswith("sensor.")
        ) or site == ev:
            raise ValueError("invalid_total_sources")
        return {"energy_mode": mode, "site_total_power": site, "ev_power_sensor": ev}
    raise ValueError("invalid_energy_mode")


def migrate_legacy(data: dict) -> dict:
    """Convert complete old mappings; never assume incomplete house coverage."""
    if "energy_mode" in data:
        return {}
    house = [data.get("power_ground"), data.get("power_first_floor")]
    ev = data.get("power_wallbox")
    if all(isinstance(s, str) and s.startswith("sensor.") for s in house) and (
        isinstance(ev, str) and ev.startswith("sensor.")
    ):
        try:
            return normalise(MODE_HOUSE, {
                "house_power_sources": house, "ev_power_sensor": ev,
            })
        except ValueError:
            pass
    return {"energy_mode": MODE_NONE}


@dataclass(frozen=True)
class Reading:
    value: float | None
    unit: str
    fresh: bool


@dataclass(frozen=True)
class Power:
    house_kw: float | None
    ev_kw: float | None
    total_kw: float | None
    quality: str


def _kw(reading: Reading | None) -> float | None:
    if reading is None or not reading.fresh or reading.value is None or (
        isinstance(reading.value, bool) or not isinstance(reading.value, Real)
    ) or not isfinite(reading.value) or reading.value < 0:
        return None
    if reading.unit not in ("W", "kW"):
        return None
    return float(reading.value) / (1000 if reading.unit == "W" else 1)


def calculate(config: dict, data: dict[str, Reading]) -> Power:
    """Compute once readings are proven current; no electrical command is possible."""
    mode = config.get("energy_mode", MODE_NONE)
    if mode == MODE_NONE:
        return Power(None, None, None, "unconfigured")
    if mode == MODE_HOUSE:
        ids = config.get("house_power_sources", [])
        if not ids:
            return Power(None, None, None, "invalid_configuration")
        house_values = [_kw(data.get(entity)) for entity in ids]
        if any(value is None for value in house_values):
            return Power(None, None, None, "house_unavailable")
        house = sum(house_values)
        ev_id = config.get("ev_power_sensor")
        if not ev_id:
            return Power(house, None, None, "house_only")
        ev = _kw(data.get(ev_id))
        return (Power(house, None, None, "ev_unavailable") if ev is None
                else Power(house, ev, house + ev, "ok"))
    if mode == MODE_TOTAL:
        site = _kw(data.get(config.get("site_total_power", "")))
        ev = _kw(data.get(config.get("ev_power_sensor", "")))
        if site is None or ev is None:
            return Power(None, None, None, "data_unavailable")
        if site + 0.05 < ev:
            return Power(None, None, None, "inconsistent_total_ev")
        return Power(max(0.0, site - ev), ev, site, "ok")
    return Power(None, None, None, "invalid_configuration")
