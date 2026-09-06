"""
Multi-route pathfinding engine.
Finds every significant path from a wallet/TX to exchanges, mixers, bridges,
scam wallets, or known entities via six path strategies:
  shortest, highest_value, highest_risk, most_recent,
  mixer_routed, bridge_routed
plus a path confidence score.
"""
from __future__ import annotations
import math
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

# ── Entity role tags (lowercase) ──────────────────────────────────────────────
_EXCHANGE_TAGS   = {"exchange", "cex", "binance", "coinbase", "kraken", "okx",
                    "kucoin", "bybit", "gate", "huobi", "bitfinex", "gemini",
                    "crypto.com", "bitstamp"}
_MIXER_TAGS      = {"mixer", "tornado", "tumbler", "chipmixer", "wasabi",
                    "coinjoin", "blender", "sinbad", "yomix", "anonymix"}
_BRIDGE_TAGS     = {"bridge", "wormhole", "stargate", "hop", "across",
                    "celer", "multichain", "synapse", "portal", "renbridge"}
_SCAM_TAGS       = {"scam", "phishing", "hack", "exploit", "rug", "fraud",
                    "drainer", "pig butcher", "romance", "theft"}
_HIGH_RISK_ROLES = _MIXER_TAGS | _SCAM_TAGS


def _parse_ts(ts) -> float:
    """Parse ISO-ish timestamp to unix epoch; returns 0 on failure.

    Accepts epoch ints/floats directly (real chain APIs return numeric timestamps).
    """
    if isinstance(ts, (int, float)):
        return float(ts)
    if not ts:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            pass
    try:
        return float(ts)
    except (ValueError, TypeError):
        return 0.0


def _role_of(node: dict) -> str:
    label = (node.get("label") or "").lower()
    role  = (node.get("role")  or "").lower()
    return f"{label} {role}".strip()


def _is_target(node: dict, node_type_filter: set[str] | None = None) -> bool:
    r = _role_of(node)
    all_target = _EXCHANGE_TAGS | _MIXER_TAGS | _BRIDGE_TAGS | _SCAM_TAGS
    if node_type_filter:
        all_target = node_type_filter
    return any(t in r for t in all_target)


def _risk_weight(node: dict) -> float:
    """Higher = riskier; used to prefer high-risk paths."""
    r = _role_of(node)
    if any(t in r for t in _MIXER_TAGS | _SCAM_TAGS):
        return 100.0
    if any(t in r for t in _BRIDGE_TAGS):
        return 30.0
    rs = float(node.get("risk_score") or 0)
    return max(rs, 0.0)


# ── Graph representation ──────────────────────────────────────────────────────

