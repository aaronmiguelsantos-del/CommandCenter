#!/usr/bin/env python3
"""Resolve requested skill names against discovered skills with alias and suggestion support."""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Sequence


class NameResolverError(Exception):
    pass


def _normalize_name(raw: str) -> str:
    text = raw.strip().lower().replace("_", "-").replace(" ", "-")
    text = re.sub(r"-+", "-", text)
    return text


def _parse_csv(raw: str) -> List[str]:
    seen = set()
    out: List[str] = []
    for token in raw.split(","):
        value = token.strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _is_skill_dir(path: Path) -> bool:
    return (path / "SKILL.md").exists() and (path / "agents" / "openai.yaml").exists()


def _discover_skill_names(source_root: Path) -> List[str]:
    if not source_root.exists() or not source_root.is_dir():
        raise NameResolverError(f"source root does not exist: {source_root}")
    names: List[str] = []
    for child in sorted(source_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if _is_skill_dir(child):
            names.append(child.name)
    return names


def _load_alias_map(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise NameResolverError(f"invalid alias file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise NameResolverError(f"alias file must be object: {path}")
    rows = obj.get("aliases", [])
    if not isinstance(rows, list):
        raise NameResolverError(f"alias file missing aliases[]: {path}")
    result: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        alias = _normalize_name(str(row.get("alias", "")))
        skill = str(row.get("skill", "")).strip()
        if not alias or not skill:
            continue
        result[alias] = skill
    return result


def _build_suggestions(value: str, available: Sequence[str]) -> List[str]:
    normalized = _normalize_name(value)
    prefix = [name for name in available if name.startswith(normalized)][:3]
    contains = [name for name in available if normalized in name and name not in prefix][:3]
    fuzzy = difflib.get_close_matches(normalized, list(available), n=4, cutoff=0.55)
    out: List[str] = []
    for name in prefix + contains + fuzzy:
        if name not in out:
            out.append(name)
    return out[:4]


def _resolve(requested: Sequence[str], available: Sequence[str], alias_map: Dict[str, str]) -> Dict[str, Any]:
    available_set = set(available)
    normalized_lookup = {_normalize_name(name): name for name in available}

    resolved: List[str] = []
    aliases_applied: List[Dict[str, str]] = []
    unknown: List[Dict[str, Any]] = []

    for raw in requested:
        normalized = _normalize_name(raw)
        candidate = ""

        if raw in available_set:
            candidate = raw
        elif normalized in normalized_lookup:
            candidate = normalized_lookup[normalized]
        else:
            alias_target = alias_map.get(normalized, "")
            if alias_target and alias_target in available_set:
                candidate = alias_target
                aliases_applied.append(
                    {
                        "input": raw,
                        "alias": normalized,
                        "resolved": alias_target,
                    }
                )
            elif alias_target:
                unknown.append(
                    {
                        "input": raw,
                        "normalized": normalized,
                        "alias_target": alias_target,
                        "suggestions": _build_suggestions(raw, available),
                    }
                )
                continue

        if not candidate:
            unknown.append(
                {
                    "input": raw,
                    "normalized": normalized,
                    "suggestions": _build_suggestions(raw, available),
                }
            )
            continue

        if candidate not in resolved:
            resolved.append(candidate)

    return {
        "resolved": resolved,
        "unknown": unknown,
        "aliases_applied": aliases_applied,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Resolve skill names with alias and typo suggestions")
    p.add_argument("--source-root", required=True, help="Path containing skill folders")
    p.add_argument("--requested", required=True, help="CSV list of requested skill names")
    p.add_argument(
        "--aliases",
        default="",
        help="Optional alias dictionary JSON path (defaults to skill-name-resolver/references/skill_name_aliases.json)",
    )
    p.add_argument("--strict", action="store_true", help="Exit 2 when unknown skill names remain")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    source_root = Path(args.source_root).expanduser().resolve()
    if args.aliases:
        aliases_path = Path(args.aliases).expanduser().resolve()
    else:
        aliases_path = Path(__file__).resolve().parents[1] / "references" / "skill_name_aliases.json"

    try:
        requested = _parse_csv(str(args.requested))
        available = _discover_skill_names(source_root)
        alias_map = _load_alias_map(aliases_path)
        resolved = _resolve(requested, available, alias_map)
    except NameResolverError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    report = {
        "schema_version": 1,
        "source_root": str(source_root),
        "available_count": len(available),
        "available": available,
        "requested": requested,
        "resolved": resolved["resolved"],
        "unknown": resolved["unknown"],
        "aliases_applied": resolved["aliases_applied"],
        "ok": len(resolved["unknown"]) == 0,
        "strict": bool(args.strict),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"source_root: {report['source_root']}")
        print(f"available_count: {report['available_count']}")
        print(f"requested: {','.join(requested)}")
        print(f"resolved: {','.join(report['resolved'])}")
        if report["unknown"]:
            print("unknown:")
            for row in report["unknown"]:
                suggestions = ",".join(row.get("suggestions", []))
                print(f"- {row.get('input')}: suggestions={suggestions}")

    if args.strict and report["unknown"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
