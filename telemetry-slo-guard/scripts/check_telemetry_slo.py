#!/usr/bin/env python3
"""Check per-skill telemetry SLO thresholds and trend degradation gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List


class TelemetrySLOError(Exception):
    pass


def _parse_timestamp_order_key(raw: str) -> str:
    return raw.strip()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise TelemetrySLOError(f"invalid json file {path}: {err}") from err
    if not isinstance(obj, dict):
        raise TelemetrySLOError(f"json file must be object: {path}")
    return obj


def _load_schema(path: Path) -> Dict[str, Any]:
    schema = _load_json(path)
    if not isinstance(schema.get("properties"), dict) or not isinstance(schema.get("required"), list):
        raise TelemetrySLOError(f"invalid schema shape: {path}")
    return schema


def _validate_event(schema: Dict[str, Any], row: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    type_map = {"integer": int, "number": (int, float), "array": list, "string": str, "object": dict}

    for key in required:
        if key not in row:
            errors.append(f"missing required key: {key}")
    for key, prop in properties.items():
        if key not in row:
            continue
        if not isinstance(prop, dict):
            continue
        expected = prop.get("type")
        py_t = type_map.get(expected)
        if py_t and not isinstance(row[key], py_t):
            errors.append(f"invalid type for {key}: expected {expected}")
            continue
        enum = prop.get("enum")
        if isinstance(enum, list) and row[key] not in enum:
            errors.append(f"invalid value for {key}: {row[key]}")
    return errors


def _load_events(path: Path, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not path.exists():
        raise TelemetrySLOError(f"events file not found: {path}")
    rows: List[Dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception as err:
            raise TelemetrySLOError(f"invalid json line {i}: {err}") from err
        if not isinstance(obj, dict):
            raise TelemetrySLOError(f"invalid event row at line {i}: expected object")
        row_errors = _validate_event(schema, obj)
        if row_errors:
            raise TelemetrySLOError(f"event schema validation failed at line {i}: {'; '.join(row_errors)}")
        rows.append(obj)
    rows.sort(key=lambda row: _parse_timestamp_order_key(str(row.get("timestamp_utc", ""))))
    return rows


def _p95(values: List[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, int(round(0.95 * (len(ordered) - 1))))
    return int(ordered[idx])


def _as_int(value: Any, field: str) -> int:
    try:
        out = int(value)
    except Exception as err:
        raise TelemetrySLOError(f"invalid integer for {field}: {value}") from err
    return out


def _as_float(value: Any, field: str) -> float:
    try:
        out = float(value)
    except Exception as err:
        raise TelemetrySLOError(f"invalid number for {field}: {value}") from err
    return out


def _window_row(skill: str, rows: List[Dict[str, Any]], index: int) -> Dict[str, Any]:
    invocations = len(rows)
    successes = sum(1 for e in rows if str(e.get("status", "")) == "success")
    durations = [max(0, _as_int(e.get("duration_ms", 0), f"{skill}.duration_ms")) for e in rows]
    success_rate = (float(successes) / float(invocations)) if invocations > 0 else 0.0
    return {
        "window_index": index,
        "invocations": invocations,
        "success_rate": round(success_rate, 4),
        "p95_duration_ms": _p95(durations),
    }


def _trend_report(
    skill: str,
    skill_events: List[Dict[str, Any]],
    window: int,
    trend_windows: int,
    max_success_rate_drop: float,
    max_p95_increase_ms: int,
) -> Dict[str, Any]:
    enabled = trend_windows >= 2
    if not enabled:
        return {
            "enabled": False,
            "trend_windows": trend_windows,
            "windows_evaluated": 0,
            "max_success_rate_drop": max_success_rate_drop,
            "max_p95_increase_ms": max_p95_increase_ms,
            "deltas": [],
            "violations": [],
        }

    needed = window * trend_windows
    tail = skill_events[-needed:]
    total_windows = len(tail) // window
    if total_windows < 2:
        return {
            "enabled": True,
            "trend_windows": trend_windows,
            "windows_evaluated": total_windows,
            "max_success_rate_drop": max_success_rate_drop,
            "max_p95_increase_ms": max_p95_increase_ms,
            "deltas": [],
            "violations": [],
        }

    usable = tail[-(total_windows * window) :]
    windows: List[Dict[str, Any]] = []
    for i in range(total_windows):
        chunk = usable[i * window : (i + 1) * window]
        windows.append(_window_row(skill, chunk, index=i + 1))

    deltas: List[Dict[str, Any]] = []
    for i in range(1, len(windows)):
        prev = windows[i - 1]
        curr = windows[i]
        drop = round(float(prev["success_rate"]) - float(curr["success_rate"]), 4)
        p95_increase = int(curr["p95_duration_ms"]) - int(prev["p95_duration_ms"])
        deltas.append(
            {
                "from_window": int(prev["window_index"]),
                "to_window": int(curr["window_index"]),
                "success_rate_drop": drop,
                "p95_increase_ms": p95_increase,
            }
        )

    violations: List[Dict[str, Any]] = []
    worst_drop = max([0.0] + [float(d["success_rate_drop"]) for d in deltas])
    worst_p95_increase = max([0] + [int(d["p95_increase_ms"]) for d in deltas])

    if worst_drop > max_success_rate_drop:
        violations.append(
            {
                "type": "trend_success_rate_drop",
                "actual": round(worst_drop, 4),
                "expected": max_success_rate_drop,
            }
        )
    if worst_p95_increase > max_p95_increase_ms:
        violations.append(
            {
                "type": "trend_p95_increase_ms",
                "actual": worst_p95_increase,
                "expected": max_p95_increase_ms,
            }
        )

    return {
        "enabled": True,
        "trend_windows": trend_windows,
        "windows_evaluated": len(windows),
        "max_success_rate_drop": max_success_rate_drop,
        "max_p95_increase_ms": max_p95_increase_ms,
        "deltas": deltas,
        "violations": violations,
    }


def _build_report(events: List[Dict[str, Any]], config: Dict[str, Any], window_override: int, trend_windows_override: int) -> Dict[str, Any]:
    window = window_override if window_override > 0 else _as_int(config.get("window", 20), "window")
    if window < 1:
        raise TelemetrySLOError("window must be >= 1")

    rows = config.get("skills")
    if not isinstance(rows, list) or not rows:
        raise TelemetrySLOError("config must contain non-empty skills[]")

    skills_report: List[Dict[str, Any]] = []
    violations: List[Dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        skill = str(row.get("skill", "")).strip()
        if not skill:
            raise TelemetrySLOError("config skills[] row missing skill")

        min_invocations = _as_int(row.get("min_invocations", 1), f"{skill}.min_invocations")
        min_success_rate = _as_float(row.get("min_success_rate", 1.0), f"{skill}.min_success_rate")
        max_p95_duration_ms = _as_int(row.get("max_p95_duration_ms", 15000), f"{skill}.max_p95_duration_ms")

        trend_windows = (
            trend_windows_override
            if trend_windows_override >= 0
            else _as_int(row.get("trend_windows", 0), f"{skill}.trend_windows")
        )
        max_success_rate_drop = _as_float(
            row.get("max_success_rate_drop", 1.0),
            f"{skill}.max_success_rate_drop",
        )
        max_p95_increase_ms = _as_int(
            row.get("max_p95_increase_ms", 2_000_000_000),
            f"{skill}.max_p95_increase_ms",
        )

        if min_invocations < 0:
            raise TelemetrySLOError(f"{skill}.min_invocations must be >= 0")
        if min_success_rate < 0 or min_success_rate > 1:
            raise TelemetrySLOError(f"{skill}.min_success_rate must be between 0 and 1")
        if max_p95_duration_ms < 0:
            raise TelemetrySLOError(f"{skill}.max_p95_duration_ms must be >= 0")
        if trend_windows < 0:
            raise TelemetrySLOError(f"{skill}.trend_windows must be >= 0")
        if max_success_rate_drop < 0 or max_success_rate_drop > 1:
            raise TelemetrySLOError(f"{skill}.max_success_rate_drop must be between 0 and 1")
        if max_p95_increase_ms < 0:
            raise TelemetrySLOError(f"{skill}.max_p95_increase_ms must be >= 0")

        skill_events = [e for e in events if str(e.get("skill", "")) == skill]
        latest_events = skill_events[-window:]
        invocations = len(latest_events)
        successes = sum(1 for e in latest_events if str(e.get("status", "")) == "success")
        durations = [max(0, _as_int(e.get("duration_ms", 0), f"{skill}.duration_ms")) for e in latest_events]
        success_rate = (float(successes) / float(invocations)) if invocations > 0 else 0.0
        p95_duration_ms = _p95(durations)

        trend = _trend_report(
            skill=skill,
            skill_events=skill_events,
            window=window,
            trend_windows=trend_windows,
            max_success_rate_drop=max_success_rate_drop,
            max_p95_increase_ms=max_p95_increase_ms,
        )

        skill_row = {
            "skill": skill,
            "window": window,
            "invocations": invocations,
            "successes": successes,
            "success_rate": round(success_rate, 4),
            "p95_duration_ms": p95_duration_ms,
            "trend_enabled": bool(trend.get("enabled", False)),
            "thresholds": {
                "min_invocations": min_invocations,
                "min_success_rate": min_success_rate,
                "max_p95_duration_ms": max_p95_duration_ms,
            },
            "trend": trend,
        }

        if invocations < min_invocations:
            violations.append(
                {
                    "skill": skill,
                    "type": "min_invocations",
                    "actual": invocations,
                    "expected": min_invocations,
                }
            )
        if success_rate < min_success_rate:
            violations.append(
                {
                    "skill": skill,
                    "type": "min_success_rate",
                    "actual": round(success_rate, 4),
                    "expected": min_success_rate,
                }
            )
        if p95_duration_ms > max_p95_duration_ms:
            violations.append(
                {
                    "skill": skill,
                    "type": "max_p95_duration_ms",
                    "actual": p95_duration_ms,
                    "expected": max_p95_duration_ms,
                }
            )

        for row_violation in trend.get("violations", []):
            if not isinstance(row_violation, dict):
                continue
            violations.append(
                {
                    "skill": skill,
                    "type": str(row_violation.get("type", "trend_violation")),
                    "actual": row_violation.get("actual"),
                    "expected": row_violation.get("expected"),
                }
            )

        skills_report.append(skill_row)

    return {
        "schema_version": 1,
        "events_total": len(events),
        "window": window,
        "skills": skills_report,
        "violations": violations,
        "passed": len(violations) == 0,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check telemetry SLO thresholds for key skills")
    p.add_argument("--events", required=True, help="Path to skill_usage_events.jsonl")
    p.add_argument(
        "--config",
        default="",
        help="Optional SLO config path (defaults to telemetry-slo-guard/references/default_slo_config.json)",
    )
    p.add_argument(
        "--schema",
        default="",
        help="Optional event schema path (defaults to skill-adoption-analytics/references/skill_usage_events.schema.json)",
    )
    p.add_argument("--window", type=int, default=0, help="Optional override for per-skill rolling event window")
    p.add_argument(
        "--trend-windows",
        type=int,
        default=-1,
        help="Optional override for trend window count (>=2 enables trend checks, 0 disables)",
    )
    p.add_argument("--strict", action="store_true", help="Exit 2 on SLO violations")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    events_path = Path(args.events).expanduser().resolve()
    config_path = (
        Path(args.config).expanduser().resolve()
        if args.config
        else repo_root / "telemetry-slo-guard" / "references" / "default_slo_config.json"
    )
    schema_path = (
        Path(args.schema).expanduser().resolve()
        if args.schema
        else repo_root / "skill-adoption-analytics" / "references" / "skill_usage_events.schema.json"
    )

    try:
        config = _load_json(config_path)
        schema = _load_schema(schema_path)
        events = _load_events(events_path, schema)
        report = _build_report(
            events=events,
            config=config,
            window_override=int(args.window),
            trend_windows_override=int(args.trend_windows),
        )
    except TelemetrySLOError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"events_total: {report['events_total']}")
        print(f"passed: {report['passed']}")
        for row in report["skills"]:
            print(
                f"- {row['skill']}: invocations={row['invocations']} success_rate={row['success_rate']} p95_ms={row['p95_duration_ms']}"
            )

    if args.strict and not report["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
