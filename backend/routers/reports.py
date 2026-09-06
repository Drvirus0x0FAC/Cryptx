"""
Mega Report Generator router — audience-tailored, CrypTX-branded case reports.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import mega_report
import database as db
import tenancy

router = APIRouter(tags=["Reports"])


def _guard(request: Request, case_id: str) -> None:
    if not case_id:
        return
    try:
        tenancy.guard_case(case_id, getattr(request.state, "user", None) or {})
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")


class GenerateReportRequest(BaseModel):
    case_id: str
    report_type: str
    include_ai: bool = True


@router.get("/reports/types")
def list_report_types():
    """The catalogue of available report types."""
    return {"types": mega_report.report_types()}


@router.post("/reports/generate")
async def generate(req: GenerateReportRequest, request: Request):
    """Generate a branded report for a case; returns the HTML + saved artifact id."""
    _guard(request, req.case_id)
    try:
        return await mega_report.generate_report(
            req.case_id, req.report_type, include_ai=req.include_ai)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")


@router.get("/reports/preview", response_class=HTMLResponse)
async def preview(request: Request, case_id: str = Query(...), report_type: str = Query(...),
                  include_ai: bool = Query(True)):
    """Raw branded HTML (for iframe preview / print), served as text/html."""
    _guard(request, case_id)
    try:
        result = await mega_report.generate_report(case_id, report_type, include_ai=include_ai)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")
    return HTMLResponse(content=result["html"])


@router.get("/reports/artifacts")
def list_artifacts(request: Request, case_id: str = Query(default="")):
    """List previously generated report artifacts (optionally by case)."""
    _guard(request, case_id)
    with db.get_connection() as con:
        if case_id:
            rows = con.execute(
                "SELECT id, subject, chain, case_id, title, format, created_at FROM report_artifacts"
                " WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall()
        else:
            rows = con.execute(
                "SELECT id, subject, chain, case_id, title, format, created_at FROM report_artifacts"
                " ORDER BY created_at DESC LIMIT 100").fetchall()
    return {"artifacts": [dict(r) for r in rows]}


@router.get("/reports/artifacts/{artifact_id}", response_class=HTMLResponse)
def get_artifact(artifact_id: str):
    """Fetch a saved report artifact's HTML."""
    with db.get_connection() as con:
        row = con.execute("SELECT content FROM report_artifacts WHERE id=?", (artifact_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(content=row["content"])
