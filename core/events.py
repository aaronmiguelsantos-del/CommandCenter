from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.globs import iter_glob
from core.registry import registry_path as default_registry_path
from core.timeutil import parse_iso_utc


def last_event_ts_from_glob(
    events_glob: str,
    registry_path: str | Path | None = None,
    *,
    as_of: datetime | None = None,
) -> datetime | None:
    """
    Return the max event timestamp across matching JSONL files, constrained by as_of if provided.
    - Ignores unreadable lines / invalid timestamps.
    - Deterministic max timestamp selection.
    """
    best: datetime | None = None
    reg_path = default_registry_path(registry_path)
    for p in iter_glob(events_glob, reg_path):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
        except Exception:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            ts = parse_iso_utc(str(obj.get("ts", "")))
            if ts is None:
                continue
            if as_of is not None and ts > as_of:
                continue
            if best is None or ts > best:
                best = ts
    return best


def read_events_from_glob(
    events_glob: str,
    registry_path: str | Path | None = None,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Read all events from JSONL files matching events_glob (registry-aware), optionally constrained by as_of.
    Deterministic output ordering:
    - events sorted by ts asc, then stable JSON str fallback.
    """
    rows: list[dict[str, Any]] = []
    reg_path = default_registry_path(registry_path)
    for p in iter_glob(events_glob, reg_path):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
        except Exception:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            ts = parse_iso_utc(str(obj.get("ts", "")))
            if ts is None:
                continue
            if as_of is not None and ts > as_of:
                continue
            rows.append(obj)

    def _key(o: dict[str, Any]) -> tuple[str, str]:
        ts = parse_iso_utc(str(o.get("ts", "")))
        return (ts.isoformat() if ts else "", json.dumps(o, sort_keys=True))

    rows.sort(key=_key)
    return rows
