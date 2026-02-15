#!/usr/bin/env python3
"""Create a deterministic low-entropy Python project scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Dict


FORCE_CONFIRMATION_FILE = ".bootstrap_force_ok"


class BootstrapError(Exception):
    pass


def _base_files() -> Dict[str, str]:
    return {
        "core/__init__.py": "",
        "core/config.py": (
            '"""Configuration helpers for environment-driven settings."""\n\n'
            "from __future__ import annotations\n\n"
            "import os\n"
            "from dataclasses import dataclass\n\n\n"
            "@dataclass(frozen=True)\n"
            "class AppConfig:\n"
            "    app_env: str\n"
            "    log_level: str\n"
            "    data_dir: str\n\n\n"
            "def load_config() -> AppConfig:\n"
            "    return AppConfig(\n"
            "        app_env=os.getenv(\"APP_ENV\", \"dev\"),\n"
            "        log_level=os.getenv(\"LOG_LEVEL\", \"INFO\"),\n"
            "        data_dir=os.getenv(\"DATA_DIR\", \"data\"),\n"
            "    )\n"
        ),
        "core/main.py": (
            '"""Entrypoint for one-command local execution."""\n\n'
            "from __future__ import annotations\n\n"
            "from core.config import load_config\n\n\n"
            "def run() -> str:\n"
            "    cfg = load_config()\n"
            "    return f\"app_env={cfg.app_env} log_level={cfg.log_level} data_dir={cfg.data_dir}\"\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    print(run())\n"
        ),
        "data/.gitkeep": "",
        "tests/test_smoke.py": (
            "import os\n"
            "import unittest\n"
            "from unittest.mock import patch\n\n"
            "from core.main import run\n\n\n"
            "class SmokeTest(unittest.TestCase):\n"
            "    def test_run_returns_status_line(self) -> None:\n"
            "        result = run()\n"
            "        self.assertIn(\"app_env=\", result)\n"
            "        self.assertIn(\"log_level=\", result)\n"
            "        self.assertIn(\"data_dir=\", result)\n\n"
            "    def test_run_reads_environment_overrides(self) -> None:\n"
            "        with patch.dict(\n"
            "            os.environ,\n"
            "            {\"APP_ENV\": \"test\", \"LOG_LEVEL\": \"DEBUG\", \"DATA_DIR\": \"tmp-data\"},\n"
            "            clear=False,\n"
            "        ):\n"
            "            result = run()\n"
            "        self.assertIn(\"app_env=test\", result)\n"
            "        self.assertIn(\"log_level=DEBUG\", result)\n"
            "        self.assertIn(\"data_dir=tmp-data\", result)\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    unittest.main()\n"
        ),
        ".env.example": (
            "APP_ENV=dev\n"
            "LOG_LEVEL=INFO\n"
            "DATA_DIR=data\n"
        ),
    }


def _stack_files(stack: str) -> Dict[str, str]:
    if stack == "basic":
        readme = (
            "# Project\n\n"
            "Minimal, deterministic Python scaffold.\n\n"
            "## Quick Start\n\n"
            "```bash\n"
            "python3 -m unittest discover -s tests -p 'test_*.py'\n"
            "python3 -m core.main\n"
            "```\n"
        )
        return {"README.md": readme}

    if stack == "streamlit":
        readme = (
            "# Project\n\n"
            "Deterministic Streamlit scaffold with config-first core module.\n\n"
            "## Quick Start\n\n"
            "```bash\n"
            "python3 -m unittest discover -s tests -p 'test_*.py'\n"
            "python3 -m pip install -r requirements.txt\n"
            "streamlit run app.py\n"
            "```\n"
        )
        app = (
            '"""Streamlit entrypoint."""\n\n'
            "from __future__ import annotations\n\n"
            "import streamlit as st\n\n"
            "from core.main import run\n\n"
            "st.set_page_config(page_title=\"Project\", layout=\"centered\")\n"
            "st.title(\"Project\")\n"
            "st.code(run())\n"
        )
        return {
            "README.md": readme,
            "requirements.txt": "streamlit\n",
            "app.py": app,
        }

    if stack == "flask":
        readme = (
            "# Project\n\n"
            "Deterministic Flask scaffold with config-first core module.\n\n"
            "## Quick Start\n\n"
            "```bash\n"
            "python3 -m unittest discover -s tests -p 'test_*.py'\n"
            "python3 -m pip install -r requirements.txt\n"
            "python3 app.py\n"
            "```\n"
        )
        app = (
            '"""Flask entrypoint."""\n\n'
            "from __future__ import annotations\n\n"
            "from flask import Flask\n\n"
            "from core.main import run\n\n"
            "app = Flask(__name__)\n\n\n"
            "@app.get(\"/\")\n"
            "def index() -> str:\n"
            "    return run()\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    app.run(host=\"127.0.0.1\", port=8000, debug=False)\n"
        )
        return {
            "README.md": readme,
            "requirements.txt": "flask\n",
            "app.py": app,
        }

    raise BootstrapError(f"unsupported stack '{stack}'")


def _render_files(stack: str) -> Dict[str, str]:
    files = _base_files()
    files.update(_stack_files(stack))
    return files


def _validate_target(mode: str, target: Path, force: bool) -> None:
    if mode == "new":
        if target.exists() and any(target.iterdir()):
            raise BootstrapError(
                f"target '{target}' exists and is not empty; use --mode merge or choose a new path"
            )
        target.mkdir(parents=True, exist_ok=True)
        return

    if mode == "merge":
        target.mkdir(parents=True, exist_ok=True)
        if force and not (target / FORCE_CONFIRMATION_FILE).exists():
            raise BootstrapError(
                "--force requires confirmation file "
                f"'{FORCE_CONFIRMATION_FILE}' in target directory"
            )
        return

    raise BootstrapError(f"unsupported mode '{mode}'")


def _write_file(path: Path, content: str, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def bootstrap(target: Path, mode: str, stack: str, force: bool) -> dict:
    _validate_target(mode=mode, target=target, force=force)

    overwrite = mode == "new" or (mode == "merge" and force)
    files = _render_files(stack=stack)

    created = []
    skipped = []

    for relative, content in files.items():
        file_path = target / relative
        changed = _write_file(file_path, content, overwrite=overwrite)
        if changed:
            created.append(relative)
        else:
            skipped.append(relative)

    manifest_path = target / "data" / "bootstrap_manifest.json"
    manifest = {
        "mode": mode,
        "stack": stack,
        "force": force,
        "created": created,
        "skipped": skipped,
    }
    manifest_changed = _write_file(
        manifest_path, json.dumps(manifest, indent=2) + "\n", overwrite=True
    )
    if manifest_changed and "data/bootstrap_manifest.json" not in created:
        created.append("data/bootstrap_manifest.json")

    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a deterministic Python repo scaffold")
    parser.add_argument("--target", required=True, help="Target project directory")
    parser.add_argument(
        "--mode",
        default="new",
        choices=["new", "merge"],
        help="Create from scratch (new) or add missing files (merge)",
    )
    parser.add_argument(
        "--stack",
        default="basic",
        choices=["basic", "streamlit", "flask"],
        help="Generated runtime stack variant",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Allow overwrite in merge mode. Requires confirmation file "
            f"{FORCE_CONFIRMATION_FILE} in target."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    target = Path(args.target).expanduser().resolve()

    if args.mode == "new" and args.force:
        print("warning: --force has no effect with --mode new", file=sys.stderr)

    try:
        manifest = bootstrap(target=target, mode=args.mode, stack=args.stack, force=args.force)
    except BootstrapError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
