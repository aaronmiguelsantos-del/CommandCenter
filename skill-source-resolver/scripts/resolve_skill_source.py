#!/usr/bin/env python3
"""Resolve best local source root containing skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
}


class SourceResolverError(Exception):
    pass


def _is_skill_dir(path: Path) -> bool:
    return (path / "SKILL.md").exists() and (path / "agents" / "openai.yaml").exists()


def _discover_skill_names(root: Path) -> List[str]:
    names: List[str] = []
    if not root.exists() or not root.is_dir():
        return names
    try:
        children = sorted(root.iterdir())
    except Exception:
        return names
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        if _is_skill_dir(child):
            names.append(child.name)
    return names


def _is_installed_inventory(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    return path.name.lower() == "skills" and ".codex" in parts


def _score_candidate(path: Path, skills: List[str], prefer_repo_root: bool) -> int:
    score = min(len(skills), 50) * 10
    has_skills_index = (path / "skills_index.json").exists()
    has_makefile = (path / "Makefile").exists()
    has_git = (path / ".git").exists()
    has_data = (path / "data").exists()

    if has_skills_index:
        score += 60
    if has_makefile:
        score += 20
    if has_git:
        score += 20
    if has_data:
        score += 20
    if path.name.lower() == "skills":
        score -= 20
    if "skill" in path.name.lower():
        score += 1

    if prefer_repo_root:
        if has_git:
            score += 320
        if has_makefile:
            score += 140
        if has_skills_index:
            score += 80
        if has_data:
            score += 30
        if _is_installed_inventory(path):
            score -= 240

    return score


def _iter_candidates(start: Path, max_depth: int) -> List[Path]:
    out: List[Path] = []
    seen = set()

    def walk(path: Path, depth: int) -> None:
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        out.append(path)
        if depth >= max_depth:
            return
        try:
            children = sorted(path.iterdir())
        except Exception:
            return
        for child in children:
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in IGNORED_DIRS:
                continue
            walk(child, depth + 1)

    walk(start, 0)
    return out


def _seed_roots(start: Path) -> List[Path]:
    seeds: List[Path] = []
    seen = set()

    def add(path: Path) -> None:
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        seeds.append(path)

    add(start)
    parent = start
    for _ in range(4):
        parent = parent.parent
        if not parent.exists() or not parent.is_dir():
            break
        add(parent)
        try:
            children = sorted(parent.iterdir())
        except Exception:
            continue
        for child in children:
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in IGNORED_DIRS:
                continue
            lowered = child.name.lower()
            if "skill" in lowered or "repo" in lowered:
                add(child)
    return seeds


def _resolve(
    start: Path,
    max_depth: int,
    min_skills: int,
    include_ancestor_search: bool,
    prefer_repo_root: bool,
) -> Dict[str, Any]:
    if max_depth < 0:
        raise SourceResolverError("--max-depth must be >= 0")
    if min_skills < 1:
        raise SourceResolverError("--min-skills must be >= 1")

    effective_start = start
    if not effective_start.exists():
        parent = effective_start.parent
        if parent.exists() and parent.is_dir():
            effective_start = parent
        else:
            raise SourceResolverError(f"start path does not exist: {start}")

    candidates: List[Dict[str, Any]] = []
    seeds = _seed_roots(effective_start) if include_ancestor_search else [effective_start]
    for i, seed in enumerate(seeds):
        depth = max_depth if i == 0 else min(2, max_depth)
        for candidate in _iter_candidates(seed, max_depth=depth):
            skills = _discover_skill_names(candidate)
            score = _score_candidate(candidate, skills, prefer_repo_root=prefer_repo_root)
            if i > 0:
                score -= 1
            candidates.append(
                {
                    "path": str(candidate),
                    "skills_count": len(skills),
                    "skills_preview": skills[:10],
                    "score": score,
                    "seed_root": str(seed),
                    "is_installed_inventory": _is_installed_inventory(candidate),
                }
            )

    ranked = sorted(candidates, key=lambda row: (-int(row["score"]), str(row["path"])))
    dedup_ranked: List[Dict[str, Any]] = []
    seen_paths = set()
    for row in ranked:
        path = str(row["path"])
        if path in seen_paths:
            continue
        seen_paths.add(path)
        dedup_ranked.append(row)

    winner: Dict[str, Any] | None = None
    for row in dedup_ranked:
        if int(row["skills_count"]) >= min_skills:
            winner = row
            break

    resolved_root = winner["path"] if winner else ""
    skills = _discover_skill_names(Path(resolved_root)) if winner else []
    return {
        "schema_version": 1,
        "start": str(start),
        "effective_start": str(effective_start),
        "max_depth": max_depth,
        "min_skills": min_skills,
        "include_ancestor_search": bool(include_ancestor_search),
        "prefer_repo_root": bool(prefer_repo_root),
        "resolved": bool(winner),
        "resolved_root": resolved_root,
        "skills_count": len(skills),
        "skills": skills,
        "seed_roots": [str(seed) for seed in seeds],
        "candidates_considered": dedup_ranked[:80],
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Resolve best skill source root")
    p.add_argument("--start", required=True, help="Start path for discovery")
    p.add_argument("--max-depth", type=int, default=4, help="Directory walk depth")
    p.add_argument("--min-skills", type=int, default=1, help="Minimum discovered skills for a valid root")
    p.add_argument(
        "--no-ancestor-search",
        action="store_true",
        help="Disable ancestor/sibling fallback search and scan only downward from --start",
    )
    p.add_argument(
        "--prefer-repo-root",
        action="store_true",
        help="Prioritize git-backed source repos over installed inventory roots in mixed environments",
    )
    p.add_argument("--strict", action="store_true", help="Exit 2 when no root is resolved")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    start = Path(args.start).expanduser().resolve()

    try:
        report = _resolve(
            start=start,
            max_depth=int(args.max_depth),
            min_skills=int(args.min_skills),
            include_ancestor_search=not bool(args.no_ancestor_search),
            prefer_repo_root=bool(args.prefer_repo_root),
        )
    except SourceResolverError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"start: {report['start']}")
        print(f"resolved: {report['resolved']}")
        print(f"resolved_root: {report['resolved_root']}")
        print(f"skills_count: {report['skills_count']}")

    if args.strict and not report["resolved"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
