---
name: repo-health-reporter
description: Generate deterministic repository health reports in human and JSON formats, enforce CI-ready exit codes, and optionally install a local app entrypoint for `python3 -m app.main report health`. Use when Codex needs to assess repo readiness, diagnose CI instability, or standardize health reporting.
---

# Repo Health Reporter

Assess repository health quickly with deterministic checks and machine-readable output.

## Enforce Output Contract

When delivering health-reporter results, output in this order:
1. Full file tree and complete file contents
2. Explanation (one short paragraph)
3. Install + run commands
4. Why it works (one line)
5. Quick fix if broken (most likely issue and fix)

Always end with `Next upgrades (3 max)` and mark one as highest leverage.

## Workflow

1. Confirm target path.
2. Run health report:
```bash
python3 scripts/repo_health.py --target /absolute/path/to/repo
```
3. Use JSON mode for pipelines:
```bash
python3 scripts/repo_health.py --target /absolute/path/to/repo --json
```
4. Install `app.main` health entrypoint when missing:
```bash
python3 scripts/repo_health.py --target /absolute/path/to/repo --install-entrypoint
```

## What the Script Does

- Detect stack (`python`, `node`, `unknown`).
- Run deterministic checks:
  - required baseline paths
  - test command viability
  - `.env.example` presence
  - git cleanliness (if repo is git-managed)
  - dependency and policy risk flags
- Output:
  - human-readable summary (default)
  - JSON schema (`--json`)
- Enforce CI gate with `--strict` (non-zero if unhealthy).
- Optionally emit JUnit XML (`--emit-junit`).
- Optionally install `app/main.py` + `app/__init__.py` + `scripts/repo_health.py` copy into target for:
  - `python3 -m app.main report health`
  - `python3 -m app.main report health --json`

## Command Patterns

Human report:
```bash
python3 scripts/repo_health.py --target /absolute/path/to/repo
```

JSON report:
```bash
python3 scripts/repo_health.py --target /absolute/path/to/repo --json
```

Strict mode:
```bash
python3 scripts/repo_health.py --target /absolute/path/to/repo --strict
```

Emit JUnit:
```bash
python3 scripts/repo_health.py --target /absolute/path/to/repo --emit-junit
```

Install entrypoint:
```bash
python3 scripts/repo_health.py --target /absolute/path/to/repo --install-entrypoint
```

## Troubleshooting

If test command fails due environment issues, run with dependencies installed first.
If git checks are noisy outside git repos, the check is auto-skipped.
If `python3 -m app.main` fails, run `--install-entrypoint` first.
