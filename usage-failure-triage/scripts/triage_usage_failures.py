#!/usr/bin/env python3
"""Summarize failure usage telemetry."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple


class TriageError(Exception):
    pass


ERROR_CLASSES = {"input", "validation", "regression", "contract", "git", "runtime"}
DEFAULT_REASON_CODES_REL = Path("skill-adoption-analytics") / "references" / "reason_codes.json"


def _load_schema(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise TriageError(f"invalid schema file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise TriageError(f"schema file must be object: {path}")
    return obj


def _load_reason_code_map(path: Path) -> Dict[str, str]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise TriageError(f"invalid reason-code file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise TriageError(f"reason-code file must be object: {path}")
    reason_rows = obj.get("reason_codes")
    if not isinstance(reason_rows, list):
        raise TriageError(f"reason-code file missing reason_codes[]: {path}")
    out: Dict[str, str] = {}
    for row in reason_rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "")).strip()
        if not code:
            continue
        error_class = str(row.get("error_class", "")).strip()
        if error_class and error_class not in ERROR_CLASSES:
            raise TriageError(f"invalid error_class '{error_class}' in reason-code file for code {code}")
        out[code] = error_class
    if not out:
        raise TriageError(f"reason-code file contains no valid reason codes: {path}")
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


def _parse_fail_on(raw_values: List[str], reason_code_map: Dict[str, str]) -> List[Tuple[str, int]]:
    parsed: List[Tuple[str, int]] = []
    seen = set()
    for raw in raw_values:
        for token in raw.split(","):
            item = token.strip()
            if not item:
                continue
            if ":" not in item:
                raise TriageError(f"invalid --fail-on value (expected reason:max): {item}")
            reason, max_raw = item.split(":", 1)
            reason = reason.strip()
            max_raw = max_raw.strip()
            if not reason:
                raise TriageError(f"invalid --fail-on reason: {item}")
            if reason not in reason_code_map:
                raise TriageError(f"invalid --fail-on reason_code (not in dictionary): {reason}")
            if reason in seen:
                raise TriageError(f"duplicate --fail-on reason: {reason}")
            try:
                max_allowed = int(max_raw)
            except ValueError as err:
                raise TriageError(f"invalid --fail-on max value for {reason}: {max_raw}") from err
            if max_allowed < 0:
                raise TriageError(f"--fail-on max must be >= 0 for {reason}")
            seen.add(reason)
            parsed.append((reason, max_allowed))
    return parsed


def _parse_fail_on_skill(raw_values: List[str]) -> List[Tuple[str, int]]:
    parsed: List[Tuple[str, int]] = []
    seen = set()
    for raw in raw_values:
        for token in raw.split(","):
            item = token.strip()
            if not item:
                continue
            if ":" not in item:
                raise TriageError(f"invalid --fail-on-skill value (expected skill:max): {item}")
            skill, max_raw = item.split(":", 1)
            skill = skill.strip()
            max_raw = max_raw.strip()
            if not skill:
                raise TriageError(f"invalid --fail-on-skill skill: {item}")
            if skill in seen:
                raise TriageError(f"duplicate --fail-on-skill skill: {skill}")
            try:
                max_allowed = int(max_raw)
            except ValueError as err:
                raise TriageError(f"invalid --fail-on-skill max value for {skill}: {max_raw}") from err
            if max_allowed < 0:
                raise TriageError(f"--fail-on-skill max must be >= 0 for {skill}")
            seen.add(skill)
            parsed.append((skill, max_allowed))
    return parsed


def _load_jsonl(
    path: Path,
    schema: Dict[str, Any],
    reason_code_map: Dict[str, str],
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
        row_errors = _validate_event(schema, obj, reason_code_map)
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
        "by_skill": [{"skill": k, "count": v} for k, v in top_skills],
        "top_failed_skills": [{"skill": k, "count": v} for k, v in top_skills[:top]],
    }


def _evaluate_fail_on(
    report: Dict[str, Any],
    fail_on: List[Tuple[str, int]],
    fail_on_total: int | None,
    fail_on_skill: List[Tuple[str, int]],
) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for row in report.get("by_reason_code", []):
        if not isinstance(row, dict):
            continue
        reason = row.get("reason_code")
        count = row.get("count")
        if isinstance(reason, str) and isinstance(count, int):
            counts[reason] = count

    skill_counts: Dict[str, int] = {}
    for row in report.get("by_skill", []):
        if not isinstance(row, dict):
            continue
        skill = row.get("skill")
        count = row.get("count")
        if isinstance(skill, str) and isinstance(count, int):
            skill_counts[skill] = count

    violations: List[Dict[str, Any]] = []
    reason_thresholds: List[Dict[str, Any]] = []
    skill_thresholds: List[Dict[str, Any]] = []
    for reason, max_allowed in fail_on:
        count = int(counts.get(reason, 0))
        reason_thresholds.append({"reason_code": reason, "max": max_allowed})
        if count > max_allowed:
            violations.append(
                {
                    "type": "reason_code",
                    "reason_code": reason,
                    "count": count,
                    "max": max_allowed,
                }
            )
    for skill, max_allowed in fail_on_skill:
        count = int(skill_counts.get(skill, 0))
        skill_thresholds.append({"skill": skill, "max": max_allowed})
        if count > max_allowed:
            violations.append(
                {
                    "type": "skill",
                    "skill": skill,
                    "count": count,
                    "max": max_allowed,
                }
            )
    total_threshold: Dict[str, Any] | None = None
    if fail_on_total is not None:
        total_count = int(report.get("failures_total", 0))
        total_threshold = {"max": fail_on_total}
        if total_count > fail_on_total:
            violations.append(
                {
                    "type": "total",
                    "count": total_count,
                    "max": fail_on_total,
                }
            )

    return {
        "passed": len(violations) == 0,
        "thresholds": {
            "reason_codes": reason_thresholds,
            "skills": skill_thresholds,
            "total": total_threshold,
        },
        "violations": violations,
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
    fail_on = report.get("fail_on", {})
    if isinstance(fail_on, dict) and fail_on.get("thresholds"):
        lines.append("## Threshold Gate")
        lines.append(f"- passed: {bool(fail_on.get('passed', True))}")
        for row in fail_on.get("violations", []):
            if isinstance(row, dict):
                if row.get("type") == "reason_code":
                    lines.append(
                        f"- violation: reason_code={row.get('reason_code')} count={row.get('count')} max={row.get('max')}"
                    )
                elif row.get("type") == "skill":
                    lines.append(f"- violation: skill={row.get('skill')} count={row.get('count')} max={row.get('max')}")
                elif row.get("type") == "total":
                    lines.append(f"- violation: total_failures={row.get('count')} max={row.get('max')}")
                else:
                    lines.append(f"- violation: {row}")
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
        "--fail-on",
        action="append",
        default=[],
        help="Reason threshold(s) as reason_code:max_failures; repeat or comma-separate for CI gating",
    )
    p.add_argument("--fail-on-total", type=int, default=-1, help="Max total failures allowed before exiting 2")
    p.add_argument(
        "--fail-on-skill",
        action="append",
        default=[],
        help="Skill threshold(s) as skill:max_failures; repeat or comma-separate for CI gating",
    )
    p.add_argument(
        "--schema",
        default="",
        help="Optional usage schema path (defaults to ../skill-adoption-analytics/references/skill_usage_events.schema.json)",
    )
    p.add_argument(
        "--reason-codes-dict",
        default="",
        help="Optional reason-code dictionary path (defaults to ../skill-adoption-analytics/references/reason_codes.json)",
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
    if args.reason_codes_dict:
        reason_codes_path = Path(args.reason_codes_dict).expanduser().resolve()
    else:
        reason_codes_path = Path(__file__).resolve().parents[2] / DEFAULT_REASON_CODES_REL

    try:
        schema = _load_schema(schema_path)
        reason_code_map = _load_reason_code_map(reason_codes_path)
        reason_codes_filter = _parse_csv(args.reason_codes)
        for reason in reason_codes_filter:
            if reason not in reason_code_map:
                raise TriageError(f"--reason-codes contains unknown reason_code: {reason}")
        rows = _load_jsonl(
            events_path,
            schema=schema,
            reason_code_map=reason_code_map,
            since_days=max(0, int(args.since_days)),
            sources=_parse_csv(args.sources),
            reason_codes=reason_codes_filter,
        )
        report = _build_report(rows, top=max(1, int(args.top)))
        fail_on = _parse_fail_on(args.fail_on, reason_code_map=reason_code_map)
        fail_on_total = int(args.fail_on_total)
        if fail_on_total < -1:
            raise TriageError("--fail-on-total must be -1 or >= 0")
        report["fail_on"] = _evaluate_fail_on(
            report,
            fail_on,
            fail_on_total=None if fail_on_total == -1 else fail_on_total,
            fail_on_skill=_parse_fail_on_skill(args.fail_on_skill),
        )
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
    fail_on_report = report.get("fail_on", {})
    if isinstance(fail_on_report, dict) and fail_on_report.get("passed") is False:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
