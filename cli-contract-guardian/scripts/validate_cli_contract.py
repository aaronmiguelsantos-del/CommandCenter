#!/usr/bin/env python3
"""Deterministic validator for app.main CLI contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Tuple


class ContractError(Exception):
    pass


def _run(args: List[str], cwd: Path, timeout: int = 120) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        return int(proc.returncode), proc.stdout or "", proc.stderr or ""
    except Exception as err:
        return 99, "", f"RUNNER_ERROR: {err}"


def _json_load(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _stderr_last_json(stderr: str) -> Dict[str, Any] | None:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return None
    obj = _json_load(lines[-1])
    return obj if isinstance(obj, dict) else None


def _has_keys(obj: Dict[str, Any], keys: List[str]) -> bool:
    return all(key in obj for key in keys)


def _check_report_health(py: str, target: Path, registry: str | None) -> Dict[str, Any]:
    cmd = [py, "-m", "app.main", "report", "health", "--json"]
    if registry:
        cmd.extend(["--registry", registry])
    rc, stdout, stderr = _run(cmd, cwd=target)
    result: Dict[str, Any] = {
        "id": "report_health_json",
        "command": cmd,
        "rc": rc,
        "passed": False,
        "details": "",
    }
    if rc != 0:
        result["details"] = f"expected rc=0, got {rc}; stderr_tail={_tail(stderr)}"
        return result
    obj = _json_load(stdout)
    if not isinstance(obj, dict):
        result["details"] = "stdout is not valid JSON object"
        return result
    if not _has_keys(obj, ["summary", "policy"]):
        result["details"] = "missing required keys: summary, policy"
        return result
    result["passed"] = True
    result["details"] = "ok"
    result["snapshot"] = {
        "report_version": obj.get("report_version"),
        "summary_keys": sorted(list(obj.get("summary", {}).keys())) if isinstance(obj.get("summary"), dict) else [],
        "policy_keys": sorted(list(obj.get("policy", {}).keys())) if isinstance(obj.get("policy"), dict) else [],
    }
    return result


def _check_report_graph(py: str, target: Path, registry: str | None) -> Dict[str, Any]:
    cmd = [py, "-m", "app.main", "report", "graph", "--json"]
    if registry:
        cmd.extend(["--registry", registry])
    rc, stdout, stderr = _run(cmd, cwd=target)
    result: Dict[str, Any] = {
        "id": "report_graph_json",
        "command": cmd,
        "rc": rc,
        "passed": False,
        "details": "",
    }
    if rc != 0:
        result["details"] = f"expected rc=0, got {rc}; stderr_tail={_tail(stderr)}"
        return result
    obj = _json_load(stdout)
    if not isinstance(obj, dict):
        result["details"] = "stdout is not valid JSON object"
        return result
    if "topo" not in obj:
        result["details"] = "missing required key: topo"
        return result
    topo = obj.get("topo")
    if not isinstance(topo, list):
        result["details"] = "topo is not a list"
        return result
    result["passed"] = True
    result["details"] = "ok"
    result["snapshot"] = {
        "graph_version": obj.get("graph_version"),
        "topo_len": len(topo),
    }
    return result


def _check_health_strict(
    py: str,
    target: Path,
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
    registry: str | None,
) -> Dict[str, Any]:
    cmd = [py, "-m", "app.main", "health", "--all", "--strict"]
    if include_staging:
        cmd.append("--include-staging")
    if include_dev:
        cmd.append("--include-dev")
    if enforce_sla:
        cmd.append("--enforce-sla")
    if registry:
        cmd.extend(["--registry", registry])

    rc, stdout, stderr = _run(cmd, cwd=target)
    result: Dict[str, Any] = {
        "id": "health_all_strict",
        "command": cmd,
        "rc": rc,
        "passed": False,
        "details": "",
    }
    if rc not in (0, 2):
        result["details"] = f"expected rc in {{0,2}}, got {rc}; stderr_tail={_tail(stderr)}"
        return result
    if rc == 0:
        result["passed"] = True
        result["details"] = "ok (strict pass)"
        result["snapshot"] = {"strict_result": "pass"}
        return result

    payload = _stderr_last_json(stderr)
    if payload is None:
        result["details"] = "rc=2 but no strict JSON payload on stderr last line"
        return result
    if not _has_keys(payload, ["schema_version", "policy", "reasons"]):
        result["details"] = "strict payload missing required keys: schema_version, policy, reasons"
        return result
    if not isinstance(payload.get("reasons"), list):
        result["details"] = "strict payload reasons is not a list"
        return result
    result["passed"] = True
    result["details"] = "ok (strict fail contract valid)"
    result["snapshot"] = {
        "strict_result": "fail",
        "schema_version": payload.get("schema_version"),
        "reason_count": len(payload.get("reasons", [])),
    }
    return result


def _tail(text: str, n: int = 8) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _snapshot_from_checks(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "version": 1,
        "checks": {c["id"]: c.get("snapshot", {}) for c in checks},
    }


def _compare_snapshot(current: Dict[str, Any], baseline: Dict[str, Any]) -> List[str]:
    diffs: List[str] = []
    cur_checks = current.get("checks", {})
    base_checks = baseline.get("checks", {})
    for check_id, cur in cur_checks.items():
        if check_id not in base_checks:
            diffs.append(f"new snapshot check: {check_id}")
            continue
        if cur != base_checks[check_id]:
            diffs.append(f"snapshot drift in {check_id}")
    for check_id in base_checks.keys():
        if check_id not in cur_checks:
            diffs.append(f"missing snapshot check: {check_id}")
    return diffs


def validate(
    target: Path,
    py: str,
    registry: str | None,
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
    snapshot_path: Path,
    update_snapshot: bool,
) -> Dict[str, Any]:
    checks = [
        _check_report_health(py=py, target=target, registry=registry),
        _check_report_graph(py=py, target=target, registry=registry),
        _check_health_strict(
            py=py,
            target=target,
            include_staging=include_staging,
            include_dev=include_dev,
            enforce_sla=enforce_sla,
            registry=registry,
        ),
    ]

    snapshot_current = _snapshot_from_checks(checks)
    snapshot_drift: List[str] = []
    if snapshot_path.exists():
        baseline = _json_load(snapshot_path.read_text(encoding="utf-8"))
        if isinstance(baseline, dict):
            snapshot_drift = _compare_snapshot(snapshot_current, baseline)
        else:
            snapshot_drift = ["invalid baseline snapshot format"]
    else:
        snapshot_drift = ["baseline snapshot missing"]

    if update_snapshot:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot_current, indent=2) + "\n", encoding="utf-8")
        snapshot_drift = []

    passed = all(bool(c.get("passed")) for c in checks) and not snapshot_drift
    report: Dict[str, Any] = {
        "schema_version": 1,
        "target": str(target),
        "checks": checks,
        "snapshot_path": str(snapshot_path),
        "snapshot_drift": snapshot_drift,
        "passed": passed,
    }
    return report


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate app.main CLI contract")
    parser.add_argument("--target", required=True, help="Repository root")
    parser.add_argument("--python", default="python3", help="Python executable")
    parser.add_argument("--registry", default="", help="Optional registry path override")
    parser.add_argument("--include-staging", action="store_true", help="Pass --include-staging to strict check")
    parser.add_argument("--include-dev", action="store_true", help="Pass --include-dev to strict check")
    parser.add_argument("--enforce-sla", action="store_true", help="Pass --enforce-sla to strict check")
    parser.add_argument("--strict", action="store_true", help="Exit 2 when contract checks fail")
    parser.add_argument("--snapshot-path", default="data/cli_contract_snapshot.json", help="Snapshot path")
    parser.add_argument("--update-snapshot", action="store_true", help="Update snapshot baseline with current results")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    target = Path(args.target).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        print(f"error: target '{target}' must be an existing directory", file=sys.stderr)
        return 1
    snapshot_path = Path(args.snapshot_path)
    if not snapshot_path.is_absolute():
        snapshot_path = target / snapshot_path

    try:
        report = validate(
            target=target,
            py=args.python,
            registry=args.registry.strip() or None,
            include_staging=bool(args.include_staging or args.include_dev),
            include_dev=bool(args.include_dev),
            enforce_sla=bool(args.enforce_sla),
            snapshot_path=snapshot_path,
            update_snapshot=bool(args.update_snapshot),
        )
    except ContractError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"target: {report['target']}")
        print(f"passed: {report['passed']}")
        print("checks:")
        for check in report["checks"]:
            state = "PASS" if check["passed"] else "FAIL"
            print(f"- {state} {check['id']} rc={check['rc']}: {check['details']}")
        if report["snapshot_drift"]:
            print("snapshot_drift:")
            for drift in report["snapshot_drift"]:
                print(f"- {drift}")

    if args.strict and not report["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
