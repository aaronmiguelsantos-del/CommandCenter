---
name: repo-hardener
description: Harden an existing repository into a low-entropy, local-first, one-command runnable project with deterministic structure, config-first defaults, smoke tests, policy checks, and measurable score output. Use when Codex needs to standardize or repair a messy Python or Node repository without destructive rewrites.
---

# Repo Hardener

Standardize existing repositories with safe, measurable changes.

## Enforce Output Contract

When delivering hardening results, output in this order:
1. Full file tree and complete file contents
2. Explanation (one short paragraph)
3. Install + run commands
4. Why it works (one line)
5. Quick fix if broken (most likely issue and fix)

Always end with `Next upgrades (3 max)` and mark one as highest leverage.

## Workflow

1. Confirm target path and run mode.
2. Run hardening:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --safe-refactor
```
3. Review `data/hardening_manifest.json` for created, updated, skipped, risk flags, and score.
4. Report exact changes plus remaining risks.

## What the Script Does

- Detect stack (`python`, `node`, or `unknown`) using local files.
- Add missing baseline files and folders:
  - `core/`
  - `data/`
  - `tests/`
  - `.env.example`
  - `README.md` refresh (append hardening section)
- Add one-command run support:
  - Python: `python3 -m core.main`
  - Node: `npm run dev`
- Add smoke tests if missing.
- Run policy checks using `rg` when available.
- Verify each recommended run/test command and store pass/fail output tails.
- Generate `data/hardening_manifest.json` with:
  - `created`
  - `updated`
  - `skipped`
  - `risk_flags`
  - `risk_flags_detail`
  - `scorecard`
  - `recommended_commands`
  - `command_checks`
  - `verify_timeout_seconds`
  - `verify_timeout_overrides`
  - `policy_fail_triggered`
  - `timeout_override_args`

- Optionally emit JUnit XML for CI at `data/hardening_junit.xml` (or `--junit-path`).

## Safe Refactor Mode

Use `--safe-refactor` to add wrapper entrypoints without deleting existing entrypoints.

- Python: create `run.py` wrapper targeting discovered existing entrypoints or fallback to `core.main`.
- Node: merge `package.json` scripts with non-destructive defaults (`dev`, `test`).

## Command Patterns

Harden with automatic detection:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --safe-refactor
```

Dry run:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --safe-refactor --dry-run
```

Force stack:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --stack python --safe-refactor
```

Strict CI gate:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --safe-refactor --strict --min-score 90
```

Fail when command checks fail:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --safe-refactor --fail-on-command-check
```

Custom verify timeout:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --safe-refactor --verify-timeout-seconds 180
```

Per-command timeout override:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --safe-refactor --timeout-override "python3 -m core.main=45"
```

Policy gate:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --safe-refactor --policy-fail-on "framework-bloat-risk,todo-in-core-paths"
```

Emit JUnit XML:
```bash
python3 scripts/harden_repo.py --target /absolute/path/to/repo --safe-refactor --emit-junit --junit-path data/hardening_junit.xml
```

## Troubleshooting

If stack detection is wrong, pass `--stack python` or `--stack node`.
If policy checks fail because `rg` is missing, the script falls back to Python scanning.
If run command fails, execute the first command listed in `recommended_commands`.
If command verification is too heavy for the environment, pass `--no-verify-commands`.
If command checks fail in CI, inspect `command_checks` and `risk_flags_detail` in the manifest.
If CI requires test report ingestion, enable `--emit-junit`.
