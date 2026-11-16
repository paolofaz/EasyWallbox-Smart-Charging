"""Append private shadow decisions to rotating local JSON Lines files.

All filesystem operations run in Home Assistant's executor, never its event
loop. Paths are fixed by the integration; raw entity IDs and car SOC are NOT
recorded. Rotation by local day and bounded size. No cloud upload.
"""
from __future__ import annotations

import json
from pathlib import Path

MAX_DAILY_BYTES = 2_000_000

from datetime import datetime
from math import isfinite


class ShadowLogSampler:
    """Compress high-frequency Shelly reports without slowing the policy.

    A stable decision is recorded at most once per minute. New decisions,
    bad data and DPM model changes are recorded immediately. Each line
    carries min/max/mean and count for the raw reports since the last line.
    """

    def __init__(self, interval_seconds: int = 60):
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        self._last_sample_at: datetime | None = None
        self._last_emitted_at: datetime | None = None
        self._last_day: str | None = None
        self._last_signature: tuple | None = None
        self._latest_record: dict | None = None
        self._count = 0
        self._total = 0.0
        self._minimum: float | None = None
        self._maximum: float | None = None
        self._first_sample: datetime | None = None
        self._last_window_sample: datetime | None = None

    def _stats(self) -> dict:
        return {
            "samples": self._count,
            "min_kw": round(self._minimum, 3) if self._minimum is not None else None,
            "max_kw": round(self._maximum, 3) if self._maximum is not None else None,
            "mean_kw": round(self._total / self._count, 3) if self._count else None,
            "first_report": self._first_sample.isoformat() if self._first_sample else None,
            "last_report": self._last_window_sample.isoformat()
            if self._last_window_sample else None,
        }

    def _reset(self) -> None:
        self._count = 0
        self._total = 0.0
        self._minimum = None
        self._maximum = None
        self._first_sample = None
        self._last_window_sample = None

    def _row(self, record: dict, kind: str) -> dict:
        result = dict(record)
        result["log_kind"] = kind
        result["house_window"] = self._stats()
        self._reset()
        return result

    def observe(
        self, when: datetime, sample_at: datetime | None,
        record: dict, signature: tuple,
    ) -> dict | None:
        """Return a JSONL row only for a due summary or significant event."""
        if when.tzinfo is None:
            raise ValueError("when must be timezone-aware")
        # State refreshes and repeated timestamps are NOT independent samples.
        if (sample_at is not None
                and (self._last_sample_at is None
                     or sample_at > self._last_sample_at)):
            self._last_sample_at = sample_at
            kw = record.get("house_kw")
            if (record.get("house_data_quality") == "ok"
                    and isinstance(kw, (float, int))
                    and not isinstance(kw, bool)
                    and isfinite(kw) and kw >= 0):
                self._count += 1
                self._total += kw
                self._minimum = (kw if self._minimum is None
                                 else min(self._minimum, kw))
                self._maximum = (kw if self._maximum is None
                                 else max(self._maximum, kw))
                if self._first_sample is None:
                    self._first_sample = sample_at
                self._last_window_sample = sample_at

        self._latest_record = record
        context = (
            signature, record.get("house_data_quality"),
            record.get("dpm_observed_kw"), record.get("dpm_model_kw"),
            record.get("dpm_model_source"), record.get("ev_baseline_kw"),
        )
        first = self._last_emitted_at is None
        changed = not first and context != self._last_signature
        day = record["time_local"][:10]
        day_changed = self._last_day is not None and day != self._last_day
        due = (not first and
               (when - self._last_emitted_at).total_seconds()
               >= self.interval_seconds)
        if not (first or changed or day_changed or due):
            return None

        kind = ("start" if first else "change" if changed
                else "day_rollover" if day_changed else "periodic")
        row = self._row(record, kind)
        self._last_emitted_at = when
        self._last_signature = context
        self._last_day = day
        return row

    def finish(self, when: datetime) -> dict | None:
        """Drain a partial minute when the field test is disabled/unloaded."""
        if self._latest_record is None or self._count == 0:
            return None
        record = dict(self._latest_record)
        record["time_local"] = when.isoformat(timespec="seconds")
        return self._row(record, "end")



def append_shadow_rows(root: str, rows: list[dict]) -> tuple[int, str]:
    """Write a batch, returning count and relative last filename.

    Caller must catch OSError and report failures. Never truncate old data.
    """
    if not rows:
        return 0, ""
    folder = Path(root)
    folder.mkdir(parents=True, exist_ok=True)
    written = 0
    last = ""
    for row in rows:
        day = row["time_local"][:10]
        if (len(day) != 10 or day[4] != "-" or day[7] != "-"
                or not day.replace("-", "").isdigit()):
            raise ValueError("invalid shadow log date")
        name = f"shadow_{day}.jsonl"
        path = folder / name
        text = json.dumps(row, sort_keys=True, ensure_ascii=False,
                          allow_nan=False, separators=(",", ":")) + "\n"
        encoded = text.encode("utf-8")
        if (path.exists() and path.stat().st_size + len(encoded) > MAX_DAILY_BYTES
                or len(encoded) > MAX_DAILY_BYTES):
            raise OSError("shadow_daily_log_limit_reached")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
        written += 1
        last = name
    return written, last
