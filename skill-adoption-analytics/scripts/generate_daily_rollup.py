#!/usr/bin/env python3
"""Generate daily roadmap rollup from releases and usage analytics."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List


class RollupError(Exception):
    pass


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise RollupError(f"file not found: {path}")
    rows: List[Dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception as err:
            raise RollupError(f"invalid json at line {i} in {path}: {err}") from err
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _build_usage_index(events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for e in events:
        skill = e.get("skill")
        status = e.get("status")
        duration = e.get("duration_ms")
        if not isinstance(skill, str) or not isinstance(duration, int):
            continue
        if status not in {"success", "failure"}:
            continue
        bucket = idx.setdefault(skill, {"invocations": 0, "successes": 0, "failures": 0, "dur_sum": 0})
        bucket["invocations"] += 1
        bucket["dur_sum"] += duration
        if status == "success":
            bucket["successes"] += 1
        else:
            bucket["failures"] += 1
    for skill, bucket in idx.items():
        inv = max(1, int(bucket["invocations"]))
        bucket["success_rate"] = round(bucket["successes"] / inv, 4)
        bucket["avg_duration_ms"] = round(bucket["dur_sum"] / inv, 2)
    return idx


def _latest_release_by_skill(releases: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in releases:
        skill = row.get("skill")
        ts = row.get("timestamp_utc")
        if not isinstance(skill, str) or not isinstance(ts, str):
            continue
        prev = latest.get(skill)
        if prev is None or str(prev.get("timestamp_utc", "")) < ts:
            latest[skill] = row
    return latest


def build_rollup(releases: List[Dict[str, Any]], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    usage = _build_usage_index(events)
    latest_rel = _latest_release_by_skill(releases)
    skills = sorted(set(list(usage.keys()) + list(latest_rel.keys())))
    rows: List[Dict[str, Any]] = []
    for skill in skills:
        u = usage.get(skill, {})
        r = latest_rel.get(skill, {})
        rows.append(
            {
                "skill": skill,
                "latest_version": r.get("version"),
                "latest_bump": r.get("bump"),
                "latest_release_utc": r.get("timestamp_utc"),
                "latest_summary": r.get("summary"),
                "invocations": int(u.get("invocations", 0)),
                "success_rate": float(u.get("success_rate", 0.0)),
                "avg_duration_ms": float(u.get("avg_duration_ms", 0.0)),
            }
        )

    roadmap_priority = sorted(
        rows,
        key=lambda x: (x["success_rate"], -x["invocations"], x["avg_duration_ms"]),
    )
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "skills": rows,
        "roadmap_priority": [r["skill"] for r in roadmap_priority[:20]],
    }


def _load_schema(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise RollupError(f"invalid schema file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise RollupError(f"schema file must be object: {path}")
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
    parser = argparse.ArgumentParser(description="Generate daily skill roadmap rollup")
    parser.add_argument("--releases", required=True, help="Path to data/skill_releases.jsonl")
    parser.add_argument("--events", required=True, help="Path to data/skill_usage_events.jsonl")
    parser.add_argument("--output", required=True, help="Path to write rollup JSON")
    parser.add_argument(
        "--schema",
        default="",
        help="Optional rollup schema path (defaults to references/roadmap_rollup.schema.json)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    releases_path = Path(args.releases).expanduser().resolve()
    events_path = Path(args.events).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if args.schema:
        schema_path = Path(args.schema).expanduser().resolve()
    else:
        schema_path = Path(__file__).resolve().parents[1] / "references" / "roadmap_rollup.schema.json"
    try:
        releases = _load_jsonl(releases_path)
        events = _load_jsonl(events_path)
        report = build_rollup(releases, events)
        schema = _load_schema(schema_path)
        validation_errors = _validate_report(report, schema)
        if validation_errors:
            raise RollupError("schema validation failed: " + "; ".join(validation_errors))
    except RollupError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
