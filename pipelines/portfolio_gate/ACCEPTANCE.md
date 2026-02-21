# Portfolio Gate — Acceptance (v3.3.x)

## CLI (v3.3.x)
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

### Parallelism
Must preserve determinism with parallel execution:
```bash
python -m app.main operator portfolio-gate --json --repos . . --jobs 4 > /tmp/a.json
python -m app.main operator portfolio-gate --json --repos . . --jobs 4 > /tmp/b.json
diff -u /tmp/a.json /tmp/b.json
```

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
python -m app.main operator portfolio-gate --json --repos . --export-path /tmp/portfolio --export-mode portfolio-only
```

Must write:
- `/tmp/portfolio/portfolio_gate.json`
- `/tmp/portfolio/bundle_meta.json`

`bundle_meta.json` must include:
- `schema_version: "1.0"`
- `artifacts` exactly:
  - `["bundle_meta.json", "portfolio_gate.json"]`

### Export mode: with-repo-gates
Command:
```bash
python -m app.main operator portfolio-gate --json --repos . --export-path /tmp/portfolio --export-mode with-repo-gates
```

Must:
- Include `repo_<hash>_operator_gate.json` files for each repo
- `bundle_meta.json["artifacts"]` contains those filenames deterministically

## Tests
All tests must pass fast:
```bash
python -m pytest -q
```
