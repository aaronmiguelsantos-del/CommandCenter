---
name: repo-bootstrapper
description: Bootstrap a low-entropy, local-first Python repository with deterministic structure and one-command execution. Use when Codex needs to create or reset a project skeleton with stack variants (basic, streamlit, flask), guarded merge overwrite, and smoke tests.
---

# Repo Bootstrapper

Create or refresh a minimal repository scaffold optimized for one-shot execution.

## Enforce Output Contract

When delivering a bootstrap result, output in this order:
1. Full file tree and complete file contents
2. Explanation (one short paragraph)
3. Install + run commands
4. Why it works (one line)
5. Quick fix if broken (most likely issue and fix)

Always end with `Next upgrades (3 max)` and mark one as highest leverage.

## Workflow

1. Confirm target path, bootstrap mode, and stack:
   - `new`: create a new project in an empty or non-existent directory.
   - `merge`: add missing scaffold files into an existing directory without deleting user files.
   - `stack`: `basic` (stdlib only), `streamlit`, or `flask`.
2. Run `scripts/bootstrap_repo.py`.
3. Run local smoke checks:
   - `python3 scripts/bootstrap_repo.py --target <path> --mode <new|merge> --stack <basic|streamlit|flask>`
   - `python3 -m unittest discover -s tests -p 'test_*.py'`
4. Report exactly what was created and skipped.

## Required Scaffold

Generate these paths at minimum:
- `core/__init__.py`
- `core/config.py`
- `core/main.py`
- `data/.gitkeep`
- `tests/test_smoke.py` (must include env override test)
- `README.md`
- `.env.example`

For `streamlit` and `flask`, also generate:
- `requirements.txt`
- `app.py`

## Implementation Rules

- Keep dependencies at standard library only unless stack requires extras.
- Keep behavior config-first via environment variables.
- Fail fast on invalid paths or unsupported mode/stack.
- Never delete files in `merge` mode.
- In `new` mode, error if target directory exists and is non-empty.
- `--force` only applies to `merge` mode and requires confirmation file `.bootstrap_force_ok` in target directory.
- Use ASCII only.

## Command Patterns

Create a new basic project:
```bash
python3 scripts/bootstrap_repo.py --target /absolute/path/to/project --mode new --stack basic
```

Create a Streamlit project:
```bash
python3 scripts/bootstrap_repo.py --target /absolute/path/to/project --mode new --stack streamlit
```

Add missing files into existing Flask project safely:
```bash
python3 scripts/bootstrap_repo.py --target /absolute/path/to/project --mode merge --stack flask
```

Overwrite scaffold files in merge mode (explicitly guarded):
```bash
touch /absolute/path/to/project/.bootstrap_force_ok
python3 scripts/bootstrap_repo.py --target /absolute/path/to/project --mode merge --stack basic --force
```

## Troubleshooting

If execution fails due to Python version mismatch, run with Python 3.11+.
If tests are not discovered, run from project root and verify `tests/test_smoke.py` exists.
If `--force` fails, create `.bootstrap_force_ok` in target root first.
