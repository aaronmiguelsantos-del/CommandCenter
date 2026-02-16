#!/usr/bin/env python3
"""Deterministic regression scenarios for skill-telemetry-instrumentor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Tuple


class CaseError(Exception):
    pass


def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except Exception as err:
        return 99, "", f"RUNNER_ERROR: {err}"
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _extract_last_json_line(text: str) -> Dict[str, Any]:
    for line in reversed(text.splitlines()):
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    raise CaseError("no JSON object found in command stdout")


def _load_events(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise CaseError("event row must be object")
        rows.append(obj)
    return rows


def _instrument_cmd(
    script_path: Path,
    events_path: Path,
    wrapped_command: List[str],
    reason_code: str = "",
    error_class: str = "",
    reason_detail: str = "",
) -> List[str]:
    cmd = [
        sys.executable,
        str(script_path),
        "--events",
        str(events_path),
        "--skill",
        "skill-publisher",
        "--source",
        "regression-suite",
        "--context",
        "regression",
        "--json",
    ]
    if reason_code:
        cmd.extend(["--reason-code", reason_code])
    if error_class:
        cmd.extend(["--error-class", error_class])
    if reason_detail:
        cmd.extend(["--reason-detail", reason_detail])
    cmd.append("--")
    cmd.extend(wrapped_command)
    return cmd


def _scenario_success_append(repo_root: Path) -> Dict[str, Any]:
    script_path = repo_root / "skill-telemetry-instrumentor" / "scripts" / "instrument_skill_telemetry.py"
    with tempfile.TemporaryDirectory(prefix="telemetry-reg-") as td:
        events_path = Path(td) / "events.jsonl"
        cmd = _instrument_cmd(
            script_path=script_path,
            events_path=events_path,
            wrapped_command=[sys.executable, "-c", "print('ok')"],
        )
        rc, stdout, stderr = _run(cmd, cwd=repo_root / "skill-telemetry-instrumentor")
        if rc != 0:
            raise CaseError(f"expected wrapper rc=0, got {rc}: {stderr or stdout}")
        summary = _extract_last_json_line(stdout)
        events = _load_events(events_path)
        last = events[-1]
        if last.get("status") != "success":
            raise CaseError(f"expected success event, got {last.get('status')}")
        return {
            "scenario": "success_append",
            "wrapper_rc": rc,
            "events_count": len(events),
            "event_status": last.get("status"),
            "event_source": last.get("source"),
            "summary_status": summary.get("status"),
            "summary_event_appended": summary.get("event_appended"),
        }


def _scenario_failure_append_reason(repo_root: Path) -> Dict[str, Any]:
    script_path = repo_root / "skill-telemetry-instrumentor" / "scripts" / "instrument_skill_telemetry.py"
    with tempfile.TemporaryDirectory(prefix="telemetry-reg-") as td:
        events_path = Path(td) / "events.jsonl"
        cmd = _instrument_cmd(
            script_path=script_path,
            events_path=events_path,
            reason_code="regression_failed",
            error_class="regression",
            reason_detail="exit_7",
            wrapped_command=[sys.executable, "-c", "import sys; sys.exit(7)"],
        )
        rc, stdout, stderr = _run(cmd, cwd=repo_root / "skill-telemetry-instrumentor")
        if rc != 7:
            raise CaseError(f"expected wrapper rc=7, got {rc}: {stderr or stdout}")
        summary = _extract_last_json_line(stdout)
        events = _load_events(events_path)
        last = events[-1]
        if last.get("status") != "failure":
            raise CaseError(f"expected failure event, got {last.get('status')}")
        return {
            "scenario": "failure_append_reason",
            "wrapper_rc": rc,
            "events_count": len(events),
            "event_status": last.get("status"),
            "event_reason_code": last.get("reason_code"),
            "event_error_class": last.get("error_class"),
            "summary_status": summary.get("status"),
            "summary_reason_code": summary.get("reason_code"),
        }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run telemetry instrumentor regression scenario")
    p.add_argument("--scenario", required=True, choices=["success_append", "failure_append_reason"])
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]

    try:
        if args.scenario == "success_append":
            payload = _scenario_success_append(repo_root)
        else:
            payload = _scenario_failure_append_reason(repo_root)
    except CaseError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
