from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.main import main as app_main
from core.bootstrap import bootstrap_repo


def _write_registry(tmp: Path, systems: list[dict]) -> Path:
    reg = tmp / "data" / "registry"
    reg.mkdir(parents=True, exist_ok=True)
    p = reg / "systems.json"
    p.write_text(json.dumps({"systems": systems}, indent=2), encoding="utf-8")
    return p


def _write_contract(tmp: Path, system_id: str) -> None:
    d = tmp / "data" / "contracts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{system_id}-0001.json").write_text(
        json.dumps(
            {
                "contract_id": f"{system_id}-0001",
                "system_id": system_id,
                "name": "t",
                "primitives_used": ["a", "b"],  # intentionally <3
                "invariants": ["a", "b"],  # intentionally <3
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_events_old(tmp: Path, system_id: str) -> None:
    d = tmp / "data" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    (d / f"{system_id}-events.jsonl").write_text(
        json.dumps({"ts": old, "type": "x"}) + "\n",
        encoding="utf-8",
    )


def _cmd(tmp: Path, *args: str) -> int:
    return app_main(list(args))


def test_staging_red_does_not_block_default_strict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    # staging system is red; default strict should ignore staging.
    _write_contract(tmp_path, "staging-sys")
    _write_events_old(tmp_path, "staging-sys")

    _write_registry(
        tmp_path,
        [
            {
                "system_id": "staging-sys",
                "contracts_glob": "data/contracts/staging-sys-*.json",
                "events_glob": "data/logs/staging-sys-events.jsonl",
                "is_sample": False,
                "tier": "staging",
            }
        ],
    )

    r = _cmd(tmp_path, "health", "--all", "--strict")
    assert r == 0


def test_staging_red_blocks_with_include_staging(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract(tmp_path, "staging-sys")
    _write_events_old(tmp_path, "staging-sys")

    _write_registry(
        tmp_path,
        [
            {
                "system_id": "staging-sys",
                "contracts_glob": "data/contracts/staging-sys-*.json",
                "events_glob": "data/logs/staging-sys-events.jsonl",
                "is_sample": False,
                "tier": "staging",
            }
        ],
    )

    r = _cmd(tmp_path, "health", "--all", "--strict", "--include-staging")
    assert r == 2


def test_dev_red_blocks_only_with_include_dev(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract(tmp_path, "dev-sys")
    _write_events_old(tmp_path, "dev-sys")

    _write_registry(
        tmp_path,
        [
            {
                "system_id": "dev-sys",
                "contracts_glob": "data/contracts/dev-sys-*.json",
                "events_glob": "data/logs/dev-sys-events.jsonl",
                "is_sample": False,
                "tier": "dev",
            }
        ],
    )

    r0 = _cmd(tmp_path, "health", "--all", "--strict")
    assert r0 == 0

    r1 = _cmd(tmp_path, "health", "--all", "--strict", "--include-staging")
    assert r1 == 0

    r2 = _cmd(tmp_path, "health", "--all", "--strict", "--include-dev")
    assert r2 == 2


def test_sample_never_blocks_even_with_include_dev(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract(tmp_path, "demo-sys")
    _write_events_old(tmp_path, "demo-sys")

    _write_registry(
        tmp_path,
        [
            {
                "system_id": "demo-sys",
                "contracts_glob": "data/contracts/demo-sys-*.json",
                "events_glob": "data/logs/demo-sys-events.jsonl",
                "is_sample": True,
                "tier": "prod",
            }
        ],
    )

    r = _cmd(tmp_path, "health", "--all", "--strict", "--include-dev")
    assert r == 0


def test_prod_red_blocks_default_strict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract(tmp_path, "prod-sys")
    _write_events_old(tmp_path, "prod-sys")

    _write_registry(
        tmp_path,
        [
            {
                "system_id": "prod-sys",
                "contracts_glob": "data/contracts/prod-sys-*.json",
                "events_glob": "data/logs/prod-sys-events.jsonl",
                "is_sample": False,
                "tier": "prod",
            }
        ],
    )

    r = _cmd(tmp_path, "health", "--all", "--strict")
    assert r == 2


def test_report_health_policy_reflects_flags(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract(tmp_path, "prod-sys")

    d = tmp_path / "data" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    (d / "prod-sys-events.jsonl").write_text(json.dumps({"ts": now, "type": "x"}) + "\n", encoding="utf-8")

    _write_registry(
        tmp_path,
        [
            {
                "system_id": "prod-sys",
                "contracts_glob": "data/contracts/prod-sys-*.json",
                "events_glob": "data/logs/prod-sys-events.jsonl",
                "is_sample": False,
                "tier": "prod",
            }
        ],
    )

    snaps = tmp_path / "data" / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    (snaps / "health_history.jsonl").write_text(
        json.dumps({"ts": now, "status": "green", "score_total": 88.0, "violations": []}) + "\n",
        encoding="utf-8",
    )

    rc = app_main(["report", "health", "--json", "--include-staging"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["policy"]["include_staging"] is True
    assert payload["policy"]["include_dev"] is False
    assert payload["policy"]["strict_blocked_tiers"] == ["prod", "staging"]
