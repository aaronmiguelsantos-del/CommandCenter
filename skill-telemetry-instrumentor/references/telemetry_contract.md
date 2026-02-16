# Telemetry Contract

Use `scripts/instrument_skill_telemetry.py` when you need command-level usage events without editing every skill script.

Required event fields:
- `skill`
- `status` (`success` or `failure`)
- `duration_ms`
- `timestamp_utc`
- `source`
- `context`

Failure-only fields:
- `reason_code`
- `reason_detail`
- `error_class`

Default schema path:
- `skill-adoption-analytics/references/skill_usage_events.schema.json`

Shared reason-code dictionary:
- `skill-adoption-analytics/references/reason_codes.json`

Recommended reason-code style:
- lower snake_case
- deterministic and machine-groupable (`regression_failed`, `unknown_skill`, `command_failed`)
