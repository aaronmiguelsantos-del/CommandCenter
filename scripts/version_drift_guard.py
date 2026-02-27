#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


VERSION_MARKER_RE = re.compile(r"\bv\d+\.\d+\.\d+\b")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")

VERSION_FILE = "version.json"
RELEASE_NOTES_FILE = "docs/RELEASE_NOTES.md"


def _run_git(repo_root: Path, args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _git_ref_exists(repo_root: Path, ref: str) -> bool:
    rc, _, _ = _run_git(repo_root, ["rev-parse", "--verify", ref])
    return rc == 0


def choose_base_ref(repo_root: Path, requested: str) -> str:
    if requested.strip():
        return requested.strip()
    github_base = os.getenv("GITHUB_BASE_REF", "").strip()
    if github_base and _git_ref_exists(repo_root, f"origin/{github_base}"):
        return f"origin/{github_base}"
    if _git_ref_exists(repo_root, "origin/main"):
        return "origin/main"
    if _git_ref_exists(repo_root, "main"):
        return "main"
    if _git_ref_exists(repo_root, "HEAD~1"):
        return "HEAD~1"
    return "HEAD"


def changed_files(repo_root: Path, base_ref: str) -> list[str]:
    rc, out, err = _run_git(repo_root, ["diff", "--name-only", f"{base_ref}...HEAD"])
    if rc != 0:
        raise RuntimeError(f"git diff --name-only failed: {err}")
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def diff_text(repo_root: Path, base_ref: str) -> str:
    rc, out, err = _run_git(repo_root, ["diff", "-U0", f"{base_ref}...HEAD"])
    if rc != 0:
        raise RuntimeError(f"git diff -U0 failed: {err}")
    return out


def marker_changes_from_diff(text: str) -> list[str]:
    hits: list[str] = []
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith(("+++", "---", "@@")):
            continue
        if not line.startswith(("+", "-")):
            continue
        content = line[1:]
        markers = VERSION_MARKER_RE.findall(content)
        if not markers:
            continue
        hits.extend(markers)
    return sorted(set(hits))


def load_version_payload(repo_root: Path) -> dict[str, Any]:
    payload = json.loads((repo_root / VERSION_FILE).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("version.json must be a JSON object")
    return payload


def version_payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    version = str(payload.get("version", "")).strip()
    release_tag = str(payload.get("release_tag", "")).strip()
    release_notes = str(payload.get("release_notes", "")).strip()
    schema_version = str(payload.get("schema_version", "")).strip()

    if schema_version != "1.0":
        errors.append("version.json schema_version must be 1.0")
    if not SEMVER_RE.match(version):
        errors.append("version.json version must be semantic (X.Y.Z)")
    if not RELEASE_TAG_RE.match(release_tag):
        errors.append("version.json release_tag must be formatted as vX.Y.Z")
    if release_tag and version and release_tag != f"v{version}":
        errors.append("version.json release_tag must match version")
    if release_notes != RELEASE_NOTES_FILE:
        errors.append("version.json release_notes must point to docs/RELEASE_NOTES.md")
    return errors


def evaluate_policy(
    *,
    changed: list[str],
    marker_changes: list[str],
    version_errors: list[str],
) -> tuple[str, list[str]]:
    errors: list[str] = []
    changed_set = set(changed)
    version_changed = VERSION_FILE in changed_set
    release_notes_changed = RELEASE_NOTES_FILE in changed_set

    errors.extend(version_errors)

    if marker_changes and not (version_changed and release_notes_changed):
        errors.append(
            "feature-level version markers changed; update both version.json and docs/RELEASE_NOTES.md in the same change"
        )

    if version_changed and not release_notes_changed:
        errors.append("version.json changed without docs/RELEASE_NOTES.md update")

    if release_notes_changed and not version_changed:
        errors.append("docs/RELEASE_NOTES.md changed without version.json update")

    return ("ok" if not errors else "needs_attention"), errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guard feature-level version marker drift.")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument("--base-ref", default="", help="Diff base ref (default: auto from CI env/origin/main)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    base_ref = choose_base_ref(repo_root, args.base_ref)

    payload = load_version_payload(repo_root)
    version_errors = version_payload_errors(payload)
    changed = changed_files(repo_root, base_ref)
    diff = diff_text(repo_root, base_ref)
    markers = marker_changes_from_diff(diff)
    status, errors = evaluate_policy(changed=changed, marker_changes=markers, version_errors=version_errors)

    report = {
        "status": status,
        "base_ref": base_ref,
        "changed_files": changed,
        "marker_changes": markers,
        "version_payload": {
            "version": str(payload.get("version", "")),
            "release_tag": str(payload.get("release_tag", "")),
            "release_notes": str(payload.get("release_notes", "")),
        },
        "errors": errors,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
