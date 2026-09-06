"""
Evidence Vault router.
  POST   /evidence/{case_id}              → save artifact
  GET    /evidence/{case_id}              → list artifacts for case
  GET    /evidence/{case_id}/{evidence_id} → get artifact + content
  PATCH  /evidence/{case_id}/{evidence_id} → annotate (notes/tags)
  DELETE /evidence/{case_id}/{evidence_id} → delete
  GET    /evidence/{case_id}/summary       → case evidence summary
  GET    /evidence/{case_id}/{evidence_id}/audit → audit log
"""
from __future__ import annotations
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import evidence_vault as ev
import tenancy

logger = logging.getLogger(__name__)
router = APIRouter()


def _user(request: Request) -> dict:
    return getattr(request.state, "user", None) or {}


def _guard(request: Request, case_id: str) -> None:
    """Enforce tenant isolation: the case must belong to the caller's org."""
    try:
        tenancy.guard_case(case_id, _user(request))
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")


class SaveEvidenceRequest(BaseModel):
    evidence_type:  str
    title:          str
    content:        dict
    subject:        str = ""
    chain:          str = ""
    tags:           list[str] = Field(default_factory=list)
    analyst_notes:  str = ""
    actor:          str = "analyst"


class AnnotateRequest(BaseModel):
    notes: str = ""
    tags:  Optional[list[str]] = None
    actor: str = "analyst"


class RegisterExportRequest(BaseModel):
    kind:    str = "report_export"   # graph_exhibit | report_export | regulatory_export
    title:   str
    content: dict
    subject: str = ""
    actor:   str = "analyst"


@router.get("/custody/verify")
async def verify_custody_chain(case_id: str = "") -> dict[str, Any]:
    """Verify the tamper-evident evidence hash chain (global, optionally scoped stats per case)."""
    try:
        return ev.verify_chain(case_id or None)
    except Exception as exc:
        logger.exception("custody verify error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/custody/register/{case_id}")
async def register_export(case_id: str, req: RegisterExportRequest, request: Request) -> dict[str, Any]:
    """Register an export (exhibit / report / regulatory draft) into the custody chain."""
    _guard(request, case_id)
    try:
        record = ev.register_export(
            case_id=case_id, kind=req.kind, title=req.title,
            content=req.content, subject=req.subject, actor=req.actor,
        )
        return {"status": "ok", "evidence": record}
    except Exception as exc:
        logger.exception("register export error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/evidence/{case_id}")
async def save_evidence(case_id: str, req: SaveEvidenceRequest, request: Request) -> dict[str, Any]:
    _guard(request, case_id)
    try:
        record = ev.save_evidence(
            case_id=case_id,
            evidence_type=req.evidence_type,
            title=req.title,
            content=req.content,
            subject=req.subject,
            chain=req.chain,
            tags=req.tags,
            analyst_notes=req.analyst_notes,
            actor=req.actor,
        )
        return {"status": "ok", "evidence": record}
    except Exception as exc:
        logger.exception("save evidence error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/evidence/{case_id}")
async def list_evidence(
    case_id: str,
    request: Request,
    evidence_type: Optional[str] = None,
    subject: Optional[str] = None,
    limit: int = 100,
) -> dict[str, Any]:
    _guard(request, case_id)
    try:
        records = ev.list_evidence(case_id, evidence_type, subject, limit)
        return {"status": "ok", "evidence": records, "count": len(records)}
    except Exception as exc:
        logger.exception("list evidence error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/evidence/{case_id}/summary")
async def evidence_summary(case_id: str, request: Request) -> dict[str, Any]:
    _guard(request, case_id)
    try:
        summary = ev.case_evidence_summary(case_id)
        return {"status": "ok", "summary": summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/evidence/{case_id}/{evidence_id}")
async def get_evidence(case_id: str, evidence_id: str, request: Request) -> dict[str, Any]:
    _guard(request, case_id)
    record = ev.get_evidence(evidence_id)
    if not record or record.get("case_id") != case_id:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {"status": "ok", "evidence": record}


@router.get("/evidence/{case_id}/{evidence_id}/audit")
async def get_audit_log(case_id: str, evidence_id: str, request: Request) -> dict[str, Any]:
    _guard(request, case_id)
    log = ev.get_audit_log(evidence_id)
    return {"status": "ok", "audit_log": log}


@router.patch("/evidence/{case_id}/{evidence_id}")
async def annotate_evidence(
    case_id: str, evidence_id: str, req: AnnotateRequest, request: Request
) -> dict[str, Any]:
    _guard(request, case_id)
    record = ev.annotate_evidence(evidence_id, req.notes, req.tags, req.actor)
    if not record:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {"status": "ok", "evidence": record}


@router.delete("/evidence/{case_id}/{evidence_id}")
async def delete_evidence(case_id: str, evidence_id: str, request: Request) -> dict[str, Any]:
    _guard(request, case_id)
    ok = ev.delete_evidence(evidence_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {"status": "ok", "deleted": evidence_id}
