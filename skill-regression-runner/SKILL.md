---
name: skill-regression-runner
description: Run deterministic regression suites for skills, compare command outputs against golden snapshots, and fail fast on behavior drift. Use when Codex needs to prevent skill regressions before publish.
---

# Skill Regression Runner

Run deterministic regression suites for skills and catch drift.

## Enforce Output Contract

When delivering results, output in this order:
1. Full file tree and complete file contents
2. Explanation (one short paragraph)
3. Install + run commands
4. Why it works (one line)
5. Quick fix if broken (most likely issue and fix)

Always end with `Next upgrades (3 max)` and mark one as highest leverage.

## Workflow

1. Run suites:
```bash
python3 scripts/run_skill_regressions.py --source-root /absolute/path/to/skills
```
2. Create/update snapshots intentionally:
```bash
python3 scripts/run_skill_regressions.py --source-root /absolute/path/to/skills --update-snapshots
```
3. Strict CI gate:
```bash
python3 scripts/run_skill_regressions.py --source-root /absolute/path/to/skills --strict
```

## Suite Format

Each skill can define `tests/regression_suite.json`:

```json
{
  "cases": [
    {
      "id": "help",
      "command": ["python3", "scripts/my_tool.py", "--help"],
      "expect_exit": 0,
      "expect_stdout_contains": ["usage"]
    }
  ]
}
```

Snapshots are stored in `tests/golden/<case-id>.json`.

Schema validation:
- `references/regression_snapshot.schema.json` is applied to each snapshot payload.
