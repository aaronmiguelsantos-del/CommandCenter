---
name: telemetry-slo-guard
description: Enforce per-skill telemetry SLOs (success rate, p95 latency, and invocation minimums) from usage events with deterministic CI exit codes.
---

# Telemetry SLO Guard

Gate publish and nightly workflows with deterministic telemetry SLO checks.

## Workflow

1. Run SLO gate:
```bash
python3 scripts/check_telemetry_slo.py \
  --events /absolute/path/to/data/skill_usage_events.jsonl \
  --config /absolute/path/to/slo_config.json \
  --strict \
  --json
```

2. Override analysis window:
```bash
python3 scripts/check_telemetry_slo.py \
  --events /absolute/path/to/data/skill_usage_events.jsonl \
  --config /absolute/path/to/slo_config.json \
  --window 30 \
  --trend-windows 4 \
  --strict \
  --json
```

## Guarantees

- Validates event rows against `skill_usage_events.schema.json`.
- Applies deterministic per-skill SLO thresholds from JSON config.
- Supports trend degradation gates (`trend_windows`, `max_success_rate_drop`, `max_p95_increase_ms`).
- Exits `2` in strict mode on SLO violations.
