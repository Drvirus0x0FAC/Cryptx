"""
Prices router — historical fiat valuation for the USD↔native toggle.

  GET  /prices/historical?asset=BTC&ts=1700000000   unit price on the tx day
  GET  /prices/spot?asset=ETH                        current unit price
  POST /prices/convert                               batch: [{asset, amount, ts}]
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import price_service as ps

router = APIRouter(tags=["Prices"])


class ConvertRequest(BaseModel):
    items: list[dict[str, Any]]


@router.get("/prices/historical")
async def historical(asset: str, ts: Optional[int] = None):
    import asyncio
    if not asset.strip():
        raise HTTPException(status_code=400, detail="asset is required")
    return await asyncio.to_thread(ps.historical_usd, asset.strip(), ts)


@router.get("/prices/spot")
async def spot(asset: str):
    import asyncio
    if not asset.strip():
        raise HTTPException(status_code=400, detail="asset is required")
    return await asyncio.to_thread(ps.spot_usd, asset.strip())


@router.post("/prices/convert")
async def convert(req: ConvertRequest):
    import asyncio
    if not req.items:
        return {"items": []}
    if len(req.items) > 500:
        raise HTTPException(status_code=400, detail="max 500 items per batch")
    return {"items": await asyncio.to_thread(ps.convert_batch, req.items)}
