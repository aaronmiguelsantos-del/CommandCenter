from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.snapshot_diff import render_snapshot_diff_pretty, snapshot_diff_from_ledger


def _write_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")


def _snapshot_row(
    *,
    ts: str,
    as_of: str | None,
    systems: list[dict],
    ranked: list[str],
    strict_failure: dict | None,
) -> dict:
    return {
        "ts": ts,
        "as_of": as_of,
        "snapshot": {
            "ts": ts,
            "as_of": as_of,
            "systems": systems,
            "risk": {"ranked": [{"system_id": sid} for sid in ranked]},
            "strict_failure": strict_failure,
        },
    }


def test_snapshot_diff_top_actions_have_deterministic_priority_order(tmp_path: Path) -> None:
    ledger = tmp_path / "data" / "snapshots" / "report_snapshot_history.jsonl"
    a = _snapshot_row(
        ts="2026-02-16T12:00:00Z",
        as_of="2026-02-16T12:00:00Z",
        systems=[
            {"system_id": "alpha", "status": "green", "violations": []},
            {"system_id": "beta", "status": "green", "violations": []},
            {"system_id": "gamma", "status": "green", "violations": []},
        ],
        ranked=["alpha", "beta", "gamma"],
        strict_failure=None,
    )
    b = _snapshot_row(
        ts="2026-02-16T13:00:00Z",
        as_of="2026-02-16T13:00:00Z",
        systems=[
            {"system_id": "alpha", "status": "yellow", "violations": []},
            {"system_id": "beta", "status": "green", "violations": []},
            {"system_id": "gamma", "status": "green", "violations": ["PRIMITIVES_MIN"]},
        ],
        ranked=["beta", "alpha", "gamma"],
        strict_failure={
            "schema_version": "1.0",
            "strict_failed": True,
            "policy": {"blocked_tiers": ["prod"], "include_staging": False, "include_dev": False, "enforce_sla": True},
            "reasons": [{"system_id": "prod-fail", "tier": "prod", "reason_code": "SLA_BREACH"}],
        },
    )
    _write_ledger(ledger, [a, b])

    out = snapshot_diff_from_ledger(ledger, a="prev", b="latest", tail=100)
    diff = out["diff"]
    actions = diff["top_actions"]
    assert [x["priority"] for x in actions] == [1, 2, 3, 4]
    assert [x["type"] for x in actions] == [
        "STRICT_REGRESSION",
        "STATUS_REGRESSION",
        "RISK_RANK_INCREASE",
        "NEW_HIGH_VIOLATION",
    ]
    assert [x["system_id"] for x in actions] == ["prod-fail", "alpha", "beta", "gamma"]

    # Repeat to prove stable ordering.
    out2 = snapshot_diff_from_ledger(ledger, a="prev", b="latest", tail=100)
    assert out2["diff"]["top_actions"] == actions


def test_snapshot_diff_empty_changes_have_no_top_actions(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    a = _snapshot_row(
        ts="2026-02-16T12:00:00Z",
        as_of=None,
        systems=[{"system_id": "x", "status": "green", "violations": []}],
        ranked=["x"],
        strict_failure=None,
    )
    b = _snapshot_row(
        ts="2026-02-16T12:05:00Z",
        as_of=None,
        systems=[{"system_id": "x", "status": "green", "violations": []}],
        ranked=["x"],
        strict_failure=None,
    )
    _write_ledger(ledger, [a, b])

    out = snapshot_diff_from_ledger(ledger, a="prev", b="latest", tail=10)
    assert out["diff"]["top_actions"] == []


def test_snapshot_diff_pretty_mode_smoke(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    a = _snapshot_row(
        ts="2026-02-16T12:00:00Z",
        as_of=None,
        systems=[{"system_id": "x", "status": "green", "violations": []}],
        ranked=["x"],
        strict_failure=None,
    )
    b = _snapshot_row(
        ts="2026-02-16T13:00:00Z",
        as_of=None,
        systems=[{"system_id": "x", "status": "yellow", "violations": []}],
        ranked=["x"],
        strict_failure=None,
    )
    _write_ledger(ledger, [a, b])
    payload = snapshot_diff_from_ledger(ledger, a="prev", b="latest", tail=10)

    pretty = render_snapshot_diff_pretty(payload)
    assert "Snapshot Diff" in pretty
    assert "Top Actions" in pretty
    assert "STATUS_REGRESSION" in pretty


def test_snapshot_diff_as_of_filters_entries_before_ref_resolution(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rows = [
        _snapshot_row(
            ts="2026-02-16T12:01:00Z",
            as_of="2026-02-16T12:00:00Z",
            systems=[{"system_id": "x", "status": "green", "violations": []}],
            ranked=["x"],
            strict_failure=None,
        ),
        _snapshot_row(
            ts="2026-02-16T12:21:00Z",
            as_of="2026-02-16T12:20:00Z",
            systems=[{"system_id": "x", "status": "yellow", "violations": []}],
            ranked=["x"],
            strict_failure=None,
        ),
        _snapshot_row(
            ts="2026-02-16T13:01:00Z",
            as_of="2026-02-16T13:00:00Z",
            systems=[{"system_id": "x", "status": "red", "violations": ["PRIMITIVES_MIN"]}],
            ranked=["x"],
            strict_failure=None,
        ),
    ]
    _write_ledger(ledger, rows)

    out = snapshot_diff_from_ledger(
        ledger=ledger,
        a="prev",
        b="latest",
        tail=10,
        as_of=datetime(2026, 2, 16, 12, 30, tzinfo=timezone.utc),
    )
    diff = out["diff"]
    assert diff["a"]["ts"] == "2026-02-16T12:01:00Z"
    assert diff["b"]["ts"] == "2026-02-16T12:21:00Z"
