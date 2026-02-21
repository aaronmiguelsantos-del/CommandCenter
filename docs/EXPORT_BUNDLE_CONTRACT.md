# Export Bundle Contract v1.0

## Command Surface

Artifacts are produced by:

- `python -m app.main report export ...`
- `python -m app.main operator gate --export-path <dir>`

## Required Bundle Files

- `bundle_meta.json`
- `report_health.json`
- `graph.json`
- `snapshot_stats.json`
- `snapshot_tail.json`

When produced by operator gate export:

- `operator_gate.json`
- `snapshot_diff.json`
- `snapshot_latest.json`

Conditional:

- `strict_failure.json` (strict failed only)

## bundle_meta.json (minimum)

Required top-level fields:

- `bundle_version` (string)
- `ts` (ISO8601 string)
- `inputs` (object)
- `artifacts` (array): sorted filenames
- `checksums` (object): SHA256 map for files written before `bundle_meta.json`

## Artifact Schema Versions

- `operator_gate.json` must include `schema_version: "1.0"`
- `snapshot_diff.json` must include `schema_version: "1.0"`
- `snapshot_latest.json` must include `schema_version: "1.0"`

## Determinism

- `artifacts` list is sorted.
- `checksums` keys are sorted.
- JSON files are written with sorted keys and trailing newline.
