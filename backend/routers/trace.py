import asyncio
import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import Literal, Any

router = APIRouter()

# Hard ceiling for a single trace call. Nexus can request longer-running
# traces, but keep an upper bound so a provider cannot hold a worker forever.
TRACE_TIMEOUT = 300  # seconds


class TraceRequest(BaseModel):
    address: str
    hops: int = 3
    mode: Literal["linear", "wide"] = "linear"
    direction: Literal["out", "in", "both"] = "out"
    timeout_seconds: int | None = None


def _detect_chain(address: str) -> str:
    """Infer chain from address format so the holistic engine routes correctly."""
    a = address.strip().lower()
    if a.startswith("0x"):
        return "eth"
    if a.startswith("bc1") or (a[:1] in "13" and 26 <= len(address) <= 35):
        return "btc"
    if a.startswith("t") and len(address) == 34:
        return "trx"
    return "eth"


# Native asset symbol per chain — used to label node balances in the graph model.
EVM_NATIVE_SYMBOL = {
    "eth": "ETH", "bsc": "BNB", "polygon": "MATIC", "arbitrum": "ETH",
    "optimism": "ETH", "base": "ETH", "gnosis": "xDAI", "avax": "AVAX",
    "btc": "BTC", "trx": "TRX", "solana": "SOL", "zcash": "ZEC",
}


