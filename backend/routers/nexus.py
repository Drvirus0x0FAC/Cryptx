"""
Nexus Graph endpoints for local wallet correlation and graph investigation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import database as db
import demix_engine
from ai_client import AIConfigError, AIProviderError, compact_evidence, deepseek_chat, deepseek_configured, deepseek_settings
from nexus_graph_engine import build_nexus_graph
from threat_intel_engine import generate_intelligence

router = APIRouter(tags=["Nexus Graph"])


class NexusRequest(BaseModel):
    address: str
    intel: Optional[Dict[str, Any]] = None
    trace_graph: Optional[Dict[str, Any]] = None
    include_ai: bool = False
    analyst_focus: str = ""
    max_nodes: int = 250


class NexusDemixRequest(BaseModel):
    nexus: Dict[str, Any]
    selected_addresses: List[str] = []
    run_tornado: bool = True
    run_mixer: bool = True
    run_bridge: bool = True
    run_chain_swap: bool = True
    run_aml: bool = True
    max_candidates: int = 8
    time_window_seconds: int = 86_400
    value_tolerance: float = 0.025


AI_NEXUS_PROMPT = """You are an AI graph investigation analyst supporting lawful cryptocurrency investigations.
Use only the supplied Nexus Graph output. Do not invent owner identity, off-chain facts, sanctions, or private data.
Return JSON with:
{
  "graph_brief": "...",
  "key_clusters": ["..."],
  "bridge_wallets": ["..."],
  "strong_correlations": ["..."],
  "priority_pivots": ["..."],
  "investigation_strategy": ["..."],
  "caveats": ["..."]
}"""


def _addr(v: Any) -> str:
    return str(v or "").strip().lower()


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _text(*vals: Any) -> str:
    return " ".join(str(v or "") for v in vals).lower()


def _node_map(nexus: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {_addr(n.get("id") or n.get("address")): n for n in nexus.get("nodes") or [] if isinstance(n, dict)}


def _edge_event(edge: Dict[str, Any], nodes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    source = _addr(edge.get("source"))
    target = _addr(edge.get("target"))
    src_node = nodes.get(source, {})
    dst_node = nodes.get(target, {})
    label_blob = _text(
        edge.get("type"),
        edge.get("kind"),
        edge.get("token"),
        src_node.get("role_hint"),
        dst_node.get("role_hint"),
        " ".join(src_node.get("labels") or []),
        " ".join(dst_node.get("labels") or []),
    )
    event_type = "transfer"
    if any(w in label_blob for w in ("mixer", "tornado", "coinjoin", "tumbler")):
        event_type = "mixer"
    elif any(w in label_blob for w in ("bridge", "cross-chain", "cross chain")):
        event_type = "bridge"
    elif any(w in label_blob for w in ("swap", "dex", "router")):
        event_type = "swap"
    return {
        "tx_hash": edge.get("hash") or edge.get("tx_hash") or "",
        "chain": edge.get("chain") or edge.get("source_chain") or "",
        "dest_chain": edge.get("dest_chain") or edge.get("target_chain") or "",
        "token": edge.get("token") or edge.get("asset") or "",
        "amount": _num(edge.get("value") or edge.get("amount") or edge.get("value_usd")),
        "timestamp": _int(edge.get("time") or edge.get("timestamp")),
        "sender": source,
        "recipient": target,
        "source": source,
        "target": target,
        "protocol": edge.get("protocol") or edge.get("type") or event_type,
        "event_type": event_type,
        "raw": edge,
    }


def _events_from_nexus(nexus: Dict[str, Any], selected_addresses: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    nodes = _node_map(nexus)
    selected = {_addr(a) for a in selected_addresses if _addr(a)}
    raw_edges = [e for e in nexus.get("edges") or [] if isinstance(e, dict)]
    if selected:
        raw_edges = [
            e for e in raw_edges
            if _addr(e.get("source")) in selected or _addr(e.get("target")) in selected
        ]
    events = [_edge_event(e, nodes) for e in raw_edges]
    deposits, withdrawals, source_events, dest_events = [], [], [], []
    for ev in events:
        source_node = nodes.get(ev["source"], {})
        target_node = nodes.get(ev["target"], {})
        source_blob = _text(source_node.get("role_hint"), " ".join(source_node.get("labels") or []))
        target_blob = _text(target_node.get("role_hint"), " ".join(target_node.get("labels") or []))
        if ev["event_type"] == "mixer":
            if any(w in target_blob for w in ("mixer", "tornado", "coinjoin", "tumbler")):
                deposits.append({**ev, "depositor": ev["sender"], "address": ev["sender"]})
            elif any(w in source_blob for w in ("mixer", "tornado", "coinjoin", "tumbler")):
                withdrawals.append({**ev, "recipient": ev["recipient"]})
            else:
                deposits.append({**ev, "depositor": ev["sender"], "address": ev["sender"]})
                withdrawals.append({**ev, "recipient": ev["recipient"]})
        if ev["event_type"] == "bridge":
            source_events.append(ev)
            dest_events.append(ev)
    if not deposits and not withdrawals:
        for ev in events:
            if ev["event_type"] in {"bridge", "swap"}:
                continue
            if ev["amount"] <= 0:
                continue
            deposits.append({**ev, "depositor": ev["sender"], "address": ev["sender"]})
            withdrawals.append({**ev, "recipient": ev["recipient"]})
    if not source_events and not dest_events:
        source_events = [e for e in events if e["event_type"] in {"bridge", "swap"}]
        dest_events = [e for e in events if e["event_type"] in {"bridge", "swap"}]
    return {
        "events": events,
        "deposits": deposits,
        "withdrawals": withdrawals,
        "source_events": source_events,
        "dest_events": dest_events,
        "chain_events": events,
    }


def _demix_overlays(results: Dict[str, Any]) -> Dict[str, Any]:
    nodes: Dict[str, Dict[str, Any]] = {}
    edges = []

    def add_node(address: str, label: str, risk: int = 60):
        addr = _addr(address)
        if not addr:
            return
        nodes[addr] = {
            "id": addr,
            "address": addr,
            "label": label,
            "risk_score": max(risk, int(nodes.get(addr, {}).get("risk_score", 0))),
        }

    def add_edge(source: str, target: str, method: str, confidence: float, reason: str, tx_hash: str = ""):
        s, t = _addr(source), _addr(target)
        if not s or not t or s == t:
            return
        risk = min(100, 45 + int(confidence * 45))
        add_node(s, "Demix source", risk)
        add_node(t, "Demix candidate", risk)
        edges.append({
            "source": s,
            "target": t,
            "method": method,
            "confidence": round(confidence, 4),
            "reason": reason,
            "tx_hash": tx_hash,
        })

    mixer = ((results.get("mixer") or {}).get("links") or []) + ((results.get("tornado") or {}).get("links") or [])
    for link in mixer:
        recipient = link.get("recipient")
        for cand in (link.get("candidates") or [])[:5]:
            add_edge(cand.get("depositor") or cand.get("funder"), recipient, results.get("mixer", {}).get("method") or "mixer_demix", _num(cand.get("confidence")), "; ".join(cand.get("reasons") or [])[:240], link.get("withdrawal_tx") or "")

    for link in (results.get("bridge") or {}).get("links") or []:
        source_tx = link.get("source_tx") or ""
        for cand in (link.get("candidates") or [])[:5]:
            add_edge(source_tx, cand.get("dest_tx"), "bridge_demix", _num(cand.get("confidence")), "; ".join(cand.get("reasons") or [])[:240], cand.get("dest_tx") or source_tx)

    for link in (results.get("chain_swaps") or {}).get("links") or []:
        source_tx = link.get("source_tx") or ""
        for cand in (link.get("candidates") or [])[:5]:
            add_edge(source_tx, cand.get("dest_tx"), "chain_swap", _num(cand.get("confidence")), "; ".join(cand.get("reasons") or [])[:240], cand.get("dest_tx") or source_tx)

    return {"nodes": list(nodes.values()), "edges": edges}


@router.post("/nexus/analyze")
async def nexus_analyze(req: NexusRequest):
    try:
        intel = req.intel
        if not intel:
            from crypto_osint import lookup_crypto_address
            intel = await lookup_crypto_address(req.address.strip())

        labels = db.labels_for_address(
            intel.get("address", req.address.strip()),
            intel.get("chain", ""),
        )
        nexus = await run_in_threadpool(
            build_nexus_graph,
            intel,
            trace_graph=req.trace_graph,
            labels=labels,
            max_nodes=max(25, min(req.max_nodes or 250, 500)),
        )
        threat_intel = await run_in_threadpool(
            generate_intelligence,
            intel,
            trace_graph=req.trace_graph,
            dex_activity=None,
            labels=labels,
        )

        ai = None
        if req.include_ai:
            if not deepseek_configured():
                ai = {
                    "error": "Selected AI provider is not configured",
                    "runtime": deepseek_settings(),
                    "graph_brief": "Nexus graph and local threat intelligence were generated without AI synthesis.",
                    "caveats": ["AI assessment skipped because the selected AI provider is not configured."],
                }
            else:
                prompt = f"""{AI_NEXUS_PROMPT}

