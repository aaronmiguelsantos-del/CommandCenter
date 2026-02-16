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
