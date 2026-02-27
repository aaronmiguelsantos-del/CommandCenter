from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def _normalize(payload: dict[str, Any], repo_root: Path, history_path: Path) -> dict[str, Any]:
    text = json.dumps(payload, sort_keys=True)
    text = text.replace(str(repo_root.resolve()), "__REPO_ROOT__")
    text = text.replace(str(history_path.resolve()), "__HISTORY_PATH__")
    return json.loads(text)


def _write_map(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_portfolio_run_health_snapshot(tmp_path: Path) -> None:
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
                    "execution_policy": {
                        "health_command": "sh -lc 'printf healthy'",
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
            "--history-path",
            str(history_path),
            "--captured-at",
            "2026-02-22T00:00:00Z",
        ]
    )
    assert p.returncode == 0, p.stderr
    actual = _normalize(json.loads(p.stdout), repo_root, history_path)
    expected = json.loads((SNAPSHOT_DIR / "portfolio_run_health.expected.json").read_text(encoding="utf-8"))
    assert actual == expected


def test_portfolio_run_release_error_snapshot(tmp_path: Path) -> None:
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
                        "release_command": "sh -lc 'exit 2'",
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
            "release",
            "--repos-map",
            str(repos_map),
            "--history-path",
            str(history_path),
            "--captured-at",
            "2026-02-22T00:00:00Z",
        ]
    )
    assert p.returncode == 2, p.stderr
    actual = _normalize(json.loads(p.stdout), repo_root, history_path)
    expected = json.loads((SNAPSHOT_DIR / "portfolio_run_release_error.expected.json").read_text(encoding="utf-8"))
    assert actual == expected
