from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_repos_map(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_portfolio_run_health_uses_explicit_policy(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()
    repos_map = tmp_path / "repos.json"
    _write_repos_map(
        repos_map,
        {
            "schema_version": "1.1",
            "repos": [
                {
                    "repo_id": "repo_a",
                    "path": str(repo_root),
                    "execution_policy": {
                        "health_command": "{python} -c \"print('healthy')\"",
                        "preferred_python": sys.executable,
                    },
                }
            ],
        },
    )

    p = _run(["operator", "portfolio-run", "--json", "--task", "health", "--repos-map", str(repos_map)])
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)
    assert payload["command"] == "portfolio_run"
    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "ok"
    assert payload["summary"]["repos_ok"] == 1
    assert payload["repos"][0]["stdout"].strip() == "healthy"


def test_portfolio_run_skips_missing_policy_instead_of_inferring(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()

    p = _run(["operator", "portfolio-run", "--json", "--task", "health", "--repos", str(repo_root)])
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)
    assert payload["status"] == "ok"
    assert payload["summary"]["repos_skipped"] == 1
    assert payload["repos"][0]["error_code"] == "TASK_POLICY_MISSING"


def test_portfolio_run_release_failure_returns_nonzero(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()
    repos_map = tmp_path / "repos.json"
    _write_repos_map(
        repos_map,
        {
            "schema_version": "1.1",
            "repos": [
                {
                    "repo_id": "repo_a",
                    "path": str(repo_root),
                    "execution_policy": {
                        "release_command": "{python} -c \"import sys; sys.exit(2)\"",
                        "preferred_python": sys.executable,
                    },
                }
            ],
        },
    )

    p = _run(["operator", "portfolio-run", "--json", "--task", "release", "--repos-map", str(repos_map)])
    assert p.returncode == 2, p.stderr
    payload = json.loads(p.stdout)
    assert payload["status"] == "needs_attention"
    assert payload["summary"]["repos_error"] == 1
    assert payload["repos"][0]["error_code"] == "TASK_FAILED"


def test_portfolio_run_allow_missing_demotes_missing_repo_to_skipped(tmp_path: Path) -> None:
    missing_repo = tmp_path / "missing_repo"
    repos_map = tmp_path / "repos.json"
    _write_repos_map(
        repos_map,
        {
            "schema_version": "1.1",
            "repos": [
                {
                    "repo_id": "missing",
                    "path": str(missing_repo),
                    "execution_policy": {
                        "health_command": "{python} -c \"print('never')\"",
                        "preferred_python": sys.executable,
                    },
                }
            ],
        },
    )

    p = _run(
        [
            "operator",
            "portfolio-run",
            "--json",
            "--task",
            "health",
            "--repos-map",
            str(repos_map),
            "--allow-missing",
        ]
    )
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)
    assert payload["summary"]["repos_skipped"] == 1
    assert payload["repos"][0]["status"] == "skipped"
    assert payload["repos"][0]["error_code"] == "REPO_PATH_NOT_FOUND"


def test_portfolio_run_respects_excluded_tasks(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()
    repos_map = tmp_path / "repos.json"
    _write_repos_map(
        repos_map,
        {
            "schema_version": "1.1",
            "repos": [
                {
                    "repo_id": "repo_a",
                    "path": str(repo_root),
                    "excluded_tasks": ["registry"],
                    "execution_policy": {
                        "registry_command": "{python} -c \"print('nope')\"",
                        "preferred_python": sys.executable,
                    },
                }
            ],
        },
    )

    p = _run(["operator", "portfolio-run", "--json", "--task", "registry", "--repos-map", str(repos_map)])
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)
    assert payload["summary"]["repos_skipped"] == 1
    assert payload["repos"][0]["error_code"] == "TASK_EXCLUDED"
