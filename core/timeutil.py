from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_iso_utc(ts: str) -> Optional[datetime]:
    """
    Parse ISO8601 timestamps into an aware UTC datetime.
    Accepts:
      - 2026-02-16T12:34:56Z
      - 2026-02-16T12:34:56+00:00
      - 2026-02-16T12:34:56-05:00
    Returns None for invalid values.
    """
    try:
        s = str(ts).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
