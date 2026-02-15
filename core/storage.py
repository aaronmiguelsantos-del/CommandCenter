from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.models import Contract, Event


DATA_DIR = Path("data")
CONTRACTS_DIR = DATA_DIR / "contracts"
LOGS_DIR = DATA_DIR / "logs"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
PRIMITIVES_DIR = DATA_DIR / "primitives"
SCHEMAS_DIR = PRIMITIVES_DIR / "schemas"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def slugify(value: str) -> str:
    stripped = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    collapsed = "-".join(part for part in stripped.split("-") if part)
    return collapsed or "item"


def list_contracts() -> list[dict[str, Any]]:
    ensure_dir(CONTRACTS_DIR)
    out: list[dict[str, Any]] = []
    for path in sorted(CONTRACTS_DIR.glob("*.json")):
        out.append(read_json(path))
    return out


def next_contract_id(system_id: str) -> str:
    existing = [c for c in list_contracts() if c.get("system_id") == system_id]
    return f"{slugify(system_id)}-{len(existing) + 1:04d}"


def create_contract(system_id: str, name: str) -> Path:
    contract = Contract(
        contract_id=next_contract_id(system_id),
        system_id=system_id,
        name=name,
    )
    filename = f"{contract.contract_id}.json"
    target = CONTRACTS_DIR / filename
    write_json(target, contract.model_dump())
    return target


def events_log_path(system_id: str | None = None) -> Path:
    if system_id is None:
        return LOGS_DIR / "events.jsonl"
    return LOGS_DIR / f"{slugify(system_id)}-events.jsonl"


def list_event_rows() -> list[dict[str, Any]]:
    ensure_dir(LOGS_DIR)
    rows: list[dict[str, Any]] = []
    for path in sorted(LOGS_DIR.glob("*-events.jsonl")):
        rows.extend(read_jsonl(path))
    # Backward compatibility for older single-file layout.
    legacy = events_log_path()
    if legacy.exists():
        rows.extend(read_jsonl(legacy))
    return rows


def append_event(system_id: str, event_type: str) -> dict[str, Any]:
    target = events_log_path(system_id)
    existing = read_jsonl(target)
    event = Event(
        event_id=f"{slugify(system_id)}-evt-{len(existing) + 1:06d}",
        system_id=system_id,
        event_type=event_type,
    )
    payload = event.model_dump()
    append_jsonl(target, payload)
    return payload
