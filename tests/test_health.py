from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.main import main as app_main
from core.bootstrap import bootstrap_repo
from core.health import _status_for, compute_and_write_health, compute_health_for_system
from core.registry import load_registry, upsert_system
from core.storage import append_event


def _write_contract(tmp_path: Path, system_id: str, primitives_used, invariants) -> None:
    contracts_dir = tmp_path / "data" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract_id": f"{system_id}-0001",
        "system_id": system_id,
        "name": f"{system_id} contract",
        "primitives_used": primitives_used,
        "invariants": invariants,
    }
    (contracts_dir / f"{system_id}-0001.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_event(tmp_path: Path, system_id: str, ts: str) -> None:
    logs_dir = tmp_path / "data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "event_id": f"{system_id}-evt-000001",
        "system_id": system_id,
        "event_type": "status_update",
        "ts": ts,
    }
    (logs_dir / "events.jsonl").write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")


def _latest(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "data" / "snapshots" / "health_latest.json").read_text(encoding="utf-8"))


def test_health_snapshot_smoke(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()
    payload, snapshot_files = compute_and_write_health()
    latest = _latest(tmp_path)

    assert payload == latest
    assert snapshot_files == payload["snapshot_files"]
    assert set(latest.keys()) == {
        "ts",
        "status",
        "score_total",
        "violations",
        "counts",
        "scores",
        "per_system",
        "snapshot_files",
    }
    assert "health" not in latest
    assert isinstance(latest["status"], str)
    assert isinstance(latest["violations"], list)
    assert isinstance(latest["per_system"], list)
    assert isinstance(latest["score_total"], (int, float))


def test_violation_primitives_min(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()
    _write_contract(tmp_path, "sys-primitives", primitives_used=["P0", "P1"], invariants=["I1", "I2", "I3"])
    _write_event(tmp_path, "sys-primitives", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    latest, _ = compute_and_write_health()

    assert "PRIMITIVES_MIN" in latest["violations"]
    assert latest["status"] == "red"


def test_violation_invariants_min(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()
    _write_contract(tmp_path, "sys-invariants", primitives_used=["P0", "P1", "P7"], invariants=["I1", "I2"])
    _write_event(tmp_path, "sys-invariants", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    latest, _ = compute_and_write_health()

    assert "INVARIANTS_MIN" in latest["violations"]
    assert latest["status"] == "red"


def test_violation_events_recent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()
    _write_contract(
        tmp_path,
        "sys-events",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    old_ts = (datetime.now(UTC) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    _write_event(tmp_path, "sys-events", old_ts)

    latest, _ = compute_and_write_health()

    assert "EVENTS_RECENT" in latest["violations"]
    assert latest["status"] == "red"


def test_list_fields_regression_no_min_violations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()
    _write_contract(
        tmp_path,
        "sys-lists",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    _write_event(tmp_path, "sys-lists", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    latest, _ = compute_and_write_health()

    assert "PRIMITIVES_MIN" not in latest["violations"]
    assert "INVARIANTS_MIN" not in latest["violations"]
    assert latest["status"] in {"green", "yellow"}


def test_load_registry_supports_list_and_object_formats(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    reg_dir = tmp_path / "data" / "registry"
    reg_dir.mkdir(parents=True, exist_ok=True)

    list_payload = [
        {
            "system_id": "list-sys",
            "contracts_glob": "data/contracts/list-sys-*.json",
            "events_glob": "data/logs/list-sys-events.jsonl",
        }
    ]
    (reg_dir / "systems.json").write_text(json.dumps(list_payload), encoding="utf-8")
    specs_list = load_registry()
    assert len(specs_list) == 1
    assert specs_list[0].system_id == "list-sys"

    object_payload = {
        "systems": [
            {
                "system_id": "obj-sys",
                "contracts_glob": "data/contracts/obj-sys-*.json",
                "events_glob": "data/logs/obj-sys-events.jsonl",
            }
        ]
    }
    (reg_dir / "systems.json").write_text(json.dumps(object_payload), encoding="utf-8")
    specs_obj = load_registry()
    assert len(specs_obj) == 1
    assert specs_obj[0].system_id == "obj-sys"


def test_upsert_updates_existing_row_when_globs_change(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    reg_dir = tmp_path / "data" / "registry"
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "systems.json").write_text(
        json.dumps(
            {
                "systems": [
                    {
                        "system_id": "atlas-core",
                        "contracts_glob": "data/contracts/atlas-core-*.json",
                        "events_glob": "data/logs/atlas-core-*.jsonl",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = upsert_system(
        "atlas-core",
        "data/contracts/atlas-core-*.json",
        "data/logs/atlas-core-events.jsonl",
    )
    assert changed is True

    changed_again = upsert_system(
        "atlas-core",
        "data/contracts/atlas-core-*.json",
        "data/logs/atlas-core-events.jsonl",
    )
    assert changed_again is False

    payload = json.loads((reg_dir / "systems.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "systems" in payload
    assert payload["systems"][0]["events_glob"] == "data/logs/atlas-core-events.jsonl"


def test_compute_health_for_system_from_glob(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    contracts_dir = tmp_path / "data" / "contracts"
    logs_dir = tmp_path / "data" / "logs"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    contract = {
        "contract_id": "atlas-core-0001",
        "system_id": "atlas-core",
        "name": "Atlas",
        "primitives_used": ["P0", "P1", "P7"],
        "invariants": ["INV-001", "INV-002", "INV-003"],
    }
    (contracts_dir / "atlas-core-0001.json").write_text(json.dumps(contract), encoding="utf-8")

    event_row = {
        "event_id": "atlas-core-evt-000001",
        "event_type": "status_update",
        # intentionally missing ts to verify fallback fill for glob reads
    }
    (logs_dir / "atlas-core-events.jsonl").write_text(json.dumps(event_row) + "\n", encoding="utf-8")

    payload = compute_health_for_system(
        "atlas-core",
        "data/contracts/atlas-core-*.json",
        "data/logs/atlas-core-events.jsonl",
    )

    assert payload["status"] in {"green", "yellow"}
    assert payload["counts"]["contracts"] == 1
    assert payload["counts"]["events"] == 1
    assert "snapshot_files" not in payload


def test_append_event_writes_system_log_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    payload = append_event("atlas-core", "status_update")

    target = tmp_path / "data" / "logs" / "atlas-core-events.jsonl"
    assert target.exists()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["system_id"] == "atlas-core"
    assert row["event_type"] == "status_update"
    assert payload["system_id"] == "atlas-core"


def test_system_add_idempotent_no_duplicate_registry(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    assert app_main(["system", "add", "sys-a", "System A"]) == 0
    assert app_main(["system", "add", "sys-a", "System A"]) == 0

    registry_path = tmp_path / "data" / "registry" / "systems.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    rows = payload["systems"] if isinstance(payload, dict) else payload
    system_rows = [r for r in rows if r.get("system_id") == "sys-a"]
    assert len(system_rows) == 1

    contracts = sorted((tmp_path / "data" / "contracts").glob("sys-a-*.json"))
    assert len(contracts) == 1

    out = capsys.readouterr().out
    assert "already exists" in out


def test_system_list_runs(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    assert app_main(["system", "add", "sys-b", "System B"]) == 0
    assert app_main(["system", "list"]) == 0

    out = capsys.readouterr().out
    assert "system_id | status | score_total | violations" in out
    assert "sys-b" in out


def test_health_all_json_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    assert app_main(["system", "add", "json-sys", "Json System"]) == 0
    capsys.readouterr()
    assert app_main(["health", "--all", "--json"]) == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "systems" in payload
    assert isinstance(payload["systems"], list)


def test_emit_health_snapshot_keeps_violations_list(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    # seed valid contract + recent event so violations are empty list
    _write_contract(
        tmp_path,
        "ok-sys",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    append_event("ok-sys", "status_update")

    assert app_main(["health"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["violations"] == []
    assert payload["violations_display"] == "none"


def test_health_all_strict_fails_when_non_sample_red(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    # Non-sample system missing required fields -> red.
    _write_contract(tmp_path, "bad-sys", primitives_used=["P0"], invariants=["INV-001"])
    append_event("bad-sys", "status_update")
    assert app_main(["system", "add", "bad-sys", "Bad System"]) == 0

    assert app_main(["health", "--all", "--strict"]) == 2


def test_health_all_strict_passes_when_only_sample_red(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    # Good non-sample system.
    _write_contract(
        tmp_path,
        "good-sys",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    append_event("good-sys", "status_update")
    assert app_main(["system", "add", "good-sys", "Good System"]) == 0

    # Red sample system.
    _write_contract(tmp_path, "sample-sys", primitives_used=["P0"], invariants=["INV-001"])
    append_event("sample-sys", "status_update")
    assert app_main(["system", "add", "sample-sys", "Sample System"]) == 0

    # Mark sample-sys as sample in registry.
    reg_path = tmp_path / "data" / "registry" / "systems.json"
    payload = json.loads(reg_path.read_text(encoding="utf-8"))
    rows = payload["systems"] if isinstance(payload, dict) else payload
    for row in rows:
        if row.get("system_id") == "sample-sys":
            row["is_sample"] = True
            row["notes"] = "sample red system"
    if isinstance(payload, dict):
        payload["systems"] = rows
    reg_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    assert app_main(["health", "--all", "--strict"]) == 0


def test_status_uses_payload_violations_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract(tmp_path, "status-sys", primitives_used=["P0"], invariants=["INV-001"])
    _write_event(tmp_path, "status-sys", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    payload, _ = compute_and_write_health()

    expected = _status_for(float(payload["score_total"]), list(payload["violations"]))
    assert payload["status"] == expected
