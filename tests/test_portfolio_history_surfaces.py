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


def test_portfolio_health_history_tail_stats_diff(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo_a"
    repo_root.mkdir()
    history_path = tmp_path / "health_history.jsonl"
    repos_map = tmp_path / "repos.json"

    _write_map(
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
    p1 = _run(
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
                    "execution_policy": {"health_command": "sh -lc 'exit 2'"},
                }
            ],
        },
    )
    p2 = _run(
        [
            "report",
            "portfolio-health",
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

    tail = _run(
        [
            "report",
            "portfolio-health",
            "tail",
            "--json",
            "--history-path",
            str(history_path),
            "--n",
            "2",
        ]
    )
    assert tail.returncode == 0, tail.stderr
    tail_payload = json.loads(tail.stdout)
    assert tail_payload["command"] == "portfolio_health_tail"
    assert len(tail_payload["history"]["rows"]) == 2

    stats = _run(
        [
            "report",
            "portfolio-health",
            "stats",
            "--json",
            "--history-path",
            str(history_path),
            "--days",
            "30",
        ]
    )
    assert stats.returncode == 0, stats.stderr
    stats_payload = json.loads(stats.stdout)
    assert stats_payload["command"] == "portfolio_health_stats"
    assert stats_payload["history"]["entry_count"] == 2
    assert stats_payload["status_counts"]["ok"] == 1
    assert stats_payload["status_counts"]["needs_attention"] == 1

    diff = _run(
        [
            "report",
            "portfolio-health",
            "diff",
            "--json",
            "--history-path",
            str(history_path),
            "--a",
            "prev",
            "--b",
            "latest",
        ]
    )
    assert diff.returncode == 0, diff.stderr
    diff_payload = json.loads(diff.stdout)
    assert diff_payload["command"] == "portfolio_health_diff"
    assert diff_payload["status_change"]["changed"] is True
    assert diff_payload["summary_delta"]["repos_error_delta"] == 1


def test_portfolio_release_history_tail_stats_diff(tmp_path: Path) -> None:
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
                    "execution_policy": {"release_command": "sh -lc 'exit 0'"},
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
                    "execution_policy": {"release_command": "sh -lc 'exit 2'"},
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

    tail = _run(
        [
            "report",
            "portfolio-release",
            "tail",
            "--json",
            "--history-path",
            str(history_path),
            "--n",
            "2",
        ]
    )
    assert tail.returncode == 0, tail.stderr
    tail_payload = json.loads(tail.stdout)
    assert tail_payload["command"] == "portfolio_release_tail"
    assert len(tail_payload["history"]["rows"]) == 2

    stats = _run(
        [
            "report",
            "portfolio-release",
            "stats",
            "--json",
            "--history-path",
            str(history_path),
            "--days",
            "30",
        ]
    )
    assert stats.returncode == 0, stats.stderr
    stats_payload = json.loads(stats.stdout)
    assert stats_payload["command"] == "portfolio_release_stats"
    assert stats_payload["history"]["entry_count"] == 2
    assert stats_payload["status_counts"]["ok"] == 1
    assert stats_payload["status_counts"]["needs_attention"] == 1

    diff = _run(
        [
            "report",
            "portfolio-release",
            "diff",
            "--json",
            "--history-path",
            str(history_path),
            "--a",
            "prev",
            "--b",
            "latest",
        ]
    )
    assert diff.returncode == 0, diff.stderr
    diff_payload = json.loads(diff.stdout)
    assert diff_payload["command"] == "portfolio_release_diff"
    assert diff_payload["status_change"]["changed"] is True
    assert diff_payload["summary_delta"]["repos_error_delta"] == 1
