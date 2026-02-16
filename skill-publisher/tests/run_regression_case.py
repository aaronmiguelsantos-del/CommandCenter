#!/usr/bin/env python3
"""Deterministic regression scenarios for skill-publisher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
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
        return 99, "", str(err)
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    (skill_dir / "agents").mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Fixture skill {name}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    (skill_dir / "agents" / "openai.yaml").write_text(
        "version: 1\nagent:\n  name: fixture-agent\n",
        encoding="utf-8",
    )


def _setup_source_root(base: Path) -> Path:
    source_root = base / "source-root"
    source_root.mkdir(parents=True, exist_ok=True)
    _write_skill(source_root, "skill-a")
    _write_skill(source_root, "skill-b")
    (source_root / "data").mkdir(parents=True, exist_ok=True)
    (source_root / "data" / "skill_usage_events.jsonl").write_text("", encoding="utf-8")
    return source_root


def _setup_repo_root(base: Path) -> Path:
    repo_root = base / "repo-root"
    repo_root.mkdir(parents=True, exist_ok=True)
    rc, _, err = _run(["git", "init", "-q"], cwd=repo_root)
    if rc != 0:
        raise CaseError(f"git init failed: {err}")
    return repo_root


def _load_last_usage_event(path: Path) -> Dict[str, Any]:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise CaseError("usage events file is empty")
    try:
        obj = json.loads(lines[-1])
    except Exception as err:
        raise CaseError(f"invalid usage event json: {err}") from err
    if not isinstance(obj, dict):
        raise CaseError("usage event row must be object")
    return obj


def _publish_cmd(
    script_path: Path,
    usage_schema: Path,
    source_root: Path,
    repo_root: Path,
    only: str,
) -> List[str]:
    return [
        "python3",
        str(script_path),
        "--source-root",
        str(source_root),
        "--repo-root",
        str(repo_root),
        "--usage-schema",
        str(usage_schema),
        "--skip-version-bump",
        "--skip-regressions",
        "--skip-rollup-contract",
        "--only",
        only,
        "--json",
    ]


def _scenario_scoped_only_publish(repo_root: Path, usage_schema: Path) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="skill-publisher-reg-") as td:
        temp = Path(td)
        source_root = _setup_source_root(temp)
        repo_clone = _setup_repo_root(temp)
        cmd = _publish_cmd(
            script_path=repo_root / "skill-publisher" / "scripts" / "publish_skills.py",
            usage_schema=usage_schema,
            source_root=source_root,
            repo_root=repo_clone,
            only="skill-a",
        )
        rc, stdout, stderr = _run(cmd, cwd=repo_root)
        if rc != 0:
            raise CaseError(f"publish failed unexpectedly: {stderr or stdout}")
        report = json.loads(stdout)
        if not isinstance(report, dict):
            raise CaseError("publish output must be JSON object")
        targeted = report.get("skills_targeted")
        synced = report.get("skills_synced")
        if targeted != ["skill-a"]:
            raise CaseError(f"unexpected targeted skills: {targeted}")
        if synced != ["skill-a"]:
            raise CaseError(f"unexpected synced skills: {synced}")
        return {
            "scenario": "scoped_only_publish",
            "publish_rc": rc,
            "skills_targeted": targeted,
            "skills_synced": synced,
        }


def _scenario_usage_event_append(repo_root: Path, usage_schema: Path) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="skill-publisher-reg-") as td:
        temp = Path(td)
        source_root = _setup_source_root(temp)
        repo_clone = _setup_repo_root(temp)
        usage_events = source_root / "data" / "skill_usage_events.jsonl"
        before_count = len([ln for ln in usage_events.read_text(encoding="utf-8").splitlines() if ln.strip()])
        cmd = _publish_cmd(
            script_path=repo_root / "skill-publisher" / "scripts" / "publish_skills.py",
            usage_schema=usage_schema,
            source_root=source_root,
            repo_root=repo_clone,
            only="skill-a",
        )
        rc, stdout, stderr = _run(cmd, cwd=repo_root)
        if rc != 0:
            raise CaseError(f"publish failed unexpectedly: {stderr or stdout}")
        report = json.loads(stdout)
        if not isinstance(report, dict):
            raise CaseError("publish output must be JSON object")
        after_count = len([ln for ln in usage_events.read_text(encoding="utf-8").splitlines() if ln.strip()])
        last_event = _load_last_usage_event(usage_events)
        appended = report.get("usage_events", {}).get("appended")
        if appended != 1:
            raise CaseError(f"expected appended=1, got {appended}")
        if after_count - before_count != 1:
            raise CaseError(f"usage events append mismatch: before={before_count} after={after_count}")
        if last_event.get("status") != "success":
            raise CaseError(f"expected success status, got {last_event.get('status')}")
        if last_event.get("skill") != "skill-a":
            raise CaseError(f"expected last skill=skill-a, got {last_event.get('skill')}")
        return {
            "scenario": "usage_event_append",
            "publish_rc": rc,
            "usage_appended": appended,
            "last_usage_status": last_event.get("status"),
            "last_usage_skill": last_event.get("skill"),
            "last_usage_source": last_event.get("source"),
        }


def _scenario_failure_reason_code(repo_root: Path, usage_schema: Path) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="skill-publisher-reg-") as td:
        temp = Path(td)
        source_root = _setup_source_root(temp)
        repo_clone = _setup_repo_root(temp)
        usage_events = source_root / "data" / "skill_usage_events.jsonl"
        cmd = _publish_cmd(
            script_path=repo_root / "skill-publisher" / "scripts" / "publish_skills.py",
            usage_schema=usage_schema,
            source_root=source_root,
            repo_root=repo_clone,
            only="no-such-skill",
        )
        rc, stdout, stderr = _run(cmd, cwd=repo_root)
        if rc != 1:
            raise CaseError(f"expected publish rc=1 for unknown skill, got {rc}")
        last_event = _load_last_usage_event(usage_events)
        if last_event.get("status") != "failure":
            raise CaseError(f"expected failure status, got {last_event.get('status')}")
        if last_event.get("reason_code") != "unknown_skill":
            raise CaseError(f"expected reason_code=unknown_skill, got {last_event.get('reason_code')}")
        if last_event.get("error_class") != "input":
            raise CaseError(f"expected error_class=input, got {last_event.get('error_class')}")
        return {
            "scenario": "failure_reason_code",
            "publish_rc": rc,
            "stderr_contains_unknown_skill": "unknown skills" in stderr.lower(),
            "last_failure_skill": last_event.get("skill"),
            "reason_code": last_event.get("reason_code"),
            "error_class": last_event.get("error_class"),
        }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run skill-publisher regression case")
    p.add_argument(
        "--scenario",
        required=True,
        choices=[
            "scoped_only_publish",
            "usage_event_append",
            "failure_reason_code",
        ],
    )
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    usage_schema = repo_root / "skill-adoption-analytics" / "references" / "skill_usage_events.schema.json"
    if not usage_schema.exists():
        raise CaseError(f"usage schema not found: {usage_schema}")

    if args.scenario == "scoped_only_publish":
        result = _scenario_scoped_only_publish(repo_root, usage_schema)
    elif args.scenario == "usage_event_append":
        result = _scenario_usage_event_append(repo_root, usage_schema)
    else:
        result = _scenario_failure_reason_code(repo_root, usage_schema)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except CaseError as err:
        print(f"error: {err}", file=sys.stderr)
        raise SystemExit(1)
