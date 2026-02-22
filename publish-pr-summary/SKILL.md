---
name: publish-pr-summary
description: Generate deterministic publish PR summary artifacts (JSON + Markdown) with resolver consistency and telemetry trend status for scoped skill publishes.
---

# Publish PR Summary

Generate high-signal PR summary artifacts for every publish run.

## Workflow

1. Build summary artifacts:
```bash
python3 scripts/generate_publish_pr_summary.py \
  --repo-root /absolute/path/to/repo \
  --skills-targeted skill-publisher,usage-failure-triage \
  --requested publisher,usage_failure_triage,skill-publisher \
  --events /absolute/path/to/repo/data/skill_usage_events.jsonl \
  --output-json /absolute/path/to/repo/data/publish_pr_summary.json \
  --output-md /absolute/path/to/repo/data/publish_pr_summary.md \
  --json
```

2. Use custom SLO config:
```bash
python3 scripts/generate_publish_pr_summary.py \
  --repo-root /absolute/path/to/repo \
  --skills-targeted skill-publisher \
  --events /absolute/path/to/repo/data/skill_usage_events.jsonl \
  --slo-config /absolute/path/to/custom_slo.json \
  --output-json /tmp/publish_pr_summary.json \
  --output-md /tmp/publish_pr_summary.md
```

## Guarantees

- Always emits JSON + Markdown artifacts when inputs are valid.
- Includes resolver consistency status (`skill-name-resolver` parity smoke).
- Includes telemetry trend/SLO status and violation preview for PR narrative.
