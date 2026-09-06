"""
In-house threat intelligence algorithms for cryptocurrency investigations.

The engine produces evidence-grounded attribution hypotheses, pivot leads,
network expansion, laundering typology scoring, and a local graph dump.
It avoids claiming a real-world owner unless the evidence supports it.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any, Dict, List, Optional

from forensic_engine import (
    _safe_float,
    _short,
    analyze_forensics,
    normalize_edges,
)

THREAT_INTEL_VERSION = "threat-intel-local-v1"


def _confidence_label(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    if score >= 0.3:
        return "low"
    return "weak"


def _edge_nodes(edges: List[Dict[str, Any]]) -> set[str]:
    nodes = set()
    for edge in edges:
        if edge.get("source"):
            nodes.add(edge["source"])
        if edge.get("target"):
            nodes.add(edge["target"])
    return nodes


def attribution_hypotheses(
    intel: Dict[str, Any],
    forensic: Dict[str, Any],
    labels: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    hypotheses: List[Dict[str, Any]] = []
    address = intel.get("address", "")

    for label in labels:
        confidence = min(0.95, max(_safe_float(label.get("confidence")), 0.35))
        hypotheses.append({
            "type": "local_label",
            "candidate": label.get("label", ""),
            "category": label.get("category", ""),
            "confidence": round(confidence, 3),
            "confidence_label": _confidence_label(confidence),
            "evidence": [
                f"Investigator label '{label.get('label', '')}' from {label.get('source', 'local')}",
                label.get("notes", ""),
            ],
            "limitations": ["Local labels require provenance review before external reporting."],
        })

    arkham = intel.get("arkham") or {}
    if arkham.get("found"):
        evidence = []
        for key in ("name", "entity_name", "entity_type", "label", "entity_website", "entity_twitter"):
            if arkham.get(key):
                evidence.append(f"{key}: {arkham.get(key)}")
        hypotheses.append({
            "type": "entity_attribution",
            "candidate": arkham.get("name") or arkham.get("entity_name") or arkham.get("label") or "Attributed entity",
            "category": arkham.get("entity_type") or arkham.get("label_type") or "entity",
            "confidence": 0.72,
            "confidence_label": "medium",
            "evidence": evidence,
            "limitations": ["External attribution should be corroborated with transaction behavior and source provenance."],
        })

    scam = intel.get("scam_reports") or {}
    if scam.get("found") and scam.get("count"):
        names = [r.get("name") or r.get("category") or r.get("source") for r in scam.get("records", []) if isinstance(r, dict)]
        hypotheses.append({
            "type": "community_report",
            "candidate": "Reported scam-related wallet",
            "category": "scam",
            "confidence": min(0.7, 0.4 + _safe_float(scam.get("count")) / 20),
            "confidence_label": "medium",
            "evidence": [f"{scam.get('count')} community report(s)"] + names[:5],
            "limitations": ["Community reports are leads, not proof of ownership."],
        })

    public = intel.get("public_enrichment") or {}
    if (public.get("ransomware") or {}).get("found"):
        matches = (public.get("ransomware") or {}).get("matches") or []
        labels_found = [m.get("label") for m in matches if isinstance(m, dict) and m.get("label")]
        hypotheses.append({
            "type": "public_ransomware_dataset",
            "candidate": labels_found[0] if labels_found else "Ransomware-linked wallet",
            "category": "ransomware",
            "confidence": 0.9,
            "confidence_label": "high",
            "evidence": [f"Exact address match in public ransomware dataset: {x}" for x in labels_found[:5]],
            "limitations": ["Public ransomware datasets should be cited and corroborated before external reporting."],
        })

    public_abuse = (public.get("abuse") or {})
    if public_abuse.get("found"):
        hypotheses.append({
            "type": "public_abuse_report",
            "candidate": "Publicly reported abuse/scam wallet",
            "category": "scam",
            "confidence": min(0.75, 0.45 + _safe_float(public_abuse.get("count")) / 20),
            "confidence_label": "medium",
            "evidence": [f"{public_abuse.get('count')} public abuse/scam report(s)"],
            "limitations": ["Public reports are investigative leads and can contain duplicates or false positives."],
        })

    role = forensic.get("role") or {}
    if role.get("role") and role.get("role") != "ordinary_wallet":
        confidence = _safe_float(role.get("confidence"))
        hypotheses.append({
            "type": "behavioral_role",
            "candidate": role.get("role"),
            "category": "wallet_role",
            "confidence": confidence,
            "confidence_label": _confidence_label(confidence),
            "evidence": [role.get("reason", "")],
            "limitations": ["Behavioral role is not identity; it describes observed wallet function."],
        })

    if not hypotheses:
        hypotheses.append({
            "type": "unknown_owner",
            "candidate": "No reliable owner attribution",
            "category": "unknown",
            "confidence": 0.1,
            "confidence_label": "weak",
            "evidence": [f"No local labels or corroborated entity attribution found for {address}"],
            "limitations": ["More transaction depth, labels, exchange records, or victim reports are needed."],
        })

    return sorted(hypotheses, key=lambda h: h["confidence"], reverse=True)


def typology_scores(intel: Dict[str, Any], forensic: Dict[str, Any]) -> List[Dict[str, Any]]:
    features = forensic.get("features") or {}
    role = (forensic.get("role") or {}).get("role", "")
    motifs = {m.get("pattern") for m in forensic.get("motifs") or [] if isinstance(m, dict)}
    dex = forensic.get("dex_forensics") or {}
    signals = {s.get("type") for s in forensic.get("algorithm_signals") or [] if isinstance(s, dict)}

    typologies = []

    def add(name: str, score: float, evidence: List[str]) -> None:
        typologies.append({
            "name": name,
            "score": round(min(score, 0.98), 3),
            "confidence_label": _confidence_label(score),
            "evidence": evidence,
        })

    pass_score = 0.0
    pass_evidence = []
    if role in {"pass_through_mule", "burst_layering_wallet"}:
        pass_score += 0.45
        pass_evidence.append(f"Role classifier: {role}")
    if features.get("flow_through_ratio", 0) >= 0.75:
        pass_score += 0.25
        pass_evidence.append(f"High flow-through ratio {features.get('flow_through_ratio')}")
    if features.get("retention_ratio", 1) <= 0.1:
        pass_score += 0.2
        pass_evidence.append(f"Low retention ratio {features.get('retention_ratio')}")
    if pass_score:
        add("pass-through mule / intermediary", pass_score, pass_evidence)

    layering_score = 0.0
    layering_evidence = []
    if "rapid_burst_movement" in motifs:
        layering_score += 0.22
        layering_evidence.append("Rapid burst movement motif")
    if "round_amount_structuring" in motifs:
        layering_score += 0.2
        layering_evidence.append("Round amount structuring motif")
    if "repeated_exact_value_hops" in motifs:
        layering_score += 0.22
        layering_evidence.append("Repeated exact-value hops")
    if intel.get("chain_hop_swap", {}).get("possible_chain_hopping"):
        layering_score += 0.24
        layering_evidence.append("Bridge/chain hopping indicator")
    if layering_score:
        add("layering / laundering workflow", layering_score, layering_evidence)

    collector_score = 0.0
    collector_evidence = []
    if role == "collector":
        collector_score += 0.42
        collector_evidence.append("Collector role classification")
    if "fan_in_consolidation" in motifs:
        collector_score += 0.25
        collector_evidence.append("Fan-in consolidation motif")
    if features.get("in_degree", 0) >= 5:
        collector_score += 0.18
        collector_evidence.append(f"{features.get('in_degree')} unique inbound counterparties")
    if collector_score:
        add("collector / consolidation wallet", collector_score, collector_evidence)

    distributor_score = 0.0
    distributor_evidence = []
    if role == "distributor":
        distributor_score += 0.42
        distributor_evidence.append("Distributor role classification")
    if "fan_out_dispersal" in motifs:
        distributor_score += 0.25
        distributor_evidence.append("Fan-out dispersal motif")
    if features.get("out_degree", 0) >= 5:
        distributor_score += 0.18
        distributor_evidence.append(f"{features.get('out_degree')} unique outbound counterparties")
    if distributor_score:
        add("distributor / dispersal wallet", distributor_score, distributor_evidence)

    if dex.get("possible_wash_cycle") or "dex_wash_cycle" in signals:
        add("DEX wash-cycle / circular trading", 0.68, ["DEX buy/sell symmetry and repeated pair activity"])

    return sorted(typologies, key=lambda t: t["score"], reverse=True)


def ownership_cluster(edges: List[Dict[str, Any]], subject: str, forensic: Dict[str, Any]) -> Dict[str, Any]:
    subject = subject.lower()
    counterparties = forensic.get("counterparty_roles") or []
    linked = []
    for cp in counterparties:
        role = cp.get("role", "")
        score = 0.0
        evidence = []
        if cp.get("flow_through_ratio", 0) >= 0.75:
            score += 0.25
            evidence.append("similar high flow-through behavior")
        if cp.get("in_degree", 0) == 1 or cp.get("out_degree", 0) == 1:
            score += 0.15
            evidence.append("single-hop dependency in local graph")
        if role in {"pass_through_mule", "burst_layering_wallet", "collector", "distributor"}:
            score += 0.25
            evidence.append(f"compatible role: {role}")
        if score > 0:
            linked.append({
                "address": cp.get("address"),
                "short": cp.get("short"),
                "role": role,
                "confidence": round(min(score, 0.85), 3),
                "evidence": evidence,
            })

    communities = (forensic.get("cluster_analysis") or {}).get("communities") or []
    subject_community = next((c for c in communities if c.get("contains_subject")), None)
    return {
        "subject": subject,
        "cluster_confidence": _confidence_label(max((x["confidence"] for x in linked), default=0)),
        "linked_wallets": sorted(linked, key=lambda x: x["confidence"], reverse=True)[:25],
        "subject_community": subject_community,
        "warning": "Cluster membership is a lead for common-control review, not proof of common ownership.",
    }


def pivot_leads(edges: List[Dict[str, Any]], forensic: Dict[str, Any], labels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    degree = Counter()
    volume = Counter()
    first_seen = {}
    last_seen = {}
    for edge in edges:
        for node in (edge.get("source"), edge.get("target")):
            if not node:
                continue
            degree[node] += 1
            volume[node] += _safe_float(edge.get("value"))
            if edge.get("time"):
                first_seen[node] = min(first_seen.get(node, edge["time"]), edge["time"])
                last_seen[node] = max(last_seen.get(node, edge["time"]), edge["time"])

    label_map = defaultdict(list)
    for label in labels:
        label_map[(label.get("address") or "").lower()].append(label)

    role_map = {cp.get("address"): cp for cp in forensic.get("counterparty_roles") or []}
    subject = (forensic.get("address") or "").lower()
    leads = []
    for node in degree:
        if node == subject:
            continue
        role = role_map.get(node, {})
        node_labels = label_map.get(node, [])
        priority = degree[node] + min(volume[node], 10)
        reasons = []
        if degree[node] >= 3:
            reasons.append(f"{degree[node]} observed graph connections")
        if volume[node] > 0:
            reasons.append(f"Observed volume {round(volume[node], 8)}")
        if role.get("role") and role.get("role") != "ordinary_wallet":
            priority += 3
            reasons.append(f"role hint: {role.get('role')}")
        if node_labels:
            priority += 5
            reasons.append("matched local label")
        leads.append({
            "address": node,
            "short": _short(node),
            "priority_score": round(priority, 3),
            "role_hint": role.get("role", "unknown"),
            "labels": [l.get("label") for l in node_labels],
            "reasons": reasons or ["Observed as local graph counterparty"],
            "recommended_pivots": [
                "Run Address Intel",
                "Run Fund Tracer both directions",
                "Check local labels and case linkage",
                "Preserve transaction hashes touching this node",
            ],
            "first_seen": first_seen.get(node, ""),
            "last_seen": last_seen.get(node, ""),
        })
    return sorted(leads, key=lambda x: x["priority_score"], reverse=True)[:50]


def network_dump(edges: List[Dict[str, Any]], subject: str, max_nodes: int = 300) -> Dict[str, Any]:
    nodes = list(_edge_nodes(edges))
    degree = Counter()
    in_volume = Counter()
    out_volume = Counter()
    for edge in edges:
        src, dst = edge.get("source"), edge.get("target")
        value = _safe_float(edge.get("value"))
        if src:
            degree[src] += 1
            out_volume[src] += value
        if dst:
            degree[dst] += 1
            in_volume[dst] += value
    ranked_nodes = sorted(nodes, key=lambda n: degree[n], reverse=True)[:max_nodes]
    node_set = set(ranked_nodes)
    return {
        "seed": subject.lower(),
        "nodes": [
            {
                "id": n,
                "short": _short(n),
                "degree": degree[n],
                "in_volume": round(in_volume[n], 8),
                "out_volume": round(out_volume[n], 8),
                "is_seed": n == subject.lower(),
            }
            for n in ranked_nodes
        ],
        "edges": [
            {
                "source": e.get("source"),
                "target": e.get("target"),
                "value": e.get("value", 0),
                "token": e.get("token", ""),
                "hash": e.get("hash", ""),
                "time": e.get("time", ""),
            }
            for e in edges
            if e.get("source") in node_set and e.get("target") in node_set
        ][:1000],
    }


def generate_intelligence(
    intel: Dict[str, Any],
    trace_graph: Optional[Dict[str, Any]] = None,
    dex_activity: Optional[Dict[str, Any]] = None,
    labels: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    labels = labels or []
    forensic_result = analyze_forensics(
        intel,
        trace_graph=trace_graph,
        dex_activity=dex_activity,
        local_labels=labels,
    )
    forensic = forensic_result["summary"]
    edges = normalize_edges(intel, trace_graph)
    address = intel.get("address", "")

    attribution = attribution_hypotheses(intel, forensic, labels)
    typologies = typology_scores(intel, forensic)
    cluster = ownership_cluster(edges, address, forensic)
    pivots = pivot_leads(edges, forensic, labels)
    graph = network_dump(edges, address)

    top_typology = typologies[0] if typologies else {"name": "unknown", "score": 0, "confidence_label": "weak"}
    top_attr = attribution[0] if attribution else {"candidate": "unknown", "confidence": 0}
    threat_score = min(
        100,
        int(
            max(_safe_float(top_typology.get("score")), _safe_float(top_attr.get("confidence"))) * 45
            + min(len(pivots), 20) * 1.5
            + min(len(forensic.get("motifs") or []), 8) * 4
        ),
    )

    return {
        "version": THREAT_INTEL_VERSION,
        "subject": address,
        "chain": intel.get("chain", ""),
        "threat_score": threat_score,
        "threat_level": "CRITICAL" if threat_score >= 85 else "HIGH" if threat_score >= 65 else "MEDIUM" if threat_score >= 40 else "LOW",
        "executive": {
            "most_likely_attribution": top_attr,
            "top_typology": top_typology,
            "summary": (
                f"Local algorithms classify {address} as {top_typology.get('name')} "
                f"with {top_typology.get('confidence_label')} confidence. "
                "Attribution remains hypothesis-based unless corroborated by labels, entity records, or legal process."
            ),
        },
        "attribution_hypotheses": attribution,
        "ownership_cluster": cluster,
        "laundering_typologies": typologies,
        "pivot_leads": pivots,
        "network_dump": graph,
        "forensic": forensic,
        "investigator_warnings": [
            "Do not claim a real-world owner without corroborating evidence.",
            "Use pivot leads to expand the case graph and preserve evidence.",
            "Exchange/customer records require appropriate lawful process.",
        ],
    }
