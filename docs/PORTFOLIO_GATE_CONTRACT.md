# PORTFOLIO_GATE_CONTRACT (v1.0)

Schema version: `1.0`
Repo map schema version: `1.0` (`data/portfolio/repos.json`)

## Command
`python -m app.main operator portfolio-gate --json ...`

## Output: portfolio_gate.json
Top-level keys (required):
- `schema_version` (string) == "1.0"
- `command` (string) == "portfolio_gate"
- `portfolio_exit_code` (int) in {0,2,3,4}
- `policy` (object)
- `repos` (array)
- `top_actions` (array)
- `artifacts` (object)

### policy (required)
- `allow_missing` (bool)
- `hide_samples` (bool)
- `strict` (bool)
- `enforce_sla` (bool)
- `as_of` (string|null)
- `jobs` (int)
- `fail_fast` (bool)
- `max_repos` (int|null)
- `export_mode` (string)
- `repos_map` (string|null)

### repos[] entries (required)
Each element is a wrapper:
- `repo` (object): `repo_id`, `repo_hash`, `repo_root`, `registry_path`
- `repo_status` (string): `"ok"` | `"error"`
- `error_code` (string|null)
- `error_message` (string|null)
- `exit_code` (int)
- `gate` (object) - result of `operator gate --json`
- `stderr` (string)

## Exit code semantics
Portfolio exit code mirrors operator gate:
- `0` clean
- `2` strict failed (any repo)
- `3` regression detected (any repo)
- `4` both

Missing repo semantics:
- If `required=true` and `repo_status="error"`:
  - portfolio exit becomes `3` (regression) unless `--allow-missing` is set.

Error codes:
- `REPO_PATH_NOT_FOUND`
- `REGISTRY_NOT_FOUND`
- `SUBPROCESS_FAILED`
- `INVALID_JSON`

## Export bundle
When `--export-path` is used, the directory must contain:
- `bundle_meta.json` (schema_version "1.0", artifacts list)
- `portfolio_gate.json`

If `--export-mode with-repo-gates` is used, export also includes:
- `repo_<repo_hash>_operator_gate.json` for each repo in `repos[]`

## Determinism
- Output ordering is deterministic:
  - repos sorted by `(repo_id, repo_hash, repo_root)`
  - top_actions merged/sorted deterministically
- JSON must be written with stable key sorting.
