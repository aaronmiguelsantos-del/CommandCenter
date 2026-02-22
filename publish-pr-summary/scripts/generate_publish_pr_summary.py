#!/usr/bin/env python3
"""Generate publish PR summary artifacts from resolver + telemetry signals."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Tuple


class SummaryError(Exception):
    pass


SKIP_PR_SUMMARY_ENV = "SKILL_PUBLISHER_DISABLE_PR_SUMMARY"


def _run(cmd: List[str], cwd: Path, env_override: Dict[str, str] | None = None) -> Tuple[int, str, str]:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, env=env)
    except Exception as err:
        return 99, "", f"RUNNER_ERROR: {err}"
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _parse_csv(raw: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _tail(text: str, n: int = 20) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _parse_json(text: str, context: str) -> Dict[str, Any]:
    try:
        obj = json.loads(text)
    except Exception as err:
        raise SummaryError(f"{context} returned invalid json: {err}") from err
    if not isinstance(obj, dict):
        raise SummaryError(f"{context} returned invalid payload")
    return obj


def _resolve_path(repo_root: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _run_resolver_smoke(repo_root: Path, requested_csv: str) -> Dict[str, Any]:
    smoke_script = repo_root / "skill-name-resolver" / "tests" / "run_shared_resolver_smoke.py"
    if not smoke_script.exists():
        return {
            "status": "error",
            "consistent": False,
            "requested": requested_csv,
            "error": f"missing script: {smoke_script}",
        }

    cmd = [
        "python3",
        str(smoke_script),
        "--requested",
        requested_csv,
        "--json",
    ]
    rc, stdout, stderr = _run(cmd, cwd=repo_root, env_override={SKIP_PR_SUMMARY_ENV: "1"})
    if rc != 0:
        return {
            "status": "error",
            "consistent": False,
            "requested": requested_csv,
            "error": (stderr or stdout).strip()[:300],
        }

    try:
        payload = _parse_json(stdout, "resolver-smoke")
    except SummaryError as err:
        return {
            "status": "error",
            "consistent": False,
            "requested": requested_csv,
            "error": str(err),
        }

    return {
        "status": "ok",
        "consistent": bool(payload.get("consistent", False)),
        "requested": requested_csv,
        "resolved": payload.get("resolved", []),
        "publish": payload.get("publish", []),
        "regression": payload.get("regression", []),
        "roadmap": payload.get("roadmap", []),
        "error": "",
    }


def _run_telemetry_slo(repo_root: Path, events: Path, slo_config: Path) -> Dict[str, Any]:
    slo_script = repo_root / "telemetry-slo-guard" / "scripts" / "check_telemetry_slo.py"
    if not slo_script.exists():
        return {
            "status": "error",
            "passed": False,
            "violations_count": 0,
            "violations_preview": [],
            "skills": [],
            "error": f"missing script: {slo_script}",
        }

    cmd = [
        "python3",
        str(slo_script),
        "--events",
        str(events),
        "--config",
        str(slo_config),
        "--json",
    ]
    rc, stdout, stderr = _run(cmd, cwd=repo_root)
    if rc != 0:
        return {
            "status": "error",
            "passed": False,
            "violations_count": 0,
            "violations_preview": [],
            "skills": [],
            "error": (stderr or stdout).strip()[:300],
        }

    try:
        payload = _parse_json(stdout, "telemetry-slo")
    except SummaryError as err:
        return {
            "status": "error",
            "passed": False,
            "violations_count": 0,
            "violations_preview": [],
            "skills": [],
            "error": str(err),
        }

    skills = payload.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    skills_rows: List[Dict[str, Any]] = []
    for row in skills:
        if not isinstance(row, dict):
            continue
        trend = row.get("trend", {}) if isinstance(row.get("trend"), dict) else {}
        trend_violations = trend.get("violations", []) if isinstance(trend.get("violations"), list) else []
        skills_rows.append(
            {
                "skill": row.get("skill"),
                "invocations": row.get("invocations"),
                "success_rate": row.get("success_rate"),
                "p95_duration_ms": row.get("p95_duration_ms"),
                "trend_enabled": row.get("trend_enabled"),
                "trend_violations": len(trend_violations),
            }
        )

    violations = payload.get("violations", [])
    if not isinstance(violations, list):
        violations = []

    return {
        "status": "ok",
        "passed": bool(payload.get("passed", False)),
        "violations_count": len(violations),
        "violations_preview": violations[:10],
        "skills": skills_rows,
        "error": "",
    }


def _markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Publish PR Summary")
    lines.append("")
    scoped = report.get("skills_targeted", [])
    lines.append("## Scoped --only Targets")
    if isinstance(scoped, list) and scoped:
        for skill in scoped:
            lines.append(f"- {skill}")
    else:
        lines.append("- (none)")
    lines.append("")

    resolver = report.get("resolver_consistency", {})
    lines.append("## Resolver Consistency")
    lines.append(f"- status: {resolver.get('status')}")
    lines.append(f"- consistent: {resolver.get('consistent')}")
    error = str(resolver.get("error", "")).strip()
    if error:
        lines.append(f"- error: {error}")
    lines.append("")

    trend = report.get("trend_status", {})
    lines.append("## Telemetry Trend Status")
    lines.append(f"- status: {trend.get('status')}")
    lines.append(f"- passed: {trend.get('passed')}")
    lines.append(f"- violations_count: {trend.get('violations_count')}")
    for row in trend.get("skills", [])[:10] if isinstance(trend.get("skills"), list) else []:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('skill')}: success_rate={row.get('success_rate')} p95_ms={row.get('p95_duration_ms')} trend_violations={row.get('trend_violations')}"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def run(repo_root: Path, skills_targeted: List[str], requested: List[str], events: Path, slo_config: Path) -> Dict[str, Any]:
    if not repo_root.exists() or not repo_root.is_dir():
        raise SummaryError(f"repo root does not exist: {repo_root}")
    if not events.exists():
        raise SummaryError(f"events file not found: {events}")
    if not slo_config.exists():
        raise SummaryError(f"slo config not found: {slo_config}")

    requested_csv = ",".join(requested if requested else skills_targeted)
    resolver_consistency = _run_resolver_smoke(repo_root=repo_root, requested_csv=requested_csv)
    trend_status = _run_telemetry_slo(repo_root=repo_root, events=events, slo_config=slo_config)

    return {
        "schema_version": 1,
        "skills_targeted": skills_targeted,
        "requested_only": requested if requested else skills_targeted,
        "resolver_consistency": resolver_consistency,
        "trend_status": trend_status,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate publish PR summary artifacts")
    p.add_argument("--repo-root", required=True, help="Repo root path")
    p.add_argument("--skills-targeted", required=True, help="CSV list of targeted skills")
    p.add_argument("--requested", default="", help="Optional CSV of originally requested --only values")
    p.add_argument("--events", required=True, help="Path to usage events JSONL")
    p.add_argument("--slo-config", default="", help="Optional telemetry SLO config path")
    p.add_argument("--output-json", required=True, help="Output JSON summary path")
    p.add_argument("--output-md", required=True, help="Output Markdown summary path")
    p.add_argument("--json", action="store_true", help="Emit JSON summary")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()

    try:
        skills_targeted = _parse_csv(str(args.skills_targeted))
        requested = _parse_csv(str(args.requested))
        events = _resolve_path(repo_root, str(args.events))
        if args.slo_config:
            slo_config = _resolve_path(repo_root, str(args.slo_config))
        else:
            slo_config = (repo_root / "telemetry-slo-guard" / "references" / "default_slo_config.json").resolve()

        output_json = _resolve_path(repo_root, str(args.output_json))
        output_md = _resolve_path(repo_root, str(args.output_md))

        report = run(
            repo_root=repo_root,
            skills_targeted=skills_targeted,
            requested=requested,
            events=events,
            slo_config=slo_config,
        )
    except SummaryError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(_markdown(report), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"output_json: {output_json}")
        print(f"output_md: {output_md}")
        print(f"resolver_status: {report['resolver_consistency']['status']}")
        print(f"trend_status: {report['trend_status']['status']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
