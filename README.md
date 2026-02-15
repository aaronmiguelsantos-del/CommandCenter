# Codex Kernel (Bootstrapping Engine)

Deterministic, local-first operator kernel for multi-system governance.

## What It Is
- Registry-driven system governance (`data/registry/systems.json`)
- Per-system health + strict gate (`health --all --strict`)
- Local snapshots + JSONL history under `/data`
- Deterministic reporting (`report health`, `report health --json`)

## What It Is Not
- No cloud/runtime service
- No web UI/dashboard requirement
- No background daemons
- No Docker requirement

## Quick Run
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

python -m app.main init
python -m app.main health --all
python -m app.main report health
python -m app.main validate
python -m app.main health --all --strict
```

## Tests
```bash
pytest -q
```

## Docs
- `docs/V1_ACCEPTANCE.md`
- `docs/CLI.md`