class PathGraph:
    """
    Directed weighted graph built from nexus nodes + edges.
    Supports six BFS/Dijkstra strategies.
    """

    def __init__(self, nodes: list[dict], edges: list[dict]) -> None:
        self.nodes: dict[str, dict] = {n["id"]: n for n in nodes}
        # adjacency: id → list of (neighbor_id, edge_dict)
        self.adj: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        self.radj: dict[str, list[tuple[str, dict]]] = defaultdict(list)  # reverse
        for e in edges:
            src = e.get("source") or e.get("src") or ""
            tgt = e.get("target") or e.get("tgt") or ""
            if src and tgt:
                self.adj[src].append((tgt, e))
                self.radj[tgt].append((src, e))

    # ── Internal BFS helpers ──────────────────────────────────────────────────

    def _bfs_all_paths(
        self,
        source: str,
        max_hops: int = 8,
        node_type_filter: set[str] | None = None,
        edge_key: str = "value",
        direction: str = "out",   # "out" | "in" | "both"
    ) -> list[list[str]]:
        """BFS collecting all simple paths to any target node."""
        targets_found: list[list[str]] = []
        queue: deque[list[str]] = deque([[source]])
        visited_per_path: dict[tuple[str, ...], set[str]] = {}

        while queue:
            path = queue.popleft()
            key = tuple(path[:-1])
            seen = visited_per_path.get(key, set()) | {path[-1]}
            visited_per_path[tuple(path)] = seen
            cur = path[-1]

            if len(path) > 1 and _is_target(self.nodes.get(cur, {}), node_type_filter):
                targets_found.append(path)
                continue  # don't extend past targets

            if len(path) - 1 >= max_hops:
                continue

            neighbors = []
            if direction in ("out", "both"):
                neighbors += self.adj.get(cur, [])
            if direction in ("in", "both"):
                neighbors += self.radj.get(cur, [])

            for nid, _ in neighbors:
                if nid not in seen:
                    new_path = path + [nid]
                    new_seen = seen | {nid}
                    visited_per_path[tuple(new_path)] = new_seen
                    queue.append(new_path)

        return targets_found

    def _path_value(self, path: list[str]) -> float:
        total = 0.0
        for i in range(len(path) - 1):
            for nid, e in self.adj.get(path[i], []):
                if nid == path[i + 1]:
                    total += float(e.get("value") or 0)
                    break
        return total

    def _path_risk(self, path: list[str]) -> float:
        """Sum of risk weights along the path nodes."""
        return sum(_risk_weight(self.nodes.get(n, {})) for n in path[1:])

    def _path_latest_ts(self, path: list[str]) -> float:
        latest = 0.0
        for i in range(len(path) - 1):
            for nid, e in self.adj.get(path[i], []):
                if nid == path[i + 1]:
                    t = _parse_ts(e.get("time") or e.get("timestamp") or "")
                    latest = max(latest, t)
                    break
        return latest

    def _path_has_role(self, path: list[str], role_tags: set[str]) -> bool:
        for node_id in path[1:-1]:  # intermediate nodes
            r = _role_of(self.nodes.get(node_id, {}))
            if any(t in r for t in role_tags):
                return True
        return False

    # ── Confidence score ──────────────────────────────────────────────────────

    def _confidence(self, path: list[str], strategy: str) -> float:
        """
        0-100 confidence that this path represents an actual flow of funds.
        Factors: hops (fewer = higher), value > 0, timestamps exist, no gaps.
        """
        n = len(path) - 1  # number of hops
        if n == 0:
            return 0.0
        hop_score = max(0.0, 100.0 - n * 10)
        val = self._path_value(path)
        val_score = min(30.0, math.log10(val + 1) * 10) if val > 0 else 0.0
        # Count edges along the path that actually carry a timestamp (bug #1 fix:
        # the old `or True` made ts_count meaningless and ts_score was hardcoded to 10).
        ts_count = 0
        for i in range(len(path) - 1):
            for nid, e in self.adj.get(path[i], []):
                if nid == path[i + 1]:
                    if e.get("time") or e.get("timestamp"):
                        ts_count += 1
                    break
        ts_score = (ts_count / n) * 15.0 if n else 0.0
        # risk boost: if destination is high-risk, we're more confident it matters
        risk_bonus = 10.0 if _risk_weight(self.nodes.get(path[-1], {})) > 50 else 0.0
        return min(100.0, hop_score * 0.5 + val_score + ts_score + risk_bonus)

    # ── Public pathfinding entry points ───────────────────────────────────────

    def _paths_cached(self, source: str, max_hops: int) -> list[list[str]]:
        """Memoized all-paths enumeration (P6 fix): compute once, reuse across strategies.

        The old code called _bfs_all_paths 6× (once per strategy) with no caching,
        re-running the exponential enumeration each time. This computes it once.
        """
        cache_key = (source, max_hops)
        if not hasattr(self, "_paths_cache"):
            self._paths_cache: dict[tuple[str, int], list[list[str]]] = {}
        if cache_key not in self._paths_cache:
            self._paths_cache[cache_key] = self._bfs_all_paths(source, max_hops)
        return self._paths_cache[cache_key]

    def find_shortest(self, source: str, max_hops: int = 8) -> dict | None:
        paths = self._paths_cached(source, max_hops)
        if not paths:
            return None
        best = min(paths, key=len)
        return self._pack(best, "shortest")

    def find_highest_value(self, source: str, max_hops: int = 8) -> dict | None:
        paths = self._paths_cached(source, max_hops)
        if not paths:
            return None
        best = max(paths, key=lambda p: self._path_value(p))
        return self._pack(best, "highest_value")

    def find_highest_risk(self, source: str, max_hops: int = 8) -> dict | None:
        paths = self._paths_cached(source, max_hops)
        if not paths:
            return None
        best = max(paths, key=lambda p: self._path_risk(p))
        return self._pack(best, "highest_risk")

    def find_most_recent(self, source: str, max_hops: int = 8) -> dict | None:
        paths = self._paths_cached(source, max_hops)
        if not paths:
            return None
        best = max(paths, key=lambda p: self._path_latest_ts(p))
        return self._pack(best, "most_recent")

    def find_mixer_routed(self, source: str, max_hops: int = 10) -> dict | None:
        paths = self._paths_cached(source, max_hops)
        mixer_paths = [p for p in paths if self._path_has_role(p, _MIXER_TAGS)]
        if not mixer_paths:
            return None
        best = max(mixer_paths, key=lambda p: self._path_risk(p))
        return self._pack(best, "mixer_routed")

    def find_bridge_routed(self, source: str, max_hops: int = 10) -> dict | None:
        paths = self._paths_cached(source, max_hops)
        bridge_paths = [p for p in paths if self._path_has_role(p, _BRIDGE_TAGS)]
        if not bridge_paths:
            return None
        best = max(bridge_paths, key=lambda p: self._path_value(p))
        return self._pack(best, "bridge_routed")

    def _pack(self, path: list[str], strategy: str) -> dict:
        """Serialize a path into a result dict."""
        hops = []
        for i in range(len(path) - 1):
            src = path[i]
            tgt = path[i + 1]
            edge_data: dict = {}
            for nid, e in self.adj.get(src, []):
                if nid == tgt:
                    edge_data = e
                    break
            hops.append({
                "from":    src,
                "to":      tgt,
                "tx_hash": edge_data.get("tx_hash") or edge_data.get("hash") or "",
                "value":   float(edge_data.get("value") or 0),
                "token":   edge_data.get("token") or "native",
                "time":    edge_data.get("time") or edge_data.get("timestamp") or "",
            })
        dest_node = self.nodes.get(path[-1], {})
        return {
            "strategy":       strategy,
            "path":           path,
            "hops":           hops,
            "hop_count":      len(path) - 1,
            "total_value":    self._path_value(path),
            "max_risk":       self._path_risk(path),
            "latest_ts":      self._path_latest_ts(path),
            "destination": {
                "id":    path[-1],
                "label": dest_node.get("label") or dest_node.get("id", ""),
                "role":  dest_node.get("role") or "",
                "risk":  int(dest_node.get("risk_score") or 0),
            },
            "confidence":     round(self._confidence(path, strategy), 1),
        }


