"""
V2 Features router — wires up all new investigation features.

Endpoints:
  F2 Graph store:        /api/investigations/*
  F3 Export engine:      /api/exports/*
  F4 Feed sync:          /api/feeds/*
  F5 Feed ingestion:     /api/ingestion/*
  F6 DeFi trackers:      /api/defi/*
  F7 Entity investigation: /api/entity/*
  F8 Time-travel:        /api/timetravel/*
  F9 Deep chain fetchers: /api/deeptrace/*
  F10 Case QA (RAG):     /api/case-qa/*
  F11 Custody audit:     /api/custody/*
  F12 Collaboration:     /api/collaboration/*
  F14 Victim portal:     /api/portal/*  (public — bypasses auth)
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

router = APIRouter(tags=["V2 Features"])


# ════════════════════════════════════════════════════════════════════════════
# F2: GRAPH PERSISTENCE & INCREMENTAL INVESTIGATION
# ════════════════════════════════════════════════════════════════════════════

class SaveInvestigationRequest(BaseModel):
    subject: str
    chain: str = ""
    graph: dict
    name: str = ""
    case_id: str = ""
    params: dict = {}


class ExpandInvestigationRequest(BaseModel):
    new_graph: dict


@router.post("/investigations")
async def save_investigation(req: SaveInvestigationRequest):
    import graph_store
    return graph_store.save_investigation(
        req.subject, req.chain, req.graph, req.name, req.case_id, req.params
    )


@router.get("/investigations")
async def list_investigations(case_id: str = "", limit: int = 50):
    import graph_store
    return {"investigations": graph_store.list_investigations(case_id, limit)}


@router.get("/investigations/{inv_id}")
async def get_investigation(inv_id: str):
    import graph_store
    inv = graph_store.get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return inv


@router.get("/investigations/by-subject/{address}")
async def find_investigation_by_subject(address: str, chain: str = ""):
    import graph_store
    inv = graph_store.find_by_subject(address, chain)
    if not inv:
        raise HTTPException(status_code=404, detail="No saved investigation for this address")
    return inv


@router.post("/investigations/{inv_id}/expand")
async def expand_investigation(inv_id: str, req: ExpandInvestigationRequest):
    import graph_store
    try:
        return graph_store.expand_investigation(inv_id, req.new_graph)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/investigations/{inv_id}/snapshot")
async def snapshot_investigation(inv_id: str, note: str = ""):
    import graph_store
    try:
        return graph_store.snapshot_investigation(inv_id, note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/investigations/{inv_id}/snapshots")
async def list_snapshots(inv_id: str):
    import graph_store
    return {"snapshots": graph_store.list_snapshots(inv_id)}


@router.get("/investigations/{inv_id}/diff")
async def diff_snapshots(inv_id: str, older: str, newer: str = ""):
    import graph_store
    try:
        return graph_store.diff_snapshots(inv_id, older, newer)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/investigations/{inv_id}")
async def delete_investigation(inv_id: str):
    import graph_store
    if not graph_store.delete_investigation(inv_id):
        raise HTTPException(status_code=404, detail="Investigation not found")
    return {"deleted": True}


# ════════════════════════════════════════════════════════════════════════════
# F3: EXPORT ENGINE (PDF / DOCX / FinCEN XML / STIX / MISP)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/exports/capabilities")
async def export_capabilities():
    import export_engine
    return export_engine.capabilities()


class PdfExportRequest(BaseModel):
    html_content: str
    title: str = "CrypTX Report"
    case_id: str = ""
    subject: str = ""


@router.post("/exports/pdf")
async def export_pdf(req: PdfExportRequest):
    import export_engine
    try:
        pdf_bytes, engine = export_engine.export_pdf(req.html_content, req.title)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    artifact_id = export_engine.save_export_artifact(
        req.case_id, req.subject, req.title, "pdf", pdf_bytes
    )
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={req.title}.pdf",
                 "X-Artifact-Id": artifact_id, "X-PDF-Engine": engine},
    )


class DocxExportRequest(BaseModel):
    case_id: str = ""
    report_data: dict = {}
    title: str = "CrypTX Report"


@router.post("/exports/docx")
async def export_docx(req: DocxExportRequest):
    import export_engine, database as db
    case_data = db.get_case(req.case_id) if req.case_id else {"name": req.title}
    if case_data is None:
        raise HTTPException(status_code=404, detail=f"case '{req.case_id}' not found")
    try:
        docx_bytes = export_engine.export_docx(case_data, req.report_data, req.title)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    artifact_id = export_engine.save_export_artifact(
        req.case_id, "", req.title, "docx", docx_bytes
    )
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={req.title}.docx",
                 "X-Artifact-Id": artifact_id},
    )


class FinCenExportRequest(BaseModel):
    payload: dict


@router.post("/exports/fincen-xml")
async def export_fincen_xml(req: FinCenExportRequest):
    import export_engine
    xml = export_engine.export_fincen_xml(req.payload)
    artifact_id = export_engine.save_export_artifact(
        req.payload.get("case_id", ""), req.payload.get("subject", {}).get("address", ""),
        f"FinCEN {req.payload.get('form_type', 'SAR')}", "xml", b"", content_text=xml
    )
    return Response(
        content=xml, media_type="application/xml",
        headers={"Content-Disposition": "attachment; filename=fincen_report.xml",
                 "X-Artifact-Id": artifact_id},
    )


class StixExportRequest(BaseModel):
    case_id: str
    addresses: list[dict] = []
    indicators: list[dict] = []


@router.post("/exports/stix")
async def export_stix(req: StixExportRequest):
    import export_engine, database as db
    case_data = db.get_case(req.case_id) or {"name": "CrypTX export"}
    addresses = req.addresses or (case_data.get("addresses") or [])
    bundle = export_engine.export_stix(case_data, addresses, req.indicators)
    return bundle


class MispExportRequest(BaseModel):
    case_id: str
    addresses: list[dict] = []
    tags: list[str] = []


@router.post("/exports/misp")
async def export_misp(req: MispExportRequest):
    import export_engine, database as db
    case_data = db.get_case(req.case_id) or {"name": "CrypTX export"}
    addresses = req.addresses or (case_data.get("addresses") or [])
    return export_engine.export_misp(case_data, addresses, req.tags)


# ════════════════════════════════════════════════════════════════════════════
# F4: FEED SYNC (sanctions auto-refresh + diff-alerts)
# ════════════════════════════════════════════════════════════════════════════

@router.post("/feeds/sync")
async def sync_feeds():
    import feed_sync
    return await feed_sync.sync_all_feeds()


@router.get("/feeds/status")
async def feed_status():
    import feed_sync
    return {"feeds": feed_sync.feed_status()}


@router.get("/feeds/search")
async def search_feeds(address: str = "", chain: str = "", designation: str = "", limit: int = 100):
    import feed_sync
    return {"records": feed_sync.search_feed_records(address, chain, designation, limit)}


@router.get("/feeds/diff-alerts")
async def diff_alerts(reviewed: Optional[bool] = None, case_id: str = "", limit: int = 50):
    import feed_sync
    return {"alerts": feed_sync.diff_alerts(reviewed, case_id, limit)}


@router.post("/feeds/diff-alerts/{alert_id}/review")
async def review_diff_alert(alert_id: str):
    import feed_sync
    if not feed_sync.review_diff_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"reviewed": True}


# ════════════════════════════════════════════════════════════════════════════
# F5: FEED INGESTION (known-bad address pipeline)
# ════════════════════════════════════════════════════════════════════════════

class ImportCsvRequest(BaseModel):
    source: str
    csv_content: str
    filename: str = ""
    column_map: Optional[dict] = None


class ImportJsonRequest(BaseModel):
    source: str
    json_content: str
    filename: str = ""


class ReviewRequest(BaseModel):
    row_ids: list[int]
    action: str   # approve | reject


@router.post("/ingestion/import-csv")
async def import_csv(req: ImportCsvRequest, request: Request):
    import feed_ingestion
    user = getattr(request.state, "user", {}) if hasattr(request, "state") else {}
    try:
        return feed_ingestion.import_csv(req.source, req.csv_content, req.filename,
                                          user.get("email", "system"), req.column_map)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ingestion/import-json")
async def import_json(req: ImportJsonRequest, request: Request):
    import feed_ingestion
    user = getattr(request.state, "user", {}) if hasattr(request, "state") else {}
    try:
        return feed_ingestion.import_json(req.source, req.json_content, req.filename,
                                           user.get("email", "system"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ingestion/imports")
async def list_imports(status: str = "", limit: int = 50):
    import feed_ingestion
    return {"imports": feed_ingestion.list_imports(status, limit),
            "sources": feed_ingestion.VALID_SOURCES}


@router.get("/ingestion/imports/{import_id}")
async def get_import(import_id: str, include_rows: bool = True, row_status: str = "", limit: int = 200):
    import feed_ingestion
    try:
        return feed_ingestion.get_import(import_id, include_rows, row_status, limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/ingestion/imports/{import_id}/review")
async def review_import(import_id: str, req: ReviewRequest, request: Request):
    import feed_ingestion
    user = getattr(request.state, "user", {}) if hasattr(request, "state") else {}
    try:
        return feed_ingestion.review_rows(import_id, req.row_ids, req.action,
                                           user.get("email", "analyst"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# F6: DEFI TRACKERS (stablecoin freeze + exploit detection)
# ════════════════════════════════════════════════════════════════════════════

class DefiAnalyzeRequest(BaseModel):
    tx_list: list[dict]
    subject: str = ""
    trackers: list[str] = ["all"]   # all | stablecoin | flashloan | rugpull | mev


@router.post("/defi/analyze")
async def defi_analyze(req: DefiAnalyzeRequest):
    import defi_trackers
    trackers = req.trackers or ["all"]
    if "all" in trackers:
        return defi_trackers.analyze_all(req.tx_list, req.subject)
    result = {}
    if "stablecoin" in trackers:
        result["stablecoin_actions"] = defi_trackers.detect_stablecoin_actions(req.tx_list, req.subject)
    if "flashloan" in trackers:
        result["flash_loan_attacks"] = defi_trackers.detect_flash_loan_attack(req.tx_list)
    if "rugpull" in trackers:
        result["rug_pulls"] = defi_trackers.detect_rug_pull(req.tx_list)
    if "mev" in trackers:
        result["mev_bots"] = defi_trackers.detect_mev_sandwich(req.tx_list)
    return result


# ════════════════════════════════════════════════════════════════════════════
# F7: ENTITY INVESTIGATION (multi-address)
# ════════════════════════════════════════════════════════════════════════════

class EntityInvestigationRequest(BaseModel):
    addresses: list[str]
    chain: str = ""


@router.post("/entity/investigate")
async def entity_investigate(req: EntityInvestigationRequest):
    import entity_investigation
    return await entity_investigation.investigate_entity(req.addresses, req.chain)


# ════════════════════════════════════════════════════════════════════════════
# F8: TIME-TRAVEL (historical state)
# ════════════════════════════════════════════════════════════════════════════

class TimeTravelRequest(BaseModel):
    tx_list: list[dict]
    address: str
    chain: str = ""
    target_timestamp: Optional[float] = None
    target_date: str = ""   # ISO date string alternative
    intervals: int = 12


@router.post("/timetravel/reconstruct")
async def timetravel_reconstruct(req: TimeTravelRequest):
    import time_travel
    target = req.target_timestamp
    if not target and req.target_date:
        from datetime import datetime
        try:
            target = datetime.fromisoformat(req.target_date.replace("Z", "+00:00")).timestamp()
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid target_date format")
    if target is None:
        raise HTTPException(status_code=400, detail="target_timestamp or target_date required")
    return time_travel.reconstruct_at_timestamp(req.tx_list, target, req.address, req.chain)


@router.post("/timetravel/evolution")
async def timetravel_evolution(req: TimeTravelRequest):
    import time_travel
    return time_travel.timeline_evolution(req.tx_list, req.address, req.chain, req.intervals)


# ════════════════════════════════════════════════════════════════════════════
# F9: DEEP CHAIN FETCHERS (BTC UTXO + Solana SPL)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/deeptrace/btc/{address}")
async def deeptrace_btc(address: str, hops: int = 3, max_nodes: int = 50):
    import deep_chain_fetchers
    return await deep_chain_fetchers.btc_deep_trace(address, hops, max_nodes)


@router.get("/deeptrace/sol/{address}")
async def deeptrace_sol(address: str, max_txs: int = 30):
    import deep_chain_fetchers
    return await deep_chain_fetchers.sol_deep_trace(address, max_txs)


# ════════════════════════════════════════════════════════════════════════════
# F10: CASE QA (RAG over evidence)
# ════════════════════════════════════════════════════════════════════════════

class CaseQARequest(BaseModel):
    question: str


@router.post("/case-qa/{case_id}/ask")
async def case_qa_ask(case_id: str, req: CaseQARequest, request: Request):
    import case_qa
    import tenancy
    user = getattr(request.state, "user", {}) if hasattr(request, "state") else {}
    try:
        tenancy.guard_case(case_id, user)
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        return await case_qa.answer_case_question(case_id, req.question, user.get("email", "analyst"))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# F11: CUSTODY AUDIT REPORT
# ════════════════════════════════════════════════════════════════════════════

@router.get("/custody/{case_id}")
async def custody_report(case_id: str, request: Request):
    import custody_audit
    import tenancy
    try:
        tenancy.guard_case(case_id, getattr(request.state, "user", None) or {})
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        return custody_audit.generate_custody_report(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/custody/{case_id}/html", response_class=HTMLResponse)
async def custody_report_html(case_id: str, request: Request):
    import custody_audit
    import tenancy
    try:
        tenancy.guard_case(case_id, getattr(request.state, "user", None) or {})
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        return HTMLResponse(content=custody_audit.custody_report_html(case_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# F12: COLLABORATION (presence)
# ════════════════════════════════════════════════════════════════════════════

class JoinRoomRequest(BaseModel):
    room_id: str
    user_name: str = ""


class HeartbeatRequest(BaseModel):
    room_id: str
    cursor: Optional[dict] = None
    panel: str = ""


@router.post("/collaboration/join")
async def collab_join(req: JoinRoomRequest, request: Request):
    import collaboration
    user = getattr(request.state, "user", {})
    uid = user.get("id") or user.get("email", "anon")
    collaboration.join_room(req.room_id, uid, req.user_name)
    return {"joined": req.room_id, "presence": collaboration.get_room_presence(req.room_id)}


@router.post("/collaboration/heartbeat")
async def collab_heartbeat(req: HeartbeatRequest, request: Request):
    import collaboration
    user = getattr(request.state, "user", {})
    uid = user.get("id") or user.get("email", "anon")
    return {"presence": collaboration.heartbeat(req.room_id, uid, req.cursor, req.panel)}


@router.post("/collaboration/leave")
async def collab_leave(req: JoinRoomRequest, request: Request):
    import collaboration
    user = getattr(request.state, "user", {})
    uid = user.get("id") or user.get("email", "anon")
    collaboration.leave_room(req.room_id, uid)
    return {"left": req.room_id}


@router.get("/collaboration/rooms")
async def collab_rooms():
    import collaboration
    return {"rooms": collaboration.list_active_rooms()}


class CaseLockRequest(BaseModel):
    case_id: str


@router.post("/collaboration/lock")
async def collab_lock(req: CaseLockRequest, request: Request):
    import collaboration
    user = getattr(request.state, "user", {})
    uid = user.get("id") or user.get("email", "anon")
    acquired = collaboration.acquire_case_lock(req.case_id, uid)
    return {"acquired": acquired, "held_by": collaboration.case_lock_holder(req.case_id)}


@router.post("/collaboration/unlock")
async def collab_unlock(req: CaseLockRequest, request: Request):
    import collaboration
    user = getattr(request.state, "user", {})
    uid = user.get("id") or user.get("email", "anon")
    collaboration.release_case_lock(req.case_id, uid)
    return {"released": True}


# ════════════════════════════════════════════════════════════════════════════
# F14: VICTIM INTAKE PORTAL (PUBLIC — bypasses auth)
# ════════════════════════════════════════════════════════════════════════════

class PublicVictimReportRequest(BaseModel):
    scam_type: str
    scammer_address: str
    victim_address: str = ""
    amount_usd: float = 0
    token: str = "Unknown"
    chain: str = "ETH"
    incident_date: str = ""
    description: str = ""
    contact_name: str = ""
    contact_email: str = ""
    jurisdiction: str = ""
    tx_hashes: list[str] = []


@router.post("/portal/victim-report")
async def public_victim_report(req: PublicVictimReportRequest):
    """Public (no-auth) victim intake endpoint. Creates a report + auto-enriches."""
    import victim_report
    victim_report.init_victim_tables()
    # If the scammer address already appears in an open case, auto-link the report to it
    linked_case_id = ""
    try:
        import database as db
        with db.get_connection() as con:
            case_addr = con.execute(
                "SELECT case_id FROM case_addresses WHERE address=? LIMIT 1",
                (req.scammer_address.lower(),),
            ).fetchone()
            if case_addr:
                linked_case_id = case_addr["case_id"]
    except Exception:
        pass
    result = victim_report.submit_report(
        scam_type=req.scam_type,
        scammer_address=req.scammer_address,
        victim_address=req.victim_address,
        amount_usd=req.amount_usd,
        token=req.token,
        chain=req.chain,
        incident_date=req.incident_date,
        description=req.description,
        contact_name=req.contact_name,
        contact_email=req.contact_email,
        jurisdiction=req.jurisdiction,
        tx_hashes=req.tx_hashes,
        case_id=linked_case_id,
    )
    report_id = result.get("id") if isinstance(result, dict) else str(result)
    return {"report_id": report_id, "status": "received", "linked_case_id": linked_case_id,
            "message": "Your report has been received. An analyst will review it."}


@router.get("/portal/scam-stats")
async def public_scam_stats():
    """Public aggregate scam statistics (no PII) for the intake portal."""
    import victim_report, database as db
    victim_report.init_victim_tables()
    with db.get_connection() as con:
        total = con.execute("SELECT COUNT(*) FROM victim_reports").fetchone()[0]
        total_usd = con.execute("SELECT COALESCE(SUM(amount_usd),0) FROM victim_reports").fetchone()[0]
        by_type = con.execute(
            "SELECT scam_type, COUNT(*) as c FROM victim_reports GROUP BY scam_type ORDER BY c DESC LIMIT 10"
        ).fetchall()
    return {
        "total_reports": total,
        "total_damage_usd": round(total_usd, 2),
        "top_scam_types": [{"type": r["scam_type"], "count": r["c"]} for r in by_type],
        "scam_types": list(victim_report.SCAM_TYPES.keys()),
    }
