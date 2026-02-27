from __future__ import annotations

import json
from datetime import UTC, datetime
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
