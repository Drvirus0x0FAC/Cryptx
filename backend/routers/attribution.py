"""
Attribution router — deterministic, provenance-tracked address attribution.
  GET  /api/attribution/methods         method-class + source catalog
  GET  /api/attribution/{address}       aggregated, court-defensible attribution record
  GET  /api/attribution/{address}/audit full provenance/audit trail (incl. revoked)
  POST /api/attribution                 add an analyst attribution (with provenance)
  POST /api/attribution/revoke/{id}     revoke an analyst attribution
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Any, Optional

import attribution_engine as ae

router = APIRouter(tags=["Attribution"])


class AddAttributionRequest(BaseModel):
    address: str
    category: str = "unknown"
    actor: str = ""
    label: str = ""
    source: str = ""
    confidence: float = 0.6
    evidence: list[dict[str, Any]] = []
    chain: str = ""
    assigned_by: str = "analyst"
    method_class: str = "analyst"
    method: str = "analyst_assertion"
    note: str = ""


@router.get("/attribution/methods")
async def methods():
    return ae.methods_catalog()


@router.get("/attribution/{address}")
async def get_attribution(address: str, chain: Optional[str] = None):
    if not address.strip():
        raise HTTPException(status_code=400, detail="address is required")
    return ae.attribute(address.strip(), chain)


@router.get("/attribution/{address}/audit")
async def get_audit(address: str):
    return ae.audit(address.strip())


@router.post("/attribution")
async def add_attribution(req: AddAttributionRequest):
    try:
        return ae.add_attribution(
            req.address, category=req.category, actor=req.actor, label=req.label,
            source=req.source, confidence=req.confidence, evidence=req.evidence,
            chain=req.chain, assigned_by=req.assigned_by, method_class=req.method_class,
            method=req.method, note=req.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/attribution/revoke/{attr_id}")
async def revoke(attr_id: str, revoked_by: str = "analyst"):
    return ae.revoke_attribution(attr_id, revoked_by)


# ── Label-database growth loop ────────────────────────────────────────────────

class BulkImportRequest(BaseModel):
    items: list[dict[str, Any]]
    source: str = "manual_import"
    method_class: str = "deterministic"
    default_confidence: float = 0.9
    assigned_by: str = "import"


@router.post("/attribution/import")
async def bulk_import(req: BulkImportRequest):
    """Bulk-import labels (Dune exports, GitHub label repos, CSV conversions…) with provenance."""
    if not req.items:
        raise HTTPException(status_code=400, detail="items is empty")
    if len(req.items) > 50_000:
        raise HTTPException(status_code=400, detail="max 50,000 items per import")
    try:
        return ae.bulk_import(
            req.items, source=req.source, assigned_by=req.assigned_by,
            method_class=req.method_class, default_confidence=req.default_confidence,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"import failed: {exc}")


@router.post("/attribution/import/ofac")
async def import_ofac():
    """Import the bundled OFAC SDN digital-currency address list (deterministic, evidence-cited)."""
    import csv
    from pathlib import Path

    csv_path = Path(__file__).resolve().parent.parent.parent / "python-modules" / "ofac_crypto_addresses.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"OFAC CSV not found at {csv_path}")

    items: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            addr = (row.get("address") or "").strip()
            if not addr:
                continue
            id_type = row.get("id_type") or ""
            chain = id_type.rsplit("-", 1)[-1].strip() if "-" in id_type else ""
            items.append({
                "address": addr,
                "chain": chain,
                "category": "sanctioned",
                "actor": (row.get("name") or "")[:200],
                "label": f"OFAC SDN: {(row.get('name') or 'listed party')[:120]}",
                "confidence": 1.0,
                "note": (row.get("program") or "")[:200],
                "evidence": [{"type": "sanctions_listing", "value": f"SDN uid {row.get('uid', '')}",
                              "ref": row.get("remarks", "")[:300]}],
            })
    result = ae.bulk_import(items, source="OFAC SDN CSV", method="ofac_sdn_csv",
                            method_class="deterministic", default_confidence=1.0)
    result["rows_in_file"] = len(items)
    return result


# ── Unified entity search (labels + attribution + KYV + sanctions) ───────────

@router.get("/entity/search")
async def entity_search(q: str, limit: int = 20):
    """Fast unified entity search: 'Binance', 'Lazarus', 'tornado'… across all local intelligence."""
    query = q.strip()
    if len(query) < 2:
        return {"query": q, "hits": []}
    hits: list[dict[str, Any]] = []

    for row in ae.search_entities(query, limit):
        hits.append({
            "kind": "attribution",
            "name": row.get("actor") or row.get("label"),
            "address": row.get("address"),
            "chain": row.get("chain"),
            "category": row.get("category"),
            "source": row.get("source"),
            "confidence": row.get("confidence"),
        })

    try:
        import sqlite3
        import config as _config
        con = sqlite3.connect(_config.DB_PATH)
        con.row_factory = sqlite3.Row
        try:
            for row in con.execute(
                "SELECT address, chain, vasp_name, vasp_type, country FROM vasp_directory"
                " WHERE LOWER(vasp_name) LIKE ? LIMIT ?", (f"%{query.lower()}%", limit),
            ).fetchall():
                hits.append({
                    "kind": "vasp",
                    "name": row["vasp_name"],
                    "address": row["address"],
                    "chain": row["chain"],
                    "category": row["vasp_type"],
                    "source": f"KYV directory ({row['country'] or 'jurisdiction unknown'})",
                    "confidence": 1.0,
                })
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        pass

    try:
        import sanctions_engine
        for m in (sanctions_engine.search_name(query, limit=limit).get("matches") or []):
            hits.append({
                "kind": "sanctions",
                "name": m.get("name") or m.get("entity_name"),
                "address": m.get("address", ""),
                "chain": m.get("chain", ""),
                "category": "sanctioned",
                "source": m.get("list") or m.get("source") or "sanctions",
                "confidence": m.get("score", 1.0),
            })
    except Exception:  # noqa: BLE001
        pass

    # Boards (investigation canvases) by name
    try:
        import boards_engine
        for b in boards_engine.search_boards(query, limit=8):
            hits.append({
                "kind": "board", "name": b.get("name"), "address": "",
                "chain": "", "category": "investigation board",
                "source": f"updated {b.get('updated_at', '')}", "confidence": 1.0,
                "ref": b.get("id"),
            })
    except Exception:  # noqa: BLE001
        pass

    # Cases by name
    try:
        import database
        for c in database.list_cases():
            if query.lower() in str(c.get("name", "")).lower():
                hits.append({
                    "kind": "case", "name": c.get("name"), "address": "",
                    "chain": "", "category": "case",
                    "source": f"{c.get('address_count', c.get('addresses', ''))} addresses",
                    "confidence": 1.0, "ref": c.get("id"),
                })
    except Exception:  # noqa: BLE001
        pass

    # Local labels
    try:
        import database
        for row in database.list_local_labels(query=query, limit=8):
            hits.append({
                "kind": "label", "name": row.get("label"), "address": row.get("address", ""),
                "chain": row.get("chain", ""), "category": row.get("category", "label"),
                "source": row.get("source") or "local label", "confidence": row.get("confidence", 0.8),
            })
    except Exception:  # noqa: BLE001
        pass

    # Dedupe by (kind, name, address)
    seen: set[tuple] = set()
    unique = []
    for h in hits:
        key = (h["kind"], str(h["name"]).lower(), h["address"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)

    return {"query": query, "hits": unique[: limit * 2]}


# ── Attribution submission workflow (label-growth loop) ──────────────────────

class SubmissionRequest(BaseModel):
    address: str
    chain: str = ""
    category: str = "unknown"
    actor: str = ""
    label: str = ""
    source: str = ""
    confidence: float = 0.6
    evidence: list[dict[str, Any]] = []
    note: str = ""


class ReviewRequest(BaseModel):
    action: str  # approve | reject
    review_note: str = ""


def _actor_name(request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("username") or user.get("email") or "analyst")


@router.post("/attribution-submissions")
async def submit_attribution(req: SubmissionRequest, request: Request):
    """Submit a new address→entity attribution for reviewer approval."""
    import attribution_workflow as aw
    try:
        return aw.submit(
            req.address, category=req.category, actor=req.actor, label=req.label,
            source=req.source, confidence=req.confidence, evidence=req.evidence,
            chain=req.chain, note=req.note, submitted_by=_actor_name(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/attribution-submissions")
async def list_submissions(status: str = "", address: str = "", limit: int = 200):
    import attribution_workflow as aw
    return {"submissions": aw.list_submissions(status, address, limit), "stats": aw.queue_stats()}


@router.post("/attribution-submissions/{sub_id}/review")
async def review_submission(sub_id: str, req: ReviewRequest, request: Request):
    """Approve (enters the attribution engine with provenance) or reject a submission."""
    import attribution_workflow as aw
    try:
        return aw.review(sub_id, req.action, reviewer=_actor_name(request), review_note=req.review_note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── Attribution Source Report (court methodology document) ───────────────────

@router.get("/attribution/{address}/source-report", response_class=HTMLResponse)
async def source_report(address: str, chain: Optional[str] = None):
    """Printable per-address methodology report: how every attribution was derived."""
    import attribution_workflow as aw
    if not address.strip():
        raise HTTPException(status_code=400, detail="address is required")
    return HTMLResponse(aw.build_source_report(address.strip(), chain))
