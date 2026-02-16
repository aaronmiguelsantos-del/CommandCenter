#!/usr/bin/env python3
"""Run a command and append schema-validated skill usage telemetry."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List, Tuple


ERROR_CLASSES = {"input", "validation", "regression", "contract", "git", "runtime"}
DEFAULT_REASON_CODES_REL = Path("skill-adoption-analytics") / "references" / "reason_codes.json"


class TelemetryError(Exception):
    pass


def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except Exception as err:
        return 99, "", f"RUNNER_ERROR: {err}"
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _load_schema(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise TelemetryError(f"invalid schema file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise TelemetryError(f"schema must be object: {path}")
    return obj


def _load_reason_code_map(path: Path) -> Dict[str, str]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise TelemetryError(f"invalid reason-code file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise TelemetryError(f"reason-code file must be object: {path}")
    rows = obj.get("reason_codes")
    if not isinstance(rows, list):
        raise TelemetryError(f"reason-code file missing reason_codes[]: {path}")
    result: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "")).strip()
        if not code:
            continue
        error_class = str(row.get("error_class", "")).strip()
        if error_class and error_class not in ERROR_CLASSES:
            raise TelemetryError(f"invalid error_class '{error_class}' in reason-code file for code {code}")
        result[code] = error_class
    if not result:
        raise TelemetryError(f"reason-code file contains no valid codes: {path}")
    return result


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


def _validate_existing_events(events_path: Path, schema: Dict[str, Any], reason_code_map: Dict[str, str]) -> None:
    if not events_path.exists():
        return
    for i, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception as err:
            raise TelemetryError(f"invalid existing JSONL row at line {i}: {err}") from err
        if not isinstance(obj, dict):
            raise TelemetryError(f"invalid existing JSONL row at line {i}: expected object")
        row_errors = _validate_event(schema, obj, reason_code_map)
        if row_errors:
            raise TelemetryError(f"existing JSONL row at line {i} failed schema: {'; '.join(row_errors)}")


def _parse_wrapped_command(command_args: List[str]) -> List[str]:
    if command_args and command_args[0] == "--":
        command_args = command_args[1:]
    if not command_args:
        raise TelemetryError("wrapped command is required; pass it after --")
    return command_args


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Instrument a command with skill usage telemetry")
    p.add_argument("--events", required=True, help="Path to skill_usage_events.jsonl")
    p.add_argument(
        "--schema",
        default="",
        help="Optional schema path (defaults to skill-adoption-analytics/references/skill_usage_events.schema.json)",
    )
    p.add_argument("--skill", required=True, help="Skill name for emitted usage row")
    p.add_argument("--source", default="skill-telemetry-instrumentor", help="Event source label")
    p.add_argument("--context", default="run", help="Event context label")
    p.add_argument("--reason-code", default="", help="Failure reason code override")
    p.add_argument("--reason-detail", default="", help="Failure reason detail override")
    p.add_argument("--error-class", default="", help="Failure error class override")
    p.add_argument(
        "--reason-codes",
        default="",
        help="Optional reason-code dictionary path (defaults to skill-adoption-analytics/references/reason_codes.json)",
    )
    p.add_argument("--cwd", default="", help="Optional working directory for wrapped command")
    p.add_argument("--stdout-file", default="", help="Optional file path to write wrapped command stdout")
    p.add_argument("--skip-validate-existing", action="store_true", help="Skip existing JSONL schema validation")
    p.add_argument("--json", action="store_true", help="Print JSON summary")
    p.add_argument("command", nargs=argparse.REMAINDER, help="Wrapped command (pass after --)")
    return p.parse_args(argv)


def _build_summary(
    *,
    events_path: Path,
    args: argparse.Namespace,
    status: str,
    command_rc: int,
    appended: int,
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "schema_version": 1,
        "events_path": str(events_path),
        "skill": args.skill,
        "source": args.source,
        "context": args.context,
        "status": status,
        "command_rc": int(command_rc),
        "event_appended": int(appended),
    }
    if status == "failure":
        summary["reason_code"] = args.reason_code or "command_failed"
        summary["error_class"] = args.error_class or "runtime"
    return summary


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
        else (repo_root / DEFAULT_REASON_CODES_REL).resolve()
    )
    command = _parse_wrapped_command(list(args.command))
    if args.error_class and args.error_class not in ERROR_CLASSES:
        raise TelemetryError(f"invalid --error-class: {args.error_class}")
    cwd = Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd()
    stdout_file = Path(args.stdout_file).expanduser().resolve() if args.stdout_file else None

    schema = _load_schema(schema_path)
    reason_code_map = _load_reason_code_map(reason_codes_path)
    if not args.skip_validate_existing:
        _validate_existing_events(events_path, schema, reason_code_map)

    started = time.perf_counter()
    rc, stdout, stderr = _run(command, cwd=cwd)
    if stdout:
        if stdout_file is None:
            print(stdout, end="")
        else:
            stdout_file.parent.mkdir(parents=True, exist_ok=True)
            stdout_file.write_text(stdout, encoding="utf-8")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    duration_ms = max(0, int((time.perf_counter() - started) * 1000))

    status = "success" if rc == 0 else "failure"
    failure_reason_code = args.reason_code or "command_failed"
    if status == "failure" and failure_reason_code not in reason_code_map:
        raise TelemetryError(f"unknown failure reason_code: {failure_reason_code}")
    if status == "failure" and not args.error_class:
        args.error_class = reason_code_map.get(failure_reason_code, "") or "runtime"
    row: Dict[str, Any] = {
        "skill": args.skill,
        "status": status,
        "duration_ms": duration_ms,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "context": args.context,
    }
    if status == "failure":
        row["reason_code"] = failure_reason_code
        row["reason_detail"] = args.reason_detail or f"command_exit={rc}"
        row["error_class"] = args.error_class or "runtime"

    row_errors = _validate_event(schema, row, reason_code_map)
    if row_errors:
        raise TelemetryError("new usage event failed schema validation: " + "; ".join(row_errors))

    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")

    summary = _build_summary(events_path=events_path, args=args, status=status, command_rc=rc, appended=1)
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"status={status} rc={rc} skill={args.skill} event_appended=1")
    return int(rc)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except TelemetryError as err:
        print(f"error: {err}", file=sys.stderr)
        raise SystemExit(1)
