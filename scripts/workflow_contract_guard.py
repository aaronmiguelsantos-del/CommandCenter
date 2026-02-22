#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


STEP_NAME_RE = re.compile(r"^\s*-\s+name:\s*(?P<value>.+?)\s*$")
MAKE_TEE_JSON_RE = re.compile(r"(?P<prefix>.*\bmake\b)(?P<args>.*)\|\s*tee\b(?P<rest>.*\.json\b.*)$")
SILENT_FLAG_RE = re.compile(r"(^|\s)(-s|--silent)(\s|$)")


def _is_quoted(value: str) -> bool:
    v = value.strip()
    if len(v) < 2:
        return False
    return (v[0] == v[-1] and v[0] in {'"', "'"})


def _strip_unquoted_comment(value: str) -> str:
    v = value.rstrip()
    if _is_quoted(v):
        return v
    if " #" in v:
        return v.split(" #", 1)[0].rstrip()
    return v


def check_workflow(path: Path) -> list[str]:
    errors: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        m = STEP_NAME_RE.match(line)
        if m:
            value = _strip_unquoted_comment(m.group("value").strip())
            if value in {"|", ">", "|-", ">-"}:
                continue
            if ":" in value and not _is_quoted(value):
                errors.append(
                    f"{path}:{lineno}: step name contains ':' but is unquoted -> {value!r} "
                    f"(use quotes: - name: \"{value}\")"
                )

        mm = MAKE_TEE_JSON_RE.match(line)
        if mm:
            args = mm.group("args")
            if not SILENT_FLAG_RE.search(args):
                errors.append(
                    f"{path}:{lineno}: make output is tee'd to JSON but make is not silent; "
                    "use `make -s ... | tee ...json` for contract-safe JSON capture"
                )
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    workflows_dir = root / ".github" / "workflows"
    workflow_files = sorted(
        [*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")]
    )
    if not workflow_files:
        print("No workflow files found.")
        return 0

    errors: list[str] = []
    for wf in workflow_files:
        errors.extend(check_workflow(wf))

    if errors:
        print("Workflow contract guard failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print(f"Workflow contract guard passed for {len(workflow_files)} workflow files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
