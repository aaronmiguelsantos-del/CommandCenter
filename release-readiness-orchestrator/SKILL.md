---
name: release-readiness-orchestrator
description: Run a deterministic release go/no-go pipeline by orchestrating repo hardening checks, health checks, and CLI contract checks, then emit a single release_readiness.json verdict and CI-friendly exit code. Use when Codex needs one-command preflight before release.
---

# Release Readiness Orchestrator

Run one command to decide release go/no-go.

## Enforce Output Contract

When delivering results, output in this order:
1. Full file tree and complete file contents
2. Explanation (one short paragraph)
3. Install + run commands
4. Why it works (one line)
5. Quick fix if broken (most likely issue and fix)

Always end with `Next upgrades (3 max)` and mark one as highest leverage.

## Workflow

1. Run release gate:
```bash
python3 scripts/release_ready.py --target /absolute/path/to/repo
```
2. Review output file:
```bash
cat /absolute/path/to/repo/data/release_readiness.json
```
3. Use strict CI mode:
```bash
python3 scripts/release_ready.py --target /absolute/path/to/repo --strict
```

## Checks Orchestrated

- `repo-hardener` in non-destructive mode (`--dry-run`)
- `repo-health-reporter` in strict JSON mode
- `cli-contract-guardian` in strict JSON mode

Outputs:
- deterministic JSON report with per-check status, command, exit code, and parsed payload
- overall release verdict (`ready` or `blocked`)
- exit code:
  - `0` when ready
  - `2` when blocked in strict mode

## Troubleshooting

If a tool script is missing, provide explicit `--hardener-script`, `--health-script`, or `--contract-script`.
If output shows parse errors, rerun each child command directly from report command lines.
