from __future__ import annotations

from pathlib import Path

from core.globs import iter_glob, resolve_glob


def test_resolve_glob_absolute_passthrough(tmp_path: Path) -> None:
    reg = tmp_path / "data" / "registry" / "systems.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text('{"systems": []}', encoding="utf-8")

    abs_pattern = str(tmp_path / "data" / "contracts" / "*.json")
    assert resolve_glob(abs_pattern, reg) == abs_pattern


def test_iter_glob_relative_with_external_registry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    root = tmp_path / "ext-root"
    (root / "data" / "registry").mkdir(parents=True, exist_ok=True)
    (root / "data" / "contracts").mkdir(parents=True, exist_ok=True)

    reg = root / "data" / "registry" / "systems.json"
    reg.write_text('{"systems": []}', encoding="utf-8")

    a = root / "data" / "contracts" / "a.json"
    b = root / "data" / "contracts" / "b.json"
    a.write_text("{}", encoding="utf-8")
    b.write_text("{}", encoding="utf-8")

    found = iter_glob("data/contracts/*.json", reg)
    assert found == sorted([a, b])


def test_iter_glob_ordering_deterministic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    root = tmp_path / "ext-order"
    (root / "data" / "registry").mkdir(parents=True, exist_ok=True)
    (root / "data" / "contracts").mkdir(parents=True, exist_ok=True)

    reg = root / "data" / "registry" / "systems.json"
    reg.write_text('{"systems": []}', encoding="utf-8")

    for name in ["z.json", "a.json", "m.json"]:
        (root / "data" / "contracts" / name).write_text("{}", encoding="utf-8")

    found = iter_glob("data/contracts/*.json", reg)
    names = [p.name for p in found]
    assert names == ["a.json", "m.json", "z.json"]
