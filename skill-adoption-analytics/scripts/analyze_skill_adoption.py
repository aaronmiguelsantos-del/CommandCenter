#!/usr/bin/env python3
"""Analyze skill adoption from local JSONL events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List


class AnalyticsError(Exception):
    pass


def _percentile(values: List[int], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * p))
    idx = max(0, min(idx, len(ordered) - 1))
    return float(ordered[idx])


def _load_events(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise AnalyticsError(f"events file not found: {path}")
    events: List[Dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except Exception as err:
            raise AnalyticsError(f"invalid json line {i}: {err}") from err
        if isinstance(obj, dict):
            events.append(obj)
    return events


def _build_report(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_skill: Dict[str, Dict[str, Any]] = {}
    ignored = 0

    for e in events:
        skill = e.get("skill")
        status = e.get("status")
        duration = e.get("duration_ms")
        if not isinstance(skill, str) or not skill.strip():
            ignored += 1
            continue
        if status not in {"success", "failure"}:
            ignored += 1
            continue
        if not isinstance(duration, int) or duration < 0:
            ignored += 1
            continue

        bucket = by_skill.setdefault(
            skill,
            {"invocations": 0, "successes": 0, "failures": 0, "durations": []},
        )
        bucket["invocations"] += 1
        bucket["durations"].append(duration)
        if status == "success":
            bucket["successes"] += 1
        else:
            bucket["failures"] += 1

    skill_rows: List[Dict[str, Any]] = []
    for skill, bucket in sorted(by_skill.items()):
        invocations = int(bucket["invocations"])
        successes = int(bucket["successes"])
        failures = int(bucket["failures"])
        durations = list(bucket["durations"])
        success_rate = (successes / invocations) if invocations else 0.0
        avg_ms = (sum(durations) / invocations) if invocations else 0.0
        p95_ms = _percentile(durations, 0.95)
        # Higher is better: prioritize reliable + frequent + fast skills.
        roi_score = round((success_rate * 100.0) + min(invocations, 100) - (avg_ms / 1000.0), 3)
        skill_rows.append(
            {
                "skill": skill,
                "invocations": invocations,
                "successes": successes,
                "failures": failures,
                "success_rate": round(success_rate, 4),
                "avg_duration_ms": round(avg_ms, 2),
                "p95_duration_ms": round(p95_ms, 2),
                "roi_score": roi_score,
            }
        )

    ranked = sorted(skill_rows, key=lambda r: (r["roi_score"], r["invocations"]), reverse=True)
    improvement_priority = sorted(
        skill_rows,
        key=lambda r: (r["success_rate"], -r["invocations"], r["avg_duration_ms"]),
    )
    return {
        "schema_version": 1,
        "events_total": len(events),
        "events_ignored": ignored,
        "skills": ranked,
        "improvement_priority": [row["skill"] for row in improvement_priority[:10]],
    }


def _load_schema(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise AnalyticsError(f"invalid schema file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise AnalyticsError(f"schema file must be object: {path}")
    return obj


def _validate_report(report: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = schema.get("required", [])
    props = schema.get("properties", {})
    if not isinstance(required, list) or not isinstance(props, dict):
        return ["invalid schema shape"]

    type_map = {"integer": int, "number": (int, float), "array": list, "string": str}
    for key in required:
        if key not in report:
            errors.append(f"missing required key: {key}")
    for key, rule in props.items():
        if key not in report or not isinstance(rule, dict):
            continue
        expected = rule.get("type")
        py_t = type_map.get(expected)
        if py_t and not isinstance(report[key], py_t):
            errors.append(f"invalid type for {key}: expected {expected}")
    return errors


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze skill adoption JSONL events")
    parser.add_argument("--events", required=True, help="Path to skill_usage_events.jsonl")
    parser.add_argument("--output", default="", help="Optional output JSON file path")
    parser.add_argument(
        "--schema",
        default="",
        help="Optional report schema path (defaults to references/adoption_report.schema.json)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    events_path = Path(args.events).expanduser().resolve()
    if args.schema:
        schema_path = Path(args.schema).expanduser().resolve()
    else:
        schema_path = Path(__file__).resolve().parents[1] / "references" / "adoption_report.schema.json"
    try:
        events = _load_events(events_path)
        report = _build_report(events)
        schema = _load_schema(schema_path)
        validation_errors = _validate_report(report, schema)
        if validation_errors:
            raise AnalyticsError("schema validation failed: " + "; ".join(validation_errors))
    except AnalyticsError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json or not args.output:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
