from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.globs import iter_glob
from core.registry import registry_path as default_registry_path


def parse_iso_utc(ts: str) -> datetime | None:
    """
    Parse ISO timestamps into aware UTC datetimes.
    Accepts trailing 'Z'. Returns None if unparsable.
    Deterministic, pure.
    """
    try:
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def last_event_ts_from_glob(events_glob: str, registry_path: str | Path | None = None) -> datetime | None:
    """
    Deterministically find max parsed event ts across all matched files.
    - sorted(paths)
    - ignores unparsable JSON lines
    - ignores missing/unparsable ts fields
    - never raises
    """
    best: datetime | None = None
    reg_path = default_registry_path(registry_path)
    paths = iter_glob(events_glob, reg_path)

    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue

        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue

            ts = row.get("ts") if isinstance(row, dict) else None
            if not isinstance(ts, str):
                continue

            dt = parse_iso_utc(ts)
            if dt is None:
                continue

            if best is None or dt > best:
                best = dt

    return best
