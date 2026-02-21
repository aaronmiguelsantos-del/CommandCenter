from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_portfolio_gate_deterministic_output(tmp_path: Path) -> None:
    # Create two deterministic registries using failcase generator.
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"

    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr
    p = _run(["failcase", "create", "--path", str(repo_b), "--mode", "clean"])
    assert p.returncode == 0, p.stderr

    args = [
        "operator",
        "portfolio-gate",
        "--json",
        "--repos",
        str(repo_a),
        str(repo_b),
        "--hide-samples",
    ]
    p1 = _run(args)
    p2 = _run(args)
    assert p1.returncode == 0, p1.stderr
    assert p2.returncode == 0, p2.stderr
    assert p1.stdout == p2.stdout


def test_portfolio_gate_export_bundle(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr

    export_dir = tmp_path / "portfolio_export"
    p = _run(
        [
            "operator",
            "portfolio-gate",
            "--json",
            "--repos",
            str(repo_a),
            "--hide-samples",
            "--export-path",
            str(export_dir),
        ]
    )
    assert p.returncode == 0, p.stderr
    assert (export_dir / "portfolio_gate.json").exists()
    assert (export_dir / "bundle_meta.json").exists()

    meta = json.loads((export_dir / "bundle_meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == "1.0"
    assert meta["artifacts"] == ["bundle_meta.json", "portfolio_gate.json"]


def test_portfolio_gate_exit_code_aggregates_strict(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"

    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr
    p = _run(["failcase", "create", "--path", str(repo_b), "--mode", "sla-breach"])
    assert p.returncode == 0, p.stderr

    # Strict + enforce-sla should produce strict fail for repo_b -> portfolio exit 2 or 4.
    p = _run(
        [
            "operator",
            "portfolio-gate",
            "--json",
            "--repos",
            str(repo_a),
            str(repo_b),
            "--hide-samples",
            "--strict",
            "--enforce-sla",
        ]
    )
    assert p.returncode in (2, 4), p.stderr
    payload = json.loads(p.stdout)
    assert payload["portfolio_exit_code"] in (2, 4)
    assert payload["command"] == "portfolio_gate"
    assert payload["schema_version"] == "1.0"
