#!/usr/bin/env python3
"""Run regression suites for skills and compare with golden snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Tuple


class RegressionError(Exception):
    pass


def _run(cmd: List[str], cwd: Path, timeout: int = 120) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        return int(proc.returncode), proc.stdout or "", proc.stderr or ""
    except Exception as err:
        return 99, "", f"RUNNER_ERROR: {err}"


def _is_skill_dir(path: Path) -> bool:
    return (path / "SKILL.md").exists() and (path / "agents" / "openai.yaml").exists()


def _discover_skill_dirs(source_root: Path) -> List[Path]:
    skills: List[Path] = []
    for child in sorted(source_root.iterdir()):
        if child.is_dir() and _is_skill_dir(child):
            skills.append(child)
    return skills


def _parse_only_csv(raw: str) -> List[str]:
    names: List[str] = []
    seen = set()
    for item in raw.split(","):
        name = item.strip()
        if not name:
            continue
        if name not in seen:
            names.append(name)
            seen.add(name)
    return names


def _select_skill_dirs(skill_dirs: List[Path], only: List[str]) -> List[Path]:
    if not only:
        return skill_dirs
    by_name = {p.name: p for p in skill_dirs}
    missing = [name for name in only if name not in by_name]
    if missing:
        raise RegressionError(f"--only contains unknown skills: {', '.join(missing)}")
    return [by_name[name] for name in only]


def _load_suite(skill_dir: Path) -> List[Dict[str, Any]]:
    suite_path = skill_dir / "tests" / "regression_suite.json"
    if not suite_path.exists():
        return []
    try:
        obj = json.loads(suite_path.read_text(encoding="utf-8"))
    except Exception as err:
        raise RegressionError(f"invalid suite for {skill_dir.name}: {err}")
    if not isinstance(obj, dict) or not isinstance(obj.get("cases"), list):
        raise RegressionError(f"invalid suite schema for {skill_dir.name}: expected object with cases[]")
    return [c for c in obj["cases"] if isinstance(c, dict)]


def _snapshot_path(skill_dir: Path, case_id: str) -> Path:
    return skill_dir / "tests" / "golden" / f"{case_id}.json"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_schema(schema_path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as err:
        raise RegressionError(f"invalid schema file {schema_path}: {err}")
    if not isinstance(obj, dict):
        raise RegressionError(f"schema must be object: {schema_path}")
    return obj


def _validate_snapshot_payload(payload: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    if not isinstance(required, list) or not isinstance(properties, dict):
        return ["invalid schema shape"]

    for key in required:
        if key not in payload:
            errors.append(f"missing required key: {key}")
    type_map = {"string": str, "integer": int}
    for key, prop in properties.items():
        if key not in payload or not isinstance(prop, dict):
            continue
        expected_type = prop.get("type")
        py_type = type_map.get(expected_type)
        if py_type and not isinstance(payload[key], py_type):
            errors.append(f"invalid type for {key}: expected {expected_type}")
    return errors


def _case_result(
    skill_dir: Path,
    case: Dict[str, Any],
    update_snapshots: bool,
    schema: Dict[str, Any],
) -> Dict[str, Any]:
    case_id = str(case.get("id", "")).strip()
    cmd = case.get("command", [])
    if not case_id:
        return {"id": "", "passed": False, "reason": "missing id"}
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
        return {"id": case_id, "passed": False, "reason": "invalid command"}

    expected_exit = int(case.get("expect_exit", 0))
    expect_stdout_contains = case.get("expect_stdout_contains", [])
    if not isinstance(expect_stdout_contains, list):
        expect_stdout_contains = []

    rc, stdout, stderr = _run(cmd, cwd=skill_dir)
    passed = rc == expected_exit
    reasons: List[str] = []
    if rc != expected_exit:
        reasons.append(f"exit mismatch expected={expected_exit} got={rc}")
    for needle in expect_stdout_contains:
        if isinstance(needle, str) and needle not in stdout:
            passed = False
            reasons.append(f"stdout missing token: {needle}")

    snapshot_payload = {
        "rc": rc,
        "stdout_sha256": _hash_text(stdout),
        "stderr_sha256": _hash_text(stderr),
        "stdout_head": "\n".join(stdout.splitlines()[:30]),
        "stderr_head": "\n".join(stderr.splitlines()[:30]),
    }
    schema_errors = _validate_snapshot_payload(snapshot_payload, schema)
    if schema_errors:
        passed = False
        reasons.extend([f"schema: {e}" for e in schema_errors])

    snap_path = _snapshot_path(skill_dir, case_id)
    drift = False
    if update_snapshots:
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(json.dumps(snapshot_payload, indent=2) + "\n", encoding="utf-8")
    else:
        if snap_path.exists():
            baseline = json.loads(snap_path.read_text(encoding="utf-8"))
            if baseline != snapshot_payload:
                drift = True
                passed = False
                reasons.append("snapshot drift")
        else:
            drift = True
            passed = False
            reasons.append("missing snapshot")

    return {
        "id": case_id,
        "command": cmd,
        "passed": passed,
        "drift": drift,
        "reasons": reasons,
        "snapshot_path": str(snap_path),
    }


def run_regressions(source_root: Path, update_snapshots: bool, schema_path: Path, only_skills: List[str]) -> Dict[str, Any]:
    if not source_root.exists() or not source_root.is_dir():
        raise RegressionError(f"source root does not exist: {source_root}")

    discovered = _discover_skill_dirs(source_root)
    skills = _select_skill_dirs(discovered, only_skills)
    report_skills: List[Dict[str, Any]] = []

    schema = _load_schema(schema_path)
    for skill_dir in skills:
        cases = _load_suite(skill_dir)
        case_results = [_case_result(skill_dir, case, update_snapshots, schema) for case in cases]
        passed = all(c["passed"] for c in case_results)
        report_skills.append(
            {
                "skill": skill_dir.name,
                "suite_cases": len(cases),
                "passed": passed,
                "cases": case_results,
            }
        )

    overall_passed = all(s["passed"] for s in report_skills)
    return {
        "schema_version": 1,
        "source_root": str(source_root),
        "update_snapshots": update_snapshots,
        "overall_passed": overall_passed,
        "snapshot_schema": str(schema_path),
        "skills_discovered": [s.name for s in discovered],
        "skills_targeted": [s.name for s in skills],
        "skills": report_skills,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run skill regression suites")
    parser.add_argument("--source-root", required=True, help="Path containing skill folders")
    parser.add_argument("--only", default="", help="Optional comma-separated skill names to run")
    parser.add_argument("--update-snapshots", action="store_true", help="Write/refresh golden snapshots")
    parser.add_argument("--strict", action="store_true", help="Exit with code 2 on failures")
    parser.add_argument(
        "--snapshot-schema",
        default="",
        help="Optional snapshot schema path (defaults to references/regression_snapshot.schema.json)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    source_root = Path(args.source_root).expanduser().resolve()
    if args.snapshot_schema:
        schema_path = Path(args.snapshot_schema).expanduser().resolve()
    else:
        schema_path = Path(__file__).resolve().parents[1] / "references" / "regression_snapshot.schema.json"
    try:
        only = _parse_only_csv(str(args.only))
        report = run_regressions(source_root, bool(args.update_snapshots), schema_path=schema_path, only_skills=only)
    except RegressionError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"source_root: {report['source_root']}")
        print(f"overall_passed: {report['overall_passed']}")
        for skill in report["skills"]:
            state = "PASS" if skill["passed"] else "FAIL"
            print(f"- {state} {skill['skill']} cases={skill['suite_cases']}")

    if args.strict and not report["overall_passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
