"""
Risk Scoring Router — POST /api/risk-score
Computes composite risk score (0-100) from address intel.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional

from risk_engine import compute_risk_score

router = APIRouter(tags=["risk"])


class RiskRequest(BaseModel):
    intel: Dict[str, Any]


@router.post("/risk-score")
async def get_risk_score(req: RiskRequest):
    try:
        result = compute_risk_score(req.intel)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
