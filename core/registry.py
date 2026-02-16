from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_TIERS = {"prod", "staging", "dev", "sample"}


@dataclass(frozen=True)
class RegistrySystem:
    system_id: str
    contracts_glob: str
    events_glob: str
    is_sample: bool = False
    notes: str = ""
    tier: str = "prod"
    depends_on: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()


# Backward-compatible name used throughout the existing codebase.
SystemSpec = RegistrySystem


def registry_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else Path("data/registry/systems.json")


def _coerce_system_rows(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        systems = payload.get("systems", [])
        if isinstance(systems, list):
            return [row for row in systems if isinstance(row, dict)]
    raise ValueError("Registry must be a list or an object with a 'systems' list")


def _as_list_str(x: Any) -> list[str]:
    if x is None:
        return []
    if not isinstance(x, list):
        return []
    out: list[str] = []
    for v in x:
        if isinstance(v, str) and v:
            out.append(v)
    return out


def load_registry_systems(registry_obj: Any) -> list[RegistrySystem]:
    """
    Accepts registry JSON object:
      - list[system]
      - {"systems": list[system]}
    Applies defaults for optional fields.
    Does NOT enforce dependency validity yet.
    """
    rows = _coerce_system_rows(registry_obj)

    out: list[RegistrySystem] = []
    for row in rows:
        system_id = str(row.get("system_id", "")).strip()
        contracts_glob = str(row.get("contracts_glob", "")).strip()
        events_glob = str(row.get("events_glob", "")).strip()
        is_sample = bool(row.get("is_sample", False))
        notes = str(row.get("notes", "") or "")

        tier = str(row.get("tier", "prod")).strip() or "prod"
        if tier not in VALID_TIERS:
            tier = "prod"

        depends_on = tuple(_as_list_str(row.get("depends_on")))
        owners = tuple(_as_list_str(row.get("owners")))

        if not system_id or not contracts_glob or not events_glob:
            continue

        out.append(
            RegistrySystem(
                system_id=system_id,
                contracts_glob=contracts_glob,
                events_glob=events_glob,
                is_sample=is_sample,
                notes=notes,
                tier=tier,
                depends_on=depends_on,
                owners=owners,
            )
        )

    out.sort(key=lambda s: s.system_id)
    return out


def load_registry(path: str | Path | None = None) -> list[SystemSpec]:
    reg_path = registry_path(path)
    if not reg_path.exists():
        return []
    payload = json.loads(reg_path.read_text(encoding="utf-8"))
    return load_registry_systems(payload)


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
            "tier": spec.tier,
            "depends_on": list(spec.depends_on),
            "owners": list(spec.owners),
        }
        for spec in sorted(specs, key=lambda s: s.system_id)
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
            tier=spec.tier,
            depends_on=spec.depends_on,
            owners=spec.owners,
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
