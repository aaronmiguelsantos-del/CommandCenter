from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_portfolio_operator_gate_export_contract(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr

    export_dir = tmp_path / "export"
    p = _run(
        [
            "operator",
            "portfolio-operator-gate",
            "--json",
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

    # bundle_meta pinned
    meta = _load(export_dir / "bundle_meta.json")
    assert meta["schema_version"] == "1.0"
    assert meta["artifacts"] == [
        "bundle_meta.json",
        "portfolio_operator_gate.json",
        "portfolio_snapshot_latest.json",
        "portfolio_snapshot_diff.json",
    ]

    pog = _load(export_dir / "portfolio_operator_gate.json")
    assert pog["schema_version"] == "1.0"
    assert pog["command"] == "portfolio_operator_gate"

    # Pin keys (contract drift sentinel)
    expected_keys = {
        "schema_version",
        "command",
        "exit_code",
        "strict_failed",
        "regression_detected",
        "policy",
        "snapshot_latest",
        "diff_prev_latest",
        "regression_reasons",
        "artifacts",
    }
    assert set(pog.keys()) == expected_keys

    # Pin types
    assert isinstance(pog["exit_code"], int)
    assert isinstance(pog["strict_failed"], bool)
    assert isinstance(pog["regression_detected"], bool)
    assert isinstance(pog["policy"], dict)
    assert isinstance(pog["snapshot_latest"], dict)
    assert isinstance(pog["diff_prev_latest"], dict)
    assert isinstance(pog["regression_reasons"], list)
    assert isinstance(pog["artifacts"], dict)
