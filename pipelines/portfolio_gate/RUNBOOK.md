# Portfolio Gate — Operator Runbook (v3.2.x)

## One-command verify
```bash
cd "/Users/aaronsantos/Documents/Bootstrapping Engine"
.venv/bin/python -m pytest -q
```

## Manual smoke
```bash
cd "/Users/aaronsantos/Documents/Bootstrapping Engine"

# single repo
.venv/bin/python -m app.main operator portfolio-gate --json --repos . | .venv/bin/python -m json.tool | head -n 120

# export
rm -rf /tmp/portfolio && mkdir -p /tmp/portfolio
.venv/bin/python -m app.main operator portfolio-gate --json --repos . --export-path /tmp/portfolio
ls -1 /tmp/portfolio | sort
```

## Failure triage

### 1) "requires --repos"
- Provide `--repos` and/or `--repos-file`.

### 2) Target repo fails running `operator gate`
- Inspect `repos[].stderr` in portfolio JSON.
- Ensure that repo has:
  - a working `.venv`
  - dependencies installed
  - compatible CLI entry `python -m app.main operator gate`

### 3) Output not deterministic
- Ensure no timestamps are generated in portfolio payload.
- Ensure stable ordering keys:
  - repo ordering uses (repo_id, repo_hash, repo_path)
  - `top_actions` ordering is stable and re-prioritized 1..N
