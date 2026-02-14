"""Minimal CLI for Aaron Command Center v0.1."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


DEFAULT_MODULES = ("creativity", "exports")
EXCLUDE_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "dist"}
EXCLUDE_FILE_SUFFIXES = {".pyc", ".pyo"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m app.main", description="Aaron Command Center CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("help", help="Show command help")
    subparsers.add_parser("list", help="List available modules")

    run_parser = subparsers.add_parser("run", help="Run a module action")
    run_parser.add_argument("module", help="Module name, e.g. creativity or exports")
    run_parser.add_argument("action", help="Action name, e.g. status or bundle")
    run_parser.add_argument("target", nargs="?", help="Optional run target, e.g. prompt name")
    run_parser.add_argument("--name", help="Optional bundle name for exports")
    run_parser.add_argument(
        "--input",
        help="Input payload as raw text or a file path with key: value lines to fill prompt templates",
    )

    return parser


def list_modules() -> int:
    print("Available modules:")
    for module in DEFAULT_MODULES:
        print(f"- {module}")
    return 0


def create_bundle(repo_root: Path, bundle_name: str) -> Path:
    dist_dir = repo_root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    output_name = bundle_name if bundle_name.endswith(".zip") else f"{bundle_name}.zip"
    output_zip = dist_dir / output_name

    with ZipFile(output_zip, "w", compression=ZIP_DEFLATED) as archive:
        for path in repo_root.rglob("*"):
            if path.is_dir():
                continue

            rel = path.relative_to(repo_root)

            if any(part in EXCLUDE_DIR_NAMES for part in rel.parts):
                continue
            if path.suffix in EXCLUDE_FILE_SUFFIXES:
                continue
            if path.suffix == ".zip" and "dist" in rel.parts:
                continue

            archive.write(path, rel.as_posix())

    return output_zip


def list_prompts(repo_root: Path) -> list[Path]:
    prompt_root = repo_root / "prompt-library"
    if not prompt_root.exists():
        return []
    return sorted(prompt_root.rglob("*.md"))


def normalize_prompt_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def resolve_prompt_file(repo_root: Path, prompt_name: str) -> Path | None:
    wanted = normalize_prompt_name(prompt_name)
    for path in list_prompts(repo_root):
        if normalize_prompt_name(path.stem) == wanted:
            return path
    return None


def parse_input_payload(payload: str | None) -> dict[str, str]:
    if not payload:
        return {}

    path = Path(payload)
    if path.exists() and path.is_file():
        raw = path.read_text(encoding="utf-8")
    else:
        raw = payload

    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key:
            fields[key] = value
    return fields


def apply_fields_to_template(template_text: str, fields: dict[str, str]) -> str:
    if not fields:
        return template_text

    output_lines: list[str] = []
    for line in template_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and ":" in stripped:
            original_key = stripped[2:].split(":", 1)[0].strip()
            normalized_key = original_key.lower()
            if normalized_key in fields:
                prefix = line[: line.find("- ") + 2]
                output_lines.append(f"{prefix}{original_key}: {fields[normalized_key]}")
                continue
        output_lines.append(line)
    return "\n".join(output_lines) + ("\n" if template_text.endswith("\n") else "")


def run_prompt(repo_root: Path, prompt_name: str | None, payload: str | None) -> int:
    if not prompt_name:
        prompts = list_prompts(repo_root)
        if not prompts:
            print("no prompt templates found under prompt-library/", file=sys.stderr)
            return 1
        print("available prompts:")
        for path in prompts:
            print(f"- {path.stem}")
        return 0

    prompt_file = resolve_prompt_file(repo_root, prompt_name)
    if prompt_file is None:
        print(f"prompt not found: {prompt_name!r}", file=sys.stderr)
        return 1

    fields = parse_input_payload(payload)
    template = prompt_file.read_text(encoding="utf-8")
    rendered = apply_fields_to_template(template, fields)

    print(f"# Prompt: {prompt_file.stem}")
    print(f"# Source: {prompt_file.relative_to(repo_root)}")
    print()
    print(rendered)
    return 0


def run_command(module: str, action: str, target: str | None, name: str | None, payload: str | None) -> int:
    repo_root = Path.cwd()

    if module == "creativity" and action == "status":
        print("creativity: placeholder module is available")
        return 0
    if module == "creativity" and action == "prompt":
        return run_prompt(repo_root, target, payload)

    if module == "exports" and action == "bundle":
        bundle_name = name or "aaron-command-center-v0.1"
        output_zip = create_bundle(repo_root, bundle_name)
        print(f"bundle created: {output_zip}")
        return 0

    print(f"unsupported run target: module={module!r} action={action!r}", file=sys.stderr)
    return 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in (None, "help"):
        parser.print_help()
        return 0
    if args.command == "list":
        return list_modules()
    if args.command == "run":
        return run_command(args.module, args.action, args.target, args.name, args.input)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
