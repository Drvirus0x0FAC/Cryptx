from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class DexRequest(BaseModel):
    address: str


@router.post("/dex")
async def dex_activity(req: DexRequest):
    """
    Fetch DEX swap history from Uniswap v2/v3 + PancakeSwap via TheGraph.
    Includes pattern analysis (wash-trading, concentration, buy/sell ratios).
    """
    try:
        from dex_trader import get_all_dex_activity, analyze_dex_patterns
        activity = await get_all_dex_activity(req.address.strip())
        # analyze_dex_patterns expects a flat list of swaps, not the aggregator dict
        analysis = analyze_dex_patterns(activity.get("all_swaps", []))
        return {"activity": activity, "analysis": analysis}
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"dex_trader unavailable: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
