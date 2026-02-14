from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Type, TypeVar

import yaml
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONTRACTS = DATA / "contracts"
LOGS = DATA / "logs"
SNAPSHOTS = DATA / "snapshots"
PRIMITIVES = DATA / "primitives"


def ensure_dirs() -> None:
    for p in [CONTRACTS, LOGS, SNAPSHOTS, PRIMITIVES, PRIMITIVES / "schemas"]:
        p.mkdir(parents=True, exist_ok=True)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, default=str) + "\n")


def save_contract(contract: BaseModel) -> None:
    path = CONTRACTS / f"{contract.system_id}.json"
    path.write_text(contract.model_dump_json(indent=2), encoding="utf-8")


def load_contracts(model: Type[T]) -> List[T]:
    ensure_dirs()
    out: List[T] = []
    for p in CONTRACTS.glob("*.json"):
        out.append(model.model_validate_json(p.read_text(encoding="utf-8")))
    return sorted(out, key=lambda x: x.name.lower())


def append_log(system_id: str, record: BaseModel) -> None:
    path = LOGS / f"{system_id}.jsonl"
    append_jsonl(path, record.model_dump())


def load_logs(system_id: str) -> List[Dict[str, Any]]:
    ensure_dirs()
    return _read_jsonl(LOGS / f"{system_id}.jsonl")


def load_invariants() -> Dict[str, Any]:
    ensure_dirs()
    path = PRIMITIVES / "invariants.yaml"
    if not path.exists():
        # minimal default
        path.write_text(
            "invariants:\n"
            "  - id: INV-001\n"
            "    name: Deterministic routing\n"
            "    statement: Routing must be deterministic and explainable.\n"
            "    test: Given same inputs, routing output is identical.\n"
            "    severity: high\n",
            encoding="utf-8",
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))
