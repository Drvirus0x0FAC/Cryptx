"""
OSINT sweep router — live social / forum / darkweb-index scan for any address.

  GET  /osint-sweep/{address}              cached (24h) live sweep; ?refresh=true forces re-scan
                                           ?reddit_type=all|posts|comments|off runs the deep
                                           Reddit scraper (posts + comments) automatically.
  POST /osint-sweep/{address}/to-evidence  file the sweep into the evidence vault
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import osint_sweep_engine as ose

router = APIRouter(tags=["OSINT Sweep"])


class ToEvidenceRequest(BaseModel):
    case_id: str


@router.get("/osint-sweep/{address}")
async def sweep(address: str, refresh: bool = False, reddit_type: str = "all"):
    import asyncio
    try:
        return await asyncio.to_thread(ose.sweep, address, refresh, reddit_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/osint-sweep/{address}/to-evidence")
async def to_evidence(address: str, req: ToEvidenceRequest, request: Request):
    import asyncio
    if not req.case_id.strip():
        raise HTTPException(status_code=400, detail="case_id is required")
    user = getattr(request.state, "user", None) or {}
    actor = str(user.get("username") or "analyst")
    try:
        return await asyncio.to_thread(ose.file_to_evidence, address, req.case_id.strip(), actor)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to file evidence: {exc}")
