# PORTFOLIO_GATE_CONTRACT (v1.1)

Portfolio schema version: `1.1` (v3.5.0)  
Repo map schema version: `1.0` (`data/portfolio/repos.json`)

## Command
`python -m app.main operator portfolio-gate --json ...`

## Output: portfolio_gate.json
Top-level keys (required):
- `schema_version` (string) == "1.1"
- `command` (string) == "portfolio_gate"
- `portfolio_exit_code` (int) in {0,2,3,4}
- `summary` (object)
- `policy` (object)
- `repos` (array)
- `top_actions` (array)
- `artifacts` (object)

### summary (required)
- `portfolio_status` (string): "green" | "yellow" | "red"
- `portfolio_score` (int): 0..100
- `repos_total` (int)
- `repos_ok` (int)
- `repos_error` (int)
- `repos_error_required` (int)
- `repos_error_optional` (int)
- `repos_strict_failed` (int)
- `repos_regression` (int)

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
Each element:
- `repo` (object):
  - `repo_id` (string)
  - `repo_hash` (string)
  - `repo_root` (string)
  - `registry_path` (string)
  - `owner` (string)
  - `required` (bool)
  - `notes` (string)
  - `policy_overrides` (object)
- `effective_policy` (object)
- `repo_status` (string): "ok" | "error"
- `error_code` (string|null)
- `error_message` (string|null)
- `exit_code` (int)
- `gate` (object) - result of `operator gate --json`
- `stderr` (string)

### per-repo policy overrides (repos.json)
Optional `policy_overrides` keys:
- `strict` (bool)
- `enforce_sla` (bool)
- `hide_samples` (bool)

Effective policy is always recorded per repo under `effective_policy`.

## Exit code semantics
Portfolio exit code mirrors operator gate:
- `0` clean
- `2` strict failed (any repo)
- `3` regression detected (any repo) OR missing required repo (unless allow_missing)
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
When `--export-path` is used, directory must contain:
- `bundle_meta.json` (schema_version "1.0", artifacts list)
- `portfolio_gate.json`

If `--export-mode with-repo-gates` is used, export also includes:
- `repo_<repo_hash>_operator_gate.json` for each repo in `repos[]`

## Determinism
- repos sorted by `(repo_id, repo_hash, repo_root)`
- merged top_actions sorted deterministically
- JSON written with stable key sorting
