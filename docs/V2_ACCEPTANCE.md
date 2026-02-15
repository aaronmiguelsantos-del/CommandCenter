# Codex Kernel — v2.0 Acceptance Criteria
Version target: v2.0.0  
Baseline: v1.0.1 (deterministic governance kernel)

v2.0 introduces dependency-aware governance, enforcement tiers, and impact modeling.

This is a capability-class upgrade.  
It must not break v1.x deterministic guarantees.

---

# 0) Definition of Done (v2.0)

v2.0.0 is cut when:

- Registry supports dependency graph + tier model.
- Graph is validated (no missing refs, no cycles).
- Health report includes impact analysis.
- Strict gating supports policy tiers.
- JSON report contract is updated to `"report_version": "2.0"`.
- All ordering is deterministic.
- All new logic is test-covered.
- v1.x semantics remain backward compatible by default.

---

# 1) Registry Extensions (Required)

Each system entry MAY include:

```json
{
  "system_id": "atlas-core",
  "depends_on": ["ops-core"],
  "owners": ["aaron"],
  "tier": "prod"
}

1.1 Tier Model (Required)

Valid values:

prod

staging

dev

sample

Rules:

sample MUST still use is_sample=true (backward compatible).

If tier missing:

default to prod for backward compatibility.

tier is case-sensitive and validated.

Invalid values → REGISTRY_TIER_INVALID

2) Dependency Graph Model (Required)
2.1 Validation

Validator must enforce:

All depends_on entries reference existing system_id.

Error: REGISTRY_DEPENDENCY_MISSING

Graph must be acyclic.

Error: REGISTRY_CYCLE_DETECTED

depends_on must be a list if present.

Error: REGISTRY_DEPENDENCY_INVALID

Validation failure → exit code 1.

2.2 Deterministic Graph Representation

Kernel must compute:

Adjacency list

Reverse dependency map

Deterministic topological order

Tie-breaking rule:

Alphabetical system_id for equal depth nodes.

3) Impact Model (Required)

When a system is:

RED

YELLOW

Drift-drop > threshold

It becomes a source.

Kernel must compute:

Transitive dependents (impacted systems).

Distance (hop count from source).

Deterministic ranking:

Sort by:

Tier severity (prod > staging > dev > sample)

Distance (ascending)

system_id alphabetical

4) Reporting Contract (v2)

report health --json must now include:

{
  "report_version": "2.0",
  "impact": {
    "sources": [...],
    "impacted": [
      {
        "system_id": "...",
        "distance": 1,
        "tier": "prod"
      }
    ]
  }
}


Rules:

If no impacted systems, impact block still exists with empty lists.

Sample systems may appear as impacted but never as strict blockers.

Ordering deterministic.

Text report must include:

Impact: line when sources exist.

Format:
Impact: ops-core → atlas-core (1 hop)

5) Enforcement Policy (Tier-Aware Strict)

Default behavior (backward compatible):

health --all --strict


Must enforce:

Only tier == "prod" systems block strict.

staging, dev, and sample never block strict by default.

New strict flags:

health --all --strict --include-staging
health --all --strict --include-dev


Rules:

--include-staging blocks on prod + staging.

--include-dev blocks on prod + staging + dev.

sample never blocks.

Exit codes unchanged:

0 pass

1 misuse/validation

2 strict failure

6) Hints Upgrade (Required)

Hints must now optionally include:

Impacted systems

Tier context

Owners (if provided in registry)

Example:

{
  "severity": "high",
  "title": "Prod governance breach",
  "why": "ops-core is red (EVENTS_RECENT). Impacted: atlas-core (1 hop).",
  "fix": "Emit at least one ops-core event within 14 days.",
  "systems": ["ops-core"],
  "owners": ["aaron"]
}


Ordering deterministic.

7) Backward Compatibility (Non-Negotiable)

v2.0 must:

Accept registries without tier, depends_on, or owners.

Default missing tier to "prod".

Preserve v1.x strict behavior when no new flags are used.

Preserve JSON fields from v1.x unchanged (additive only).

Breaking changes require v3.0.

8) Validation Command Upgrade

validate must now also check:

Dependency existence

Cycle detection

Tier validity

Owners type (list if present)

Must remain deterministic.
Must not crash on malformed input.

9) Non-Goals (Still Not in v2.0)

Web UI

Background scheduler

Notifications

Auto-remediation

External databases

v2.0 strengthens governance substrate only.

10) Architectural Principle (v2 Layer)

Health answers:

Is this system disciplined?

Graph answers:

What does it affect?

Policy answers:

Should this block deployment?

Kernel must remain:

Deterministic

Replayable

Pure

CLI-first

UI-ready via JSON contract
