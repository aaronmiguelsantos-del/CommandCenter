from __future__ import annotations

from typing import Dict, List

from .models import SystemContract


def recommend_fixes(
    overall: float, dim: Dict[str, float], issues: List[str], contracts: List[SystemContract]
) -> List[str]:
    fixes: List[str] = []

    if dim.get("coverage", 0) < 80:
        fixes.append(
            "Standardize contracts: fill inputs/outputs/invariants/failure_modes for every system "
            "(target >= 90% coverage)."
        )

    if dim.get("reuse", 0) < 70:
        fixes.append(
            "Refactor bespoke logic into primitives: require each system to declare >= 6 "
            "primitives_used from the APL list."
        )

    if dim.get("observability", 0) < 70:
        fixes.append("Instrument logs: every meaningful run emits EventRecord + DecisionRecord + MetricSample.")

    if dim.get("staleness", 0) < 70:
        fixes.append("Add a monthly contract refresh: bump version + add a changelog note even for small improvements.")

    # Merge candidates (simple heuristic): systems with similar primitive sets
    if len(contracts) >= 2:
        fixes.append(
            "Scan for merge candidates: systems with >70% overlapping primitives are likely redundant—consider "
            "consolidating."
        )

    # Trim the list
    fixes.extend([f"Fix: {x}" for x in issues[:6]])
    return fixes[:10]


def rag_from_score(score: float) -> str:
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"
