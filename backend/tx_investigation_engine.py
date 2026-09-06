"""
TX Lens: transaction-first investigation algorithms.

This engine turns a single transaction ID into an investigation package:
party roles, value-flow edges, local graph, risk pivots, attribution leads,
laundering indicators, and explainable next steps.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from forensic_engine import _safe_float, _short
from risk_engine import compute_risk_score

TX_LENS_VERSION = "tx-lens-local-v1"


def _addr(value: Any) -> str:
    return str(value or "").strip().lower()


def _token_amount(t: Dict[str, Any]) -> float:
    raw = t.get("value_raw")
    decimals = t.get("decimals")
    try:
        if decimals is not None:
            return float(raw or 0) / (10 ** int(decimals))
        return float(raw or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def extract_value_flows(tx: Dict[str, Any]) -> List[Dict[str, Any]]:
    flows: List[Dict[str, Any]] = []
    chain = tx.get("chain", "")
    unit = tx.get("native_unit") or chain
    tx_hash = tx.get("hash", "")
    ts = tx.get("timestamp", "")

    src = _addr(tx.get("from"))
    dst = _addr(tx.get("to") or tx.get("contract_created"))
    native_value = _safe_float(tx.get("value"))
    if src and dst and native_value > 0:
        flows.append({
            "source": src,
            "target": dst,
            "value": round(native_value, 12),
            "token": unit,
            "asset_type": "native",
            "hash": tx_hash,
            "time": ts,
            "evidence": "native transfer",
        })

    for i, t in enumerate(tx.get("token_transfers") or []):
        s = _addr(t.get("from"))
        d = _addr(t.get("to"))
        if not s or not d:
            continue
        flows.append({
            "source": s,
            "target": d,
            "value": round(_token_amount(t), 12),
            "token": t.get("symbol") or t.get("contract") or "TOKEN",
            "asset_type": "token",
            "contract": t.get("contract", ""),
            "hash": t.get("tx_hash") or tx_hash,
            "time": ts,
            "evidence": f"token transfer #{i + 1}",
        })

    for i, itx in enumerate(tx.get("internal_txs") or []):
        s = _addr(itx.get("from"))
        d = _addr(itx.get("to"))
        if not s or not d:
            continue
        flows.append({
            "source": s,
            "target": d,
            "value": round(_safe_float(itx.get("value_eth")), 12),
            "token": unit,
            "asset_type": "internal",
            "hash": tx_hash,
            "time": ts,
            "evidence": f"internal {itx.get('type', 'call')} #{i + 1}",
            "error": itx.get("error", ""),
        })

    inputs = [i for i in (tx.get("inputs") or []) if _addr(i.get("address"))]
    outputs = [o for o in (tx.get("outputs") or []) if _addr(o.get("address"))]
    if tx.get("chain") == "BTC" and inputs and outputs:
        total_out = sum(_safe_float(o.get("value_btc")) for o in outputs) or 1.0
        for inp in inputs[:25]:
            for out in outputs[:25]:
                flows.append({
                    "source": _addr(inp.get("address")),
                    "target": _addr(out.get("address")),
                    "value": round(_safe_float(out.get("value_btc")) * (_safe_float(inp.get("value_btc")) / max(total_out, 1e-12)), 12),
                    "token": "BTC",
                    "asset_type": "utxo_inferred",
                    "hash": tx_hash,
                    "time": ts,
                    "evidence": "BTC UTXO input-output inferred flow",
                })
    return flows


def involved_addresses(tx: Dict[str, Any], flows: List[Dict[str, Any]]) -> List[str]:
    seen = []
    for a in [tx.get("from"), tx.get("to"), tx.get("contract_created")]:
        aa = _addr(a)
        if aa and aa not in seen:
            seen.append(aa)
    for f in flows:
        for key in ("source", "target", "contract"):
            aa = _addr(f.get(key))
            if aa and aa not in seen:
                seen.append(aa)
    return seen


def _role_for(address: str, tx: Dict[str, Any], flows: List[Dict[str, Any]]) -> str:
    address = _addr(address)
    if address == _addr(tx.get("from")):
        return "initiator"
    if address == _addr(tx.get("contract_created")):
        return "created_contract"
    if address == _addr(tx.get("to")):
        return "primary_recipient"
    src_count = sum(1 for f in flows if f.get("source") == address)
    dst_count = sum(1 for f in flows if f.get("target") == address)
    if src_count and dst_count:
        return "intermediate_party"
    if src_count:
        return "asset_sender"
    if dst_count:
        return "asset_recipient"
    return "related_party"


def _party_volumes(address: str, flows: List[Dict[str, Any]]) -> Dict[str, float]:
    inbound = sum(_safe_float(f.get("value")) for f in flows if f.get("target") == address)
    outbound = sum(_safe_float(f.get("value")) for f in flows if f.get("source") == address)
    return {"inbound": round(inbound, 12), "outbound": round(outbound, 12)}


def _label_for(address: str, labels_by_address: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    return [l.get("label", "") for l in labels_by_address.get(address, []) if l.get("label")]


def _risk_for(intel: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not intel:
        return {"score": 0, "risk_level": "UNKNOWN", "categories": [], "signals": []}
    try:
        return compute_risk_score(intel)
    except Exception:
        return {"score": 0, "risk_level": "UNKNOWN", "categories": [], "signals": []}


def laundering_indicators(tx: Dict[str, Any], flows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    indicators: List[Dict[str, Any]] = []
    source_counts = Counter(f["source"] for f in flows if f.get("source"))
    target_counts = Counter(f["target"] for f in flows if f.get("target"))
    tokens = {f.get("token") for f in flows if f.get("token")}
    token_transfers = tx.get("token_transfers") or []
    internal_txs = tx.get("internal_txs") or []

    def add(name: str, severity: str, score: float, evidence: List[str]) -> None:
        indicators.append({
            "name": name,
            "severity": severity,
            "score": round(min(score, 0.98), 3),
            "evidence": evidence,
        })

    max_out = max(source_counts.values(), default=0)
    if max_out >= 5:
        add("fan-out dispersal", "HIGH" if max_out >= 10 else "MEDIUM", min(0.35 + max_out / 20, 0.85), [f"One party sends to {max_out} recipients inside the transaction"])

    max_in = max(target_counts.values(), default=0)
    if max_in >= 5:
        add("fan-in consolidation", "HIGH" if max_in >= 10 else "MEDIUM", min(0.35 + max_in / 20, 0.85), [f"{max_in} inbound flows converge on one party"])

    if len(tokens) >= 3:
        add("multi-asset movement", "MEDIUM", min(0.3 + len(tokens) / 12, 0.75), [f"{len(tokens)} distinct assets/contracts observed"])

    if tx.get("is_contract_call") and (token_transfers or internal_txs):
        add("contract-mediated movement", "MEDIUM", 0.56, ["Transaction is a contract call with token or internal value movement"])

    if tx.get("chain") == "BTC" and (tx.get("input_count") or 0) >= 3:
        add("BTC multi-input common-control lead", "MEDIUM", min(0.38 + (tx.get("input_count") or 0) / 25, 0.78), [f"{tx.get('input_count')} inputs in one transaction; common-input ownership is a lead, not proof"])

    round_values = [f for f in flows if _safe_float(f.get("value")) > 0 and abs(_safe_float(f.get("value")) - round(_safe_float(f.get("value")), 2)) < 1e-9]
    if len(round_values) >= 3:
        add("structured round amounts", "LOW", min(0.25 + len(round_values) / 25, 0.65), [f"{len(round_values)} flows use round or near-round amounts"])

    if tx.get("status") == "failed":
        add("failed execution", "LOW", 0.2, ["Transaction failed; value-flow conclusions may be limited to attempted behavior"])

    return sorted(indicators, key=lambda x: x["score"], reverse=True)


def build_tx_graph(tx: Dict[str, Any], flows: List[Dict[str, Any]], parties: List[Dict[str, Any]]) -> Dict[str, Any]:
    party_by_addr = {p["address"]: p for p in parties}
    nodes = []
    for address, p in party_by_addr.items():
        nodes.append({
            "id": address,
            "address": address,
            "short": _short(address),
            "role": p["role"],
            "risk_score": p["risk_score"],
            "risk_level": p["risk_level"],
            "labels": p["labels"],
            "inbound": p["inbound"],
            "outbound": p["outbound"],
        })
    return {
        "seed_tx": tx.get("hash", ""),
        "nodes": nodes,
        "edges": flows,
        "stats": {
            "nodes": len(nodes),
            "edges": len(flows),
            "assets": len({f.get("token") for f in flows if f.get("token")}),
            "contracts": len({f.get("contract") for f in flows if f.get("contract")}),
        },
    }


def attribution_hypotheses(parties: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hypotheses = []
    for p in parties:
        evidence = []
        if p["labels"]:
            evidence.append(f"Local labels: {', '.join(p['labels'][:4])}")
        intel = p.get("intel") or {}
        arkham = intel.get("arkham") or {}
        if arkham.get("found"):
            evidence.append(f"Entity attribution: {arkham.get('name') or arkham.get('entity_name') or arkham.get('label')}")
        sanctions = intel.get("sanctions") or {}
        if sanctions.get("sanctioned"):
            evidence.append(f"Sanctions source: {sanctions.get('source', 'screening')}")
        scam = intel.get("scam_reports") or {}
        if scam.get("found") and scam.get("count"):
            evidence.append(f"{scam.get('count')} scam/community reports")
        if evidence:
            confidence = 0.35
            confidence += 0.18 if p["labels"] else 0
            confidence += 0.22 if arkham.get("found") else 0
            confidence += 0.25 if sanctions.get("sanctioned") else 0
            confidence += 0.12 if scam.get("count") else 0
            hypotheses.append({
                "address": p["address"],
                "role": p["role"],
                "candidate": p["labels"][0] if p["labels"] else arkham.get("name") or arkham.get("entity_name") or arkham.get("label") or "Attributed party lead",
                "confidence": round(min(confidence, 0.95), 3),
                "evidence": evidence,
                "limitations": ["Transaction participation does not prove real-world ownership without corroboration."],
            })
    return sorted(hypotheses, key=lambda h: h["confidence"], reverse=True) or [{
        "address": "",
        "role": "unknown",
        "candidate": "No supported owner attribution from this TXID alone",
        "confidence": 0.1,
        "evidence": ["No labels, entity attribution, sanctions, or scam records were present in enriched party evidence."],
        "limitations": ["Expand surrounding transactions and collect off-chain records before making identity claims."],
    }]


def pivot_leads(parties: List[Dict[str, Any]], indicators: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    leads = []
    indicator_boost = 10 if any(i["severity"] in {"HIGH", "MEDIUM"} for i in indicators) else 0
    for p in parties:
        reasons = []
        score = p["risk_score"] + indicator_boost
        if p["role"] in {"initiator", "primary_recipient", "intermediate_party"}:
            score += 12
            reasons.append(f"Core transaction role: {p['role']}")
        if p["outbound"] > 0 and p["inbound"] > 0:
            score += 10
            reasons.append("Both sends and receives value in the transaction")
        if p["labels"]:
            score += 8
            reasons.append("Has local investigator labels")
        if p["risk_score"] >= 60:
            reasons.append(f"High address risk: {p['risk_level']}")
        leads.append({
            "address": p["address"],
            "short": _short(p["address"]),
            "priority_score": min(int(score), 100),
            "role": p["role"],
            "risk_level": p["risk_level"],
            "reasons": reasons or ["Participates in the investigated transaction"],
            "recommended_actions": [
                "Trace inbound source of funds",
                "Trace outbound destination and exchange exits",
                "Check local labels and case notes",
                "Compare timing and amount patterns with nearby transactions",
            ],
        })
    return sorted(leads, key=lambda x: x["priority_score"], reverse=True)


def analyze_transaction(
    tx: Dict[str, Any],
    enriched_intel: Optional[Dict[str, Dict[str, Any]]] = None,
    labels_by_address: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    trace_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    enriched_intel = enriched_intel or {}
    labels_by_address = labels_by_address or {}
    trace_context = trace_context or {}
    flows = extract_value_flows(tx)
    addresses = involved_addresses(tx, flows)
    parties = []
    for address in addresses:
        intel = enriched_intel.get(address) or {}
        risk = _risk_for(intel)
        vols = _party_volumes(address, flows)
        parties.append({
            "address": address,
            "short": _short(address),
            "role": _role_for(address, tx, flows),
            "inbound": vols["inbound"],
            "outbound": vols["outbound"],
            "labels": _label_for(address, labels_by_address),
            "risk_score": int(risk.get("score") or 0),
            "risk_level": risk.get("risk_level", "UNKNOWN"),
            "risk_categories": risk.get("categories", []),
            "risk_signals": risk.get("signals", [])[:8],
            "intel": {
                "chain": intel.get("chain", tx.get("chain", "")),
                "tx_count": intel.get("tx_count"),
                "balance": intel.get("balance"),
                "arkham": intel.get("arkham"),
                "sanctions": intel.get("sanctions"),
                "scam_reports": intel.get("scam_reports"),
                "mixer_hits": intel.get("mixer_hits"),
            } if intel else {},
        })
    parties.sort(key=lambda p: (p["risk_score"], p["outbound"] + p["inbound"]), reverse=True)

    indicators = laundering_indicators(tx, flows)
    graph = build_tx_graph(tx, flows, parties)
    top_risk = max((p["risk_score"] for p in parties), default=0)
    tx_risk = min(100, top_risk + sum(12 for i in indicators if i["severity"] == "HIGH") + sum(7 for i in indicators if i["severity"] == "MEDIUM"))

    return {
        "version": TX_LENS_VERSION,
        "tx_hash": tx.get("hash", ""),
        "chain": tx.get("chain", ""),
        "summary": {
            "status": tx.get("status", "unknown"),
            "timestamp": tx.get("timestamp", ""),
            "party_count": len(parties),
            "flow_count": len(flows),
            "asset_count": graph["stats"]["assets"],
            "indicator_count": len(indicators),
            "tx_risk_score": tx_risk,
            "highest_party_risk": top_risk,
        },
        "transaction": tx,
        "parties": parties,
        "value_flows": flows,
        "local_graph": graph,
        "laundering_indicators": indicators,
        "attribution_hypotheses": attribution_hypotheses(parties),
        "pivot_leads": pivot_leads(parties, indicators),
        "trace_context": trace_context,
        "next_steps": [
            "Preserve transaction detail, receipt/logs, and explorer URL in the case file.",
            "Prioritize highest-risk party pivots for inbound and outbound tracing.",
            "Review token contracts and method ID for protocol-specific behavior.",
            "Treat common-control and behavioral correlations as leads until corroborated.",
        ],
    }
