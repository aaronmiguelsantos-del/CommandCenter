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


def _write_contract_compliant(tmp: Path, system_id: str) -> None:
    d = tmp / "data" / "contracts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{system_id}-0001.json").write_text(
        json.dumps(
            {
                "contract_id": f"{system_id}-0001",
                "system_id": system_id,
                "name": "t",
                "primitives_used": ["a", "b", "c"],
                "invariants": ["a", "b", "c"],
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


def _write_events_old_many(tmp: Path, system_id: str, n: int) -> None:
    d = tmp / "data" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    lines = [json.dumps({"ts": old, "type": "x", "system_id": system_id}) for _ in range(max(1, int(n)))]
    (d / f"{system_id}-events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    assert payload["policy"]["enforce_sla"] is False
    assert payload["policy"]["strict_blocked_tiers"] == ["prod", "staging"]


def test_report_health_strict_enforce_sla_blocks_when_enabled(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract_compliant(tmp_path, "prod-sys")
    _write_events_old_many(tmp_path, "prod-sys", 8)

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
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    (snaps / "health_history.jsonl").write_text(
        json.dumps({"ts": now, "status": "yellow", "score_total": 72.0, "violations": ["EVENTS_RECENT"]}) + "\n",
        encoding="utf-8",
    )

    rc = app_main(["report", "health", "--strict", "--enforce-sla", "--json"])
    assert rc == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["policy"]["enforce_sla"] is True

    err_payload = json.loads(captured.err.strip().splitlines()[-1])
    assert err_payload["strict_failed"] is True
    assert err_payload["policy"]["enforce_sla"] is True
    assert any(r.get("reason_code") == "SLA_BREACH" for r in err_payload["reasons"])


def test_enforce_sla_blocks_only_when_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract_compliant(tmp_path, "prod-sys")
    # Keep event score high enough that EVENTS_RECENT alone does not force strict red.
    _write_events_old_many(tmp_path, "prod-sys", 8)

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

    r0 = _cmd(tmp_path, "health", "--all", "--strict")
    assert r0 == 0

    r1 = _cmd(tmp_path, "health", "--all", "--strict", "--enforce-sla")
    assert r1 == 2


def test_enforce_sla_never_blocks_samples(tmp_path: Path, monkeypatch) -> None:
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

    r = _cmd(tmp_path, "health", "--all", "--strict", "--enforce-sla", "--include-dev")
    assert r == 0


def test_strict_failure_emits_reason_json_to_stderr(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract_compliant(tmp_path, "prod-sys")
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

    rc = app_main(["health", "--all", "--strict", "--enforce-sla"])
    assert rc == 2

    captured = capsys.readouterr()
    assert captured.err.strip() != ""
    payload = json.loads(captured.err.strip().splitlines()[-1])

    assert payload["strict_failed"] is True
    assert payload["schema_version"] == "1.0"
    assert "policy" in payload and isinstance(payload["policy"], dict)
    assert payload["policy"]["blocked_tiers"] == ["prod"]
    assert payload["policy"]["enforce_sla"] is True

    reasons = payload["reasons"]
    assert isinstance(reasons, list)
    assert any(r.get("system_id") == "prod-sys" for r in reasons)

    for r in reasons:
        assert set(r.keys()) == {"details", "reason_code", "system_id", "tier"}
        assert r["reason_code"] in {"RED_STATUS", "SLA_BREACH"}
        assert isinstance(r["details"], dict)


def test_strict_reason_ordering_is_deterministic(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    _write_contract_compliant(tmp_path, "a-prod")
    _write_events_old(tmp_path, "a-prod")

    _write_contract_compliant(tmp_path, "b-prod")
    _write_events_old(tmp_path, "b-prod")

    _write_registry(
        tmp_path,
        [
            {
                "system_id": "b-prod",
                "contracts_glob": "data/contracts/b-prod-*.json",
                "events_glob": "data/logs/b-prod-events.jsonl",
                "is_sample": False,
                "tier": "prod",
            },
            {
                "system_id": "a-prod",
                "contracts_glob": "data/contracts/a-prod-*.json",
                "events_glob": "data/logs/a-prod-events.jsonl",
                "is_sample": False,
                "tier": "prod",
            },
        ],
    )

    rc = app_main(["health", "--all", "--strict", "--enforce-sla"])
    assert rc == 2

    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    systems = [r["system_id"] for r in payload["reasons"] if r["reason_code"] == "SLA_BREACH"]
    assert systems == sorted(systems)


def test_strict_with_absolute_globs_external_registry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    ext = tmp_path / "ext-fail"
    (ext / "data" / "registry").mkdir(parents=True, exist_ok=True)
    (ext / "data" / "contracts").mkdir(parents=True, exist_ok=True)
    (ext / "data" / "logs").mkdir(parents=True, exist_ok=True)

    # compliant contract
    (ext / "data" / "contracts" / "prod-fail-0001.json").write_text(
        json.dumps(
            {
                "contract_id": "prod-fail-0001",
                "system_id": "prod-fail",
                "name": "Prod failcase contract",
                "primitives_used": ["a", "b", "c"],
                "invariants": ["a", "b", "c"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    _write_events_old_many(ext, "prod-fail", 8)

    reg = ext / "data" / "registry" / "systems.json"
    reg.write_text(
        json.dumps(
            {
                "systems": [
                    {
                        "system_id": "prod-fail",
                        "contracts_glob": str(ext / "data/contracts/prod-fail-*.json"),
                        "events_glob": str(ext / "data/logs/prod-fail-events.jsonl"),
                        "is_sample": False,
                        "tier": "prod",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    r0 = _cmd(tmp_path, "health", "--all", "--strict", "--registry", str(reg))
    assert r0 == 0

    r1 = _cmd(tmp_path, "health", "--all", "--strict", "--enforce-sla", "--registry", str(reg))
    assert r1 == 2


def test_failcase_create_sla_breach_mode_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    target = tmp_path / "codex-kernel-failcase"
    rc = app_main(["failcase", "create", "--path", str(target), "--mode", "sla-breach"])
    assert rc == 0

    reg = target / "data" / "registry" / "systems.json"
    assert reg.exists()

    payload = json.loads(reg.read_text(encoding="utf-8"))
    systems = payload.get("systems", [])
    assert isinstance(systems, list)
    assert systems
    assert systems[0]["system_id"] == "prod-fail"
    assert systems[0]["tier"] == "prod"

    r0 = app_main(["health", "--all", "--strict", "--registry", str(reg)])
    assert r0 == 0

    r1 = app_main(["health", "--all", "--strict", "--enforce-sla", "--registry", str(reg)])
    assert r1 == 2