def _holistic_to_graph_model(result: dict[str, Any]) -> dict[str, Any]:
    """Adapt the holistic_trace_engine output shape to the TraceGraph contract the
    frontend expects (originally produced by the legacy crypto_tracer).

    The holistic engine returns {graph:{nodes:[TraceNode], edges:[TraceEdge]}, summary:{...}}.
    The frontend expects a TraceGraph with GraphNode/GraphEdge/TraceStats fields.
    This maps one to the other so the existing FundTracer + NexusGraph UIs work
    unchanged after the backend swap.
    """
    g = result.get("graph") or {}
    summary = result.get("summary") or {}
    raw_nodes = g.get("nodes") or []
    raw_edges = g.get("edges") or []

    def _risk_color(score: int) -> str:
        if score >= 80: return "#F87171"
        if score >= 60: return "#FBBF24"
        if score >= 40: return "#FBBF24"
        if score >= 20: return "#FBBF24"
        return "#34D399"

    def _risk_level(score: int) -> str:
        if score >= 100: return "SANCTIONED"
        if score >= 80: return "CRITICAL"
        if score >= 60: return "HIGH"
        if score >= 40: return "MEDIUM"
        if score >= 20: return "LOW"
        return "CLEAN"

    EXPLORERS = {
        "eth": "https://etherscan.io/address/", "bsc": "https://bscscan.com/address/",
        "polygon": "https://polygonscan.com/address/", "arbitrum": "https://arbiscan.io/address/",
        "optimism": "https://optimistic.etherscan.io/address/", "base": "https://basescan.org/address/",
        "btc": "https://mempool.space/address/", "trx": "https://tronscan.org/#/address/",
    }

    nodes = []
    for n in raw_nodes:
        addr = n.get("address") or n.get("id", "")
        chain = n.get("chain", "")
        risk = int(n.get("risk") or n.get("risk_score", 0) or 0)
        # When the deep-analysis path ran, nodes are enriched with real values;
        # fall back to zeros/empty for the plain trace path (backward compatible).
        risk_composite = n.get("risk_score_composite")
        effective_risk = int(risk_composite) if risk_composite is not None else risk
        # holistic TraceNode uses "type"; GraphNode uses "entity"
        entity = n.get("label") or n.get("vasp") or n.get("type", "")
        # Prefer the multi-label risk_labels from enrichment; fall back to [entity].
        risk_labels = n.get("risk_labels")
        if not risk_labels:
            risk_labels = [entity] if entity else []
        nodes.append({
            "id": (addr or n.get("id") or "").lower(),   # bare lc address — MUST match edge endpoints
            "address": addr,
            "short_address": f"{addr[:8]}…{addr[-4:]}" if len(addr) > 16 else addr,
            "hop": int(n.get("hop", 0) or 0),
            "chain": chain,
            "balance": float(n.get("balance", 0.0) or 0.0),
            "balance_unit": EVM_NATIVE_SYMBOL.get(chain, chain.upper()) if chain in EVM_NATIVE_SYMBOL else "",
            "tx_count": int(n.get("tx_count", 0) or 0),
            "entity": entity,
            "risk_level": _risk_level(effective_risk),
            "risk_color": _risk_color(effective_risk),
            "risk_score": effective_risk,
            "risk_labels": risk_labels,
            "is_suspicious": effective_risk >= 60,
            "first_seen": n.get("first_seen", 0) or 0,
            "last_seen": n.get("last_seen", 0) or 0,
            "inflow_value": float(n.get("inflow_value", 0.0) or 0.0),
            "outflow_value": float(n.get("outflow_value", 0.0) or 0.0),
            "explorer": EXPLORERS.get(chain, "") + addr,
            "source": "deep-analysis" if risk_composite is not None else "holistic-trace",
        })

    nodes_by_id = {n["id"]: n for n in nodes}
    # Also index by lowercased address for edge endpoint resolution (the holistic
    # engine uses {chain}:{address} node-ids, but traceNodeToNexus uses the bare
    # lowercased address as the nexus id — edges must match the latter).
    nodes_by_addr = {}
    for n in nodes:
        nodes_by_addr.setdefault(n["address"].lower(), n)

    edges = []
    risk_levels: dict[str, int] = {}
    suspicious_count = 0
    for e in raw_edges:
        src_id = e.get("source", "")
        tgt_id = e.get("target", "")
        # Resolve source/target to node addresses (try id lookup, then strip chain prefix)
        src_node = nodes_by_id.get(src_id)
        tgt_node = nodes_by_id.get(tgt_id)
        src_addr = (src_node or {}).get("address", src_id.split(":")[-1] if ":" in src_id else src_id)
        tgt_addr = (tgt_node or {}).get("address", tgt_id.split(":")[-1] if ":" in tgt_id else tgt_id)
        # Re-key against the lowercased address (what traceNodeToNexus uses as id)
        src_addr_lc = src_addr.lower()
        tgt_addr_lc = tgt_addr.lower()
        amount = float(e.get("value", 0) or 0)
        token = e.get("asset") or e.get("token", "")
        tx_hash = e.get("tx_hash", "")
        edges.append({
            "source": src_addr_lc,
            "target": tgt_addr_lc,
            "amount": amount,
            "token": token,
            "hash": tx_hash,
            "source_address": src_addr_lc,
            "target_address": tgt_addr_lc,
        })

    for n in nodes:
        lvl = n["risk_level"]
        risk_levels[lvl] = risk_levels.get(lvl, 0) + 1
        if n["is_suspicious"]:
            suspicious_count += 1

    # patterns — holistic engine surfaces these in result["patterns"]
    raw_patterns = result.get("patterns") or []
    patterns = []
    for p in raw_patterns:
        if isinstance(p, dict):
            entry = {
                "scope": p.get("scope", "node"),
                "node_id": p.get("node_id") or p.get("node", ""),
                "address": p.get("address", ""),
                "pattern": p.get("pattern") or p.get("name", ""),
                "severity": p.get("severity", "MEDIUM"),
                "confidence": p.get("confidence", "medium"),
                "evidence": p.get("evidence") or p.get("detail", ""),
            }
            # Preserve optional path/categories for peel-chain + layering findings.
            if p.get("path"):
                entry["path"] = p["path"]
            if p.get("categories"):
                entry["categories"] = p["categories"]
            patterns.append(entry)

    graph = {
        "seed": result.get("subject", ""),
        "mode": "wide",
        "direction": result.get("direction", "both"),
        "hops_requested": result.get("max_hops", 0),
        "nodes": nodes,
        "edges": edges,
        "timeline": [],
        "patterns": patterns,
        "warnings": result.get("errors", []),
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "suspicious_nodes": suspicious_count,
            "timeline_events": 0,
            "patterns": len(patterns),
            "risk_levels": risk_levels,
        },
    }
    # Surface the deep-analysis block (clusters, crosschain, cashout, dwell)
    # when present so the frontend can render the analysis summary + clusters.
    if result.get("analysis"):
        graph["analysis"] = result["analysis"]
    return graph


