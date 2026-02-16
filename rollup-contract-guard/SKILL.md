---
name: rollup-contract-guard
description: Enforce roadmap rollup determinism by running schema validation plus snapshot drift checks through one local command. Use when Codex needs a single contract gate for rollup stability in local and CI flows.
---

# Rollup Contract Guard

Run one command to verify rollup schema + drift contract.

## Workflow

1. Run contract check:
```bash
python3 scripts/run_rollup_contract.py --repo-root /absolute/path/to/repo
```

2. Optional custom inputs:
```bash
python3 scripts/run_rollup_contract.py --repo-root /absolute/path/to/repo --releases /path/to/releases.jsonl --events /path/to/events.jsonl --expected /path/to/expected.json
```

## Output

- Exit `0`: contract pass
- Exit `2`: rollup drift detected
- Exit `1`: misuse/runtime failure
