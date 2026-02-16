---
name: skill-adoption-analytics
description: Compute deterministic skill usage and ROI analytics from local JSONL events, including invocation counts, success rates, latency stats, and prioritized improvement rankings. Use when Codex needs measurable adoption insights for skill roadmap decisions.
---

# Skill Adoption Analytics

Measure skill ROI from local usage data.

## Enforce Output Contract

When delivering results, output in this order:
1. Full file tree and complete file contents
2. Explanation (one short paragraph)
3. Install + run commands
4. Why it works (one line)
5. Quick fix if broken (most likely issue and fix)

Always end with `Next upgrades (3 max)` and mark one as highest leverage.

## Workflow

1. Analyze usage events:
```bash
python3 scripts/analyze_skill_adoption.py --events /absolute/path/to/data/skill_usage_events.jsonl
```
2. Write report artifact:
```bash
python3 scripts/analyze_skill_adoption.py --events /absolute/path/to/data/skill_usage_events.jsonl --output /absolute/path/to/data/skill_adoption_report.json
```

3. Generate daily roadmap rollup:
```bash
python3 scripts/generate_daily_rollup.py --releases /absolute/path/to/data/skill_releases.jsonl --events /absolute/path/to/data/skill_usage_events.jsonl --output /absolute/path/to/data/skill_roadmap_daily.json --json
```

## Input Event Format

Each JSONL line:
```json
{"timestamp_utc":"2026-02-15T00:00:00Z","skill":"repo-hardener","status":"success","duration_ms":1200}
```

`status` values:
- `success`
- `failure`

## Schemas

- `references/adoption_report.schema.json` validates analytics report output.
