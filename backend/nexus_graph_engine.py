"""
Nexus Graph: in-house address correlation and graph investigation engine.

The goal is not only transaction visibility, but relationship intelligence:
communities, bridge wallets, common-control leads, shortest paths, pivots,
and explainable correlation scores.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from itertools import combinations
from typing import Any, Dict, List, Optional

from forensic_engine import _safe_float, _short, normalize_edges, behavior_fingerprint, detect_motifs

NEXUS_VERSION = "nexus-graph-local-v1"


def _nodes(edges: List[Dict[str, Any]]) -> set[str]:
    out = set()
    for e in edges:
        if e.get("source"):
            out.add(e["source"])
        if e.get("target"):
            out.add(e["target"])
    return out


def _undirected(edges: List[Dict[str, Any]]) -> Dict[str, set]:
    g: Dict[str, set] = defaultdict(set)
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if not s or not t:
            continue
        g[s].add(t)
        g[t].add(s)
    return g


def _directed(edges: List[Dict[str, Any]]) -> Dict[str, list]:
    g: Dict[str, list] = defaultdict(list)
    for e in edges:
        if e.get("source") and e.get("target"):
            g[e["source"]].append(e)
    return g


def _shortest_path(graph: Dict[str, set], start: str, goal: str, max_depth: int = 6) -> List[str]:
    if start == goal:
        return [start]
    q = deque([(start, [start])])
    seen = {start}
    while q:
        node, path = q.popleft()
        if len(path) > max_depth:
            continue
        for nxt in graph.get(node, set()):
            if nxt in seen:
                continue
            npath = path + [nxt]
            if nxt == goal:
                return npath
            seen.add(nxt)
            q.append((nxt, npath))
    return []


def _communities(graph: Dict[str, set]) -> List[Dict[str, Any]]:
    """Connected-component grouping (BFS).

    NOTE: this is connected-component detection, NOT modularity-based community
    detection (Louvain/Leiden). For a connected graph it returns one component.
    The name is kept for backward compatibility but callers should understand the
    distinction. Each component reports size, edge count, and density.
    """
    seen = set()
    communities = []
    for node in sorted(graph):
        if node in seen:
            continue
        q = deque([node])
        seen.add(node)
        members = []
        edge_count = 0
        while q:
            cur = q.popleft()
            members.append(cur)
            edge_count += len(graph.get(cur, set()))
            for nxt in graph.get(cur, set()):
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
        edge_count //= 2
        possible = max(len(members) * (len(members) - 1) / 2, 1)
        communities.append({
            "id": f"N{len(communities) + 1}",
            "size": len(members),
            "edge_count": edge_count,
            "density": round(edge_count / possible, 4),
            "members": members[:100],
            "detection_method": "connected_component",  # not modularity-based
        })
    return sorted(communities, key=lambda c: (c["size"], c["edge_count"]), reverse=True)


def _betweenness_approx(graph: Dict[str, set], nodes: List[str], samples: int = 60) -> Counter:
    score = Counter()
    # Bug #9 fix: the old `nodes[:samples]` took the first N by sort order, which
    # biased the approximation toward whichever nodes sorted first. Use random
    # sampling so the betweenness estimate is unbiased.
    import random
    if len(nodes) > samples:
        # deterministic seed for reproducibility, but still a random sample
        rng = random.Random(42)
        sample_nodes = rng.sample(nodes, samples)
    else:
        sample_nodes = nodes
    for a, b in combinations(sample_nodes, 2):
        path = _shortest_path(graph, a, b, max_depth=8)
        for mid in path[1:-1]:
            score[mid] += 1
    return score


def _address_features(addresses: List[str], edges: List[Dict[str, Any]], chain: str) -> Dict[str, Dict[str, Any]]:
    features = {}
    for addr in addresses:
        local_txs = []
        for e in edges:
            if addr not in (e.get("source"), e.get("target")):
                continue
            local_txs.append({
                "from": e.get("source"),
                "to": e.get("target"),
                "value": e.get("value"),
                "time": e.get("time"),
                "token": e.get("token"),
                "direction": "OUT" if e.get("source") == addr else "IN",
            })
        pseudo_intel = {
            "address": addr,
            "chain": chain,
            "balance": 0,
            "tx_count": len(local_txs),
            "recent_txs": local_txs,
            "token_txs": [],
            "tokens": [],
        }
        features[addr] = behavior_fingerprint(pseudo_intel, edges)
    return features


def _correlation_score(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    score = 0.0
    evidence = []
    gap_a, gap_b = a.get("median_intertx_gap_seconds"), b.get("median_intertx_gap_seconds")
    if gap_a and gap_b and abs(gap_a - gap_b) <= max(120, min(gap_a, gap_b) * 0.2):
        score += 0.18
        evidence.append("similar median transaction timing")
    if abs(a.get("flow_through_ratio", 0) - b.get("flow_through_ratio", 0)) <= 0.12:
        score += 0.18
        evidence.append("similar flow-through behavior")
    if abs(a.get("roundness_score", 0) - b.get("roundness_score", 0)) <= 0.15:
        score += 0.12
        evidence.append("similar amount roundness")
    if abs(a.get("token_entropy", 0) - b.get("token_entropy", 0)) <= 0.5:
        score += 0.1
        evidence.append("similar token diversity")
    if a.get("burstiness_score", 0) >= 0.4 and b.get("burstiness_score", 0) >= 0.4:
        score += 0.14
        evidence.append("both show bursty timing")
    return {"score": round(min(score, 0.95), 3), "evidence": evidence}


def build_nexus_graph(
    intel: Dict[str, Any],
    trace_graph: Optional[Dict[str, Any]] = None,
    labels: Optional[List[Dict[str, Any]]] = None,
    max_nodes: int = 250,
) -> Dict[str, Any]:
    labels = labels or []
    seed = (intel.get("address") or "").lower()
    chain = intel.get("chain", "")
    edges = normalize_edges(intel, trace_graph)
    node_ids = sorted(_nodes(edges), key=lambda n: n != seed)[:max_nodes]
    undir = _undirected(edges)
    dirg = _directed(edges)
    communities = _communities(undir)
    features = _address_features(node_ids, edges, chain)
    between = _betweenness_approx(undir, node_ids)
    degree = Counter()
    volume = Counter()
    inbound = Counter()
    outbound = Counter()
    for e in edges:
        s, t = e.get("source"), e.get("target")
        val = _safe_float(e.get("value"))
        if s:
            degree[s] += 1
            outbound[s] += val
            volume[s] += val
        if t:
            degree[t] += 1
            inbound[t] += val
            volume[t] += val

    label_map = defaultdict(list)
    for label in labels:
        label_map[(label.get("address") or "").lower()].append(label)

    community_by_node = {}
    for c in communities:
        for m in c["members"]:
            community_by_node[m] = c["id"]

    nodes = []
    for n in node_ids:
        f = features.get(n, {})
        motifs = detect_motifs(edges, f, n)
        arkham_owner = None
        if n == seed:
            arkham = intel.get("arkham") or {}
            arkham_name = arkham.get("name") or arkham.get("entity_name")
            if arkham.get("found") and arkham_name:
                arkham_owner = {"name": arkham_name}
        risk = 0
        if n == seed:
            risk += 20
        if f.get("flow_through_ratio", 0) >= 0.75:
            risk += 25
        if f.get("retention_ratio", 1) <= 0.1:
            risk += 15
        if between[n] > 0:
            risk += min(20, between[n])
        if label_map.get(n):
            risk += max((int(l.get("risk_weight") or 0) for l in label_map[n]), default=0)
        risk = min(risk, 100)
        node = {
            "id": n,
            "address": n,
            "short": _short(n),
            "arkham_owner": arkham_owner,
            "community": community_by_node.get(n, ""),
            "degree": degree[n],
            "inbound_volume": round(inbound[n], 8),
            "outbound_volume": round(outbound[n], 8),
            "total_volume": round(volume[n], 8),
            "bridge_score": between[n],
            "risk_score": risk,
            "role_hint": _role_hint(f),
            "labels": [l.get("label") for l in label_map.get(n, [])],
            "motif_count": len(motifs),
            "features": f,
        }
        if arkham_owner and arkham_owner["name"] not in node["labels"]:
            node["labels"] = [arkham_owner["name"], *node["labels"]]
        nodes.append(node)

    node_set = {n["id"] for n in nodes}
    nexus_edges = []
    for e in edges:
        if e.get("source") not in node_set or e.get("target") not in node_set:
            continue
        nexus_edges.append({
            "source": e.get("source"),
            "target": e.get("target"),
            "value": e.get("value", 0),
            "token": e.get("token", ""),
            "hash": e.get("hash", ""),
            "time": e.get("time", ""),
            "type": "transaction",
        })

    correlations = []
    for a, b in combinations(node_ids[:80], 2):
        corr = _correlation_score(features.get(a, {}), features.get(b, {}))
        if corr["score"] >= 0.28:
            path = _shortest_path(undir, a, b, max_depth=5)
            correlations.append({
                "source": a,
                "target": b,
                "score": corr["score"],
                "evidence": corr["evidence"],
                "path": path,
                "type": "behavioral_correlation",
            })
    correlations.sort(key=lambda c: c["score"], reverse=True)

    bridge_wallets = sorted(
        [n for n in nodes if n["bridge_score"] > 0],
        key=lambda n: (n["bridge_score"], n["degree"]),
        reverse=True,
    )[:20]
    pivot_queue = sorted(
        nodes,
        key=lambda n: (n["risk_score"], n["bridge_score"], n["degree"], n["total_volume"]),
        reverse=True,
    )[:30]

    paths_from_seed = []
    for n in pivot_queue[:12]:
        if n["id"] == seed:
            continue
        path = _shortest_path(undir, seed, n["id"], max_depth=6)
        if path:
            paths_from_seed.append({"target": n["id"], "target_short": n["short"], "path": path, "hops": len(path) - 1})

    return {
        "version": NEXUS_VERSION,
        "seed": seed,
        "chain": chain,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(nexus_edges),
            "correlation_count": len(correlations),
            "community_count": len(communities),
            "bridge_wallet_count": len(bridge_wallets),
            "highest_risk": max((n["risk_score"] for n in nodes), default=0),
        },
        "nodes": nodes,
        "edges": nexus_edges,
        "correlations": correlations[:100],
        "communities": communities,
        "bridge_wallets": bridge_wallets,
        "pivot_queue": pivot_queue,
        "paths_from_seed": paths_from_seed,
        "explainability": [
            "Correlation scores are behavior-based leads, not proof of common ownership.",
            "Bridge wallets are high-betweenness nodes in the observed local graph.",
            "Pivot queue prioritizes risk, graph position, degree, and observed volume.",
        ],
    }


def _role_hint(features: Dict[str, Any]) -> str:
    if features.get("flow_through_ratio", 0) >= 0.75 and features.get("retention_ratio", 1) <= 0.1:
        return "pass-through"
    if features.get("in_degree", 0) >= 5 and features.get("out_degree", 0) <= 2:
        return "collector"
    if features.get("out_degree", 0) >= 5 and features.get("in_degree", 0) <= 2:
        return "distributor"
    if features.get("counterparty_entropy", 0) >= 3:
        return "service-like"
    return "unknown"
