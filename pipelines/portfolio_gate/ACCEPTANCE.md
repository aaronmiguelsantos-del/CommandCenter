# Portfolio Gate — Acceptance (v3.2.x)

## CLI
Command:
```bash
python -m app.main operator portfolio-gate --json --repos <repoA> <repoB>
```

Must:
- Exit in {0,2,3,4}
- Print valid JSON when `--json` is set
- Include:
  - `schema_version`
  - `command: "portfolio_gate"`
  - `portfolio_exit_code`
  - `policy`
  - `repos[]` (deterministically ordered)
  - `top_actions[]` (deterministically ordered)

## Determinism
Two consecutive runs with the same repo list must output identical JSON bytes:
```bash
python -m app.main operator portfolio-gate --json --repos . . > /tmp/a.json
python -m app.main operator portfolio-gate --json --repos . . > /tmp/b.json
diff -u /tmp/a.json /tmp/b.json
```

## Export
Command:
```bash
python -m app.main operator portfolio-gate --json --repos . --export-path /tmp/portfolio
```

Must write:
- `/tmp/portfolio/portfolio_gate.json`
- `/tmp/portfolio/bundle_meta.json`

`bundle_meta.json` must include:
- `schema_version: "1.0"`
- `artifacts` exactly:
  - `["bundle_meta.json", "portfolio_gate.json"]`

## Tests
All tests must pass fast:
```bash
python -m pytest -q
```
