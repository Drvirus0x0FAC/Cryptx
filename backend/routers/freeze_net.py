"""
Freeze-network operationalization router (Next-Horizon 3.2).

  GET  /api/freeze-net/directory              issuer/VASP intake-channel directory
  POST /api/freeze-net/watches                add a watchlist entry
  GET  /api/freeze-net/watches                list watches
  GET  /api/freeze-net/watches/{wid}          watch detail
  POST /api/freeze-net/watches/{wid}/status   pause/activate
  DELETE /api/freeze-net/watches/{wid}        remove watch
  POST /api/freeze-net/watches/{wid}/evaluate manual transfer evaluation
  POST /api/freeze-net/scan                   Beacon-lite sweep of monitor notifications
  GET  /api/freeze-net/events                 watch events (auto-queued packages)
  GET  /api/freeze-net/kpis                   freeze telemetry (time-to-freeze, totals)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import freeze_network as fn
import tenancy

router = APIRouter(prefix="/freeze-net", tags=["Freeze Network"])


def _guard(request: Request, case_id: str) -> None:
    if not case_id:
        return
    try:
        tenancy.guard_case(case_id, getattr(request.state, "user", None) or {})
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")


@router.get("/directory")
async def get_directory(asset: str = "", target_type: str = "") -> dict[str, Any]:
    return {"directory": fn.directory(asset, target_type)}


class WatchRequest(BaseModel):
    address: str
    chain: str = "eth"
    asset: str = "USDT"
    case_id: str = ""
    min_usd: float = 0
    reason: str = ""
    auto_queue: bool = True


@router.post("/watches")
async def add_watch(req: WatchRequest, request: Request) -> dict[str, Any]:
    _guard(request, req.case_id)
    return fn.add_watch(req.address, req.chain, req.asset, req.case_id,
                        req.min_usd, req.reason, req.auto_queue)


@router.get("/watches")
async def list_watches(request: Request, case_id: str = "", status: str = "") -> dict[str, Any]:
    _guard(request, case_id)
    return {"watches": fn.list_watches(case_id, status)}


@router.get("/watches/{wid}")
async def get_watch(wid: str) -> dict[str, Any]:
    w = fn.get_watch(wid)
    if not w:
        raise HTTPException(status_code=404, detail="watch not found")
    return w


class WatchStatusRequest(BaseModel):
    status: str


@router.post("/watches/{wid}/status")
async def set_watch_status(wid: str, req: WatchStatusRequest) -> dict[str, Any]:
    try:
        w = fn.set_watch_status(wid, req.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not w:
        raise HTTPException(status_code=404, detail="watch not found")
    return w


@router.delete("/watches/{wid}")
async def delete_watch(wid: str) -> dict[str, Any]:
    if not fn.delete_watch(wid):
        raise HTTPException(status_code=404, detail="watch not found")
    return {"deleted": True}


class EvaluateRequest(BaseModel):
    counterparty: str
    direction: str = "out"
    amount_usd: float = 0
    tx_hash: str = ""


@router.post("/watches/{wid}/evaluate")
async def evaluate_transfer(wid: str, req: EvaluateRequest) -> dict[str, Any]:
    try:
        return fn.evaluate_transfer(wid, req.counterparty, req.direction, req.amount_usd, req.tx_hash)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/scan")
async def scan() -> dict[str, Any]:
    return fn.scan_watches()


@router.get("/events")
async def events(watch_id: str = "", limit: int = 100) -> dict[str, Any]:
    return {"events": fn.list_events(watch_id, limit)}


@router.get("/kpis")
async def kpis() -> dict[str, Any]:
    return fn.kpis()
