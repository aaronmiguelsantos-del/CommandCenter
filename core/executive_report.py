from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.portfolio_history import now_utc_iso
from core.portfolio_execution import run_portfolio_task


EXECUTIVE_REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_EXECUTIVE_RUNBOOK = "data/executive/runbook.json"


def _load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("executive runbook must be a JSON object")
    return payload


def _load_runbook(path: str) -> dict[str, Any]:
    payload = _load_json(path)
    if str(payload.get("schema_version", "")).strip() != "1.0":
        raise ValueError("executive runbook schema_version drift")
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("executive runbook must include non-empty steps")
    return payload


def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    step_id = str(step.get("step_id", "")).strip()
    task = str(step.get("task", "")).strip()
    title = str(step.get("title", "")).strip() or step_id
    severity = str(step.get("severity_on_error", "high")).strip() or "high"
    if not step_id or task not in {"health", "release", "registry"}:
        raise ValueError("executive runbook step requires step_id and valid task")
    if severity not in {"high", "medium", "low"}:
        raise ValueError("executive runbook severity_on_error must be high|medium|low")
    return {
        "step_id": step_id,
        "task": task,
        "title": title,
        "severity_on_error": severity,
    }


def _failing_actions(step_result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = step_result.get("payload")
    if not isinstance(payload, dict):
        return []
    repos = payload.get("repos")
    if not isinstance(repos, list):
        return []

    out: list[dict[str, Any]] = []
    for item in repos:
        if not isinstance(item, dict) or str(item.get("status", "")) != "error":
            continue
        repo = item.get("repo")
        if not isinstance(repo, dict):
            repo = {}
        repo_id = str(repo.get("repo_id", "")).strip()
        reason = str(item.get("reason", "")).strip()
        error_code = str(item.get("error_code", "")).strip()
        command = str(item.get("command", "")).strip()
        if not repo_id:
            continue
        out.append(
            {
                "step_id": step_result.get("step_id"),
                "task": step_result.get("task"),
                "severity": step_result.get("severity_on_error"),
                "repo_id": repo_id,
                "why": f"{error_code or 'TASK_FAILED'}: {reason or 'task command failed'}",
                "recommended_command": command,
                "title": f"Fix {repo_id} {step_result.get('task')}",
            }
        )
    out.sort(key=lambda row: (str(row["step_id"]), str(row["repo_id"]), str(row["title"])))
    return out


def render_executive_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    lines = [
        "# Executive Report",
        "",
        f"- Status: `{report.get('status', 'unknown')}`",
        f"- Captured at: `{report.get('captured_at')}`",
        f"- Steps: `{summary.get('steps_total', 0)}` total | `{summary.get('steps_ok', 0)}` ok | `{summary.get('steps_error', 0)}` error",
        "",
        "## Checks",
    ]
    for step in report.get("checks", []):
        if not isinstance(step, dict):
            continue
        lines.append(
            f"- `{step.get('step_id')}` task=`{step.get('task')}` status=`{step.get('status')}` severity=`{step.get('severity_on_error')}`"
        )
    lines.append("")
    lines.append("## Top Actions")
    actions = report.get("top_actions", [])
    if isinstance(actions, list) and actions:
        for item in actions:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- priority=`{item.get('priority')}` title=`{item.get('title')}` why=`{item.get('why')}` command=`{item.get('recommended_command')}`"
            )
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def run_executive_report(
    *,
    runbook_path: str = DEFAULT_EXECUTIVE_RUNBOOK,
    repos: list[str] | None = None,
    repos_file: str | None = None,
    repos_map: str | None = None,
    allow_missing: bool = False,
    max_repos: int | None = None,
    jobs: int = 1,
    captured_at: str | None = None,
    write_history: bool = True,
) -> tuple[dict[str, Any], int]:
    runbook = _load_runbook(runbook_path)
    steps = [_normalize_step(step) for step in runbook.get("steps", [])]
    report_captured_at = captured_at or now_utc_iso()

    checks: list[dict[str, Any]] = []
    top_actions: list[dict[str, Any]] = []
    for step in steps:
        payload, exit_code = run_portfolio_task(
            task=step["task"],
            repos=repos,
            repos_file=repos_file,
            repos_map=repos_map,
            allow_missing=allow_missing,
            max_repos=max_repos,
            jobs=jobs,
            captured_at=report_captured_at,
            write_history=write_history,
        )
        step_result = {
            "step_id": step["step_id"],
            "title": step["title"],
            "task": step["task"],
            "severity_on_error": step["severity_on_error"],
            "status": payload.get("status"),
            "exit_code": int(exit_code),
            "summary": payload.get("summary", {}),
            "payload": payload,
        }
        checks.append(step_result)
        top_actions.extend(_failing_actions(step_result))

    top_actions.sort(key=lambda row: (str(row["severity"]), str(row["step_id"]), str(row["repo_id"])))
    for i, item in enumerate(top_actions, start=1):
        item["priority"] = i

    steps_error = sum(1 for item in checks if int(item.get("exit_code", 0)) != 0)
    steps_ok = sum(1 for item in checks if int(item.get("exit_code", 0)) == 0)
    report = {
        "schema_version": EXECUTIVE_REPORT_SCHEMA_VERSION,
        "command": "executive_report",
        "captured_at": report_captured_at,
        "status": "ok" if steps_error == 0 else "needs_attention",
        "runbook": {
            "schema_version": str(runbook.get("schema_version", "")),
            "name": str(runbook.get("name", "")),
            "path": str(Path(runbook_path).expanduser().resolve()),
        },
        "summary": {
            "steps_total": len(checks),
            "steps_ok": steps_ok,
            "steps_error": steps_error,
        },
        "checks": checks,
        "top_actions": top_actions,
    }
    return report, 0 if steps_error == 0 else 2


def write_executive_outputs(report: dict[str, Any], *, json_path: str | None, md_path: str | None) -> None:
    if json_path:
        p = Path(json_path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if md_path:
        p = Path(md_path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_executive_markdown(report), encoding="utf-8")