Analyst focus:
{req.analyst_focus or "No extra focus provided."}

Nexus Graph local output:
{compact_evidence({"nexus": nexus, "threat_intel": threat_intel}, max_chars=22000)}
"""
                try:
                    ai_res = await deepseek_chat(
                        [
                            {
                                "role": "system",
                                "content": "You produce evidence-grounded graph investigation leads. Treat correlations as leads, not proof.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        response_json=True,
                        max_tokens=1700,
                        temperature=0.12,
                    )
                    ai = ai_res["json"] or {"graph_brief": ai_res["content"]}
                except (AIConfigError, AIProviderError) as e:
                    ai = {
                        "error": str(e),
                        "runtime": deepseek_settings(),
                        "graph_brief": "Nexus graph and local threat intelligence were generated, but AI synthesis was skipped.",
                        "caveats": ["Review local graph evidence; AI assessment failed independently from Nexus graph generation."],
                    }

        return {"nexus": nexus, "threat_intel": threat_intel, "ai_assessment": ai}
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"crypto_osint module unavailable: {e}")
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nexus/demix")
async def nexus_demix(req: NexusDemixRequest):
    try:
        if not req.nexus.get("nodes") and not req.nexus.get("edges"):
            raise HTTPException(status_code=400, detail="nexus graph with nodes or edges is required")

        extracted = _events_from_nexus(req.nexus, req.selected_addresses)
        max_candidates = max(1, min(req.max_candidates or 8, 50))
        time_window = max(60, min(req.time_window_seconds or 86_400, 2_592_000))
        tolerance = max(0.0001, min(req.value_tolerance or 0.025, 0.25))
        results: Dict[str, Any] = {}
        skipped: Dict[str, str] = {}

        deposits = extracted["deposits"]
        withdrawals = extracted["withdrawals"]
        source_events = extracted["source_events"]
        dest_events = extracted["dest_events"]
        chain_events = extracted["chain_events"]

        if req.run_tornado:
            tornado_withdrawals = [w for w in withdrawals if _num(w.get("denomination") or w.get("amount")) in demix_engine.TORNADO_DENOMINATIONS]
            tornado_deposits = [d for d in deposits if _num(d.get("denomination") or d.get("amount")) in demix_engine.TORNADO_DENOMINATIONS]
            if tornado_withdrawals:
                results["tornado"] = await run_in_threadpool(
                    demix_engine.demix_tornado,
                    tornado_deposits,
                    tornado_withdrawals,
                    max_candidates=max_candidates,
                    time_window_seconds=time_window,
                )
            else:
                skipped["tornado"] = "no Tornado-denomination withdrawal events were derivable from the Nexus graph"

        if req.run_mixer:
            if withdrawals:
                results["mixer"] = await run_in_threadpool(
                    demix_engine.demix_mixer,
                    deposits,
                    withdrawals,
                    max_candidates=max_candidates,
                    time_window_seconds=time_window,
                    value_tolerance=tolerance,
                )
            else:
                skipped["mixer"] = "no withdrawal-like events were derivable from the Nexus graph"

        if req.run_bridge:
            if source_events and dest_events:
                results["bridge"] = await run_in_threadpool(
                    demix_engine.demix_bridge,
                    source_events,
                    dest_events,
                    value_tolerance=tolerance,
                    time_window_seconds=time_window,
                    max_candidates=max_candidates,
                )
            else:
                skipped["bridge"] = "no bridge-like source/destination events were derivable from the Nexus graph"

        if req.run_chain_swap:
            if chain_events:
                results["chain_swaps"] = await run_in_threadpool(
                    demix_engine.detect_chain_swaps,
                    chain_events,
                    value_tolerance=tolerance * 1.4,
                    time_window_seconds=time_window,
                    max_candidates=max_candidates,
                )
            else:
                skipped["chain_swaps"] = "no transaction events were derivable from the Nexus graph"

        if req.run_aml:
            if withdrawals or source_events or dest_events or chain_events:
                results["aml"] = await run_in_threadpool(
                    demix_engine.analyze_laundering,
                    deposits=deposits,
                    withdrawals=withdrawals,
                    source_events=source_events,
                    dest_events=dest_events,
                    chain_events=chain_events,
                    value_tolerance=tolerance,
                    time_window_seconds=time_window,
                    max_candidates=max_candidates,
                )
            else:
                skipped["aml"] = "no demix-compatible events were derivable from the Nexus graph"

        overlays = _demix_overlays(results)
        risk_scores = [
            _int((v.get("risk") or {}).get("score"))
            for v in results.values()
            if isinstance(v, dict) and isinstance(v.get("risk"), dict)
        ]
        typologies = []
        for v in results.values():
            if isinstance(v, dict):
                typologies.extend(v.get("typologies") or [])

        return {
            "status": "ok",
            "source": "nexus_graph",
            "event_inventory": {
                "events": len(extracted["events"]),
                "deposits": len(deposits),
                "withdrawals": len(withdrawals),
                "source_events": len(source_events),
                "dest_events": len(dest_events),
                "chain_events": len(chain_events),
            },
            "results": results,
            "skipped": skipped,
            "overlay": overlays,
            "summary": {
                "risk_score": max(risk_scores or [0]),
                "typology_count": len(typologies),
                "overlay_node_count": len(overlays["nodes"]),
                "overlay_edge_count": len(overlays["edges"]),
                "engines_run": sorted(results.keys()),
            },
            "typologies": typologies,
            "disclaimer": "Nexus Demixing converts graph edges into heuristic demix events. Results are investigative leads, not attribution proof.",
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Nexus demixing failed: {exc}")
