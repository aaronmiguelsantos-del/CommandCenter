---
name: skill-name-resolver
description: Resolve skill names deterministically from CSV inputs with alias mapping and typo suggestions, and fail fast on unknown names for --only and other scoped skill flags.
---

# Skill Name Resolver

Normalize and validate skill name inputs before publish, regression, and roadmap flows.

## Workflow

1. Resolve a requested CSV list against a source root:
```bash
python3 scripts/resolve_skill_names.py \
  --source-root /absolute/path/to/repo \
  --requested skill_publisher,roadmap-pr-prep \
  --strict \
  --json
```

2. Use alias dictionary overrides:
```bash
python3 scripts/resolve_skill_names.py \
  --source-root /absolute/path/to/repo \
  --requested publisher,triage \
  --aliases /absolute/path/to/skill_name_aliases.json \
  --strict \
  --json
```

3. Non-blocking advisory mode:
```bash
python3 scripts/resolve_skill_names.py \
  --source-root /absolute/path/to/repo \
  --requested skill-publihser \
  --json
```

4. Shared smoke parity across publish/regression/roadmap:
```bash
python3 tests/run_shared_resolver_smoke.py --json
```
Override requested corpus inline:
```bash
python3 tests/run_shared_resolver_smoke.py --requested publisher,usage_failure_triage --json
```

## Guarantees

- Discovers skills via `SKILL.md` + `agents/openai.yaml` contract.
- Supports deterministic alias mapping and normalization (`_`/space to `-`).
- Emits structured unknown-skill suggestions.
- Returns exit code `2` in `--strict` mode when unknown names remain.
