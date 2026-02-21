from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_LEDGER_PATH = "data/snapshots/report_snapshot_history.jsonl"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_utc(ts: str) -> datetime | None:
    # Accepts Z or offset forms; mirrors your core/events behavior.
    try:
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _read_jsonl(path: Path, tail: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if tail is not None and tail > 0:
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
            # tolerate bad lines, keep deterministic behavior
            continue
    return out


def _sorted_reasons(reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(r.get("reason_code", "")),
            str(r.get("tier", "")),
            str(r.get("system_id", "")),
        )
    return sorted(reasons, key=key)


def _policy_key(policy: dict[str, Any]) -> tuple:
    blocked = policy.get("blocked_tiers", policy.get("strict_blocked_tiers", []))
    if isinstance(blocked, list):
        blocked = tuple(sorted([str(x) for x in blocked]))
    else:
        blocked = tuple()
    return (
        bool(policy.get("include_staging", False)),
        bool(policy.get("include_dev", False)),
        bool(policy.get("enforce_sla", False)),
        blocked,
    )


@dataclass(frozen=True)
class SnapshotEntry:
    ts: str
    as_of: str | None
    policy: dict[str, Any]
    summary: dict[str, Any]
    systems: list[dict[str, Any]]
    strict_failure: dict[str, Any] | None


def build_snapshot_ledger_entry(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    policy = report.get("policy", {}) if isinstance(report, dict) else {}
    systems_status = report.get("systems", {}).get("status", []) if isinstance(report, dict) else []

    rows: list[dict[str, Any]] = []
    if isinstance(systems_status, list):
        for row in sorted(
            [r for r in systems_status if isinstance(r, dict)],
            key=lambda r: str(r.get("system_id", "")),
        ):
            rows.append(
                {
                    "system_id": str(row.get("system_id", "")),
                    "status": str(row.get("status", "unknown")),
                    "score_total": float(row.get("score_total", 0.0)),
                    "violations": sorted([str(v) for v in (row.get("violations") or [])]),
                    "tier": str(row.get("tier", "prod")),
                    "is_sample": bool(row.get("is_sample", False)),
                    "sla_status": str(row.get("sla_status", "ok")),
                }
            )

    strict_blocked = policy.get("strict_blocked_tiers", policy.get("blocked_tiers", ["prod"]))
    if not isinstance(strict_blocked, list):
        strict_blocked = ["prod"]

    summary_payload = {
        "current_status": str(summary.get("current_status", summary.get("status", "unknown"))),
        "current_score": float(summary.get("current_score", summary.get("score_total", 0.0))),
        "status": str(summary.get("status", summary.get("current_status", "unknown"))),
        "score_total": float(summary.get("score_total", summary.get("current_score", 0.0))),
        "now_non_sample": summary.get("now_non_sample", {}),
        "strict_ready_now": bool(summary.get("strict_ready_now", False)),
    }

    return {
        "ts": _utcnow().isoformat().replace("+00:00", "Z"),
        "as_of": report.get("as_of"),
        "summary": summary_payload,
        "policy": {
            "strict_blocked_tiers": sorted([str(x) for x in strict_blocked]),
            "include_staging": bool(policy.get("include_staging", False)),
            "include_dev": bool(policy.get("include_dev", False)),
            "enforce_sla": bool(policy.get("enforce_sla", False)),
        },
        "systems": rows,
        "strict_failure": report.get("strict_failure"),
    }


def write_snapshot_ledger(report: dict[str, Any], path: str | Path | None = None) -> Path:
    ledger_path = Path(path) if path is not None else Path(DEFAULT_LEDGER_PATH)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    entry = build_snapshot_ledger_entry(report)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return ledger_path


def tail_snapshots(
    ledger_path: str | Path,
    *,
    n: int = 50,
    since_hours: int | None = None,
) -> list[dict[str, Any]]:
    p = Path(ledger_path)
    rows = _read_jsonl(p, tail=max(1, n * 5))  # read a bit more to allow since filtering
    # filter by since
    if since_hours is not None and since_hours > 0:
        cutoff = _utcnow() - timedelta(hours=since_hours)
        filtered: list[dict[str, Any]] = []
        for r in rows:
            ts = r.get("ts")
            dt = _parse_iso_utc(str(ts)) if ts is not None else None
            if dt is None:
                continue
            if dt >= cutoff:
                filtered.append(r)
        rows = filtered
    # take last n (chronological stability)
    rows = rows[-n:]
    # normalize strict_failure ordering for determinism
    for r in rows:
        sf = r.get("strict_failure")
        if isinstance(sf, dict) and isinstance(sf.get("reasons"), list):
            sf["reasons"] = _sorted_reasons(sf["reasons"])
    return rows


@dataclass(frozen=True)
class SnapshotStats:
    days: int
    window_start: str
    window_end: str
    total: int
    strict_ready_rate: float
    status_counts: dict[str, int]
    reason_counts: list[dict[str, Any]]
    system_reason_counts: list[dict[str, Any]]


def compute_stats(
    ledger_path: str | Path,
    *,
    days: int = 7,
) -> dict[str, Any]:
    p = Path(ledger_path)
    rows = _read_jsonl(p, tail=None)
    if not rows:
        now = _utcnow().isoformat().replace("+00:00", "Z")
        empty: SnapshotStats = SnapshotStats(
            days=days,
            window_start=now,
            window_end=now,
            total=0,
            strict_ready_rate=0.0,
            status_counts={"green": 0, "yellow": 0, "red": 0, "unknown": 0},
            reason_counts=[],
            system_reason_counts=[],
        )
        return _stats_to_dict(empty)

    end = _utcnow()
    start = end - timedelta(days=days)

    windowed: list[dict[str, Any]] = []
    for r in rows:
        ts = r.get("ts")
        dt = _parse_iso_utc(str(ts)) if ts is not None else None
        if dt is None:
            continue
        if start <= dt <= end:
            windowed.append(r)

    # deterministic chronological order
    windowed.sort(key=lambda r: str(r.get("ts", "")))

    status_counts = {"green": 0, "yellow": 0, "red": 0, "unknown": 0}
    strict_ready_true = 0
    total = len(windowed)

    # reason counts
    reason_counter: dict[tuple, int] = {}
    system_reason_counter: dict[tuple, int] = {}

    for r in windowed:
        summary = r.get("summary", {})
        if isinstance(summary, dict):
            strict_now = bool(summary.get("strict_ready_now", False))
            if strict_now:
                strict_ready_true += 1

        status = "unknown"
        # prefer explicit summary status, else infer from systems
        if isinstance(summary, dict) and "status" in summary:
            status = str(summary.get("status") or "unknown")
        status = status if status in status_counts else "unknown"
        status_counts[status] += 1

        sf = r.get("strict_failure")
        if isinstance(sf, dict):
            policy = sf.get("policy", {})
            policy_tuple = _policy_key(policy if isinstance(policy, dict) else {})
            reasons = sf.get("reasons", [])
            if isinstance(reasons, list):
                for rr in _sorted_reasons([x for x in reasons if isinstance(x, dict)]):
                    rc = str(rr.get("reason_code", ""))
                    tier = str(rr.get("tier", ""))
                    sysid = str(rr.get("system_id", ""))
                    k = (policy_tuple, rc, tier)
                    reason_counter[k] = reason_counter.get(k, 0) + 1
                    k2 = (policy_tuple, sysid, rc, tier)
                    system_reason_counter[k2] = system_reason_counter.get(k2, 0) + 1

    strict_ready_rate = (strict_ready_true / total) if total else 0.0

    reason_counts = []
    for (policy_tuple, rc, tier), c in reason_counter.items():
        reason_counts.append(
            {
                "count": c,
                "reason_code": rc,
                "tier": tier,
                "policy": _policy_tuple_to_dict(policy_tuple),
            }
        )
    reason_counts.sort(key=lambda d: (-int(d["count"]), str(d["reason_code"]), str(d["tier"])))

    system_reason_counts = []
    for (policy_tuple, sysid, rc, tier), c in system_reason_counter.items():
        system_reason_counts.append(
            {
                "count": c,
                "system_id": sysid,
                "reason_code": rc,
                "tier": tier,
                "policy": _policy_tuple_to_dict(policy_tuple),
            }
        )
    system_reason_counts.sort(
        key=lambda d: (-int(d["count"]), str(d["system_id"]), str(d["reason_code"]), str(d["tier"]))
    )

    stats = SnapshotStats(
        days=days,
        window_start=start.isoformat().replace("+00:00", "Z"),
        window_end=end.isoformat().replace("+00:00", "Z"),
        total=total,
        strict_ready_rate=float(round(strict_ready_rate, 4)),
        status_counts=status_counts,
        reason_counts=reason_counts[:50],
        system_reason_counts=system_reason_counts[:50],
    )
    return _stats_to_dict(stats)


def read_jsonl_tail(*, ledger_path: str | Path, n: int) -> list[dict[str, Any]]:
    tail = int(max(1, n))
    return _read_jsonl(Path(ledger_path), tail=tail)


def snapshot_stats(*, ledger_path: str | Path, days: int) -> dict[str, Any]:
    p = Path(ledger_path)
    if not p.exists():
        return {
            "stats_version": "1.0",
            "ledger": str(p),
            "days": int(days),
            "rows": 0,
            "strict_failures": 0,
            "reason_codes": {},
        }

    cutoff = _utcnow() - timedelta(days=max(0, int(days)))
    total = 0
    strict_failures = 0
    reason_codes: dict[str, int] = {}

    for row in _read_jsonl(p, tail=None):
        ts = row.get("ts")
        dt = _parse_iso_utc(str(ts)) if ts is not None else None
        if dt is not None and dt < cutoff:
            continue
        total += 1

        sf = row.get("strict_failure")
        if isinstance(sf, dict) and sf.get("strict_failed") is True:
            strict_failures += 1
            reasons = sf.get("reasons")
            if isinstance(reasons, list):
                for r in reasons:
                    if not isinstance(r, dict):
                        continue
                    code = str(r.get("reason_code", "UNKNOWN"))
                    reason_codes[code] = reason_codes.get(code, 0) + 1

    return {
        "stats_version": "1.0",
        "ledger": str(p),
        "days": int(days),
        "rows": total,
        "strict_failures": strict_failures,
        "reason_codes": dict(sorted(reason_codes.items(), key=lambda kv: kv[0])),
    }


def _policy_tuple_to_dict(t: tuple) -> dict[str, Any]:
    include_staging, include_dev, enforce_sla, blocked = t
    return {
        "include_staging": bool(include_staging),
        "include_dev": bool(include_dev),
        "enforce_sla": bool(enforce_sla),
        "blocked_tiers": list(blocked),
    }


def _stats_to_dict(s: SnapshotStats) -> dict[str, Any]:
    return {
        "stats_version": "1.0",
        "days": s.days,
        "window_start": s.window_start,
        "window_end": s.window_end,
        "total": s.total,
        "strict_ready_rate": s.strict_ready_rate,
        "status_counts": s.status_counts,
        "top_reasons": s.reason_counts,
        "top_system_reasons": s.system_reason_counts,
    }


def run_snapshot_loop(
    *,
    every_seconds: int,
    count: int,
    write_fn,
) -> dict[str, Any]:
    """
    write_fn() is injected from core.reporting.write_snapshot_ledger path.
    Deterministic behavior: sleeps are real-time; payload is stable given time.
    """
    every_seconds = int(max(1, every_seconds))
    count = int(max(1, count))

    written = 0
    started = _utcnow().isoformat().replace("+00:00", "Z")
    for i in range(count):
        write_fn()
        written += 1
        if i < count - 1:
            time.sleep(every_seconds)

    ended = _utcnow().isoformat().replace("+00:00", "Z")
    return {"loop_version": "1.0", "started": started, "ended": ended, "every_seconds": every_seconds, "count": count, "written": written}
