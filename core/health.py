from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.events import read_events_from_glob
from core.globs import iter_glob
from core.models import Health
from core.registry import registry_path as default_registry_path
from core.storage import PRIMITIVES_DIR, SCHEMAS_DIR, list_contracts, list_event_rows, read_jsonl


HIGH_VIOLATIONS = {"PRIMITIVES_MIN", "INVARIANTS_MIN"}


def _has_high_violations(violations: list[str]) -> bool:
    return any(str(v) in HIGH_VIOLATIONS for v in violations)


def _count_invariants() -> int:
    path = PRIMITIVES_DIR / "invariants.yaml"
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("- id:"):
            count += 1
    return count


def _count_schemas() -> int:
    if not SCHEMAS_DIR.exists():
        return 0
    return len(sorted(SCHEMAS_DIR.glob("*.json")))


def _parse_ts(value: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_iso_utc(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _list_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def _read_contracts_from_glob(
    pattern: str,
    system_id: str,
    *,
    registry_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    reg_path = default_registry_path(registry_path)
    for path in iter_glob(pattern, reg_path):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            if str(payload.get("system_id", "")).strip() != system_id:
                continue
            out.append(payload)
    out.sort(key=lambda o: (str(o.get("contract_id", "")), json.dumps(o, sort_keys=True)))
    return out


def _read_events_from_glob(
    pattern: str,
    system_id: str,
    *,
    registry_path: str | Path | None = None,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    reg_path = default_registry_path(registry_path)
    rows = read_events_from_glob(pattern, registry_path=reg_path, as_of=as_of)

    # Backward-compatible fallback: lines missing ts are treated as current/as_of timestamp.
    fallback_dt = as_of.astimezone(timezone.utc) if as_of is not None else datetime.now(timezone.utc)
    fallback_ts = fallback_dt.isoformat().replace("+00:00", "Z")
    for path in iter_glob(pattern, reg_path):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            ts = payload.get("ts")
            if isinstance(ts, str) and ts.strip():
                continue
            patched = dict(payload)
            patched["ts"] = fallback_ts
            if not patched.get("system_id"):
                patched["system_id"] = system_id
            rows.append(patched)

    filtered: list[dict[str, Any]] = []
    for r in rows:
        sid = r.get("system_id")
        if sid is None or str(sid) == system_id:
            filtered.append(r)
    filtered.sort(
        key=lambda o: (
            (_parse_iso_utc(str(o.get("ts", ""))).isoformat() if o.get("ts") else ""),
            json.dumps(o, sort_keys=True),
        )
    )
    return filtered


def _count_events_lines_from_glob(pattern: str, registry_path: str | Path | None = None) -> int:
    count = 0
    reg_path = default_registry_path(registry_path)
    for path in iter_glob(pattern, reg_path):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                count += 1
    return count


def _compute_discipline(
    contract_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    systems: dict[str, dict[str, bool]] = {}
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    as_of_utc = as_of.astimezone(timezone.utc)
    recent_cutoff = as_of_utc - timedelta(days=14)

    for contract in contract_rows:
        system_id = str(contract.get("system_id", "")).strip()
        if not system_id:
            continue
        entry = systems.setdefault(
            system_id,
            {"primitives_ok": True, "invariants_ok": True, "events_recent_ok": False},
        )
        primitives_count = _list_count(contract.get("primitives_used"))
        invariants_count = _list_count(contract.get("invariants"))
        if primitives_count < 3:
            entry["primitives_ok"] = False
        if invariants_count < 3:
            entry["invariants_ok"] = False

    for event in event_rows:
        system_id = str(event.get("system_id", "")).strip()
        if not system_id:
            continue
        entry = systems.setdefault(
            system_id,
            {"primitives_ok": False, "invariants_ok": False, "events_recent_ok": False},
        )
        ts = event.get("ts")
        if not ts:
            continue
        try:
            dt = _parse_iso_utc(str(ts))
        except Exception:
            continue
        if dt >= recent_cutoff:
            entry["events_recent_ok"] = True

    violations: list[str] = []
    violating_pairs = 0
    per_system: list[dict[str, Any]] = []

    for system_id in sorted(systems):
        state = systems[system_id]
        per_system.append({"system_id": system_id, **state})
        if not state["primitives_ok"]:
            violations.append("PRIMITIVES_MIN")
            violating_pairs += 1
        if not state["invariants_ok"]:
            violations.append("INVARIANTS_MIN")
            violating_pairs += 1
        if not state["events_recent_ok"]:
            violations.append("EVENTS_RECENT")
            violating_pairs += 1

    unique_violations = sorted(set(violations))
    return {
        "violations": unique_violations,
        "per_system": per_system,
        "penalty": violating_pairs * 25.0,
    }


def _score_health(
    contract_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    *,
    discipline_penalty: float = 0.0,
    has_high_violations: bool = False,
) -> Health:
    contracts_count = len(contract_rows)
    events_count = len(event_rows)
    schema_count = _count_schemas()
    invariant_count = _count_invariants()

    score_contracts = 100.0 if contracts_count > 0 else 35.0
    score_events = min(100.0, 50.0 + events_count * 5.0)
    score_primitives = min(100.0, (schema_count * 20.0) + (invariant_count * 20.0))
    score_total = (score_contracts * 0.4) + (score_events * 0.3) + (score_primitives * 0.3)

    score_total -= float(discipline_penalty)
    score_total = max(0.0, min(100.0, score_total))
    if has_high_violations and score_total >= 70.0:
        score_total = 69.0
    score_total = round(score_total, 2)

    return Health(
        contracts_count=contracts_count,
        events_count=events_count,
        schema_count=schema_count,
        invariant_count=invariant_count,
        score_contracts=round(score_contracts, 2),
        score_events=round(score_events, 2),
        score_primitives=round(score_primitives, 2),
        score_total=score_total,
    )


def compute_health() -> Health:
    contract_rows = list_contracts()
    event_rows = list_event_rows()
    discipline = _compute_discipline(contract_rows, event_rows)
    return _score_health(
        contract_rows,
        event_rows,
        discipline_penalty=float(discipline["penalty"]),
        has_high_violations=_has_high_violations(list(discipline["violations"])),
    )


def _status_for(score_total: float, violations: list[str]) -> str:
    if _has_high_violations(list(violations)):
        return "red"
    if score_total >= 85.0:
        return "green"
    if score_total >= 70.0:
        return "yellow"
    return "red"


def _canonical_from_health(
    health_model: Health,
    discipline: dict[str, Any],
    snapshot_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    health = health_model.model_dump()
    canonical = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": _status_for(health["score_total"], discipline["violations"]),
        "score_total": health["score_total"],
        "violations": discipline.get("violations", []),
        "counts": {
            "contracts": health["contracts_count"],
            "events": health["events_count"],
            "invariants": health["invariant_count"],
            "schemas": health["schema_count"],
        },
        "scores": {
            "contracts": health["score_contracts"],
            "events": health["score_events"],
            "primitives": health["score_primitives"],
        },
        "per_system": discipline.get("per_system", []),
    }
    if snapshot_files is not None:
        canonical["snapshot_files"] = snapshot_files
    return canonical


def compute_health_for_system(
    system_id: str,
    contracts_glob: str,
    events_glob: str,
    *,
    registry_path: str | Path | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    contract_rows = _read_contracts_from_glob(
        contracts_glob,
        system_id,
        registry_path=registry_path,
    )

    event_rows = _read_events_from_glob(events_glob, system_id, registry_path=registry_path, as_of=as_of)

    discipline = _compute_discipline(contract_rows, event_rows, as_of=as_of)
    health_model = _score_health(
        contract_rows,
        event_rows,
        discipline_penalty=float(discipline["penalty"]),
        has_high_violations=_has_high_violations(list(discipline["violations"])),
    )
    return _canonical_from_health(health_model, discipline)


def compute_and_write_health() -> tuple[dict[str, Any], dict[str, str]]:
    contract_rows = list_contracts()
    event_rows = list_event_rows()
    discipline = _compute_discipline(contract_rows, event_rows)
    health_model = _score_health(
        contract_rows,
        event_rows,
        discipline_penalty=float(discipline["penalty"]),
        has_high_violations=_has_high_violations(list(discipline["violations"])),
    )

    snapshot_dir = Path("data/snapshots")
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    latest_path = snapshot_dir / "health_latest.json"
    history_path = snapshot_dir / "health_history.jsonl"
    snapshot_files = {
        "latest": str(latest_path),
        "history": str(history_path),
    }

    canonical = _canonical_from_health(health_model, discipline, snapshot_files=snapshot_files)

    with open(latest_path, "w") as f:
        json.dump(canonical, f, indent=2)

    with open(history_path, "a") as f:
        f.write(json.dumps(canonical, sort_keys=True) + "\n")

    return canonical, snapshot_files
