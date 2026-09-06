"""
Counterparty & exchange-usage analytics router.
  GET /api/analytics/counterparties?address=&chain=&window=
      → Exchange Usage (deposits/withdrawals + series), Top Counterparties, Entity Predictions.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import counterparty_analytics as ca

router = APIRouter(tags=["Analytics"])


@router.get("/analytics/counterparties")
async def counterparties(
    address: str = Query(..., description="Subject address (any supported chain)"),
    chain: str = Query("auto", description="Chain id or 'auto' to detect from address format"),
    window: str = Query("all", description="1h | 24h | 1w | 1m | all"),
    limit: int = Query(150, ge=20, le=400),
):
    addr = (address or "").strip()
    if not addr:
        raise HTTPException(status_code=400, detail="address is required")
    try:
        return await ca.analyze(addr, chain=chain, window=window, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"counterparty analytics failed: {exc}")
