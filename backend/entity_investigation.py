"""
Multi-address / entity-level investigation.

Investigators work with *groups* of addresses (a suspect's wallet set), not single
addresses. This module treats a set of addresses as one entity:
  - Clusters them (delegates to clustering_engine)
  - Computes aggregate in/out flows for the whole entity
  - Traces flows between the cluster's members (inter-cluster links)
  - Surfaces the entity's external counterparties (who they trade with)
"""
from __future__ import annotations

from typing import Any

import constants


async def investigate_entity(addresses: list[str], chain: str = "") -> dict:
    """Run an entity-level investigation over a set of addresses.

    Returns: cluster analysis, aggregate flows, inter-cluster links, external counterparties.
    """
    from clustering_engine import analyze_clusters
    from holistic_trace_engine import fetch_transfers, classify_counterparty
    import asyncio

    addresses = list({a.strip() for a in addresses if a.strip()})
    if not addresses:
        return {"error": "no addresses provided"}

    # 1. Fetch transfers for each address concurrently (with bounded concurrency)
    sem = asyncio.Semaphore(6)
    async def _safe_fetch(addr: str) -> tuple[str, list[dict]]:
        async with sem:
            try:
                txs = await fetch_transfers(addr, chain)
                return addr, list(txs or [])
            except Exception:
                return addr, []

    results = await asyncio.gather(*[_safe_fetch(a) for a in addresses])
    transfers_by_addr: dict[str, list[dict]] = {addr: txs for addr, txs in results}

    # 2. Build a unified edge list
    all_edges: list[dict] = []
    for addr, txs in transfers_by_addr.items():
        for tx in txs:
            src = str(tx.get("from") or "").lower() if str(tx.get("from") or "").startswith("0x") else tx.get("from")
            tgt = str(tx.get("to") or "").lower() if str(tx.get("to") or "").startswith("0x") else tx.get("to")
            all_edges.append({
                "source": src, "target": tgt,
                "value": float(tx.get("value") or 0),
                "token": tx.get("token") or tx.get("asset") or "",
                "tx_hash": tx.get("hash") or tx.get("tx_hash") or "",
                "timestamp": tx.get("time") or tx.get("timestamp") or "",
                "chain": tx.get("chain", chain) or chain,
            })

    # 3. Cluster (which addresses are likely under common control?)
    # Build a node list (analyze_clusters expects (nodes, edges, ...)) — bug fix:
    # the previous call passed all_edges as the first arg, which was interpreted
    # as the nodes list, so every cluster method received garbage node data.
    addr_set_lower = {a.lower() for a in addresses}
    cluster_nodes = [{"id": a, "label": "", "role": ""} for a in addr_set_lower]
    try:
        cluster_result = analyze_clusters(cluster_nodes, all_edges, methods=[
            "gas_funder", "common_counterparty", "temporal_coordination",
            "same_value_pattern", "common_deposit_address",
        ])
    except Exception:
        cluster_result = {"clusters": [], "disclaimer": "clustering unavailable"}

    # 4. Aggregate flows (addr_set_lower already defined above for clustering)
    total_in = 0.0
    total_out = 0.0
    internal_flows = 0.0
    external_counterparties: dict[str, dict] = {}
    for e in all_edges:
        src_internal = e["source"] in addr_set_lower if e["source"] else False
        tgt_internal = e["target"] in addr_set_lower if e["target"] else False
        val = e["value"]
        if src_internal and tgt_internal:
            internal_flows += val
        elif tgt_internal:
            total_in += val
            cp = e["source"]
            external_counterparties.setdefault(cp, {"in": 0.0, "out": 0.0, "txs": 0})
            external_counterparties[cp]["in"] += val
            external_counterparties[cp]["txs"] += 1
        elif src_internal:
            total_out += val
            cp = e["target"]
            external_counterparties.setdefault(cp, {"in": 0.0, "out": 0.0, "txs": 0})
            external_counterparties[cp]["out"] += val
            external_counterparties[cp]["txs"] += 1

    # 5. Classify external counterparties
    top_counterparties = []
    for cp, stats in sorted(external_counterparties.items(),
                            key=lambda x: x[1]["in"] + x[1]["out"], reverse=True)[:30]:
        try:
            classification = classify_counterparty(cp, chain)
        except Exception:
            classification = {"type": "unknown", "label": ""}
        top_counterparties.append({
            "address": cp,
            "in": stats["in"], "out": stats["out"],
            "txs": stats["txs"],
            "type": classification.get("type", "unknown"),
            "label": classification.get("label", ""),
        })

    # 6. Inter-cluster links (flows between detected cluster members)
    inter_cluster = []
    cluster_members: list[set] = []
    for c in (cluster_result.get("clusters") or []):
        members = {m.lower() if isinstance(m, str) else m for m in (c.get("members") or [])}
        cluster_members.append(members)
    for e in all_edges:
        for i, members_i in enumerate(cluster_members):
            for j, members_j in enumerate(cluster_members):
                if i >= j:
                    continue
                if e["source"] in members_i and e["target"] in members_j:
                    inter_cluster.append({
                        "from_cluster": i, "to_cluster": j,
                        "value": e["value"], "tx_hash": e["tx_hash"],
                    })

    return {
        "entity_addresses": addresses,
        "chain": chain,
        "address_count": len(addresses),
        "aggregate_flows": {
            "total_in": total_in,
            "total_out": total_out,
            "net": total_in - total_out,
            "internal": internal_flows,
        },
        "clusters": cluster_result.get("clusters", []),
        "cluster_count": len(cluster_result.get("clusters") or []),
        "inter_cluster_links": inter_cluster[:100],
        "external_counterparties": top_counterparties,
        "total_edges": len(all_edges),
        "disclaimer": "Entity-level analysis treats a group of addresses as one subject. "
                      "Cluster membership is 'common-control lead', not proof of ownership.",
    }
