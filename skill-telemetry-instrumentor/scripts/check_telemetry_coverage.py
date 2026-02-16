#!/usr/bin/env python3
"""Fail CI when required skills have no recent telemetry events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List


ERROR_CLASSES = {"input", "validation", "regression", "contract", "git", "runtime"}


class CoverageError(Exception):
    pass


def _parse_csv(raw: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise CoverageError(f"invalid json file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise CoverageError(f"json file must contain an object: {path}")
    return obj


def _load_reason_code_map(path: Path) -> Dict[str, str]:
    obj = _load_json(path)
    rows = obj.get("reason_codes")
    if not isinstance(rows, list):
        raise CoverageError(f"reason-code file missing reason_codes[]: {path}")
    out: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "")).strip()
        if not code:
            continue
        error_class = str(row.get("error_class", "")).strip()
        if error_class and error_class not in ERROR_CLASSES:
            raise CoverageError(f"invalid error_class '{error_class}' for reason_code '{code}'")
        out[code] = error_class
    if not out:
        raise CoverageError(f"reason-code file contains no valid codes: {path}")
    return out


def _validate_event(schema: Dict[str, Any], row: Dict[str, Any], reason_code_map: Dict[str, str]) -> List[str]:
    errors: List[str] = []
    required = schema.get("required", [])
    props = schema.get("properties", {})
    if not isinstance(required, list) or not isinstance(props, dict):
        return ["invalid schema shape"]

    type_map = {"integer": int, "number": (int, float), "array": list, "string": str, "object": dict}
    for key in required:
        if key not in row:
            errors.append(f"missing required key: {key}")
    for key, rule in props.items():
        if key not in row or not isinstance(rule, dict):
            continue
        expected = rule.get("type")
        py_t = type_map.get(expected)
        if py_t and not isinstance(row[key], py_t):
            errors.append(f"invalid type for {key}: expected {expected}")
            continue
        enum = rule.get("enum")
        if isinstance(enum, list) and row[key] not in enum:
            errors.append(f"invalid value for {key}: {row[key]}")

    reason = row.get("reason_code")
    if isinstance(reason, str) and reason:
        if reason not in reason_code_map:
            errors.append(f"unknown reason_code: {reason}")
        expected_error_class = reason_code_map.get(reason, "")
        actual_error_class = row.get("error_class")
        if expected_error_class and isinstance(actual_error_class, str) and actual_error_class:
            if actual_error_class != expected_error_class:
                errors.append(
                    f"error_class mismatch for reason_code {reason}: expected {expected_error_class}, got {actual_error_class}"
                )
    return errors


def _load_events(path: Path, schema: Dict[str, Any], reason_code_map: Dict[str, str]) -> List[Dict[str, Any]]:
    if not path.exists():
        raise CoverageError(f"events file not found: {path}")
    rows: List[Dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception as err:
            raise CoverageError(f"invalid json line {i}: {err}") from err
        if not isinstance(obj, dict):
            raise CoverageError(f"invalid event row at line {i}: expected object")
        row_errors = _validate_event(schema, obj, reason_code_map)
        if row_errors:
            raise CoverageError(f"event schema validation failed at line {i}: {'; '.join(row_errors)}")
        rows.append(obj)
    return rows


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check telemetry coverage for key skills")
    p.add_argument("--events", required=True, help="Path to skill_usage_events.jsonl")
    p.add_argument("--skills", required=True, help="CSV list of required skills")
    p.add_argument("--last-n", type=int, default=20, help="Only inspect the most recent N events (0=all)")
    p.add_argument("--min-events-per-skill", type=int, default=1, help="Minimum required events per required skill")
    p.add_argument(
        "--schema",
        default="",
        help="Optional usage schema path (defaults to skill-adoption-analytics/references/skill_usage_events.schema.json)",
    )
    p.add_argument(
        "--reason-codes",
        default="",
        help="Optional reason-code dictionary path (defaults to skill-adoption-analytics/references/reason_codes.json)",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON report")
    p.add_argument("--strict", action="store_true", help="Exit 2 when coverage check fails")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    events_path = Path(args.events).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    schema_path = (
        Path(args.schema).expanduser().resolve()
        if args.schema
        else repo_root / "skill-adoption-analytics" / "references" / "skill_usage_events.schema.json"
    )
    reason_codes_path = (
        Path(args.reason_codes).expanduser().resolve()
        if args.reason_codes
        else repo_root / "skill-adoption-analytics" / "references" / "reason_codes.json"
    )

    try:
        required_skills = _parse_csv(args.skills)
        if not required_skills:
            raise CoverageError("--skills must include at least one skill")
        min_events = int(args.min_events_per_skill)
        if min_events < 1:
            raise CoverageError("--min-events-per-skill must be >= 1")
        last_n = int(args.last_n)
        if last_n < 0:
            raise CoverageError("--last-n must be >= 0")

        schema = _load_json(schema_path)
        reason_code_map = _load_reason_code_map(reason_codes_path)
        events = _load_events(events_path, schema=schema, reason_code_map=reason_code_map)
        window = events if last_n == 0 else events[-last_n:]
    except CoverageError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    counts: Dict[str, int] = {skill: 0 for skill in required_skills}
    for row in window:
        skill = row.get("skill")
        if isinstance(skill, str) and skill in counts:
            counts[skill] += 1

    rows = [
        {
            "skill": skill,
            "count": counts[skill],
            "min_required": min_events,
            "covered": counts[skill] >= min_events,
        }
        for skill in required_skills
    ]
    missing = [row["skill"] for row in rows if not row["covered"]]
    report = {
        "schema_version": 1,
        "events_path": str(events_path),
        "last_n": last_n,
        "events_total": len(events),
        "events_window": len(window),
        "min_events_per_skill": min_events,
        "required_skills": required_skills,
        "coverage": rows,
        "covered": len(missing) == 0,
        "missing_skills": missing,
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"covered: {report['covered']}")
        for row in rows:
            print(f"- {row['skill']}: {row['count']}/{row['min_required']}")
    if args.strict and not report["covered"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
