from __future__ import annotations

import glob
from pathlib import Path


def _as_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def _is_default_registry_layout(reg_path: Path) -> bool:
    parts = reg_path.parts
    return len(parts) >= 3 and parts[-3:] == ("data", "registry", "systems.json")


def resolve_glob(pattern: str, registry_path: str | Path) -> str:
    """
    Resolve a registry glob deterministically.

    Rules:
    - absolute patterns are returned as-is
    - relative patterns are resolved using registry-owned context
      - default data/registry/systems.json layout keeps legacy project-root behavior for data/* patterns
      - otherwise resolve relative to registry file directory
    """
    p = Path(str(pattern))
    if p.is_absolute():
        return str(p)

    reg = _as_path(registry_path)
    reg_dir = reg.parent

    normalized = str(pattern).replace("\\", "/")
    if _is_default_registry_layout(reg) and normalized.startswith("data/"):
        base = reg.parent.parent.parent
    else:
        base = reg_dir

    return str((base / p).expanduser())


def iter_glob(pattern: str, registry_path: str | Path) -> list[Path]:
    resolved = resolve_glob(pattern, registry_path)
    return [Path(p) for p in sorted(glob.glob(resolved, recursive=True))]
