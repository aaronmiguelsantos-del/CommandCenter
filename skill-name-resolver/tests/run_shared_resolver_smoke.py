#!/usr/bin/env python3
"""Shared smoke suite for --only resolution parity across publish/regression/roadmap."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Tuple


class SmokeError(Exception):
    pass


def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except Exception as err:
        return 99, "", f"RUNNER_ERROR: {err}"
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _load_json_text(text: str, label: str) -> Dict[str, Any]:
    try:
        obj = json.loads(text)
    except Exception as err:
        raise SmokeError(f"{label} returned invalid json: {err}") from err
    if not isinstance(obj, dict):
        raise SmokeError(f"{label} returned invalid payload")
    return obj


def _load_requested(corpus_path: Path) -> str:
    try:
        obj = json.loads(corpus_path.read_text(encoding="utf-8"))
    except Exception as err:
        raise SmokeError(f"invalid corpus file {corpus_path}: {err}") from err
    if not isinstance(obj, dict):
        raise SmokeError(f"invalid corpus file shape: {corpus_path}")
    requested = str(obj.get("requested", "")).strip()
    if not requested:
        raise SmokeError("corpus requested value is empty")
    return requested


def _copy_repo(src: Path, dst: Path) -> None:
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            "*.pyc",
            ".DS_Store",
            ".pytest_cache",
        ),
    )


def _must_list(payload: Dict[str, Any], key: str, label: str) -> List[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SmokeError(f"{label} missing {key}[]")
    return [v for v in value if v]


def run_smoke(repo_root: Path, requested: str) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="resolver-smoke-") as td:
        tmp = Path(td)
        source = tmp / "source-repo"
        _copy_repo(repo_root, source)

        publish_target = tmp / "publish-target"
        publish_target.mkdir(parents=True, exist_ok=True)
        rc, _, err = _run(["git", "init", "-q"], cwd=publish_target)
        if rc != 0:
            raise SmokeError(f"git init failed: {err}")

        name_cmd = [
            "python3",
            str(source / "skill-name-resolver" / "scripts" / "resolve_skill_names.py"),
            "--source-root",
            str(source),
            "--requested",
            requested,
            "--strict",
            "--json",
        ]
        rc, out, err = _run(name_cmd, cwd=source)
        if rc != 0:
            raise SmokeError(f"name resolver failed: {err or out}")
        name_report = _load_json_text(out, "name resolver")
        name_resolved = _must_list(name_report, "resolved", "name resolver")

        publish_cmd = [
            "python3",
            str(source / "skill-publisher" / "scripts" / "publish_skills.py"),
            "--source-root",
            str(source),
            "--repo-root",
            str(publish_target),
            "--only",
            requested,
            "--skip-version-bump",
            "--skip-regressions",
            "--skip-rollup-contract",
            "--json",
        ]
        rc, out, err = _run(publish_cmd, cwd=source)
        if rc != 0:
            raise SmokeError(f"publish failed: {err or out}")
        publish_report = _load_json_text(out, "publish")
        publish_resolved = _must_list(publish_report, "skills_targeted", "publish")

        regression_cmd = [
            "python3",
            str(source / "skill-regression-runner" / "scripts" / "run_skill_regressions.py"),
            "--source-root",
            str(source),
            "--only",
            requested,
            "--json",
        ]
        rc, out, err = _run(regression_cmd, cwd=source)
        if rc != 0:
            raise SmokeError(f"regression runner failed: {err or out}")
        regression_report = _load_json_text(out, "regression")
        regression_resolved = _must_list(regression_report, "skills_targeted", "regression")

        roadmap_cmd = [
            "python3",
            str(source / "roadmap-pr-prep" / "scripts" / "prepare_roadmap_pr.py"),
            "--repo-root",
            str(source),
            "--releases",
            str(source / "skill-adoption-analytics" / "tests" / "fixtures" / "rollup_releases.jsonl"),
            "--events",
            str(source / "skill-adoption-analytics" / "tests" / "fixtures" / "rollup_events.jsonl"),
            "--output-dir",
            str(tmp / "roadmap-output"),
            "--stamp",
            "2026-02-22",
            "--only",
            requested,
            "--json",
        ]
        rc, out, err = _run(roadmap_cmd, cwd=source)
        if rc != 0:
            raise SmokeError(f"roadmap prep failed: {err or out}")
        roadmap_report = _load_json_text(out, "roadmap")
        roadmap_resolved = _must_list(roadmap_report, "only_skills", "roadmap")

        consistent = (
            name_resolved == publish_resolved
            and publish_resolved == regression_resolved
            and regression_resolved == roadmap_resolved
        )
        if not consistent:
            raise SmokeError(
                "resolver mismatch: "
                f"name={name_resolved} publish={publish_resolved} "
                f"regression={regression_resolved} roadmap={roadmap_resolved}"
            )

        return {
            "schema_version": 1,
            "requested": requested,
            "resolved": name_resolved,
            "publish": publish_resolved,
            "regression": regression_resolved,
            "roadmap": roadmap_resolved,
            "consistent": True,
        }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Shared resolver smoke suite")
    p.add_argument(
        "--corpus",
        default="",
        help="Path to input corpus json with requested CSV",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    if args.corpus:
        corpus_path = Path(args.corpus).expanduser()
        if not corpus_path.is_absolute():
            corpus_path = (Path.cwd() / corpus_path).resolve()
    else:
        corpus_path = (Path(__file__).resolve().parent / "fixtures" / "shared_only_corpus.json").resolve()

    try:
        requested = _load_requested(corpus_path)
        report = run_smoke(repo_root=repo_root, requested=requested)
    except SmokeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"requested: {report['requested']}")
        print(f"resolved: {','.join(report['resolved'])}")
        print(f"consistent: {report['consistent']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
