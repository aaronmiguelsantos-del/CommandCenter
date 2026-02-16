from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from app.main import main as app_main
import core.reporting as reporting
from core.bootstrap import bootstrap_repo
from core.registry import upsert_system
from core.reporting import build_drift_hint, compute_report
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
    (contracts_dir / f"{system_id}-0001.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _mark_sample(tmp_path: Path, system_id: str, is_sample: bool) -> None:
    reg_path = tmp_path / "data" / "registry" / "systems.json"
    payload = json.loads(reg_path.read_text(encoding="utf-8"))
    rows = payload["systems"] if isinstance(payload, dict) else payload
    for row in rows:
        if row.get("system_id") == system_id:
            row["is_sample"] = is_sample
    if isinstance(payload, dict):
        payload["systems"] = rows
    reg_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(tmp_path: Path, rows: list[dict]) -> None:
    path = tmp_path / "data" / "snapshots" / "health_history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def test_compute_report_delta_frequency_and_strict_ready(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    upsert_system("good-sys", "data/contracts/good-sys-*.json", "data/logs/good-sys-events.jsonl")
    upsert_system("sample-red", "data/contracts/sample-red-*.json", "data/logs/sample-red-events.jsonl")
    _mark_sample(tmp_path, "sample-red", True)

    _write_contract(
        tmp_path,
        "good-sys",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    _write_contract(tmp_path, "sample-red", primitives_used=["P0"], invariants=["INV-001"])
    append_event("good-sys", "status_update")
    append_event("sample-red", "status_update")

    now = datetime.now(UTC)
    _write_history(
        tmp_path,
        [
            {
                "ts": (now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                "status": "yellow",
                "score_total": 80.0,
                "violations": ["PRIMITIVES_MIN"],
            },
            {
                "ts": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                "status": "yellow",
                "score_total": 85.0,
                "violations": ["PRIMITIVES_MIN", "INVARIANTS_MIN"],
            },
            {
                "ts": now.isoformat().replace("+00:00", "Z"),
                "status": "red",
                "score_total": 90.0,
                "violations": ["PRIMITIVES_MIN"],
            },
        ],
    )

    report = compute_report(days=30, tail=2000, strict=True)

    assert report["report_version"] == "2.0"
    assert report["summary"]["snapshots_analyzed"] == 3
    assert report["summary"]["strict_ready_now"] is True
    assert report["summary"]["now_non_sample"]["status"] == "green"
    assert report["summary"]["now_non_sample"]["strict_ready_now"] is True
    assert report["summary"]["current_status"] == "red"
    assert report["trend"]["score_total"]["start_score"] == 80.0
    assert report["trend"]["score_total"]["end_score"] == 90.0
    assert report["trend"]["score_total"]["delta"] == 10.0
    assert report["trend"]["rolling_avg_score"] == 85.0

    top = {row["code"]: row["count"] for row in report["violations"]["top"]}
    assert top["PRIMITIVES_MIN"] == 3
    assert top["INVARIANTS_MIN"] == 1


def test_hints_high_for_non_sample_red_violations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    upsert_system("bad-sys", "data/contracts/bad-sys-*.json", "data/logs/bad-sys-events.jsonl")
    _write_contract(tmp_path, "bad-sys", primitives_used=["P0"], invariants=["INV-001"])
    append_event("bad-sys", "status_update")

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_history(tmp_path, [{"ts": now, "status": "red", "score_total": 40.0, "violations": ["PRIMITIVES_MIN"]}])

    report = compute_report(days=30, tail=2000, strict=True)

    assert report["summary"]["hints_count"] >= 1
    hints = report["hints"]
    assert all(h["severity"] == "high" for h in hints)
    titles = {h["title"] for h in hints}
    assert "System contract missing minimum primitives" in titles
    assert "System contract missing minimum invariants" in titles
    systems = sorted({sid for h in hints for sid in h["systems"]})
    assert systems == ["bad-sys"]


def test_hints_low_when_only_sample_red_and_global_red(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    upsert_system("good-sys", "data/contracts/good-sys-*.json", "data/logs/good-sys-events.jsonl")
    upsert_system("sample-red", "data/contracts/sample-red-*.json", "data/logs/sample-red-events.jsonl")
    _mark_sample(tmp_path, "sample-red", True)

    _write_contract(
        tmp_path,
        "good-sys",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    _write_contract(tmp_path, "sample-red", primitives_used=["P0"], invariants=["INV-001"])
    append_event("good-sys", "status_update")
    append_event("sample-red", "status_update")

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_history(tmp_path, [{"ts": now, "status": "red", "score_total": 50.0, "violations": ["PRIMITIVES_MIN"]}])

    report = compute_report(days=30, tail=2000, strict=True)

    assert report["summary"]["now_non_sample"]["status"] == "green"
    assert report["summary"]["strict_ready_now"] is True
    assert report["summary"]["current_status"] == "red"
    assert report["hints"][0]["severity"] == "low"
    assert report["hints"][0]["title"] == "Global snapshot is red, strict is passing"


def test_report_health_json_command_outputs_sections(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    upsert_system("json-sys", "data/contracts/json-sys-*.json", "data/logs/json-sys-events.jsonl")
    _write_contract(
        tmp_path,
        "json-sys",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    append_event("json-sys", "status_update")

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_history(tmp_path, [{"ts": now, "status": "green", "score_total": 88.0, "violations": []}])

    assert app_main(["report", "health", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert set(payload.keys()) == {"report_version", "summary", "trend", "violations", "systems", "impact", "hints", "policy"}
    assert payload["report_version"] == "2.0"
    assert "now_non_sample" in payload["summary"]
    assert "hints_count" in payload["summary"]
    assert isinstance(payload["systems"]["status"], list)
    assert isinstance(payload["systems"]["recency"], list)


def test_report_no_hints_flag_disables_hints_json_and_text(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    upsert_system("json-sys", "data/contracts/json-sys-*.json", "data/logs/json-sys-events.jsonl")
    _write_contract(
        tmp_path,
        "json-sys",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    append_event("json-sys", "status_update")

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_history(tmp_path, [{"ts": now, "status": "green", "score_total": 88.0, "violations": []}])

    assert app_main(["report", "health", "--no-hints"]) == 0
    out_text = capsys.readouterr().out
    assert "ACTION HINTS" not in out_text

    assert app_main(["report", "health", "--json", "--no-hints"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["hints_count"] == 0
    assert payload["hints"] == []


def test_report_health_missing_history_exits_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    assert app_main(["report", "health"]) == 0
    out = capsys.readouterr().out
    assert "No health history found" in out


def test_report_health_strict_fails_for_non_sample_red(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    upsert_system("bad-sys", "data/contracts/bad-sys-*.json", "data/logs/bad-sys-events.jsonl")
    _write_contract(tmp_path, "bad-sys", primitives_used=["P0"], invariants=["INV-001"])
    append_event("bad-sys", "status_update")

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_history(tmp_path, [{"ts": now, "status": "yellow", "score_total": 75.0, "violations": []}])

    assert app_main(["report", "health", "--strict"]) == 2


def test_drift_hint_none_if_insufficient_history() -> None:
    now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
    hint = build_drift_hint(points=[], rolling_avg=None, now_utc=now)
    assert hint is None


def test_drift_hint_med_if_drop_gt_10() -> None:
    now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
    points = [
        {"ts": "2026-02-13T11:59:00Z", "score": 90},
        {"ts": "2026-02-14T12:00:00Z", "score": 79},
    ]
    hint = build_drift_hint(points=points, rolling_avg=85.0, now_utc=now)
    assert hint is not None
    assert hint["severity"] == "med"


def test_drift_hint_high_if_drop_gt_20() -> None:
    now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
    points = [
        {"ts": "2026-02-13T12:00:00Z", "score": 95},
        {"ts": "2026-02-14T12:00:00Z", "score": 70},
    ]
    hint = build_drift_hint(points=points, rolling_avg=None, now_utc=now)
    assert hint is not None
    assert hint["severity"] == "high"


def test_compute_report_includes_drift_hint_in_full_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    upsert_system("good-sys", "data/contracts/good-sys-*.json", "data/logs/good-sys-events.jsonl")
    _write_contract(
        tmp_path,
        "good-sys",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    append_event("good-sys", "status_update")

    now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(reporting, "_now_utc", lambda: now)

    _write_history(
        tmp_path,
        [
            {"ts": "2026-02-13T11:59:00Z", "status": "green", "score_total": 95.0, "violations": []},
            {"ts": "2026-02-14T12:00:00Z", "status": "green", "score_total": 70.0, "violations": []},
        ],
    )

    report = compute_report(days=30, tail=2000, strict=False)

    titles = {h["title"] for h in report["hints"]}
    assert "Health drift detected" in titles
    assert report["summary"]["hints_count"] == len(report["hints"])


def test_text_report_includes_drift_line(monkeypatch) -> None:
    from datetime import datetime, timezone
    import core.reporting as r

    monkeypatch.setattr(r, "_now_utc", lambda: datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc))

    report = {
        "trend": {
            "points": [
                {"ts": "2026-02-13T12:00:00Z", "score": 95},
                {"ts": "2026-02-14T12:00:00Z", "score": 70},
            ],
            "rolling_avg": 85.0,
        }
    }

    text = r.render_report_health_text(report)
    assert "Drift (24h): -25" in text
    assert "Rolling avg: 85.0" in text


def test_drift_contributors_uses_cache_for_duplicate_rows(monkeypatch) -> None:
    import core.reporting as r

    now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
    calls: list[tuple[str, str]] = []

    def fake_compute_health_for_system(system_id: str, contracts_glob: str, events_glob: str, *, as_of=None):
        assert as_of is not None
        stamp = as_of.astimezone(timezone.utc).isoformat()
        calls.append((system_id, stamp))
        # Older snapshot should score higher to create drop.
        score = 90.0 if as_of < now else 70.0
        return {"score_total": score}

    monkeypatch.setattr(r, "compute_health_for_system", fake_compute_health_for_system)

    systems = [
        {
            "system_id": "dup-sys",
            "contracts_glob": "data/contracts/dup-sys-*.json",
            "events_glob": "data/logs/dup-sys-events.jsonl",
            "is_sample": False,
        },
        {
            "system_id": "dup-sys",
            "contracts_glob": "data/contracts/dup-sys-*.json",
            "events_glob": "data/logs/dup-sys-events.jsonl",
            "is_sample": False,
        },
    ]

    drops = r._drift_contributors(systems, now_utc=now)

    assert drops == [("dup-sys", 20), ("dup-sys", 20)]
    # cache ensures one call per unique as_of key (now, now-24h) despite duplicate system rows
    assert len(calls) == 2


def test_sample_systems_never_appear_in_drift_attribution(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    upsert_system("good-sys", "data/contracts/good-sys-*.json", "data/logs/good-sys-events.jsonl")
    upsert_system("sample-red", "data/contracts/sample-red-*.json", "data/logs/sample-red-events.jsonl")
    _mark_sample(tmp_path, "sample-red", True)

    _write_contract(
        tmp_path,
        "good-sys",
        primitives_used=["P0", "P1", "P7"],
        invariants=["INV-001", "INV-002", "INV-003"],
    )
    _write_contract(tmp_path, "sample-red", primitives_used=["P0"], invariants=["INV-001"])
    append_event("good-sys", "status_update")
    append_event("sample-red", "status_update")

    now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(reporting, "_now_utc", lambda: now)

    # Force aggregate drift hint from history, but contributor attribution must stay non-sample only.
    _write_history(
        tmp_path,
        [
            {"ts": "2026-02-13T12:00:00Z", "status": "yellow", "score_total": 95.0, "violations": []},
            {"ts": "2026-02-14T12:00:00Z", "status": "yellow", "score_total": 70.0, "violations": []},
        ],
    )

    report = compute_report(days=30, tail=2000, strict=False)

    # sample system must not appear in drift hint systems
    for hint in report.get("hints", []):
        if hint.get("title") == "Health drift detected":
            assert "sample-red" not in (hint.get("systems") or [])

    # sample system must not appear in top_drift_24h summary line
    top = report.get("summary", {}).get("top_drift_24h")
    if top:
        assert "sample-red" not in top


def test_report_json_includes_version() -> None:
    report = compute_report()

    assert "report_version" in report
    assert report["report_version"] == "2.0"


def test_report_json_includes_impact_block() -> None:
    report = compute_report()

    assert "impact" in report
    assert "sources" in report["impact"]
    assert "impacted" in report["impact"]
    assert isinstance(report["impact"]["sources"], list)
    assert isinstance(report["impact"]["impacted"], list)


def test_select_impact_sources_excludes_samples_and_includes_drift() -> None:
    from core.reporting import _select_impact_sources

    current = [
        {"system_id": "demo-sys", "status": "red", "is_sample": True},
        {"system_id": "ops-core", "status": "yellow", "is_sample": False},
        {"system_id": "atlas-core", "status": "green", "is_sample": False},
    ]
    sources = _select_impact_sources(current_systems=current, drift_sources=["atlas-core"])

    assert sources == ["atlas-core", "ops-core"]


def test_drift_hint_includes_impacted_suffix_when_graph_has_dependents(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    bootstrap_repo()

    upsert_system("ops-core", "data/contracts/ops-core-*.json", "data/logs/ops-core-events.jsonl")
    upsert_system("atlas-core", "data/contracts/atlas-core-*.json", "data/logs/atlas-core-events.jsonl")

    # Add dependency: atlas-core depends on ops-core
    reg_path = tmp_path / "data" / "registry" / "systems.json"
    payload = json.loads(reg_path.read_text(encoding="utf-8"))
    rows = payload["systems"] if isinstance(payload, dict) else payload
    for row in rows:
        if row.get("system_id") == "atlas-core":
            row["depends_on"] = ["ops-core"]
    if isinstance(payload, dict):
        payload["systems"] = rows
    reg_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # Use fixed now and history to force aggregate drift.
    now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(reporting, "_now_utc", lambda: now)
    _write_history(
        tmp_path,
        [
            {"ts": "2026-02-13T12:00:00Z", "status": "yellow", "score_total": 95.0, "violations": []},
            {"ts": "2026-02-14T12:00:00Z", "status": "yellow", "score_total": 70.0, "violations": []},
        ],
    )

    # Force deterministic contributor attribution to ops-core.
    def fake_compute_health_for_system(system_id: str, contracts_glob: str, events_glob: str, *, as_of=None):
        if as_of is None:
            return {"status": "green", "score_total": 90.0, "violations": []}
        if system_id == "ops-core":
            return {"score_total": 95.0 if as_of < now else 70.0, "status": "green", "violations": []}
        return {"score_total": 70.0, "status": "green", "violations": []}

    monkeypatch.setattr(reporting, "compute_health_for_system", fake_compute_health_for_system)

    report = compute_report(days=30, tail=2000, strict=False)

    drift_hints = [h for h in report.get("hints", []) if "drift" in str(h.get("title", "")).lower()]
    assert drift_hints, "expected drift hint"
    why = str(drift_hints[0].get("why", ""))
    assert "Impacted:" in why


def test_report_json_includes_policy_block() -> None:
    report = compute_report()

    assert report["report_version"] == "2.0"
    assert "policy" in report
    p = report["policy"]
    assert set(p.keys()) == {"strict_blocked_tiers", "include_staging", "include_dev"}
    assert isinstance(p["strict_blocked_tiers"], list)
    assert isinstance(p["include_staging"], bool)
    assert isinstance(p["include_dev"], bool)
