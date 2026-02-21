from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.events import parse_iso_utc

_STATUS_RANK = {"missing": -1, "unknown": 0, "green": 1, "yellow": 2, "red": 3}
_HIGH_VIOLATION_CODES = {"PRIMITIVES_MIN", "INVARIANTS_MIN"}
_ACTION_SEVERITY_RANK = {
    "STRICT_REGRESSION": 1,
    "STATUS_REGRESSION": 2,
    "RISK_RANK_INCREASE": 3,
    "NEW_HIGH_VIOLATION": 4,
}


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


def _effective_row_time(row: dict[str, Any]) -> datetime | None:
    snap = row.get("snapshot")
    if isinstance(snap, dict):
        as_of = snap.get("as_of")
        if isinstance(as_of, str) and as_of.strip():
            dt = parse_iso_utc(as_of)
            if dt is not None:
                return dt

    as_of = row.get("as_of")
    if isinstance(as_of, str) and as_of.strip():
        dt = parse_iso_utc(as_of)
        if dt is not None:
            return dt

    ts = row.get("ts")
    if isinstance(ts, str) and ts.strip():
        dt = parse_iso_utc(ts)
        if dt is not None:
            return dt

    if isinstance(snap, dict):
        ts = snap.get("ts")
        if isinstance(ts, str) and ts.strip():
            dt = parse_iso_utc(ts)
            if dt is not None:
                return dt
    return None


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


def _systems_violations_map(entry: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for sid, system in _systems_map(entry).items():
        violations = system.get("violations")
        if not isinstance(violations, list):
            out[sid] = set()
            continue
        out[sid] = {str(v) for v in violations}
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


def _new_strict_reasons(a_entry: dict[str, Any], b_entry: dict[str, Any]) -> list[dict[str, Any]]:
    a_reasons = _strict_reasons(a_entry)
    b_reasons = _strict_reasons(b_entry)

    def _reason_key(r: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(r.get("system_id", "")),
            str(r.get("tier", "")),
            str(r.get("reason_code", "")),
        )

    a_keys = {_reason_key(r) for r in a_reasons if isinstance(r, dict)}
    out: list[dict[str, Any]] = []
    for r in b_reasons:
        if not isinstance(r, dict):
            continue
        if _reason_key(r) not in a_keys:
            out.append(r)

    out.sort(
        key=lambda r: (
            str(r.get("system_id", "")),
            str(r.get("tier", "")),
            str(r.get("reason_code", "")),
        )
    )
    return out


def _status_changes(a_entry: dict[str, Any], b_entry: dict[str, Any]) -> list[dict[str, Any]]:
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
    return status_changes


def _risk_deltas(a_entry: dict[str, Any], b_entry: dict[str, Any]) -> list[dict[str, Any]]:
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
    deltas.sort(key=lambda x: (-abs(int(x["delta"])), str(x["system_id"])))
    return deltas[:5]


def _new_high_violations(a_entry: dict[str, Any], b_entry: dict[str, Any]) -> list[dict[str, Any]]:
    a_violations = _systems_violations_map(a_entry)
    b_violations = _systems_violations_map(b_entry)
    out: list[dict[str, Any]] = []
    for sid in sorted(set(a_violations.keys()) | set(b_violations.keys())):
        a_high = a_violations.get(sid, set()) & _HIGH_VIOLATION_CODES
        b_high = b_violations.get(sid, set()) & _HIGH_VIOLATION_CODES
        new_codes = sorted(b_high - a_high)
        if new_codes:
            out.append({"system_id": sid, "new_codes": new_codes})
    return out


def _recommended_strict_command(entry: dict[str, Any]) -> str:
    snap = entry.get("snapshot", entry)
    sf = snap.get("strict_failure")
    policy = sf.get("policy", {}) if isinstance(sf, dict) else {}
    command = ["python", "-m", "app.main", "health", "--all", "--strict"]
    if bool(policy.get("include_staging", False)):
        command.append("--include-staging")
    if bool(policy.get("include_dev", False)):
        command.append("--include-dev")
    if bool(policy.get("enforce_sla", False)):
        command.append("--enforce-sla")
    return " ".join(command)


def _top_actions(diff: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    strict_cmd = str(diff.get("strict_recheck_command", "python -m app.main health --all --strict --enforce-sla"))

    for reason in diff.get("new_strict_reasons", []):
        if not isinstance(reason, dict):
            continue
        sid = str(reason.get("system_id", "")).strip() or "unknown"
        code = str(reason.get("reason_code", "")).strip() or "UNKNOWN"
        actions.append(
            {
                "type": "STRICT_REGRESSION",
                "system_id": sid,
                "reason": f"New {code} introduced",
                "recommended_command": strict_cmd,
            }
        )

    for row in diff.get("system_status_changes", []):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("system_id", "")).strip() or "unknown"
        before = str(row.get("from", "unknown")).strip() or "unknown"
        after = str(row.get("to", "unknown")).strip() or "unknown"
        if before not in {"green", "yellow"}:
            continue
        if after not in {"yellow", "red"}:
            continue
        if _STATUS_RANK.get(after, 0) <= _STATUS_RANK.get(before, 0):
            continue
        actions.append(
            {
                "type": "STATUS_REGRESSION",
                "system_id": sid,
                "reason": f"Status regressed {before}->{after}",
                "recommended_command": "python -m app.main health --all --json",
            }
        )

    for row in diff.get("risk_rank_delta_top", []):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("system_id", "")).strip() or "unknown"
        from_rank = row.get("from_rank")
        to_rank = row.get("to_rank")
        if not isinstance(from_rank, int) or not isinstance(to_rank, int):
            continue
        if to_rank >= from_rank:
            continue
        actions.append(
            {
                "type": "RISK_RANK_INCREASE",
                "system_id": sid,
                "reason": f"Risk rank increased {from_rank}->{to_rank}",
                "recommended_command": "python -m app.main report health --json",
            }
        )

    for row in diff.get("new_high_violations", []):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("system_id", "")).strip() or "unknown"
        codes = row.get("new_codes", [])
        if not isinstance(codes, list):
            continue
        codes_sorted = sorted([str(c) for c in codes if str(c).strip()])
        if not codes_sorted:
            continue
        actions.append(
            {
                "type": "NEW_HIGH_VIOLATION",
                "system_id": sid,
                "reason": f"New high violation(s): {','.join(codes_sorted)}",
                "recommended_command": "python -m app.main report health --json",
            }
        )

    actions.sort(
        key=lambda a: (
            int(_ACTION_SEVERITY_RANK.get(str(a.get("type", "")), 99)),
            str(a.get("system_id", "")),
            str(a.get("reason", "")),
        )
    )

    out: list[dict[str, Any]] = []
    for idx, action in enumerate(actions, start=1):
        out.append(
            {
                "priority": idx,
                "type": str(action.get("type", "")),
                "system_id": str(action.get("system_id", "")),
                "reason": str(action.get("reason", "")),
                "recommended_command": str(action.get("recommended_command", "")),
            }
        )
    return out


