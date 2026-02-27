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
    health_step = next(step for step in payload["steps"] if step["task"] == "health")
    release_step = next(step for step in payload["steps"] if step["task"] == "release")
    assert health_step["repos_map"]
    assert health_step["history_path"]
    assert health_step["output_json"]
    assert health_step["output_md"]
    assert release_step["repos_map"]
    assert release_step["history_path"]
    assert release_step["output_json"]
    assert release_step["output_md"]


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


def test_executive_report_step_overrides_write_step_outputs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()
    repos_map = tmp_path / "repos.json"
    runbook = tmp_path / "runbook.json"
    step_history = tmp_path / "step_health_history.jsonl"
    step_json = tmp_path / "step_health.json"
    step_md = tmp_path / "step_health.md"

    _write_json(
        repos_map,
        {
            "schema_version": "1.1",
            "repos": [
                {
                    "repo_id": "repo_a",
                    "path": str(repo_root),
                    "execution_policy": {
                        "health_command": "sh -lc 'printf healthy'",
                    },
                }
            ],
        },
    )
    _write_json(
        runbook,
        {
            "schema_version": "1.0",
            "name": "test_exec_overrides",
            "steps": [
                {
                    "step_id": "health",
                    "title": "Health",
                    "task": "health",
                    "severity_on_error": "high",
                    "repos_map": str(repos_map),
                    "history_path": str(step_history),
                    "output_json": str(step_json),
                    "output_md": str(step_md),
                    "write_history": True,
                }
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
            "--captured-at",
            "2026-02-22T00:00:00Z",
            "--no-write-history",
        ]
    )
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)
    assert payload["status"] == "ok"
    assert payload["summary"]["steps_total"] == 1
    assert step_history.exists()
    assert step_json.exists()
    assert step_md.exists()
