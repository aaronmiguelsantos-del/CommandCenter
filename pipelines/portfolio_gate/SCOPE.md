# Portfolio Gate — Scope (v3.2.x)

## What we are building
- A portfolio-level aggregator that runs `operator gate` across multiple repos and merges results deterministically.

## In-scope
- `operator portfolio-gate` CLI command
- Multi-repo execution (subprocess in repo cwd)
- Deterministic aggregation:
  - stable repo ordering
  - stable merged `top_actions` ordering
  - stable exit code semantics
- Optional export bundle:
  - `portfolio_gate.json`
  - `bundle_meta.json` (artifact list)
- Tests for determinism + export + exit code aggregation
- Docs: `docs/WORKFLOWS.md` entry + CLI docs

## Out-of-scope (explicit)
- Any mutations in UI
- New policy DSL or saved policies
- Parallel execution (Phase 2+ only; Phase 1 is deterministic serial)
- Cross-repo graph merges (future)
- Multi-process concurrency / scheduling

## Guardrails
- Do not touch strict schema contract (1.0) or report contract (2.0)
- Avoid expanding existing exports except by adding new portfolio artifacts
- No new heavy dependencies
