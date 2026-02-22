---
name: release-preflight-guard
description: Run resolver smoke, strict regressions, rollup contract checks, and telemetry SLO gating in one deterministic command and emit a single JSON verdict artifact.
---

# Release Preflight Guard

Run a single deterministic preflight gate before publish or PR merge.

## Workflow

1. Run full preflight and write artifact:
```bash
python3 scripts/run_release_preflight.py \
  --repo-root /absolute/path/to/repo \
  --events /absolute/path/to/repo/data/skill_usage_events.jsonl \
  --output /absolute/path/to/repo/data/release_preflight.json \
  --strict \
  --json
```

2. Non-blocking advisory mode:
```bash
python3 scripts/run_release_preflight.py \
  --repo-root /absolute/path/to/repo \
  --json
```

## Guarantees

- Chains resolver-smoke, regression-strict, rollup-contract, and telemetry-slo.
- Produces one stable verdict artifact with per-check status + parsed JSON payloads.
- Returns exit code `2` in `--strict` mode when any gate is blocked.
