.PHONY: roadmap-pr rollup-contract verify-roadmap regression-strict publish-skills nightly-local nightly-local-check

roadmap-pr:
	python3 roadmap-pr-prep/scripts/prepare_roadmap_pr.py \
		--repo-root . \
		--json

rollup-contract:
	python3 skill-adoption-analytics/scripts/check_rollup_contract.py \
		--releases skill-adoption-analytics/tests/fixtures/rollup_releases.jsonl \
		--events skill-adoption-analytics/tests/fixtures/rollup_events.jsonl \
		--schema skill-adoption-analytics/references/roadmap_rollup.schema.json \
		--expected skill-adoption-analytics/tests/golden/roadmap_rollup.expected.json \
		--output /tmp/roadmap_rollup.actual.json \
		--json
	python3 skill-adoption-analytics/scripts/check_rollup_contract.py \
		--releases skill-adoption-analytics/tests/fixtures/rollup_releases.jsonl \
		--events skill-adoption-analytics/tests/fixtures/rollup_events_unknown_skills.jsonl \
		--schema skill-adoption-analytics/references/roadmap_rollup.schema.json \
		--expected skill-adoption-analytics/tests/golden/roadmap_rollup_unknown_skills.expected.json \
		--output /tmp/roadmap_rollup_unknown_skills.actual.json \
		--json

verify-roadmap:
	$(MAKE) roadmap-pr
	$(MAKE) rollup-contract
	python3 -m unittest discover -s skill-adoption-analytics/tests -p 'test_*.py'

regression-strict:
	python3 skill-regression-runner/scripts/run_skill_regressions.py \
		--source-root . \
		--only roadmap-pr-prep,usage-failure-triage,skill-publisher \
		--strict \
		--json

publish-skills:
	@if [ -z "$(REPO_ROOT)" ]; then echo "error: set REPO_ROOT=/absolute/path/to/repo-clone" >&2; exit 1; fi
	$(MAKE) regression-strict
	python3 skill-publisher/scripts/publish_skills.py \
		--source-root . \
		--repo-root "$(REPO_ROOT)" \
		$(PUBLISH_ARGS)

nightly-local:
	python3 -c 'from pathlib import Path; import shutil; root=Path("/tmp/nightly"); shutil.rmtree(root, ignore_errors=True); (root / "roadmap").mkdir(parents=True, exist_ok=True)'
	python3 usage-failure-triage/scripts/triage_usage_failures.py \
		--events data/skill_usage_events.jsonl \
		--output /tmp/nightly/usage_failure_triage.json \
		--markdown-output /tmp/nightly/usage_failure_triage.md
	python3 roadmap-pr-prep/scripts/prepare_roadmap_pr.py \
		--repo-root . \
		--output-dir /tmp/nightly/roadmap \
		--json > /tmp/nightly/roadmap_pr_report.json
	python3 -c 'import json; from datetime import datetime, timezone; from pathlib import Path; root=Path("/tmp/nightly"); files=sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()); manifest={"schema_version": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "files": files}; (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")'

nightly-local-check:
	$(MAKE) nightly-local
	python3 skill-regression-runner/scripts/nightly_local_check.py --current /tmp/nightly --last /tmp/nightly-last --report /tmp/nightly_local_check.json --schema skill-regression-runner/references/nightly_local_check.schema.json
