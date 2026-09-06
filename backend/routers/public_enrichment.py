"""
Public enrichment routes for open/free OSINT sources.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import public_enrichment_engine as engine

router = APIRouter(tags=["Public Enrichment"])


class EnrichmentRequest(BaseModel):
    address: str
    chain: str = ""
    intel: Optional[dict[str, Any]] = None
    refresh: bool = False


@router.post("/public-enrichment/address")
async def public_enrichment_address(req: EnrichmentRequest):
    # P3 fix: enrich_address uses sync `requests` internally, which would block
    # the event loop. Offload to a threadpool so concurrent requests aren't stalled.
    try:
        result = await run_in_threadpool(
            engine.enrich_address,
            req.address.strip(),
            chain=req.chain.strip(),
            intel=req.intel,
            refresh=req.refresh,
        )
        return {"status": "ok", "enrichment": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/public-enrichment/refresh")
async def public_enrichment_refresh():
    try:
        return await run_in_threadpool(engine.refresh_public_feeds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/public-enrichment/status")
async def public_enrichment_status():
    try:
        return await run_in_threadpool(engine.public_enrichment_status)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
