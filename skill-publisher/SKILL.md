---
name: skill-publisher
description: Validate, package, index, and publish skills from a local skills workspace into a git repo clone with deterministic checks, artifact blocking, and optional commit/push automation. Use when Codex needs to publish newly built skills to GitHub consistently.
---

# Skill Publisher

Publish skills to GitHub with one deterministic command.

## Enforce Output Contract

When delivering publish results, output in this order:
1. Full file tree and complete file contents
2. Explanation (one short paragraph)
3. Install + run commands
4. Why it works (one line)
5. Quick fix if broken (most likely issue and fix)

Always end with `Next upgrades (3 max)` and mark one as highest leverage.

## Workflow

1. Validate + sync skills to repo clone:
```bash
python3 scripts/publish_skills.py --source-root /absolute/path/to/skills --repo-root /absolute/path/to/repo-clone
```
Target only changed skills:
```bash
python3 scripts/publish_skills.py --source-root /absolute/path/to/skills --repo-root /absolute/path/to/repo-clone --only skill-a,skill-b
```
Custom usage schema:
```bash
python3 scripts/publish_skills.py --source-root /absolute/path/to/skills --repo-root /absolute/path/to/repo-clone --usage-schema /absolute/path/to/skill_usage_events.schema.json
```
2. Commit and push:
```bash
python3 scripts/publish_skills.py --source-root /absolute/path/to/skills --repo-root /absolute/path/to/repo-clone --commit --push
```

Default integrated pipeline on each run:
- auto-version-bump every discovered skill (`patch` by default)
- run regression precheck (`skill-regression-runner`) in strict mode, scoped by `--only` when provided
- run rollup contract precheck (`skill-adoption-analytics/scripts/check_rollup_contract.py`)
- publish sync + index generation
- enforce `skill_usage_events.schema.json` and append valid usage events to `data/skill_usage_events.jsonl` for targeted skills
- append failure usage events with deterministic `reason_code` on publish errors

## What It Enforces

- Required files:
  - `SKILL.md`
  - `agents/openai.yaml`
- Blocks artifacts:
  - `__pycache__/`
  - `*.pyc`
  - `.DS_Store`
- Generates deterministic `skills_index.json` with:
  - skill name
  - folder path
  - description

## Troubleshooting

If push fails, verify network and git remote permissions.
If validation fails, remove blocked artifacts and retry.
If regressions fail, fix failing snapshots/tests or run with `--skip-regressions` only when intentionally bypassing guardrails.
If rollup contract fails, update expected rollup snapshot intentionally or use `--skip-rollup-contract` when bypassing guardrails.
