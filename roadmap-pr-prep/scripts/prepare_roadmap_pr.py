#!/usr/bin/env python3
"""Generate roadmap PR artifacts from local telemetry."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Tuple


class RoadmapPrepError(Exception):
    pass


def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise RoadmapPrepError(f"invalid json file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise RoadmapPrepError(f"json file must be object: {path}")
    return obj


def _summary_markdown(rollup: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# Roadmap Update ({date.today().isoformat()})")
    lines.append("")
    lines.append("## Top Priority Skills")
    for i, skill in enumerate(rollup.get("roadmap_priority", [])[:10], start=1):
        lines.append(f"{i}. {skill}")
    lines.append("")
    lines.append("## Skills Snapshot")
    for row in rollup.get("skills", [])[:20]:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('skill')}: success_rate={row.get('success_rate')} invocations={row.get('invocations')} avg_ms={row.get('avg_duration_ms')}"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def run(repo_root: Path, output_dir: Path) -> Dict[str, Any]:
    releases = repo_root / "data" / "skill_releases.jsonl"
    events = repo_root / "data" / "skill_usage_events.jsonl"
    if not releases.exists():
        fallback_releases = repo_root / "skill-adoption-analytics" / "tests" / "fixtures" / "rollup_releases.jsonl"
        if fallback_releases.exists():
            releases = fallback_releases
    schema = repo_root / "skill-adoption-analytics" / "references" / "roadmap_rollup.schema.json"
    rollup_script = repo_root / "skill-adoption-analytics" / "scripts" / "generate_daily_rollup.py"

    if not releases.exists():
        raise RoadmapPrepError(f"missing releases file: {releases}")
    if not events.exists():
        raise RoadmapPrepError(f"missing events file: {events}")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    rollup_out = output_dir / f"roadmap_rollup_{stamp}.json"
    md_out = output_dir / f"roadmap_summary_{stamp}.md"

    cmd = [
        "python3",
        str(rollup_script),
        "--releases",
        str(releases),
        "--events",
        str(events),
        "--schema",
        str(schema),
        "--output",
        str(rollup_out),
    ]
    rc, out, err = _run(cmd, cwd=repo_root)
    if rc != 0:
        raise RoadmapPrepError(f"rollup generation failed: {err or out}")

    rollup = _load_json(rollup_out)
    md_out.write_text(_summary_markdown(rollup), encoding="utf-8")

    return {
        "schema_version": 1,
        "rollup_path": str(rollup_out),
        "summary_md_path": str(md_out),
        "top_priority": list(rollup.get("roadmap_priority", []))[:10],
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prepare roadmap PR artifacts")
    p.add_argument("--repo-root", required=True, help="Path to repo root")
    p.add_argument("--output-dir", default="", help="Optional output dir (default: data/roadmap)")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else repo_root / "data" / "roadmap"

    try:
        report = run(repo_root, output_dir)
    except RoadmapPrepError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"rollup_path: {report['rollup_path']}")
        print(f"summary_md_path: {report['summary_md_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
