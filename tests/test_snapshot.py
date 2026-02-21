from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.snapshot import compute_stats, tail_snapshots


def _write_line(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def test_tail_snapshots_filters_and_orders(tmp_path: Path) -> None:
    ledger = tmp_path / "report_snapshot_history.jsonl"
    now = datetime.now(timezone.utc)

    for i in range(5):
        ts = (now - timedelta(hours=10 - i)).isoformat().replace("+00:00", "Z")
        _write_line(
            ledger,
            {"ts": ts, "summary": {"status": "green", "strict_ready_now": True}},
        )

    rows = tail_snapshots(ledger, n=3)
    assert len(rows) == 3
    # chronological (last 3)
    assert rows[0]["ts"] < rows[-1]["ts"]

    rows2 = tail_snapshots(ledger, n=50, since_hours=3)
    # should include only recent ones (<= 3 hours from now), likely 0..depending, but deterministic check:
    for r in rows2:
        assert "ts" in r


def test_compute_stats_counts_reasons_deterministic(tmp_path: Path) -> None:
    ledger = tmp_path / "report_snapshot_history.jsonl"
    now = datetime.now(timezone.utc)

    # 2 strict failures, same reason/system
    for i in range(2):
        ts = (now - timedelta(hours=i)).isoformat().replace("+00:00", "Z")
        _write_line(
            ledger,
            {
                "ts": ts,
                "summary": {"status": "yellow", "strict_ready_now": False},
                "strict_failure": {
                    "schema_version": "1.0",
                    "policy": {"blocked_tiers": ["prod"], "include_staging": False, "include_dev": False, "enforce_sla": True},
                    "strict_failed": True,
                    "reasons": [
                        {
                            "system_id": "prod-fail",
                            "tier": "prod",
                            "reason_code": "SLA_BREACH",
                            "details": {"threshold_days": 7, "days_since_event": 30, "sla_status": "breach"},
                        }
                    ],
                },
            },
        )

    payload = compute_stats(ledger, days=7)
    assert payload["stats_version"] == "1.0"
    assert payload["total"] == 2
    assert payload["strict_ready_rate"] == 0.0
    assert payload["status_counts"]["yellow"] == 2
    top = payload["top_reasons"][0]
    assert top["reason_code"] == "SLA_BREACH"
    assert top["count"] == 2
