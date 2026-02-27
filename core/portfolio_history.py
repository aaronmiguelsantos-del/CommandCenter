from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


PORTFOLIO_TASK_HISTORY_SCHEMA_VERSION = "1.0"


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_jsonl(path: str | Path, payload: dict[str, Any]) -> None:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True))
        f.write("\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def build_history_entry(*, task: str, captured_at: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PORTFOLIO_TASK_HISTORY_SCHEMA_VERSION,
        "task": task,
        "captured_at": captured_at,
        "payload": payload,
    }


def latest_and_previous(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not rows:
        return None, None
    latest = rows[-1]
    previous = rows[-2] if len(rows) >= 2 else None
    return latest, previous


def _summary(payload: dict[str, Any]) -> dict[str, int]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return {"repos_selected": 0, "repos_ok": 0, "repos_error": 0, "repos_skipped": 0}
    return {
        "repos_selected": int(summary.get("repos_selected", 0) or 0),
        "repos_ok": int(summary.get("repos_ok", 0) or 0),
        "repos_error": int(summary.get("repos_error", 0) or 0),
        "repos_skipped": int(summary.get("repos_skipped", 0) or 0),
    }


def summary_delta(
    *,
    latest_payload: dict[str, Any],
    previous_payload: dict[str, Any] | None,
) -> dict[str, int | None]:
    latest = _summary(latest_payload)
    previous = _summary(previous_payload or {})
    if previous_payload is None:
        return {
            "repos_ok_delta": None,
            "repos_error_delta": None,
            "repos_skipped_delta": None,
            "repos_selected_delta": None,
        }
    return {
        "repos_ok_delta": latest["repos_ok"] - previous["repos_ok"],
        "repos_error_delta": latest["repos_error"] - previous["repos_error"],
        "repos_skipped_delta": latest["repos_skipped"] - previous["repos_skipped"],
        "repos_selected_delta": latest["repos_selected"] - previous["repos_selected"],
    }


def parse_iso_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def filter_as_of(rows: list[dict[str, Any]], as_of: str | None) -> list[dict[str, Any]]:
    if not as_of:
        return rows
    cutoff = parse_iso_utc(as_of)
    kept: list[dict[str, Any]] = []
    for row in rows:
        captured_at = row.get("captured_at")
        if not isinstance(captured_at, str):
            continue
        try:
            if parse_iso_utc(captured_at) <= cutoff:
                kept.append(row)
        except Exception:
            continue
    return kept


def ref_select(rows: list[dict[str, Any]], ref: str) -> dict[str, Any]:
    if not rows:
        raise SystemExit("portfolio history ledger is empty")
    if ref == "latest":
        return rows[-1]
    if ref == "prev":
        if len(rows) < 2:
            raise SystemExit("portfolio history ledger has no prev entry")
        return rows[-2]
    try:
        index = int(ref)
    except ValueError:
        index = None
    if index is not None:
        if index < 0 or index >= len(rows):
            raise SystemExit(f"ref index out of range: {ref}")
        return rows[index]

    target = parse_iso_utc(ref)
    candidate: dict[str, Any] | None = None
    for row in rows:
        captured_at = row.get("captured_at")
        if not isinstance(captured_at, str):
            continue
        try:
            dt = parse_iso_utc(captured_at)
        except Exception:
            continue
        if dt <= target:
            candidate = row
    if candidate is None:
        raise SystemExit(f"no history entry <= {ref}")
    return candidate


def repo_status_index(payload: dict[str, Any]) -> dict[tuple[str, str], str]:
    repos = payload.get("repos")
    out: dict[tuple[str, str], str] = {}
    if not isinstance(repos, list):
        return out
    for item in repos:
        if not isinstance(item, dict):
            continue
        repo = item.get("repo")
        if not isinstance(repo, dict):
            continue
        key = (str(repo.get("repo_id", "")), str(repo.get("repo_root", "")))
        out[key] = str(item.get("status", ""))
    return out


def repo_transitions(
    *,
    latest_payload: dict[str, Any],
    previous_payload: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if previous_payload is None:
        return []
    latest = repo_status_index(latest_payload)
    previous = repo_status_index(previous_payload)
    keys = sorted(set(latest.keys()) | set(previous.keys()))
    out: list[dict[str, str]] = []
    for repo_id, repo_root in keys:
        before = previous.get((repo_id, repo_root), "missing")
        after = latest.get((repo_id, repo_root), "missing")
        if before == after:
            continue
        out.append(
            {
                "repo_id": repo_id,
                "repo_root": repo_root,
                "from": before,
                "to": after,
            }
        )
    return out


def history_tail(*, ledger_path: str, n: int, as_of: str | None) -> dict[str, Any]:
    rows = filter_as_of(read_jsonl(ledger_path), as_of)
    return {
        "schema_version": PORTFOLIO_TASK_HISTORY_SCHEMA_VERSION,
        "ledger": str(Path(ledger_path).expanduser().resolve()),
        "as_of": as_of,
        "n": int(n),
        "rows": rows[-n:] if n > 0 else [],
    }


def history_stats(*, ledger_path: str, days: int, as_of: str | None) -> dict[str, Any]:
    rows = filter_as_of(read_jsonl(ledger_path), as_of)
    if days > 0:
        now = parse_iso_utc(as_of) if as_of else datetime.now(UTC)
        cutoff = now - timedelta(days=int(days))
        scoped: list[dict[str, Any]] = []
        for row in rows:
            captured_at = row.get("captured_at")
            if not isinstance(captured_at, str):
                continue
            try:
                if parse_iso_utc(captured_at) >= cutoff:
                    scoped.append(row)
            except Exception:
                continue
        rows = scoped

    status_counts: dict[str, int] = {}
    repos_ok_total = 0
    repos_error_total = 0
    repos_skipped_total = 0
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        summary = _summary(payload)
        repos_ok_total += summary["repos_ok"]
        repos_error_total += summary["repos_error"]
        repos_skipped_total += summary["repos_skipped"]

    count = len(rows)
    return {
        "schema_version": PORTFOLIO_TASK_HISTORY_SCHEMA_VERSION,
        "ledger": str(Path(ledger_path).expanduser().resolve()),
        "as_of": as_of,
        "days": int(days),
        "entry_count": count,
        "status_counts": status_counts,
        "avg_repos_ok": round(repos_ok_total / count, 3) if count else None,
        "avg_repos_error": round(repos_error_total / count, 3) if count else None,
        "avg_repos_skipped": round(repos_skipped_total / count, 3) if count else None,
    }


def history_diff(*, ledger_path: str, a: str, b: str, as_of: str | None) -> dict[str, Any]:
    rows = filter_as_of(read_jsonl(ledger_path), as_of)
    a_entry = ref_select(rows, a)
    b_entry = ref_select(rows, b)
    a_payload = a_entry.get("payload")
    b_payload = b_entry.get("payload")
    if not isinstance(a_payload, dict) or not isinstance(b_payload, dict):
        raise SystemExit("portfolio history diff requires payload objects")
    a_status = str(a_payload.get("status", "unknown"))
    b_status = str(b_payload.get("status", "unknown"))
    a_summary = _summary(a_payload)
    b_summary = _summary(b_payload)
    return {
        "schema_version": PORTFOLIO_TASK_HISTORY_SCHEMA_VERSION,
        "ledger": str(Path(ledger_path).expanduser().resolve()),
        "a": {"captured_at": a_entry.get("captured_at"), "status": a_status},
        "b": {"captured_at": b_entry.get("captured_at"), "status": b_status},
        "status_change": {"from": a_status, "to": b_status, "changed": a_status != b_status},
        "summary_delta": {
            "repos_ok_delta": b_summary["repos_ok"] - a_summary["repos_ok"],
            "repos_error_delta": b_summary["repos_error"] - a_summary["repos_error"],
            "repos_skipped_delta": b_summary["repos_skipped"] - a_summary["repos_skipped"],
            "repos_selected_delta": b_summary["repos_selected"] - a_summary["repos_selected"],
        },
        "repo_transitions": repo_transitions(latest_payload=b_payload, previous_payload=a_payload),
    }
