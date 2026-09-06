"""
Entity search + VASP dossier router — /api/entities

  GET  /api/entities/search?q=Binance        unified search across all sources
  GET  /api/entities/{entity_id}             full detail for one entity
  GET  /api/entities/vasp/{name}/dossier     VASP due-diligence dossier (P1.7)

The dossier is the QLUE "Entity Explorer" equivalent: a generated report per
VASP aggregating identity, jurisdiction/licensing, known addresses, sanctions
exposure, and risk — the kind of due-diligence document compliance teams buy.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from typing import Optional

import entity_search
import tenancy

router = APIRouter(prefix="/entities", tags=["Entity Search"])


def _user(request: Request) -> dict:
    return getattr(request.state, "user", None) or {}


# ── Unified search ──────────────────────────────────────────────────────────

@router.get("/search")
def search(q: str, limit: int = 20):
    """Unified entity search. Example: /api/entities/search?q=Lazarus"""
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="query must be at least 2 characters")
    return entity_search.search_entities(q.strip(), limit=min(max(limit, 1), 50))


@router.get("/{entity_id}")
def get_entity(entity_id: str):
    """Full detail for one entity (populates the address list for attributions)."""
    detail = entity_search.get_entity_detail(entity_id)
    if not detail:
        raise HTTPException(status_code=404, detail="entity not found")
    return detail


# ── VASP due-diligence dossier (P1.7) ───────────────────────────────────────

@router.get("/vasp/{name}/dossier")
def vasp_dossier(name: str, request: Request):
    """Generate a VASP due-diligence dossier.

    Aggregates: identity, jurisdiction/licensing, known addresses, sanctions
    exposure (any of the VASP's addresses sanctioned?), risk rating, and
    investigator notes. The QLUE "Entity Explorer" equivalent — sells to
    compliance teams, not just investigators.
    """
    import vasp_directory
    import sanctions_engine

    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="VASP name is required")

    # 1. Gather all known addresses for this VASP.
    addresses: list[dict] = []
    try:
        listing = vasp_directory.list_vasps()
        for v in listing.get("vasps", []):
            if (v.get("vasp_name") or "").lower() == name.lower():
                addresses.append({
                    "chain": v.get("chain") or "",
                    "address": v.get("address") or "",
                    "label": v.get("label") or "",
                })
    except Exception:
        pass

    if not addresses:
        raise HTTPException(status_code=404, detail=f"no VASP found named '{name}'")

    # 2. Identity + jurisdiction (from the first matching row).
    identity: dict = {}
    try:
        first = listing["vasps"][0] if listing.get("vasps") else {}
        identity = {
            "name": name,
            "type": first.get("vasp_type") or "exchange",
            "jurisdiction": first.get("jurisdiction") or "",
            "country": first.get("country") or "",
            "source": first.get("source") or "seed",
        }
    except Exception:
        identity = {"name": name, "type": "exchange", "jurisdiction": "", "country": ""}

    # 3. Sanctions exposure — screen every known address.
    sanctioned_addresses: list[dict] = []
    try:
        for addr in addresses:
            res = sanctions_engine.screen_address(addr["address"], addr.get("chain"))
            if res.get("hit") or res.get("matches"):
                sanctioned_addresses.append({
                    "address": addr["address"],
                    "chain": addr.get("chain", ""),
                    "matches": res.get("matches") or [],
                })
    except Exception:
        pass

    # 4. Risk rating.
    sanctioned = len(sanctioned_addresses) > 0
    if sanctioned:
        risk_level = "PROHIBITED"
        risk_score = 100
        risk_basis = "One or more known addresses appear on a sanctions list."
    else:
        # Heuristic: high-risk jurisdictions lower the rating.
        high_risk_jurisdictions = {"kp", "ir", "sy", "cu", "ve", "mm", "af"}
        risk_score = 15
        risk_basis = "No sanctions hits on known addresses."
        if (identity.get("country") or "").lower() in high_risk_jurisdictions:
            risk_score = 60
            risk_basis = "Registered in a high-risk jurisdiction; no sanctions hits."

    # 5. Attribution context (do our own attributions reference this VASP?).
    attribution_count = 0
    try:
        import attribution_engine
        for addr in addresses[:20]:  # cap the lookups
            attrs = attribution_engine.attribute(addr["address"], addr.get("chain"))
            attribution_count += len(attrs.get("attributions") or [])
    except Exception:
        pass

    dossier = {
        "entity": identity,
        "known_addresses": addresses,
        "address_count": len(addresses),
        "sanctions_screening": {
            "screened": len(addresses),
            "sanctioned_hits": len(sanctioned_addresses),
            "sanctioned_addresses": sanctioned_addresses,
        },
        "risk_assessment": {
            "level": "HIGH" if risk_score >= 70 else ("MEDIUM" if risk_score >= 40 else "LOW") if not sanctioned else "PROHIBITED",
            "score": risk_score,
            "basis": risk_basis,
            "sanctioned": sanctioned,
        },
        "attribution_references": attribution_count,
        "generated_at": _now_iso(),
        "disclaimer": (
            "This dossier is an investigative lead, not a legal determination. "
            "Sanctions screening is based on the bundled OFAC/OpenSanctions seed "
            "and any ingested feeds; verify against the authoritative source before "
            "any compliance filing or legal action."
        ),
    }
    return dossier


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
