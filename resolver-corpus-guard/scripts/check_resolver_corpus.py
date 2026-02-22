#!/usr/bin/env python3
"""Run resolver corpus checks against skill-source-resolver."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Tuple


class CorpusError(Exception):
    pass


def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except Exception as err:
        return 99, "", f"RUNNER_ERROR: {err}"
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise CorpusError(f"invalid json file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise CorpusError(f"json file must be object: {path}")
    return obj


def _tail(text: str, n: int = 20) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _resolve_rel(repo_root: Path, raw: str) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = repo_root / p
    return p.resolve()


def _run_case(repo_root: Path, resolver_script: Path, case: Dict[str, Any]) -> Dict[str, Any]:
    case_id = str(case.get("id", "")).strip()
    if not case_id:
        raise CorpusError("corpus case missing id")

    start_raw = str(case.get("start", "")).strip()
    if not start_raw:
        raise CorpusError(f"case {case_id} missing start")
    start = _resolve_rel(repo_root, start_raw)
    max_depth = _as_int(case.get("max_depth", 4), 4)
    min_skills = _as_int(case.get("min_skills", 1), 1)
    prefer_repo_root = _as_bool(case.get("prefer_repo_root"), False)
    no_ancestor_search = _as_bool(case.get("no_ancestor_search"), False)
    expected_resolved = _as_bool(case.get("expected_resolved"), True)
    expected_root_suffix = str(case.get("expected_root_suffix", "")).strip()

    cmd = [
        "python3",
        str(resolver_script),
        "--start",
        str(start),
        "--max-depth",
        str(max_depth),
        "--min-skills",
        str(min_skills),
        "--strict",
        "--json",
    ]
    if prefer_repo_root:
        cmd.append("--prefer-repo-root")
    if no_ancestor_search:
        cmd.append("--no-ancestor-search")

    rc, stdout, stderr = _run(cmd, cwd=repo_root)
    payload: Dict[str, Any] = {}
    try:
        obj = json.loads(stdout) if stdout.strip() else {}
        if isinstance(obj, dict):
            payload = obj
    except Exception:
        payload = {}

    resolved = bool(payload.get("resolved", False))
    resolved_root = str(payload.get("resolved_root", ""))
    passed = True
    reasons: List[str] = []

    if expected_resolved != resolved:
        passed = False
        reasons.append(f"resolved mismatch expected={expected_resolved} got={resolved}")
    if expected_resolved and expected_root_suffix:
        if not resolved_root.endswith(expected_root_suffix):
            passed = False
            reasons.append(f"resolved_root mismatch expected suffix={expected_root_suffix} got={resolved_root}")
    if not expected_resolved and rc not in (0, 2):
        passed = False
        reasons.append(f"unexpected exit code for unresolved case: {rc}")
    if expected_resolved and rc != 0:
        passed = False
        reasons.append(f"unexpected exit code for resolved case: {rc}")

    return {
        "id": case_id,
        "start": str(start),
        "command": cmd,
        "expected_resolved": expected_resolved,
        "expected_root_suffix": expected_root_suffix,
        "rc": rc,
        "resolved": resolved,
        "resolved_root": resolved_root,
        "passed": passed,
        "reasons": reasons,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def run(repo_root: Path, corpus_path: Path) -> Dict[str, Any]:
    resolver_script = repo_root / "skill-source-resolver" / "scripts" / "resolve_skill_source.py"
    if not resolver_script.exists():
        raise CorpusError(f"resolver script not found: {resolver_script}")

    corpus = _load_json(corpus_path)
    rows = corpus.get("cases")
    if not isinstance(rows, list) or not rows:
        raise CorpusError("corpus must contain non-empty cases[]")

    cases: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cases.append(_run_case(repo_root=repo_root, resolver_script=resolver_script, case=row))

    overall_passed = all(bool(row.get("passed", False)) for row in cases)
    return {
        "schema_version": 1,
        "repo_root": str(repo_root),
        "corpus_path": str(corpus_path),
        "overall_passed": overall_passed,
        "cases": cases,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check resolver behavior against a corpus")
    p.add_argument("--repo-root", default=".", help="Repo root path")
    p.add_argument("--corpus", default="", help="Optional corpus JSON path")
    p.add_argument("--strict", action="store_true", help="Exit 2 when any case fails")
    p.add_argument("--json", action="store_true", help="Emit JSON output")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    corpus_path = (
        _resolve_rel(repo_root, str(args.corpus))
        if args.corpus
        else (repo_root / "resolver-corpus-guard" / "references" / "resolver_corpus.json").resolve()
    )

    try:
        report = run(repo_root=repo_root, corpus_path=corpus_path)
    except CorpusError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"overall_passed: {report['overall_passed']}")
        for row in report["cases"]:
            state = "PASS" if row.get("passed") else "FAIL"
            print(f"- {state} {row.get('id')}")

    if args.strict and not bool(report.get("overall_passed", False)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
