from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.events import parse_iso_utc


@dataclass(frozen=True)
class SnapshotRef:
    ts: str
    snapshot: dict[str, Any]


def _iter_ledger_rows(ledger_path: Path, tail: int) -> list[dict[str, Any]]:
    """
    Read up to last N JSONL rows. Deterministic: preserves file order for those rows.
    Tolerant of bad lines.
    """
    if not ledger_path.exists():
        return []

    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if tail > 0:
        lines = lines[-tail:]

    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


def _select_by_index(rows: list[dict[str, Any]], idx: int) -> dict[str, Any] | None:
    # idx supports negative indexing (Python style). Deterministic.
    try:
        return rows[idx]
    except Exception:
        return None


def _select_by_ts(rows: list[dict[str, Any]], ts: str) -> dict[str, Any] | None:
    # exact match first
    for r in rows:
        if str(r.get("ts", "")) == ts:
            return r
    # else attempt datetime equality (same instant)
    target = parse_iso_utc(ts)
    if target is None:
        return None
    for r in rows:
        rt = parse_iso_utc(str(r.get("ts", "")))
        if rt is not None and rt == target:
            return r
    return None


def _resolve_ref(rows: list[dict[str, Any]], ref: str) -> dict[str, Any] | None:
    ref = ref.strip()
    if not ref:
        return None

    if ref.lower() == "latest":
        return _select_by_index(rows, -1)
    if ref.lower() in {"prev", "previous"}:
        return _select_by_index(rows, -2)

    # integer index (supports negative)
    try:
        idx = int(ref)
        return _select_by_index(rows, idx)
    except Exception:
        pass

    # timestamp
    return _select_by_ts(rows, ref)


def _systems_map(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snap = entry.get("snapshot", entry)  # tolerate shape: either ledger row or raw snapshot
    systems = snap.get("systems", [])
    out: dict[str, dict[str, Any]] = {}
    if isinstance(systems, list):
        for s in systems:
            if isinstance(s, dict) and "system_id" in s:
                out[str(s["system_id"])] = s
    return out


def _risk_rank_map(entry: dict[str, Any]) -> dict[str, int]:
    snap = entry.get("snapshot", entry)
    risk = snap.get("risk", {})
    ranked = risk.get("ranked", [])
    out: dict[str, int] = {}
    if isinstance(ranked, list):
        for i, r in enumerate(ranked):
            if isinstance(r, dict) and "system_id" in r:
                out[str(r["system_id"])] = i + 1  # rank 1 = highest risk
    return out


def _strict_reasons(entry: dict[str, Any]) -> list[dict[str, Any]]:
    snap = entry.get("snapshot", entry)
    sf = snap.get("strict_failure")
    if not isinstance(sf, dict):
        return []
    reasons = sf.get("reasons", [])
    return reasons if isinstance(reasons, list) else []


def diff_snapshots(a_entry: dict[str, Any], b_entry: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic diff from a -> b.
    """
    a_ts = str(a_entry.get("ts", "")) or str(a_entry.get("snapshot", {}).get("ts", ""))
    b_ts = str(b_entry.get("ts", "")) or str(b_entry.get("snapshot", {}).get("ts", ""))

    a_sys = _systems_map(a_entry)
    b_sys = _systems_map(b_entry)

    status_changes: list[dict[str, Any]] = []
    for system_id in sorted(set(a_sys.keys()) | set(b_sys.keys())):
        a_status = str(a_sys.get(system_id, {}).get("status", "missing"))
        b_status = str(b_sys.get(system_id, {}).get("status", "missing"))
        if a_status != b_status:
            status_changes.append(
                {
                    "system_id": system_id,
                    "from": a_status,
                    "to": b_status,
                }
            )

    # strict reasons delta (new in b)
    a_reasons = _strict_reasons(a_entry)
    b_reasons = _strict_reasons(b_entry)

    def _reason_key(r: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(r.get("system_id", "")),
            str(r.get("tier", "")),
            str(r.get("reason_code", "")),
        )

    a_keys = {_reason_key(r) for r in a_reasons if isinstance(r, dict)}
    new_reasons = []
    for r in b_reasons:
        if not isinstance(r, dict):
            continue
        if _reason_key(r) not in a_keys:
            new_reasons.append(r)

    # risk rank delta (top 5 movers by absolute delta)
    a_rank = _risk_rank_map(a_entry)
    b_rank = _risk_rank_map(b_entry)
    deltas: list[dict[str, Any]] = []
    for sid in sorted(set(a_rank.keys()) | set(b_rank.keys())):
        ra = a_rank.get(sid)
        rb = b_rank.get(sid)
        if ra is None or rb is None:
            continue
        if ra != rb:
            deltas.append(
                {
                    "system_id": sid,
                    "from_rank": ra,
                    "to_rank": rb,
                    "delta": rb - ra,
                }
            )
    deltas.sort(key=lambda x: (abs(int(x["delta"])), x["system_id"]), reverse=True)
    deltas = deltas[:5]

    return {
        "a": {"ts": a_ts},
        "b": {"ts": b_ts},
        "system_status_changes": status_changes,
        "new_strict_reasons": new_reasons,
        "risk_rank_delta_top": deltas,
    }


def snapshot_diff_from_ledger(
    ledger: str | Path,
    a: str,
    b: str,
    *,
    tail: int = 2000,
) -> dict[str, Any]:
    ledger_path = Path(ledger)
    rows = _iter_ledger_rows(ledger_path, tail=tail)
    if not rows:
        return {"error": "NO_LEDGER_ROWS", "ledger": str(ledger_path)}

    a_entry = _resolve_ref(rows, a)
    b_entry = _resolve_ref(rows, b)
    if a_entry is None or b_entry is None:
        return {
            "error": "BAD_REF",
            "ledger": str(ledger_path),
            "a": a,
            "b": b,
            "hint": "Use --a latest|prev|<int index>|<iso ts> and same for --b. Indices support negatives.",
        }

    return {
        "ledger": str(ledger_path),
        "diff": diff_snapshots(a_entry, b_entry),
    }
