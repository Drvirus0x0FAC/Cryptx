"""
Memecoin insider forensics router — /api/memecoin

  POST /api/memecoin/analyze   analyze a token for insider-network manipulation
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import memecoin_forensics as mf

router = APIRouter(prefix="/memecoin", tags=["Memecoin Forensics"])


class TransferItem(BaseModel):
    frm: str = ""  # 'from' is reserved in Python; use frm
    to: str = ""
    amount: float = 0
    timestamp: int = 0
    tx_hash: str = ""
    block: str = ""


class AnalyzeRequest(BaseModel):
    token_address: str
    transfers: list[dict[str, Any]] = []
    deployer: str = ""
    launch_timestamp: Optional[int] = None


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Analyze a memecoin token for insider-network manipulation."""
    if not req.token_address.strip():
        raise HTTPException(status_code=400, detail="token_address is required")
    # Normalize 'frm' → 'from' for the engine (Pydantic can't use 'from' as a field).
    transfers = []
    for t in req.transfers:
        transfers.append({
            "from": t.get("from") or t.get("frm") or "",
            "to": t.get("to") or "",
            "amount": t.get("amount") or 0,
            "timestamp": t.get("timestamp") or 0,
            "tx_hash": t.get("tx_hash") or "",
            "block": t.get("block") or "",
        })
    return mf.analyze_memecoin(
        req.token_address.strip(),
        transfers,
        deployer=req.deployer.strip(),
        launch_timestamp=req.launch_timestamp,
    )
