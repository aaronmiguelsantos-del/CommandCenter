# Bootstrapping Engine - operator commands (no shell activation needed)

PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help venv deps test health health-json health-global log system-list

help:
	@echo ""
	@echo "Targets:"
	@echo "  make venv          Create .venv"
	@echo "  make deps          Install deps into .venv"
	@echo "  make test          Run tests"
	@echo "  make health        Per-system health (registry) table (recommended default)"
	@echo "  make health-json   Per-system health JSON (pretty)"
	@echo "  make health-global Global repo health (aggregated across all systems)"
	@echo "  make system-list   Alias for per-system health"
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
