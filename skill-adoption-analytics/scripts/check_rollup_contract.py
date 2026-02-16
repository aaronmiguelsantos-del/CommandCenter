#!/usr/bin/env python3
"""Run rollup generation and enforce drift contract against expected snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Tuple


class ContractError(Exception):
    pass


def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except Exception as err:
        return 99, "", str(err)
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _json_load(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise ContractError(f"invalid json file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise ContractError(f"json file must be object: {path}")
    return obj


def _normalize_fields(payload: Dict[str, Any], fields: List[str], token: str) -> Dict[str, Any]:
    normalized = dict(payload)
    for field in fields:
        if field in normalized:
            normalized[field] = token
    return normalized


def run_contract(
    releases: Path,
    events: Path,
    schema: Path,
    expected: Path,
    output: Path,
    normalize_fields: List[str],
    normalize_token: str,
) -> Dict[str, Any]:
    script_path = Path(__file__).resolve().parent / "generate_daily_rollup.py"
    if not script_path.exists():
        raise ContractError(f"missing script: {script_path}")

    cmd = [
        "python3",
        str(script_path),
        "--releases",
        str(releases),
        "--events",
        str(events),
        "--schema",
        str(schema),
        "--output",
        str(output),
    ]
    rc, out, err = _run(cmd, cwd=Path.cwd())
    if rc != 0:
        raise ContractError(f"rollup generation failed: {err or out}")

    actual = _json_load(output)
    expected_obj = _json_load(expected)

    actual_norm = _normalize_fields(actual, normalize_fields, normalize_token)
    expected_norm = _normalize_fields(expected_obj, normalize_fields, normalize_token)
    drift = actual_norm != expected_norm

    return {
        "schema_version": 1,
        "ok": not drift,
        "drift": drift,
        "normalize_fields": normalize_fields,
        "normalize_token": normalize_token,
        "actual_path": str(output),
        "expected_path": str(expected),
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check rollup contract against expected snapshot")
    parser.add_argument("--releases", required=True, help="Path to releases JSONL")
    parser.add_argument("--events", required=True, help="Path to usage events JSONL")
    parser.add_argument("--schema", required=True, help="Path to rollup schema JSON")
    parser.add_argument("--expected", required=True, help="Path to expected rollup JSON")
    parser.add_argument("--output", required=True, help="Path to write generated rollup JSON")
    parser.add_argument(
        "--normalize-fields",
        default="generated_utc",
        help="Comma-separated top-level fields to normalize before diff",
    )
    parser.add_argument("--normalize-token", default="__NORMALIZED__", help="Replacement token")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    releases = Path(args.releases).expanduser().resolve()
    events = Path(args.events).expanduser().resolve()
    schema = Path(args.schema).expanduser().resolve()
    expected = Path(args.expected).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    normalize_fields = [x.strip() for x in str(args.normalize_fields).split(",") if x.strip()]

    try:
        report = run_contract(
            releases=releases,
            events=events,
            schema=schema,
            expected=expected,
            output=output,
            normalize_fields=normalize_fields,
            normalize_token=str(args.normalize_token),
        )
    except ContractError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"ok: {report['ok']}")
        print(f"drift: {report['drift']}")
        print(f"actual_path: {report['actual_path']}")
        print(f"expected_path: {report['expected_path']}")

    if report["drift"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
