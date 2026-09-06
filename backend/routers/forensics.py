"""
Local forensic analysis endpoints.
"""
import csv
import io
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import database as db
from forensic_engine import ALGORITHM_VERSION, analyze_forensics
from risk_engine import compute_risk_score
from report_builder import build_address_report, build_case_report

router = APIRouter(tags=["forensics"])


class ForensicRequest(BaseModel):
    address: str
    intel: Optional[Dict[str, Any]] = None
    trace_graph: Optional[Dict[str, Any]] = None
    dex_activity: Optional[Dict[str, Any]] = None
    persist: bool = True


class LocalLabelRequest(BaseModel):
    address: str
    chain: str = ""
    label: str
    category: str = ""
    risk_weight: int = 0
    confidence: float = 1.0
    source: str = "investigator"
    notes: str = ""


class LabelImportRequest(BaseModel):
    csv_text: str
    default_source: str = "csv_import"


@router.post("/forensics/analyze")
async def forensic_analyze(req: ForensicRequest):
    try:
        intel = req.intel
        if not intel:
            from crypto_osint import lookup_crypto_address
            intel = await lookup_crypto_address(req.address.strip())

        analysis = await run_in_threadpool(
            analyze_forensics,
            intel,
            trace_graph=req.trace_graph,
            dex_activity=req.dex_activity,
            local_labels=db.labels_for_address(
                intel.get("address", req.address.strip()),
                intel.get("chain", ""),
            ),
        )

        run_id = None
        if req.persist:
            evidence = analysis["evidence"]
            summary = analysis["summary"]
            run_id = await run_in_threadpool(
                db.save_forensic_run,
                subject=summary.get("address", req.address),
                chain=summary.get("chain", ""),
                summary=summary,
                addresses=evidence["addresses"],
                transactions=evidence["transactions"],
                edges=evidence["edges"],
                outputs=evidence["outputs"],
                algorithm_version=ALGORITHM_VERSION,
            )
        return {
            "run_id": run_id,
            "analysis": analysis["summary"],
        }
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"crypto_osint module unavailable: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/forensics/runs")
def forensic_runs(limit: int = 50):
    return {"runs": db.list_forensic_runs(max(1, min(limit, 200)))}


@router.get("/forensics/runs/{run_id}")
def forensic_run(run_id: str):
    run = db.get_forensic_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Forensic run not found")
    return run


@router.get("/forensics/runs/{run_id}/report", response_class=HTMLResponse)
def forensic_run_report(run_id: str):
    run = db.get_forensic_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Forensic run not found")
    analysis = run.get("summary") or {}
    risk = compute_risk_score({
        "address": analysis.get("address", run.get("subject", "")),
        "chain": analysis.get("chain", run.get("chain", "")),
        "forensic_analysis": analysis,
    })
    html = build_address_report(analysis, risk)
    db.save_report_artifact(
        subject=run.get("subject", ""),
        chain=run.get("chain", ""),
        title=f"Forensic Report - {run.get('subject', '')}",
        content=html,
        fmt="html",
    )
    return HTMLResponse(content=html)


@router.post("/labels")
def create_label(req: LocalLabelRequest):
    if not req.address.strip() or not req.label.strip():
        raise HTTPException(status_code=400, detail="address and label are required")
    return db.upsert_local_label(
        address=req.address.strip(),
        chain=req.chain.strip().upper(),
        label=req.label.strip(),
        category=req.category.strip(),
        risk_weight=max(0, min(req.risk_weight, 100)),
        confidence=max(0, min(req.confidence, 1)),
        source=req.source.strip() or "investigator",
        notes=req.notes.strip(),
    )


@router.get("/labels")
def list_labels(query: str = "", chain: str = "", limit: int = 200):
    return {
        "labels": db.list_local_labels(
            query=query.strip(),
            chain=chain.strip().upper(),
            limit=max(1, min(limit, 1000)),
        )
    }


@router.get("/labels/{address}")
def labels_for_address(address: str, chain: str = ""):
    return {"labels": db.labels_for_address(address.strip(), chain.strip().upper())}


@router.delete("/labels/{label_id}")
def delete_label(label_id: int):
    if not db.delete_local_label(label_id):
        raise HTTPException(status_code=404, detail="Label not found")
    return {"deleted": label_id}


@router.post("/labels/import")
def import_labels(req: LabelImportRequest):
    reader = csv.DictReader(io.StringIO(req.csv_text))
    imported = []
    required = {"address", "label"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(status_code=400, detail="CSV must include address and label columns")
    for row in reader:
        address = (row.get("address") or "").strip()
        label = (row.get("label") or "").strip()
        if not address or not label:
            continue
        imported.append(db.upsert_local_label(
            address=address,
            chain=(row.get("chain") or "").strip().upper(),
            label=label,
            category=(row.get("category") or "").strip(),
            risk_weight=max(0, min(int(float(row.get("risk_weight") or 0)), 100)),
            confidence=max(0, min(float(row.get("confidence") or 1), 1)),
            source=(row.get("source") or req.default_source or "csv_import").strip(),
            notes=(row.get("notes") or "").strip(),
        ))
    return {"imported": len(imported), "labels": imported}


@router.get("/cases/{case_id}/report", response_class=HTMLResponse)
def case_report(case_id: str):
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    runs = []
    for item in case.get("addresses") or []:
        run = db.latest_forensic_run(item.get("address", ""), item.get("chain", ""))
        if run:
            runs.append(run)
    html = build_case_report(case, runs)
    db.save_report_artifact(
        subject=case.get("name", case_id),
        case_id=case_id,
        title=f"Case Report - {case.get('name', case_id)}",
        content=html,
        fmt="html",
    )
    return HTMLResponse(content=html)
