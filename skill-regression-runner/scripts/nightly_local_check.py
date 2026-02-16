#!/usr/bin/env python3
"""Compare nightly-local artifacts against previous run and detect deterministic drift."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List


VOLATILE_JSON_KEYS = {"generated_utc", "generated_at_utc"}


class NightlyCheckError(Exception):
    pass


def _load_schema(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise NightlyCheckError(f"invalid schema file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise NightlyCheckError(f"schema must be object: {path}")
    return obj


def _validate_report_schema(report: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = schema.get("required", [])
    props = schema.get("properties", {})
    if not isinstance(required, list) or not isinstance(props, dict):
        return ["invalid schema shape"]

    type_map = {"integer": int, "number": (int, float), "array": list, "string": str, "object": dict}
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
            continue
        enum = rule.get("enum")
        if isinstance(enum, list) and report[key] not in enum:
            errors.append(f"invalid value for {key}: {report[key]}")
    return errors


def _iter_files(root: Path) -> List[Path]:
    return sorted([p for p in root.rglob("*") if p.is_file()])


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key in sorted(value.keys()):
            if key in VOLATILE_JSON_KEYS:
                continue
            out[key] = _normalize_json_value(value[key])
        return out
    if isinstance(value, list):
        return [_normalize_json_value(v) for v in value]
    return value


def _normalized_bytes(path: Path) -> bytes:
    if path.suffix.lower() != ".json":
        return path.read_bytes()
    obj = json.loads(path.read_text(encoding="utf-8"))
    normalized = _normalize_json_value(obj)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _compare(current: Path, last: Path) -> Dict[str, Any]:
    current_files = {str(p.relative_to(current)): p for p in _iter_files(current)}
    last_files = {str(p.relative_to(last)): p for p in _iter_files(last)}

    current_names = set(current_files.keys())
    last_names = set(last_files.keys())

    missing_from_current = sorted(last_names - current_names)
    new_in_current = sorted(current_names - last_names)
    common = sorted(current_names & last_names)

    changed: List[str] = []
    for name in common:
        cur = current_files[name]
        prev = last_files[name]
        if _normalized_bytes(cur) != _normalized_bytes(prev):
            changed.append(name)

    return {
        "missing_from_current": missing_from_current,
        "new_in_current": new_in_current,
        "changed": changed,
        "drift_count": len(missing_from_current) + len(new_in_current) + len(changed),
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare nightly-local artifacts with previous run")
    p.add_argument("--current", required=True, help="Current artifact directory (e.g., /tmp/nightly)")
    p.add_argument("--last", required=True, help="Last-run snapshot directory (e.g., /tmp/nightly-last)")
    p.add_argument("--report", default="", help="Optional JSON report output path")
    p.add_argument("--schema", default="", help="Optional report schema path")
    p.add_argument("--json", action="store_true", help="Print JSON report")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    current = Path(args.current).expanduser().resolve()
    last = Path(args.last).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve() if args.report else None
    schema_path = Path(args.schema).expanduser().resolve() if args.schema else None

    if not current.exists() or not current.is_dir():
        raise NightlyCheckError(f"current directory not found: {current}")

    if not last.exists():
        _copy_tree(current, last)
        report = {
            "schema_version": 1,
            "status": "initialized",
            "current": str(current),
            "last": str(last),
            "drift_count": 0,
            "missing_from_current": [],
            "new_in_current": [],
            "changed": [],
        }
    else:
        comparison = _compare(current, last)
        status = "stable" if comparison["drift_count"] == 0 else "drift"
        report = {
            "schema_version": 1,
            "status": status,
            "current": str(current),
            "last": str(last),
            **comparison,
        }
        _copy_tree(current, last)

    if schema_path is not None:
        schema = _load_schema(schema_path)
        errors = _validate_report_schema(report, schema)
        if errors:
            raise NightlyCheckError("schema validation failed: " + "; ".join(errors))

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json or report_path is None:
        print(json.dumps(report, indent=2))

    if report["status"] == "drift":
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except NightlyCheckError as err:
        print(f"error: {err}", file=sys.stderr)
        raise SystemExit(1)
