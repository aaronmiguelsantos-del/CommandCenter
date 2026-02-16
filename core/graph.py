from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import heapq


@dataclass(frozen=True)
class GraphView:
    """
    Deterministic dependency graph view.

    Semantics:
      - depends_on means: system -> its prerequisites
      - topo order means: prerequisites appear before dependents
    """
    # system -> sorted list of dependencies
    depends_on: dict[str, list[str]]

    # system -> sorted list of dependents
    dependents: dict[str, list[str]]

    # deterministic topological order (deps first)
    topo_order: list[str]

    # metadata (from registry)
    tiers: dict[str, str]
    owners: dict[str, list[str]]


def build_graph(systems: Sequence[object]) -> GraphView:
    """
    Build a deterministic graph from normalized registry systems.

    Expects each system object to have:
      - system_id: str
      - depends_on: tuple[str, ...] or list[str]
      - tier: str
      - owners: tuple[str, ...] or list[str]

    Does not validate cycles or missing references (validate step already handles).
    """
    # Collect ids deterministically
    ids = sorted(str(getattr(s, "system_id")) for s in systems)

    # Base maps
    depends_on: dict[str, list[str]] = {sid: [] for sid in ids}
    dependents: dict[str, list[str]] = {sid: [] for sid in ids}
    tiers: dict[str, str] = {}
    owners: dict[str, list[str]] = {}

    # Fill depends_on + metadata
    for s in systems:
        sid = str(getattr(s, "system_id"))
        dep_raw = getattr(s, "depends_on", ()) or ()
        dep_list = [str(x) for x in dep_raw if str(x)]
        dep_list_sorted = sorted(dep_list)

        # Ensure key exists even if registry had weird ordering
        depends_on.setdefault(sid, [])
        depends_on[sid] = dep_list_sorted

        tiers[sid] = str(getattr(s, "tier", "prod") or "prod")

        owners_raw = getattr(s, "owners", ()) or ()
        owners_list = [str(x) for x in owners_raw if str(x)]
        owners[sid] = sorted(owners_list)

    # Build reverse edges: dep -> dependent
    for sid, deps in depends_on.items():
        for d in deps:
            if d not in dependents:
                # validate should have caught missing; ignore here to stay pure/robust
                continue
            dependents[d].append(sid)

    # Sort dependents lists deterministically
    for sid in list(dependents.keys()):
        dependents[sid] = sorted(dependents[sid])

    topo = _topological_order(ids, depends_on)

    return GraphView(
        depends_on={k: list(v) for k, v in sorted(depends_on.items(), key=lambda kv: kv[0])},
        dependents={k: list(v) for k, v in sorted(dependents.items(), key=lambda kv: kv[0])},
        topo_order=topo,
        tiers=dict(sorted(tiers.items(), key=lambda kv: kv[0])),
        owners=dict(sorted(owners.items(), key=lambda kv: kv[0])),
    )


def _topological_order(all_ids: list[str], depends_on: dict[str, list[str]]) -> list[str]:
    """
    Deterministic Kahn's algorithm.

    Edge semantics:
      if A depends_on B, then B must come before A.
    """
    indeg: dict[str, int] = {sid: 0 for sid in all_ids}
    forward: dict[str, list[str]] = {sid: [] for sid in all_ids}

    # Build edges dep -> sid
    for sid in all_ids:
        for dep in depends_on.get(sid, []):
            if dep not in indeg:
                continue
            forward[dep].append(sid)
            indeg[sid] += 1

    # Deterministic neighbor order
    for sid in all_ids:
        forward[sid].sort()

    # Deterministic queue of zero indegree nodes
    heap: list[str] = []
    for sid in all_ids:
        if indeg[sid] == 0:
            heapq.heappush(heap, sid)

    out: list[str] = []
    while heap:
        node = heapq.heappop(heap)
        out.append(node)
        for nxt in forward[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, nxt)

    # If cycle exists, output will be partial. Validate should prevent this.
    # Still deterministic: append remaining sorted.
    if len(out) != len(all_ids):
        remaining = sorted([sid for sid in all_ids if sid not in set(out)])
        out.extend(remaining)

    return out


def render_graph_text(g: GraphView) -> str:
    lines: list[str] = []
    lines.append("Codex Kernel — Dependency Graph")
    lines.append(f"Systems: {len(g.topo_order)}")
    lines.append("")
    lines.append("Topological order (deps first):")
    lines.append("  " + " -> ".join(g.topo_order))
    lines.append("")
    lines.append("Systems:")
    for sid in g.topo_order:
        tier = g.tiers.get(sid, "prod")
        deps = g.depends_on.get(sid, [])
        deps_txt = ", ".join(deps) if deps else "-"
        rdeps = g.dependents.get(sid, [])
        rdeps_txt = ", ".join(rdeps) if rdeps else "-"
        owners = g.owners.get(sid, [])
        owners_txt = ", ".join(owners) if owners else "-"
        lines.append(f"- {sid} (tier={tier})")
        lines.append(f"  depends_on: {deps_txt}")
        lines.append(f"  dependents: {rdeps_txt}")
        lines.append(f"  owners: {owners_txt}")
    return "\n".join(lines)


def graph_as_json(g: GraphView) -> dict:
    return {
        "graph_version": "1.0",
        "depends_on": g.depends_on,
        "dependents": g.dependents,
        "topo_order": g.topo_order,
        "tiers": g.tiers,
        "owners": g.owners,
    }
