from __future__ import annotations

import json
from pathlib import Path

from app.main import main as app_main
from core.bootstrap import bootstrap_repo


def _mark_sample(tmp_path: Path, system_id: str) -> None:
    reg_path = tmp_path / "data" / "registry" / "systems.json"
    payload = json.loads(reg_path.read_text(encoding="utf-8"))
    rows = payload["systems"] if isinstance(payload, dict) else payload
    for row in rows:
        if row.get("system_id") == system_id:
            row["is_sample"] = True
    if isinstance(payload, dict):
        payload["systems"] = rows
    reg_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_health_all_json_hide_samples_excludes_sample_systems(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    assert app_main(["system", "add", "prod-sys", "Prod System"]) == 0
    assert app_main(["system", "add", "sample-sys", "Sample System"]) == 0
    _mark_sample(tmp_path, "sample-sys")

    capsys.readouterr()
    assert app_main(["health", "--all", "--json"]) == 0
    baseline = json.loads(capsys.readouterr().out)
    baseline_ids = sorted(row["system_id"] for row in baseline["systems"])
    assert "sample-sys" in baseline_ids

    assert app_main(["health", "--all", "--json", "--hide-samples"]) == 0
    payload = json.loads(capsys.readouterr().out)
    ids = sorted(row["system_id"] for row in payload["systems"])
    assert "prod-sys" in ids
    assert "sample-sys" not in ids


def test_health_all_table_hide_samples_excludes_sample_row(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    assert app_main(["system", "add", "prod-sys", "Prod System"]) == 0
    assert app_main(["system", "add", "sample-sys", "Sample System"]) == 0
    _mark_sample(tmp_path, "sample-sys")

    capsys.readouterr()
    assert app_main(["health", "--all", "--hide-samples"]) == 0
    out = capsys.readouterr().out
    assert "prod-sys" in out
    assert "sample-sys" not in out
