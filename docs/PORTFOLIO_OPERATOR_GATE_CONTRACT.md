# PORTFOLIO_OPERATOR_GATE_CONTRACT (v1.0)

Schema version: `1.0`

## Command
`python -m app.main operator portfolio-operator-gate --json ...`

## Exit codes
- `0` clean
- `2` strict failed (latest portfolio_exit_code in 2/4)
- `3` regression detected (prev->latest diff indicates regression)
- `4` both

## Export bundle
When `--export-path` is set, directory contains:
- `bundle_meta.json` (schema_version "1.0")
- `portfolio_operator_gate.json` (schema_version "1.0")
- `portfolio_snapshot_latest.json` (schema_version "1.0")
- `portfolio_snapshot_diff.json` (schema_version "1.0")

Artifacts list in bundle_meta is pinned and deterministic.

## Determinism
- Snapshot writes are deterministic under `--captured-at`
- Diff is deterministic via stable selection prev/latest
- Payload keys are stable; schema bump required on changes
