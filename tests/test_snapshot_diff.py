from __future__ import annotations

import json
from pathlib import Path

from core.snapshot_diff import snapshot_diff_from_ledger


def _write_ledger(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")


def test_snapshot_diff_detects_status_change_and_new_reason(tmp_path: Path) -> None:
    ledger = tmp_path / "data" / "snapshots" / "report_snapshot_history.jsonl"

    a = {
        "ts": "2026-02-16T12:00:00Z",
        "snapshot": {
            "ts": "2026-02-16T12:00:00Z",
            "systems": [{"system_id": "x", "status": "green"}],
            "risk": {"ranked": [{"system_id": "x"}]},
            "strict_failure": None,
        },
    }
    b = {
        "ts": "2026-02-16T13:00:00Z",
        "snapshot": {
            "ts": "2026-02-16T13:00:00Z",
            "systems": [{"system_id": "x", "status": "yellow"}],
            "risk": {"ranked": [{"system_id": "x"}]},
            "strict_failure": {
                "schema_version": "1.0",
                "strict_failed": True,
                "policy": {"blocked_tiers": ["prod"], "include_staging": False, "include_dev": False, "enforce_sla": True},
                "reasons": [{"system_id": "x", "tier": "prod", "reason_code": "SLA_BREACH", "details": {"threshold_days": 7}}],
            },
        },
    }

    _write_ledger(ledger, [a, b])

    out = snapshot_diff_from_ledger(ledger, a="prev", b="latest", tail=100)
    assert "error" not in out
    diff = out["diff"]
    assert diff["a"]["ts"] == "2026-02-16T12:00:00Z"
    assert diff["b"]["ts"] == "2026-02-16T13:00:00Z"
    assert diff["system_status_changes"] == [{"system_id": "x", "from": "green", "to": "yellow"}]
    assert len(diff["new_strict_reasons"]) == 1
    assert diff["new_strict_reasons"][0]["reason_code"] == "SLA_BREACH"


def test_snapshot_diff_bad_refs(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [{"ts": "t", "snapshot": {"systems": []}}])
    out = snapshot_diff_from_ledger(ledger, a="nope", b="latest", tail=10)
    assert out["error"] == "BAD_REF"
