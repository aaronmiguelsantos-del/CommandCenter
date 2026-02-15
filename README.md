# Bootstrapping Engine v0.1

Local-first operator repo with deterministic CLI workflows for bootstrapping primitives, creating contracts, logging events, and computing meta-health snapshots on every command.

## Requirements

- Python 3.11+

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## One-command run

```bash
python -m app.main run
```

## CLI commands

```bash
python -m app.main --help
python -m app.main init
python -m app.main health
python -m app.main contract new bootstrap-core "Bootstrapping Engine Core Contract"
python -m app.main log bootstrap-core status_update
```

## Data outputs

- `data/contracts/*.json`
- `data/logs/events.jsonl`
- `data/snapshots/health_latest.json`
- `data/snapshots/health_history.jsonl`

## Test

```bash
pytest -q
```
