---
name: resolver-corpus-guard
description: Validate skill-source-resolver behavior against a deterministic corpus of multi-root edge cases, including nested .codex/skills and competing git repos.
---

# Resolver Corpus Guard

Run deterministic resolver corpus checks to block source-resolution drift.

## Workflow

1. Run corpus checks:
```bash
python3 scripts/check_resolver_corpus.py \
  --repo-root /absolute/path/to/repo \
  --corpus /absolute/path/to/repo/resolver-corpus-guard/references/resolver_corpus.json \
  --strict \
  --json
```

2. Use default corpus:
```bash
python3 scripts/check_resolver_corpus.py --repo-root /absolute/path/to/repo --strict --json
```

## Guarantees

- Executes a shared resolver corpus using `skill-source-resolver` as source of truth.
- Asserts expected `resolved` state and root suffix for each case.
- Returns exit code `2` in `--strict` mode if any case drifts.
