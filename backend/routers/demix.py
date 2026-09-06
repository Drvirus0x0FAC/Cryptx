"""
Demixing router — Tornado Cash and cross-chain bridge link analysis.
  POST /api/demix/tornado   pair pool deposits to withdrawals
  POST /api/demix/mixer     generic mixer/tumbler/CoinJoin demix
  POST /api/demix/bridge    reconcile bridge lock/burn to mint/unlock
  POST /api/demix/chain-swap detect chain hopping + asset conversion
  POST /api/demix/analyze   combined AML laundering report
  GET  /api/demix/pools     known Tornado Cash pool denominations/contracts
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Any

import demix_engine

router = APIRouter(tags=["Demixing"])


class TornadoRequest(BaseModel):
    deposits: list[dict[str, Any]] = []
    withdrawals: list[dict[str, Any]] = []
    max_candidates: int = 5
    time_window_seconds: int = 86_400


class BridgeRequest(BaseModel):
    source_events: list[dict[str, Any]] = []
    dest_events: list[dict[str, Any]] = []
    value_tolerance: float = 0.01
    time_window_seconds: int = 21_600
    max_candidates: int = 5


class MixerRequest(BaseModel):
    deposits: list[dict[str, Any]] = []
    withdrawals: list[dict[str, Any]] = []
    max_candidates: int = 8
    time_window_seconds: int = 604_800
    value_tolerance: float = 0.015


class ChainSwapRequest(BaseModel):
    events: list[dict[str, Any]] = []
    value_tolerance: float = 0.035
    time_window_seconds: int = 43_200
    max_candidates: int = 25


class AmlDemixRequest(BaseModel):
    deposits: list[dict[str, Any]] = []
    withdrawals: list[dict[str, Any]] = []
    source_events: list[dict[str, Any]] = []
    dest_events: list[dict[str, Any]] = []
    chain_events: list[dict[str, Any]] = []
    value_tolerance: float = 0.025
    time_window_seconds: int = 86_400
    max_candidates: int = 8


@router.post("/demix/tornado")
async def tornado(req: TornadoRequest):
    if not req.withdrawals:
        raise HTTPException(status_code=400, detail="at least one withdrawal event is required")
    try:
        return await run_in_threadpool(
            demix_engine.demix_tornado,
            req.deposits, req.withdrawals, req.max_candidates, req.time_window_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"tornado demix failed: {exc}")


@router.post("/demix/bridge")
async def bridge(req: BridgeRequest):
    if not req.source_events or not req.dest_events:
        raise HTTPException(status_code=400, detail="source_events and dest_events are required")
    try:
        return await run_in_threadpool(
            demix_engine.demix_bridge,
            req.source_events, req.dest_events, req.value_tolerance,
            req.time_window_seconds, req.max_candidates,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"bridge demix failed: {exc}")


@router.post("/demix/mixer")
async def mixer(req: MixerRequest):
    if not req.withdrawals:
        raise HTTPException(status_code=400, detail="at least one withdrawal event is required")
    try:
        return await run_in_threadpool(
            demix_engine.demix_mixer,
            req.deposits,
            req.withdrawals,
            req.max_candidates,
            req.time_window_seconds,
            req.value_tolerance,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"mixer demix failed: {exc}")


@router.post("/demix/chain-swap")
async def chain_swap(req: ChainSwapRequest):
    if not req.events:
        raise HTTPException(status_code=400, detail="events list is required")
    try:
        return await run_in_threadpool(
            demix_engine.detect_chain_swaps,
            req.events,
            req.value_tolerance,
            req.time_window_seconds,
            req.max_candidates,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"chain-swap detection failed: {exc}")


@router.post("/demix/analyze")
async def analyze(req: AmlDemixRequest):
    if not (req.withdrawals or req.source_events or req.dest_events or req.chain_events):
        raise HTTPException(status_code=400, detail="provide mixer, bridge, or chain_events data")
    try:
        return await run_in_threadpool(
            demix_engine.analyze_laundering,
            deposits=req.deposits,
            withdrawals=req.withdrawals,
            source_events=req.source_events,
            dest_events=req.dest_events,
            chain_events=req.chain_events,
            value_tolerance=req.value_tolerance,
            time_window_seconds=req.time_window_seconds,
            max_candidates=req.max_candidates,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"AML demix analysis failed: {exc}")


@router.get("/demix/pools")
async def pools():
    return {
        "ethereum_pools": [
            {"denomination": d, "contract": demix_engine.TORNADO_ETH_POOLS[d]}
            for d in demix_engine.TORNADO_DENOMINATIONS
        ]
    }
