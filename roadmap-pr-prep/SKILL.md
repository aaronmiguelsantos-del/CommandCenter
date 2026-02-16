---
name: roadmap-pr-prep
description: Generate deterministic roadmap PR artifacts from releases and usage events, including rollup JSON and markdown summary. Use when Codex needs a daily auto-prioritization output ready for commit/PR.
---

# Roadmap PR Prep

Produce PR-ready roadmap artifacts in one command.

## Workflow

1. Build rollup + markdown summary:
```bash
python3 scripts/prepare_roadmap_pr.py --repo-root /absolute/path/to/repo
```

2. Custom output directory:
```bash
python3 scripts/prepare_roadmap_pr.py --repo-root /absolute/path/to/repo --output-dir /absolute/path/to/repo/data/roadmap
```
3. Open or update deterministic daily PR:
```bash
python3 scripts/prepare_roadmap_pr.py --repo-root /absolute/path/to/repo --open-pr --base-branch main --branch-prefix codex/roadmap-daily --json
```
4. Dry-run PR actions:
```bash
python3 scripts/prepare_roadmap_pr.py --repo-root /absolute/path/to/repo --open-pr --dry-run --json
```
5. Skip PR updates when artifacts have no staged diff:
```bash
python3 scripts/prepare_roadmap_pr.py --repo-root /absolute/path/to/repo --open-pr --skip-pr-if-no-change --json
```
6. Scope roadmap artifacts to changed skills:
```bash
python3 scripts/prepare_roadmap_pr.py --repo-root /absolute/path/to/repo --only skill-a,skill-b --json
```
7. Deterministic fixture run for regression:
```bash
python3 scripts/prepare_roadmap_pr.py --repo-root /absolute/path/to/repo --releases /absolute/path/to/rollup_releases.jsonl --events /absolute/path/to/rollup_events.jsonl --stamp 2026-02-16 --only skill-a,skill-b --json
```
