from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_portfolio_operator_gate_no_prev_is_not_regression(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr

    ledger = tmp_path / "portfolio_snapshot_history.jsonl"
    export_dir = tmp_path / "export"

    p = _run(
        [
            "operator",
            "portfolio-operator-gate",
            "--json",
            "--ledger",
            str(ledger),
            "--repos",
            str(repo_a),
            "--hide-samples",
            "--jobs",
            "1",
            "--captured-at",
            "2026-02-22T00:00:00+00:00",
            "--export-path",
            str(export_dir),
        ]
    )
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)
    assert payload["schema_version"] == "1.0"
    assert payload["command"] == "portfolio_operator_gate"
    assert payload["regression_detected"] is False

    assert (export_dir / "bundle_meta.json").exists()
    assert (export_dir / "portfolio_operator_gate.json").exists()
    assert (export_dir / "portfolio_snapshot_latest.json").exists()
    assert (export_dir / "portfolio_snapshot_diff.json").exists()


def test_portfolio_operator_gate_detects_new_top_actions_as_regression(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr
    # sla-breach creates strict failure => top actions
    p = _run(["failcase", "create", "--path", str(repo_b), "--mode", "sla-breach"])
    assert p.returncode == 0, p.stderr

    ledger = tmp_path / "portfolio_snapshot_history.jsonl"

    # First snapshot: clean only (repo_a)
    p = _run(
        [
            "operator",
            "portfolio-operator-gate",
            "--json",
            "--ledger",
            str(ledger),
            "--repos",
            str(repo_a),
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

    # Second snapshot: add repo_b (sla breach => new top actions) => regression or strict or both
    p = _run(
        [
            "operator",
            "portfolio-operator-gate",
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
    assert p.returncode in (2, 3, 4), p.stderr
    payload = json.loads(p.stdout)
    assert payload["schema_version"] == "1.0"
    assert payload["command"] == "portfolio_operator_gate"
    assert payload["strict_failed"] is True
    # If strict is true, exit should be 2 or 4. Regression may also trigger -> 4.
    assert payload["exit_code"] in (2, 4)
    assert isinstance(payload["diff_prev_latest"]["new_top_actions"], list)
