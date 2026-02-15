# Codex Kernel — v1.0 Acceptance Criteria
Version target: v1.0.0  
Current baseline: v0.4.0 (stable)

This document defines the non-negotiable acceptance criteria for Codex Kernel v1.0.
Anything not listed here is explicitly NOT required for v1.0.

---

## 0) Definition of Done (v1.0)
v1.0.0 is cut when ALL items below are true:

- CLI contract is stable and documented.
- Data contracts are stable and validated.
- Determinism invariants are enforced (tests + CI).
- Strict governance semantics are locked.
- Reporting JSON contract is stable and versioned.
- No hidden state outside `/data`.
- No non-deterministic ordering in outputs.

---

## 1) Scope (v1.0 In / Out)

### In scope (must ship)
- Registry-driven multi-system governance.
- Per-system health scoring (contracts + primitives/invariants + events).
- Sample isolation (`is_sample=true`) and strict gating (non-sample only).
- Reporting (text + JSON), including:
  - non-sample headline aggregation
  - global snapshot separation
  - deterministic hints (including drift + attribution)
- Time-indexed evaluation via `as_of` (deterministic replay).

### Out of scope (not required)
- Web UI / dashboards.
- Background scheduler / cron / daemons.
- Cloud services / hosted storage.
- LLM integration.
- Auto-remediation / auto-writing events/contracts.
- Cross-system dependency graphs (can be v1.x).

---

## 2) CLI Contract (Stable Surface)

### Required commands
These commands MUST exist and behave deterministically:

- `init`
- `health`
- `health --all`
- `health --all --strict`
- `report health`
- `report health --json`
- `report health --no-hints` (if supported today, must remain stable)
- `system add`
- `system list`
- `contract new`
- `log`

### Exit codes (canonical)
- `0` → success
- `1` → CLI misuse / validation error (bad inputs, missing files, schema invalid)
- `2` → strict failure (any NON-SAMPLE system is red)

### Strict semantics (canonical)
- If any NON-SAMPLE system is red → exit `2`.
- Sample systems NEVER affect strict gating.
- Strict mode must never depend on global snapshot score.

---

## 3) Data Contracts (Stable + Validated)

### 3.1 Registry schema (systems.json)
Registry is authoritative. No hardcoded systems.

Each system entry must contain:
- `system_id` (string, unique)
- `contracts_glob` (string)
- `events_glob` (string)
- `is_sample` (bool)
- `notes` (string, optional)

Validation rules:
- `system_id` unique across registry.
- `contracts_glob` resolves to 0+ files (0 allowed but affects score).
- `events_glob` resolves to 0+ files (0 allowed but affects score).
- No registry entry may crash evaluation; failures must become deterministic violations/errors.

### 3.2 Contract JSON schema
Minimum required fields must be validated (exact schema as implemented).
Validate checks presence + type:
- `primitives_used` exists and is list
- `invariants` exists and is list

Minimum lengths are enforced by health discipline (`PRIMITIVES_MIN`, `INVARIANTS_MIN`).

### 3.3 Event JSONL schema
Each event row must validate:
- `ts` is present and parseable as ISO timestamp (Z or offset or naive assumed UTC).
- Additional fields are allowed but must not break parsing.

Event discipline requirement:
- At least one event within the last 14 days relative to evaluation time `t`.
Violation:
- `EVENTS_RECENT`

### 3.4 No hidden state rule
Kernel may only read/write inside `/data` (plus repo code).
No implicit caches persisted across runs.

---

## 4) Determinism Invariants (Non-Negotiable)

### 4.1 No hidden time reads
All time-dependent behavior must derive from a single seam:
- `_now_utc()` (or equivalent)

Time-indexed evaluation must support:
- `as_of: datetime` for per-system health evaluation and discipline checks

### 4.2 Time-indexed event replay (as_of)
When evaluating at time `t`:
- Only events with `event.ts <= t` may be considered.
- Recency window is relative to `t` (not wall-clock).

