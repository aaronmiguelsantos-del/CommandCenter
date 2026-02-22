from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_portfolio_gate_deterministic_output(tmp_path: Path) -> None:
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
        "--jobs",
        "1",
    ]
    p1 = _run(args)
    p2 = _run(args)
    assert p1.returncode == 0, p1.stderr
    assert p2.returncode == 0, p2.stderr
    assert p1.stdout == p2.stdout

    payload = json.loads(p1.stdout)
    assert payload["schema_version"] == "1.1"
    assert payload["command"] == "portfolio_gate"
    assert "summary" in payload
    assert isinstance(payload["summary"]["portfolio_score"], int)


def test_portfolio_gate_parallel_determinism(tmp_path: Path) -> None:
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
        "--jobs",
        "2",
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
            "--jobs",
            "1",
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

    pg = json.loads((export_dir / "portfolio_gate.json").read_text(encoding="utf-8"))
    assert pg["schema_version"] == "1.1"


def test_portfolio_gate_export_mode_with_repo_gates(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr
    p = _run(["failcase", "create", "--path", str(repo_b), "--mode", "clean"])
    assert p.returncode == 0, p.stderr

    export_dir = tmp_path / "portfolio_export"
    p = _run(
        [
            "operator",
            "portfolio-gate",
            "--json",
            "--repos",
            str(repo_a),
            str(repo_b),
            "--hide-samples",
            "--export-path",
            str(export_dir),
            "--export-mode",
            "with-repo-gates",
            "--jobs",
            "1",
        ]
    )
    assert p.returncode == 0, p.stderr
    meta = json.loads((export_dir / "bundle_meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == "1.0"
    artifacts = meta["artifacts"]
    assert "portfolio_gate.json" in artifacts
    assert "bundle_meta.json" in artifacts
    assert any(a.startswith("repo_") and a.endswith("_operator_gate.json") for a in artifacts)


def test_portfolio_gate_exit_code_aggregates_strict(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"

    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr
    p = _run(["failcase", "create", "--path", str(repo_b), "--mode", "sla-breach"])
    assert p.returncode == 0, p.stderr

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
            "--jobs",
            "1",
        ]
    )
    assert p.returncode in (2, 4), p.stderr
    payload = json.loads(p.stdout)
    assert payload["portfolio_exit_code"] in (2, 4)
    assert payload["schema_version"] == "1.1"
    assert payload["summary"]["portfolio_status"] in ("yellow", "red")


def test_portfolio_gate_missing_required_repo_forces_regression_unless_allow_missing(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr

    missing = tmp_path / "does_not_exist"
    assert not missing.exists()

    p = _run(
        [
            "operator",
            "portfolio-gate",
            "--json",
            "--repos",
            str(repo_a),
            str(missing),
            "--hide-samples",
            "--jobs",
            "1",
        ]
    )
    assert p.returncode in (3, 4), p.stderr
    payload = json.loads(p.stdout)
    assert payload["portfolio_exit_code"] in (3, 4)
    errs = [r for r in payload["repos"] if r.get("repo_status") == "error"]
    assert errs

    p = _run(
        [
            "operator",
            "portfolio-gate",
            "--json",
            "--repos",
            str(repo_a),
            str(missing),
            "--hide-samples",
            "--allow-missing",
            "--jobs",
            "1",
        ]
    )
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)
    assert payload["portfolio_exit_code"] == 0
    assert payload["summary"]["repos_error"] >= 1


def test_portfolio_gate_repo_map_policy_overrides_disable_enforce_sla(tmp_path: Path) -> None:
    """
    repo_b is sla-breach. Global flags enforce strict+enforce-sla, but repo_map overrides disable enforce_sla for repo_b.
    Expect: no strict failure from repo_b (portfolio can remain clean).
    """
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    p = _run(["failcase", "create", "--path", str(repo_a), "--mode", "clean"])
    assert p.returncode == 0, p.stderr
    p = _run(["failcase", "create", "--path", str(repo_b), "--mode", "sla-breach"])
    assert p.returncode == 0, p.stderr

    repos_map = tmp_path / "repos.json"
    repos_map.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "repos": [
                    {
                        "repo_id": "a",
                        "path": str(repo_a),
                        "owner": "t",
                        "required": True,
                        "policy_overrides": {"strict": True, "enforce_sla": True, "hide_samples": True},
                    },
                    {
                        "repo_id": "b",
                        "path": str(repo_b),
                        "owner": "t",
                        "required": True,
                        # override enforce_sla OFF
                        "policy_overrides": {"strict": True, "enforce_sla": False, "hide_samples": True},
                    },
                ],
            },
            sort_keys=True,
        )
    )

    p = _run(
        [
            "operator",
            "portfolio-gate",
            "--json",
            "--repos-map",
            str(repos_map),
            "--hide-samples",
            "--strict",
            "--enforce-sla",
            "--jobs",
            "1",
        ]
    )
    assert p.returncode == 0, p.stderr
    payload = json.loads(p.stdout)
    assert payload["portfolio_exit_code"] == 0
    # ensure repo b effective_policy reflects override
    b = [r for r in payload["repos"] if r["repo"]["repo_id"] == "b"][0]
    assert b["effective_policy"]["enforce_sla"] is False
