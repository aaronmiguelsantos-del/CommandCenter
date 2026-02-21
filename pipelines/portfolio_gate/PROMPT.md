# Portfolio Gate — Deterministic Task Brief (v3.2.x)

Role:
You are the Builder for Bootstrapping Engine.

Objective:
Ship `operator portfolio-gate` as a deterministic multi-repo governance layer.

Non-negotiables:
- Deterministic outputs (stable ordering, no timestamps in payloads unless explicitly part of contract)
- Read-only UI (if touched)
- Parity-first: portfolio-gate is built from operator-gate outputs (do not re-implement health/strict logic)
- Tests must remain fast
- Schema changes require schema_version bump + contract doc update + drift sentinel update

Deliverables:
1) CLI: `python -m app.main operator portfolio-gate --json --repos ...`
2) Export: `portfolio_gate.json` + `bundle_meta.json` with deterministic artifacts list
3) Tests:
   - deterministic output across repeated runs
   - export bundle includes expected files
   - aggregated exit code semantics

Verification commands (must pass):
```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m app.main operator portfolio-gate --json --repos . | .venv/bin/python -m json.tool | head -n 120
```
