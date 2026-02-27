from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.portfolio_health import run_portfolio_health_report, write_portfolio_health_outputs
from core.portfolio_history import now_utc_iso
from core.portfolio_release import run_portfolio_release_report, write_portfolio_release_outputs
from core.portfolio_execution import run_portfolio_task


EXECUTIVE_REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_EXECUTIVE_RUNBOOK = "data/executive/runbook.json"
_ALLOWED_TASKS = {"health", "release", "registry"}
_ALLOWED_SEVERITIES = {"high", "medium", "low"}
_ALLOWED_STEP_KEYS = {
    "step_id",
    "title",
    "task",
    "severity_on_error",
    "repos",
    "repos_file",
    "repos_map",
    "allow_missing",
    "max_repos",
    "jobs",
    "history_path",
    "write_history",
    "output_json",
    "output_md",
}
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("executive runbook must be a JSON object")
    return payload


def _load_runbook(path: str | Path) -> dict[str, Any]:
    payload = _load_json(path)
    if str(payload.get("schema_version", "")).strip() != "1.0":
        raise ValueError("executive runbook schema_version drift")
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("executive runbook must include non-empty steps")
    return payload


def _resolve_optional_path(value: Any, *, base_dir: Path, field: str) -> str | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"executive runbook {field} must be a non-empty string when provided")
    raw = Path(value.strip()).expanduser()
    return str(raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve())


def _resolve_optional_repos(value: Any, *, base_dir: Path) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("executive runbook repos must be a non-empty array when provided")
    resolved: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("executive runbook repos[] must be a non-empty string")
        raw = Path(item.strip()).expanduser()
        resolved.append(str(raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()))
    return resolved


def _normalize_step(step: dict[str, Any], *, runbook_dir: Path) -> dict[str, Any]:
    bad = set(step.keys()) - _ALLOWED_STEP_KEYS
    if bad:
        raise ValueError(f"executive runbook step has unknown keys: {sorted(bad)}")

    step_id = str(step.get("step_id", "")).strip()
    task = str(step.get("task", "")).strip()
    title = str(step.get("title", "")).strip() or step_id
    severity = str(step.get("severity_on_error", "high")).strip() or "high"
    if not step_id or task not in _ALLOWED_TASKS:
        raise ValueError("executive runbook step requires step_id and valid task")
    if severity not in _ALLOWED_SEVERITIES:
        raise ValueError("executive runbook severity_on_error must be high|medium|low")

    allow_missing = step.get("allow_missing")
    if allow_missing is not None:
        allow_missing = bool(allow_missing)
    max_repos = step.get("max_repos")
    if max_repos is not None and (not isinstance(max_repos, int) or isinstance(max_repos, bool) or max_repos <= 0):
        raise ValueError("executive runbook max_repos must be a positive integer when provided")
    jobs = step.get("jobs")
    if jobs is not None and (not isinstance(jobs, int) or isinstance(jobs, bool) or jobs <= 0):
        raise ValueError("executive runbook jobs must be a positive integer when provided")
    write_history = step.get("write_history")
    if write_history is not None:
        write_history = bool(write_history)

    return {
        "step_id": step_id,
        "task": task,
        "title": title,
        "severity_on_error": severity,
        "repos": _resolve_optional_repos(step.get("repos"), base_dir=runbook_dir),
        "repos_file": _resolve_optional_path(step.get("repos_file"), base_dir=runbook_dir, field="repos_file"),
        "repos_map": _resolve_optional_path(step.get("repos_map"), base_dir=runbook_dir, field="repos_map"),
        "allow_missing": allow_missing,
        "max_repos": max_repos,
        "jobs": jobs,
        "history_path": _resolve_optional_path(step.get("history_path"), base_dir=runbook_dir, field="history_path"),
        "write_history": write_history,
        "output_json": _resolve_optional_path(step.get("output_json"), base_dir=runbook_dir, field="output_json"),
        "output_md": _resolve_optional_path(step.get("output_md"), base_dir=runbook_dir, field="output_md"),
    }


def _payload_repos(payload: dict[str, Any]) -> list[dict[str, Any]]:
    repos = payload.get("repos")
    if isinstance(repos, list):
        return [item for item in repos if isinstance(item, dict)]
    latest = payload.get("latest")
    if isinstance(latest, dict):
        nested = latest.get("repos")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return []


def _failing_actions(step_result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = step_result.get("payload")
    if not isinstance(payload, dict):
        return []

    out: list[dict[str, Any]] = []
    for item in _payload_repos(payload):
        if str(item.get("status", "")) != "error":
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


def _step_value(step: dict[str, Any], key: str, default: Any) -> Any:
    value = step.get(key)
    return default if value is None else value


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
    apply_step_outputs: bool = False,
) -> tuple[dict[str, Any], int]:
    resolved_runbook = Path(runbook_path).expanduser().resolve()
    runbook = _load_runbook(resolved_runbook)
    steps = [_normalize_step(step, runbook_dir=resolved_runbook.parent) for step in runbook.get("steps", [])]
    report_captured_at = captured_at or now_utc_iso()

    checks: list[dict[str, Any]] = []
    top_actions: list[dict[str, Any]] = []
    for step in steps:
        step_repos = _step_value(step, "repos", repos)
        step_repos_file = _step_value(step, "repos_file", repos_file)
        step_repos_map = _step_value(step, "repos_map", repos_map)
        step_allow_missing = bool(_step_value(step, "allow_missing", allow_missing))
        step_max_repos = _step_value(step, "max_repos", max_repos)
        step_jobs = int(_step_value(step, "jobs", jobs))
        step_history_path = _step_value(step, "history_path", None)
        step_write_history = bool(_step_value(step, "write_history", write_history))
        step_output_json = _step_value(step, "output_json", None)
        step_output_md = _step_value(step, "output_md", None)

        if step["task"] == "health":
            payload, exit_code = run_portfolio_health_report(
                repos=step_repos,
                repos_file=step_repos_file,
                repos_map=step_repos_map,
                allow_missing=step_allow_missing,
                max_repos=step_max_repos,
                jobs=step_jobs,
                history_path=step_history_path or "data/portfolio/health_history.jsonl",
                captured_at=report_captured_at,
                write_history=step_write_history,
            )
            if apply_step_outputs:
                write_portfolio_health_outputs(payload, json_path=step_output_json, md_path=step_output_md)
        elif step["task"] == "release":
            payload, exit_code = run_portfolio_release_report(
                repos=step_repos,
                repos_file=step_repos_file,
                repos_map=step_repos_map,
                allow_missing=step_allow_missing,
                max_repos=step_max_repos,
                jobs=step_jobs,
                history_path=step_history_path or "data/portfolio/release_history.jsonl",
                captured_at=report_captured_at,
                write_history=step_write_history,
            )
            if apply_step_outputs:
                write_portfolio_release_outputs(payload, json_path=step_output_json, md_path=step_output_md)
        else:
            payload, exit_code = run_portfolio_task(
                task=step["task"],
                repos=step_repos,
                repos_file=step_repos_file,
                repos_map=step_repos_map,
                allow_missing=step_allow_missing,
                max_repos=step_max_repos,
                jobs=step_jobs,
                captured_at=report_captured_at,
                write_history=step_write_history,
                history_path=step_history_path,
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

    top_actions.sort(key=lambda row: (_SEVERITY_RANK[str(row["severity"])], str(row["step_id"]), str(row["repo_id"])))
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
            "path": str(resolved_runbook),
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
