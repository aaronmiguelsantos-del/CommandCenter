#!/usr/bin/env python3
"""One-command release readiness gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple


class OrchestratorError(Exception):
    pass


def _run(cmd: List[str], cwd: Path, timeout: int = 300) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        return int(proc.returncode), proc.stdout or "", proc.stderr or ""
    except Exception as err:
        return 99, "", f"RUNNER_ERROR: {err}"


def _json_load(text: str) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(text)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _resolve_tool(
    explicit: str | None,
    target: Path,
    target_candidates: List[str],
    relative_candidates: List[str],
) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.exists() else None

    for rel in target_candidates:
        path = target / rel
        if path.exists():
            return path

    workspace_root = Path(__file__).resolve().parents[2]
    for rel in relative_candidates:
        path = workspace_root / rel
        if path.exists():
            return path
    return None


def _tail(text: str, n: int = 8) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _run_check(name: str, cmd: List[str], cwd: Path) -> Dict[str, Any]:
    rc, stdout, stderr = _run(cmd, cwd=cwd)
    parsed = _json_load(stdout.strip())
    return {
        "name": name,
        "command": cmd,
        "rc": rc,
        "passed": rc == 0,
        "stdout_json": parsed,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def build_report(
    target: Path,
    py: str,
    hardener_script: str | None,
    health_script: str | None,
    contract_script: str | None,
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
) -> Dict[str, Any]:
    if not target.exists() or not target.is_dir():
        raise OrchestratorError(f"target '{target}' must be an existing directory")

    hardener_path = _resolve_tool(
        explicit=hardener_script,
        target=target,
        target_candidates=["scripts/harden_repo.py"],
        relative_candidates=["repo-hardener/scripts/harden_repo.py"],
    )
    health_path = _resolve_tool(
        explicit=health_script,
        target=target,
        target_candidates=["scripts/repo_health.py"],
        relative_candidates=["repo-health-reporter/scripts/repo_health.py"],
    )
    contract_path = _resolve_tool(
        explicit=contract_script,
        target=target,
        target_candidates=["scripts/validate_cli_contract.py"],
        relative_candidates=["cli-contract-guardian/scripts/validate_cli_contract.py"],
    )

    checks: List[Dict[str, Any]] = []
    blockers: List[str] = []

    if hardener_path is None:
        checks.append(
            {
                "name": "repo-hardener",
                "passed": False,
                "rc": 1,
                "command": [],
                "stdout_json": None,
                "stdout_tail": "",
                "stderr_tail": "hardener script not found",
            }
        )
        blockers.append("missing repo-hardener script")
    else:
        cmd = [
            py,
            str(hardener_path),
            "--target",
            str(target),
            "--safe-refactor",
            "--dry-run",
            "--strict",
            "--min-score",
            "85",
            "--no-verify-commands",
        ]
        hardener_result = _run_check("repo-hardener", cmd, cwd=target)
        checks.append(hardener_result)
        if not hardener_result["passed"]:
            blockers.append("repo-hardener check failed")

    if health_path is None:
        checks.append(
            {
                "name": "repo-health-reporter",
                "passed": False,
                "rc": 1,
                "command": [],
                "stdout_json": None,
                "stdout_tail": "",
                "stderr_tail": "health reporter script not found",
            }
        )
        blockers.append("missing repo-health-reporter script")
    else:
        cmd = [py, str(health_path), "--target", str(target), "--json", "--strict"]
        health_result = _run_check("repo-health-reporter", cmd, cwd=target)
        checks.append(health_result)
        if not health_result["passed"]:
            blockers.append("repo-health-reporter check failed")

    if contract_path is None:
        checks.append(
            {
                "name": "cli-contract-guardian",
                "passed": False,
                "rc": 1,
                "command": [],
                "stdout_json": None,
                "stdout_tail": "",
                "stderr_tail": "cli-contract-guardian script not found",
            }
        )
        blockers.append("missing cli-contract-guardian script")
    else:
        cmd = [py, str(contract_path), "--target", str(target), "--json", "--strict"]
        if include_staging:
            cmd.append("--include-staging")
        if include_dev:
            cmd.append("--include-dev")
        if enforce_sla:
            cmd.append("--enforce-sla")
        contract_result = _run_check("cli-contract-guardian", cmd, cwd=target)
        checks.append(contract_result)
        if not contract_result["passed"]:
            blockers.append("cli-contract-guardian check failed")

    ready = not blockers
    report: Dict[str, Any] = {
        "schema_version": 1,
        "target": str(target),
        "verdict": "ready" if ready else "blocked",
        "ready": ready,
        "blockers": blockers,
        "checks": checks,
    }
    return report


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one-command release readiness checks")
    parser.add_argument("--target", required=True, help="Repository root path")
    parser.add_argument("--python", default="python3", help="Python executable for child scripts")
    parser.add_argument("--hardener-script", default="", help="Optional explicit path to hardener script")
    parser.add_argument("--health-script", default="", help="Optional explicit path to health script")
    parser.add_argument("--contract-script", default="", help="Optional explicit path to contract script")
    parser.add_argument("--include-staging", action="store_true", help="Pass policy flag through to child checks")
    parser.add_argument("--include-dev", action="store_true", help="Pass policy flag through to child checks")
    parser.add_argument("--enforce-sla", action="store_true", help="Pass policy flag through to child checks")
    parser.add_argument("--output", default="data/release_readiness.json", help="Output JSON path")
    parser.add_argument("--json", action="store_true", help="Print full JSON report to stdout")
    parser.add_argument("--strict", action="store_true", help="Return exit code 2 when blocked")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    target = Path(args.target).expanduser().resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = target / output_path

    report = build_report(
        target=target,
        py=args.python,
        hardener_script=args.hardener_script.strip() or None,
        health_script=args.health_script.strip() or None,
        contract_script=args.contract_script.strip() or None,
        include_staging=bool(args.include_staging or args.include_dev),
        include_dev=bool(args.include_dev),
        enforce_sla=bool(args.enforce_sla),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"target: {report['target']}")
        print(f"verdict: {report['verdict']}")
        print(f"ready: {report['ready']}")
        if report["blockers"]:
            print("blockers:")
            for blocker in report["blockers"]:
                print(f"- {blocker}")
        print("checks:")
        for check in report["checks"]:
            state = "PASS" if check["passed"] else "FAIL"
            print(f"- {state} {check['name']} rc={check['rc']}")

    if args.strict and not report["ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
