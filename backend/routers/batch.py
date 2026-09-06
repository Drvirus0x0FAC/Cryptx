"""
Batch Screening Router — POST /api/batch/screen
Screens multiple crypto addresses in parallel, returning risk scores.
"""
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from risk_engine import compute_risk_score

router = APIRouter(tags=["batch"])


class BatchRequest(BaseModel):
    addresses: List[str]
    max_concurrent: int = 5


class BatchItem(BaseModel):
    address: str
    chain: Optional[str] = None
    label: Optional[str] = None


class BatchRequestDetailed(BaseModel):
    items: List[BatchItem]
    max_concurrent: int = 5


async def _screen_one(address: str) -> Dict[str, Any]:
    """Look up one address and compute risk score."""
    address = address.strip()
    if not address:
        return {"address": address, "error": "empty address", "score": -1, "risk_level": "ERROR"}

    try:
        from crypto_osint import lookup_crypto_address
        intel = await lookup_crypto_address(address)
        risk = compute_risk_score(intel)
        return {
            "address": address,
            "chain": intel.get("chain", ""),
            "balance": intel.get("balance", 0),
            "balance_unit": intel.get("balance_unit", ""),
            "tx_count": intel.get("tx_count", 0),
            "score": risk["score"],
            "risk_level": risk["risk_level"],
            "categories": risk["categories"],
            "signals": [s["label"] for s in risk["signals"] if s.get("weight", 0) > 0][:3],
            "error": None,
        }
    except Exception as e:
        return {
            "address": address,
            "chain": "",
            "score": -1,
            "risk_level": "ERROR",
            "categories": [],
            "signals": [],
            "error": str(e),
        }


@router.post("/batch/screen")
async def batch_screen(req: BatchRequest):
    """Screen a list of addresses (plain strings) in parallel."""
    addresses = [a.strip() for a in req.addresses if a.strip()]
    if not addresses:
        raise HTTPException(status_code=400, detail="No addresses provided")
    if len(addresses) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 addresses per batch")

    semaphore = asyncio.Semaphore(req.max_concurrent)

    async def bounded(addr: str) -> Dict[str, Any]:
        async with semaphore:
            return await _screen_one(addr)

    results = await asyncio.gather(*[bounded(a) for a in addresses])

    # Compute aggregate stats
    scored = [r for r in results if r["score"] >= 0]
    stats = {
        "total": len(results),
        "scored": len(scored),
        "errors": len(results) - len(scored),
        "sanctioned": sum(1 for r in scored if r["risk_level"] == "SANCTIONED"),
        "critical": sum(1 for r in scored if r["risk_level"] == "CRITICAL"),
        "high": sum(1 for r in scored if r["risk_level"] == "HIGH"),
        "medium": sum(1 for r in scored if r["risk_level"] == "MEDIUM"),
        "low": sum(1 for r in scored if r["risk_level"] == "LOW"),
        "clean": sum(1 for r in scored if r["risk_level"] == "CLEAN"),
        "avg_score": round(sum(r["score"] for r in scored) / len(scored), 1) if scored else 0,
        "max_score": max((r["score"] for r in scored), default=0),
    }

    return {
        "results": sorted(results, key=lambda r: r["score"], reverse=True),
        "stats": stats,
    }
