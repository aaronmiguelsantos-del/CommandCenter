#!/usr/bin/env python3
"""Run deterministic release preflight gates and emit one verdict artifact."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Tuple


class PreflightError(Exception):
    pass


def _run(cmd: List[str], cwd: Path, env_override: Dict[str, str] | None = None) -> Tuple[int, str, str]:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, env=env)
    except Exception as err:
        return 99, "", f"RUNNER_ERROR: {err}"
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _tail(text: str, n: int = 20) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _parse_json_objects(text: str) -> List[Dict[str, Any]]:
    decoder = json.JSONDecoder()
    payloads: List[Dict[str, Any]] = []
    raw = text.strip()
    idx = 0
    while idx < len(raw):
        while idx < len(raw) and raw[idx].isspace():
            idx += 1
        if idx >= len(raw):
            break
        try:
            obj, next_idx = decoder.raw_decode(raw, idx)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            payloads.append(obj)
        idx = next_idx
    return payloads


def _resolve_events(repo_root: Path, raw_events: str) -> Path:
    events = Path(raw_events).expanduser()
    if not events.is_absolute():
        events = repo_root / events
    return events.resolve()


def _resolve_slo_config(repo_root: Path, raw_path: str) -> Path:
    if raw_path:
        config = Path(raw_path).expanduser()
        if not config.is_absolute():
            config = repo_root / config
        return config.resolve()
    return (repo_root / "telemetry-slo-guard" / "references" / "default_slo_config.json").resolve()


def _resolve_output(repo_root: Path, raw_path: str) -> Path:
    output = Path(raw_path).expanduser()
    if not output.is_absolute():
        output = repo_root / output
    return output.resolve()


def _check_from_make(
    repo_root: Path,
    name: str,
    target: str,
    extra_env: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    cmd = ["make", "-s", target]
    rc, stdout, stderr = _run(cmd, cwd=repo_root, env_override=extra_env)
    parsed = _parse_json_objects(stdout)
    return {
        "name": name,
        "target": target,
        "command": cmd,
        "rc": rc,
        "passed": rc == 0,
        "stdout_json": parsed,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def run_preflight(
    repo_root: Path,
    events: Path,
    slo_config: Path,
    skip_resolver_smoke: bool,
    skip_regression_strict: bool,
    skip_rollup_contract: bool,
    skip_telemetry_slo: bool,
) -> Dict[str, Any]:
    if not repo_root.exists() or not repo_root.is_dir():
        raise PreflightError(f"repo root does not exist: {repo_root}")
    if not (repo_root / "Makefile").exists():
        raise PreflightError(f"missing Makefile in repo root: {repo_root}")

    checks: List[Dict[str, Any]] = []

    if skip_resolver_smoke:
        checks.append({"name": "resolver-smoke", "target": "resolver-smoke", "skipped": True, "passed": True})
    else:
        checks.append(_check_from_make(repo_root, name="resolver-smoke", target="resolver-smoke"))

    if skip_regression_strict:
        checks.append({"name": "regression-strict", "target": "regression-strict", "skipped": True, "passed": True})
    else:
        checks.append(_check_from_make(repo_root, name="regression-strict", target="regression-strict"))

    if skip_rollup_contract:
        checks.append({"name": "rollup-contract", "target": "rollup-contract", "skipped": True, "passed": True})
    else:
        checks.append(_check_from_make(repo_root, name="rollup-contract", target="rollup-contract"))

    if skip_telemetry_slo:
        checks.append({"name": "telemetry-slo", "target": "telemetry-slo", "skipped": True, "passed": True})
    else:
        checks.append(
            _check_from_make(
                repo_root,
                name="telemetry-slo",
                target="telemetry-slo",
                extra_env={"EVENTS": str(events), "SLO_CONFIG": str(slo_config)},
            )
        )

    blockers: List[str] = []
    for check in checks:
        if not bool(check.get("passed", False)):
            blockers.append(str(check.get("name", "unknown")))

    ready = len(blockers) == 0
    return {
        "schema_version": 1,
        "repo_root": str(repo_root),
        "events": str(events),
        "slo_config": str(slo_config),
        "verdict": "ready" if ready else "blocked",
        "ready": ready,
        "blockers": blockers,
        "checks": checks,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one-command release preflight checks")
    p.add_argument("--repo-root", default=".", help="Repo root path")
    p.add_argument("--events", default="data/skill_usage_events.jsonl", help="Telemetry events JSONL path")
    p.add_argument("--slo-config", default="", help="Optional telemetry SLO config override")
    p.add_argument("--output", default="data/release_preflight.json", help="Output artifact path")
    p.add_argument("--skip-resolver-smoke", action="store_true", help="Skip resolver-smoke check")
    p.add_argument("--skip-regression-strict", action="store_true", help="Skip regression-strict check")
    p.add_argument("--skip-rollup-contract", action="store_true", help="Skip rollup-contract check")
    p.add_argument("--skip-telemetry-slo", action="store_true", help="Skip telemetry-slo check")
    p.add_argument("--strict", action="store_true", help="Exit 2 when verdict is blocked")
    p.add_argument("--json", action="store_true", help="Emit JSON report")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()

    try:
        events = _resolve_events(repo_root, str(args.events))
        slo_config = _resolve_slo_config(repo_root, str(args.slo_config))
        output = _resolve_output(repo_root, str(args.output))
        report = run_preflight(
            repo_root=repo_root,
            events=events,
            slo_config=slo_config,
            skip_resolver_smoke=bool(args.skip_resolver_smoke),
            skip_regression_strict=bool(args.skip_regression_strict),
            skip_rollup_contract=bool(args.skip_rollup_contract),
            skip_telemetry_slo=bool(args.skip_telemetry_slo),
        )
    except PreflightError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"output: {output}")
        print(f"verdict: {report['verdict']}")
        for check in report["checks"]:
            state = "SKIP" if check.get("skipped") else ("PASS" if check.get("passed") else "FAIL")
            print(f"- {state} {check.get('name')}")

    if args.strict and not bool(report.get("ready", False)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