### 4.3 Stable ordering
All lists in JSON/text output must have deterministic ordering:
- tie-breakers must be explicit (e.g., `(-drop, system_id)`)

### 4.4 Pure scoring core
Numeric scoring function must be pure:
- no file reads
- no time reads
- no internal discipline recomputation

Discipline must be computed once per evaluation and reused everywhere.

---

## 5) Health Scoring Semantics (Canonical)

### 5.1 Weighted scoring (as implemented)
Health score uses:
- Contracts presence
- Event count
- Primitives/invariant count

Penalty:
- 25 points per violation instance (canonical)

Clamp rule (canonical):
- If violations exist AND score_total >= 70 → clamp to 69

Status bands (canonical):
- 0–69 → RED
- 70–84 → YELLOW
- 85–100 → GREEN

### 5.2 Sample isolation (canonical)
- Sample systems may be red by design.
- Sample systems never affect strict gating.
- Sample systems never appear in non-sample drift attribution.

---

## 6) Reporting Contract (Stable)

### 6.1 Text report
`report health` must include:
- Headline for non-sample aggregate + strict PASS/FAIL
- Global snapshot line (and flag that includes samples)
- Trend summary (start/end/delta/rolling avg)
- Drift line (24h)
- Top drift (24h) contributors when available
- Per-system current status (sample flagged explicitly)

### 6.2 JSON report
`report health --json` must include:
- `summary` block with:
  - non-sample aggregate now
  - global snapshot now
  - strict pass/fail
  - `hints_count` equals `len(hints)`
  - `top_drift_24h` when available
- `trend` block containing:
  - points with timestamps + scores (deterministic ordering)
  - rolling average
- `hints` list with deterministic structure:
  - `severity` ∈ {`high`,`med`,`low`}
  - `title`, `why`, `fix`, `systems`

### 6.3 Hints semantics (canonical)
- If non-sample red:
  - up to 2 HIGH hints based on most frequent current violations
- If strict passes but global snapshot red:
  - one LOW hint explaining sample/legacy drift
- If fully clean:
  - LOW “No action required”
- Drift hints:
  - `drift = latest_score - score_at_or_before(now - 24h)`
  - `drop = -drift`
  - `drop > 10` → MED
  - `drop > 20` → HIGH
  - If drift triggers, include top 3 non-sample contributors (deterministic ordering)

---

## 7) Validation Command (Required for v1.0)
Kernel must provide deterministic validation that fails fast with exit code `1`.

Minimum checks:
- Registry schema valid + unique system_id
- Contract files parse + required fields
- Contract list-field checks: `primitives_used` and `invariants` exist and are lists
- Event files parse + required `ts`
- No crash on missing globs; surface deterministic error messages

Minimum list lengths are enforced by health discipline (`PRIMITIVES_MIN`, `INVARIANTS_MIN`), not by `validate`.

This may be implemented as:
- `python -m app.main validate`
OR equivalent existing command extension

---

## 8) Test + CI Acceptance
v1.0 requires:
- Unit tests for scoring invariants (clamp, bands, penalties)
- Tests for sample isolation (strict + drift attribution)
- Tests for drift semantics (24h thresholds)
- Tests for single-truth discipline (status derived from payload violations)
- CI workflow runs:
  1) tests
  2) `report health` (echo drift)
  3) `health --all --strict`

---

## 9) Versioning + Compatibility Promise (v1.x)
After v1.0:
- CLI commands and exit codes remain stable across v1.x.
- JSON report keys remain stable across v1.x (additive changes allowed; breaking changes require v2.0).
- Data contract changes require explicit schema versioning and migration notes.

---

## 10) Open Items (Allowed Post-1.0)
These are explicitly deferred:
- Dependency graph + blast radius
- Scheduled audits
- Web UI
- Auto-contract scaffolding
- SLA escalation / notifications

Next steps tonight (tight sequence)

Create the file: docs/V1_ACCEPTANCE.md with the above content
