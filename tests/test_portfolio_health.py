from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_map(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_portfolio_health_report_writes_history_and_outputs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()
    history_path = tmp_path / "health_history.jsonl"
    out_json = tmp_path / "portfolio_health.json"
    out_md = tmp_path / "portfolio_health.md"
    repos_map = tmp_path / "repos.json"
    _write_map(
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

    p = _run(
        [
            "report",
            "portfolio-health",
            "--json",
            "--repos-map",
            str(repos_map),
            "--history-path",
            str(history_path),
            "--captured-at",
            "2026-02-22T00:00:00Z",
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
        ]
    )
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)
    assert payload["command"] == "portfolio_health_report"
    assert payload["summary"]["repos_ok"] == 1
    assert payload["history"]["entry_count"] == 1
    assert out_json.exists()
    assert out_md.exists()


def test_portfolio_release_report_tracks_transitions(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()
    history_path = tmp_path / "release_history.jsonl"
    repos_map = tmp_path / "repos.json"

    _write_map(
        repos_map,
        {
            "schema_version": "1.1",
            "repos": [
                {
                    "repo_id": "repo_a",
                    "path": str(repo_root),
                    "execution_policy": {
                        "release_command": "sh -lc 'exit 0'",
                    },
                }
            ],
        },
    )

    p1 = _run(
        [
            "report",
            "portfolio-release",
            "--json",
            "--repos-map",
            str(repos_map),
            "--history-path",
            str(history_path),
            "--captured-at",
            "2026-02-22T00:00:00Z",
        ]
    )
    assert p1.returncode == 0, p1.stderr

    _write_map(
        repos_map,
        {
            "schema_version": "1.1",
            "repos": [
                {
                    "repo_id": "repo_a",
                    "path": str(repo_root),
                    "execution_policy": {
                        "release_command": "sh -lc 'exit 2'",
                    },
                }
            ],
        },
    )

    p2 = _run(
        [
            "report",
            "portfolio-release",
            "--json",
            "--repos-map",
            str(repos_map),
            "--history-path",
            str(history_path),
            "--captured-at",
            "2026-02-23T00:00:00Z",
        ]
    )
    assert p2.returncode == 2, p2.stderr
    payload = json.loads(p2.stdout)
    assert payload["command"] == "portfolio_release_report"
    assert payload["summary"]["repos_error"] == 1
    assert payload["history"]["entry_count"] == 2
    assert payload["repo_transitions"][0]["from"] == "ok"
    assert payload["repo_transitions"][0]["to"] == "error"
