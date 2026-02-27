from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_executive_report_top_level_contract_is_pinned(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()
    repos_map = tmp_path / "repos.json"
    runbook = tmp_path / "runbook.json"

    _write_json(
        repos_map,
        {
            "schema_version": "1.1",
            "repos": [
                {
                    "repo_id": "repo_a",
                    "path": str(repo_root),
                    "execution_policy": {"health_command": "sh -lc 'exit 0'"},
                }
            ],
        },
    )
    _write_json(
        runbook,
        {
            "schema_version": "1.0",
            "name": "contract_exec",
            "steps": [
                {
                    "step_id": "health",
                    "title": "Health",
                    "task": "health",
                    "severity_on_error": "high",
                    "repos_map": str(repos_map),
                }
            ],
        },
    )

    p = _run(
        [
            "operator",
            "executive",
            "status",
            "--json",
            "--runbook",
            str(runbook),
            "--captured-at",
            "2026-02-22T00:00:00Z",
            "--no-write-history",
        ]
    )
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)

    assert set(payload.keys()) == {
        "schema_version",
        "command",
        "captured_at",
        "status",
        "runbook",
        "summary",
        "checks",
        "top_actions",
    }
    assert isinstance(payload["schema_version"], str)
    assert isinstance(payload["command"], str)
    assert isinstance(payload["captured_at"], str)
    assert isinstance(payload["status"], str)
    assert isinstance(payload["runbook"], dict)
    assert isinstance(payload["summary"], dict)
    assert isinstance(payload["checks"], list)
    assert isinstance(payload["top_actions"], list)
    assert set(payload["runbook"].keys()) == {"schema_version", "name", "path"}
    assert set(payload["summary"].keys()) == {"steps_total", "steps_ok", "steps_error"}
