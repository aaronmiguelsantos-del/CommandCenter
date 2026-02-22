# CLI

## operator portfolio-gate

Runs `operator gate` across multiple repo roots / registries and aggregates results deterministically.

```bash
python -m app.main operator portfolio-gate --json --repos /path/repoA /path/repoB
python -m app.main operator portfolio-gate --json --repos-file data/portfolio/repos.txt
python -m app.main operator portfolio-gate --json --repos-map data/portfolio/repos.json
python -m app.main operator portfolio-gate --json --repos . --export-path /tmp/portfolio
```

## Defaults (recommended)

If `data/portfolio/repos.json` exists and you provide no `--repos`/`--repos-file`/`--repos-map`, portfolio-gate uses it automatically:

```bash
python -m app.main operator portfolio-gate --json
```

## Flags passed through to each repo run

- `--hide-samples`
- `--strict`
- `--enforce-sla`
- `--as-of`

## Phase flags

- `--repos-map PATH` repo roots + owner + required + optional `policy_overrides`
- `--allow-missing` missing required repos do NOT force regression exit (still recorded as errors)
- `--jobs N` bounded parallelism (determinism preserved via stable output sorting)
- `--fail-fast` stop launching new runs once outcome is already non-zero
- `--max-repos N` safety valve
- `--export-mode portfolio-only|with-repo-gates`
- `--export-path PATH` writes `portfolio_gate.json` + `bundle_meta.json`

## Partial failure semantics

Each repo entry includes:

- `repo_status: ok|error`
- `error_code` in:
  - `REPO_PATH_NOT_FOUND`
  - `REGISTRY_NOT_FOUND`
  - `SUBPROCESS_FAILED`
  - `INVALID_JSON`

Missing required repos force portfolio exit `3` (regression) unless `--allow-missing` is set.

## Portfolio scoring (v3.5.0)

Output includes:

- `summary.portfolio_status` in `green|yellow|red`
- `summary.portfolio_score` in `0..100`
- counts for ok/error/strict/regression

Status mapping:

- `red`: strict failed (exit 2 or 4)
- `yellow`: regression (exit 3) OR score < 90
- `green`: clean + score >= 90

## report portfolio-snapshot (v3.6.0)

Portfolio-level snapshot ledger for `operator portfolio-gate` output.

Ledger default:
- `data/snapshots/portfolio_snapshot_history.jsonl`

Write snapshot (captures portfolio-gate output then appends to ledger):

```bash
python -m app.main report portfolio-snapshot --write --json \
  --repos-map data/portfolio/repos.json \
  --hide-samples --strict --enforce-sla --jobs 4
```

Tail:

```bash
python -m app.main report portfolio-snapshot tail --json --n 5
```

Stats:

```bash
python -m app.main report portfolio-snapshot stats --json --days 7
```

Diff:

```bash
python -m app.main report portfolio-snapshot diff --json --a prev --b latest
```

Determinism (tests / CI):

Use `--captured-at 2026-02-22T00:00:00+00:00` to pin timestamps.

## operator portfolio-operator-gate (v3.7.0)

Portfolio-level CI gate:
- writes a portfolio snapshot
- diffs prev -> latest
- returns gate-style exit codes (0/2/3/4)

```bash
python -m app.main operator portfolio-operator-gate --json \
  --repos-map data/portfolio/repos.json \
  --hide-samples --strict --enforce-sla --jobs 4
```

Export artifacts:

```bash
python -m app.main operator portfolio-operator-gate --json \
  --repos-map data/portfolio/repos.json \
  --hide-samples --strict --enforce-sla --jobs 4 \
  --export-path /tmp/portfolio_gate
ls -1 /tmp/portfolio_gate | sort
```

Determinism (tests):

Use `--captured-at 2026-02-22T00:00:00+00:00`.

Pretty mode:

```bash
python -m app.main operator portfolio-operator-gate --pretty \
  --repos-map data/portfolio/repos.json \
  --hide-samples --strict --enforce-sla --jobs 4
```

CI enforcement:

`.github/workflows/portfolio_gate.yml` runs this gate, exports artifacts, uploads them, and fails the job on non-zero exit.