# ── Public API ────────────────────────────────────────────────────────────────

def find_all_paths(
    nodes: list[dict],
    edges: list[dict],
    source_id: str,
    max_hops: int = 8,
    strategies: list[str] | None = None,
) -> dict[str, Any]:
    """
    Entry point. Returns all six path types (or subset if strategies given).
    """
    pg = PathGraph(nodes, edges)
    all_strats = strategies or [
        "shortest", "highest_value", "highest_risk",
        "most_recent", "mixer_routed", "bridge_routed",
    ]
    results: dict[str, Any] = {}
    for s in all_strats:
        fn = {
            "shortest":       pg.find_shortest,
            "highest_value":  pg.find_highest_value,
            "highest_risk":   pg.find_highest_risk,
            "most_recent":    pg.find_most_recent,
            "mixer_routed":   pg.find_mixer_routed,
            "bridge_routed":  pg.find_bridge_routed,
        }.get(s)
        if fn:
            results[s] = fn(source_id, max_hops)

    # Deduplicate identical paths across strategies
    seen_paths: set[tuple[str, ...]] = set()
    unique_paths: list[dict] = []
    for s, r in results.items():
        if r and tuple(r["path"]) not in seen_paths:
            seen_paths.add(tuple(r["path"]))
            unique_paths.append(r)

    return {
        "source":       source_id,
        "by_strategy":  results,
        "unique_paths": unique_paths,
        "path_count":   len(unique_paths),
        "target_count": len({p["path"][-1] for p in unique_paths if p}),
        "max_confidence": max((p["confidence"] for p in unique_paths if p), default=0.0),
    }
