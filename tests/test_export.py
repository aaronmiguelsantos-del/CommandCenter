from __future__ import annotations

import json
from pathlib import Path

from app.main import main as app_main
from core.bootstrap import bootstrap_repo


def test_report_export_writes_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    out_dir = tmp_path / "bundle"
    failcase_dir = tmp_path / "fc"

    rc = app_main(["failcase", "create", "--path", str(failcase_dir), "--mode", "sla-breach"])
    assert rc == 0
    reg = failcase_dir / "data" / "registry" / "systems.json"
    assert reg.exists()

    rc2 = app_main(
        [
            "report",
            "export",
            "--out",
            str(out_dir),
            "--registry",
            str(reg),
            "--strict",
            "--enforce-sla",
            "--ledger",
            str(failcase_dir / "data" / "snapshots" / "report_snapshot_history.jsonl"),
            "--n-tail",
            "5",
        ]
    )
    assert rc2 == 0

    health = json.loads((out_dir / "report_health.json").read_text(encoding="utf-8"))
    assert health.get("report_version") == "2.0"
    assert "strict_failure" in health
    sf = health.get("strict_failure")
    assert sf is None or isinstance(sf, dict)

    assert (out_dir / "graph.json").exists()
    assert (out_dir / "snapshot_stats.json").exists()
    assert (out_dir / "snapshot_tail.json").exists()
    assert (out_dir / "bundle_meta.json").exists()
