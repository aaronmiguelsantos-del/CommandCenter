from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """
    Run the CLI as a subprocess so argparse surface is tested.
    """
    cmd = [sys.executable, "-m", "app.main", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_operator_gate_accepts_hide_samples_flag() -> None:
    p = _run(["operator", "gate", "--json", "--hide-samples"])
    # It may return non-zero depending on local ledger state, but it must not be argparse error.
    assert p.returncode in (0, 2, 3, 4)
    assert "unrecognized arguments" not in (p.stderr or "")


def test_operator_gate_json_shape_includes_policy_and_top_actions() -> None:
    p = _run(["operator", "gate", "--json"])
    assert p.returncode in (0, 2, 3, 4)
    payload = json.loads((p.stdout or "").strip() or "{}")
    assert payload.get("command") == "operator_gate"
    assert "exit_code" in payload
    assert "policy" in payload
    assert "top_actions" in payload


def test_operator_gate_export_writes_gate_artifacts(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    p = _run(["operator", "gate", "--json", "--export-path", str(export_dir)])
    assert p.returncode in (0, 2, 3, 4)

    required = {
        "bundle_meta.json",
        "report_health.json",
        "graph.json",
        "snapshot_stats.json",
        "snapshot_tail.json",
        "operator_gate.json",
        "snapshot_diff.json",
        "snapshot_latest.json",
    }
    actual = {p.name for p in export_dir.iterdir() if p.is_file()}
    assert actual == required

    gate_payload = json.loads((export_dir / "operator_gate.json").read_text(encoding="utf-8"))
    assert gate_payload.get("schema_version") == "1.0"
    assert gate_payload.get("command") == "operator_gate"
    assert gate_payload.get("exit_code") in (0, 2, 3, 4)
    policy = gate_payload.get("policy", {})
    assert isinstance(policy, dict)
    for k in ["registry", "hide_samples", "strict", "enforce_sla", "as_of"]:
        assert k in policy

    diff_payload = json.loads((export_dir / "snapshot_diff.json").read_text(encoding="utf-8"))
    assert isinstance(diff_payload.get("top_actions"), list)

    meta = json.loads((export_dir / "bundle_meta.json").read_text(encoding="utf-8"))
    artifacts = meta.get("artifacts", [])
    assert isinstance(artifacts, list)
    assert artifacts == sorted(required)
