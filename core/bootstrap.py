from __future__ import annotations

from pathlib import Path

from core.storage import CONTRACTS_DIR, DATA_DIR, LOGS_DIR, PRIMITIVES_DIR, SCHEMAS_DIR, SNAPSHOTS_DIR


INVARIANTS_CONTENT = """version: 1
invariants:
  - id: contracts_have_system_id
    description: Every contract file has a non-empty system_id.
  - id: events_have_type
    description: Every event has a non-empty event_type.
"""


MINIMAL_SCHEMAS: dict[str, str] = {
    "contract.schema.json": """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Contract",
  "type": "object",
  "required": ["contract_id", "system_id", "name"],
  "properties": {
    "contract_id": {"type": "string"},
    "system_id": {"type": "string"},
    "name": {"type": "string"}
  },
  "additionalProperties": true
}
""",
    "event.schema.json": """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Event",
  "type": "object",
  "required": ["event_id", "system_id", "event_type", "ts"],
  "properties": {
    "event_id": {"type": "string"},
    "system_id": {"type": "string"},
    "event_type": {"type": "string"},
    "ts": {"type": "string"}
  },
  "additionalProperties": true
}
""",
    "health.schema.json": """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Health",
  "type": "object",
  "required": ["ts", "score_total"],
  "properties": {
    "ts": {"type": "string"},
    "score_total": {"type": "number"}
  },
  "additionalProperties": true
}
""",
}


def _ensure_file(path: Path, content: str = "") -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def bootstrap_repo() -> list[Path]:
    created: list[Path] = []
    for folder in [DATA_DIR, PRIMITIVES_DIR, SCHEMAS_DIR, CONTRACTS_DIR, LOGS_DIR, SNAPSHOTS_DIR]:
        folder.mkdir(parents=True, exist_ok=True)
    if _ensure_file(PRIMITIVES_DIR / "invariants.yaml", INVARIANTS_CONTENT):
        created.append(PRIMITIVES_DIR / "invariants.yaml")
    for name, content in MINIMAL_SCHEMAS.items():
        path = SCHEMAS_DIR / name
        if _ensure_file(path, content):
            created.append(path)
    for path in [CONTRACTS_DIR / ".gitkeep", LOGS_DIR / ".gitkeep", SNAPSHOTS_DIR / ".gitkeep"]:
        if _ensure_file(path):
            created.append(path)
    return created
