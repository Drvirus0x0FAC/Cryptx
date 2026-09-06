"""
Victim Report & Scam Intelligence router.
"""
from __future__ import annotations
import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import victim_report as vr

logger = logging.getLogger(__name__)
router = APIRouter()


class SubmitReportRequest(BaseModel):
    scam_type:        str
    scammer_address:  str
    chain:            str   = "ETH"
    victim_address:   str   = ""
    amount_usd:       float = 0.0
    token:            str   = "Unknown"
    incident_date:    str   = ""
    description:      str   = ""
    contact_name:     str   = ""
    contact_email:    str   = ""
    jurisdiction:     str   = ""
    tx_hashes:        List[str] = []
    tags:             List[str] = []
    case_id:          str   = ""


class UpdateReportRequest(BaseModel):
    status:         Optional[str]        = None
    analyst_notes:  Optional[str]        = None
    case_id:        Optional[str]        = None
    jurisdiction:   Optional[str]        = None
    contact_name:   Optional[str]        = None
    contact_email:  Optional[str]        = None
    tags:           Optional[List[str]]  = None
    description:    Optional[str]        = None
    amount_usd:     Optional[float]      = None
    incident_date:  Optional[str]        = None


class ExportBundleRequest(BaseModel):
    report_ids: List[str]


# ── Victim Reports ─────────────────────────────────────────────────────────────

@router.post("/victim-reports")
def submit_victim_report(req: SubmitReportRequest):
    if req.scam_type not in vr.SCAM_TYPES:
        raise HTTPException(400, f"Unknown scam_type '{req.scam_type}'")
    if not req.scammer_address.strip():
        raise HTTPException(400, "scammer_address is required")
    try:
        report = vr.submit_report(
            scam_type=req.scam_type,
            scammer_address=req.scammer_address,
            chain=req.chain,
            victim_address=req.victim_address,
            amount_usd=req.amount_usd,
            token=req.token,
            incident_date=req.incident_date,
            description=req.description,
            contact_name=req.contact_name,
            contact_email=req.contact_email,
            jurisdiction=req.jurisdiction,
            tx_hashes=req.tx_hashes,
            tags=req.tags,
            case_id=req.case_id,
        )
        return {"status": "ok", "report": report}
    except Exception as e:
        logger.exception("submit_report error")
        raise HTTPException(500, str(e))


@router.get("/victim-reports")
def list_victim_reports(
    scammer_address: str = Query(""),
    scam_type:       str = Query(""),
    status:          str = Query(""),
    case_id:         str = Query(""),
    chain:           str = Query(""),
    limit:  int = Query(100, le=500),
    offset: int = Query(0,   ge=0),
):
    return vr.list_reports(
        scammer_address=scammer_address,
        scam_type=scam_type,
        status=status,
        case_id=case_id,
        chain=chain,
        limit=limit,
        offset=offset,
    )


@router.get("/victim-reports/{report_id}")
def get_victim_report(report_id: str):
    report = vr.get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return {"status": "ok", "report": report}


_CONFIRMED_STATUSES = {"under_review", "escalated", "referred"}


def _feed_attribution_engine(report: dict, actor: str = "analyst") -> Optional[dict]:
    """
    Label-database growth loop: a vetted victim report becomes a provenance-
    tracked 'scam' attribution on the scammer address (source = the report id).
    Deduped inside the attribution engine on (address, source, label).
    """
    try:
        import attribution_engine as ae
        scam_type = report.get("scam_type", "scam")
        result = ae.bulk_import(
            [{
                "address": report.get("scammer_address", ""),
                "chain": report.get("chain", ""),
                "category": "scam",
                "label": f"Victim-reported: {scam_type.replace('_', ' ')}",
                "confidence": 0.75,
                "note": f"Confirmed victim report; damage ≈ ${report.get('amount_usd', 0):,.0f}",
                "evidence": [{
                    "type": "victim_report",
                    "value": f"victim-report:{report.get('id', '')}",
                    "ref": (report.get("tx_hashes") or [""])[0],
                }],
            }],
            source=f"victim-report:{report.get('id', '')}",
            assigned_by=actor,
            method="victim_report_confirmed",
            method_class="analyst",
            default_confidence=0.75,
        )
        return result
    except Exception:  # noqa: BLE001 — the growth loop must never block report updates
        logger.exception("attribution feed failed for victim report %s", report.get("id"))
        return None


@router.patch("/victim-reports/{report_id}")
def update_victim_report(report_id: str, req: UpdateReportRequest):
    if not vr.get_report(report_id):
        raise HTTPException(404, "Report not found")
    if req.status and req.status not in vr.REPORT_STATUSES:
        raise HTTPException(400, f"Invalid status '{req.status}'")
    updated = vr.update_report(report_id, **req.dict(exclude_none=True))
    attribution_feed = None
    if req.status in _CONFIRMED_STATUSES:
        attribution_feed = _feed_attribution_engine(updated)
    return {"status": "ok", "report": updated, "attribution_feed": attribution_feed}


@router.post("/victim-reports/{report_id}/confirm-label")
def confirm_victim_label(report_id: str, actor: str = "analyst"):
    """Explicitly push this report's scammer address into the attribution engine."""
    report = vr.get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    result = _feed_attribution_engine(report, actor=actor)
    if result is None:
        raise HTTPException(500, "Attribution feed failed")
    return {"status": "ok", "attribution_feed": result}


@router.delete("/victim-reports/{report_id}")
def delete_victim_report(report_id: str):
    if not vr.delete_report(report_id):
        raise HTTPException(404, "Report not found")
    return {"status": "ok"}


# ── Scam Intelligence ─────────────────────────────────────────────────────────

@router.get("/scam-intel/summary")
def scam_intel_summary():
    return {"status": "ok", **vr.scam_intelligence_summary()}


@router.get("/scam-intel/clusters")
def scam_clusters(
    min_victims: int = Query(1, ge=1),
    scam_type:   str = Query(""),
    limit:       int = Query(50, le=200),
):
    clusters = vr.list_scam_clusters(
        min_victims=min_victims, scam_type=scam_type, limit=limit
    )
    return {"status": "ok", "clusters": clusters, "count": len(clusters)}


@router.get("/scam-intel/address/{address}")
def scam_intel_address(address: str):
    return {"status": "ok", "intel": vr.get_scam_intel(address)}


@router.post("/scam-intel/export")
def export_bundle(req: ExportBundleRequest):
    if not req.report_ids:
        raise HTTPException(400, "report_ids required")
    bundle = vr.export_report_bundle(req.report_ids)
    if "error" in bundle:
        raise HTTPException(404, bundle["error"])
    return {"status": "ok", "bundle": bundle}


@router.get("/scam-intel/scam-types")
def list_scam_types():
    return {"scam_types": [{"id": k, **v} for k, v in vr.SCAM_TYPES.items()]}
