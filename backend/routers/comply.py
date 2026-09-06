"""
Stablecoin compliance suite router — "CrypTX Comply" (Next-Horizon 3.1).

  POST /api/comply/programs                     create compliance program
  GET  /api/comply/programs                     list programs
  GET  /api/comply/programs/{pid}               program detail
  DELETE /api/comply/programs/{pid}             delete program
  POST /api/comply/programs/{pid}/addresses     add address-book entries
  GET  /api/comply/programs/{pid}/addresses     list address book
  DELETE /api/comply/programs/{pid}/addresses/{aid}  remove entry
  POST /api/comply/programs/{pid}/screen        run a KYT screening
  GET  /api/comply/programs/{pid}/screenings    screening history
  GET  /api/comply/screenings/{sid}             full screening result
  POST /api/comply/programs/{pid}/transfers     Travel-Rule/CTR transfer evaluation
  GET  /api/comply/programs/{pid}/report        examiner/board compliance report
  GET  /api/comply/programs/{pid}/audit         examiner audit log
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import stablecoin_compliance as sc

router = APIRouter(prefix="/comply", tags=["Stablecoin Compliance"])


class ProgramRequest(BaseModel):
    name: str
    org: str = ""
    asset: str = "USDT"
    chains: list[str] = ["eth"]
    travel_rule_usd: float = 3000
    notes: str = ""
    actor: str = ""


@router.post("/programs")
async def create_program(req: ProgramRequest) -> dict[str, Any]:
    return sc.create_program(req.name, req.org, req.asset, req.chains,
                             req.travel_rule_usd, req.notes, req.actor)


@router.get("/programs")
async def list_programs() -> dict[str, Any]:
    return {"programs": sc.list_programs()}


@router.get("/programs/{pid}")
async def get_program(pid: str) -> dict[str, Any]:
    p = sc.get_program(pid)
    if not p:
        raise HTTPException(status_code=404, detail="program not found")
    return p


@router.delete("/programs/{pid}")
async def delete_program(pid: str, actor: str = "") -> dict[str, Any]:
    if not sc.delete_program(pid, actor):
        raise HTTPException(status_code=404, detail="program not found")
    return {"deleted": True}


class AddressesRequest(BaseModel):
    entries: list[dict[str, Any]]
    actor: str = ""


@router.post("/programs/{pid}/addresses")
async def add_addresses(pid: str, req: AddressesRequest) -> dict[str, Any]:
    if not sc.get_program(pid):
        raise HTTPException(status_code=404, detail="program not found")
    return sc.add_addresses(pid, req.entries, req.actor)


@router.get("/programs/{pid}/addresses")
async def list_addresses(pid: str) -> dict[str, Any]:
    return {"addresses": sc.list_addresses(pid)}


@router.delete("/programs/{pid}/addresses/{aid}")
async def remove_address(pid: str, aid: str, actor: str = "") -> dict[str, Any]:
    if not sc.remove_address(pid, aid, actor):
        raise HTTPException(status_code=404, detail="address not found")
    return {"deleted": True}


class ActorRequest(BaseModel):
    actor: str = ""


@router.post("/programs/{pid}/screen")
async def run_screening(pid: str, req: ActorRequest) -> dict[str, Any]:
    try:
        return sc.run_screening(pid, req.actor)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/programs/{pid}/screenings")
async def list_screenings(pid: str, limit: int = 20) -> dict[str, Any]:
    return {"screenings": sc.list_screenings(pid, limit)}


@router.get("/screenings/{sid}")
async def get_screening(sid: str) -> dict[str, Any]:
    s = sc.get_screening(sid)
    if not s:
        raise HTTPException(status_code=404, detail="screening not found")
    return s


class TransfersRequest(BaseModel):
    transfers: list[dict[str, Any]]
    actor: str = ""


@router.post("/programs/{pid}/transfers")
async def evaluate_transfers(pid: str, req: TransfersRequest) -> dict[str, Any]:
    try:
        return sc.evaluate_transfers(pid, req.transfers, req.actor)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/programs/{pid}/report")
async def compliance_report(pid: str) -> dict[str, Any]:
    try:
        return sc.compliance_report(pid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/programs/{pid}/audit")
async def audit_log(pid: str, limit: int = 200) -> dict[str, Any]:
    return {"entries": sc.audit_log(pid, limit)}
