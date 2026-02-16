---
name: skill-telemetry-instrumentor
description: Wrap skill commands with schema-validated usage telemetry so success/failure events are appended consistently with reason codes and error classes. Use when Codex needs end-to-end skill instrumentation without rewriting each script.
---

# Skill Telemetry Instrumentor

Instrument skill command runs with deterministic usage events.

## Workflow

1. Wrap a command and append a success/failure event:
```bash
python3 scripts/instrument_skill_telemetry.py \
  --events /absolute/path/to/data/skill_usage_events.jsonl \
  --skill skill-publisher \
  --source codex \
  --context publish \
  --json \
  -- python3 /absolute/path/to/script.py --flag
```

2. Add deterministic failure reason codes and classes:
```bash
python3 scripts/instrument_skill_telemetry.py \
  --events /absolute/path/to/data/skill_usage_events.jsonl \
  --skill skill-publisher \
  --source codex \
  --context publish \
  --reason-code regression_failed \
  --error-class regression \
  --json \
  -- python3 /absolute/path/to/script.py --bad-arg
```

3. Use a custom event schema:
```bash
python3 scripts/instrument_skill_telemetry.py \
  --events /absolute/path/to/data/skill_usage_events.jsonl \
  --schema /absolute/path/to/skill_usage_events.schema.json \
  --reason-codes /absolute/path/to/reason_codes.json \
  --skill usage-failure-triage \
  --source nightly \
  --context triage \
  --json \
  -- python3 /absolute/path/to/triage_usage_failures.py --events /absolute/path/to/events.jsonl
```

4. Gate telemetry coverage in CI for key skills:
```bash
python3 scripts/check_telemetry_coverage.py \
  --events /absolute/path/to/data/skill_usage_events.jsonl \
  --skills usage-failure-triage,roadmap-pr-prep \
  --last-n 20 \
  --strict \
  --json
```

## Guarantees

- Appends one JSONL usage event per wrapped command execution.
- Validates existing and newly appended rows against schema.
- Validates `reason_code` against shared dictionary at `skill-adoption-analytics/references/reason_codes.json`.
- Preserves wrapped command exit code (`0` success, non-zero failure).
- Emits deterministic JSON summaries for CI and regression snapshots.
