from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SystemSpec:
    system_id: str
    contracts_glob: str
    events_glob: str
    is_sample: bool = False
    notes: str = ""


def registry_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else Path("data/registry/systems.json")


def _coerce_system_rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        systems = payload.get("systems", [])
        if isinstance(systems, list):
            return [row for row in systems if isinstance(row, dict)]
    raise ValueError("Registry must be a list or an object with a 'systems' list")


def load_registry(path: str | Path | None = None) -> list[SystemSpec]:
    reg_path = registry_path(path)
    if not reg_path.exists():
        return []
    payload = json.loads(reg_path.read_text(encoding="utf-8"))
    rows = _coerce_system_rows(payload)

    specs: list[SystemSpec] = []
    for row in rows:
        system_id = str(row.get("system_id", "")).strip()
        contracts_glob = str(row.get("contracts_glob", "")).strip()
        events_glob = str(row.get("events_glob", "")).strip()
        is_sample = bool(row.get("is_sample", False))
        notes = str(row.get("notes", ""))
        if not system_id or not contracts_glob or not events_glob:
            continue
        specs.append(
            SystemSpec(
                system_id=system_id,
                contracts_glob=contracts_glob,
                events_glob=events_glob,
                is_sample=is_sample,
                notes=notes,
            )
        )
    return specs


def save_registry(specs: list[SystemSpec], path: str | Path | None = None) -> Path:
    reg_path = registry_path(path)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    systems = [
        {
            "system_id": spec.system_id,
            "contracts_glob": spec.contracts_glob,
            "events_glob": spec.events_glob,
            "is_sample": spec.is_sample,
            "notes": spec.notes,
        }
        for spec in specs
    ]
    payload = {"systems": systems}
    reg_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return reg_path


def upsert_system(system_id: str, contracts_glob: str, events_glob: str, path: str | Path | None = None) -> bool:
    specs = load_registry(path)
    changed = False
    out: list[SystemSpec] = []

    found = False
    for spec in specs:
        if spec.system_id != system_id:
            out.append(spec)
            continue
        found = True
        updated = SystemSpec(
            system_id=system_id,
            contracts_glob=contracts_glob,
            events_glob=events_glob,
            is_sample=spec.is_sample,
            notes=spec.notes,
        )
        out.append(updated)
        if updated != spec:
            changed = True

    if not found:
        out.append(SystemSpec(system_id=system_id, contracts_glob=contracts_glob, events_glob=events_glob))
        changed = True

    if changed:
        out = sorted(out, key=lambda s: s.system_id)
        save_registry(out, path)
    return changed
