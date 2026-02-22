from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from core.portfolio_gate import run_portfolio_gate
from core.timeutil import parse_iso_utc


PORTFOLIO_SNAPSHOT_SCHEMA_VERSION = "1.0"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_jsonl_line(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True))
        f.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _parse_iso(ts: str) -> datetime:
    # Prefer shared parser (handles Z, offsets, naive->UTC).
    dt = parse_iso_utc(ts)
    if dt is None:
        raise ValueError(f"invalid iso timestamp: {ts}")
    return dt


def _filter_as_of(rows: list[dict[str, Any]], as_of: Optional[str]) -> list[dict[str, Any]]:
    if not as_of:
        return rows
    cutoff = _parse_iso(as_of)
    kept: list[dict[str, Any]] = []
    for r in rows:
        captured_at = r.get("captured_at")
        if not isinstance(captured_at, str):
            continue
        try:
            dt = _parse_iso(captured_at)
        except Exception:
            continue
        if dt <= cutoff:
            kept.append(r)
    return kept


def _ref_select(rows: list[dict[str, Any]], ref: str) -> dict[str, Any]:
    if not rows:
        raise SystemExit("portfolio snapshot ledger is empty")

    if ref == "latest":
        return rows[-1]
    if ref == "prev":
        if len(rows) < 2:
            raise SystemExit("portfolio snapshot ledger has no prev entry")
        return rows[-2]

    # If ref is an int index (0-based)
    try:
        i = int(ref)
        if i < 0 or i >= len(rows):
            raise SystemExit(f"ref index out of range: {ref}")
        return rows[i]
    except ValueError:
        pass

    # If ref is ISO timestamp, pick the last snapshot <= that time
    try:
        t = _parse_iso(ref)
        cand: dict[str, Any] | None = None
        for r in rows:
            ca = r.get("captured_at")
            if not isinstance(ca, str):
                continue
            dt = _parse_iso(ca)
            if dt <= t:
                cand = r
        if cand is None:
            raise SystemExit(f"no snapshot <= {ref}")
        return cand
    except Exception:
        raise SystemExit(f"invalid ref: {ref} (use prev|latest|index|iso)")


def capture_portfolio_snapshot(
    *,
    repos: Optional[list[str]],
    repos_file: Optional[str],
    repos_map: Optional[str],
    allow_missing: bool,
    hide_samples: bool,
    strict: bool,
    enforce_sla: bool,
    as_of: Optional[str],
    jobs: int,
    fail_fast: bool,
    max_repos: Optional[int],
    export_mode: str,
    captured_at: Optional[str],
) -> dict[str, Any]:
    pg, exit_code = run_portfolio_gate(
        repos=repos,
        repos_file=repos_file,
        repos_map=repos_map,
        allow_missing=allow_missing,
        hide_samples=hide_samples,
        strict=strict,
        enforce_sla=enforce_sla,
        as_of=as_of,
        export_path=None,
        jobs=jobs,
        fail_fast=fail_fast,
        max_repos=max_repos,
        export_mode=export_mode,
    )

    snap = {
        "schema_version": PORTFOLIO_SNAPSHOT_SCHEMA_VERSION,
        "captured_at": captured_at or _now_utc_iso(),
        "as_of": as_of,
        "portfolio_exit_code": int(exit_code),
        "portfolio_gate": pg,
    }
    return snap


def write_portfolio_snapshot(
    *,
    ledger_path: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    path = Path(ledger_path).expanduser().resolve()
    _write_jsonl_line(path, snapshot)
    return snapshot


def tail_portfolio_snapshots(*, ledger_path: str, n: int, as_of: Optional[str]) -> dict[str, Any]:
    path = Path(ledger_path).expanduser().resolve()
    rows = _read_jsonl(path)
    rows = _filter_as_of(rows, as_of)
    tail = rows[-n:] if n > 0 else []
    return {"schema_version": "1.0", "ledger": str(path), "as_of": as_of, "n": int(n), "rows": tail}


def stats_portfolio_snapshots(*, ledger_path: str, days: int, as_of: Optional[str]) -> dict[str, Any]:
    """
    Lightweight stats:
    - counts by portfolio_status
    - avg score
    - strict/regression incidence
    """
    path = Path(ledger_path).expanduser().resolve()
    rows = _read_jsonl(path)
    rows = _filter_as_of(rows, as_of)

    if not rows:
        return {
            "schema_version": "1.0",
            "ledger": str(path),
            "as_of": as_of,
            "days": int(days),
            "count": 0,
            "status_counts": {},
            "avg_score": None,
            "strict_fail_rate": None,
            "regression_rate": None,
        }

    # If days specified, filter by captured_at time window
    if days is not None and int(days) > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
        filt: list[dict[str, Any]] = []
        for r in rows:
            ca = r.get("captured_at")
            if not isinstance(ca, str):
                continue
            try:
                dt = _parse_iso(ca)
            except Exception:
                continue
            if dt >= cutoff:
                filt.append(r)
        rows = filt

    status_counts: dict[str, int] = {}
    scores: list[int] = []
    strict_fail = 0
    regression = 0

    for r in rows:
        pg = r.get("portfolio_gate") or {}
        if not isinstance(pg, dict):
            continue
        summary = pg.get("summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        status = str(summary.get("portfolio_status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1

        score = summary.get("portfolio_score")
        if isinstance(score, int):
            scores.append(score)

        exit_code = r.get("portfolio_exit_code")
        if exit_code in (2, 4):
            strict_fail += 1
        if exit_code in (3, 4):
            regression += 1

    count = len(rows)
    avg_score = round(sum(scores) / len(scores), 2) if scores else None
    strict_fail_rate = round(strict_fail / count, 3) if count else None
    regression_rate = round(regression / count, 3) if count else None

    return {
        "schema_version": "1.0",
        "ledger": str(path),
        "as_of": as_of,
        "days": int(days),
        "count": int(count),
        "status_counts": status_counts,
        "avg_score": avg_score,
        "strict_fail_rate": strict_fail_rate,
        "regression_rate": regression_rate,
    }
