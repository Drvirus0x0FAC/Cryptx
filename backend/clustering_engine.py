"""
Entity resolution and wallet clustering engine.
Groups wallets into "common-control" clusters using multiple heuristics.

IMPORTANT: Output uses "common-control lead" language — NEVER claims ownership.
These are investigative leads requiring further verification.

Clustering methods:
  1. Gas-funder clustering (EVM: same address pays gas for multiple wallets)
  2. Common counterparty clustering (shared transaction counterparties)
  3. Temporal coordination (transactions within tight time windows)
  4. Same-value pattern matching (repeated identical transaction amounts)
  5. Common deposit address (multiple wallets deposit to same exchange address)
  6. Address reuse (same address reused across multiple contexts)
"""
from __future__ import annotations
import uuid
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


_CLUSTER_METHODS = [
    "gas_funder",
    "common_counterparty",
    "temporal_coordination",
    "same_value_pattern",
    "common_deposit_address",
    "address_reuse",
]


def _parse_ts(ts) -> float:
    # Accept epoch ints/floats directly (real chain APIs return numeric timestamps).
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


# ── Union-Find for merging clusters ──────────────────────────────────────────

class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def clusters(self, members: list[str]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for m in members:
            groups[self.find(m)].append(m)
        return {k: v for k, v in groups.items() if len(v) > 1}


# ── Clustering heuristics ─────────────────────────────────────────────────────

def _cluster_gas_funder(
    nodes: list[dict],
    edges: list[dict],
    gas_threshold: float = 0.002,  # ETH
) -> list[dict]:
    """
    One address pays gas (small ETH out) to multiple others.
    Those recipients are likely controlled by the same entity.
    """
    signals: list[dict] = []
    # Build: funder → set of funded addresses
    funder_to_funded: dict[str, set[str]] = defaultdict(set)

    for e in edges:
        token = (e.get("token") or "native").lower()
        val   = float(e.get("value") or 0)
        src   = e.get("source") or ""
        tgt   = e.get("target") or ""
        # Gas funding: small native token transfers (ETH < threshold)
        if token in ("native", "eth", "") and 0 < val <= gas_threshold and src and tgt:
            funder_to_funded[src].add(tgt)

    for funder, funded in funder_to_funded.items():
        if len(funded) >= 2:
            signals.append({
                "method":        "gas_funder",
                "pivot":         funder,
                "members":       sorted(funded),
                "confidence":    min(95, 50 + len(funded) * 10),
                "evidence":      f"Address {funder[:10]} funded gas for {len(funded)} wallets",
                "method_label":  "Gas-funder cluster",
            })
    return signals


def _cluster_common_counterparty(
    nodes: list[dict],
    edges: list[dict],
    min_shared: int = 2,
) -> list[dict]:
    """
    Wallets sharing 2+ common counterparties likely belong to same entity.
    """
    addr_counterparties: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        src = e.get("source") or ""
        tgt = e.get("target") or ""
        if src and tgt:
            addr_counterparties[src].add(tgt)
            addr_counterparties[tgt].add(src)

    addrs = list(addr_counterparties.keys())
    uf = UnionFind()
    signals: list[dict] = []

    for i in range(len(addrs)):
        for j in range(i + 1, len(addrs)):
            shared = addr_counterparties[addrs[i]] & addr_counterparties[addrs[j]]
            if len(shared) >= min_shared:
                uf.union(addrs[i], addrs[j])
                signals.append({
                    "method":       "common_counterparty",
                    "pivot":        None,
                    "pair":         (addrs[i], addrs[j]),
                    "shared":       sorted(shared),
                    "shared_count": len(shared),
                    "confidence":   min(90, 35 + len(shared) * 15),
                    "evidence":     f"Share {len(shared)} counterparties: {', '.join(list(shared)[:3])}",
                    "method_label": "Shared counterparty cluster",
                })

    # Merge into cluster groups
    groups = uf.clusters(addrs)
    cluster_signals: list[dict] = []
    for root, members in groups.items():
        # Gather all evidence for this cluster
        cluster_evidence = [s for s in signals
                            if s.get("pair") and set(s["pair"]) <= set(members)]
        cluster_signals.append({
            "method":       "common_counterparty",
            "pivot":        None,
            "members":      members,
            "confidence":   max((s["confidence"] for s in cluster_evidence), default=50),
            "evidence":     f"{len(cluster_evidence)} shared counterparty link(s) among {len(members)} wallets",
            "method_label": "Shared counterparty cluster",
        })
    return cluster_signals


def _cluster_temporal_coordination(
    nodes: list[dict],
    edges: list[dict],
    window_sec: float = 120.0,
    min_addr: int = 2,
) -> list[dict]:
    """
    Multiple wallets transacting within a tight time window (coordinated movement).
    """
    # Build list of (timestamp, address) for all source addresses
    timed_addrs: list[tuple[float, str]] = []
    for e in edges:
        ts  = _parse_ts(e.get("time") or e.get("timestamp") or "")
        src = e.get("source") or ""
        if ts > 0 and src:
            timed_addrs.append((ts, src))

    if not timed_addrs:
        return []

    timed_addrs.sort()
    signals: list[dict] = []
    i = 0
    while i < len(timed_addrs):
        window_addrs: set[str] = {timed_addrs[i][1]}
        j = i + 1
        while j < len(timed_addrs) and timed_addrs[j][0] - timed_addrs[i][0] <= window_sec:
            window_addrs.add(timed_addrs[j][1])
            j += 1
        if len(window_addrs) >= min_addr:
            signals.append({
                "method":       "temporal_coordination",
                "pivot":        None,
                "members":      sorted(window_addrs),
                "window_sec":   window_sec,
                "window_start": timed_addrs[i][0],
                "confidence":   min(85, 40 + len(window_addrs) * 8),
                "evidence":     (
                    f"{len(window_addrs)} wallets transacted within "
                    f"{window_sec:.0f}s window"
                ),
                "method_label": "Temporal coordination cluster",
            })
        # Bug #6 fix: advance by one (not i=j) so windows OVERLAP. The old `i=j`
        # jumped past the entire window, splitting coordinated activity that
        # straddled a window boundary into separate (weaker) clusters.
        i += 1

    # Deduplicate by member sets
    seen: set[frozenset[str]] = set()
    unique: list[dict] = []
    for s in signals:
        key = frozenset(s["members"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def _cluster_same_value(
    nodes: list[dict],
    edges: list[dict],
    tolerance: float = 0.001,
    min_occurrences: int = 3,
) -> list[dict]:
    """
    Multiple transactions with identical (or near-identical) values from different
    source addresses suggest a coordinated peel chain or single controller.
    """
    # Group edges by rounded value
    value_groups: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        val = float(e.get("value") or 0)
        if val <= 0:
            continue
        # Round to tolerance bucket
        bucket = round(val / tolerance) * tolerance
        value_groups[str(round(bucket, 8))].append(e)

    signals: list[dict] = []
    for bucket_key, txs in value_groups.items():
        src_addrs = {e.get("source") or "" for e in txs if e.get("source")}
        if len(src_addrs) >= min_occurrences and len(src_addrs) >= 2:
            signals.append({
                "method":       "same_value_pattern",
                "pivot":        None,
                "members":      sorted(src_addrs),
                "value":        float(bucket_key),
                "tx_count":     len(txs),
                "confidence":   min(80, 30 + len(src_addrs) * 10),
                "evidence":     (
                    f"{len(src_addrs)} wallets sent identical value "
                    f"~{float(bucket_key):.6f}"
                ),
                "method_label": "Same-value pattern cluster",
            })
    return signals


def _cluster_common_deposit(
    nodes: list[dict],
    edges: list[dict],
    node_map: dict[str, dict],
    min_depositors: int = 2,
) -> list[dict]:
    """
    Multiple wallets depositing to the same exchange address.
    Classic clustering heuristic from Bitcoin UTXO analysis, extended to EVM.
    """
    _EXCHANGE_TAGS = {"exchange", "cex", "binance", "coinbase", "kraken",
                      "okx", "kucoin", "bybit", "gate", "huobi"}

    def _is_exchange(nid: str) -> bool:
        lbl = f"{(node_map.get(nid, {}).get('label') or '')} {(node_map.get(nid, {}).get('role') or '')}".lower()
        return any(t in lbl for t in _EXCHANGE_TAGS)

    deposit_target_to_sources: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        tgt = e.get("target") or ""
        src = e.get("source") or ""
        if tgt and src and _is_exchange(tgt):
            deposit_target_to_sources[tgt].add(src)

    signals: list[dict] = []
    for dest, sources in deposit_target_to_sources.items():
        if len(sources) >= min_depositors:
            dest_label = node_map.get(dest, {}).get("label") or dest[:10]
            signals.append({
                "method":       "common_deposit_address",
                "pivot":        dest,
                "members":      sorted(sources),
                "dest_label":   dest_label,
                "confidence":   min(92, 55 + len(sources) * 10),
                "evidence":     (
                    f"{len(sources)} wallets all deposited to "
                    f"{dest_label} ({dest[:10]})"
                ),
                "method_label": "Common deposit address cluster",
            })
    return signals


def _cluster_address_reuse(
    nodes: list[dict],
    edges: list[dict],
) -> list[dict]:
    """
    Address appearing as both source and destination in different contexts
    with different counterparties — suggests address reuse / single controller.
    BTC-style: all inputs to a TX share a common controller (UTXO model).
    """
    # In a single transaction (by tx_hash), multiple sources → common input owner
    tx_sources: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        tx  = e.get("tx_hash") or e.get("hash") or ""
        src = e.get("source") or ""
        if tx and src:
            tx_sources[tx].add(src)

    signals: list[dict] = []
    for tx, sources in tx_sources.items():
        if len(sources) >= 2:
            signals.append({
                "method":       "address_reuse",
                "pivot":        tx,
                "members":      sorted(sources),
                "confidence":   min(88, 60 + len(sources) * 8),
                "evidence":     (
                    f"Common-input heuristic: {len(sources)} addresses "
                    f"co-spent in tx {tx[:12]}"
                ),
                "method_label": "Common-input (BTC) cluster",
            })
    return signals


# ── Cluster assembly ──────────────────────────────────────────────────────────

def _merge_signals(signals: list[dict], all_addr: list[str]) -> list[dict]:
    """
    Use Union-Find to merge overlapping signals into final clusters.
    """
    uf = UnionFind()
    for sig in signals:
        members = sig.get("members") or []
        for m in members[1:]:
            uf.union(members[0], m)

    groups = uf.clusters(all_addr)
    clusters: list[dict] = []
    for root, members in groups.items():
        member_signals = [s for s in signals
                          if any(m in (s.get("members") or []) for m in members)]
        methods_used = list({s["method"] for s in member_signals})
        max_conf     = max((s.get("confidence", 0) for s in member_signals), default=50)

        # Aggregate evidence
        evidence_lines = list({s["evidence"] for s in member_signals})

        cluster_id = str(uuid.uuid4())[:8]
        clusters.append({
            "cluster_id":      cluster_id,
            "lead_address":    root,  # the UnionFind root = "lead"
            "members":         sorted(set(members)),
            "member_count":    len(set(members)),
            "methods":         methods_used,
            "confidence":      round(max_conf, 1),
            "evidence":        evidence_lines,
            # CRITICAL: use "common-control lead" language
            "finding":         (
                f"Common-control lead: {len(set(members))} wallets share "
                f"{len(methods_used)} clustering signal(s) — "
                f"possible single-controller relationship (investigative lead only)"
            ),
            "disclaimer":      (
                "This is a heuristic common-control lead, not an ownership claim. "
                "Requires further verification before use in legal proceedings."
            ),
        })

    return sorted(clusters, key=lambda c: (-c["member_count"], -c["confidence"]))


# ── Public entry point ────────────────────────────────────────────────────────

def analyze_clusters(
    nodes: list[dict],
    edges: list[dict],
    methods: list[str] | None = None,
    gas_threshold: float = 0.002,
    time_window: float = 120.0,
    min_shared_counterparties: int = 2,
) -> dict[str, Any]:
    """
    Main entry point.
    nodes: list of {id, label, role, risk_score, ...}
    edges: list of {source, target, value, token, time, tx_hash, ...}
    """
    active_methods = set(methods or _CLUSTER_METHODS)
    node_map = {n["id"]: n for n in nodes}
    all_addrs = [n["id"] for n in nodes]

    all_signals: list[dict] = []

    if "gas_funder" in active_methods:
        all_signals += _cluster_gas_funder(nodes, edges, gas_threshold)

    if "common_counterparty" in active_methods:
        all_signals += _cluster_common_counterparty(nodes, edges, min_shared_counterparties)

    if "temporal_coordination" in active_methods:
        all_signals += _cluster_temporal_coordination(nodes, edges, time_window)

    if "same_value_pattern" in active_methods:
        all_signals += _cluster_same_value(nodes, edges)

    if "common_deposit_address" in active_methods:
        all_signals += _cluster_common_deposit(nodes, edges, node_map)

    if "address_reuse" in active_methods:
        all_signals += _cluster_address_reuse(nodes, edges)

    clusters = _merge_signals(all_signals, all_addrs)
    total_clustered = len({m for c in clusters for m in c["members"]})

    return {
        "clusters":          clusters,
        "cluster_count":     len(clusters),
        "total_clustered":   total_clustered,
        "methods_applied":   sorted(active_methods),
        "raw_signal_count":  len(all_signals),
        "disclaimer":        (
            "All clusters are heuristic common-control leads requiring "
            "independent verification. They indicate possible shared control, "
            "not confirmed ownership."
        ),
        "summary":           (
            f"Found {len(clusters)} potential cluster(s) spanning "
            f"{total_clustered} address(es) via "
            f"{len(active_methods)} detection method(s)"
        ),
    }
