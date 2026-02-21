# CLI Contract

## Commands
- `python -m app.main init`
- `python -m app.main health`
- `python -m app.main health --all`
- `python -m app.main health --all --strict`
- `python -m app.main health --all --strict --enforce-sla`
- `python -m app.main report health`
- `python -m app.main report health --json`
- `python -m app.main report health --strict --enforce-sla --json`
- `python -m app.main report snapshot --write --json`
- `python -m app.main report snapshot tail --json --ledger data/snapshots/report_snapshot_history.jsonl --n 20`
- `python -m app.main report snapshot stats --json --ledger data/snapshots/report_snapshot_history.jsonl --days 7`
- `python -m app.main report snapshot run --every 1 --count 3 --json`
- `python -m app.main report snapshot diff --json --ledger data/snapshots/report_snapshot_history.jsonl --a prev --b latest`
- `python -m app.main report health --no-hints`
- `python -m app.main validate`
- `python -m app.main failcase create --path /tmp/codex-kernel-failcase --mode sla-breach`
- `python -m app.main system add <system_id> "<name>"`
- `python -m app.main system list`
- `python -m app.main contract new <system_id> "<name>"`
- `python -m app.main log <system_id> <event_type>`

## Exit Codes
- `0` success
- `1` validation/usage failure
- `2` strict governance failure (`--strict` only)

## Examples
```bash
python -m app.main health --all --json
python -m app.main report health --json
python -m app.main report snapshot tail --json --ledger data/snapshots/report_snapshot_history.jsonl --n 20
python -m app.main report snapshot stats --json --ledger data/snapshots/report_snapshot_history.jsonl --days 7
python -m app.main report snapshot run --every 1 --count 3 --json
python -m app.main report snapshot diff --json --ledger data/snapshots/report_snapshot_history.jsonl --a prev --b latest
python -m app.main validate
python -m app.main system add ops-core "Ops Core"
python -m app.main log ops-core status_update
```

## Snapshot Diff Refs
- `latest`: most recent ledger entry
- `prev` / `previous`: entry before latest
- `<int>`: index into tail rows (supports negatives, Python style)
- `<iso ts>`: exact or equivalent ISO timestamp instant