@router.post("/trace")
async def trace_funds(req: TraceRequest):
    """
    Multi-hop fund-flow trace.

    Consolidation: this endpoint now delegates to holistic_trace_engine (the newer,
    cross-chain-capable, async-concurrent tracer) instead of the legacy
    python-modules/crypto_tracer.py. The response is adapted to the graph-model
    shape the FundTracer frontend expects, so no UI change was needed.
    """
    try:
        import holistic_trace_engine as hte
        address = req.address.strip()
        chain = _detect_chain(address)
        api_key = os.environ.get("ETHERSCAN_API_KEY", "") if chain in hte.EVM_EXPLORERS else ""
        timeout = max(30, min(req.timeout_seconds or TRACE_TIMEOUT, TRACE_TIMEOUT))
        try:
            result = await asyncio.wait_for(
                hte.trace(
                    subject=address,
                    chain=chain,
                    direction=req.direction,
                    max_hops=max(1, min(req.hops, 5)),
                    max_nodes=120,
                    api_key=api_key,
                    # Soft budget below the hard timeout → return a partial graph
                    # gracefully instead of a 504 for very active addresses.
                    time_budget=timeout * 0.88,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail=f"Trace timed out after {timeout}s — try fewer hops or linear mode",
            )
        graph = _holistic_to_graph_model(result)
        return {"trace": result, "graph": graph}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trace/deep")
async def trace_deep(req: TraceRequest):
    """
    Deep analysis trace: runs the multi-hop trace, then orchestrates the five
    existing analysis engines (forensic motifs, cashout detection, cross-chain
    bridge stitching, clustering, composite risk scoring) plus three new
    algorithms (peel-chain, layering sequence, dwell-time) into a single pass.

    Returns the same {trace, graph} shape as /trace, but with:
      - graph.patterns POPULATED (was always empty from /trace)
      - graph.nodes enriched (real balance, tx_count, first/last_seen, risk_labels)
      - trace.analysis block (clusters, crosschain paths, cashout dest, dwell)

    The frontend FundTracer renders this with the same TraceGraph component —
    deep analysis just produces a richer graph.
    """
    try:
        import trace_deep_analysis as tda
        import holistic_trace_engine as hte
        address = req.address.strip()
        chain = _detect_chain(address)
        api_key = os.environ.get("ETHERSCAN_API_KEY", "") if chain in hte.EVM_EXPLORERS else ""
        timeout = max(60, min(req.timeout_seconds or TRACE_TIMEOUT, TRACE_TIMEOUT))
        # Cap the fetch depth harder when there's no Etherscan key (Blockscout free
        # tier throttles at ~5 rps, so 120 nodes cannot finish in a sane window).
        deep_max_nodes = 120 if api_key else 70
        try:
            result = await asyncio.wait_for(
                tda.deep_analyze(
                    subject=address,
                    chain=chain,
                    direction=req.direction,
                    max_hops=max(1, min(req.hops, 5)),
                    max_nodes=deep_max_nodes,
                    api_key=api_key,
                    # Soft internal budget below the hard timeout: the trace stops
                    # early and the engines still run, returning a partial-but-valid
                    # deep result instead of a 504 for active addresses.
                    time_budget=timeout * 0.85,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail=f"Deep analysis timed out after {timeout}s — try fewer hops",
            )
        graph = _holistic_to_graph_model(result)
        return {"trace": result, "graph": graph}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
async def trace_html(req: TraceRequest):
    """
    Returns a fully standalone interactive HTML page for the trace graph.
    Embed this in an <iframe> in the frontend.

    Consolidation: now uses holistic_trace_engine for the data, with a minimal
    HTML renderer (the legacy crypto_tracer formatter is no longer used).
    """
    try:
        import holistic_trace_engine as hte
        address = req.address.strip()
        chain = _detect_chain(address)
        api_key = os.environ.get("ETHERSCAN_API_KEY", "") if chain in hte.EVM_EXPLORERS else ""
        result = await hte.trace(
            subject=address, chain=chain, direction=req.direction,
            max_hops=max(1, min(req.hops, 5)), api_key=api_key,
        )
        graph = _holistic_to_graph_model(result)
        from html import escape
        nodes_html = "".join(
            f"<tr><td>{escape(str(n['address'])[:16])}…</td><td>{escape(n.get('entity', ''))}</td></tr>"
            for n in graph["nodes"][:50]
        )
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Trace {escape(address[:12])}</title>
        <style>body{{font-family:monospace;background:#0a0a0f;color:#eee;padding:20px}}
        table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #333;padding:4px}}</style>
        </head><body><h2>Fund Trace: {escape(address)}</h2>
        <p>{graph['stats']['nodes']} nodes, {graph['stats']['edges']} edges, {graph['stats']['suspicious_nodes']} flagged</p>
        <table><thead><tr><th>Address</th><th>Role</th></tr></thead><tbody>{nodes_html}</tbody></table>
        </body></html>"""
        return HTMLResponse(content=html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/trace/deep/stream")
async def trace_deep_stream(req: TraceRequest):
    """Deep analysis with live progress via Server-Sent Events.

    Streams `data: {"type":"progress","pct":..,"label":..,"detail":..}` messages
    as each phase runs, then a final `{"type":"result", trace, graph}` (or
    `{"type":"error", detail}`). Same computation as POST /trace/deep — this
    variant just gives the UI visibility instead of a blind spinner.
    """
    import trace_deep_analysis as tda
    import holistic_trace_engine as hte

    address = req.address.strip()
    chain = _detect_chain(address)
    api_key = os.environ.get("ETHERSCAN_API_KEY", "") if chain in hte.EVM_EXPLORERS else ""
    timeout = max(60, min(req.timeout_seconds or TRACE_TIMEOUT, TRACE_TIMEOUT))
    deep_max_nodes = 120 if api_key else 70

    queue: asyncio.Queue = asyncio.Queue()

    def _progress(evt: dict):
        try:
            queue.put_nowait({"type": "progress", **evt})
        except Exception:  # noqa: BLE001
            pass

    async def _run():
        try:
            result = await asyncio.wait_for(
                tda.deep_analyze(
                    subject=address, chain=chain, direction=req.direction,
                    max_hops=max(1, min(req.hops, 5)), max_nodes=deep_max_nodes,
                    api_key=api_key, time_budget=timeout * 0.85, progress=_progress,
                ),
                timeout=timeout,
            )
            graph = _holistic_to_graph_model(result)
            await queue.put({"type": "result", "trace": result, "graph": graph})
        except asyncio.TimeoutError:
            await queue.put({"type": "error",
                             "detail": f"Deep analysis timed out after {timeout}s — try fewer hops"})
        except Exception as e:  # noqa: BLE001
            await queue.put({"type": "error", "detail": str(e)})
        finally:
            await queue.put({"type": "__end__"})

    async def _gen():
        task = asyncio.create_task(_run())
        # Prime the stream: a ~2KB comment padding forces intermediaries (the Vite
        # dev proxy, some browsers) to flush immediately instead of buffering the
        # first small SSE messages until a threshold — which is what makes progress
        # appear "all at once at the end".
        yield ":" + (" " * 2048) + "\n\n"
        yield "retry: 10000\n\n"
        try:
            while True:
                evt = await queue.get()
                if evt.get("type") == "__end__":
                    break
                yield f"data: {json.dumps(evt)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
