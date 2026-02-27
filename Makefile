# Bootstrapping Engine - operator commands (no shell activation needed)

PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help venv deps test health health-json health-global log system-list workflow-contract-guard install-hooks portfolio-run-health portfolio-run-release portfolio-run-registry portfolio-health-report portfolio-release-report executive-status executive-report

help:
	@echo ""
	@echo "Targets:"
	@echo "  make venv          Create .venv"
	@echo "  make deps          Install deps into .venv"
	@echo "  make test          Run tests"
	@echo "  make health        Per-system health (registry) table (recommended default)"
	@echo "  make health-json   Per-system health JSON (pretty)"
	@echo "  make health-global Global repo health (aggregated across all systems)"
	@echo "  make portfolio-run-health  Run policy-driven portfolio health task(s)"
	@echo "  make portfolio-run-release Run policy-driven portfolio release task(s)"
	@echo "  make portfolio-run-registry Run policy-driven portfolio registry task(s)"
	@echo "  make portfolio-health-report Write/print trendable portfolio health report"
	@echo "  make portfolio-release-report Write/print trendable portfolio release report"
	@echo "  make executive-status Run deterministic executive status"
	@echo "  make executive-report Write deterministic executive report artifacts"
	@echo "  make system-list   Alias for per-system health"
	@echo "  make workflow-contract-guard Validate workflow lint contracts"
	@echo "  make install-hooks Configure local git hooks path (.githooks)"
	@echo ""

venv:
	python3 -m venv .venv
	$(PIP) install -U pip

deps:
	$(PIP) install -r requirements.txt

test:
	$(PY) -m pytest -q

# This is your DEFAULT dashboard
health:
	$(PY) -m app.main health --all

health-json:
	$(PY) -m app.main health --all --json | $(PY) -m json.tool | head -n 80

# This is the strict repo-wide gate (will go red if any system is failing)
health-global:
	$(PY) -m app.main health | $(PY) -m json.tool | head -n 80

system-list:
	$(PY) -m app.main system list

portfolio-run-health:
	$(PY) -m app.main operator portfolio-run --task health --json | $(PY) -m json.tool | head -n 120

portfolio-run-release:
	$(PY) -m app.main operator portfolio-run --task release --json | $(PY) -m json.tool | head -n 120

portfolio-run-registry:
	$(PY) -m app.main operator portfolio-run --task registry --json | $(PY) -m json.tool | head -n 120

portfolio-health-report:
	$(PY) -m app.main report portfolio-health --json --output-json reports/portfolio_health.json --output-md reports/portfolio_health.md | $(PY) -m json.tool | head -n 120

portfolio-release-report:
	$(PY) -m app.main report portfolio-release --json --output-json reports/portfolio_release.json --output-md reports/portfolio_release.md | $(PY) -m json.tool | head -n 120

executive-status:
	$(PY) -m app.main operator executive status --json | $(PY) -m json.tool | head -n 120

executive-report:
	$(PY) -m app.main operator executive report --json --output-json reports/executive_report.json --output-md reports/executive_report.md | $(PY) -m json.tool | head -n 120

workflow-contract-guard:
	python3 scripts/workflow_contract_guard.py

install-hooks:
	git config core.hooksPath .githooks
