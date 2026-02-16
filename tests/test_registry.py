from core.registry import load_registry_systems


def test_registry_defaults_and_ordering() -> None:
    registry = [
        {
            "system_id": "b-sys",
            "contracts_glob": "data/contracts/b-*.json",
            "events_glob": "data/logs/b.jsonl",
            "is_sample": False,
        },
        {
            "system_id": "a-sys",
            "contracts_glob": "data/contracts/a-*.json",
            "events_glob": "data/logs/a.jsonl",
            "is_sample": True,
            "tier": "staging",
            "depends_on": ["b-sys"],
            "owners": ["aaron"],
        },
    ]

    systems = load_registry_systems(registry)

    # deterministic ordering
    assert [s.system_id for s in systems] == ["a-sys", "b-sys"]

    a = systems[0]
    b = systems[1]

    assert a.tier == "staging"
    assert list(a.depends_on) == ["b-sys"]
    assert list(a.owners) == ["aaron"]

    # defaults
    assert b.tier == "prod"
    assert list(b.depends_on) == []
    assert list(b.owners) == []
