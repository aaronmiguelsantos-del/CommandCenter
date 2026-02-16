#!/usr/bin/env python3
"""Summarize failure usage telemetry."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List


class TriageError(Exception):
    pass


def _load_schema(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise TriageError(f"invalid schema file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise TriageError(f"schema file must be object: {path}")
    return obj


def _validate_event(schema: Dict[str, Any], row: Dict[str, Any]) -> List[str]:
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
    return errors


def _parse_timestamp(ts: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_csv(raw: str) -> List[str]:
    seen = set()
    out: List[str] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _load_jsonl(
    path: Path,
    schema: Dict[str, Any],
    since_days: int,
    sources: List[str],
    reason_codes: List[str],
) -> List[Dict[str, Any]]:
    if not path.exists():
        raise TriageError(f"events file not found: {path}")
    cutoff: datetime | None = None
    if since_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    rows: List[Dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception as err:
            raise TriageError(f"invalid json line {i}: {err}") from err
        if not isinstance(obj, dict):
            raise TriageError(f"invalid event line {i}: expected object")
        row_errors = _validate_event(schema, obj)
        if row_errors:
            raise TriageError(f"event schema validation failed at line {i}: {'; '.join(row_errors)}")
        if cutoff is not None:
            ts = _parse_timestamp(str(obj.get("timestamp_utc", "")))
            if ts is None or ts < cutoff:
                continue
        if sources and str(obj.get("source", "")) not in sources:
            continue
        if reason_codes and str(obj.get("reason_code", "")) not in reason_codes:
            continue
        rows.append(obj)
    return rows


def _build_report(rows: List[Dict[str, Any]], top: int) -> Dict[str, Any]:
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
        "by_error_class": [
            {"error_class": k, "count": v}
            for k, v in sorted(by_error_class.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "top_failed_skills": [{"skill": k, "count": v} for k, v in top_skills[:top]],
    }


def _to_markdown(report: Dict[str, Any]) -> str:
    lines = []
    lines.append("# Usage Failure Triage")
    lines.append("")
    lines.append(f"- events_total: {report.get('events_total')}")
    lines.append(f"- failures_total: {report.get('failures_total')}")
    lines.append("")
    lines.append("## Top Reason Codes")
    for row in report.get("by_reason_code", [])[:10]:
        if isinstance(row, dict):
            lines.append(f"- {row.get('reason_code')}: {row.get('count')}")
    lines.append("")
    lines.append("## Top Failed Skills")
    for row in report.get("top_failed_skills", [])[:10]:
        if isinstance(row, dict):
            lines.append(f"- {row.get('skill')}: {row.get('count')}")
    lines.append("")
    return "\n".join(lines) + "\n"


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Triage failure usage events")
    p.add_argument("--events", required=True, help="Path to skill_usage_events.jsonl")
    p.add_argument("--output", default="", help="Optional output JSON path")
    p.add_argument("--markdown-output", default="", help="Optional markdown summary path")
    p.add_argument("--since-days", type=int, default=0, help="Include only events from last N days (0=all)")
    p.add_argument("--top", type=int, default=20, help="Max top failed skills rows")
    p.add_argument("--sources", default="", help="Optional CSV list to filter source values")
    p.add_argument("--reason-codes", default="", help="Optional CSV list to filter reason_code values")
    p.add_argument(
        "--schema",
        default="",
        help="Optional usage schema path (defaults to ../skill-adoption-analytics/references/skill_usage_events.schema.json)",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    events_path = Path(args.events).expanduser().resolve()
    if args.schema:
        schema_path = Path(args.schema).expanduser().resolve()
    else:
        schema_path = Path(__file__).resolve().parents[2] / "skill-adoption-analytics" / "references" / "skill_usage_events.schema.json"

    try:
        schema = _load_schema(schema_path)
        rows = _load_jsonl(
            events_path,
            schema=schema,
            since_days=max(0, int(args.since_days)),
            sources=_parse_csv(args.sources),
            reason_codes=_parse_csv(args.reason_codes),
        )
        report = _build_report(rows, top=max(1, int(args.top)))
    except TriageError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.markdown_output:
        md_path = Path(args.markdown_output).expanduser().resolve()
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(_to_markdown(report), encoding="utf-8")

    if args.json or not args.output:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
