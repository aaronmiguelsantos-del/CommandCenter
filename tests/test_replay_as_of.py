from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.main import main as app_main
from core.bootstrap import bootstrap_repo
from core.timeutil import iso_utc


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
                "name": "x",
                "primitives_used": ["a", "b", "c"],
                "invariants": ["i1", "i2", "i3"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_events(tmp: Path, system_id: str, ts_list: list[datetime]) -> None:
    d = tmp / "data" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{system_id}-events.jsonl"
    lines = []
    for ts in ts_list:
        lines.append(json.dumps({"ts": iso_utc(ts), "type": "heartbeat", "system_id": system_id}))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_replay_as_of_ignores_future_events(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    now = datetime.now(timezone.utc)
    past = now - timedelta(days=10)
    future = now + timedelta(days=10)

    _write_contract(tmp_path, "x")
    _write_events(tmp_path, "x", [past, future])

    reg = _write_registry(
        tmp_path,
        [
            {
                "system_id": "x",
                "contracts_glob": "data/contracts/x-*.json",
                "events_glob": "data/logs/x-events.jsonl",
                "is_sample": False,
                "tier": "prod",
            }
        ],
    )

    rc = app_main(["health", "--all", "--json", "--registry", str(reg), "--as-of", iso_utc(now)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    systems = payload["systems"]
    assert len(systems) == 1
    assert systems[0]["counts"]["events"] == 1


def test_report_health_as_of_embeds_as_of(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    now = datetime.now(timezone.utc)
    past = now - timedelta(days=30)

    _write_contract(tmp_path, "x")
    _write_events(tmp_path, "x", [past])

    reg = _write_registry(
        tmp_path,
        [
            {
                "system_id": "x",
                "contracts_glob": "data/contracts/x-*.json",
                "events_glob": "data/logs/x-events.jsonl",
                "is_sample": False,
                "tier": "prod",
            }
        ],
    )

    snaps = tmp_path / "data" / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    (snaps / "health_history.jsonl").write_text(
        json.dumps({"ts": iso_utc(now), "status": "green", "score_total": 88.0, "violations": []}) + "\n",
        encoding="utf-8",
    )

    rc = app_main(["report", "health", "--json", "--registry", str(reg), "--as-of", iso_utc(now)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["as_of"] == iso_utc(now)
