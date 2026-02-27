from __future__ import annotations

import json
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.portfolio_policy import PortfolioRepo, resolve_portfolio_repos


PORTFOLIO_RUN_SCHEMA_VERSION = "1.0"
ERR_INVALID_POLICY_MAP = "INVALID_POLICY_MAP"
ERR_REPO_PATH_NOT_FOUND = "REPO_PATH_NOT_FOUND"
ERR_TASK_POLICY_MISSING = "TASK_POLICY_MISSING"
ERR_TASK_EXCLUDED = "TASK_EXCLUDED"
ERR_TASK_TIMEOUT = "TASK_TIMEOUT"
ERR_TASK_FAILED = "TASK_FAILED"
_ALLOWED_TASKS = {"health", "release", "registry"}


@dataclass(frozen=True)
class TaskResult:
    repo: PortfolioRepo
    task: str
    status: str
    rc: int
    command: str
    stdout: str
    stderr: str
    error_code: str
    reason: str
    timeout_seconds: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo.to_dict(),
            "task": self.task,
            "status": self.status,
            "rc": self.rc,
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error_code": self.error_code,
            "reason": self.reason,
            "timeout_seconds": self.timeout_seconds,
        }


def _render_command(command: str, repo: PortfolioRepo) -> str:
    preferred_python = repo.execution_policy.preferred_python or sys.executable
    rendered = command.replace("{python}", shlex.quote(preferred_python))
    if command != rendered:
        return rendered

    try:
        tokens = shlex.split(command)
    except ValueError:
        return command
    if not tokens:
        return command

    first = tokens[0]
    if first in {"python", "python3", "py"}:
        tokens[0] = preferred_python
        return " ".join(shlex.quote(token) for token in tokens)
    if first == "pytest":
        rewritten = [preferred_python, "-m", "pytest", *tokens[1:]]
        return " ".join(shlex.quote(token) for token in rewritten)
    return command


def _missing_repo_result(repo: PortfolioRepo, task: str, *, allow_missing: bool) -> TaskResult:
    status = "skipped" if (allow_missing or not repo.required) else "error"
    return TaskResult(
        repo=repo,
        task=task,
        status=status,
        rc=0 if status == "skipped" else 2,
        command="",
        stdout="",
        stderr="",
        error_code=ERR_REPO_PATH_NOT_FOUND,
        reason="repo_path_missing_allowed" if status == "skipped" else "repo_path_missing_required",
        timeout_seconds=None,
    )


def _execute_task(repo: PortfolioRepo, task: str, *, allow_missing: bool) -> TaskResult:
    repo_path = Path(repo.repo_root)
    if not repo_path.exists():
        return _missing_repo_result(repo, task, allow_missing=allow_missing)

    if task in repo.excluded_tasks:
        return TaskResult(
            repo=repo,
            task=task,
            status="skipped",
            rc=0,
            command="",
            stdout="",
            stderr="",
            error_code=ERR_TASK_EXCLUDED,
            reason="task_excluded_by_policy",
            timeout_seconds=repo.task_timeouts_seconds.get(task),
        )

    command = repo.execution_policy.command_for_task(task)
    if not command:
        return TaskResult(
            repo=repo,
            task=task,
            status="skipped",
            rc=0,
            command="",
            stdout="",
            stderr="",
            error_code=ERR_TASK_POLICY_MISSING,
            reason="task_command_not_configured",
            timeout_seconds=repo.task_timeouts_seconds.get(task),
        )

    rendered = _render_command(command, repo)
    timeout_seconds = repo.task_timeouts_seconds.get(task)
    try:
        completed = subprocess.run(
            rendered,
            cwd=repo.repo_root,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return TaskResult(
            repo=repo,
            task=task,
            status="error",
            rc=124,
            command=rendered,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            error_code=ERR_TASK_TIMEOUT,
            reason="task_timeout",
            timeout_seconds=timeout_seconds,
        )

    status = "ok" if completed.returncode == 0 else "error"
    return TaskResult(
        repo=repo,
        task=task,
        status=status,
        rc=int(completed.returncode),
        command=rendered,
        stdout=completed.stdout,
        stderr=completed.stderr,
        error_code="" if status == "ok" else ERR_TASK_FAILED,
        reason="task_ok" if status == "ok" else "task_command_failed",
        timeout_seconds=timeout_seconds,
    )


def _summary(results: list[TaskResult]) -> dict[str, int]:
    return {
        "repos_selected": len(results),
        "repos_ok": sum(1 for item in results if item.status == "ok"),
        "repos_error": sum(1 for item in results if item.status == "error"),
        "repos_skipped": sum(1 for item in results if item.status == "skipped"),
    }


def run_portfolio_task(
    *,
    task: str,
    repos: list[str] | None = None,
    repos_file: str | None = None,
    repos_map: str | None = None,
    allow_missing: bool = False,
    max_repos: int | None = None,
    jobs: int = 1,
) -> tuple[dict[str, Any], int]:
    if task not in _ALLOWED_TASKS:
        payload = {
            "schema_version": PORTFOLIO_RUN_SCHEMA_VERSION,
            "command": "portfolio_run",
            "task": task,
            "status": "error",
            "error_code": ERR_INVALID_POLICY_MAP,
            "message": f"unsupported task: {task}",
            "repos": [],
            "summary": {"repos_selected": 0, "repos_ok": 0, "repos_error": 0, "repos_skipped": 0},
        }
        return payload, 5

    try:
        repo_specs = resolve_portfolio_repos(
            repos=repos,
            repos_file=repos_file,
            repos_map=repos_map,
            max_repos=max_repos,
        )
    except ValueError as exc:
        payload = {
            "schema_version": PORTFOLIO_RUN_SCHEMA_VERSION,
            "command": "portfolio_run",
            "task": task,
            "status": "error",
            "error_code": ERR_INVALID_POLICY_MAP,
            "message": str(exc),
            "repos": [],
            "summary": {"repos_selected": 0, "repos_ok": 0, "repos_error": 0, "repos_skipped": 0},
        }
        return payload, 5

    if jobs <= 1:
        results = [_execute_task(repo, task, allow_missing=allow_missing) for repo in repo_specs]
    else:
        with ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
            futures = [pool.submit(_execute_task, repo, task, allow_missing=allow_missing) for repo in repo_specs]
            results = [future.result() for future in futures]

    results.sort(key=lambda item: (item.repo.repo_id, item.repo.repo_root))
    summary = _summary(results)
    status = "ok" if summary["repos_error"] == 0 else "needs_attention"
    payload = {
        "schema_version": PORTFOLIO_RUN_SCHEMA_VERSION,
        "command": "portfolio_run",
        "task": task,
        "status": status,
        "repos": [item.to_dict() for item in results],
        "summary": summary,
    }
    return payload, 0 if status == "ok" else 2


def dump_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
