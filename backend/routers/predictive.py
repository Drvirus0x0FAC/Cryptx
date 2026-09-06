"""
Predictive Intelligence Router
  POST /api/predict            — run one prediction type (or "all")
  GET  /api/predict/status     — model / baseline status
  POST /api/predict/train      — retrain ML layer from historic labels
  POST /api/predict/baselines  — rebuild population baselines
  GET  /api/predict/history    — prediction audit log
  POST /api/insights           — shared investigator-insight layer (all screens)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import insight_engine
import predictive_engine

router = APIRouter(tags=["Predictive Intelligence"])


class PredictRequest(BaseModel):
    address: str
    chain: str = ""
    type: str = "all"                 # laundering | rugpull | trajectory | victim | all
    intel: Optional[Dict[str, Any]] = None


class InsightRequest(BaseModel):
    context: str = "address"          # address | trace | dex | case | monitor | dashboard
    address: str = ""
    chain: str = ""
    data: Optional[Dict[str, Any]] = None
    include_predictions: bool = True
    limit: int = 8


@router.post("/predict")
async def run_prediction(req: PredictRequest):
    addr = (req.address or "").strip()
    if not addr:
        raise HTTPException(status_code=400, detail="address is required")
    try:
        if req.type == "all":
            return await run_in_threadpool(
                predictive_engine.predict_all, addr, req.chain, req.intel)
        return await run_in_threadpool(
            predictive_engine.predict, req.type, addr, req.chain, req.intel)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"prediction failed: {e}")


@router.get("/predict/status")
async def get_status():
    try:
        return await run_in_threadpool(predictive_engine.model_status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/predict/train")
async def train():
    try:
        return await run_in_threadpool(predictive_engine.train_models)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/predict/baselines")
async def rebuild_baselines():
    try:
        return await run_in_threadpool(predictive_engine.rebuild_baselines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/predict/history")
async def history(address: str = "", limit: int = 50):
    try:
        return await run_in_threadpool(
            predictive_engine.prediction_history, address, min(limit, 200))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/insights")
async def get_insights(req: InsightRequest):
    try:
        return await run_in_threadpool(
            insight_engine.generate_insights,
            req.context, req.address, req.chain, req.data,
            req.include_predictions, min(req.limit, 20),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insight generation failed: {e}")
