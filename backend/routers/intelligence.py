"""
Intelligence router — Phase 1 + Phase 2 endpoints:
  POST /nexus/paths        → multi-route pathfinding
  POST /cluster/analyze    → wallet clustering
  POST /cashout/detect     → cashout / exposure detection
  POST /tx/interpret       → transaction interpretation layer
  POST /crosschain/trace   → cross-chain trace engine
  POST /timeline/build     → investigation timeline
"""
from __future__ import annotations
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from pathfinder        import find_all_paths
from cashout_detector  import detect_cashout
from clustering_engine import analyze_clusters
from tx_interpreter    import interpret_tx
from crosschain_engine import trace_crosschain
from timeline_engine   import build_timeline

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class PathRequest(BaseModel):
    source_id:  str
    nodes:      list[dict] = Field(default_factory=list)
    edges:      list[dict] = Field(default_factory=list)
    max_hops:   int = 8
    strategies: Optional[list[str]] = None


class ClusterRequest(BaseModel):
    nodes:                     list[dict] = Field(default_factory=list)
    edges:                     list[dict] = Field(default_factory=list)
    methods:                   Optional[list[str]] = None
    gas_threshold:             float = 0.002
    time_window:               float = 120.0
    min_shared_counterparties: int   = 2


class CashoutRequest(BaseModel):
    subject_id: str
    nodes:      list[dict] = Field(default_factory=list)
    edges:      list[dict] = Field(default_factory=list)


class TxInterpretRequest(BaseModel):
    tx: dict  # TxDetail dict from the TX router


class CrossChainRequest(BaseModel):
    subject_id:       str
    nodes:            list[dict] = Field(default_factory=list)
    edges:            list[dict] = Field(default_factory=list)
    time_window:      float = 3600.0
    value_tolerance:  float = 0.02


class TimelineRequest(BaseModel):
    address:     str
    intel:       Optional[dict] = None
    trace_graph: Optional[dict] = None
    risk:        Optional[dict] = None
    case:        Optional[dict] = None
    cashout:     Optional[dict] = None
    crosschain:  Optional[dict] = None
    limit:       int = 500


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/nexus/paths")
async def find_paths(req: PathRequest) -> dict[str, Any]:
    """
    Find every significant path from source to exchange/mixer/bridge/scam.
    Returns up to 6 path strategies: shortest, highest_value, highest_risk,
    most_recent, mixer_routed, bridge_routed — plus deduped unique_paths list.
    """
    if not req.source_id:
        raise HTTPException(status_code=400, detail="source_id is required")
    if not req.nodes:
        raise HTTPException(status_code=400, detail="nodes list is required")

    try:
        result = await run_in_threadpool(
            find_all_paths,
            nodes=req.nodes,
            edges=req.edges,
            source_id=req.source_id,
            max_hops=min(req.max_hops, 12),
            strategies=req.strategies,
        )
        return {"status": "ok", "paths": result}
    except Exception as exc:
        logger.exception("pathfinder error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cluster/analyze")
async def cluster_analyze(req: ClusterRequest) -> dict[str, Any]:
    """
    Cluster wallets by common-control heuristics.
    Output uses 'common-control lead' language — not ownership claims.
    """
    if not req.nodes:
        raise HTTPException(status_code=400, detail="nodes list is required")

    try:
        result = await run_in_threadpool(
            analyze_clusters,
            nodes=req.nodes,
            edges=req.edges,
            methods=req.methods,
            gas_threshold=req.gas_threshold,
            time_window=req.time_window,
            min_shared_counterparties=req.min_shared_counterparties,
        )
        return {"status": "ok", "clustering": result}
    except Exception as exc:
        logger.exception("clustering error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cashout/detect")
async def cashout_detect(req: CashoutRequest) -> dict[str, Any]:
    """
    Detect exposure / cash-out patterns for a subject wallet.
    Checks for exchange deposits, stablecoin off-ramps, structuring,
    hot-wallet fan-out, fan-in consolidation, and off-ramp service usage.
    """
    if not req.subject_id:
        raise HTTPException(status_code=400, detail="subject_id is required")

    try:
        result = await run_in_threadpool(
            detect_cashout,
            nodes=req.nodes,
            edges=req.edges,
            subject_id=req.subject_id,
        )
        return {"status": "ok", "cashout": result}
    except Exception as exc:
        logger.exception("cashout detection error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/tx/interpret")
async def tx_interpret(req: TxInterpretRequest) -> dict[str, Any]:
    """
    Interpret a transaction: decode method, narrate token transfers,
    explain internal calls, detect approvals/drains, build 'What Happened' timeline.
    """
    if not req.tx:
        raise HTTPException(status_code=400, detail="tx object is required")
    try:
        result = await run_in_threadpool(interpret_tx, req.tx)
        return {"status": "ok", "interpretation": result}
    except Exception as exc:
        logger.exception("tx interpretation error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/crosschain/trace")
async def crosschain_trace(req: CrossChainRequest) -> dict[str, Any]:
    """
    Detect cross-chain movements: bridge hops, value-time matches,
    wrapped assets, stablecoin hops, and cross-chain path confidence.
    """
    if not req.subject_id:
        raise HTTPException(status_code=400, detail="subject_id is required")
    try:
        result = await run_in_threadpool(
            trace_crosschain,
            nodes=req.nodes,
            edges=req.edges,
            subject_id=req.subject_id,
            time_window=req.time_window,
            value_tolerance=req.value_tolerance,
        )
        return {"status": "ok", "crosschain": result}
    except Exception as exc:
        logger.exception("cross-chain trace error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/timeline/build")
async def timeline_build(req: TimelineRequest) -> dict[str, Any]:
    """
    Build a unified investigation timeline from all available data sources:
    address intel, trace graph, risk score, case notes, cashout indicators,
    and cross-chain findings.
    """
    if not req.address:
        raise HTTPException(status_code=400, detail="address is required")
    try:
        result = await run_in_threadpool(
            build_timeline,
            address=req.address,
            intel=req.intel,
            trace_graph=req.trace_graph,
            risk=req.risk,
            case=req.case,
            cashout=req.cashout,
            crosschain=req.crosschain,
            limit=req.limit,
        )
        return {"status": "ok", "timeline": result}
    except Exception as exc:
        logger.exception("timeline build error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
