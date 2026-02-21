# Snapshot Diff Contract v1.0

## Artifact

`snapshot_diff.json`

## Schema (minimum)

Required top-level fields:

- `schema_version` (string): `"1.0"`
- `a` (object): includes `ts` (string)
- `b` (object): includes `ts` (string)
- `system_status_changes` (array)
- `new_strict_reasons` (array)
- `risk_rank_delta_top` (array)
- `top_actions` (array)

Optional fields:

- `new_high_violations` (array)
- `strict_recheck_command` (string)

## Determinism

- Ordering of `top_actions` is deterministic and driven by severity/system sort in core diff engine.
- JSON is written with sorted keys and trailing newline.
