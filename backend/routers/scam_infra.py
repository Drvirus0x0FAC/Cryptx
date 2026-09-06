"""
Scam Network Atlas router (Next-Horizon 3.3).

  GET  /api/scam-infra/atlas              full atlas (cached; ?rebuild=true to recluster)
  GET  /api/scam-infra/summary            headline stats
  GET  /api/scam-infra/networks/{nid}     network detail incl. member reports
  POST /api/scam-infra/networks/{nid}/promote  register addresses as attribution leads
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import scam_infrastructure as si

router = APIRouter(prefix="/scam-infra", tags=["Scam Network Atlas"])


@router.get("/atlas")
async def atlas(rebuild: bool = False, min_reports: int = 1) -> dict[str, Any]:
    return si.get_atlas(rebuild, min_reports)


@router.get("/summary")
async def summary() -> dict[str, Any]:
    return si.summary()


@router.get("/networks/{nid}")
async def network(nid: str) -> dict[str, Any]:
    n = si.get_network(nid)
    if not n:
        raise HTTPException(status_code=404, detail="network not found")
    return n


class PromoteRequest(BaseModel):
    assigned_by: str = "scam-atlas"


@router.post("/networks/{nid}/promote")
async def promote(nid: str, req: PromoteRequest) -> dict[str, Any]:
    try:
        return si.promote_to_attribution(nid, req.assigned_by)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
