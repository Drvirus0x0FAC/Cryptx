"""
Modern laundering & tracing router (Domain B).

  POST /api/laundering/poisoning       address-poisoning (look-alike dust) detection
  POST /api/laundering/swap-trace      instant-exchanger / cross-chain-swap continuation
  POST /api/laundering/typologies      peel-chain & micro-fragmentation scoring
  GET  /api/laundering/services        instant-swap service registry

Additive; existing tracing features untouched.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import laundering_trace as lt

router = APIRouter(prefix="/laundering", tags=["Laundering Trace"])


class PoisoningRequest(BaseModel):
    subject: str
    transfers: list[dict[str, Any]] = []
    edge: int = 4


@router.post("/poisoning")
async def poisoning(req: PoisoningRequest) -> dict[str, Any]:
    return await run_in_threadpool(lt.detect_address_poisoning, req.subject, req.transfers, req.edge)


class SwapTraceRequest(BaseModel):
    subject: str
    transfers: list[dict[str, Any]] = []
    candidate_outputs: list[dict[str, Any]] = []
    value_tolerance: float = 0.05
    time_window_seconds: int = 21_600


@router.post("/swap-trace")
async def swap_trace(req: SwapTraceRequest) -> dict[str, Any]:
    return await run_in_threadpool(
        lt.detect_swap_continuation,
        req.subject, req.transfers, req.candidate_outputs,
        req.value_tolerance, req.time_window_seconds,
    )


class TypologyRequest(BaseModel):
    subject: str
    transfers: list[dict[str, Any]] = []


@router.post("/typologies")
async def typologies(req: TypologyRequest) -> dict[str, Any]:
    return await run_in_threadpool(lt.score_laundering_typologies, req.subject, req.transfers)


@router.get("/services")
async def services() -> dict[str, Any]:
    return await run_in_threadpool(lt.services_catalog)
