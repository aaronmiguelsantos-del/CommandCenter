---
name: skill-version-manager
description: Manage deterministic semver for skills, append release records, and store migration notes in local-first JSON artifacts. Use when Codex needs structured version bumps and release bookkeeping for skills.
---

# Skill Version Manager

Bump skill versions deterministically with release records.

## Enforce Output Contract

When delivering results, output in this order:
1. Full file tree and complete file contents
2. Explanation (one short paragraph)
3. Install + run commands
4. Why it works (one line)
5. Quick fix if broken (most likely issue and fix)

Always end with `Next upgrades (3 max)` and mark one as highest leverage.

## Workflow

1. Patch bump:
```bash
python3 scripts/manage_skill_version.py --skills-root /absolute/path/to/skills --skill repo-hardener --bump patch --summary "Bug fixes"
```
2. Minor bump with migration note:
```bash
python3 scripts/manage_skill_version.py --skills-root /absolute/path/to/skills --skill repo-hardener --bump minor --summary "New strict gate" --migration "Review CI threshold defaults."
```

## Files Managed

- `<skill>/skill_version.json`
- `<skills-root>/data/skill_releases.jsonl`
