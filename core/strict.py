from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.events import last_event_ts_from_glob
from core.health import compute_health_for_system
from core.registry import load_registry
from core.sla import SLA_THRESHOLDS_DAYS, sla_status
from core.timeutil import iso_utc


@dataclass(frozen=True)
class StrictPolicy:
    blocked_tiers: list[str]
    include_staging: bool
    include_dev: bool
    enforce_sla: bool


Policy = StrictPolicy


def build_policy(include_staging: bool, include_dev: bool, enforce_sla: bool) -> StrictPolicy:
    blocked = ["prod"]
    if include_staging or include_dev:
        blocked.append("staging")
    if include_dev:
        blocked.append("dev")
    return StrictPolicy(
        blocked_tiers=blocked,
        include_staging=bool(include_staging),
        include_dev=bool(include_dev),
        enforce_sla=bool(enforce_sla),
    )


STRICT_FAILURE_SCHEMA_VERSION = "1.0"
STRICT_REASON_CODES = {"RED_STATUS", "SLA_BREACH"}


def collect_strict_failures(
    registry_path_arg: str | Path | None,
    policy: StrictPolicy,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    blocked = set(policy.blocked_tiers)
    eval_time = as_of.astimezone(timezone.utc) if as_of is not None else datetime.now(timezone.utc)

    for spec in load_registry(registry_path_arg):
        if spec.is_sample:
            continue
        if spec.tier not in blocked:
            continue

        payload = compute_health_for_system(
            system_id=spec.system_id,
            contracts_glob=spec.contracts_glob,
            events_glob=spec.events_glob,
            registry_path=registry_path_arg,
            as_of=as_of,
        )

        status = str(payload.get("status", "unknown"))
        if status == "red":
            reasons.append(
                {
                    "system_id": spec.system_id,
                    "tier": spec.tier,
                    "reason_code": "RED_STATUS",
                    "details": {
                        "status": "red",
                        "score_total": float(payload.get("score_total", 0.0)),
                        "violations": payload.get("violations", []),
                    },
                }
            )
            continue

        if policy.enforce_sla:
            last_ts = last_event_ts_from_glob(
                spec.events_glob,
                registry_path=registry_path_arg,
                as_of=as_of,
            )
            st = sla_status(last_ts, spec.tier, as_of=eval_time)
            if st == "breach":
                threshold = int(SLA_THRESHOLDS_DAYS.get(spec.tier, 7))
                days_since = None
                if last_ts is not None:
                    days_since = int((eval_time - last_ts).total_seconds() // 86400)
                reasons.append(
                    {
                        "system_id": spec.system_id,
                        "tier": spec.tier,
                        "reason_code": "SLA_BREACH",
                        "details": {
                            "sla_status": "breach",
                            "threshold_days": threshold,
                            "days_since_event": days_since,
                            "as_of": iso_utc(eval_time),
                            "last_event_ts": iso_utc(last_ts) if last_ts else None,
                        },
                    }
                )

    reasons.sort(key=lambda r: (str(r.get("reason_code", "")), str(r.get("tier", "")), str(r.get("system_id", ""))))
    return reasons


def strict_failure_payload(policy: StrictPolicy, reasons: list[dict[str, Any]]) -> dict[str, Any]:
    for r in reasons:
        if r.get("reason_code") not in STRICT_REASON_CODES:
            raise ValueError(f"Invalid reason_code: {r.get('reason_code')}")

    return {
        "strict_failed": True,
        "schema_version": STRICT_FAILURE_SCHEMA_VERSION,
        "policy": {
            "blocked_tiers": list(policy.blocked_tiers),
            "include_staging": bool(policy.include_staging),
            "include_dev": bool(policy.include_dev),
            "enforce_sla": bool(policy.enforce_sla),
        },
        "reasons": reasons,
    }
