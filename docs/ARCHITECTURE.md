# Codex Kernel — Architecture
Version: v1.0 target
Status: Stable core (v0.4 baseline)

Codex Kernel is a deterministic governance engine for multi-system discipline enforcement.

It is not an application layer.
It is not a UI.
It is not a scheduler.

It is a local-first, CLI-driven governance substrate.

---

# 1. Core Model

The Kernel evaluates systems defined in a registry.

Flow:

Registry → Contracts + Events → Discipline → Scoring → Report → Strict Gate

There is no hidden state.

All behavior is derived from:
- `/data/registry/systems.json`
- `/data/contracts/*.json`
- `/data/logs/*.jsonl`
- `/data/primitives/schemas/*.json`

---

# 2. Registry-Driven Systems

Registry is authoritative.

Each system defines:

- `system_id`
- `contracts_glob`
- `events_glob`
- `is_sample`
- `notes`

There are no hardcoded systems in scoring or reporting logic.

If a system is not in the registry, it does not exist to the kernel.

---

# 3. Health Evaluation Model

Per-system evaluation consists of:

### 3.1 Contracts
- Presence contributes to score.
- `primitives_used` (list)
- `invariants` (list)

Minimum discipline rules:
- `len(primitives_used) >= 3`
- `len(invariants) >= 3`

Violations:
- `PRIMITIVES_MIN`
- `INVARIANTS_MIN`

### 3.2 Events
- JSONL entries.
- `ts` required and parseable ISO timestamp.
- At least one event within last 14 days relative to evaluation time.

Violation:
- `EVENTS_RECENT`

---

# 4. Determinism Invariants

The kernel is deterministic by design.

## 4.1 No Hidden Time Reads
All time-sensitive logic derives from a single seam:
- `_now_utc()` (or equivalent)

Time-indexed evaluation supports:
- `as_of: datetime`

When evaluating at time `t`:
- Only events with `event.ts <= t` are considered.
- Recency window is relative to `t`.

## 4.2 Pure Scoring Core
Numeric scoring:
- Does not read files.
- Does not read time.
- Does not recompute discipline internally.

Discipline is computed once and reused everywhere.

## 4.3 Stable Ordering
All outputs:
- Sorted deterministically.
- Explicit tie-breakers used where ranking exists.
- No reliance on dictionary insertion order.

## 4.4 No Hidden State
The kernel:
- Reads only from `/data`.
- Does not persist runtime caches.
- In-report memoization is local and ephemeral.

---

# 5. Sample Isolation Model

Sample systems (`is_sample=true`) are:

- Evaluated normally.
- Included in reporting.
- Allowed to be red intentionally.

But:

- NEVER affect strict gating.
- NEVER appear in non-sample drift attribution.

Sample isolation applies only to enforcement, not to schema validation.

---

# 6. Reporting Architecture

Two report modes:

- Text (`report health`)
- JSON (`report health --json`)

JSON includes:
- `report_version`
- `summary`
- `trend`
- `hints`

Report contract is stable across v1.x (additive changes allowed).

---

# 7. Strict Gate

Command:


python -m app.main health --all --strict


Rules:
- If any NON-SAMPLE system is RED → exit code 2.
- Sample systems do not affect strict.
- Strict does not depend on global snapshot score.

Strict is enforcement.
Report is observability.

---

# 8. Drift Detection

Drift is advisory.

Definition:


drift = latest_score - score_at_or_before(now - 24h)
drop = -drift


Thresholds:
- `drop > 10` → MED
- `drop > 20` → HIGH

If triggered:
- Include top 3 non-sample contributors.
- Deterministic ordering: (-drop, system_id).

Drift never affects strict gating.

---

# 9. Validation Layer

Command:


python -m app.main validate


Validation checks:
- Registry structure + uniqueness.
- Schema parseability.
- Contract parseability + required fields.
- Event parseability + `ts` presence.
- Glob resolution.

Validation enforces structural integrity.

Health enforces discipline.

---

# 10. Non-Goals (v1.0)

The kernel does NOT include:

- Web UI
- Background scheduler
- External storage
- Auto-remediation
- Dependency graph
- Notification systems

These may exist in v1.x or later.

---

# 11. Versioning Policy

v1.0 stabilizes:

- CLI surface.
- Exit codes.
- JSON report contract.
- Deterministic semantics.

Breaking changes require v2.0.

Additive extensions allowed in v1.x.

---

# 12. Architectural Principle

Determinism > Convenience  
Enforcement > Visibility  
Registry > Hardcoding  
Pure Functions > Implicit State  

The kernel must remain replayable, predictable, and explainable.
