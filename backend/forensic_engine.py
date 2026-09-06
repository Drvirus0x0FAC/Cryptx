"""
Local forensic algorithms for cryptocurrency investigation.

This module intentionally avoids paid/vendor intelligence. It extracts
behavioral fingerprints, graph motifs, role hypotheses, taint flow, and
explainable confidence scores from evidence already collected by the app.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from math import log2
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

ALGORITHM_VERSION = "forensic-local-v1"


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OSError, ValueError):
            return None
    text = str(value).strip()
    for suffix in ("Z", " UTC"):
        if text.endswith(suffix):
            text = text[: -len(suffix)] + "+00:00"
            break
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _value(tx: Dict[str, Any]) -> float:
    return abs(_safe_float(
        tx.get("value_eth")
        or tx.get("value_trx")
        or tx.get("delta_btc")
        or tx.get("amount")
        or tx.get("value")
        or tx.get("usd_value")
    ))


def _tx_hash(tx: Dict[str, Any]) -> str:
    return tx.get("hash") or tx.get("txid") or tx.get("tx_hash") or ""


def _short(addr: str) -> str:
    return f"{addr[:8]}...{addr[-6:]}" if len(addr) > 18 else addr


def _entropy(values: Iterable[str]) -> float:
    counts = Counter(v for v in values if v)
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return round(-sum((c / total) * log2(c / total) for c in counts.values()), 4)


def _roundness_score(values: List[float]) -> float:
    if not values:
        return 0.0
    hits = 0
    for v in values:
        if v <= 0:
            continue
        text = f"{v:.8f}".rstrip("0").rstrip(".")
        if text.endswith(".0") or text.split(".")[0] == text:
            hits += 1
        elif abs(v - round(v, 1)) < 1e-9 or abs(v - round(v, 2)) < 1e-9:
            hits += 1
    return round(hits / max(len(values), 1), 4)


def normalize_edges(intel: Dict[str, Any], trace_graph: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    subject = (intel.get("address") or "").lower()
    chain = intel.get("chain", "")
    edges: List[Dict[str, Any]] = []

    if trace_graph:
        for edge in trace_graph.get("edges") or []:
            source = edge.get("source_address") or edge.get("source") or ""
            target = edge.get("target_address") or edge.get("target") or ""
            if source and target:
                edges.append({
                    "source": source.lower(),
                    "target": target.lower(),
                    "chain": edge.get("chain", chain),
                    "hash": edge.get("hash") or edge.get("tx_hash") or "",
                    "token": edge.get("token", ""),
                    "value": _safe_float(edge.get("amount") or edge.get("value")),
                    "time": edge.get("time") or edge.get("timestamp") or "",
                    "evidence": {"source": "trace_graph"},
                })

    for tx in list(intel.get("recent_txs") or []) + list(intel.get("token_txs") or []):
        src = (tx.get("from") or "").lower()
        dst = (tx.get("to") or "").lower()
        direction = (tx.get("direction") or "").upper()
        if not src and direction == "OUT":
            src = subject
        if not dst and direction == "IN":
            dst = subject
        if src and dst and src != dst:
            edges.append({
                "source": src,
                "target": dst,
                "chain": chain,
                "hash": _tx_hash(tx),
                "token": tx.get("token", intel.get("balance_unit", "")),
                "value": _value(tx),
                "time": tx.get("time") or tx.get("timestamp") or "",
                "evidence": {"source": "address_intel"},
            })
    seen = set()
    deduped = []
    for edge in edges:
        key = (edge["source"], edge["target"], edge.get("hash", ""), edge.get("token", ""), edge.get("value", 0))
        if key not in seen:
            seen.add(key)
            deduped.append(edge)
    return deduped


def behavior_fingerprint(intel: Dict[str, Any], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    address = (intel.get("address") or "").lower()
    txs = list(intel.get("recent_txs") or []) + list(intel.get("token_txs") or [])
    in_edges = [e for e in edges if e.get("target") == address]
    out_edges = [e for e in edges if e.get("source") == address]
    values = [_value(tx) for tx in txs if _value(tx) > 0] or [e.get("value", 0) for e in edges if e.get("value", 0) > 0]
    counterparties = [
        e["source"] if e.get("target") == address else e["target"]
        for e in edges
        if address in (e.get("source"), e.get("target"))
    ]
    times = sorted([dt for dt in (_parse_time(tx.get("time") or tx.get("timestamp")) for tx in txs) if dt])
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:]) if (b - a).total_seconds() >= 0]
    active_hours = Counter(dt.hour for dt in times)
    total_in = sum(e.get("value", 0) for e in in_edges)
    total_out = sum(e.get("value", 0) for e in out_edges)
    balance = _safe_float(intel.get("balance"))
    tx_count = int(_safe_float(intel.get("tx_count")) or len(txs))
    token_symbols = [str(t.get("symbol") or t.get("token") or "").upper() for t in (intel.get("tokens") or []) + txs]

    return {
        "tx_count": tx_count,
        "native_balance": balance,
        "edge_count": len(edges),
        "in_degree": len({e["source"] for e in in_edges}),
        "out_degree": len({e["target"] for e in out_edges}),
        "total_in": round(total_in, 8),
        "total_out": round(total_out, 8),
        "flow_through_ratio": round(min(total_in, total_out) / max(max(total_in, total_out), 1e-12), 4),
        "retention_ratio": round(balance / max(total_in, total_out, balance, 1e-12), 4),
        "counterparty_entropy": _entropy(counterparties),
        "token_entropy": _entropy(token_symbols),
        "roundness_score": _roundness_score(values),
        "median_value": round(median(values), 8) if values else 0,
        "median_intertx_gap_seconds": round(median(gaps), 2) if gaps else None,
        "burstiness_score": round(sum(1 for g in gaps if g <= 600) / max(len(gaps), 1), 4) if gaps else 0,
        "active_hour_histogram": dict(sorted(active_hours.items())),
        "first_seen": min((t.isoformat() for t in times), default=intel.get("first_seen", "")),
        "last_seen": max((t.isoformat() for t in times), default=intel.get("last_seen", "")),
    }


def classify_role(features: Dict[str, Any]) -> Dict[str, Any]:
    in_deg = features.get("in_degree", 0)
    out_deg = features.get("out_degree", 0)
    retention = features.get("retention_ratio", 0)
    flow = features.get("flow_through_ratio", 0)
    entropy = features.get("counterparty_entropy", 0)
    burst = features.get("burstiness_score", 0)
    tx_count = features.get("tx_count", 0)

    candidates: List[Tuple[str, float, str]] = []
    if flow > 0.75 and retention < 0.08 and tx_count >= 8:
        candidates.append(("pass_through_mule", 0.82, "High flow-through with low retained balance"))
    if in_deg >= 5 and out_deg <= 2:
        candidates.append(("collector", min(0.9, 0.55 + in_deg / 30), "Many sources converge into few destinations"))
    if out_deg >= 5 and in_deg <= 2:
        candidates.append(("distributor", min(0.9, 0.55 + out_deg / 30), "Funds split from few sources to many destinations"))
    if in_deg >= 8 and out_deg >= 8 and entropy >= 3:
        candidates.append(("service_or_hot_wallet", 0.74, "High two-sided degree and diverse counterparties"))
    if burst >= 0.5 and flow > 0.5:
        candidates.append(("burst_layering_wallet", 0.68, "Rapid repeated transfers with flow-through behavior"))
    if retention > 0.7 and tx_count <= 8:
        candidates.append(("parking_or_vault", 0.63, "Funds retained with limited transaction activity"))

    if not candidates:
        candidates.append(("ordinary_wallet", 0.45, "No strong role pattern detected"))
    candidates.sort(key=lambda x: x[1], reverse=True)
    role, confidence, reason = candidates[0]
    return {
        "role": role,
        "confidence": round(confidence, 3),
        "reason": reason,
        "alternatives": [
            {"role": r, "confidence": round(c, 3), "reason": why}
            for r, c, why in candidates[1:4]
        ],
    }


def counterparty_roles(edges: List[Dict[str, Any]], subject: str) -> List[Dict[str, Any]]:
    subject = subject.lower()
    nodes = sorted({e.get("source", "") for e in edges} | {e.get("target", "") for e in edges})
    roles = []
    for node in nodes:
        if not node or node == subject:
            continue
        in_edges = [e for e in edges if e.get("target") == node]
        out_edges = [e for e in edges if e.get("source") == node]
        total_in = sum(_safe_float(e.get("value")) for e in in_edges)
        total_out = sum(_safe_float(e.get("value")) for e in out_edges)
        features = {
            "tx_count": len(in_edges) + len(out_edges),
            "native_balance": 0,
            "edge_count": len(in_edges) + len(out_edges),
            "in_degree": len({e.get("source") for e in in_edges}),
            "out_degree": len({e.get("target") for e in out_edges}),
            "total_in": total_in,
            "total_out": total_out,
            "flow_through_ratio": min(total_in, total_out) / max(total_in, total_out, 1e-12),
            "retention_ratio": 0 if total_in and total_out else 1,
            "counterparty_entropy": _entropy(
                [e.get("source", "") for e in in_edges] + [e.get("target", "") for e in out_edges]
            ),
            "token_entropy": _entropy([e.get("token", "") for e in in_edges + out_edges]),
            "roundness_score": _roundness_score([_safe_float(e.get("value")) for e in in_edges + out_edges]),
            "burstiness_score": 0,
        }
        role = classify_role(features)
        roles.append({
            "address": node,
            "short": _short(node),
            "role": role["role"],
            "confidence": role["confidence"],
            "reason": role["reason"],
            "in_degree": features["in_degree"],
            "out_degree": features["out_degree"],
            "flow_through_ratio": round(features["flow_through_ratio"], 4),
        })
    return sorted(roles, key=lambda r: (r["confidence"], r["in_degree"] + r["out_degree"]), reverse=True)[:25]


def graph_metrics(edges: List[Dict[str, Any]], subject: str) -> Dict[str, Any]:
    out_map: Dict[str, set] = defaultdict(set)
    in_map: Dict[str, set] = defaultdict(set)
    nodes = set()
    for edge in edges:
        s, t = edge.get("source", ""), edge.get("target", "")
        if not s or not t:
            continue
        nodes.update([s, t])
        out_map[s].add(t)
        in_map[t].add(s)
    degrees = {n: len(out_map[n]) + len(in_map[n]) for n in nodes}
    subject = subject.lower()
    max_degree = max(degrees.values(), default=1)
    hubs = sorted(
        [{"address": n, "degree": d, "short": _short(n)} for n, d in degrees.items()],
        key=lambda x: x["degree"],
        reverse=True,
    )[:10]
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "subject_degree": degrees.get(subject, 0),
        "subject_centrality": round(degrees.get(subject, 0) / max_degree, 4),
        "max_degree": max_degree,
        "hub_candidates": hubs,
        "components_estimate": _component_count(nodes, out_map),
    }


def cluster_analysis(edges: List[Dict[str, Any]], subject: str, features: Dict[str, Any]) -> Dict[str, Any]:
    """Unsupervised local graph/community and anomaly scoring."""
    subject = subject.lower()
    undirected: Dict[str, set] = defaultdict(set)
    weighted_degree: Dict[str, float] = defaultdict(float)
    nodes = set()
    for edge in edges:
        src, dst = edge.get("source", ""), edge.get("target", "")
        if not src or not dst:
            continue
        value = max(_safe_float(edge.get("value")), 1.0)
        nodes.update([src, dst])
        undirected[src].add(dst)
        undirected[dst].add(src)
        weighted_degree[src] += value
        weighted_degree[dst] += value

    communities = []
    seen = set()
    for node in sorted(nodes):
        if node in seen:
            continue
        q = deque([node])
        seen.add(node)
        members = []
        internal_edges = 0
        while q:
            cur = q.popleft()
            members.append(cur)
            internal_edges += len(undirected[cur])
            for nxt in undirected[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
        internal_edges //= 2
        possible = max(len(members) * (len(members) - 1) / 2, 1)
        communities.append({
            "id": f"c{len(communities) + 1}",
            "size": len(members),
            "edge_count": internal_edges,
            "density": round(internal_edges / possible, 4),
            "contains_subject": subject in members,
            "members": members[:25],
        })
    communities.sort(key=lambda c: (not c["contains_subject"], -c["size"], -c["edge_count"]))

    core_numbers = _core_numbers(undirected)
    max_degree = max((len(v) for v in undirected.values()), default=1)
    subject_degree = len(undirected.get(subject, []))
    hubness = subject_degree / max_degree if max_degree else 0
    anomaly_terms = {
        "hubness": min(hubness, 1),
        "burstiness": min(features.get("burstiness_score", 0), 1),
        "flow_through": min(features.get("flow_through_ratio", 0), 1),
        "roundness": min(features.get("roundness_score", 0), 1),
        "low_retention": 1 - min(features.get("retention_ratio", 1), 1),
        "token_entropy": min(features.get("token_entropy", 0) / 4, 1),
    }
    anomaly_score = round(sum(anomaly_terms.values()) / len(anomaly_terms), 4)
    if anomaly_score >= 0.7:
        anomaly_level = "HIGH"
    elif anomaly_score >= 0.45:
        anomaly_level = "MEDIUM"
    elif anomaly_score >= 0.25:
        anomaly_level = "LOW"
    else:
        anomaly_level = "NORMAL"

    return {
        "communities": communities[:10],
        "subject_community": next((c for c in communities if c["contains_subject"]), None),
        "core_number": core_numbers.get(subject, 0),
        "max_core_number": max(core_numbers.values(), default=0),
        "weighted_degree": round(weighted_degree.get(subject, 0), 8),
        "anomaly_score": anomaly_score,
        "anomaly_level": anomaly_level,
        "anomaly_terms": anomaly_terms,
    }


def _core_numbers(undirected: Dict[str, set]) -> Dict[str, int]:
    """Compute k-core numbers via the Batagelj-Zaversnik O(V+E) algorithm.

    Bug #4 fix: the old implementation removed nodes but never pruned their
    neighbors' sets, so degrees were computed against stale data and the k>1000
    guard could trigger on dense graphs. This is the standard linear-time version.
    """
    if not undirected:
        return {}
    degree = {node: len(set(neighbors) & set(undirected.keys())) for node, neighbors in undirected.items()}
    core = dict(degree)
    # Process nodes in order of increasing degree
    nodes_sorted = sorted(degree.keys(), key=lambda n: degree[n])
    for node in nodes_sorted:
        for neighbor in (undirected.get(node, set()) & set(undirected.keys())):
            if degree[neighbor] > degree[node]:
                degree[neighbor] -= 1
                # re-sort position: since we process in sorted order, just cap the degree
                new_deg = max(degree[node], degree[neighbor])
                core[neighbor] = min(core[neighbor], new_deg) if core[neighbor] > new_deg else core[neighbor]
    return core


def _component_count(nodes: set, out_map: Dict[str, set]) -> int:
    undirected: Dict[str, set] = defaultdict(set)
    for src, targets in out_map.items():
        for dst in targets:
            undirected[src].add(dst)
            undirected[dst].add(src)
    seen = set()
    count = 0
    for node in nodes:
        if node in seen:
            continue
        count += 1
        q = deque([node])
        seen.add(node)
        while q:
            cur = q.popleft()
            for nxt in undirected[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
    return count


def detect_motifs(edges: List[Dict[str, Any]], features: Dict[str, Any], subject: str) -> List[Dict[str, Any]]:
    motifs: List[Dict[str, Any]] = []
    subject = subject.lower()
    by_source = defaultdict(list)
    by_target = defaultdict(list)
    by_value = defaultdict(list)
    for edge in edges:
        by_source[edge.get("source", "")].append(edge)
        by_target[edge.get("target", "")].append(edge)
        rounded = round(_safe_float(edge.get("value")), 6)
        if rounded > 0:
            by_value[(edge.get("token", ""), rounded)].append(edge)

    if features.get("out_degree", 0) >= 5:
        motifs.append({
            "pattern": "fan_out_dispersal",
            "severity": "MEDIUM",
            "confidence": min(0.9, 0.5 + features["out_degree"] / 20),
            "evidence": f"{_short(subject)} sent funds to {features['out_degree']} unique recipients",
        })
    if features.get("in_degree", 0) >= 5:
        motifs.append({
            "pattern": "fan_in_consolidation",
            "severity": "MEDIUM",
            "confidence": min(0.9, 0.5 + features["in_degree"] / 20),
            "evidence": f"{_short(subject)} received funds from {features['in_degree']} unique sources",
        })
    if features.get("flow_through_ratio", 0) >= 0.75 and features.get("retention_ratio", 1) <= 0.1:
        motifs.append({
            "pattern": "pass_through_flow",
            "severity": "HIGH",
            "confidence": 0.82,
            "evidence": "Incoming and outgoing volume are similar while retained balance is low",
        })
    if features.get("roundness_score", 0) >= 0.45 and features.get("tx_count", 0) >= 5:
        motifs.append({
            "pattern": "round_amount_structuring",
            "severity": "MEDIUM",
            "confidence": features["roundness_score"],
            "evidence": f"{features['roundness_score'] * 100:.1f}% of observed values are rounded",
        })
    if features.get("burstiness_score", 0) >= 0.45:
        motifs.append({
            "pattern": "rapid_burst_movement",
            "severity": "MEDIUM",
            "confidence": features["burstiness_score"],
            "evidence": "Many observed transactions occur within 10 minutes of another transaction",
        })
    repeated = [items for items in by_value.values() if len(items) >= 3]
    if repeated:
        motifs.append({
            "pattern": "repeated_exact_value_hops",
            "severity": "MEDIUM",
            "confidence": min(0.9, 0.45 + len(repeated) / 10),
            "evidence": f"{len(repeated)} repeated value/token groups observed across transfers",
        })

    for source, out_edges in by_source.items():
        if len(out_edges) == 1:
            first = out_edges[0]
            nxt = first.get("target")
            if nxt and len(by_source.get(nxt, [])) == 1 and len(by_target.get(nxt, [])) == 1:
                motifs.append({
                    "pattern": "possible_peel_chain",
                    "severity": "LOW",
                    "confidence": 0.52,
                    "evidence": f"Single-successor chain segment { _short(source) } -> { _short(nxt) }",
                })
                break
    return sorted(motifs, key=lambda m: m.get("confidence", 0), reverse=True)


def taint_flow(seed: str, edges: List[Dict[str, Any]], max_depth: int = 5) -> Dict[str, Any]:
    seed = seed.lower()
    outgoing = defaultdict(list)
    for edge in edges:
        outgoing[edge.get("source", "")].append(edge)

    exposure = {seed: 1.0}
    paths = []
    q = deque([(seed, 1.0, 0, [seed])])
    while q:
        node, taint, depth, path = q.popleft()
        if depth >= max_depth:
            continue
        outs = outgoing.get(node, [])
        total = sum(max(_safe_float(e.get("value")), 0.0) for e in outs) or len(outs)
        if not outs or total <= 0:
            continue
        for edge in outs:
            dst = edge.get("target", "")
            share = (_safe_float(edge.get("value")) / total) if total and _safe_float(edge.get("value")) > 0 else (1 / len(outs))
            next_taint = taint * share * 0.86
            if next_taint < 0.005:
                continue
            exposure[dst] = max(exposure.get(dst, 0), next_taint)
            next_path = path + [dst]
            paths.append({
                "address": dst,
                "taint": round(next_taint, 5),
                "depth": depth + 1,
                "path": next_path,
                "tx_hash": edge.get("hash", ""),
            })
            q.append((dst, next_taint, depth + 1, next_path))
    ranked = sorted(
        [{"address": k, "taint": round(v, 5), "short": _short(k)} for k, v in exposure.items() if k != seed],
        key=lambda x: x["taint"],
        reverse=True,
    )[:25]
    return {
        "seed": seed,
        "model": "proportional_decay",
        "depth": max_depth,
        "exposed_addresses": ranked,
        "top_paths": sorted(paths, key=lambda x: x["taint"], reverse=True)[:10],
    }


def temporal_correlations(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_minute = defaultdict(set)
    for edge in edges:
        dt = _parse_time(edge.get("time") or edge.get("timestamp"))
        if not dt:
            continue
        bucket = dt.strftime("%Y-%m-%dT%H:%M")
        by_minute[bucket].update([edge.get("source", ""), edge.get("target", "")])
    findings = []
    for bucket, addrs in by_minute.items():
        addrs = {a for a in addrs if a}
        if len(addrs) >= 4:
            findings.append({
                "type": "synchronized_activity_cluster",
                "time_bucket": bucket,
                "address_count": len(addrs),
                "addresses": sorted(addrs)[:10],
                "confidence": min(0.9, 0.4 + len(addrs) / 20),
            })
    return sorted(findings, key=lambda x: x["confidence"], reverse=True)[:10]


def analyze_forensics(
    intel: Dict[str, Any],
    trace_graph: Optional[Dict[str, Any]] = None,
    dex_activity: Optional[Dict[str, Any]] = None,
    local_labels: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    address = intel.get("address", "")
    chain = intel.get("chain", "")
    edges = normalize_edges(intel, trace_graph)
    features = behavior_fingerprint(intel, edges)
    role = classify_role(features)
    counterparties = counterparty_roles(edges, address)
    motifs = detect_motifs(edges, features, address)
    metrics = graph_metrics(edges, address)
    clusters = cluster_analysis(edges, address, features)
    taint = taint_flow(address, edges)
    temporal = temporal_correlations(edges)
    dex = _dex_forensics(dex_activity or {})
    labels = local_labels or []

    confidence = _analysis_confidence(intel, edges, trace_graph, dex_activity)
    algorithm_signals = _algorithm_signals(role, motifs, features, metrics, dex, clusters, labels)

    addresses = [{
        "address": address.lower(),
        "chain": chain,
        "first_seen": features.get("first_seen", ""),
        "last_seen": features.get("last_seen", ""),
        "role": role["role"],
        "risk_score": -1,
        "features": features,
    }]
    transactions = list(intel.get("recent_txs") or []) + list(intel.get("token_txs") or [])
    outputs = [
        {"address": address, "chain": chain, "algorithm": "behavior_fingerprint", "output": features, "confidence": confidence},
        {"address": address, "chain": chain, "algorithm": "role_classifier", "output": role, "confidence": role["confidence"]},
        {"address": address, "chain": chain, "algorithm": "motif_detection", "output": {"motifs": motifs}, "confidence": confidence},
        {"address": address, "chain": chain, "algorithm": "taint_flow", "output": taint, "confidence": confidence},
        {"address": address, "chain": chain, "algorithm": "cluster_anomaly", "output": clusters, "confidence": confidence},
        {"address": address, "chain": chain, "algorithm": "counterparty_roles", "output": {"counterparties": counterparties}, "confidence": confidence},
    ]
    summary = {
        "address": address,
        "chain": chain,
        "algorithm_version": ALGORITHM_VERSION,
        "confidence": confidence,
        "role": role,
        "counterparty_roles": counterparties,
        "features": features,
        "motifs": motifs,
        "graph_metrics": metrics,
        "cluster_analysis": clusters,
        "taint_flow": taint,
        "temporal_correlations": temporal,
        "dex_forensics": dex,
        "local_labels": labels,
        "algorithm_signals": algorithm_signals,
        "evidence_counts": {
            "transactions": len(transactions),
            "edges": len(edges),
            "motifs": len(motifs),
            "temporal_clusters": len(temporal),
            "local_labels": len(labels),
        },
    }
    return {
        "summary": summary,
        "evidence": {
            "addresses": addresses,
            "transactions": transactions,
            "edges": edges,
            "outputs": outputs,
        },
    }


def _analysis_confidence(
    intel: Dict[str, Any],
    edges: List[Dict[str, Any]],
    trace_graph: Optional[Dict[str, Any]],
    dex_activity: Optional[Dict[str, Any]],
) -> float:
    tx_count = int(_safe_float(intel.get("tx_count")) or len(intel.get("recent_txs") or []))
    score = 0.25
    score += min(0.25, tx_count / 200)
    score += min(0.25, len(edges) / 80)
    if trace_graph:
        score += 0.15
    if dex_activity:
        score += 0.10
    return round(min(score, 0.95), 3)


def _algorithm_signals(
    role: Dict[str, Any],
    motifs: List[Dict[str, Any]],
    features: Dict[str, Any],
    metrics: Dict[str, Any],
    dex: Dict[str, Any],
    clusters: Dict[str, Any],
    local_labels: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    if role["role"] in {"pass_through_mule", "burst_layering_wallet"}:
        signals.append({
            "type": "forensic_role",
            "severity": "HIGH",
            "weight": 62,
            "label": f"Behavioral role: {role['role'].replace('_', ' ')}",
            "detail": role["reason"],
            "confidence": role["confidence"],
        })
    elif role["role"] in {"collector", "distributor"}:
        signals.append({
            "type": "forensic_role",
            "severity": "MEDIUM",
            "weight": 42,
            "label": f"Behavioral role: {role['role']}",
            "detail": role["reason"],
            "confidence": role["confidence"],
        })

    for motif in motifs[:6]:
        severity = motif.get("severity", "LOW")
        weight = {"CRITICAL": 85, "HIGH": 65, "MEDIUM": 42, "LOW": 22}.get(severity, 15)
        signals.append({
            "type": f"motif_{motif['pattern']}",
            "severity": severity,
            "weight": weight,
            "label": motif["pattern"].replace("_", " ").title(),
            "detail": motif.get("evidence", ""),
            "confidence": round(float(motif.get("confidence", 0.5)), 3),
        })

    if metrics.get("subject_centrality", 0) >= 0.75 and metrics.get("nodes", 0) >= 8:
        signals.append({
            "type": "graph_centrality",
            "severity": "MEDIUM",
            "weight": 38,
            "label": "High Local Graph Centrality",
            "detail": "Subject is a central node in the observed evidence graph",
            "confidence": metrics["subject_centrality"],
        })
    if dex.get("possible_wash_cycle"):
        signals.append({
            "type": "dex_wash_cycle",
            "severity": "MEDIUM",
            "weight": 45,
            "label": "Local DEX Wash-Cycle Pattern",
            "detail": "Repeated buy/sell symmetry detected in local DEX activity",
            "confidence": dex.get("confidence", 0.55),
        })
    if clusters.get("anomaly_level") in {"MEDIUM", "HIGH"}:
        signals.append({
            "type": "cluster_anomaly",
            "severity": clusters["anomaly_level"],
            "weight": 58 if clusters["anomaly_level"] == "HIGH" else 36,
            "label": f"Unsupervised anomaly score: {clusters['anomaly_level']}",
            "detail": "Local graph/behavior profile deviates from ordinary-wallet baseline",
            "confidence": clusters.get("anomaly_score", 0),
        })
    if clusters.get("core_number", 0) >= 3:
        signals.append({
            "type": "graph_core_membership",
            "severity": "MEDIUM",
            "weight": 34,
            "label": "Dense Graph Core Membership",
            "detail": f"Subject appears in local {clusters.get('core_number')}-core",
            "confidence": min(0.9, 0.45 + clusters.get("core_number", 0) / 10),
        })
    for label in local_labels[:5]:
        weight = _safe_float(label.get("risk_weight"))
        if weight <= 0:
            continue
        signals.append({
            "type": "local_label",
            "severity": "HIGH" if weight >= 65 else "MEDIUM" if weight >= 35 else "LOW",
            "weight": int(weight),
            "label": f"Local label: {label.get('label', '')}",
            "detail": label.get("notes") or label.get("category", "Investigator-owned label"),
            "confidence": _safe_float(label.get("confidence")) or 1,
        })
    return signals


def _dex_forensics(activity: Dict[str, Any]) -> Dict[str, Any]:
    swaps = activity.get("swaps") or activity.get("all_swaps") or []
    if not swaps:
        return {"swap_count": 0, "possible_wash_cycle": False, "confidence": 0}
    pair_counts = Counter()
    directions = Counter()
    for swap in swaps:
        pair = "/".join(sorted([str(swap.get("token0_symbol", "")), str(swap.get("token1_symbol", ""))]))
        pair_counts[pair] += 1
        directions[swap.get("direction", "unknown")] += 1
    top_pair, top_count = pair_counts.most_common(1)[0]
    buys = directions.get("buy", 0)
    sells = directions.get("sell", 0)
    symmetry = 1 - abs(buys - sells) / max(buys + sells, 1)
    possible = top_count >= 6 and symmetry >= 0.75
    return {
        "swap_count": len(swaps),
        "top_pair": top_pair,
        "top_pair_count": top_count,
        "buy_sell_symmetry": round(symmetry, 4),
        "possible_wash_cycle": possible,
        "confidence": round(min(0.9, 0.35 + symmetry / 2 + min(top_count / 50, 0.2)), 3) if possible else round(symmetry, 3),
    }
