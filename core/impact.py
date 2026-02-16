from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from typing import Iterable

from core.graph import GraphView


_TIER_WEIGHT = {"prod": 3, "staging": 2, "dev": 1, "sample": 0}


@dataclass(frozen=True)
class Impacted:
    system_id: str
    distance: int
    tier: str


def compute_impact(g: GraphView, sources: Iterable[str]) -> tuple[list[str], list[Impacted]]:
    """
    Compute blast radius from sources using g.dependents (reverse edges).

    Returns:
      (sources_sorted, impacted_sorted)

    impacted excludes the sources themselves.

    Deterministic ordering:
      - traversal uses sorted dependents from GraphView
      - final impacted sorted by:
          tier severity (prod > staging > dev > sample),
          then distance asc,
          then system_id asc
    """
    src = sorted({str(s) for s in sources if str(s)})

    # BFS from each source; keep minimal distance found.
    dist: dict[str, int] = {}

    q: deque[tuple[str, int]] = deque()
    for s in src:
        q.append((s, 0))

    while q:
        node, d = q.popleft()
        for dep in g.dependents.get(node, []):
            nd = d + 1
            # record shortest distance only
            prev = dist.get(dep)
            if prev is None or nd < prev:
                dist[dep] = nd
                q.append((dep, nd))

    # remove sources from impacted
    for s in src:
        dist.pop(s, None)

    impacted: list[Impacted] = []
    for sid, d in dist.items():
        tier = g.tiers.get(sid, "prod")
        impacted.append(Impacted(system_id=sid, distance=int(d), tier=tier))

    impacted.sort(key=lambda x: (-_TIER_WEIGHT.get(x.tier, 0), x.distance, x.system_id))
    return src, impacted


def render_impact_line(sources: list[str], impacted: list[Impacted]) -> str | None:
    """
    Render a single deterministic Impact line for text reports.
    If no sources or no impacted, return None.
    """
    if not sources:
        return None
    if not impacted:
        return None

    # Render first up to 3 impacted (deterministic after sort)
    parts: list[str] = []
    for it in impacted[:3]:
        hop = "hop" if it.distance == 1 else "hops"
        parts.append(f"{it.system_id} ({it.distance} {hop})")

    src_txt = ", ".join(sources)
    imp_txt = ", ".join(parts)
    more = ""
    if len(impacted) > 3:
        more = f", +{len(impacted) - 3} more"
    return f"Impact: {src_txt} → {imp_txt}{more}"