def diff_snapshots(a_entry: dict[str, Any], b_entry: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic diff from a -> b.
    """
    a_ts = str(a_entry.get("ts", "")) or str(a_entry.get("snapshot", {}).get("ts", ""))
    b_ts = str(b_entry.get("ts", "")) or str(b_entry.get("snapshot", {}).get("ts", ""))

    new_reasons = _new_strict_reasons(a_entry, b_entry)
    status_changes = _status_changes(a_entry, b_entry)
    deltas = _risk_deltas(a_entry, b_entry)
    high_violations = _new_high_violations(a_entry, b_entry)
    diff = {
        "a": {"ts": a_ts},
        "b": {"ts": b_ts},
        "system_status_changes": status_changes,
        "new_strict_reasons": new_reasons,
        "risk_rank_delta_top": deltas,
        "new_high_violations": high_violations,
        "strict_recheck_command": _recommended_strict_command(b_entry),
    }
    diff["top_actions"] = _top_actions(diff)
    return diff


def snapshot_diff_from_ledger(
    ledger: str | Path,
    a: str,
    b: str,
    *,
    tail: int = 2000,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    ledger_path = Path(ledger)
    rows = _iter_ledger_rows(ledger_path, tail=tail)
    if as_of is not None:
        filtered: list[dict[str, Any]] = []
        for r in rows:
            dt = _effective_row_time(r)
            if dt is None:
                continue
            if dt <= as_of:
                filtered.append(r)
        rows = filtered
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


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, col in enumerate(row):
            widths[i] = max(widths[i], len(col))

    header = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep = "-+-".join("-" * widths[i] for i in range(len(headers)))
    body = [" | ".join(col.ljust(widths[i]) for i, col in enumerate(row)) for row in rows]
    return "\n".join([header, sep, *body])


def render_snapshot_diff_pretty(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return json.dumps(payload, indent=2, sort_keys=True)

    diff = payload.get("diff", {})
    if not isinstance(diff, dict):
        return json.dumps(payload, indent=2, sort_keys=True)

    lines: list[str] = []
    lines.append("Snapshot Diff")
    lines.append(f"ledger: {payload.get('ledger', '')}")
    a_ts = diff.get("a", {}).get("ts", "") if isinstance(diff.get("a"), dict) else ""
    b_ts = diff.get("b", {}).get("ts", "") if isinstance(diff.get("b"), dict) else ""
    lines.append(f"a.ts: {a_ts}")
    lines.append(f"b.ts: {b_ts}")

    top_actions = diff.get("top_actions", [])
    lines.append("")
    lines.append("Top Actions")
    if isinstance(top_actions, list) and top_actions:
        rows = []
        for row in top_actions:
            if not isinstance(row, dict):
                continue
            rows.append(
                [
                    str(row.get("priority", "")),
                    str(row.get("type", "")),
                    str(row.get("system_id", "")),
                    str(row.get("reason", "")),
                    str(row.get("recommended_command", "")),
                ]
            )
        if rows:
            lines.append(_render_table(["priority", "type", "system_id", "reason", "recommended_command"], rows))
        else:
            lines.append("(none)")
    else:
        lines.append("(none)")

    sections: list[tuple[str, list[str], list[dict[str, Any]]]] = [
        (
            "Status changes",
            ["system_id", "from", "to"],
            diff.get("system_status_changes", []) if isinstance(diff.get("system_status_changes"), list) else [],
        ),
        (
            "New strict reasons",
            ["system_id", "tier", "reason_code"],
            diff.get("new_strict_reasons", []) if isinstance(diff.get("new_strict_reasons"), list) else [],
        ),
        (
            "Risk rank delta (top movers)",
            ["system_id", "from_rank", "to_rank", "delta"],
            diff.get("risk_rank_delta_top", []) if isinstance(diff.get("risk_rank_delta_top"), list) else [],
        ),
    ]

    for title, headers, rows_obj in sections:
        lines.append("")
        lines.append(title)
        if not rows_obj:
            lines.append("(none)")
            continue
        rows: list[list[str]] = []
        for row in rows_obj:
            if not isinstance(row, dict):
                continue
            rows.append([str(row.get(h, "")) for h in headers])
        if rows:
            lines.append(_render_table(headers, rows))
        else:
            lines.append("(none)")

    return "\n".join(lines)
