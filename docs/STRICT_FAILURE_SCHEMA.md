# Strict Failure Schema (v1)

This schema is emitted as a single JSON line to **stderr** when strict gating fails.

- Deterministic ordering.
- Backwards compatible changes must only be additive.
- Breaking changes require bumping `schema_version`.

## Shape

```json
{
  "strict_failed": true,
  "schema_version": "1.0",
  "policy": {
    "blocked_tiers": ["prod", "staging"],
    "include_staging": true,
    "include_dev": false,
    "enforce_sla": true
  },
  "reasons": [
    {
      "system_id": "atlas-core",
      "tier": "prod",
      "reason_code": "RED_STATUS",
      "details": {
        "status": "red",
        "score_total": 69.0,
        "violations": ["PRIMITIVES_MIN"]
      }
    },
    {
      "system_id": "ops-core",
      "tier": "prod",
      "reason_code": "SLA_BREACH",
      "details": {
        "sla_status": "breach",
        "days_since_event": 9,
        "threshold_days": 7
      }
    }
  ]
}
```

reason_code enum

RED_STATUS: system status is red for a policy-blocked tier (non-sample).

SLA_BREACH: SLA status is breach for a policy-blocked tier (non-sample) when enforce_sla=true.

Ordering

reasons sorted by:

reason_code (lexicographic)

tier

system_id

Stability rules

New fields may be added inside details without bumping version.

New reason_code values require updating this doc and tests.

Any rename/removal of top-level keys or existing fields requires bumping schema_version.
