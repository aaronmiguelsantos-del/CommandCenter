---
name: cli-contract-guardian
description: Validate CLI contract stability for app.main commands, including command availability, exit codes, stdout JSON schemas, strict stderr payload schema, and snapshot drift checks. Use when Codex needs to prevent UI/CLI contract regressions before release.
---

# CLI Contract Guardian

Enforce deterministic CLI contracts before shipping.

## Enforce Output Contract

When delivering contract-check results, output in this order:
1. Full file tree and complete file contents
2. Explanation (one short paragraph)
3. Install + run commands
4. Why it works (one line)
5. Quick fix if broken (most likely issue and fix)

Always end with `Next upgrades (3 max)` and mark one as highest leverage.

## Workflow

1. Run contract validation:
```bash
python3 scripts/validate_cli_contract.py --target /absolute/path/to/repo
```
2. Run strict CI gate:
```bash
python3 scripts/validate_cli_contract.py --target /absolute/path/to/repo --strict
```
3. Initialize or refresh snapshot baseline:
```bash
python3 scripts/validate_cli_contract.py --target /absolute/path/to/repo --update-snapshot
```

## Contract Scope

Validate these commands:
- `python -m app.main report health --json`
- `python -m app.main report graph --json`
- `python -m app.main health --all --strict`

Checks:
- command executes
- expected exit code contract
- JSON schema contract for stdout
- strict failure payload on stderr (last non-empty line JSON)
- snapshot drift for top-level stable fields

## Troubleshooting

If command import fails, verify target repo root and venv Python path.
If strict payload fails parse, ensure strict failure writes one JSON line on stderr.
If snapshot drift is intentional, rerun with `--update-snapshot`.
