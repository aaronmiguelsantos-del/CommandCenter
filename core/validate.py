from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.health import _parse_iso_utc
from core.registry import VALID_TIERS, registry_path


def _coerce_registry_rows(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        systems = payload.get("systems", [])
        if isinstance(systems, list):
            return [row for row in systems if isinstance(row, dict)]
    raise ValueError("registry payload must be a list or object with 'systems' list")


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _err(code: str, detail: str) -> str:
    return f"{code}: {detail}"


def _first_cycle(adjacency: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}  # 0=unseen, 1=visiting, 2=done
    stack: list[str] = []
    index_by_node: dict[str, int] = {}

    def dfs(node: str) -> list[str] | None:
        state[node] = 1
        index_by_node[node] = len(stack)
        stack.append(node)

        for nxt in adjacency.get(node, []):
            st = state.get(nxt, 0)
            if st == 0:
                cycle = dfs(nxt)
                if cycle is not None:
                    return cycle
            elif st == 1:
                start = index_by_node[nxt]
                return stack[start:] + [nxt]

        stack.pop()
        index_by_node.pop(node, None)
        state[node] = 2
        return None

    for node in sorted(adjacency):
        if state.get(node, 0) == 0:
            cycle = dfs(node)
            if cycle is not None:
                return cycle
    return None


def validate_repo(path: str | Path | None = None) -> list[str]:
    errors: list[str] = []

    reg_path = registry_path(path)
    rows: list[dict[str, Any]] = []
    if not reg_path.exists():
        errors.append(_err("REGISTRY_MISSING", str(reg_path)))
    else:
        try:
            payload = _json_load(reg_path)
        except Exception as exc:
            errors.append(_err("REGISTRY_PARSE_ERROR", f"{reg_path}: {exc}"))
            payload = None
        if payload is not None:
            try:
                rows = _coerce_registry_rows(payload)
            except Exception as exc:
                errors.append(_err("REGISTRY_SCHEMA_INVALID", f"{reg_path}: {exc}"))

    seen: set[str] = set()
    systems: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        system_id = str(row.get("system_id", "")).strip()
        contracts_glob = str(row.get("contracts_glob", "")).strip()
        events_glob = str(row.get("events_glob", "")).strip()

        if not system_id:
            errors.append(_err("REGISTRY_SCHEMA_INVALID", f"row[{idx}] missing system_id"))
            continue
        if system_id in seen:
            errors.append(_err("REGISTRY_DUPLICATE_SYSTEM_ID", system_id))
        seen.add(system_id)

        if not contracts_glob:
            errors.append(_err("REGISTRY_SCHEMA_INVALID", f"{system_id} missing contracts_glob"))
        if not events_glob:
            errors.append(_err("REGISTRY_SCHEMA_INVALID", f"{system_id} missing events_glob"))

        tier = str(row.get("tier", "prod")).strip() or "prod"
        if tier not in VALID_TIERS:
            errors.append(_err("REGISTRY_TIER_INVALID", f"{system_id}: {tier}"))

        depends_raw = row.get("depends_on", [])
        depends_on: list[str] = []
        if depends_raw is None:
            depends_on = []
        elif not isinstance(depends_raw, list):
            errors.append(_err("REGISTRY_DEPENDENCY_INVALID", system_id))
        else:
            for dep in depends_raw:
                if isinstance(dep, str) and dep.strip():
                    depends_on.append(dep.strip())

        systems.append(
            {
                "system_id": system_id,
                "contracts_glob": contracts_glob,
                "events_glob": events_glob,
                "depends_on": depends_on,
            }
        )

    known_ids = {s["system_id"] for s in systems}
    for system in sorted(systems, key=lambda x: x["system_id"]):
        sid = system["system_id"]
        for dep in sorted(set(system["depends_on"])):
            if dep not in known_ids:
                errors.append(_err("REGISTRY_DEPENDENCY_MISSING", f"{sid}: {dep}"))

    adjacency: dict[str, list[str]] = {}
    for system in systems:
        sid = system["system_id"]
        adjacency[sid] = sorted({dep for dep in system["depends_on"] if dep in known_ids})
    cycle = _first_cycle(adjacency)
    if cycle is not None:
        errors.append(_err("REGISTRY_CYCLE_DETECTED", " -> ".join(cycle)))

    schema_dir = Path("data/primitives/schemas")
    schema_files = sorted(schema_dir.glob("*.json")) if schema_dir.exists() else []
    if not schema_files:
        errors.append(_err("SCHEMA_MISSING_TYPE", "no schema files found under data/primitives/schemas"))

    for schema_path in schema_files:
        try:
            schema = _json_load(schema_path)
        except Exception as exc:
            errors.append(_err("SCHEMA_PARSE_ERROR", f"{schema_path}: {exc}"))
            continue
        if not isinstance(schema, dict):
            errors.append(_err("SCHEMA_PARSE_ERROR", f"{schema_path}: schema must be JSON object"))
            continue
        if "type" not in schema:
            errors.append(_err("SCHEMA_MISSING_TYPE", str(schema_path)))

    for system in sorted(systems, key=lambda x: x["system_id"]):
        system_id = system["system_id"]
        contracts_glob = system["contracts_glob"]
        events_glob = system["events_glob"]

        contract_paths: list[Path] = []
        event_paths: list[Path] = []

        if contracts_glob:
            try:
                contract_paths = sorted(Path().glob(contracts_glob))
            except Exception as exc:
                errors.append(_err("GLOB_NO_MATCH", f"{system_id}: contracts_glob -> {contracts_glob}: {exc}"))
                contract_paths = []
            if not contract_paths:
                errors.append(_err("GLOB_NO_MATCH", f"{system_id}: contracts_glob -> {contracts_glob}"))

        if events_glob:
            try:
                event_paths = sorted(Path().glob(events_glob))
            except Exception as exc:
                errors.append(_err("GLOB_NO_MATCH", f"{system_id}: events_glob -> {events_glob}: {exc}"))
                event_paths = []
            if not event_paths:
                errors.append(_err("GLOB_NO_MATCH", f"{system_id}: events_glob -> {events_glob}"))

        for contract_path in contract_paths:
            try:
                payload = _json_load(contract_path)
            except Exception as exc:
                errors.append(_err("CONTRACT_PARSE_ERROR", f"{contract_path}: {exc}"))
                continue
            if not isinstance(payload, dict):
                errors.append(_err("CONTRACT_PARSE_ERROR", f"{contract_path}: contract must be JSON object"))
                continue

            for key in ("contract_id", "system_id", "name"):
                if not str(payload.get(key, "")).strip():
                    errors.append(_err("CONTRACT_MISSING_FIELD", f"{contract_path}: {key}"))

            primitives_used = payload.get("primitives_used")
            invariants = payload.get("invariants")

            if not isinstance(primitives_used, list):
                errors.append(_err("CONTRACT_MISSING_FIELD", f"{contract_path}: primitives_used"))

            if not isinstance(invariants, list):
                errors.append(_err("CONTRACT_MISSING_FIELD", f"{contract_path}: invariants"))

        for event_path in event_paths:
            try:
                lines = event_path.read_text(encoding="utf-8").splitlines()
            except Exception as exc:
                errors.append(_err("GLOB_NO_MATCH", f"{system_id}: {event_path}: {exc}"))
                continue

            for lineno, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception as exc:
                    errors.append(_err("SCHEMA_PARSE_ERROR", f"{event_path}:{lineno}: {exc}"))
                    continue
                if not isinstance(row, dict):
                    errors.append(_err("SCHEMA_PARSE_ERROR", f"{event_path}:{lineno}: event must be JSON object"))
                    continue

                ts = row.get("ts")
                if not ts:
                    errors.append(_err("EVENT_TS_MISSING", f"{event_path}:{lineno}"))
                    continue
                try:
                    _parse_iso_utc(str(ts))
                except Exception:
                    errors.append(_err("EVENT_TS_UNPARSABLE", f"{event_path}:{lineno}: {ts}"))

    return sorted(errors)
