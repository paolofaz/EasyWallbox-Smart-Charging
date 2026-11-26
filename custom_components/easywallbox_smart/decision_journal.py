"""Private, ordered decision journal for field trials; user-configurable."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)
RETENTION_DAYS = 90


def _prune_decision_logs(folder: Path, today: date) -> None:
    """Remove only dated diagnostic journals older than the retention window."""
    cutoff = today - timedelta(days=RETENTION_DAYS - 1)
    for path in folder.glob("decisions_*.jsonl"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            day = date.fromisoformat(path.stem.removeprefix("decisions_"))
        except ValueError:
            continue
        if path.name != f"decisions_{day.isoformat()}.jsonl" or day >= cutoff:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            _LOGGER.warning("Unable to prune decision journal (%s)", type(error).__name__)


def _append(folder, rows):
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    for day, items in groupby(rows, key=lambda row: row["time_local"][:10]):
        path = folder / f"decisions_{day}.jsonl"
        path.touch(mode=0o600, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            for row in items:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False,
                                        separators=(",", ":")) + "\n")


class DecisionJournal:
    """One ordered writer per entry. The controller supplies only selected facts."""

    def __init__(self, hass, entry, version, enabled=True):
        self._version = version
        self._enabled = bool(enabled)
        self._hass = hass
        self._entry = entry
        self._zone = ZoneInfo(hass.config.time_zone)
        self._folder = Path(hass.config.path("easywallbox_smart", "decision_logs"))
        self._queue = []
        self._task = None
        self._seq = 0
        self._retry_after = None
        self._gap = 0
        self._last_prune_day = None

    def record(self, session, event, reason, **facts):
        if not session or not self._enabled:
            return
        now = datetime.now(timezone.utc)
        self._seq += 1
        if len(self._queue) >= 2048 or (self._retry_after and now < self._retry_after):
            self._gap += 1
            return
        row = {"schema": 1, "version": self._version, "session": session,
               "seq": self._seq, "time_local": now.astimezone(self._zone).isoformat(),
               "event": event, "reason": reason, **facts}
        if self._gap:
            row["preceding_records_unverified"] = self._gap
            self._gap = 0
        self._queue.append(row)
        if self._task is None or self._task.done():
            self._task = self._entry.async_create_background_task(
                self._hass, self._drain(), "EasyWallbox decision journal")

    async def _drain(self):
        while self._queue:
            batch, self._queue = self._queue, []
            try:
                await self._hass.async_add_executor_job(_append, self._folder, batch)
            except (OSError, ValueError) as error:
                self._gap += sum(1 + row.get("preceding_records_unverified", 0)
                                 for row in (*batch, *self._queue))
                self._queue.clear()
                if self._retry_after is None:
                    _LOGGER.warning("Diario decisioni non scrivibile (%s). Verificare il file locale.",
                                    type(error).__name__)
                self._retry_after = datetime.now(timezone.utc) + timedelta(minutes=1)
                return
            self._retry_after = None
            today = datetime.now(self._zone).date()
            if self._last_prune_day != today:
                try:
                    await self._hass.async_add_executor_job(_prune_decision_logs, self._folder, today)
                except OSError as error:
                    _LOGGER.warning("Unable to prune decision journals (%s)", type(error).__name__)
                else:
                    self._last_prune_day = today

    async def async_flush(self):
        if self._task is not None:
            await self._task
