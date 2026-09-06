"""
Smart-contract forensics router (Domain A).

  POST /api/contract/scan          static malicious-pattern risk scan
  POST /api/contract/fingerprint   opcode + selector fingerprint of bytecode
  POST /api/contract/compare       similarity between two contracts / library match
  POST /api/contract/incident      exploit post-mortem reconstruction
  POST /api/contract/approvals     wallet approval-drain exposure scan

Pure analysis over supplied artifacts — no external calls required. Existing
features are untouched; this is an additive surface.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import contract_forensics as cf

router = APIRouter(prefix="/contract", tags=["Contract Forensics"])


class ScanRequest(BaseModel):
    address: str = ""
    chain: str = "eth"
    bytecode: str = ""
    source: str = ""
    abi_selectors: list[str] = []
    verified: Optional[bool] = None


@router.post("/scan")
async def scan(req: ScanRequest) -> dict[str, Any]:
    return await run_in_threadpool(
        cf.scan_contract,
        address=req.address, chain=req.chain, bytecode=req.bytecode,
        source=req.source, abi_selectors=req.abi_selectors, verified=req.verified,
    )


class FingerprintRequest(BaseModel):
    bytecode: str


@router.post("/fingerprint")
async def fingerprint(req: FingerprintRequest) -> dict[str, Any]:
    return await run_in_threadpool(cf.fingerprint_bytecode, req.bytecode)


class CompareRequest(BaseModel):
    bytecode: str = ""
    fingerprint: dict[str, Any] | None = None
    library: list[dict[str, Any]] = []
    threshold: float = 0.5
    top_k: int = 10
    # Optional direct 2-way compare
    other_bytecode: str = ""


@router.post("/compare")
async def compare(req: CompareRequest) -> dict[str, Any]:
    def _compare_sync() -> dict[str, Any]:
        if req.other_bytecode:
            fa = cf.fingerprint_bytecode(req.bytecode)
            fb = cf.fingerprint_bytecode(req.other_bytecode)
            return {"pairwise": cf.compare_fingerprints(fa, fb)}
        return cf.match_library(req.bytecode, req.library, req.threshold, req.top_k)
    return await run_in_threadpool(_compare_sync)


class IncidentRequest(BaseModel):
    txs: list[dict[str, Any]] = []
    contract: str = ""
    attacker: str = ""


@router.post("/incident")
async def incident(req: IncidentRequest) -> dict[str, Any]:
    return await run_in_threadpool(cf.reconstruct_incident, req.txs, req.contract, req.attacker)


class ApprovalsRequest(BaseModel):
    approvals: list[dict[str, Any]] = []
    malicious_spenders: list[str] = []


@router.post("/approvals")
async def approvals(req: ApprovalsRequest) -> dict[str, Any]:
    return await run_in_threadpool(cf.approval_exposure, req.approvals, req.malicious_spenders)
