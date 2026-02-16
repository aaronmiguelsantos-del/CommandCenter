#!/usr/bin/env python3
"""Validate and publish skills into a git repo clone."""

from __future__ import annotations

import argparse
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

    synced: List[str] = []
    for skill_dir in skill_dirs:
        synced.append(_sync_skill(skill_dir, repo_root))

    index = _build_index(skill_dirs)
    index_path = repo_root / "skills_index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    commit_info = "commit skipped"
    committed = False
    if commit:
        commit_paths = sorted(synced + ["skills_index.json"])
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
