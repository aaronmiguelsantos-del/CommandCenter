#!/usr/bin/env python3
"""Deterministic skill semver manager."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
import sys
from typing import Any, Dict, List, Tuple


class VersionError(Exception):
    pass


def _parse_semver(version: str) -> Tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3:
        raise VersionError(f"invalid semver: {version}")
    try:
        major, minor, patch = (int(x) for x in parts)
    except ValueError as err:
        raise VersionError(f"invalid semver: {version}") from err
    return major, minor, patch


def _bump(version: str, part: str) -> str:
    major, minor, patch = _parse_semver(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise VersionError(f"unsupported bump: {part}")


def _load_or_default(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": "0.1.0", "history": []}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise VersionError(f"invalid json in {path}: {err}")
    if not isinstance(obj, dict):
        raise VersionError(f"invalid json object in {path}")
    return obj


def bump_skill_version(
    skills_root: Path,
    skill_name: str,
    bump: str,
    summary: str,
    migration: str,
) -> Dict[str, Any]:
    skill_dir = skills_root / skill_name
    if not skill_dir.exists():
        raise VersionError(f"skill not found: {skill_dir}")
    if not (skill_dir / "SKILL.md").exists():
        raise VersionError(f"not a skill directory: {skill_dir}")

    version_path = skill_dir / "skill_version.json"
    data = _load_or_default(version_path)
    current = str(data.get("version", "0.1.0"))
    nxt = _bump(current, bump)
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "from": current,
        "to": nxt,
        "bump": bump,
        "summary": summary,
        "migration": migration,
        "timestamp_utc": now,
    }
    history = data.get("history", [])
    if not isinstance(history, list):
        history = []
    history.append(record)
    data["version"] = nxt
    data["history"] = history
    data["last_updated_utc"] = now
    version_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    releases_path = skills_root / "data" / "skill_releases.jsonl"
    releases_path.parent.mkdir(parents=True, exist_ok=True)
    releases_path.write_text("", encoding="utf-8") if not releases_path.exists() else None
    release_event = {
        "skill": skill_name,
        "version": nxt,
        "bump": bump,
        "summary": summary,
        "migration": migration,
        "timestamp_utc": now,
    }
    with releases_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(release_event, sort_keys=True) + "\n")

    return {
        "schema_version": 1,
        "skill": skill_name,
        "from_version": current,
        "to_version": nxt,
        "version_file": str(version_path),
        "releases_file": str(releases_path),
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage skill versions deterministically")
    parser.add_argument("--skills-root", required=True, help="Root containing skill folders")
    parser.add_argument("--skill", required=True, help="Skill folder name")
    parser.add_argument("--bump", required=True, choices=["major", "minor", "patch"], help="Semver bump type")
    parser.add_argument("--summary", required=True, help="Release summary")
    parser.add_argument("--migration", default="", help="Migration note")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    skills_root = Path(args.skills_root).expanduser().resolve()
    try:
        result = bump_skill_version(
            skills_root=skills_root,
            skill_name=args.skill,
            bump=args.bump,
            summary=args.summary,
            migration=args.migration,
        )
    except VersionError as err:
        print(f"error: {err}")
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"skill: {result['skill']}")
        print(f"from: {result['from_version']}")
        print(f"to: {result['to_version']}")
        print(f"version_file: {result['version_file']}")
        print(f"releases_file: {result['releases_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
