"""
Regulatory reporting + Know-Your-VASP router.
  POST /api/regulatory/sar           generate a Suspicious Activity Report (draft)
  POST /api/regulatory/ctr           generate a Currency Transaction Report (draft)
  POST /api/regulatory/travel-rule   generate a Travel Rule message (draft)
  GET  /api/kyv/{address}            identify VASP for an address
  POST /api/kyv                      add a VASP address mapping
  GET  /api/kyv                      list known VASPs
  GET  /api/regulatory/sar-categories  SAR activity category options
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

import regulatory_reports
import vasp_directory

router = APIRouter(tags=["Regulatory & KYV"])


class GenericReportRequest(BaseModel):
    payload: dict[str, Any]


class AddVaspRequest(BaseModel):
    address: str
    vasp_name: str
    vasp_type: str = "exchange"
    chain: str = ""
    country: str = ""
    jurisdiction: str = ""
    label: str = ""


def _register_draft(kind: str, payload: dict, result: dict) -> dict:
    """Chain-of-custody: register regulatory drafts in the evidence vault when a case_id is supplied."""
    case_id = str(payload.get("case_id") or "").strip()
    if not case_id:
        return result
    try:
        import evidence_vault
        record = evidence_vault.register_export(
            case_id=case_id,
            kind="regulatory_export",
            title=f"{kind} draft — {payload.get('subject_address', payload.get('address', ''))}",
            content=result,
            subject=str(payload.get("subject_address") or payload.get("address") or ""),
            actor=str(payload.get("actor") or "analyst"),
        )
        result["custody"] = {
            "evidence_id": record.get("id"),
            "content_hash": record.get("content_hash"),
            "chain_hash": record.get("chain_hash"),
            "registered_at": record.get("created_at"),
        }
    except Exception:  # noqa: BLE001 — custody registration must never block report generation
        result["custody"] = {"error": "custody registration failed (is the case_id valid?)"}
    return result


@router.post("/regulatory/sar")
async def sar(req: GenericReportRequest):
    try:
        return _register_draft("SAR", req.payload, regulatory_reports.generate_sar(req.payload))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"SAR generation failed: {exc}")


@router.post("/regulatory/ctr")
async def ctr(req: GenericReportRequest):
    try:
        return _register_draft("CTR", req.payload, regulatory_reports.generate_ctr(req.payload))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"CTR generation failed: {exc}")


@router.post("/regulatory/travel-rule")
async def travel_rule(req: GenericReportRequest):
    try:
        return _register_draft("Travel Rule", req.payload, regulatory_reports.generate_travel_rule(req.payload))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Travel Rule generation failed: {exc}")


@router.get("/regulatory/sar-categories")
async def sar_categories():
    return {"categories": regulatory_reports.SAR_ACTIVITY_CATEGORIES}


@router.get("/kyv/{address}")
async def kyv_lookup(address: str, chain: Optional[str] = None):
    return vasp_directory.identify_vasp(address, chain)


@router.post("/kyv")
async def kyv_add(req: AddVaspRequest):
    try:
        return vasp_directory.add_vasp(
            req.address, req.vasp_name, req.vasp_type, req.chain,
            req.country, req.jurisdiction, req.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/kyv")
async def kyv_list():
    return vasp_directory.list_vasps()


@router.get("/kyv/dossier/{vasp_name}")
async def kyv_dossier(vasp_name: str):
    """
    VASP due-diligence dossier: jurisdiction, known addresses, sanctions and
    attribution exposure, and a draft risk assessment — built entirely from
    local data (KYV directory, sanctions engine, attribution engine).
    """
    import sqlite3
    from pathlib import Path

    q = vasp_name.strip().lower()
    if not q:
        raise HTTPException(status_code=400, detail="vasp_name is required")

    import config as _config
    db_path = _config.DB_PATH
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM vasp_directory WHERE LOWER(vasp_name) LIKE ? ORDER BY vasp_name, chain",
            (f"%{q}%",),
        ).fetchall()]
    finally:
        con.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No VASP matching '{vasp_name}' in the KYV directory")

    # Group by exact VASP name (query may match several)
    name = rows[0]["vasp_name"]
    entries = [r for r in rows if r["vasp_name"] == name]
    addresses = [{"address": r["address"], "chain": r["chain"], "label": r["label"], "source": r["source"]} for r in entries]

    # Exposure screening (local, cheap)
    import sanctions_engine
    import attribution_engine
    sanctioned, flagged = [], []
    for a in addresses[:50]:
        try:
            scr = sanctions_engine.screen_address(a["address"], a["chain"] or None)
            if scr.get("sanctioned") or scr.get("matches"):
                sanctioned.append({"address": a["address"], "detail": scr.get("matches", [])[:2]})
        except Exception:  # noqa: BLE001
            pass
        try:
            attr = attribution_engine.attribute(a["address"], a["chain"] or None)
            bad = [x for x in attr.get("attributions", []) if x.get("category") in ("mixer", "scam", "darknet", "ransomware", "sanctioned")]
            if bad:
                flagged.append({"address": a["address"], "categories": sorted({x["category"] for x in bad})})
        except Exception:  # noqa: BLE001
            pass

    risk = "LOW"
    reasons = []
    if sanctioned:
        risk = "CRITICAL"
        reasons.append(f"{len(sanctioned)} directory address(es) match sanctions data")
    elif flagged:
        risk = "HIGH"
        reasons.append(f"{len(flagged)} address(es) carry high-risk attributions")
    if not entries[0].get("jurisdiction") and not entries[0].get("country"):
        if risk == "LOW":
            risk = "MEDIUM"
        reasons.append("No jurisdiction on record — licensing status unverified")
    if not reasons:
        reasons.append("No adverse local intelligence on directory addresses")

    dossier = {
        "vasp_name": name,
        "vasp_type": entries[0]["vasp_type"],
        "country": entries[0]["country"],
        "jurisdiction": entries[0]["jurisdiction"],
        "address_count": len(addresses),
        "chains": sorted({a["chain"] for a in addresses if a["chain"]}),
        "addresses": addresses,
        "sanctions_exposure": sanctioned,
        "high_risk_attributions": flagged,
        "risk_level": risk,
        "risk_reasons": reasons,
        "disclaimer": "Draft due-diligence dossier from local intelligence only. Verify licensing/registration with the competent regulator before relying on this assessment.",
    }
    md = [
        f"# VASP Due-Diligence Dossier — {name}",
        "",
        f"**Type:** {dossier['vasp_type']}  |  **Country:** {dossier['country'] or 'unknown'}  |  **Jurisdiction:** {dossier['jurisdiction'] or 'unknown'}",
        f"**Risk assessment:** {risk} — {'; '.join(reasons)}",
        "",
        f"## Known addresses ({len(addresses)})",
        *[f"- `{a['address']}` ({a['chain'] or '?'}) {a['label']}" for a in addresses[:30]],
        "",
        f"_{dossier['disclaimer']}_",
    ]
    dossier["markdown"] = "\n".join(md)
    return dossier
