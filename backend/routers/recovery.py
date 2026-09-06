"""
Recovery last-mile router (Domain D).

  GET  /api/recovery/route          resolve who can freeze an asset (issuer/VASP)
  POST /api/recovery/preview        build a freeze-request package (not persisted)
  POST /api/recovery/requests       create + persist a freeze request
  GET  /api/recovery/requests       list requests (filter by case/status)
  GET  /api/recovery/requests/{id}  fetch one request
  POST /api/recovery/requests/{id}/status  advance status (draft→submitted→frozen…)
  GET  /api/recovery/summary        portfolio: counts + value frozen/seized

Own table in the shared DB; additive.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import recovery_ops as ro
import tenancy

router = APIRouter(prefix="/recovery", tags=["Recovery Ops"])


def _guard(request: Request, case_id: str) -> None:
    if not case_id:
        return
    try:
        tenancy.guard_case(case_id, getattr(request.state, "user", None) or {})
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")


@router.get("/route")
async def route(asset: str, chain: str = "", vasp_name: str = "") -> dict[str, Any]:
    return ro.route_target(asset, chain, vasp_name)


class PreviewRequest(BaseModel):
    address: str
    chain: str = ""
    asset: str
    amount_usd: float = 0
    case_id: str = ""
    reason: str = ""
    vasp_name: str = ""
    evidence: list[dict[str, Any]] = []
    requester: str = ""


@router.post("/preview")
async def preview(req: PreviewRequest, request: Request) -> dict[str, Any]:
    _guard(request, req.case_id)
    return ro.build_package(req.address, req.chain, req.asset, req.amount_usd,
                            req.case_id, req.reason, req.vasp_name, req.evidence, req.requester)


@router.post("/requests")
async def create(req: PreviewRequest, request: Request) -> dict[str, Any]:
    _guard(request, req.case_id)
    return ro.create_request(req.address, req.chain, req.asset, req.amount_usd,
                             req.case_id, req.reason, req.vasp_name, req.evidence, req.requester)


@router.get("/requests")
async def list_requests(request: Request, case_id: str = "", status: str = "", limit: int = 100) -> dict[str, Any]:
    _guard(request, case_id)
    return {"requests": ro.list_requests(case_id, status, limit)}


@router.get("/requests/{rid}")
async def get_request(rid: str) -> dict[str, Any]:
    r = ro.get_request(rid)
    if not r:
        raise HTTPException(status_code=404, detail="request not found")
    return r


class StatusRequest(BaseModel):
    status: str
    note: str = ""
    by: str = ""


@router.post("/requests/{rid}/status")
async def set_status(rid: str, req: StatusRequest) -> dict[str, Any]:
    try:
        r = ro.update_status(rid, req.status, req.note, req.by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not r:
        raise HTTPException(status_code=404, detail="request not found")
    return r


@router.get("/summary")
async def summary() -> dict[str, Any]:
    return ro.summary()
