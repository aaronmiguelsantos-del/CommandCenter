from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .models import SystemContract


def _days_since(dt: datetime) -> float:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt.astimezone(timezone.utc)
    return max(delta.total_seconds() / 86400.0, 0.0)


def score_health(
    contracts: List[SystemContract], logs_by_system: Dict[str, int]
) -> Tuple[float, Dict[str, float], List[str]]:
    """
    Lightweight scoring using proxies.
    You can harden later with real tests & invariant checks.
    """
    issues: List[str] = []
    if not contracts:
        return (
            0.0,
            {"coverage": 0, "reuse": 0, "staleness": 0, "observability": 0},
            ["No system contracts found."],
        )

    # Coverage: contracts completeness
    coverage_vals = []
    reuse_vals = []
    staleness_vals = []
    observ_vals = []

    for c in contracts:
        # Coverage proxy
        fields = [c.purpose, c.inputs, c.outputs, c.primitives_used, c.invariants, c.failure_modes]
        filled = sum(1 for x in fields if (x if not isinstance(x, list) else len(x) > 0))
        coverage = filled / len(fields)
        coverage_vals.append(coverage * 100)

        # Reuse proxy: primitives count
        reuse = min(len(set(c.primitives_used)) / 6.0, 1.0)  # expects ~6+ for mature
        reuse_vals.append(reuse * 100)

        # Staleness proxy
        days = _days_since(c.updated_at)
        staleness = 100.0 if days <= 14 else max(0.0, 100.0 - (days - 14) * 3.0)
        staleness_vals.append(staleness)

        # Observability proxy: has logs
        logn = logs_by_system.get(c.system_id, 0)
        observ = 100.0 if logn >= 10 else (logn / 10.0) * 100.0
        observ_vals.append(observ)

        if coverage < 0.67:
            issues.append(f"{c.name}: contract incomplete (coverage {coverage*100:.0f}%).")
        if reuse < 0.34:
            issues.append(f"{c.name}: low primitive reuse ({reuse*100:.0f}%).")
        if staleness < 60:
            issues.append(f"{c.name}: stale contract ({days:.0f}d since update).")
        if logn == 0:
            issues.append(f"{c.name}: no logs found (observability 0%).")

    dim = {
        "coverage": sum(coverage_vals) / len(coverage_vals),
        "reuse": sum(reuse_vals) / len(reuse_vals),
        "staleness": sum(staleness_vals) / len(staleness_vals),
        "observability": sum(observ_vals) / len(observ_vals),
    }

    # Overall: weighted
    overall = (
        0.30 * dim["coverage"]
        + 0.30 * dim["reuse"]
        + 0.20 * dim["staleness"]
        + 0.20 * dim["observability"]
    )
    overall = round(overall, 1)
    return overall, dim, issues
