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
    rows = []
    for i, ts in enumerate(ts_list, start=1):
        rows.append(
            {
                "event_id": f"{system_id}-evt-{i:04d}",
                "event_type": "status_update",
                "system_id": system_id,
                "ts": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
    p.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")


def test_operator_gate_clean_repo_exits_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    rc = app_main(["operator", "gate", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 0
    assert payload["strict_failed"] is False
    assert payload["regression_detected"] is False


def test_operator_gate_failcase_sla_breach_exits_two(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    failcase_dir = tmp_path / "fc"
    rc = app_main(["failcase", "create", "--path", str(failcase_dir), "--mode", "sla-breach"])
    assert rc == 0
    capsys.readouterr()

    registry = failcase_dir / "data" / "registry" / "systems.json"
    rc2 = app_main(
        [
            "operator",
            "gate",
            "--json",
            "--registry",
            str(registry),
            "--enforce-sla",
        ]
    )
    assert rc2 == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["strict_failed"] is True
    assert payload["regression_detected"] is False
    assert payload["exit_code"] == 2


def test_operator_gate_detects_regression_exits_three(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    system_id = "ops-core"
    _write_contract(tmp_path, system_id)
    reg = _write_registry(
        tmp_path,
        [
            {
                "system_id": system_id,
                "contracts_glob": f"data/contracts/{system_id}-*.json",
                "events_glob": f"data/logs/{system_id}-events.jsonl",
                "is_sample": False,
                "tier": "staging",
            }
        ],
    )

    now = datetime.now(timezone.utc)
    _write_events(tmp_path, system_id, [now - timedelta(minutes=5 * i) for i in range(4)])

    rc0 = app_main(
        [
            "operator",
            "gate",
            "--json",
            "--registry",
            str(reg),
        ]
    )
    assert rc0 == 0
    capsys.readouterr()

    # Regress staging system to red. Default strict policy blocks prod only, so strict stays passing.
    contracts = tmp_path / "data" / "contracts" / f"{system_id}-0001.json"
    contracts.write_text(
        json.dumps(
            {
                "contract_id": f"{system_id}-0001",
                "system_id": system_id,
                "name": "x",
                "primitives_used": ["a"],
                "invariants": ["i1"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    rc1 = app_main(
        [
            "operator",
            "gate",
            "--json",
            "--registry",
            str(reg),
        ]
    )
    assert rc1 == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["strict_failed"] is False
    assert payload["regression_detected"] is True
    assert payload["exit_code"] == 3
    diff = payload["diff"] if isinstance(payload.get("diff"), dict) else {}
    actions = diff.get("top_actions", [])
    assert any(isinstance(a, dict) and a.get("type") == "STATUS_REGRESSION" for a in actions)
