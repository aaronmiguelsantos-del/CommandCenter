from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.portfolio_execution import run_portfolio_task
from core.portfolio_history import latest_and_previous, read_jsonl, repo_transitions


PORTFOLIO_HEALTH_REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_PORTFOLIO_HEALTH_HISTORY = "data/portfolio/health_history.jsonl"


def _build_report(
    *,
    command: str,
    history_path: str,
    latest_payload: dict[str, Any],
) -> dict[str, Any]:
    rows = read_jsonl(history_path)
    latest_entry, previous_entry = latest_and_previous(rows)
    latest_payload_from_history = latest_payload
    previous_payload = previous_entry.get("payload") if isinstance(previous_entry, dict) else None
    previous_captured_at = previous_entry.get("captured_at") if isinstance(previous_entry, dict) else None
    history = latest_payload_from_history.get("history") if isinstance(latest_payload_from_history, dict) else {}
    if not isinstance(history, dict):
        history = {}

    failing_repos: list[dict[str, Any]] = []
    for item in latest_payload_from_history.get("repos", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")) != "error":
            continue
        repo = item.get("repo")
        if not isinstance(repo, dict):
            repo = {}
        failing_repos.append(
            {
                "repo_id": str(repo.get("repo_id", "")),
                "repo_root": str(repo.get("repo_root", "")),
                "reason": str(item.get("reason", "")),
                "error_code": str(item.get("error_code", "")),
                "command": str(item.get("command", "")),
            }
        )
    failing_repos.sort(key=lambda row: (row["repo_id"], row["repo_root"], row["error_code"]))

    summary = latest_payload_from_history.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    delta_summary = history.get("delta_summary", {})
    if not isinstance(delta_summary, dict):
        delta_summary = {}

    return {
        "schema_version": PORTFOLIO_HEALTH_REPORT_SCHEMA_VERSION,
        "command": command,
        "status": str(latest_payload_from_history.get("status", "unknown")),
        "task": str(latest_payload_from_history.get("task", "health")),
        "history": {
            "path": str(Path(history_path).expanduser().resolve()),
            "entry_count": len(rows),
            "captured_at": history.get("captured_at") or (latest_entry.get("captured_at") if isinstance(latest_entry, dict) else None),
            "previous_captured_at": previous_captured_at,
        },
        "summary": {
            "repos_selected": int(summary.get("repos_selected", 0) or 0),
            "repos_ok": int(summary.get("repos_ok", 0) or 0),
            "repos_error": int(summary.get("repos_error", 0) or 0),
            "repos_skipped": int(summary.get("repos_skipped", 0) or 0),
            "repos_ok_delta": delta_summary.get("repos_ok_delta"),
            "repos_error_delta": delta_summary.get("repos_error_delta"),
            "repos_skipped_delta": delta_summary.get("repos_skipped_delta"),
            "repos_selected_delta": delta_summary.get("repos_selected_delta"),
        },
        "repo_transitions": repo_transitions(
            latest_payload=latest_payload_from_history,
            previous_payload=previous_payload if isinstance(previous_payload, dict) else None,
        ),
        "failing_repos": failing_repos,
        "latest": latest_payload_from_history,
    }


def render_portfolio_health_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    lines = [
        "# Portfolio Health",
        "",
        f"- Status: `{report.get('status', 'unknown')}`",
        f"- Captured at: `{report.get('history', {}).get('captured_at')}`",
        f"- Previous: `{report.get('history', {}).get('previous_captured_at')}`",
        f"- Repos: `{summary.get('repos_selected', 0)}` selected | `{summary.get('repos_ok', 0)}` ok | `{summary.get('repos_error', 0)}` error | `{summary.get('repos_skipped', 0)}` skipped",
        "",
        "## Repo Transitions",
    ]
    transitions = report.get("repo_transitions", [])
    if isinstance(transitions, list) and transitions:
        for item in transitions:
            if not isinstance(item, dict):
                continue
            lines.append(f"- `{item.get('repo_id')}` `{item.get('from')}` -> `{item.get('to')}`")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Failing Repos")
    failing = report.get("failing_repos", [])
    if isinstance(failing, list) and failing:
        for item in failing:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('repo_id')}` reason=`{item.get('reason')}` error_code=`{item.get('error_code')}` command=`{item.get('command')}`"
            )
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def run_portfolio_health_report(
    *,
    repos: list[str] | None = None,
    repos_file: str | None = None,
    repos_map: str | None = None,
    allow_missing: bool = False,
    max_repos: int | None = None,
    jobs: int = 1,
    history_path: str = DEFAULT_PORTFOLIO_HEALTH_HISTORY,
    captured_at: str | None = None,
    write_history: bool = True,
) -> tuple[dict[str, Any], int]:
    payload, code = run_portfolio_task(
        task="health",
        repos=repos,
        repos_file=repos_file,
        repos_map=repos_map,
        allow_missing=allow_missing,
        max_repos=max_repos,
        jobs=jobs,
        write_history=write_history,
        history_path=history_path,
        captured_at=captured_at,
    )
    report = _build_report(
        command="portfolio_health_report",
        history_path=history_path,
        latest_payload=payload,
    )
    return report, code


def write_portfolio_health_outputs(report: dict[str, Any], *, json_path: str | None, md_path: str | None) -> None:
    if json_path:
        p = Path(json_path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if md_path:
        p = Path(md_path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_portfolio_health_markdown(report), encoding="utf-8")
