#!/usr/bin/env python3
"""Validate and publish skills into a git repo clone."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Tuple


class PublishError(Exception):
    pass


BLOCKED_NAMES = {".DS_Store"}
BLOCKED_SUFFIXES = {".pyc"}
BLOCKED_DIRS = {"__pycache__"}


def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except Exception as err:
        return 99, "", str(err)
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _extract_frontmatter_description(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    if end == -1:
        return ""
    frontmatter = text[4:end]
    for line in frontmatter.splitlines():
        match = re.match(r"^description:\s*(.*)\s*$", line)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return ""


def _is_skill_dir(path: Path) -> bool:
    return (path / "SKILL.md").exists() and (path / "agents" / "openai.yaml").exists()


def _discover_skills(source_root: Path) -> List[Path]:
    skills: List[Path] = []
    for child in sorted(source_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if child.name in {"repo-bootstrapper-repo"}:
            continue
        if _is_skill_dir(child):
            skills.append(child)
    return skills


def _validate_skill_dir(skill_dir: Path) -> List[str]:
    issues: List[str] = []
    if not (skill_dir / "SKILL.md").exists():
        issues.append(f"{skill_dir}: missing SKILL.md")
    if not (skill_dir / "agents" / "openai.yaml").exists():
        issues.append(f"{skill_dir}: missing agents/openai.yaml")

    for file in skill_dir.rglob("*"):
        if file.name in BLOCKED_NAMES:
            issues.append(f"{skill_dir}: blocked file {file.relative_to(skill_dir)}")
        if file.suffix in BLOCKED_SUFFIXES:
            issues.append(f"{skill_dir}: blocked file suffix {file.relative_to(skill_dir)}")
    for blocked in BLOCKED_DIRS:
        for directory in skill_dir.rglob(blocked):
            if directory.is_dir():
                issues.append(f"{skill_dir}: blocked directory {directory.relative_to(skill_dir)}")
    return issues


def _sync_skill(skill_dir: Path, repo_root: Path) -> str:
    dst = repo_root / skill_dir.name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(skill_dir, dst)
    return skill_dir.name


def _build_index(skills: List[Path]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for skill_dir in skills:
        description = _extract_frontmatter_description(skill_dir / "SKILL.md")
        items.append(
            {
                "name": skill_dir.name,
                "path": skill_dir.name,
                "description": description,
            }
        )
    return {
        "schema_version": 1,
        "skills": items,
    }


def _parse_semver(version: str) -> Tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3:
        raise PublishError(f"invalid semver: {version}")
    try:
        major, minor, patch = (int(x) for x in parts)
    except ValueError as err:
        raise PublishError(f"invalid semver: {version}") from err
    return major, minor, patch


def _bump_semver(version: str, bump: str) -> str:
    major, minor, patch = _parse_semver(version)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise PublishError(f"unsupported bump type: {bump}")


def _auto_bump_versions(
    source_root: Path,
    skill_dirs: List[Path],
    bump: str,
    summary: str,
    migration: str,
) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    releases_path = source_root / "data" / "skill_releases.jsonl"
    releases_path.parent.mkdir(parents=True, exist_ok=True)

    for skill_dir in skill_dirs:
        version_path = skill_dir / "skill_version.json"
        if version_path.exists():
            data = json.loads(version_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise PublishError(f"invalid json object in {version_path}")
        else:
            data = {"version": "0.1.0", "history": []}

        current = str(data.get("version", "0.1.0"))
        nxt = _bump_semver(current, bump)
        history = data.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "from": current,
                "to": nxt,
                "bump": bump,
                "summary": summary,
                "migration": migration,
                "timestamp_utc": now,
            }
        )
        data["version"] = nxt
        data["history"] = history
        data["last_updated_utc"] = now
        version_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        event = {
            "skill": skill_dir.name,
            "version": nxt,
            "bump": bump,
            "summary": summary,
            "migration": migration,
            "timestamp_utc": now,
        }
        events.append(event)

    if events:
        with releases_path.open("a", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, sort_keys=True) + "\n")
    return {
        "events": events,
        "releases_path": str(releases_path),
    }


def _only_missing_snapshot_failures(report: Dict[str, Any]) -> bool:
    skills = report.get("skills", [])
    if not isinstance(skills, list):
        return False
    saw_failure = False
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        cases = skill.get("cases", [])
        if not isinstance(cases, list):
            continue
        for case in cases:
            if not isinstance(case, dict):
                continue
            if bool(case.get("passed", False)):
                continue
            saw_failure = True
            reasons = case.get("reasons", [])
            if not isinstance(reasons, list) or any(r != "missing snapshot" for r in reasons):
                return False
    return saw_failure


def _run_regressions(source_root: Path, strict: bool, bootstrap_missing_snapshots: bool) -> Dict[str, Any]:
    runner = source_root / "skill-regression-runner" / "scripts" / "run_skill_regressions.py"
    if not runner.exists():
        raise PublishError(f"regression runner not found: {runner}")
    cmd = ["python3", str(runner), "--source-root", str(source_root), "--json"]
    if strict:
        cmd.append("--strict")
    rc, out, err = _run(cmd, cwd=source_root)
    if rc not in (0, 2):
        raise PublishError(f"regression runner failed: {err or out}")
    report = json.loads(out) if out.strip() else {}
    if not isinstance(report, dict):
        raise PublishError("invalid regression runner json output")
    report["rc"] = rc
    report["bootstrapped_snapshots"] = False

    if rc == 2 and bootstrap_missing_snapshots and _only_missing_snapshot_failures(report):
        bootstrap_cmd = ["python3", str(runner), "--source-root", str(source_root), "--update-snapshots", "--json"]
        b_rc, b_out, b_err = _run(bootstrap_cmd, cwd=source_root)
        if b_rc != 0:
            raise PublishError(f"snapshot bootstrap failed: {b_err or b_out}")
        rc, out, err = _run(cmd, cwd=source_root)
        if rc not in (0, 2):
            raise PublishError(f"regression rerun failed: {err or out}")
        report = json.loads(out) if out.strip() else {}
        if not isinstance(report, dict):
            raise PublishError("invalid regression rerun json output")
        report["rc"] = rc
        report["bootstrapped_snapshots"] = True

    return report


def _git_commit(repo_root: Path, message: str, paths: List[str]) -> Tuple[bool, str]:
    rc, out, err = _run(["git", "status", "--short"], cwd=repo_root)
    if rc != 0:
        raise PublishError(f"git status failed: {err or out}")

    add_cmd = ["git", "add", "-A", "--"] + paths
    rc, out, err = _run(add_cmd, cwd=repo_root)
    if rc != 0:
        raise PublishError(f"git add failed: {err or out}")

    rc, out, err = _run(["git", "diff", "--cached", "--name-only"], cwd=repo_root)
    if rc != 0:
        raise PublishError(f"git diff --cached failed: {err or out}")
    if not out.strip():
        return False, "no publishable changes to commit"

    rc, out, err = _run(["git", "commit", "-m", message], cwd=repo_root)
    if rc != 0:
        raise PublishError(f"git commit failed: {err or out}")
    return True, out.strip()


def _git_push(repo_root: Path) -> str:
    rc, out, err = _run(["git", "push"], cwd=repo_root)
    if rc != 0:
        raise PublishError(f"git push failed: {err or out}")
    return out.strip()


def publish(
    source_root: Path,
    repo_root: Path,
    commit: bool,
    push: bool,
    commit_message: str,
    auto_version_bump: bool,
    bump_type: str,
    bump_summary: str,
    bump_migration: str,
    run_regressions: bool,
    bootstrap_missing_snapshots: bool,
) -> Dict[str, Any]:
    if not source_root.exists() or not source_root.is_dir():
        raise PublishError(f"source root does not exist: {source_root}")
    if not repo_root.exists() or not repo_root.is_dir():
        raise PublishError(f"repo root does not exist: {repo_root}")
    if not (repo_root / ".git").exists():
        raise PublishError(f"repo root is not a git repo: {repo_root}")

    skill_dirs = _discover_skills(source_root)
    if not skill_dirs:
        raise PublishError("no skill directories found")

    issues: List[str] = []
    for skill_dir in skill_dirs:
        issues.extend(_validate_skill_dir(skill_dir))
    if issues:
        raise PublishError("validation failed:\n" + "\n".join(issues))

    version_info: Dict[str, Any] = {"events": [], "releases_path": ""}
    if auto_version_bump:
        version_info = _auto_bump_versions(
            source_root=source_root,
            skill_dirs=skill_dirs,
            bump=bump_type,
            summary=bump_summary,
            migration=bump_migration,
        )

    regression_info: Dict[str, Any] = {"ran": False}
    if run_regressions:
        regression_report = _run_regressions(
            source_root=source_root,
            strict=True,
            bootstrap_missing_snapshots=bootstrap_missing_snapshots,
        )
        regression_info = {
            "ran": True,
            "overall_passed": bool(regression_report.get("overall_passed")),
            "rc": int(regression_report.get("rc", 1)),
        }
        if not regression_info["overall_passed"]:
            raise PublishError("regression check failed; aborting publish")

    synced: List[str] = []
    for skill_dir in skill_dirs:
        synced.append(_sync_skill(skill_dir, repo_root))

    releases_src = source_root / "data" / "skill_releases.jsonl"
    if releases_src.exists():
        releases_dst = repo_root / "data" / "skill_releases.jsonl"
        releases_dst.parent.mkdir(parents=True, exist_ok=True)
        releases_dst.write_text(releases_src.read_text(encoding="utf-8"), encoding="utf-8")

    index = _build_index(skill_dirs)
    index_path = repo_root / "skills_index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    commit_info = "commit skipped"
    committed = False
    if commit:
        commit_paths = sorted(synced + ["skills_index.json", "data/skill_releases.jsonl"])
        committed, commit_info = _git_commit(repo_root, commit_message, commit_paths)

    push_info = "push skipped"
    if push:
        if not commit:
            raise PublishError("--push requires --commit")
        push_info = _git_push(repo_root)

    return {
        "schema_version": 1,
        "source_root": str(source_root),
        "repo_root": str(repo_root),
        "skills_discovered": [s.name for s in skill_dirs],
        "skills_synced": sorted(synced),
        "index_path": str(index_path),
        "versioning": version_info,
        "regressions": regression_info,
        "committed": committed,
        "commit_info": commit_info,
        "push_info": push_info,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish skills into a git repo clone")
    parser.add_argument("--source-root", required=True, help="Path containing skill folders")
    parser.add_argument("--repo-root", required=True, help="Git repo clone path to publish into")
    parser.add_argument("--commit", action="store_true", help="Commit changes")
    parser.add_argument("--push", action="store_true", help="Push changes (requires --commit)")
    parser.add_argument("--commit-message", default="Publish skill updates", help="Commit message")
    parser.add_argument("--skip-version-bump", action="store_true", help="Do not auto-bump skill versions")
    parser.add_argument("--bump", default="patch", choices=["major", "minor", "patch"], help="Auto-bump type")
    parser.add_argument("--version-summary", default="Automated publish", help="Version bump summary")
    parser.add_argument("--version-migration", default="", help="Version bump migration note")
    parser.add_argument("--skip-regressions", action="store_true", help="Skip regression runner precheck")
    parser.add_argument(
        "--no-bootstrap-missing-snapshots",
        action="store_true",
        help="Do not auto-create snapshots when regression failures are only missing snapshots",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    source_root = Path(args.source_root).expanduser().resolve()
    repo_root = Path(args.repo_root).expanduser().resolve()

    try:
        report = publish(
            source_root=source_root,
            repo_root=repo_root,
            commit=bool(args.commit),
            push=bool(args.push),
            commit_message=args.commit_message,
            auto_version_bump=not args.skip_version_bump,
            bump_type=args.bump,
            bump_summary=args.version_summary,
            bump_migration=args.version_migration,
            run_regressions=not args.skip_regressions,
            bootstrap_missing_snapshots=not args.no_bootstrap_missing_snapshots,
        )
    except PublishError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"source_root: {report['source_root']}")
        print(f"repo_root: {report['repo_root']}")
        print("skills_synced:")
        for name in report["skills_synced"]:
            print(f"- {name}")
        print(f"committed: {report['committed']}")
        print(f"commit_info: {report['commit_info']}")
        print(f"push_info: {report['push_info']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
