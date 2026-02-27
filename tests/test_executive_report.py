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


def test_executive_runbook_contract() -> None:
    payload = json.loads(Path("data/executive/runbook.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["name"]
    assert isinstance(payload["steps"], list) and payload["steps"]
    for step in payload["steps"]:
        assert step["task"] in {"health", "release", "registry"}
        assert step["severity_on_error"] in {"high", "medium", "low"}


def test_executive_report_emits_top_actions_and_outputs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()
    repos_map = tmp_path / "repos.json"
    runbook = tmp_path / "runbook.json"
    out_json = tmp_path / "executive_report.json"
    out_md = tmp_path / "executive_report.md"

    _write_json(
        repos_map,
        {
            "schema_version": "1.1",
            "repos": [
                {
                    "repo_id": "repo_a",
                    "path": str(repo_root),
                    "execution_policy": {
                        "health_command": "sh -lc 'exit 0'",
                        "release_command": "sh -lc 'exit 2'",
                        "registry_command": "sh -lc 'exit 0'",
                    },
                }
            ],
        },
    )
    _write_json(
        runbook,
        {
            "schema_version": "1.0",
            "name": "test_exec",
            "steps": [
                {"step_id": "health", "title": "Health", "task": "health", "severity_on_error": "high"},
                {"step_id": "release", "title": "Release", "task": "release", "severity_on_error": "high"},
                {"step_id": "registry", "title": "Registry", "task": "registry", "severity_on_error": "medium"},
            ],
        },
    )

    p = _run(
        [
            "operator",
            "executive",
            "report",
            "--json",
            "--runbook",
            str(runbook),
            "--repos-map",
            str(repos_map),
            "--captured-at",
            "2026-02-22T00:00:00Z",
            "--no-write-history",
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
        ]
    )
    assert p.returncode == 2, p.stderr
    payload = json.loads(p.stdout)
    assert payload["command"] == "executive_report"
    assert payload["status"] == "needs_attention"
    assert payload["summary"]["steps_total"] == 3
    assert payload["summary"]["steps_error"] == 1
    assert payload["top_actions"]
    assert payload["top_actions"][0]["repo_id"] == "repo_a"
    assert out_json.exists()
    assert out_md.exists()
