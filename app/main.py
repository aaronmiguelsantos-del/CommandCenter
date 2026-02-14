"""Minimal CLI for Aaron Command Center v0.1."""

from __future__ import annotations

import argparse
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
    run_parser.add_argument("--name", help="Optional bundle name for exports")

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


def run_command(module: str, action: str, name: str | None) -> int:
    if module == "creativity" and action == "status":
        print("creativity: placeholder module is available")
        return 0

    if module == "exports" and action == "bundle":
        bundle_name = name or "aaron-command-center-v0.1"
        output_zip = create_bundle(Path.cwd(), bundle_name)
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
        return run_command(args.module, args.action, args.name)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
