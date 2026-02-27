# PORTFOLIO_POLICY_CONTRACT (v1.0)

Repos map schema version: `1.1`

## File

`data/portfolio/repos.json`

## Purpose

Defines explicit per-repo execution policy for portfolio tasks.

`operator portfolio-run` does not infer health/release/registry commands when a policy map is present.

## Top-level keys

- `schema_version` (string): `1.0` or `1.1`
- `repos` (array)

## Repo entry keys

Required:
- `repo_id` (string)
- `path` (string)

Optional:
- `owner` (string)
- `required` (bool)
- `notes` (string)
- `policy_overrides` (object)
- `lifecycle` (`active|archival|experimental`)
- `group_key` (string)
- `group_role` (`primary|clone|backup`)
- `execution_policy` (object)
- `excluded_tasks` (array of `health|release|registry`)
- `task_timeouts_seconds` (object keyed by task name)

## execution_policy

Supported keys:
- `health_command` (string)
- `release_command` (string)
- `registry_command` (string)
- `preferred_python` (string)

Command strings may include `{python}` which is replaced with `preferred_python`.

If `preferred_python` is omitted, runtime falls back to `sys.executable`.

## operator portfolio-run

```bash
python -m app.main operator portfolio-run --task health --json
python -m app.main operator portfolio-run --task release --json
python -m app.main operator portfolio-run --task registry --json
```

Task result statuses:
- `ok`: command returned exit code `0`
- `skipped`: task excluded, policy missing, or missing repo path allowed
- `error`: command failed, timed out, or missing required repo path

Exit codes:
- `0`: no task errors
- `2`: one or more task errors
- `5`: invalid policy map / invalid task

## Determinism

- Repo ordering is stable: `(repo_id, repo_root)`
- Output JSON keys are stable
- Missing policy is explicit `skipped`, never implicit fallback
- Relative `preferred_python` is resolved against repo root
