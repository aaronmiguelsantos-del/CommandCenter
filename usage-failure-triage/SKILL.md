---
name: usage-failure-triage
description: Summarize skill usage failures by reason_code, error_class, and skill from local JSONL telemetry. Use when Codex needs high-signal triage for feedback-loop incidents.
---

# Usage Failure Triage

Turn raw `skill_usage_events.jsonl` failures into deterministic triage summaries.

## Workflow

1. Generate triage report:
```bash
python3 scripts/triage_usage_failures.py --events /absolute/path/to/data/skill_usage_events.jsonl --json
```

2. Write artifact:
```bash
python3 scripts/triage_usage_failures.py --events /absolute/path/to/data/skill_usage_events.jsonl --output /absolute/path/to/data/usage_failure_triage.json
```
3. Recent-window triage with markdown:
```bash
python3 scripts/triage_usage_failures.py --events /absolute/path/to/data/skill_usage_events.jsonl --since-days 7 --top 10 --markdown-output /absolute/path/to/data/usage_failure_triage.md --json
```
4. Scoped triage by source and reason code:
```bash
python3 scripts/triage_usage_failures.py --events /absolute/path/to/data/skill_usage_events.jsonl --sources skill-publisher --reason-codes regression_failed,git_push_failed --json
```

Schema enforcement:
- defaults to `../skill-adoption-analytics/references/skill_usage_events.schema.json`
- override with `--schema /absolute/path/to/skill_usage_events.schema.json`
