"""Smoke tests for on-graph filtering (P1.8)."""
import graph_filter


def _holistic_graph():
    """A minimal Holistic-shaped graph for testing."""
    return {
        "subject": "0xaaa",
        "graph": {
            "nodes": [
                {"id": "eth:0xaaa", "address": "0xaaa", "chain": "eth"},
                {"id": "eth:0xbbb", "address": "0xbbb", "chain": "eth"},
                {"id": "eth:0xccc", "address": "0xccc", "chain": "eth"},
                {"id": "eth:0xddd", "address": "0xddd", "chain": "eth"},
            ],
            "edges": [
                {"source": "eth:0xaaa", "target": "eth:0xbbb", "value": 100, "value_usd": 1000,
                 "timestamp": 1700000000, "direction": "out", "kind": "transfer", "asset": "ETH", "hop": 1},
                {"source": "eth:0xbbb", "target": "eth:0xccc", "value": 0.5, "value_usd": 5,
                 "timestamp": 1700001000, "direction": "out", "kind": "transfer", "asset": "USDT", "hop": 2},
                {"source": "eth:0xccc", "target": "eth:0xddd", "value": 50, "value_usd": 50000,
                 "timestamp": 1700002000, "direction": "out", "kind": "bridge", "asset": "ETH", "hop": 3},
            ],
        },
    }


def test_filter_by_min_value():
    g = _holistic_graph()
    result = graph_filter.filter_graph(g, min_value=10)
    # Only edges with value >= 10 survive: 100 and 50 (not 0.5).
    edges = result["graph"]["edges"]
    assert len(edges) == 2
    assert all(e["value"] >= 10 for e in edges)


def test_filter_by_token():
    g = _holistic_graph()
    result = graph_filter.filter_graph(g, token="ETH")
    edges = result["graph"]["edges"]
    assert len(edges) == 2
    assert all(e["asset"] == "ETH" for e in edges)


def test_filter_by_kind():
    g = _holistic_graph()
    result = graph_filter.filter_graph(g, kinds=["bridge"])
    edges = result["graph"]["edges"]
    assert len(edges) == 1
    assert edges[0]["kind"] == "bridge"


def test_filter_by_time_window():
    g = _holistic_graph()
    result = graph_filter.filter_graph(g, from_time=1700000500, to_time=1700001500)
    edges = result["graph"]["edges"]
    assert len(edges) == 1
    assert edges[0]["timestamp"] == 1700001000


def test_filter_by_max_hops():
    g = _holistic_graph()
    result = graph_filter.filter_graph(g, max_hops=2)
    edges = result["graph"]["edges"]
    assert all(e["hop"] <= 2 for e in edges)
    assert len(edges) == 2  # hops 1 and 2


def test_filter_prunes_disconnected_nodes():
    g = _holistic_graph()
    result = graph_filter.filter_graph(g, kinds=["bridge"])
    # Only the bridge edge survives → only its source+target nodes remain.
    nodes = result["graph"]["nodes"]
    assert len(nodes) == 2
    node_ids = {n["id"] for n in nodes}
    assert "eth:0xccc" in node_ids
    assert "eth:0xddd" in node_ids


def test_filter_keep_isolated_preserves_nodes():
    g = _holistic_graph()
    result = graph_filter.filter_graph(g, kinds=["bridge"], keep_isolated=True)
    nodes = result["graph"]["nodes"]
    assert len(nodes) == 4  # all original nodes kept


def test_filter_by_counterparty():
    g = _holistic_graph()
    result = graph_filter.filter_graph(g, counterparty="0xbbb")
    edges = result["graph"]["edges"]
    # Edges involving 0xbbb: the first two (aaa→bbb, bbb→ccc).
    assert len(edges) == 2


def test_filter_records_applied_criteria():
    g = _holistic_graph()
    result = graph_filter.filter_graph(g, min_value=10, token="ETH")
    fa = result["filter_applied"]
    assert fa["original_edges"] == 3
    assert fa["filtered_edges"] == 2
    # The two ETH edges (aaa→bbb, ccc→ddd) touch 4 distinct nodes.
    assert fa["filtered_nodes"] == 4
    assert fa["criteria"]["min_value"] == 10


def test_filter_works_on_nexus_shape():
    """Nexus graphs have nodes/edges at the top level (no 'graph' wrapper)."""
    nexus = {
        "nodes": [{"id": "0x1"}, {"id": "0x2"}],
        "edges": [{"source": "0x1", "target": "0x2", "value": 5, "token": "WETH", "time": "1700000000"}],
    }
    result = graph_filter.filter_graph(nexus, min_value=10)
    assert result["filter_applied"]["filtered_edges"] == 0
    assert result["filter_applied"]["filtered_nodes"] == 0
