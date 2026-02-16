from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.main import main as app_main
from core.bootstrap import bootstrap_repo


def _write_registry_payload(tmp_path: Path, systems: list[dict]) -> None:
    reg_dir = tmp_path / "data" / "registry"
    reg_dir.mkdir(parents=True, exist_ok=True)
    payload = {"systems": systems}
    (reg_dir / "systems.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_registry(tmp_path: Path, system_id: str) -> None:
    _write_registry_payload(
        tmp_path,
        [
            {
                "system_id": system_id,
                "contracts_glob": f"data/contracts/{system_id}-*.json",
                "events_glob": f"data/logs/{system_id}-events.jsonl",
                "is_sample": False,
                "notes": "",
            }
        ],
    )


def _write_contract(
    tmp_path: Path,
    system_id: str,
    primitives_used: list[str] | None = None,
    invariants: list[str] | None = None,
) -> None:
    contracts_dir = tmp_path / "data" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract_id": f"{system_id}-0001",
        "system_id": system_id,
        "name": "System",
        "primitives_used": primitives_used if primitives_used is not None else ["P0", "P1", "P7"],
        "invariants": invariants if invariants is not None else ["INV-001", "INV-002", "INV-003"],
    }
    (contracts_dir / f"{system_id}-0001.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_event(tmp_path: Path, system_id: str, ts: str) -> None:
    logs_dir = tmp_path / "data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "event_id": f"{system_id}-evt-000001",
        "system_id": system_id,
        "event_type": "status_update",
        "ts": ts,
    }
    (logs_dir / f"{system_id}-events.jsonl").write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_valid_system_files(tmp_path: Path, system_id: str) -> None:
    _write_contract(tmp_path, system_id)
    _write_event(tmp_path, system_id, datetime.now(UTC).isoformat().replace("+00:00", "Z"))


def test_validate_ok(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_registry(tmp_path, "sys-ok")
    _write_contract(tmp_path, "sys-ok")
    _write_event(tmp_path, "sys-ok", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    assert app_main(["validate"]) == 0
    out = capsys.readouterr().out
    assert "VALIDATE_OK" in out


def test_validate_fails_on_unparsable_event_ts(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_registry(tmp_path, "sys-bad")
    _write_contract(tmp_path, "sys-bad")
    _write_event(tmp_path, "sys-bad", "not-a-timestamp")

    assert app_main(["validate"]) == 1
    out = capsys.readouterr().out
    assert "EVENT_TS_UNPARSABLE" in out


def test_validate_allows_short_list_fields(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_registry(tmp_path, "sys-min")
    _write_contract(tmp_path, "sys-min", primitives_used=["P0"], invariants=["INV-001"])
    _write_event(tmp_path, "sys-min", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    assert app_main(["validate"]) == 0
    out = capsys.readouterr().out
    assert "VALIDATE_OK" in out


def test_validate_registry_tier_invalid(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    system_id = "sys-tier"
    _write_registry_payload(
        tmp_path,
        [
            {
                "system_id": system_id,
                "contracts_glob": f"data/contracts/{system_id}-*.json",
                "events_glob": f"data/logs/{system_id}-events.jsonl",
                "tier": "production",
            }
        ],
    )
    _write_valid_system_files(tmp_path, system_id)

    assert app_main(["validate"]) == 1
    out = capsys.readouterr().out
    assert "REGISTRY_TIER_INVALID" in out


def test_validate_registry_dependency_invalid_type(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    system_id = "sys-dep-type"
    _write_registry_payload(
        tmp_path,
        [
            {
                "system_id": system_id,
                "contracts_glob": f"data/contracts/{system_id}-*.json",
                "events_glob": f"data/logs/{system_id}-events.jsonl",
                "depends_on": "ops-core",
            }
        ],
    )
    _write_valid_system_files(tmp_path, system_id)

    assert app_main(["validate"]) == 1
    out = capsys.readouterr().out
    assert "REGISTRY_DEPENDENCY_INVALID" in out


def test_validate_registry_dependency_missing_reference(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    system_id = "sys-a"
    _write_registry_payload(
        tmp_path,
        [
            {
                "system_id": system_id,
                "contracts_glob": f"data/contracts/{system_id}-*.json",
                "events_glob": f"data/logs/{system_id}-events.jsonl",
                "depends_on": ["sys-missing"],
            }
        ],
    )
    _write_valid_system_files(tmp_path, system_id)

    assert app_main(["validate"]) == 1
    out = capsys.readouterr().out
    assert "REGISTRY_DEPENDENCY_MISSING" in out


def test_validate_registry_cycle_detected(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_registry_payload(
        tmp_path,
        [
            {
                "system_id": "sys-a",
                "contracts_glob": "data/contracts/sys-a-*.json",
                "events_glob": "data/logs/sys-a-events.jsonl",
                "depends_on": ["sys-b"],
            },
            {
                "system_id": "sys-b",
                "contracts_glob": "data/contracts/sys-b-*.json",
                "events_glob": "data/logs/sys-b-events.jsonl",
                "depends_on": ["sys-a"],
            },
        ],
    )
    _write_valid_system_files(tmp_path, "sys-a")
    _write_valid_system_files(tmp_path, "sys-b")

    assert app_main(["validate"]) == 1
    out = capsys.readouterr().out
    assert "REGISTRY_CYCLE_DETECTED" in out


def test_validate_registry_owners_invalid_type(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    system_id = "sys-owners-type"
    _write_registry_payload(
        tmp_path,
        [
            {
                "system_id": system_id,
                "contracts_glob": f"data/contracts/{system_id}-*.json",
                "events_glob": f"data/logs/{system_id}-events.jsonl",
                "owners": "aaron",
            }
        ],
    )
    _write_valid_system_files(tmp_path, system_id)

    assert app_main(["validate"]) == 1
    out = capsys.readouterr().out
    assert "REGISTRY_OWNERS_INVALID" in out


def test_validate_backward_compat_missing_v2_optional_fields(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    # Backward compatibility: tier/depends_on/owners omitted.
    system_id = "sys-legacy"
    _write_registry_payload(
        tmp_path,
        [
            {
                "system_id": system_id,
                "contracts_glob": f"data/contracts/{system_id}-*.json",
                "events_glob": f"data/logs/{system_id}-events.jsonl",
            }
        ],
    )
    _write_valid_system_files(tmp_path, system_id)

    assert app_main(["validate"]) == 0
    out = capsys.readouterr().out
    assert "VALIDATE_OK" in out
