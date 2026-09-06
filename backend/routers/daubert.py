"""
Court-readiness / Daubert router (Domain C).

  GET  /api/daubert/methods        catalog of platform heuristics + Daubert factors
  POST /api/daubert/dossier        build admissibility appendix (JSON)
  POST /api/daubert/dossier/html   build appendix as print-ready HTML
  POST /api/daubert/notarize       tamper-evident timestamp record for an exhibit
  POST /api/daubert/verify-chain   recompute a notarization hash chain

Additive; complements attribution_workflow + evidence_vault.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import daubert_engine as de

router = APIRouter(prefix="/daubert", tags=["Court Readiness"])


@router.get("/methods")
async def methods() -> dict[str, Any]:
    return de.list_methods()


class DossierRequest(BaseModel):
    case_ref: str
    methods_used: list[str] = []
    analyst: str = ""
    subject: str = ""
    findings: list[dict[str, Any]] = []


@router.post("/dossier")
async def dossier(req: DossierRequest) -> dict[str, Any]:
    return de.build_dossier(req.case_ref, req.methods_used, req.analyst, req.subject, req.findings)


@router.post("/dossier/html", response_class=HTMLResponse)
async def dossier_html(req: DossierRequest) -> HTMLResponse:
    d = de.build_dossier(req.case_ref, req.methods_used, req.analyst, req.subject, req.findings)
    return HTMLResponse(content=de.render_dossier_html(d))


class NotarizeRequest(BaseModel):
    payload: Any
    prev_hash: str = ""
    label: str = ""
    tsa_url: str | None = None  # override config.TSA_URL for this request


@router.post("/notarize")
async def notarize(req: NotarizeRequest) -> dict[str, Any]:
    # When tsa_url is explicitly None on the request, fall back to config.TSA_URL.
    # Pass an empty string to explicitly disable TSA for this notarization.
    import config
    url = req.tsa_url if req.tsa_url is not None else config.TSA_URL
    return de.notarize(req.payload, req.prev_hash, req.label, tsa_url=url)


class VerifyChainRequest(BaseModel):
    records: list[dict[str, Any]] = []


@router.post("/verify-chain")
async def verify_chain(req: VerifyChainRequest) -> dict[str, Any]:
    return de.verify_chain(req.records)


@router.get("/benchmark")
async def benchmark_results() -> dict[str, Any]:
    """Latest labeled-benchmark results (measured error rates per method)."""
    measured = de.measured_error_rates()
    return {"measured": measured, "available": bool(measured)}


@router.post("/benchmark/run")
async def benchmark_run() -> dict[str, Any]:
    """Re-run the reproducible labeled detector benchmark (seeded synthetic corpus)."""
    import asyncio

    def _run():
        from benchmarks.run_benchmark import run
        return run()
    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"benchmark failed: {e}")
