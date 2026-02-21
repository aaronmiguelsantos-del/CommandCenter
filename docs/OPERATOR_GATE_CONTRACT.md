# Operator Gate Contract v1.0

## Command

`python -m app.main operator gate --json`

## Output JSON (minimum)

Required top-level fields:

- `command` (string): always `"operator_gate"`
- `schema_version` (string): currently `"1.0"`
- `exit_code` (int): one of `0`, `2`, `3`, `4`
- `strict_failed` (bool)
- `regression_detected` (bool)
- `policy` (object)
- `top_actions` (array)
- `artifacts` (object)

`policy` minimum fields:

- `registry` (string|null)
- `hide_samples` (bool)
- `strict` (bool)
- `enforce_sla` (bool)
- `as_of` (string|null)

`artifacts` minimum fields:

- `snapshot_written` (bool)
- `diff_includes_top_actions` (bool)
- `export_path` (string|null)
- `export_written` (array)

## Exit Codes

- `0`: clean
- `2`: strict failed
- `3`: regression detected
- `4`: strict failed and regression detected

## Export Contract (`--export-path`)

Required files:

- `bundle_meta.json`
- `report_health.json`
- `graph.json`
- `snapshot_stats.json`
- `snapshot_tail.json`
- `operator_gate.json`
- `snapshot_diff.json`
- `snapshot_latest.json`

Conditional file:

- `strict_failure.json` (only when strict fails)

`bundle_meta.json` must include:

- `artifacts`: sorted list of exported filenames
- `checksums`: deterministic SHA256 map for exported files written before `bundle_meta.json`

## Determinism Rules

- No random ordering in `top_actions`; ordering is driven by core snapshot diff ranking.
- Export extra files are written in sorted filename order.
- `operator gate` derives regressions from diff payload only (no duplicate client logic).
- JSON export files are written with sorted keys and trailing newline.
