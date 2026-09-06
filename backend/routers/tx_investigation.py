"""
Transaction-first investigation endpoint.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database as db
from ai_client import AIConfigError, AIProviderError, compact_evidence, deepseek_chat, deepseek_configured
from routers.tx import EVM_CHAINS, _detect_chain, _is_eth_tx, _lookup_btc_tx, _lookup_evm_tx, _lookup_trx_tx
from tx_investigation_engine import analyze_transaction, extract_value_flows, involved_addresses

router = APIRouter(tags=["TX Lens"])

ADDRESS_ENRICH_TIMEOUT = 45
TRACE_EXPAND_TIMEOUT = 120
AI_SYNTHESIS_TIMEOUT = 120
_JOBS: Dict[str, Dict[str, Any]] = {}


class TxInvestigationRequest(BaseModel):
    hash: str
    chain: Optional[str] = None
    include_ai: bool = False
    analyst_focus: str = ""
    enrich_addresses: bool = True
    expand_traces: bool = True
    max_addresses: int = 8


AI_TX_PROMPT = """You are an AI transaction investigation analyst supporting lawful cryptocurrency investigations.
Use only the supplied TX Lens output. Do not invent owner identity, off-chain facts, sanctions, or private data.
Return JSON with:
{
  "tx_brief": "...",
  "party_assessment": ["..."],
  "attribution_leads": ["..."],
  "laundering_assessment": ["..."],
  "highest_value_pivots": ["..."],
  "investigation_plan": ["..."],
  "caveats": ["..."]
}"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job() -> str:
    jid = str(uuid.uuid4())
    _JOBS[jid] = {
        "job_id": jid,
        "status": "queued",
        "progress": 3,
        "stage": "Queued",
        "detail": "TX Lens job is waiting to start.",
        "result": None,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    return jid


def _set_job(job_id: str, *, status: Optional[str] = None, progress: Optional[int] = None, stage: Optional[str] = None, detail: Optional[str] = None, result: Any = None, error: Optional[str] = None) -> None:
    job = _JOBS.get(job_id)
    if not job:
        return
    if status is not None:
        job["status"] = status
    if progress is not None:
        job["progress"] = max(0, min(100, progress))
    if stage is not None:
        job["stage"] = stage
    if detail is not None:
        job["detail"] = detail
    if result is not None:
        job["result"] = result
    if error is not None:
        job["error"] = error
    job["updated_at"] = _now()


async def _lookup_transaction(tx_hash: str, chain_hint: str = "") -> Dict[str, Any]:
    chain = _detect_chain(tx_hash, chain_hint)
    tried: list[str] = []
    if chain == "BTC":
        return await _lookup_btc_tx(tx_hash)
    if chain == "TRX":
        return await _lookup_trx_tx(tx_hash)
    first = await _lookup_evm_tx(tx_hash, chain)
    if not first.get("error"):
        return first
    tried.append(chain)

    # A 0x transaction hash is valid on every EVM chain. If the selected chain
    # misses, probe the other configured EVM chains before failing.
    if _is_eth_tx(tx_hash):
        for candidate in EVM_CHAINS:
            if candidate in tried:
                continue
            tried.append(candidate)
            result = await _lookup_evm_tx(tx_hash, candidate)
            if not result.get("error"):
                result["chain_auto_detected"] = candidate != chain
                result["lookup_attempted_chains"] = tried
                return result
    first["lookup_attempted_chains"] = tried
    return first


async def _safe_address_intel(address: str) -> Optional[Dict[str, Any]]:
    try:
        from crypto_osint import lookup_crypto_address
        result = await asyncio.wait_for(
            lookup_crypto_address(address),
            timeout=ADDRESS_ENRICH_TIMEOUT,
        )
        return result if isinstance(result, dict) else None
    except (asyncio.TimeoutError, Exception):
        return None


async def _safe_trace(address: str) -> Optional[Dict[str, Any]]:
    """Expand a TX party's neighborhood for context. Uses holistic_trace_engine
    (the consolidated tracer) instead of the legacy crypto_tracer."""
    try:
        import holistic_trace_engine as hte
        import os
        a = address.strip().lower()
        chain = "btc" if (a.startswith("bc1") or a[:1] in "13") else ("trx" if a.startswith("t") and len(address) == 34 else "eth")
        api_key = os.environ.get("ETHERSCAN_API_KEY", "") if chain in hte.EVM_EXPLORERS else ""
        result = await asyncio.wait_for(
            hte.trace(subject=address, chain=chain, direction="both", max_hops=2, max_nodes=40, api_key=api_key),
            timeout=TRACE_EXPAND_TIMEOUT,
        )
        # adapt to the graph-model shape the caller expects
        g = result.get("graph") or {}
        return {
            "seed": address,
            "nodes": [{"address": n.get("address", ""), "label": n.get("label", ""), "role": n.get("type", "")} for n in (g.get("nodes") or [])],
            "edges": [{"source": e.get("source", ""), "target": e.get("target", ""), "value": float(e.get("value", 0) or 0)} for e in (g.get("edges") or [])],
            "stats": {"node_count": len(g.get("nodes") or []), "edge_count": len(g.get("edges") or [])},
        }
    except (asyncio.TimeoutError, Exception):
        return None


async def _run_tx_lens(req: TxInvestigationRequest, progress=None) -> Dict[str, Any]:
    def tick(p: int, stage: str, detail: str) -> None:
        if progress:
            progress(p, stage, detail)

    tx_hash = req.hash.strip()
    tick(8, "Resolving Transaction", "Fetching transaction detail from explorer/RPC providers.")
    tx = await _lookup_transaction(tx_hash, req.chain or "")
    if tx.get("error"):
        detail = tx.get("error")
        attempted = tx.get("lookup_attempted_chains") or []
        if attempted:
            detail = f"{detail} Attempted chains: {', '.join(attempted)}."
        raise HTTPException(status_code=502, detail=detail)

    tick(20, "Extracting Value Flows", "Decoding native transfers, token logs, internal calls, and UTXO flows.")
    flows = extract_value_flows(tx)
    addresses = involved_addresses(tx, flows)
    max_addresses = max(2, min(req.max_addresses or 8, 16))
    enrich_targets = addresses[:max_addresses]

    trace_context: Dict[str, Any] = {
        "traced_addresses": [],
        "graphs": {},
        "warnings": [],
        "performance": {
            "address_enrichment_requested": bool(req.enrich_addresses),
            "address_enrichment_limit": max_addresses,
            "address_enrichment_timeout_seconds": ADDRESS_ENRICH_TIMEOUT,
            "trace_expansion_requested": bool(req.expand_traces),
            "trace_timeout_seconds": TRACE_EXPAND_TIMEOUT,
        },
    }

    enriched: Dict[str, Dict[str, Any]] = {}
    if req.enrich_addresses and enrich_targets:
        tick(34, "Enriching Parties", f"Running address intelligence for {len(enrich_targets)} involved wallet(s).")
        results = await asyncio.gather(*[_safe_address_intel(a) for a in enrich_targets], return_exceptions=True)
        for addr, res in zip(enrich_targets, results):
            if isinstance(res, dict):
                enriched[addr] = res
            else:
                trace_context["warnings"].append(f"Address enrichment timed out or failed for {addr}")
    elif not req.enrich_addresses:
        trace_context["warnings"].append("Address enrichment skipped by request")

    tick(50, "Loading Local Labels", "Checking investigator-owned labels and local attribution data.")
    labels_by_address = {
        addr: db.labels_for_address(addr, tx.get("chain", ""))
        for addr in enrich_targets
    }

    if req.expand_traces:
        trace_targets = enrich_targets[:2]
        tick(64, "Expanding Trace Context", f"Tracing surrounding activity for {len(trace_targets)} priority party wallet(s).")
        trace_results = await asyncio.gather(*[_safe_trace(a) for a in trace_targets], return_exceptions=True)
        for addr, graph in zip(trace_targets, trace_results):
            if isinstance(graph, dict):
                trace_context["traced_addresses"].append(addr)
                trace_context["graphs"][addr] = {
                    "stats": graph.get("stats", {}),
                    "patterns": graph.get("patterns", [])[:10],
                    "nodes": (graph.get("nodes") or [])[:40],
                    "edges": (graph.get("edges") or [])[:80],
                }
            else:
                trace_context["warnings"].append(f"Trace expansion timed out or failed for {addr}")
    else:
        trace_context["warnings"].append("Trace expansion skipped by request")

    tick(78, "Running Local Algorithms", "Scoring party risk, laundering indicators, attribution leads, and pivot queue.")
    result = analyze_transaction(
        tx,
        enriched_intel=enriched,
        labels_by_address=labels_by_address,
        trace_context=trace_context,
    )

    ai = None
    if req.include_ai:
        tick(90, "Synthesizing AI Assessment", "The selected AI provider is reviewing the local TX Lens evidence package.")
        if not deepseek_configured():
            raise HTTPException(status_code=400, detail="Selected AI provider is not configured")
        prompt = f"""{AI_TX_PROMPT}

Analyst focus:
{req.analyst_focus or "No extra focus provided."}

TX Lens local output:
{compact_evidence(result, max_chars=18000)}
"""
        ai_res = await asyncio.wait_for(
            deepseek_chat(
                [
                    {
                        "role": "system",
                        "content": "You produce evidence-grounded transaction investigations. Treat attribution and common-control as leads, not proof.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_json=True,
                max_tokens=1800,
                temperature=0.12,
            ),
            timeout=AI_SYNTHESIS_TIMEOUT,
        )
        ai = ai_res["json"] or {"tx_brief": ai_res["content"]}

    tick(98, "Finalizing Report", "Packaging transaction graph, pivots, indicators, and AI assessment.")
    return {"tx_lens": result, "ai_assessment": ai}


async def _run_job(job_id: str, req: TxInvestigationRequest) -> None:
    def progress(p: int, stage: str, detail: str) -> None:
        _set_job(job_id, status="running", progress=p, stage=stage, detail=detail)

    try:
        result = await _run_tx_lens(req, progress=progress)
        _set_job(job_id, status="complete", progress=100, stage="Complete", detail="TX Lens investigation is ready.", result=result)
    except HTTPException as e:
        _set_job(job_id, status="failed", progress=100, stage="Failed", detail=str(e.detail), error=str(e.detail))
    except Exception as e:
        _set_job(job_id, status="failed", progress=100, stage="Failed", detail=str(e), error=str(e))


@router.post("/tx-investigate/jobs")
async def start_tx_investigation_job(req: TxInvestigationRequest):
    job_id = _new_job()
    _set_job(job_id, status="running", progress=5, stage="Starting", detail="Preparing TX Lens investigation.")
    asyncio.create_task(_run_job(job_id, req))
    return _JOBS[job_id]


@router.get("/tx-investigate/jobs/{job_id}")
async def get_tx_investigation_job(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="TX Lens job not found")
    return job


@router.post("/tx-investigate/analyze")
async def tx_investigate(req: TxInvestigationRequest):
    try:
        return await _run_tx_lens(req)
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"investigation dependency unavailable: {e}")
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="TX Lens timed out while waiting for an external provider")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
