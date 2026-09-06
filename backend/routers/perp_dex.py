"""
Perp-DEX intelligence router (Next-Horizon 3.4).

  GET /api/perp-dex/hyperliquid/{address}   full account analysis + abuse detectors
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

import hyperliquid_engine as hl

router = APIRouter(prefix="/perp-dex", tags=["Perp DEX Intel"])


@router.get("/hyperliquid/{address}")
async def analyze(address: str) -> dict[str, Any]:
    addr = (address or "").strip()
    if not (addr.startswith("0x") and len(addr) == 42):
        raise HTTPException(status_code=400, detail="Hyperliquid accounts are EVM addresses (0x…, 42 chars)")
    try:
        return await hl.analyze(addr)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Hyperliquid API unavailable: {e}")
