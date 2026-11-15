"""Offline replay of anonymized *household-only* power CSV.

This is a TEST helper, not part of the Home Assistant integration. It makes
no network calls, writes no files, and cannot access any actual device.

Input format: timestamp,power,unit,quality
- timestamp: ISO 8601 with explicit UTC offset
- power: the ALREADY-AGGREGATED household load EXCLUDING EV, in W or kW
- unit: W or kW
- quality: ok | unavailable | stale | incoherent
Unknown measurements have an empty power cell and non-ok quality; never 0.
Do not commit real household occupancy/consumption traces to GitHub.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from math import isfinite
from typing import Callable


@dataclass(frozen=True)
class HouseholdSample:
    at: datetime
    kw: float | None
    quality: str


def read_household_csv(source: str) -> tuple[HouseholdSample, ...]:
    """Parse strict anonymized trace, preserving unavailable data as None."""
    reader = csv.DictReader(StringIO(source))
    if reader.fieldnames != ["timestamp", "power", "unit", "quality"]:
        raise ValueError("expected timestamp,power,unit,quality")
    result: list[HouseholdSample] = []
    last_at: datetime | None = None
    for line, row in enumerate(reader, 2):
        if None in row or any(x is None for x in row.values()):
            raise ValueError(f"malformed row {line}")
        try:
            at = datetime.fromisoformat(row["timestamp"].strip())
        except ValueError as exc:
            raise ValueError(f"invalid timestamp at row {line}") from exc
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError(f"timestamp must have timezone at row {line}")
        if last_at is not None and at <= last_at:
            raise ValueError(f"non-monotonic timestamp at row {line}")
        quality = row["quality"].strip()
        if quality not in ("ok", "unavailable", "stale", "incoherent"):
            raise ValueError(f"unknown quality at row {line}")
        raw = row["power"].strip()
        if not raw:
            if quality == "ok":
                raise ValueError(f"missing trusted value at row {line}")
            kw = None
        else:
            try:
                value = float(raw)
            except ValueError as exc:
                raise ValueError(f"invalid power at row {line}") from exc
            if not isfinite(value) or value < 0:
                raise ValueError(f"invalid power at row {line}")
            unit = row["unit"].strip()
            if unit not in ("W", "kW"):
                raise ValueError(f"invalid unit at row {line}")
            kw = value / 1000 if unit == "W" else value
            if quality != "ok":
                kw = None
        result.append(HouseholdSample(at, kw, quality))
        last_at = at
    if not result:
        raise ValueError("empty trace")
    return tuple(result)


def replay_trace(trace, core, session_at: Callable, *, confirmed_kw=4.0, cfg=None):
    """Produce (sample, virtual proposal) tuples with a synthetic EV session.

    session_at must return an explicitly constructed, simulation-only
    SessionSnapshot; the source file alone does NOT prove an EV was charging.
    """
    previous = None
    output = []
    for sample in trace:
        house = core.HouseSnapshot(
            None, None,
            "ok" if sample.quality == "ok" and sample.kw is not None else "unavailable",
            sources_kw=(sample.kw,),
        )
        limits = core.LimitSnapshot(confirmed_kw, confirmed_kw)
        previous, proposal = core.evaluate(
            sample.at, session_at(sample.at), house, limits, previous,
            cfg or core.Config(),
        )
        output.append((sample, proposal))
    return tuple(output)
