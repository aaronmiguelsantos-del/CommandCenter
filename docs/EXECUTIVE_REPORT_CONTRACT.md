# EXECUTIVE_REPORT_CONTRACT (v1.0)

## Commands

```bash
python -m app.main operator executive status --json
python -m app.main operator executive report --json
```

## Runbook

Default runbook path:

`data/executive/runbook.json`

Runbook schema:
- `schema_version` = `1.0`
- `name` (string)
- `steps` (array)

Step fields:
- `step_id` (string)
- `title` (string)
- `task` in `health|release|registry`
- `severity_on_error` in `high|medium|low`
- optional step-local overrides:
  - `repos` (array of repo roots)
  - `repos_file` (string path)
  - `repos_map` (string path)
  - `allow_missing` (bool)
  - `max_repos` (positive int)
  - `jobs` (positive int)
  - `history_path` (string path)
  - `write_history` (bool)
  - `output_json` (string path)
  - `output_md` (string path)

Relative override paths resolve relative to the runbook file path.

## Report JSON

Required top-level fields:
- `schema_version` (string): `1.0`
- `command` (string): `executive_report`
- `captured_at` (string|null)
- `status` (string): `ok|needs_attention`
- `runbook` (object)
- `summary` (object)
- `checks` (array)
- `top_actions` (array)

Summary fields:
- `steps_total` (int)
- `steps_ok` (int)
- `steps_error` (int)

## Determinism

- Step ordering follows runbook order exactly.
- `top_actions` are sorted by severity rank (`high`, `medium`, `low`) then `(step_id, repo_id)` and assigned increasing `priority`.
- Executive reporting reuses `portfolio-run` payloads; it does not invent a parallel execution model.
- `operator executive status` never writes per-step output artifacts.
- `operator executive report` may write per-step output artifacts when the runbook declares `output_json` / `output_md`.
