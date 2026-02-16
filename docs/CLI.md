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
python -m app.main validate
python -m app.main system add ops-core "Ops Core"
python -m app.main log ops-core status_update
```
