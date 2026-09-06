"""
Holistic cross-chain trace router.
  POST /api/holistic/trace          live best-effort multi-chain trace of a subject
  POST /api/holistic/trace-events   deterministic trace from supplied normalized events
  GET  /api/holistic/registry       known bridges / DEX routers / mixers + supported chains
"""
from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Any, Optional

import holistic_trace_engine as hte

router = APIRouter(tags=["Holistic Trace"])


class TraceRequest(BaseModel):
    subject: str
    chain: str = "eth"
    direction: str = "both"          # in | out | both
    max_hops: int = 3
    max_nodes: int = 120
    min_value: float = 0.0


class TraceEventsRequest(BaseModel):
    subject: str
    chain: str = "eth"
    direction: str = "both"
    max_hops: int = 4
    min_value: float = 0.0
    events: list[dict[str, Any]] = []


def _api_key_for(chain: str) -> str:
    # Reuse the explorer key configured in Settings (.env) for EVM chains.
    return os.environ.get("ETHERSCAN_API_KEY", "") if chain in hte.EVM_EXPLORERS else ""


@router.post("/holistic/trace")
async def trace(req: TraceRequest):
    subject = req.subject.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="subject address is required")
    if req.direction not in ("in", "out", "both"):
        raise HTTPException(status_code=400, detail="direction must be in, out, or both")
    try:
        return await hte.trace(
            subject, chain=req.chain, direction=req.direction,
            max_hops=max(1, min(req.max_hops, 8)),
            max_nodes=max(5, min(req.max_nodes, 400)),
            min_value=req.min_value,
            api_key=_api_key_for(req.chain),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"holistic trace failed: {exc}")


@router.post("/holistic/trace-events")
async def trace_events(req: TraceEventsRequest):
    if not req.subject.strip():
        raise HTTPException(status_code=400, detail="subject is required")
    if not req.events:
        raise HTTPException(status_code=400, detail="events array is required")
    try:
        return await run_in_threadpool(
            hte.trace_from_events,
            req.subject.strip(), req.events, chain=req.chain,
            direction=req.direction, max_hops=max(1, min(req.max_hops, 8)),
            min_value=req.min_value,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"trace-events failed: {exc}")


@router.get("/holistic/registry")
async def get_registry():
    return hte.registry()


# ── On-graph filtering (P1.8) ───────────────────────────────────────────────
# Post-processes a returned graph by value/time/token/direction/kind/counterparty.
# Works on any graph dict (Holistic or Nexus shape) — the frontend calls this
# after fetching a trace, applying investigator filters without re-running it.

class GraphFilterRequest(BaseModel):
    graph: dict[str, Any]
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    direction: Optional[str] = None      # in | out | both
    token: Optional[str] = None
    kinds: Optional[list[str]] = None    # transfer | bridge | swap | deposit
    from_time: Optional[int] = None      # unix timestamp
    to_time: Optional[int] = None
    max_hops: Optional[int] = None
    counterparty: Optional[str] = None
    keep_isolated: bool = False


@router.post("/holistic/filter")
async def filter_graph_endpoint(req: GraphFilterRequest):
    """Apply investigator filters to a graph. Returns the filtered graph."""
    if not req.graph:
        raise HTTPException(status_code=400, detail="graph is required")
    import graph_filter
    return graph_filter.filter_graph(
        req.graph,
        min_value=req.min_value,
        max_value=req.max_value,
        direction=req.direction,
        token=req.token,
        kinds=req.kinds,
        from_time=req.from_time,
        to_time=req.to_time,
        max_hops=req.max_hops,
        counterparty=req.counterparty,
        keep_isolated=req.keep_isolated,
    )
