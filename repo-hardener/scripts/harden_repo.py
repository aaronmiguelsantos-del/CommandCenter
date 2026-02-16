#!/usr/bin/env python3
"""Harden an existing repository with deterministic, merge-safe defaults."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape


class HardeningError(Exception):
    pass


def detect_stack(target: Path, forced: str) -> str:
    if forced != "auto":
        return forced
    if (target / "package.json").exists():
        return "node"
    if any((target / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py")):
        return "python"
    if any(target.glob("*.py")):
        return "python"
    if any(target.glob("*.js")) or any(target.glob("*.ts")):
        return "node"
    return "unknown"


def _write_file(path: Path, content: str, dry_run: bool, overwrite: bool = False) -> Tuple[bool, str]:
    if path.exists() and not overwrite:
        return False, "skipped"
    if dry_run:
        return True, "would-write"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True, "written"


def _append_readme_section(path: Path, section: str, dry_run: bool) -> bool:
    header = "## Hardening"
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if header in current:
            return False
        updated = current.rstrip() + "\n\n" + section.strip() + "\n"
        if not dry_run:
            path.write_text(updated, encoding="utf-8")
        return True
    if not dry_run:
        path.write_text("# Project\n\n" + section.strip() + "\n", encoding="utf-8")
    return True


def _python_templates() -> Dict[str, str]:
    return {
        "core/__init__.py": "",
        "core/main.py": (
            '"""Default one-command Python entrypoint."""\n\n'
            "from __future__ import annotations\n\n"
            "import os\n\n\n"
            "def run() -> str:\n"
            "    app_env = os.getenv(\"APP_ENV\", \"dev\")\n"
            "    log_level = os.getenv(\"LOG_LEVEL\", \"INFO\")\n"
            "    data_dir = os.getenv(\"DATA_DIR\", \"data\")\n"
            "    return f\"app_env={app_env} log_level={log_level} data_dir={data_dir}\"\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    print(run())\n"
        ),
        "tests/test_smoke.py": (
            "import unittest\n\n"
            "from core.main import run\n\n\n"
            "class SmokeTest(unittest.TestCase):\n"
            "    def test_run_returns_status_line(self) -> None:\n"
            "        result = run()\n"
            "        self.assertIn(\"app_env=\", result)\n"
            "        self.assertIn(\"log_level=\", result)\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    unittest.main()\n"
        ),
        ".env.example": "APP_ENV=dev\nLOG_LEVEL=INFO\nDATA_DIR=data\n",
    }


def _node_test_template() -> str:
    return (
        "const assert = require('assert');\n\n"
        "function smoke() {\n"
        "  const env = process.env.APP_ENV || 'dev';\n"
        "  return `app_env=${env}`;\n"
        "}\n\n"
        "assert.ok(smoke().includes('app_env='));\n"
        "console.log('smoke ok');\n"
    )


def _find_python_entry(target: Path) -> str:
    candidates = [
        "app.py",
        "main.py",
        "server.py",
    ]
    for name in candidates:
        if (target / name).exists():
            module = name.replace(".py", "")
            return module
    return "core.main"


def _safe_refactor_python(target: Path, dry_run: bool) -> Tuple[bool, str]:
    entry_module = _find_python_entry(target)
    content = (
        '"""Safe wrapper entrypoint; does not remove existing commands."""\n\n'
        "from __future__ import annotations\n\n"
        "import importlib\n\n"
        "def main() -> int:\n"
        f"    module_name = \"{entry_module}\"\n"
        "    module = importlib.import_module(module_name)\n"
        "    if hasattr(module, \"run\"):\n"
        "        result = module.run()\n"
        "        if result is not None:\n"
        "            print(result)\n"
        "        return 0\n"
        "    if hasattr(module, \"app\"):\n"
        "        print(\"module exposes 'app'; run existing server command as needed\")\n"
        "        return 0\n"
        "    print(\"entry module loaded but no run() found\")\n"
        "    return 0\n\n\n"
        "if __name__ == \"__main__\":\n"
        "    raise SystemExit(main())\n"
    )
    return _write_file(target / "run.py", content, dry_run=dry_run, overwrite=False)


def _safe_refactor_node(target: Path, dry_run: bool, risk_flags: List[str]) -> Tuple[bool, str]:
    package_json = target / "package.json"
    if not package_json.exists():
        risk_flags.append("missing-package-json-for-node-safe-refactor")
        return False, "skipped"
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        risk_flags.append("invalid-package-json")
        return False, "skipped"

    scripts = data.get("scripts", {})
    changed = False
    if "dev" not in scripts:
        if (target / "src" / "index.js").exists():
            scripts["dev"] = "node src/index.js"
        elif (target / "index.js").exists():
            scripts["dev"] = "node index.js"
        else:
            scripts["dev"] = "node index.js"
            if not (target / "index.js").exists():
                _write_file(
                    target / "index.js",
                    "console.log('dev entrypoint placeholder');\n",
                    dry_run=dry_run,
                    overwrite=False,
                )
        changed = True
    if "test" not in scripts:
        scripts["test"] = "node tests/test_smoke.js"
        changed = True

    if not changed:
        return False, "skipped"
    data["scripts"] = scripts
    if not dry_run:
        package_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True, "written"


def _has_framework_dep_in_requirements(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(r"^\s*(django|fastapi|flask|bottle|tornado)\b", flags=re.IGNORECASE | re.MULTILINE)
    return pattern.search(text) is not None


def _has_framework_dep_in_pyproject(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    # Keep parsing light: match common dependency declarations across PEP 621 and Poetry styles.
    pattern = re.compile(
        r"(django|fastapi|flask|bottle|tornado)",
        flags=re.IGNORECASE,
    )
    return pattern.search(text) is not None


def _has_framework_dep_in_package_json(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    deps = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))
    names = {name.lower() for name in deps.keys()}
    frameworks = {"express", "next", "react", "vue", "angular", "svelte", "nestjs", "fastify"}
    return bool(names.intersection(frameworks))


def _scan_with_evidence(path: Path, pattern: str, max_hits: int = 10) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    rg_available = shutil.which("rg") is not None
    evidence: List[Dict[str, object]] = []
    if rg_available:
        cmd = ["rg", "-n", "-i", "--no-heading", pattern, str(path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return []
        for line in proc.stdout.splitlines()[:max_hits]:
            parts = line.split(":", 2)
            if len(parts) == 3:
                file_name, line_num, snippet = parts
            elif len(parts) == 2:
                file_name = str(path)
                line_num, snippet = parts
            else:
                continue
            try:
                line_int = int(line_num)
            except ValueError:
                line_int = 0
            evidence.append({"file": file_name, "line": line_int, "snippet": snippet.strip()})
        return evidence

    regex = re.compile(pattern, flags=re.IGNORECASE)
    files = [path] if path.is_file() else [f for f in path.rglob("*") if f.is_file()]
    for file in files:
        try:
            lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, start=1):
            if regex.search(line):
                evidence.append({"file": str(file), "line": idx, "snippet": line.strip()})
                if len(evidence) >= max_hits:
                    return evidence
    return evidence


def run_policy_checks(target: Path) -> Tuple[List[str], List[Dict[str, object]]]:
    checks = [
        ("todo-in-core-paths", r"TODO: implement later|TODO", target / "core"),
        ("hidden-state-default-none", r"os\.getenv\([^)]*,\s*None\)", target),
    ]

    issues: List[str] = []
    details: List[Dict[str, object]] = []
    for name, pattern, scan_path in checks:
        evidence = _scan_with_evidence(scan_path, pattern)
        if evidence:
            issues.append(name)
            details.append({"flag": name, "evidence": evidence})

    framework_evidence: List[Dict[str, object]] = []
    req = target / "requirements.txt"
    if _has_framework_dep_in_requirements(req):
        framework_evidence.extend(_scan_with_evidence(req, r"django|fastapi|flask|bottle|tornado"))
    pyproject = target / "pyproject.toml"
    if _has_framework_dep_in_pyproject(pyproject):
        py_evidence = _scan_with_evidence(pyproject, r"django|fastapi|flask|bottle|tornado")
        if py_evidence:
            framework_evidence.extend(py_evidence)
        else:
            framework_evidence.append(
                {"file": str(pyproject), "line": 1, "snippet": "framework dependency detected in pyproject.toml"}
            )
    package_json = target / "package.json"
    if _has_framework_dep_in_package_json(package_json):
        framework_evidence.append(
            {
                "file": str(package_json),
                "line": 1,
                "snippet": "framework dependency detected in dependencies/devDependencies",
            }
        )
    if framework_evidence:
        issues.append("framework-bloat-risk")
        details.append({"flag": "framework-bloat-risk", "evidence": framework_evidence[:10]})

    return sorted(set(issues)), details


def _timeout_overrides_for_commands(stack: str, commands: List[str]) -> Dict[str, int]:
    overrides: Dict[str, int] = {}
    if stack == "node":
        for command in commands:
            if command == "npm install":
                overrides[command] = 300
            elif command == "npm test":
                overrides[command] = 180
    else:
        for command in commands:
            if "unittest discover" in command:
                overrides[command] = 90
            elif command == "python3 -m core.main":
                overrides[command] = 30
    return overrides


def _parse_user_timeout_overrides(raw_overrides: List[str], commands: List[str]) -> Dict[str, int]:
    parsed: Dict[str, int] = {}
    for raw in raw_overrides:
        if "=" not in raw:
            raise HardeningError(
                f"invalid --timeout-override value '{raw}'; expected '<command>=<seconds>'"
            )
        command, seconds_text = raw.rsplit("=", 1)
        command = command.strip()
        if command not in commands:
            raise HardeningError(
                f"unknown command in --timeout-override '{command}'; use one of: {commands}"
            )
        try:
            seconds = int(seconds_text.strip())
        except ValueError as err:
            raise HardeningError(
                f"invalid timeout seconds '{seconds_text}' for command '{command}'"
            ) from err
        if seconds < 1:
            raise HardeningError(
                f"timeout for command '{command}' must be >= 1 second"
            )
        parsed[command] = seconds
    return parsed


def _parse_policy_fail_on(raw: str) -> List[str]:
    if not raw.strip():
        return []
    return sorted({part.strip() for part in raw.split(",") if part.strip()})


def _build_junit_xml(manifest: Dict[str, object], exit_code: int) -> str:
    cases: List[Dict[str, object]] = []

    strict = bool(manifest.get("strict", False))
    score = int(manifest.get("scorecard", {}).get("total", 0))  # type: ignore[union-attr]
    min_score = int(manifest.get("min_score", 0))
    cases.append(
        {
            "name": "score-threshold",
            "failure": strict and score < min_score,
            "message": f"score={score} min_score={min_score}",
        }
    )

    command_checks = manifest.get("command_checks", [])
    if isinstance(command_checks, list):
        for check in command_checks:
            if not isinstance(check, dict):
                continue
            command = str(check.get("command", "unknown-command"))
            skipped = bool(check.get("skipped", False))
            passed = bool(check.get("passed", False))
            timed_out = bool(check.get("timed_out", False))
            stderr_tail = str(check.get("stderr_tail", ""))
            if skipped:
                cases.append(
                    {
                        "name": f"command:{command}",
                        "failure": False,
                        "skipped": True,
                        "message": "skipped",
                    }
                )
            else:
                message = "ok" if passed else ("timed out" if timed_out else stderr_tail or "failed")
                cases.append(
                    {
                        "name": f"command:{command}",
                        "failure": not passed,
                        "message": message,
                    }
                )

    policy_failed = "policy-gate-failed" in manifest.get("risk_flags", [])
    policy_triggered = manifest.get("policy_fail_triggered", [])
    cases.append(
        {
            "name": "policy-gate",
            "failure": policy_failed,
            "message": ",".join(policy_triggered) if isinstance(policy_triggered, list) else "",
        }
    )

    failures = sum(1 for case in cases if case.get("failure"))
    skipped = sum(1 for case in cases if case.get("skipped"))
    tests = len(cases)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="repo-hardener" tests="{tests}" failures="{failures}" skipped="{skipped}">',
    ]
    for case in cases:
        name = escape(str(case.get("name", "unnamed")))
        lines.append(f'  <testcase classname="repo-hardener" name="{name}">')
        if case.get("skipped"):
            lines.append('    <skipped message="skipped"/>')
        if case.get("failure"):
            msg = escape(str(case.get("message", "failed")))
            lines.append(f'    <failure message="{msg}"/>')
        lines.append("  </testcase>")
    lines.append(
        f'  <system-out>{escape("exit_code=" + str(exit_code))}</system-out>'
    )
    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"


def verify_commands(
    target: Path,
    commands: List[str],
    dry_run: bool,
    default_timeout_seconds: int,
    timeout_overrides: Dict[str, int],
) -> List[Dict[str, object]]:
    if dry_run:
        return [
            {
                "command": command,
                "passed": False,
                "returncode": None,
                "stdout_tail": "",
                "stderr_tail": "",
                "skipped": True,
                "timeout_seconds": timeout_overrides.get(command, default_timeout_seconds),
                "timed_out": False,
            }
            for command in commands
        ]

    results: List[Dict[str, object]] = []
    for command in commands:
        timeout_seconds = timeout_overrides.get(command, default_timeout_seconds)
        try:
            proc = subprocess.run(
                shlex.split(command),
                cwd=target,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            stdout_tail = "\n".join(proc.stdout.strip().splitlines()[-5:])
            stderr_tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
            results.append(
                {
                    "command": command,
                    "passed": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                    "skipped": False,
                    "timeout_seconds": timeout_seconds,
                    "timed_out": False,
                }
            )
        except subprocess.TimeoutExpired as err:
            stdout_tail = "\n".join((err.stdout or "").strip().splitlines()[-5:])
            stderr_tail = "\n".join((err.stderr or "").strip().splitlines()[-5:])
            results.append(
                {
                    "command": command,
                    "passed": False,
                    "returncode": None,
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                    "skipped": False,
                    "timeout_seconds": timeout_seconds,
                    "timed_out": True,
                }
            )
        except (subprocess.SubprocessError, ValueError) as err:
            results.append(
                {
                    "command": command,
                    "passed": False,
                    "returncode": None,
                    "stdout_tail": "",
                    "stderr_tail": str(err),
                    "skipped": False,
                    "timeout_seconds": timeout_seconds,
                    "timed_out": False,
                }
            )
    return results


def build_readme_section(stack: str) -> str:
    if stack == "node":
        return (
            "## Hardening\n\n"
            "This repository was hardened for deterministic local operation.\n\n"
            "### Run\n\n"
            "```bash\n"
            "npm run dev\n"
            "```\n\n"
            "### Test\n\n"
            "```bash\n"
            "npm test\n"
            "```\n"
        )
    return (
        "## Hardening\n\n"
        "This repository was hardened for deterministic local operation.\n\n"
        "### Run\n\n"
        "```bash\n"
        "python3 -m core.main\n"
        "```\n\n"
        "### Test\n\n"
        "```bash\n"
        "python3 -m unittest discover -s tests -p 'test_*.py'\n"
        "```\n"
    )


def calculate_scorecard(target: Path, stack: str, policy_issues: List[str]) -> Dict[str, int]:
    structure = 0
    for part in ("core", "data", "tests"):
        if (target / part).exists():
            structure += 10

    run_score = 0
    if stack == "node":
        package_json = target / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                if "dev" in scripts:
                    run_score += 20
            except json.JSONDecodeError:
                pass
    elif (target / "core" / "main.py").exists():
        run_score += 20

    config = 20 if (target / ".env.example").exists() else 0

    tests = 0
    if stack == "node":
        if (target / "tests" / "test_smoke.js").exists():
            tests = 20
    else:
        if (target / "tests" / "test_smoke.py").exists():
            tests = 20

    policy = max(0, 10 - (len(policy_issues) * 3))
    total = structure + run_score + config + tests + policy

    return {
        "structure": structure,
        "run_command": run_score,
        "config": config,
        "tests": tests,
        "policy": policy,
        "total": min(100, total),
    }


def harden_repo(
    target: Path,
    stack: str,
    safe_refactor: bool,
    dry_run: bool,
    verify: bool,
    strict: bool,
    min_score: int,
    fail_on_command_check: bool,
    verify_timeout_seconds: int,
    timeout_override_args: List[str],
    policy_fail_on: List[str],
    emit_junit: bool,
    junit_path: str,
) -> Tuple[Dict[str, object], int]:
    if not target.exists():
        raise HardeningError(f"target '{target}' does not exist")
    if not target.is_dir():
        raise HardeningError(f"target '{target}' is not a directory")

    stack_resolved = detect_stack(target=target, forced=stack)
    created: List[str] = []
    updated: List[str] = []
    skipped: List[str] = []
    risk_flags: List[str] = []

    for folder in ("core", "data", "tests"):
        path = target / folder
        if path.exists():
            skipped.append(folder)
        else:
            if not dry_run:
                path.mkdir(parents=True, exist_ok=True)
            created.append(folder)

    if stack_resolved in ("python", "unknown"):
        for rel, content in _python_templates().items():
            changed, _ = _write_file(target / rel, content, dry_run=dry_run, overwrite=False)
            if changed:
                created.append(rel)
            else:
                skipped.append(rel)
    elif stack_resolved == "node":
        env_changed, _ = _write_file(
            target / ".env.example",
            "APP_ENV=dev\nLOG_LEVEL=INFO\n",
            dry_run=dry_run,
            overwrite=False,
        )
        if env_changed:
            created.append(".env.example")
        else:
            skipped.append(".env.example")
        test_changed, _ = _write_file(
            target / "tests" / "test_smoke.js",
            _node_test_template(),
            dry_run=dry_run,
            overwrite=False,
        )
        if test_changed:
            created.append("tests/test_smoke.js")
        else:
            skipped.append("tests/test_smoke.js")

    readme_changed = _append_readme_section(
        target / "README.md", build_readme_section(stack_resolved), dry_run=dry_run
    )
    if readme_changed:
        updated.append("README.md")
    else:
        skipped.append("README.md")

    if safe_refactor:
        if stack_resolved in ("python", "unknown"):
            changed, _ = _safe_refactor_python(target=target, dry_run=dry_run)
            if changed:
                created.append("run.py")
            else:
                skipped.append("run.py")
        elif stack_resolved == "node":
            changed, _ = _safe_refactor_node(target=target, dry_run=dry_run, risk_flags=risk_flags)
            if changed:
                updated.append("package.json")
            else:
                skipped.append("package.json")

    policy_issues, risk_flags_detail = run_policy_checks(target=target)
    risk_flags.extend(policy_issues)
    scorecard = calculate_scorecard(target=target, stack=stack_resolved, policy_issues=policy_issues)

    if stack_resolved == "node":
        commands = ["npm install", "npm run dev", "npm test"]
    else:
        commands = [
            "python3 -m unittest discover -s tests -p 'test_*.py'",
            "python3 -m core.main",
        ]

    timeout_overrides = _timeout_overrides_for_commands(stack_resolved, commands)
    timeout_overrides.update(_parse_user_timeout_overrides(timeout_override_args, commands))
    command_checks = (
        verify_commands(
            target=target,
            commands=commands,
            dry_run=dry_run,
            default_timeout_seconds=verify_timeout_seconds,
            timeout_overrides=timeout_overrides,
        )
        if verify
        else []
    )

    manifest = {
        "stack": stack_resolved,
        "safe_refactor": safe_refactor,
        "dry_run": dry_run,
        "strict": strict,
        "min_score": min_score,
        "verify_commands_enabled": verify,
        "verify_timeout_seconds": verify_timeout_seconds,
        "verify_timeout_overrides": timeout_overrides,
        "timeout_override_args": timeout_override_args,
        "fail_on_command_check": fail_on_command_check,
        "policy_fail_on": policy_fail_on,
        "created": sorted(set(created)),
        "updated": sorted(set(updated)),
        "skipped": sorted(set(skipped)),
        "risk_flags": sorted(set(risk_flags)),
        "risk_flags_detail": risk_flags_detail,
        "scorecard": scorecard,
        "recommended_commands": commands,
        "command_checks": command_checks,
        "policy_fail_triggered": [],
    }

    exit_code = 0
    if strict and scorecard["total"] < min_score:
        exit_code = 2
        risk_flags.append("strict-score-threshold-not-met")
        manifest["risk_flags"] = sorted(set(risk_flags))
    if fail_on_command_check and verify:
        failed_checks = [check for check in command_checks if not check.get("passed", False) and not check.get("skipped", False)]
        if failed_checks:
            exit_code = max(exit_code, 3)
            risk_flags.append("command-check-failed")
            manifest["risk_flags"] = sorted(set(risk_flags))
    policy_fail_triggered = sorted(set(policy_fail_on).intersection(set(manifest["risk_flags"])))
    manifest["policy_fail_triggered"] = policy_fail_triggered
    if policy_fail_triggered:
        exit_code = max(exit_code, 4)
        risk_flags.append("policy-gate-failed")
        manifest["risk_flags"] = sorted(set(risk_flags))

    manifest_path = target / "data" / "hardening_manifest.json"
    if not dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if emit_junit:
            junit_output = _build_junit_xml(manifest=manifest, exit_code=exit_code)
            junit_out_path = Path(junit_path)
            if not junit_out_path.is_absolute():
                junit_out_path = target / junit_out_path
            junit_out_path.parent.mkdir(parents=True, exist_ok=True)
            junit_out_path.write_text(junit_output, encoding="utf-8")
    return manifest, exit_code


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harden repository to low-entropy defaults")
    parser.add_argument("--target", required=True, help="Path to existing repository")
    parser.add_argument(
        "--stack",
        default="auto",
        choices=["auto", "python", "node"],
        help="Force stack or auto-detect",
    )
    parser.add_argument(
        "--safe-refactor",
        action="store_true",
        help="Add wrapper entrypoints and preserve existing commands",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")
    parser.add_argument(
        "--no-verify-commands",
        action="store_true",
        help="Skip execution checks for recommended run/test commands",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if scorecard total is lower than --min-score",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=85,
        help="Minimum score required in --strict mode (default: 85)",
    )
    parser.add_argument(
        "--verify-timeout-seconds",
        type=int,
        default=120,
        help="Default timeout for each verification command (seconds)",
    )
    parser.add_argument(
        "--fail-on-command-check",
        action="store_true",
        help="Exit non-zero when any verified command fails",
    )
    parser.add_argument(
        "--timeout-override",
        action="append",
        default=[],
        help="Override timeout with '<command>=<seconds>' (repeatable)",
    )
    parser.add_argument(
        "--policy-fail-on",
        default="",
        help="Comma-separated risk flags that should fail the run",
    )
    parser.add_argument(
        "--emit-junit",
        action="store_true",
        help="Emit JUnit XML summary for CI",
    )
    parser.add_argument(
        "--junit-path",
        default="data/hardening_junit.xml",
        help="Path for JUnit XML output (absolute or target-relative)",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    target = Path(args.target).expanduser().resolve()
    if args.min_score < 0 or args.min_score > 100:
        print("error: --min-score must be between 0 and 100", file=sys.stderr)
        return 1
    if args.verify_timeout_seconds < 1:
        print("error: --verify-timeout-seconds must be >= 1", file=sys.stderr)
        return 1
    policy_fail_on = _parse_policy_fail_on(args.policy_fail_on)
    try:
        manifest, strict_exit_code = harden_repo(
            target=target,
            stack=args.stack,
            safe_refactor=args.safe_refactor,
            dry_run=args.dry_run,
            verify=not args.no_verify_commands,
            strict=args.strict,
            min_score=args.min_score,
            fail_on_command_check=args.fail_on_command_check,
            verify_timeout_seconds=args.verify_timeout_seconds,
            timeout_override_args=args.timeout_override,
            policy_fail_on=policy_fail_on,
            emit_junit=args.emit_junit,
            junit_path=args.junit_path,
        )
    except HardeningError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    print(json.dumps(manifest, indent=2))
    if strict_exit_code == 2:
        score = manifest["scorecard"]["total"]
        print(
            f"error: strict mode failed, score {score} is below required minimum {args.min_score}",
            file=sys.stderr,
        )
    elif strict_exit_code == 3:
        print("error: command verification failed and --fail-on-command-check is enabled", file=sys.stderr)
    elif strict_exit_code == 4:
        print(
            f"error: policy gate failed for flags: {','.join(manifest.get('policy_fail_triggered', []))}",
            file=sys.stderr,
        )
    return strict_exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
