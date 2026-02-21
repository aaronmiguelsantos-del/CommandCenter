from __future__ import annotations

import json
from collections import Counter, deque
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.events import last_event_ts_from_glob
from core.health import compute_health_for_system
from core.graph import GraphView, build_graph
from core.impact import Impacted, compute_impact, render_impact_line
from core.registry import load_registry, load_registry_systems, registry_path as registry_file_path
from core.sla import SLA_THRESHOLDS_DAYS, sla_status, tier_threshold_days


# NOTE: no new deps; stdlib only.

_TIER_WEIGHT = {"prod": 4.0, "staging": 3.0, "dev": 2.0, "sample": 1.0}

def _parse_ts(value: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _now_utc() -> datetime:
    # Centralized time for deterministic patching/mocking in tests.
    return datetime.now(timezone.utc)


def _parse_iso_utc(ts: str) -> datetime:
    # Accepts ISO timestamps with timezone or Z; missing tz is treated as UTC.
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _score_at_or_before(points: list[dict[str, Any]], target: datetime) -> int | None:
    """
    points: [{"ts": iso_str, "score": int}, ...] sorted ascending by ts.
    Returns latest score where ts <= target, else None.
    """
    best: int | None = None
    best_dt: datetime | None = None
    for p in points:
        ts = p.get("ts")
        score = p.get("score")
        if ts is None or score is None:
            continue
        dt = _parse_iso_utc(str(ts))
        if dt <= target and (best_dt is None or dt > best_dt):
            best_dt = dt
            best = int(score)
    return best




def _trend_drift_line(trend: dict[str, Any], now_utc: datetime) -> str:
    """
    Pure formatting: derives drift from existing trend.points and trend.rolling_avg.
    No new state, no hint logic, deterministic.
    """
    points = trend.get("points") or []
    rolling_avg = trend.get("rolling_avg")

    if not points:
        drift_str = "n/a"
    else:
        latest_score = points[-1].get("score")
        score_24h = _score_at_or_before(points, now_utc - timedelta(hours=24))
        if latest_score is None or score_24h is None:
            drift_str = "n/a"
        else:
            drift = int(latest_score) - int(score_24h)
            drift_str = f"{drift:+d}"

    if rolling_avg is None:
        avg_str = "n/a"
    else:
        try:
            avg_str = f"{float(rolling_avg):.1f}"
        except Exception:
            avg_str = "n/a"

    return f"Drift (24h): {drift_str} | Rolling avg: {avg_str}"

def _drift_contributors(
    systems: list[dict[str, Any]],
    *,
    now_utc: datetime,
    registry_path: str | None = None,
) -> list[tuple[str, int]]:
    drops: list[tuple[str, int]] = []
    t0 = now_utc
    t1 = now_utc - timedelta(hours=24)
    cache: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def _health_at(sid: str, contracts_glob: str, events_glob: str, as_of: datetime) -> dict[str, Any]:
        key = (sid, contracts_glob, events_glob, as_of.astimezone(timezone.utc).isoformat())
        cached = cache.get(key)
        if cached is not None:
            return cached
        payload = compute_health_for_system(sid, contracts_glob, events_glob, registry_path=registry_path, as_of=as_of)
        cache[key] = payload
        return payload

    for s in systems:
        if s.get("is_sample"):
            continue
        sid = str(s.get("system_id", "")).strip()
        contracts_glob = str(s.get("contracts_glob", "")).strip()
        events_glob = str(s.get("events_glob", "")).strip()
        if not sid or not contracts_glob or not events_glob:
            continue

        h_now = _health_at(sid, contracts_glob, events_glob, t0)
        h_24 = _health_at(sid, contracts_glob, events_glob, t1)

        a = float(h_now.get("score_total", 0.0))
        b = float(h_24.get("score_total", 0.0))
        drop = int(round(b - a))
        if drop > 0:
            drops.append((sid, drop))

    drops.sort(key=lambda x: (-x[1], x[0]))
    return drops[:3]


def build_drift_hint(
    *,
    points: list[dict[str, Any]],
    rolling_avg: float | int | None,
    now_utc: datetime,
    contributors: list[tuple[str, int]] | None = None,
) -> dict[str, Any] | None:
    """
    Deterministic drift detection:
    - Compare latest score vs score at/before now-24h.
    - MED if drop >10, HIGH if drop >20.
    - If insufficient history, no hint.
    """
    if not points:
        return None

    latest = points[-1].get("score")
    latest_ts = points[-1].get("ts")
    if latest is None or latest_ts is None:
        return None

    latest_score = int(latest)
    score_24h = _score_at_or_before(points, now_utc - timedelta(hours=24))
    if score_24h is None:
        return None

    # Drift semantics: latest_score - score_at_or_before(now - 24h)
    drift = latest_score - score_24h
    drop = -drift
    if drop <= 10:
        return None

    severity = "med" if drop <= 20 else "high"
    why = f"Score dropped {drop} points vs 24h ago ({score_24h} -> {latest_score})."
    if rolling_avg is not None:
        try:
            avg = float(rolling_avg)
            why += f" Rolling avg: {avg:.1f}."
        except Exception:
            pass

    systems: list[str] = []
    if contributors:
        systems = [sid for sid, _drop in contributors]
        top_line = " | ".join(f"{sid} -{drop}" for sid, drop in contributors)
        why += f" Top drift (24h): {top_line}."

    return {
        "severity": severity,
        "title": "Health drift detected",
        "why": why,
        "fix": "Inspect recent violations + event recency. Run: `python -m app.main report health` then `python -m app.main health --all` to isolate the system(s) pulling the aggregate down.",
        "systems": systems,
    }


def load_history(tail: int = 2000, path: str | Path | None = None) -> list[dict[str, Any]]:
    history_path = Path(path) if path is not None else Path("data/snapshots/health_history.jsonl")
    if not history_path.exists():
        return []

    buf: deque[str] = deque(maxlen=max(1, int(tail)))
    with history_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                buf.append(line)

    out: list[dict[str, Any]] = []
    for line in buf:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def _current_system_health(registry_path: str | None, *, as_of: datetime | None = None) -> list[dict[str, Any]]:
    systems: list[dict[str, Any]] = []
    for spec in load_registry(registry_path):
        payload = compute_health_for_system(
            spec.system_id,
            spec.contracts_glob,
            spec.events_glob,
            registry_path=registry_path,
            as_of=as_of,
        )
        systems.append(
            {
                "system_id": spec.system_id,
                "is_sample": spec.is_sample,
                "status": payload["status"],
                "score_total": payload["score_total"],
                "violations": payload["violations"],
            }
        )
    return systems


def _system_recency(registry_path: str | None, *, as_of: datetime | None = None) -> list[dict[str, Any]]:
    now = as_of.astimezone(UTC) if as_of is not None else datetime.now(UTC)
    recency: list[dict[str, Any]] = []

    for spec in load_registry(registry_path):
        last = last_event_ts_from_glob(spec.events_glob, registry_path=registry_path, as_of=as_of)
        days = 999999 if last is None else max(0, int((now - last).total_seconds() // 86400))
        recency.append(
            {
                "system_id": spec.system_id,
                "is_sample": spec.is_sample,
                "days_since_last_event": days,
                "last_event_ts": _iso_utc(last) if last is not None else None,
                "stale": days > 14,
            }
        )

    recency.sort(key=lambda row: str(row.get("system_id", "")))
    return recency


def _aggregate_non_sample(current_systems: list[dict[str, Any]]) -> dict[str, Any]:
    non_sample = [row for row in current_systems if not row.get("is_sample", False)]
    if not non_sample:
        return {"status": "unknown", "score_total": 0.0, "strict_ready_now": True}

    statuses = [str(row.get("status", "unknown")) for row in non_sample]
    if any(status == "red" for status in statuses):
        status = "red"
    elif any(status == "yellow" for status in statuses):
        status = "yellow"
    else:
        status = "green"

    avg_score = sum(float(row.get("score_total", 0.0)) for row in non_sample) / len(non_sample)
    strict_ready_now = status != "red"
    return {
        "status": status,
        "score_total": round(avg_score, 2),
        "strict_ready_now": strict_ready_now,
    }


def _augment_current_systems(
    current_systems: list[dict[str, Any]],
    systems: list[Any],
    recency_rows: list[dict[str, Any]],
    *,
    as_of: datetime,
) -> list[dict[str, Any]]:
    recency_by_id = {str(row.get("system_id", "")): row for row in recency_rows}
    by_id = {str(spec.system_id): spec for spec in systems}
    out: list[dict[str, Any]] = []
    for row in sorted(current_systems, key=lambda r: str(r.get("system_id", ""))):
        system_id = str(row.get("system_id", "")).strip()
        spec = by_id.get(system_id)
        tier = str(getattr(spec, "tier", "prod")) if spec is not None else "prod"
        owners = sorted([str(x) for x in getattr(spec, "owners", ())]) if spec is not None else []
        recency = recency_by_id.get(system_id, {})
        days = int(recency.get("days_since_last_event", 999999))
        last_event_ts = recency.get("last_event_ts")
        status = sla_status(last_event_ts, tier, as_of=as_of)
        max_days = tier_threshold_days(tier)
        escalation_hint = (
            f"Escalate to owners ({','.join(owners)}) and emit event within {max_days}d."
            if owners
            else f"Assign owner and emit event within {max_days}d."
        )
        enriched = {
            **row,
            "tier": tier,
            "owners": owners,
            "days_since_last_event": days,
            "last_event_ts": last_event_ts,
            "sla_status": status,
            "sla_max_days": max_days,
            "escalation_hint": escalation_hint,
        }
        out.append(enriched)
    return out


def _risk_scores(g: GraphView, sources: list[str]) -> list[dict[str, Any]]:
    if not sources:
        return []
    risk_rows: list[dict[str, Any]] = []
    for source in sorted(set(sources)):
        tier = g.tiers.get(source, "prod")
        tier_weight = _TIER_WEIGHT.get(tier, 1.0)
        _, impacted = compute_impact(g, [source])
        dependents_count = len(impacted)
        avg_distance = (sum(x.distance for x in impacted) / dependents_count) if dependents_count else 0.0
        avg_distance_weight = 1.0 if dependents_count == 0 else (1.0 + (1.0 / (1.0 + avg_distance)))
        risk_score = round(tier_weight * (1.0 + dependents_count) * avg_distance_weight, 2)
        risk_rows.append(
            {
                "system_id": source,
                "tier": tier,
                "dependents_count": dependents_count,
                "avg_distance": round(avg_distance, 2),
                "risk_score": risk_score,
                "impacted": [
                    {"system_id": x.system_id, "distance": x.distance, "tier": x.tier}
                    for x in impacted
                ],
            }
        )
    risk_rows.sort(key=lambda r: (-float(r["risk_score"]), str(r["system_id"])))
    return risk_rows


def _sla_hints(current_systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    breach_rows = [
        row for row in current_systems
        if not row.get("is_sample", False) and row.get("sla_status") in {"breach", "unknown"}
    ]
    for row in sorted(breach_rows, key=lambda r: (str(r.get("sla_status", "")), str(r.get("system_id", "")))):
        severity = "high" if row.get("sla_status") == "breach" else "med"
        system_id = str(row.get("system_id", ""))
        owners = [str(x) for x in row.get("owners", [])]
        why = (
            f"{system_id} is {row.get('sla_status')} ({int(row.get('days_since_last_event', 0))}d since last event, "
            f"SLA max {int(row.get('sla_max_days', 0))}d)."
        )
        hints.append(
            {
                "severity": severity,
                "title": "SLA escalation required",
                "why": why,
                "fix": str(row.get("escalation_hint", "")),
                "systems": [system_id],
                "owners": owners,
            }
        )
    return hints[:2]


def _hint_template(code: str) -> dict[str, str]:
    if code == "PRIMITIVES_MIN":
        return {
            "title": "System contract missing minimum primitives",
            "why": "Contract must declare >=3 primitives_used to stay enforceable.",
            "fix": (
                "Edit the system contract JSON and set primitives_used to at least 3 items "
                '(e.g., ["P0","P1","P7"]). Re-run: python -m app.main health --all --strict'
            ),
        }
    if code == "INVARIANTS_MIN":
        return {
            "title": "System contract missing minimum invariants",
            "why": "Contract must reference >=3 invariant IDs to define what must remain true.",
            "fix": (
                "Edit the system contract JSON and set invariants to at least 3 IDs "
                '(e.g., ["INV-001","INV-002","INV-003"]). Re-run: python -m app.main health --all --strict'
            ),
        }
    if code == "EVENTS_RECENT":
        return {
            "title": "System is stale (no recent events)",
            "why": "Systems must emit events within 14 days to prove they're alive.",
            "fix": "Run: python -m app.main log <system_id> status_update (or run the system). Then re-run strict.",
        }
    return {
        "title": "Health violation requires attention",
        "why": "A health rule is failing.",
        "fix": "Inspect report.systems.status for violations and update contract/events accordingly.",
    }


def _build_hints(current_systems: list[dict[str, Any]], snapshot_status: str, include_hints: bool) -> list[dict[str, Any]]:
    if not include_hints:
        return []

    red_non_sample = [row for row in current_systems if not row.get("is_sample", False) and row.get("status") == "red"]
    if red_non_sample:
        affected_by_violation: dict[str, set[str]] = {}
        freq: Counter[str] = Counter()
        for row in red_non_sample:
            system_id = str(row.get("system_id", "")).strip()
            for code in row.get("violations", []) or []:
                key = str(code)
                freq[key] += 1
                affected_by_violation.setdefault(key, set()).add(system_id)

        top = sorted(
            freq.items(),
            key=lambda kv: (-kv[1], kv[0]),
        )[:2]

        hints: list[dict[str, Any]] = []
        for code, _count in top:
            tpl = _hint_template(code)
            hints.append(
                {
                    "severity": "high",
                    "title": tpl["title"],
                    "why": tpl["why"],
                    "fix": tpl["fix"],
                    "systems": sorted(affected_by_violation.get(code, set())),
                }
            )
        return hints

    if snapshot_status == "red":
        sample_red_ids = sorted(
            str(row.get("system_id", "")).strip()
            for row in current_systems
            if row.get("is_sample", False) and row.get("status") == "red"
        )
        return [
            {
                "severity": "low",
                "title": "Global snapshot is red, strict is passing",
                "why": (
                    "Global health snapshot may include sample systems, legacy snapshots, "
                    "or repo-wide penalties; strict passes based on non-sample systems."
                ),
                "fix": (
                    "Use `python -m app.main health --all --strict` as the gate. Optionally clear "
                    "legacy global noise by removing sample contracts from data/contracts or by "
                    "ignoring samples in global health computation."
                ),
                "systems": sample_red_ids,
            }
        ]

    return [
        {
            "severity": "low",
            "title": "No action required",
            "why": "All non-sample systems are healthy.",
            "fix": "Keep cadence: run `make health` daily and `make test` before changes.",
            "systems": [],
        }
    ]


def _select_impact_sources(
    current_systems: list[dict[str, Any]],
    drift_sources: list[str] | None,
) -> list[str]:
    """
    Impact sources are advisory-only and must be deterministic.

    Rules (Step 5):
      - status sources: any NON-SAMPLE system that is red or yellow
      - drift sources: any system_ids from drift hint contributors (already non-sample)
    """
    src: set[str] = set()

    for row in current_systems:
        sid = str(row.get("system_id", "")).strip()
        if not sid:
            continue
        if bool(row.get("is_sample", False)):
            continue
        if row.get("status") in ("red", "yellow"):
            src.add(sid)

    if drift_sources:
        for sid in drift_sources:
            s = str(sid).strip()
            if s:
                src.add(s)

    return sorted(src)


def _impact_suffix(g: GraphView, sources: list[str]) -> str:
    if not sources:
        return ""
    _, impacted = compute_impact(g, sources)
    if not impacted:
        return ""
    parts: list[str] = []
    for it in impacted[:3]:
        hop = "hop" if it.distance == 1 else "hops"
        parts.append(f"{it.system_id} ({it.distance} {hop})")
    more = f", +{len(impacted) - 3} more" if len(impacted) > 3 else ""
    return " Impacted: " + ", ".join(parts) + more


def compute_report(
    days: int = 30,
    tail: int = 2000,
    strict: bool = False,
    registry_path: str | None = None,
    history_path: str | Path | None = None,
    include_hints: bool = True,
    strict_policy: dict[str, Any] | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    loaded = load_history(tail=tail, path=history_path)
    now = as_of.astimezone(UTC) if as_of is not None else _now_utc().astimezone(UTC)
    if as_of is not None:
        loaded = [row for row in loaded if (ts := _parse_ts(str(row.get("ts", "")))) is not None and ts <= now]
    cutoff = now - timedelta(days=max(0, int(days)))

    analyzed: list[dict[str, Any]] = []
    for row in loaded:
        ts = _parse_ts(str(row.get("ts", "")))
        if ts is not None and ts >= cutoff:
            analyzed.append(row)
    if not analyzed:
        analyzed = loaded

    latest = loaded[-1] if loaded else {}
    current_systems = _current_system_health(registry_path, as_of=as_of)
    reg_path = registry_file_path(registry_path)
    registry_obj: Any = {"systems": []}
    if reg_path.exists():
        registry_obj = json.loads(reg_path.read_text(encoding="utf-8"))

    systems = load_registry_systems(registry_obj)
    g = build_graph(systems)

    registry_rows = [
        {
            "system_id": s.system_id,
            "contracts_glob": s.contracts_glob,
            "events_glob": s.events_glob,
            "is_sample": s.is_sample,
            "tier": s.tier,
            "depends_on": list(s.depends_on),
            "owners": list(s.owners),
        }
        for s in systems
    ]
    recency_rows = _system_recency(registry_path, as_of=as_of)
    current_systems = _augment_current_systems(current_systems, systems, recency_rows, as_of=now)
    now_non_sample = _aggregate_non_sample(current_systems)
    strict_ready_now = bool(now_non_sample["strict_ready_now"])

    score_values = [float(row.get("score_total", 0.0)) for row in analyzed]
    start_score = score_values[0] if score_values else 0.0
    end_score = score_values[-1] if score_values else 0.0
    avg_score = sum(score_values) / len(score_values) if score_values else 0.0

    parsed_ts = [_parse_ts(str(row.get("ts", ""))) for row in analyzed]
    valid_ts = [ts for ts in parsed_ts if ts is not None]

    violation_counts: Counter[str] = Counter()
    last_seen: dict[str, datetime] = {}
    for row in analyzed:
        ts = _parse_ts(str(row.get("ts", "")))
        violations = row.get("violations", [])
        if not isinstance(violations, list):
            continue
        for code in violations:
            key = str(code)
            violation_counts[key] += 1
            if ts is not None and (key not in last_seen or ts > last_seen[key]):
                last_seen[key] = ts

    violation_rows: list[dict[str, Any]] = []
    for code, count in violation_counts.most_common(10):
        row = {"code": code, "count": count, "last_seen_ts": _iso_utc(last_seen[code]) if code in last_seen else None}
        violation_rows.append(row)

    trend_points: list[dict[str, Any]] = []
    for row in analyzed:
        ts = row.get("ts")
        score = row.get("score_total")
        if ts is None or score is None:
            continue
        try:
            point = {"ts": str(ts), "score": int(float(score))}
        except (TypeError, ValueError):
            continue
        trend_points.append(point)

    trend = {
        "score_total": {
            "start_score": round(start_score, 2),
            "end_score": round(end_score, 2),
            "delta": round(end_score - start_score, 2),
        },
        "rolling_avg_score": round(avg_score, 2),
        "rolling_avg": round(avg_score, 2),
        "points": trend_points,
    }

    snapshot_status = str(latest.get("status", "unknown"))
    hints = _build_hints(current_systems, snapshot_status=snapshot_status, include_hints=include_hints)
    top_drift_line = None
    drift_sources: list[str] = []
    if include_hints:
        hints.extend(_sla_hints(current_systems))
        for hint in hints:
            if str(hint.get("severity", "")).lower() == "high" and hint.get("systems"):
                hint["why"] = str(hint.get("why", "")) + _impact_suffix(g, list(hint.get("systems", [])))

        now_utc = now
        contributors = _drift_contributors(registry_rows, now_utc=now_utc, registry_path=registry_path)
        drift_hint = build_drift_hint(
            points=trend_points,
            rolling_avg=trend.get("rolling_avg"),
            now_utc=now_utc,
            contributors=contributors,
        )
        if drift_hint is not None:
            systems_for_hint = list(drift_hint.get("systems", []))
            drift_hint["why"] = str(drift_hint.get("why", "")) + _impact_suffix(g, systems_for_hint)
            hints.append(drift_hint)
            drift_sources = systems_for_hint
            if contributors:
                top_drift_line = " | ".join(f"{sid} -{drop}" for sid, drop in contributors)

    sources = _select_impact_sources(current_systems=current_systems, drift_sources=drift_sources)
    src, impacted = compute_impact(g, sources)
    risk_rows = _risk_scores(g, src)
    if include_hints and risk_rows:
        top = risk_rows[0]
        impacted_ids = [str(row["system_id"]) for row in top["impacted"][:3]]
        impacted_txt = ",".join(impacted_ids) if impacted_ids else "none"
        hints.append(
            {
                "severity": "med",
                "title": "Prioritize highest blast-radius source",
                "why": (
                    f"{top['system_id']} has the highest risk score ({top['risk_score']}) "
                    f"with {top['dependents_count']} impacted dependents."
                ),
                "fix": f"Fix {top['system_id']} first; impacted systems: {impacted_txt}.",
                "systems": [str(top["system_id"])],
                "owners": g.owners.get(str(top["system_id"]), []),
            }
        )
    hints = sorted(
        hints,
        key=lambda h: (
            {"high": 0, "med": 1, "low": 2}.get(str(h.get("severity", "low")).lower(), 3),
            str(h.get("title", "")),
        ),
    )

    report = {
        "report_version": "2.0",
        "summary": {
            "snapshots_analyzed": len(analyzed),
            "date_range": {
                "min_ts": _iso_utc(min(valid_ts)) if valid_ts else None,
                "max_ts": _iso_utc(max(valid_ts)) if valid_ts else None,
            },
            "current_status": snapshot_status,
            "current_score": float(latest.get("score_total", 0.0)) if latest else 0.0,
            "strict_ready_now": strict_ready_now,
            "now_non_sample": now_non_sample,
            "global_includes_samples": latest.get("global_includes_samples", "unknown") if latest else "unknown",
            "strict_requested": bool(strict),
            "hints_count": len(hints),
            "top_drift_24h": top_drift_line,
            "sla": {
                "thresholds_days": {
                    k: int(v) for k, v in sorted(SLA_THRESHOLDS_DAYS.items(), key=lambda kv: kv[0])
                }
            },
        },
        "trend": trend,
        "violations": {
            "top": violation_rows,
        },
        "systems": {
            "recency": recency_rows,
            "status": current_systems,
        },
        "impact": {
            "sources": src,
            "impacted": [
                {"system_id": it.system_id, "distance": it.distance, "tier": it.tier}
                for it in impacted
            ],
        },
        "risk": {
            "ranked": risk_rows,
        },
        "hints": hints,
    }

    policy = strict_policy or {
        "strict_blocked_tiers": ["prod"],
        "include_staging": False,
        "include_dev": False,
        "enforce_sla": False,
    }
    tiers = policy.get("strict_blocked_tiers", ["prod"])
    tiers_sorted = sorted([str(t) for t in tiers if str(t)])

    report["policy"] = {
        "strict_blocked_tiers": tiers_sorted,
        "include_staging": bool(policy.get("include_staging", False)),
        "include_dev": bool(policy.get("include_dev", False)),
        "enforce_sla": bool(policy.get("enforce_sla", False)),
    }
    if as_of is not None:
        report["as_of"] = _iso_utc(now)
    return report


def format_text(report: dict[str, Any], days: int) -> str:
    summary = report["summary"]
    trend = report["trend"]
    violations = report["violations"]["top"]
    systems_recency = report["systems"]["recency"]
    systems_status = report["systems"]["status"]
    hints = report.get("hints", [])

    strict_text = "PASS" if bool(summary["now_non_sample"]["strict_ready_now"]) else "FAIL"
    lines = [
        f"HEALTH REPORT ({days}d)",
        (
            f"Range: {summary['date_range']['min_ts']} -> {summary['date_range']['max_ts']} | "
            f"snapshots: {summary['snapshots_analyzed']}"
        ),
        (
            f"Now (non-sample): {summary['now_non_sample']['status']} "
            f"{float(summary['now_non_sample']['score_total']):.2f} | Strict: {strict_text}"
        ),
        (
            f"Now (global snapshot): {summary['current_status']} {float(summary['current_score']):.2f} | "
            f"global_includes_samples={summary.get('global_includes_samples', 'unknown')}"
        ),
    ]

    tiers = report.get("policy", {}).get("strict_blocked_tiers", []) if isinstance(report, dict) else []
    tiers_txt = "+".join([str(t) for t in tiers if str(t)]) if tiers else "prod"
    lines.append(f"Strict policy: {tiers_txt}")

    impact = report.get("impact", {})
    impact_sources = [str(x) for x in impact.get("sources", []) if str(x)] if isinstance(impact, dict) else []
    impacted_rows = impact.get("impacted", []) if isinstance(impact, dict) else []
    impacted_objs: list[Impacted] = []
    if isinstance(impacted_rows, list):
        for row in impacted_rows:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("system_id", "")).strip()
            if not sid:
                continue
            try:
                distance = int(row.get("distance", 0))
            except Exception:
                distance = 0
            tier = str(row.get("tier", "prod"))
            impacted_objs.append(Impacted(system_id=sid, distance=distance, tier=tier))
    impact_line = render_impact_line(impact_sources, impacted_objs)
    if impact_line:
        lines.append(impact_line)

    if hints:
        lines.extend(["", "ACTION HINTS:"])
        for hint in hints[:2]:
            systems = ",".join(hint.get("systems", [])) if hint.get("systems") else "none"
            lines.extend(
                [
                    f"- [{str(hint.get('severity', '')).upper()}] {hint.get('title', '')}",
                    f"  why: {hint.get('why', '')}",
                    f"  fix: {hint.get('fix', '')}",
                    f"  systems: {systems}",
                ]
            )

    lines.extend(
        [
            "",
            "Trend:",
            (
                f"- score_total: {trend['score_total']['start_score']:.2f} -> {trend['score_total']['end_score']:.2f} "
                f"(D {trend['score_total']['delta']:+.2f}) | avg: {trend['rolling_avg_score']:.2f}"
            ),
            _trend_drift_line(
                trend,
                _parse_ts(str(report.get("as_of"))) or _now_utc(),
            ),
        ]
    )
    if summary.get("top_drift_24h"):
        lines.append(f"Top drift (24h): {summary['top_drift_24h']}")
    lines.extend(
        [
            "",
            "Violations (count | last seen):",
        ]
    )

    if violations:
        for row in violations:
            lines.append(f"- {row['code']}: {row['count']} | {row['last_seen_ts']}")
    else:
        lines.append("- none")

    lines.extend(["", "System recency (days since last event):"])
    for row in systems_recency:
        sample = " [sample]" if row["is_sample"] else ""
        state = "STALE" if row["stale"] else "OK"
        lines.append(f"- {row['system_id']}{sample}: {row['days_since_last_event']} ({state})")

    lines.extend(["", "System status:"])
    for row in systems_status:
        sample = " [sample]" if row["is_sample"] else ""
        violations_text = ",".join(row["violations"]) if row["violations"] else "none"
        lines.append(f"- {row['system_id']}{sample}: {row['status']} ({violations_text})")

    return "\n".join(lines)


def render_report_health_text(report: dict[str, Any]) -> str:
    """
    Lightweight text renderer for tests and operator debug output.
    Accepts sparse report payloads.
    """
    lines: list[str] = []

    trend = report.get("trend", {}) if isinstance(report, dict) else {}
    score_total = trend.get("score_total", {}) if isinstance(trend, dict) else {}

    lines.append("Trend")
    lines.append(f"Start score: {score_total.get('start_score')}")
    lines.append(f"End score: {score_total.get('end_score')}")
    lines.append(f"Delta: {score_total.get('delta')}")
    lines.append(f"Rolling average: {trend.get('rolling_avg')}")
    lines.append(_trend_drift_line(trend, _now_utc()))

    return "\n".join(lines)


def build_snapshot_ledger_entry(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    policy = report.get("policy", {}) if isinstance(report, dict) else {}
    systems_status = report.get("systems", {}).get("status", []) if isinstance(report, dict) else []
    rows: list[dict[str, Any]] = []
    if isinstance(systems_status, list):
        for row in sorted(
            [r for r in systems_status if isinstance(r, dict)],
            key=lambda r: str(r.get("system_id", "")),
        ):
            rows.append(
                {
                    "system_id": str(row.get("system_id", "")),
                    "status": str(row.get("status", "unknown")),
                    "score_total": float(row.get("score_total", 0.0)),
                    "violations": sorted([str(v) for v in (row.get("violations") or [])]),
                    "tier": str(row.get("tier", "prod")),
                    "is_sample": bool(row.get("is_sample", False)),
                    "sla_status": str(row.get("sla_status", "ok")),
                }
            )
    return {
        "ts": _iso_utc(_now_utc()),
        "summary": {
            "current_status": str(summary.get("current_status", "unknown")),
            "current_score": float(summary.get("current_score", 0.0)),
            "now_non_sample": summary.get("now_non_sample", {}),
            "strict_ready_now": bool(summary.get("strict_ready_now", False)),
        },
        "policy": {
            "strict_blocked_tiers": sorted([str(x) for x in policy.get("strict_blocked_tiers", ["prod"])]),
            "include_staging": bool(policy.get("include_staging", False)),
            "include_dev": bool(policy.get("include_dev", False)),
            "enforce_sla": bool(policy.get("enforce_sla", False)),
        },
        "systems": rows,
    }


def write_snapshot_ledger(report: dict[str, Any], path: str | Path | None = None) -> Path:
    ledger_path = Path(path) if path is not None else Path("data/snapshots/report_snapshot_history.jsonl")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    entry = build_snapshot_ledger_entry(report)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return ledger_path
