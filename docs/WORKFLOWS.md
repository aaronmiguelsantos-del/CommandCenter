# WORKFLOWS

This repo is a deterministic governance kernel.
Workflows are **operator runbooks**: copy/paste commands, stable contracts, predictable exit codes.

Rules:
- No UI mutation (Streamlit is read-only)
- CLI output is the source of truth
- Schema changes require schema_version bump + contract doc update + drift sentinel update
- Keep tests fast

---

## Workflow: v3.2.x Portfolio Gate MVP (Multi-Repo Aggregation)

### Goal
Run `operator gate` across multiple repos and aggregate outcomes into a deterministic portfolio view.

### Entry Points
- `python -m app.main operator portfolio-gate --json --repos ...`
- Optional: `--repos-file repos.txt`
- Optional: `--export-path /tmp/portfolio`

### Acceptance Contract
- `portfolio_gate.json` is schema-versioned (`schema_version: "1.0"`)
- Aggregation is deterministic (stable ordering across runs)
- Export bundle includes stable artifact list
- Exit codes mirror single-repo gate semantics:
  - `0` clean
  - `2` strict failed (any repo)
  - `3` regression detected (any repo)
  - `4` both

### Operator Runbook (Happy Path)
```bash
cd "/Users/aaronsantos/Documents/Bootstrapping Engine"

# 1) tests
.venv/bin/python -m pytest -q

# 2) single-repo portfolio sanity
.venv/bin/python -m app.main operator portfolio-gate --json --repos . | .venv/bin/python -m json.tool | head -n 120

# 3) deterministic repeat (must be identical)
.venv/bin/python -m app.main operator portfolio-gate --json --repos . . > /tmp/pg1.json
.venv/bin/python -m app.main operator portfolio-gate --json --repos . . > /tmp/pg2.json
diff -u /tmp/pg1.json /tmp/pg2.json

# 4) export bundle
rm -rf /tmp/portfolio && mkdir -p /tmp/portfolio
.venv/bin/python -m app.main operator portfolio-gate --json --repos . --export-path /tmp/portfolio
ls -1 /tmp/portfolio | sort
```

### Failure Handling
- If `portfolio-gate` errors with missing repos:
  - Provide `--repos` and/or `--repos-file`
- If a target repo fails to run `operator gate`:
  - The per-repo entry includes `stderr`
  - Fix the repo’s env/venv and rerun
- If determinism diff fails:
  - Check sorting keys and ensure no timestamps leak into payloads

---

## Workflow: Release Cut (Tags + CI)

### Goal
Ship a version with deterministic tests, clean git state, and pushed tags.

```bash
cd "/Users/aaronsantos/Documents/Bootstrapping Engine"
.venv/bin/python -m pytest -q

git status --short
git diff

git add -A
git commit -m "vX.Y.Z: <summary>"
git tag vX.Y.Z
git push origin main --tags
```
