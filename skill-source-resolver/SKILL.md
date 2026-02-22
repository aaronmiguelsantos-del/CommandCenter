---
name: skill-source-resolver
description: Discover and score the best local source root containing publishable skills so workflows avoid scanning the wrong worktree.
---

# Skill Source Resolver

Find the best skill source root deterministically.

## Workflow

1. Resolve source root from a start path:
```bash
python3 scripts/resolve_skill_source.py \
  --start /absolute/path/to/search \
  --max-depth 4 \
  --prefer-repo-root \
  --strict \
  --json
```

2. Advisory mode without strict failure:
```bash
python3 scripts/resolve_skill_source.py \
  --start /absolute/path/to/search \
  --max-depth 2 \
  --json
```

## Guarantees

- Discovers valid skill folders by `SKILL.md` + `agents/openai.yaml`.
- Scores candidates deterministically by skill density and repo signals.
- Optional `--prefer-repo-root` strongly prioritizes git-backed source repos over installed inventory roots.
- Supports strict exit code `2` when no valid root is found.
