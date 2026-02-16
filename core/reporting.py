from __future__ import annotations

import json
from collections import Counter, deque
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.health import compute_health_for_system
from core.graph import GraphView, build_graph
from core.impact import Impacted, compute_impact, render_impact_line
from core.registry import load_registry, load_registry_systems, registry_path as registry_file_path
from core.storage import list_event_rows


# NOTE: no new deps; stdlib only.


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
        payload = compute_health_for_system(sid, contracts_glob, events_glob, as_of=as_of)
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


def _current_system_health(registry_path: str | None) -> list[dict[str, Any]]:
    systems: list[dict[str, Any]] = []
    for spec in load_registry(registry_path):
        payload = compute_health_for_system(spec.system_id, spec.contracts_glob, spec.events_glob)
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


def _system_recency(registry_path: str | None) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    is_sample_by_system = {spec.system_id: spec.is_sample for spec in load_registry(registry_path)}
    last_by_system: dict[str, datetime] = {}

    for row in list_event_rows():
        system_id = str(row.get("system_id", "")).strip()
        if not system_id:
            continue
        ts = _parse_ts(str(row.get("ts", "")))
        if ts is None:
            continue
        current = last_by_system.get(system_id)
        if current is None or ts > current:
            last_by_system[system_id] = ts

    recency: list[dict[str, Any]] = []
    for system_id, is_sample in sorted(is_sample_by_system.items()):
        last = last_by_system.get(system_id)
        days = 999999 if last is None else max(0, int((now - last).total_seconds() // 86400))
        recency.append(
            {
                "system_id": system_id,
                "is_sample": is_sample,
                "days_since_last_event": days,
                "stale": days > 14,
            }
        )
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
) -> dict[str, Any]:
    loaded = load_history(tail=tail, path=history_path)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=max(0, int(days)))

    analyzed: list[dict[str, Any]] = []
    for row in loaded:
        ts = _parse_ts(str(row.get("ts", "")))
        if ts is not None and ts >= cutoff:
            analyzed.append(row)
    if not analyzed:
        analyzed = loaded

    latest = loaded[-1] if loaded else {}
    current_systems = _current_system_health(registry_path)
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
        for hint in hints:
            if str(hint.get("severity", "")).lower() == "high" and hint.get("systems"):
                hint["why"] = str(hint.get("why", "")) + _impact_suffix(g, list(hint.get("systems", [])))

        now_utc = _now_utc()
        contributors = _drift_contributors(registry_rows, now_utc=now_utc)
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
        },
        "trend": trend,
        "violations": {
            "top": violation_rows,
        },
        "systems": {
            "recency": _system_recency(registry_path),
            "status": current_systems,
        },
        "impact": {
            "sources": src,
            "impacted": [
                {"system_id": it.system_id, "distance": it.distance, "tier": it.tier}
                for it in impacted
            ],
        },
        "hints": hints,
    }

    policy = strict_policy or {
        "strict_blocked_tiers": ["prod"],
        "include_staging": False,
        "include_dev": False,
    }
    tiers = policy.get("strict_blocked_tiers", ["prod"])
    tiers_sorted = sorted([str(t) for t in tiers if str(t)])

    report["policy"] = {
        "strict_blocked_tiers": tiers_sorted,
        "include_staging": bool(policy.get("include_staging", False)),
        "include_dev": bool(policy.get("include_dev", False)),
    }
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
            _trend_drift_line(trend, _now_utc()),
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
