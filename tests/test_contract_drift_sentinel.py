import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """
    Subprocess runner to validate real CLI behavior (argparse + I/O).
    """
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    py_path = str(repo_root)
    if env.get("PYTHONPATH"):
        py_path = py_path + os.pathsep + env["PYTHONPATH"]
    env["PYTHONPATH"] = py_path
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd is not None else str(repo_root),
        env=env,
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _assert_schema_version(payload: dict[str, Any], expected: str) -> None:
    assert "schema_version" in payload, "missing schema_version"
    assert payload["schema_version"] == expected, f"schema_version drift: {payload['schema_version']} != {expected}"


def _assert_exact_keys(payload: dict[str, Any], expected_keys: set[str]) -> None:
    keys = set(payload.keys())
    assert keys == expected_keys, f"schema keys drift:\nexpected={sorted(expected_keys)}\nactual={sorted(keys)}"


def _assert_types(payload: dict[str, Any], type_map: dict[str, type]) -> None:
    for k, t in type_map.items():
        assert k in payload, f"missing required key: {k}"
        assert isinstance(payload[k], t), f"type drift for {k}: {type(payload[k])} != {t}"


def test_contract_drift_sentinel_export_bundle(tmp_path: Path) -> None:
    """
    Contract Drift Sentinel (v3.1.0):
    - Pins exported artifact schemas and top-level keys/types.
    - Any schema change requires:
      1) schema_version bump
      2) contract docs update
      3) this test update
    """
    root = tmp_path / "failcase"
    work_dir = tmp_path / "work"
    export_dir = tmp_path / "export"
    work_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)

    # Deterministic fixture repo + isolated working directory.
    p = _run(["failcase", "create", "--path", str(root), "--mode", "sla-breach"], cwd=work_dir)
    assert p.returncode == 0, f"failcase create failed: {p.stderr}"

    registry = root / "data" / "registry" / "systems.json"
    assert registry.exists()

    isolated_ledger = work_dir / "data" / "snapshots" / "report_snapshot_history.jsonl"

    # Export must succeed cleanly for this fixture.
    p = _run(
        [
            "operator",
            "gate",
            "--json",
            "--hide-samples",
            "--registry",
            str(registry),
            "--ledger",
            str(isolated_ledger),
            "--export-path",
            str(export_dir),
        ],
        cwd=work_dir,
    )
    assert p.returncode == 0, f"operator gate clean fixture failed:\nstderr={p.stderr}\nstdout={p.stdout}"

    # Required exported artifacts (contract)
    expected_artifacts = [
        "bundle_meta.json",
        "graph.json",
        "operator_gate.json",
        "report_health.json",
        "snapshot_diff.json",
        "snapshot_latest.json",
        "snapshot_stats.json",
        "snapshot_tail.json",
    ]
    for name in expected_artifacts:
        assert (export_dir / name).exists(), f"missing exported artifact: {name}"

    # ---- bundle_meta.json contract ----
    bundle_meta = _load_json(export_dir / "bundle_meta.json")
    _assert_schema_version(bundle_meta, "1.0")
    _assert_types(
        bundle_meta,
        {
            "schema_version": str,
            "artifacts": list,
        },
    )
    # artifacts list must be stable and complete
    assert bundle_meta["artifacts"] == expected_artifacts

    # ---- operator_gate.json contract ----
    gate = _load_json(export_dir / "operator_gate.json")
    _assert_schema_version(gate, "1.0")
    # NOTE: strict_failure must NOT be present on clean fixture
    _assert_exact_keys(
        gate,
        {
            "operator_version",
            "schema_version",
            "command",
            "exit_code",
            "strict_failed",
            "regression_detected",
            "policy",
            "artifacts",
            "strict_reasons",
            "snapshot",
            "diff",
            "top_actions",
        },
    )
    _assert_types(
        gate,
        {
            "schema_version": str,
            "operator_version": str,
            "command": str,
            "exit_code": int,
            "strict_failed": bool,
            "regression_detected": bool,
            "policy": dict,
            "artifacts": dict,
            "strict_reasons": list,
            "snapshot": dict,
            "diff": dict,
            "top_actions": list,
        },
    )
    assert gate["command"] == "operator_gate"
    assert gate["exit_code"] == 0
    assert gate["strict_failed"] is False
    assert gate["regression_detected"] is False

    # ---- snapshot_diff.json contract ----
    diff = _load_json(export_dir / "snapshot_diff.json")
    _assert_schema_version(diff, "1.0")
    _assert_types(diff, {"schema_version": str, "top_actions": list})
    # drift sentinel: top_actions must always exist (even empty)
    assert isinstance(diff["top_actions"], list)

    # ---- snapshot_latest.json contract ----
    latest = _load_json(export_dir / "snapshot_latest.json")
    _assert_schema_version(latest, "1.0")
    # don't over-pin snapshot payload structure here (it may evolve),
    # but schema_version must bump if it does.

    # ---- report_health.json + graph.json contracts (light pin) ----
    report_health = _load_json(export_dir / "report_health.json")
    _assert_schema_version(report_health, "2.0")
    graph = _load_json(export_dir / "graph.json")
    _assert_schema_version(graph, "1.0")
