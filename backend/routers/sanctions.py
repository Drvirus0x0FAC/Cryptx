"""
Sanctions screening router — multi-jurisdiction address + name screening.
  POST /api/sanctions/screen        screen one address
  POST /api/sanctions/screen-bulk   screen many addresses
  POST /api/sanctions/search        fuzzy entity-name search
  POST /api/sanctions/refresh       pull latest public feeds (best-effort)
  GET  /api/sanctions/status        dataset stats + last refresh
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import sanctions_engine

router = APIRouter(tags=["Sanctions"])


class ScreenRequest(BaseModel):
    address: str
    chain: Optional[str] = None


class ScreenBulkRequest(BaseModel):
    addresses: list[str]
    chain: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    limit: int = 25
    min_score: float = 0.55


@router.post("/sanctions/screen")
async def screen(req: ScreenRequest):
    addr = req.address.strip()
    if not addr:
        raise HTTPException(status_code=400, detail="address is required")
    return sanctions_engine.screen_address(addr, req.chain)


@router.post("/sanctions/screen-bulk")
async def screen_bulk(req: ScreenBulkRequest):
    addrs = [a.strip() for a in req.addresses if a.strip()]
    if not addrs:
        raise HTTPException(status_code=400, detail="at least one address is required")
    if len(addrs) > 500:
        raise HTTPException(status_code=400, detail="max 500 addresses per request")
    return sanctions_engine.screen_addresses(addrs, req.chain)


@router.post("/sanctions/search")
async def search(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    return sanctions_engine.search_name(req.query, req.limit, req.min_score)


@router.get("/sanctions/entity/{uid}")
async def entity_detail(uid: str):
    result = sanctions_engine.get_entity(uid)
    if result is None:
        raise HTTPException(status_code=404, detail="sanctioned entity not found")
    return result


@router.post("/sanctions/refresh")
async def refresh():
    try:
        import asyncio
        # sync requests-based feed pull — run off the event loop (I/O discipline)
        return await asyncio.to_thread(sanctions_engine.refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"refresh failed: {exc}")


@router.get("/sanctions/status")
async def get_status():
    return sanctions_engine.status()
