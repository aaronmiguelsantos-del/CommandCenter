from __future__ import annotations

import json
from pathlib import Path

from app.main import main as app_main
from core.bootstrap import bootstrap_repo


def test_snapshot_write_replay_as_of_embeds_strict_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    failcase_dir = tmp_path / "failcase"
    rc = app_main(["failcase", "create", "--path", str(failcase_dir), "--mode", "sla-breach"])
    assert rc == 0
    capsys.readouterr()

    registry = failcase_dir / "data" / "registry" / "systems.json"
    assert registry.exists()
    as_of = "2026-02-16T12:00:00Z"

    rc2 = app_main(
        [
            "report",
            "snapshot",
            "--as-of",
            as_of,
            "--strict",
            "--enforce-sla",
            "--write",
            "--json",
            "--registry",
            str(registry),
        ]
    )
    assert rc2 == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["as_of"] == as_of
    assert payload["snapshot"]["as_of"] == as_of

    sf = payload["snapshot"]["strict_failure"]
    assert isinstance(sf, dict)
    assert sf.get("schema_version") == "1.0"
    reason_codes = [str(r.get("reason_code")) for r in sf.get("reasons", []) if isinstance(r, dict)]
    assert reason_codes == ["SLA_BREACH"]

    ledger = tmp_path / "data" / "snapshots" / "report_snapshot_history.jsonl"
    lines = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines
    row = json.loads(lines[-1])

    assert row["as_of"] == as_of
    sf_row = row.get("strict_failure")
    assert isinstance(sf_row, dict)
    assert sf_row.get("schema_version") == "1.0"
    reason_codes_row = [str(r.get("reason_code")) for r in sf_row.get("reasons", []) if isinstance(r, dict)]
    assert reason_codes_row == ["SLA_BREACH"]
