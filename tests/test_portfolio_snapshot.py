from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_portfolio_snapshot_write_tail_diff_deterministic(tmp_path: Path) -> None:
    # Create two deterministic repos
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr
    p = _run(["failcase", "create", "--path", str(repo_b), "--mode", "sla-breach"])
    assert p.returncode == 0, p.stderr

    ledger = tmp_path / "portfolio_snapshot_history.jsonl"

    # Write two snapshots with deterministic captured_at
    p = _run(
        [
            "report",
            "portfolio-snapshot",
            "--write",
            "--json",
            "--ledger",
            str(ledger),
            "--repos",
            str(repo_a),
            str(repo_b),
            "--hide-samples",
            "--strict",
            "--enforce-sla",
            "--jobs",
            "1",
            "--captured-at",
            "2026-02-22T00:00:00+00:00",
        ]
    )
    assert p.returncode == 0, p.stderr
    s1 = json.loads(p.stdout)
    assert s1["schema_version"] == "1.0"

    p = _run(
        [
            "report",
            "portfolio-snapshot",
            "--write",
            "--json",
            "--ledger",
            str(ledger),
            "--repos",
            str(repo_a),
            str(repo_b),
            "--hide-samples",
            "--strict",
            "--enforce-sla",
            "--jobs",
            "1",
            "--captured-at",
            "2026-02-22T00:00:01+00:00",
        ]
    )
    assert p.returncode == 0, p.stderr

    # Tail returns 2 rows
    p = _run(["report", "portfolio-snapshot", "tail", "--json", "--ledger", str(ledger), "--n", "2"])
    assert p.returncode == 0, p.stderr
    t = json.loads(p.stdout)
    assert len(t["rows"]) == 2

    # Diff prev->latest is stable and includes expected keys
    p = _run(["report", "portfolio-snapshot", "diff", "--json", "--ledger", str(ledger), "--a", "prev", "--b", "latest"])
    assert p.returncode == 0, p.stderr
    d = json.loads(p.stdout)
    assert d["schema_version"] == "1.0"
    assert "portfolio_status_change" in d
    assert "repos_changed" in d
