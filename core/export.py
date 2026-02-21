from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.events import last_event_ts_from_glob
from core.graph import build_graph, graph_as_json
from core.health import compute_health_for_system
from core.registry import load_registry, load_registry_systems, registry_path as registry_file_path
from core.reporting import compute_report
from core.sla import SLA_THRESHOLDS_DAYS, sla_status
from core.snapshot import read_jsonl_tail, snapshot_stats

STRICT_FAILURE_SCHEMA_VERSION = "1.0"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _blocked_tiers(include_staging: bool, include_dev: bool) -> set[str]:
    tiers = {"prod"}
    if include_staging or include_dev:
        tiers.add("staging")
    if include_dev:
        tiers.add("dev")
    return tiers


def _collect_strict_failures(
    registry_path: str | None,
    blocked_tiers: set[str],
    enforce_sla: bool,
) -> list[dict[str, Any]]:
    now_utc = datetime.now(timezone.utc)
    reasons: list[dict[str, Any]] = []

    for spec in load_registry(registry_path):
        if spec.is_sample:
            continue
        if spec.tier not in blocked_tiers:
            continue

        payload = compute_health_for_system(
            system_id=spec.system_id,
            contracts_glob=spec.contracts_glob,
            events_glob=spec.events_glob,
            registry_path=registry_path,
        )

        status = str(payload.get("status", "unknown"))
        score_total = float(payload.get("score_total", 0.0))
        violations = payload.get("violations") or []
        violations_list = [str(v) for v in violations] if isinstance(violations, list) else []

        if status == "red":
            reasons.append(
                {
                    "system_id": spec.system_id,
                    "tier": spec.tier,
                    "reason_code": "RED_STATUS",
                    "details": {
                        "status": status,
                        "score_total": round(score_total, 2),
                        "violations": sorted(violations_list),
                    },
                }
            )
            continue

        if enforce_sla:
            last_ts = last_event_ts_from_glob(spec.events_glob, registry_path=registry_path)
            if sla_status(last_ts, tier=spec.tier, as_of=now_utc) == "breach":
                threshold = int(SLA_THRESHOLDS_DAYS.get(spec.tier, 14))
                days_since = None
                if last_ts is not None:
                    days_since = int((now_utc - last_ts).total_seconds() // 86400)
                reasons.append(
                    {
                        "system_id": spec.system_id,
                        "tier": spec.tier,
                        "reason_code": "SLA_BREACH",
                        "details": {
                            "sla_status": "breach",
                            "days_since_event": days_since,
                            "threshold_days": threshold,
                        },
                    }
                )

    reasons.sort(key=lambda r: (str(r.get("reason_code")), str(r.get("tier")), str(r.get("system_id"))))
    return reasons


def _strict_failure_payload(
    blocked_tiers: set[str],
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
    reasons: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "strict_failed": True,
        "schema_version": STRICT_FAILURE_SCHEMA_VERSION,
        "policy": {
            "blocked_tiers": sorted(blocked_tiers),
            "include_staging": bool(include_staging),
            "include_dev": bool(include_dev),
            "enforce_sla": bool(enforce_sla),
        },
        "reasons": reasons,
    }


def export_bundle(
    *,
    out_dir: str | Path,
    days: int,
    tail: int,
    registry_path: str | None,
    strict: bool,
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
    include_hints: bool,
    ledger_path: str,
    n_tail: int,
    extra_files: dict[str, Any] | None = None,
) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    blocked_tiers = _blocked_tiers(include_staging, include_dev)
    strict_policy = {
        "strict_blocked_tiers": sorted(blocked_tiers),
        "include_staging": bool(include_staging),
        "include_dev": bool(include_dev),
        "enforce_sla": bool(enforce_sla),
    }

    report = compute_report(
        days=days,
        tail=tail,
        strict=bool(strict),
        registry_path=registry_path,
        include_hints=bool(include_hints),
        strict_policy=strict_policy,
    )
    report["strict_failure"] = None
    if strict:
        reasons = _collect_strict_failures(registry_path, blocked_tiers, enforce_sla=bool(enforce_sla))
        if reasons:
            report["strict_failure"] = _strict_failure_payload(
                blocked_tiers=blocked_tiers,
                include_staging=bool(include_staging),
                include_dev=bool(include_dev),
                enforce_sla=bool(enforce_sla),
                reasons=reasons,
            )
    report_path = out / "report_health.json"
    _write_json(report_path, report)
    written.append(report_path)

    reg_path = registry_file_path(registry_path)
    registry_obj: Any = {"systems": []}
    if reg_path.exists():
        registry_obj = json.loads(reg_path.read_text(encoding="utf-8"))
    systems = load_registry_systems(registry_obj)
    g = build_graph(systems)
    graph_path = out / "graph.json"
    _write_json(graph_path, graph_as_json(g))
    written.append(graph_path)

    stats_path = out / "snapshot_stats.json"
    _write_json(stats_path, snapshot_stats(ledger_path=ledger_path, days=int(days)))
    written.append(stats_path)

    tail_path = out / "snapshot_tail.json"
    _write_json(
        tail_path,
        {"ledger": ledger_path, "n": int(n_tail), "rows": read_jsonl_tail(ledger_path=ledger_path, n=max(1, int(n_tail)))},
    )
    written.append(tail_path)

    if extra_files:
        for name in sorted(extra_files.keys()):
            target = out / str(name)
            _write_json(target, extra_files[name])
            written.append(target)

    meta_path = out / "bundle_meta.json"
    meta = {
        "bundle_version": "1.0",
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "inputs": {
            "days": int(days),
            "tail": int(tail),
            "registry_path": registry_path,
            "strict": bool(strict),
            "policy": {
                "blocked_tiers": sorted(blocked_tiers),
                "include_staging": bool(include_staging),
                "include_dev": bool(include_dev),
                "enforce_sla": bool(enforce_sla),
            },
            "include_hints": bool(include_hints),
            "ledger_path": ledger_path,
            "n_tail": int(n_tail),
        },
        "files": [p.name for p in written],
    }
    _write_json(meta_path, meta)
    written.append(meta_path)

    return written
