from core.graph import build_graph
from core.impact import compute_impact


class _S:
    def __init__(self, system_id: str, depends_on=(), tier="prod", owners=()):
        self.system_id = system_id
        self.depends_on = tuple(depends_on)
        self.tier = tier
        self.owners = tuple(owners)


def test_compute_impact_transitive_and_ranking() -> None:
    # Graph:
    # b -> a  (a depends on b)  => b impacts a
    # b -> c  (c depends on b)  => b impacts c
    # a -> d  (d depends on a)  => b impacts d at distance 2
    systems = [
        _S("b", depends_on=(), tier="dev"),
        _S("a", depends_on=("b",), tier="prod"),
        _S("c", depends_on=("b",), tier="staging"),
        _S("d", depends_on=("a",), tier="prod"),
    ]
    g = build_graph(systems)

    src, impacted = compute_impact(g, sources=["b"])

    assert src == ["b"]
    # impacted should include a,c,d with correct distances
    dist = {x.system_id: x.distance for x in impacted}
    assert dist["a"] == 1
    assert dist["c"] == 1
    assert dist["d"] == 2

    # ranking: tier severity first (prod before staging before dev/sample),
    # then distance, then system_id
    order = [x.system_id for x in impacted]
    # prod tier: a (1 hop), d (2 hops) first
    assert order[0] == "a"
    assert order[1] == "d"
    # then staging: c
    assert order[2] == "c"
