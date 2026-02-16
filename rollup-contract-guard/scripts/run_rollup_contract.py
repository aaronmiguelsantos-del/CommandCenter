#!/usr/bin/env python3
"""Wrapper for skill-adoption-analytics rollup contract check."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from typing import List


def _run(cmd: List[str], cwd: Path) -> int:
    proc = subprocess.run(cmd, cwd=cwd, check=False)
    return int(proc.returncode)


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run rollup contract check")
    p.add_argument("--repo-root", required=True, help="Path to repo root")
    p.add_argument("--releases", default="", help="Optional releases JSONL path")
    p.add_argument("--events", default="", help="Optional events JSONL path")
    p.add_argument("--schema", default="", help="Optional schema JSON path")
    p.add_argument("--expected", default="", help="Optional expected JSON path")
    p.add_argument("--output", default="", help="Optional generated output JSON path")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    root = Path(args.repo_root).expanduser().resolve()
    checker = root / "skill-adoption-analytics" / "scripts" / "check_rollup_contract.py"

    releases = Path(args.releases).expanduser().resolve() if args.releases else root / "skill-adoption-analytics" / "tests" / "fixtures" / "rollup_releases.jsonl"
    events = Path(args.events).expanduser().resolve() if args.events else root / "skill-adoption-analytics" / "tests" / "fixtures" / "rollup_events.jsonl"
    schema = Path(args.schema).expanduser().resolve() if args.schema else root / "skill-adoption-analytics" / "references" / "roadmap_rollup.schema.json"
    expected = Path(args.expected).expanduser().resolve() if args.expected else root / "skill-adoption-analytics" / "tests" / "golden" / "roadmap_rollup.expected.json"
    output = Path(args.output).expanduser().resolve() if args.output else root / "data" / "rollup_contract.actual.json"

    cmd = [
        "python3",
        str(checker),
        "--releases",
        str(releases),
        "--events",
        str(events),
        "--schema",
        str(schema),
        "--expected",
        str(expected),
        "--output",
        str(output),
    ]
    return _run(cmd, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
