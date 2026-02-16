from __future__ import annotations

from datetime import datetime, timezone

from core.sla import SLA_THRESHOLDS_DAYS, sla_status, tier_threshold_days


def test_tier_threshold_days_defaults_to_prod() -> None:
    assert tier_threshold_days("prod") == SLA_THRESHOLDS_DAYS["prod"]
    assert tier_threshold_days("unknown-tier") == SLA_THRESHOLDS_DAYS["prod"]


def test_sla_status_ok_breach_unknown() -> None:
    as_of = datetime(2026, 2, 16, 12, 0, 0, tzinfo=timezone.utc)

    recent_prod = datetime(2026, 2, 12, 12, 0, 0, tzinfo=timezone.utc)
    stale_prod = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

    assert sla_status(recent_prod, "prod", as_of=as_of) == "ok"
    assert sla_status(stale_prod, "prod", as_of=as_of) == "breach"
    assert sla_status(None, "prod", as_of=as_of) == "unknown"
    assert sla_status("not-a-ts", "prod", as_of=as_of) == "unknown"


def test_sla_status_supports_iso_z_and_naive_inputs() -> None:
    as_of = datetime(2026, 2, 16, 12, 0, 0, tzinfo=timezone.utc)
    assert sla_status("2026-02-10T12:00:00Z", "prod", as_of=as_of) == "ok"
    assert sla_status("2026-01-01T00:00:00", "prod", as_of=as_of) == "breach"
