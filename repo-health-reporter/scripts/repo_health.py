#!/usr/bin/env python3
"""Deterministic repository health reporter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape


class HealthError(Exception):
    pass


def detect_stack(target: Path) -> str:
    if (target / "package.json").exists():
        return "node"
    if any((target / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py")):
        return "python"
    if any(target.glob("*.py")):
        return "python"
    for root in ("core", "app", "scripts", "tests"):
        root_path = target / root
        if root_path.exists() and any(root_path.rglob("*.py")):
            return "python"
    if any(target.glob("*.js")) or any(target.glob("*.ts")):
        return "node"
    return "unknown"


def _run_command(command: List[str], cwd: Path, timeout: int = 120) -> Tuple[bool, int, str]:
    try:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError) as err:
        return False, 1, str(err)
    text = (proc.stdout + "\n" + proc.stderr).strip()
    tail = "\n".join(text.splitlines()[-8:])
    return proc.returncode == 0, proc.returncode, tail


def _dependency_risk_flags(target: Path) -> List[str]:
    flags: List[str] = []
    req = target / "requirements.txt"
    if req.exists():
        lines = req.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "==" not in stripped and not stripped.startswith("-"):
                flags.append("unbounded-python-dependencies")
                break
    pkg = target / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            deps = {}
            deps.update(data.get("dependencies", {}))
            deps.update(data.get("devDependencies", {}))
            if any(str(v).startswith("^") or str(v).startswith("~") for v in deps.values()):
                flags.append("floating-node-dependencies")
        except json.JSONDecodeError:
            flags.append("invalid-package-json")
    return sorted(set(flags))


def _policy_flags(target: Path) -> List[str]:
    flags: List[str] = []
    checks = [
        ("todo-in-core-paths", r"TODO: implement later|TODO", target / "core"),
        ("hidden-state-default-none", r"os\.getenv\([^)]*,\s*None\)", target),
    ]
    rg_available = shutil.which("rg") is not None
    for flag, pattern, scan_path in checks:
        if not scan_path.exists():
            continue
        if rg_available:
            cmd = ["rg", "-n", "-i", pattern, str(scan_path)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0:
                flags.append(flag)
        else:
            regex = re.compile(pattern, flags=re.IGNORECASE)
            files = [scan_path] if scan_path.is_file() else [f for f in scan_path.rglob("*") if f.is_file()]
            for file in files:
                text = file.read_text(encoding="utf-8", errors="ignore")
                if regex.search(text):
                    flags.append(flag)
                    break
    return sorted(set(flags))


def _git_clean_check(target: Path) -> Tuple[bool, str, str]:
    inside, _, _ = _run_command(["git", "rev-parse", "--is-inside-work-tree"], cwd=target, timeout=10)
    if not inside:
        return True, "skipped", "not a git repository"
    clean, _, output = _run_command(["git", "status", "--porcelain"], cwd=target, timeout=20)
    if not clean:
        return False, "failed", output
    return output.strip() == "", "ok" if output.strip() == "" else "failed", "clean" if output.strip() == "" else output


def _build_checks(target: Path, stack: str) -> List[Dict[str, object]]:
    checks: List[Dict[str, object]] = []
    required = ["README.md", ".env.example", "data", "tests"]
    if stack in ("python", "unknown"):
        required.append("core")

    for path in required:
        exists = (target / path).exists()
        checks.append(
            {
                "id": f"required:{path}",
                "severity": "high",
                "passed": exists,
                "details": "present" if exists else f"missing {path}",
            }
        )

    if stack == "python":
        ok, code, tail = _run_command(
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], cwd=target, timeout=120
        )
        checks.append(
            {
                "id": "tests:python-unittest",
                "severity": "high",
                "passed": ok,
                "details": "pass" if ok else f"exit={code} {tail}",
            }
        )
    elif stack == "node":
        ok, code, tail = _run_command(["npm", "test"], cwd=target, timeout=180)
        checks.append(
            {
                "id": "tests:npm-test",
                "severity": "high",
                "passed": ok,
                "details": "pass" if ok else f"exit={code} {tail}",
            }
        )
    else:
        checks.append(
            {
                "id": "tests:unknown-stack",
                "severity": "medium",
                "passed": False,
                "details": "cannot infer test command for unknown stack",
            }
        )

    git_ok, git_state, git_detail = _git_clean_check(target)
    checks.append(
        {
            "id": "git:clean",
            "severity": "low",
            "passed": git_ok,
            "details": f"{git_state} {git_detail}",
        }
    )
    return checks


def _score(checks: List[Dict[str, object]], flags: List[str]) -> int:
    score = 100
    for check in checks:
        if check["passed"]:
            continue
        sev = check["severity"]
        if sev == "high":
            score -= 15
        elif sev == "medium":
            score -= 8
        else:
            score -= 3
    score -= min(20, len(flags) * 5)
    return max(0, score)


def _status(score: int, checks: List[Dict[str, object]]) -> str:
    high_failures = [c for c in checks if c["severity"] == "high" and not c["passed"]]
    if high_failures:
        return "unhealthy"
    any_failures = [c for c in checks if not c["passed"]]
    if any_failures:
        return "degraded"
    return "healthy" if score >= 85 else "degraded"


def _build_junit(report: Dict[str, object]) -> str:
    checks = report["checks"]
    tests = len(checks)
    failures = len([c for c in checks if not c["passed"]])
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="repo-health" tests="{tests}" failures="{failures}" skipped="0">',
    ]
    for check in checks:
        name = escape(str(check["id"]))
        lines.append(f'  <testcase classname="repo-health" name="{name}">')
        if not check["passed"]:
            lines.append(f'    <failure message="{escape(str(check["details"]))}"/>')
        lines.append("  </testcase>")
    lines.append(f'  <system-out>{escape("status=" + str(report["status"]))}</system-out>')
    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"


def _install_entrypoint(target: Path, force: bool) -> List[str]:
    created: List[str] = []
    app_init = target / "app" / "__init__.py"
    app_main = target / "app" / "main.py"
    script_target = target / "scripts" / "repo_health.py"

    if (app_main.exists() or script_target.exists()) and not force:
        raise HealthError("entrypoint already exists; rerun with --force to overwrite install artifacts")

    app_init.parent.mkdir(parents=True, exist_ok=True)
    script_target.parent.mkdir(parents=True, exist_ok=True)

    app_init.write_text("", encoding="utf-8")
    created.append("app/__init__.py")

    wrapper = (
        '"""App entrypoint wrapper for health reporting."""\n\n'
        "from __future__ import annotations\n\n"
        "import argparse\n"
        "from pathlib import Path\n"
        "import subprocess\n"
        "import sys\n\n\n"
        "def parse_args(argv: list[str]) -> argparse.Namespace:\n"
        "    parser = argparse.ArgumentParser(description='App CLI')\n"
        "    sub = parser.add_subparsers(dest='cmd')\n"
        "    report = sub.add_parser('report')\n"
        "    report_sub = report.add_subparsers(dest='report_cmd')\n"
        "    health = report_sub.add_parser('health')\n"
        "    health.add_argument('--json', action='store_true')\n"
        "    health.add_argument('--strict', action='store_true')\n"
        "    return parser.parse_args(argv)\n\n\n"
        "def main(argv: list[str]) -> int:\n"
        "    args = parse_args(argv)\n"
        "    if args.cmd != 'report' or args.report_cmd != 'health':\n"
        "        print(\"usage: python3 -m app.main report health [--json] [--strict]\", file=sys.stderr)\n"
        "        return 2\n"
        "    root = Path(__file__).resolve().parents[1]\n"
        "    health_script = root / 'scripts' / 'repo_health.py'\n"
        "    cmd = [sys.executable, str(health_script), '--target', str(root)]\n"
        "    if args.json:\n"
        "        cmd.append('--json')\n"
        "    if args.strict:\n"
        "        cmd.append('--strict')\n"
        "    proc = subprocess.run(cmd)\n"
        "    return proc.returncode\n\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main(sys.argv[1:]))\n"
    )
    app_main.write_text(wrapper, encoding="utf-8")
    created.append("app/main.py")

    source = Path(__file__).resolve()
    script_target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    created.append("scripts/repo_health.py")
    return created


def build_report(target: Path) -> Dict[str, object]:
    if not target.exists() or not target.is_dir():
        raise HealthError(f"target '{target}' must be an existing directory")

    stack = detect_stack(target)
    checks = _build_checks(target=target, stack=stack)
    risk_flags = sorted(set(_dependency_risk_flags(target) + _policy_flags(target)))
    score = _score(checks, risk_flags)
    status = _status(score, checks)
    fixes = [check["details"] for check in checks if not check["passed"]]
    if risk_flags:
        fixes.extend(f"resolve risk flag: {flag}" for flag in risk_flags)
    report = {
        "target": str(target),
        "stack": stack,
        "status": status,
        "score": score,
        "checks": checks,
        "risk_flags": risk_flags,
        "recommended_fixes": fixes[:12],
    }
    return report


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report deterministic repository health")
    parser.add_argument("--target", required=True, help="Repository path")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero unless status is healthy")
    parser.add_argument("--emit-junit", action="store_true", help="Write JUnit XML summary")
    parser.add_argument("--junit-path", default="data/health_junit.xml", help="JUnit path (absolute or target-relative)")
    parser.add_argument("--install-entrypoint", action="store_true", help="Install app.main health entrypoint")
    parser.add_argument("--force", action="store_true", help="Overwrite install artifacts when installing entrypoint")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    target = Path(args.target).expanduser().resolve()
    try:
        installed: List[str] = []
        if args.install_entrypoint:
            installed = _install_entrypoint(target=target, force=args.force)

        report = build_report(target)
        if installed:
            report["installed_artifacts"] = installed

        if args.emit_junit:
            junit_path = Path(args.junit_path)
            if not junit_path.is_absolute():
                junit_path = target / junit_path
            junit_path.parent.mkdir(parents=True, exist_ok=True)
            junit_path.write_text(_build_junit(report), encoding="utf-8")

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"repo: {report['target']}")
            print(f"stack: {report['stack']}")
            print(f"status: {report['status']}")
            print(f"score: {report['score']}")
            print("checks:")
            for check in report["checks"]:
                state = "PASS" if check["passed"] else "FAIL"
                print(f"- {state} {check['id']} ({check['severity']}): {check['details']}")
            if report["risk_flags"]:
                print("risk_flags:")
                for flag in report["risk_flags"]:
                    print(f"- {flag}")

    except HealthError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.strict and report["status"] != "healthy":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
