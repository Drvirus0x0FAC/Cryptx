"""
On-graph filtering for CrypTX — QLUE's signature investigator feature.

The Nexus and Holistic graph engines already return edges carrying value,
timestamp, token/asset, and direction. This module applies investigator-defined
filters (value range, time window, counterparty, direction, token, hop depth)
to a returned graph, producing a filtered graph with only matching edges (and
the nodes they connect). Non-matching nodes are pruned unless `keep_isolated`
is set.

This is a pure post-processing layer — it never re-fetches data. It works on
any graph dict shaped like {"graph": {"nodes": [...], "edges": [...]}} or
{"nodes": [...], "edges": [...]} (both Nexus and Holistic shapes).
"""
from __future__ import annotations

from typing import Any, Optional


def _edge_value(edge: dict) -> float:
    """Extract a numeric value from an edge, handling both Nexus and Holistic field names."""
    for key in ("value_usd", "value", "amount", "usd_value"):
        v = edge.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _edge_timestamp(edge: dict) -> Optional[int]:
    """Extract a unix timestamp from an edge (Holistic) or parse a date string (Nexus)."""
    ts = edge.get("timestamp")
    if ts is not None:
        try:
            return int(ts)
        except (TypeError, ValueError):
            pass
    # Nexus uses "time" as a string.
    t = edge.get("time")
    if t:
        try:
            return int(t)
        except (TypeError, ValueError):
            pass
    return None


def _edge_token(edge: dict) -> str:
    return str(edge.get("asset") or edge.get("token") or "").upper()


def _edge_direction(edge: dict) -> str:
    return str(edge.get("direction") or "").lower()


def _edge_hop(edge: dict) -> Optional[int]:
    h = edge.get("hop")
    if h is not None:
        try:
            return int(h)
        except (TypeError, ValueError):
            pass
    return None


def _edge_kind(edge: dict) -> str:
    return str(edge.get("kind") or edge.get("type") or "transaction").lower()


def filter_graph(
    graph: dict[str, Any],
    *,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    direction: Optional[str] = None,      # "in" | "out" | "both"
    token: Optional[str] = None,
    kinds: Optional[list[str]] = None,    # transfer | bridge | swap | deposit
    from_time: Optional[int] = None,      # unix timestamp
    to_time: Optional[int] = None,
    max_hops: Optional[int] = None,
    counterparty: Optional[str] = None,   # address substring to match on source/target
    keep_isolated: bool = False,
) -> dict[str, Any]:
    """Apply investigator filters to a graph dict. Returns a NEW filtered graph.

    Works on both shapes:
      * Holistic: {"graph": {"nodes":[...], "edges":[...]}, "summary": {...}}
      * Nexus:    {"nodes":[...], "edges":[...], "summary": {...}}

    The filtered graph keeps the original structure but with pruned edges/nodes.
    A `filter_applied` block records what was filtered for UI display.
    """
    # Normalize: extract the nodes/edges lists wherever they are.
    inner = graph.get("graph", graph)
    nodes: list[dict] = list(inner.get("nodes") or [])
    edges: list[dict] = list(inner.get("edges") or [])

    dir_filter = (direction or "").lower() if direction and direction.lower() != "both" else None
    token_filter = token.upper().strip() if token else None
    cp_filter = (counterparty or "").strip().lower() if counterparty else None
    kinds_filter = {k.lower() for k in kinds} if kinds else None

    kept_edges: list[dict] = []
    for e in edges:
        # Value range.
        val = _edge_value(e)
        if min_value is not None and val < min_value:
            continue
        if max_value is not None and val > max_value:
            continue
        # Direction.
        if dir_filter:
            ed = _edge_direction(e)
            if ed and ed != dir_filter:
                continue
        # Token.
        if token_filter and _edge_token(e) != token_filter:
            continue
        # Kind.
        if kinds_filter and _edge_kind(e) not in kinds_filter:
            continue
        # Time window.
        ts = _edge_timestamp(e)
        if from_time is not None and (ts is None or ts < from_time):
            continue
        if to_time is not None and (ts is None or ts > to_time):
            continue
        # Hop depth.
        if max_hops is not None:
            h = _edge_hop(e)
            if h is not None and h > max_hops:
                continue
        # Counterparty (address substring on source or target).
        if cp_filter:
            src = str(e.get("source") or "").lower()
            tgt = str(e.get("target") or "").lower()
            if cp_filter not in src and cp_filter not in tgt:
                continue
        kept_edges.append(e)

    # Prune nodes not connected by any kept edge (unless keep_isolated).
    connected_ids: set[str] = set()
    for e in kept_edges:
        connected_ids.add(str(e.get("source") or ""))
        connected_ids.add(str(e.get("target") or ""))
    if keep_isolated:
        kept_nodes = nodes
    else:
        kept_nodes = [n for n in nodes if str(n.get("id") or "") in connected_ids]

    # Build the result preserving the original shape.
    filtered_inner = {"nodes": kept_nodes, "edges": kept_edges}
    result: dict[str, Any] = dict(graph)  # shallow copy preserves summary etc.
    if "graph" in graph:
        result["graph"] = {**(graph.get("graph") or {}), "nodes": kept_nodes, "edges": kept_edges}
    else:
        result["nodes"] = kept_nodes
        result["edges"] = kept_edges

    result["filter_applied"] = {
        "original_nodes": len(nodes),
        "original_edges": len(edges),
        "filtered_nodes": len(kept_nodes),
        "filtered_edges": len(kept_edges),
        "criteria": {
            "min_value": min_value,
            "max_value": max_value,
            "direction": direction,
            "token": token,
            "kinds": kinds,
            "from_time": from_time,
            "to_time": to_time,
            "max_hops": max_hops,
            "counterparty": counterparty,
        },
    }
    return result
