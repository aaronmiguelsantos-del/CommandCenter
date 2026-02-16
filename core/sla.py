from __future__ import annotations

from datetime import UTC, datetime


SLA_THRESHOLDS_DAYS = {
    "prod": 7,
    "staging": 14,
    "dev": 30,
    "sample": 9999,
}


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_ts(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _as_utc(parsed)


def tier_threshold_days(tier: str) -> int:
    return int(SLA_THRESHOLDS_DAYS.get(str(tier), SLA_THRESHOLDS_DAYS["prod"]))


def sla_status(last_event_ts: datetime | str | None, tier: str, as_of: datetime) -> str:
    """
    Deterministic pure SLA evaluation.

    Returns:
      - "ok" when last_event_ts exists and age <= threshold
      - "breach" when last_event_ts exists and age > threshold
      - "unknown" when last_event_ts is missing/unparsable
    """
    as_of_utc = _as_utc(as_of)
    last_utc = _parse_ts(last_event_ts)
    if last_utc is None:
        return "unknown"
    age_days = max(0.0, (as_of_utc - last_utc).total_seconds() / 86400.0)
    return "breach" if age_days > float(tier_threshold_days(tier)) else "ok"
