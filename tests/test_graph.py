from core.graph import build_graph


class _S:
    def __init__(self, system_id: str, depends_on: tuple[str, ...] = (), tier: str = "prod", owners: tuple[str, ...] = ()):
        self.system_id = system_id
        self.depends_on = depends_on
        self.tier = tier
        self.owners = owners


def test_build_graph_deterministic_topo_and_maps() -> None:
    # a depends on b; c depends on b
    systems = [
        _S("c", depends_on=("b",), tier="staging"),
        _S("a", depends_on=("b",), tier="prod", owners=("aaron",)),
        _S("b", depends_on=(), tier="dev"),
    ]

    g = build_graph(systems)

    # topo: b must come before a and c
    assert g.topo_order[0] == "b"
    assert set(g.topo_order) == {"a", "b", "c"}

    # depends_on sorted
    assert g.depends_on["a"] == ["b"]
    assert g.depends_on["c"] == ["b"]
    assert g.depends_on["b"] == []

    # dependents sorted deterministically
    assert g.dependents["b"] == ["a", "c"]
    assert g.dependents["a"] == []
    assert g.dependents["c"] == []

    # metadata
    assert g.tiers["a"] == "prod"
    assert g.tiers["b"] == "dev"
    assert g.tiers["c"] == "staging"
    assert g.owners["a"] == ["aaron"]
