#!/usr/bin/env python3
"""Summarize failure usage telemetry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List


class TriageError(Exception):
    pass


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise TriageError(f"events file not found: {path}")
    rows: List[Dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception as err:
            raise TriageError(f"invalid json line {i}: {err}") from err
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _build_report(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    failures = [r for r in rows if r.get("status") == "failure"]
    by_reason: Dict[str, int] = {}
    by_error_class: Dict[str, int] = {}
    by_skill: Dict[str, int] = {}

    for row in failures:
        reason = str(row.get("reason_code", "unknown"))
        error_class = str(row.get("error_class", "unknown"))
        skill = str(row.get("skill", "unknown"))
        by_reason[reason] = by_reason.get(reason, 0) + 1
        by_error_class[error_class] = by_error_class.get(error_class, 0) + 1
        by_skill[skill] = by_skill.get(skill, 0) + 1

    top_reasons = sorted(by_reason.items(), key=lambda kv: (-kv[1], kv[0]))
    top_skills = sorted(by_skill.items(), key=lambda kv: (-kv[1], kv[0]))

    return {
        "schema_version": 1,
        "events_total": len(rows),
        "failures_total": len(failures),
        "by_reason_code": [{"reason_code": k, "count": v} for k, v in top_reasons],
        "by_error_class": [{"error_class": k, "count": v} for k, v in sorted(by_error_class.items(), key=lambda kv: (-kv[1], kv[0]))],
        "top_failed_skills": [{"skill": k, "count": v} for k, v in top_skills[:20]],
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Triage failure usage events")
    p.add_argument("--events", required=True, help="Path to skill_usage_events.jsonl")
    p.add_argument("--output", default="", help="Optional output JSON path")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    events_path = Path(args.events).expanduser().resolve()
    try:
        rows = _load_jsonl(events_path)
        report = _build_report(rows)
    except TriageError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json or not args.output:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
