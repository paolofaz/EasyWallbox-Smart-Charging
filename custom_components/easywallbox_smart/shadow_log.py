"""Append private shadow decisions to rotating local JSON Lines files.

All filesystem operations run in Home Assistant's executor, never its event
loop. Paths are fixed by the integration; raw entity IDs and car SOC are NOT
recorded. Rotation by local day and bounded size. No cloud upload.
"""
from __future__ import annotations

import json
from pathlib import Path

MAX_DAILY_BYTES = 2_000_000


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
