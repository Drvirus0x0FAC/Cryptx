"""
Deterministic, provenance-tracked attribution engine.

Every attribution (label) on an address carries the four fields that make it
court-defensible rather than a black-box score:

    source     - WHERE the claim originates (OFAC SDN, VASP directory, an
                 analyst, an external feed)
    method     - HOW it was derived, classified as:
                   deterministic  (exact, reproducible match -> pinned confidence)
                   analyst        (human assertion, with attribution to the analyst)
                   heuristic      (probabilistic inference, clearly marked)
    confidence - 0.0-1.0
    evidence   - structured, citable evidence items ({type, value, ref})

`attribute()` aggregates all applicable attributions for an address from the
deterministic registries already in the platform (sanctions, VASP directory,
known bridge/DEX/mixer contracts) plus any analyst-contributed attributions
stored in the database, and reports whether the result is **court-defensible**
(at least one deterministic, high-confidence, evidence-backed attribution).

Deterministic attributions are recomputed live (reproducible); analyst
attributions are stored append-only with full provenance and an audit trail.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH

DETERMINISTIC = "deterministic"
ANALYST = "analyst"
HEURISTIC = "heuristic"
METHOD_CLASSES = (DETERMINISTIC, ANALYST, HEURISTIC)

# A category taxonomy shared across the platform.
CATEGORIES = (
    "sanctioned", "exchange", "mixer", "bridge", "dex", "darknet", "scam",
    "ransomware", "terrorist_financing", "gambling", "merchant", "contract", "unknown",
)

# Confidence threshold above which a deterministic, evidence-backed attribution
# is considered court-defensible.
COURT_CONFIDENCE = 0.95


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _addr(v: Any) -> str:
    return str(v or "").strip().lower()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_attribution_tables() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS attributions (
                id           TEXT PRIMARY KEY,
                address      TEXT NOT NULL,
                chain        TEXT DEFAULT '',
                category     TEXT DEFAULT 'unknown',
                actor        TEXT DEFAULT '',
                label        TEXT DEFAULT '',
                source       TEXT NOT NULL,
                method       TEXT NOT NULL,
                method_class TEXT NOT NULL DEFAULT 'analyst',
                confidence   REAL NOT NULL DEFAULT 0.5,
                evidence     TEXT DEFAULT '[]',
                assigned_by  TEXT DEFAULT 'analyst',
                assigned_at  TEXT NOT NULL,
                valid        INTEGER NOT NULL DEFAULT 1,
                note         TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_attr_address ON attributions(address);
            CREATE INDEX IF NOT EXISTS idx_attr_category ON attributions(category, valid);
            CREATE INDEX IF NOT EXISTS idx_attr_method_class ON attributions(method_class);
            """
        )
        con.commit()


def _attribution(
    category: str, actor: str, label: str, source: str, method: str,
    method_class: str, confidence: float, evidence: list[dict[str, Any]],
    assigned_by: str = "system", assigned_at: Optional[str] = None, attr_id: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "id": attr_id or "",
        "category": category,
        "actor": actor,
        "label": label,
        "source": source,
        "method": method,
        "method_class": method_class,
        "confidence": round(float(confidence), 4),
        "evidence": evidence,
        "assigned_by": assigned_by,
        "assigned_at": assigned_at or _now(),
    }


# ---------------------------------------------------------------------------
# Deterministic providers (reproducible, recomputed live)
# ---------------------------------------------------------------------------
def _from_sanctions(address: str, chain: Optional[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        import sanctions_engine
        res = sanctions_engine.screen_address(address, chain)
    except Exception:  # noqa: BLE001
        return out
    for m in res.get("matches", []):
        out.append(_attribution(
            category="sanctioned",
            actor=m.get("name", ""),
            label=f"Sanctioned entity: {m.get('name','')}",
            source=m.get("source", "OFAC/Sanctions list"),
            method="sanctions_list_exact_address_match",
            method_class=DETERMINISTIC,
            confidence=1.0,
            evidence=[
                {"type": "blockchain_address", "value": address, "ref": "screened address"},
                {"type": "sanctions_entity", "value": m.get("name", ""), "ref": m.get("source", "")},
                {"type": "sanctions_programs", "value": ", ".join(m.get("programs", []) or []), "ref": m.get("listed_on", "")},
            ],
        ))
    return out


def _from_vasp(address: str, chain: Optional[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        import vasp_directory
        v = vasp_directory.identify_vasp(address, chain)
    except Exception:  # noqa: BLE001
        return out
    if v.get("is_vasp") and v.get("vasp"):
        vp = v["vasp"]
        out.append(_attribution(
            category="exchange",
            actor=vp.get("name", ""),
            label=vp.get("label") or f"{vp.get('name','')} ({vp.get('type','exchange')})",
            source=f"CrypTX VASP Directory ({vp.get('source','seed')})",
            method="vasp_directory_exact_address_match",
            method_class=DETERMINISTIC,
            confidence=0.97,
            evidence=[
                {"type": "blockchain_address", "value": address, "ref": "matched VASP wallet"},
                {"type": "vasp", "value": vp.get("name", ""), "ref": vp.get("jurisdiction") or vp.get("country", "")},
            ],
        ))
    return out


def _from_contract_registry(address: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    a = _addr(address)
    try:
        import holistic_trace_engine as hte
        registries = [
            ("mixer", hte.MIXER_CONTRACTS, 1.0),
            ("bridge", hte.BRIDGE_CONTRACTS, 0.98),
            ("dex", hte.DEX_ROUTERS, 0.98),
        ]
    except Exception:  # noqa: BLE001
        return out
    for category, reg, conf in registries:
        if a in reg:
            info = reg[a]
            out.append(_attribution(
                category=category,
                actor=info.get("name", ""),
                label=f"{info.get('name','')} ({category})",
                source="CrypTX Contract Registry (public on-chain infrastructure)",
                method="known_contract_exact_address_match",
                method_class=DETERMINISTIC,
                confidence=conf,
                evidence=[
                    {"type": "contract_address", "value": a, "ref": info.get("name", "")},
                    {"type": "protocol", "value": info.get("name", ""), "ref": info.get("chain", "")},
                ],
            ))
    return out


def _stored(address: str, chain: Optional[str]) -> list[dict[str, Any]]:
    a = _addr(address)
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM attributions WHERE address = ? AND valid = 1 ORDER BY assigned_at DESC", (a,)
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        if chain and r["chain"] and r["chain"].lower() != chain.lower():
            continue
        try:
            evidence = json.loads(r["evidence"] or "[]")
        except Exception:  # noqa: BLE001
            evidence = []
        out.append(_attribution(
            category=r["category"], actor=r["actor"], label=r["label"],
            source=r["source"], method=r["method"], method_class=r["method_class"],
            confidence=r["confidence"], evidence=evidence,
            assigned_by=r["assigned_by"], assigned_at=r["assigned_at"], attr_id=r["id"],
        ))
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def attribute(address: str, chain: Optional[str] = None) -> dict[str, Any]:
    """Aggregate all applicable attributions into a court-defensible record."""
    a = _addr(address)
    if not a:
        return {"address": address, "attributions": [], "court_defensible": False, "checked_at": _now()}

    attributions: list[dict[str, Any]] = []
    attributions += _from_sanctions(a, chain)
    attributions += _from_vasp(a, chain)
    attributions += _from_contract_registry(a)
    attributions += _stored(a, chain)

    # Sort: deterministic first, then by confidence.
    order = {DETERMINISTIC: 0, ANALYST: 1, HEURISTIC: 2}
    attributions.sort(key=lambda x: (order.get(x["method_class"], 3), -x["confidence"]))

    deterministic_backed = [
        x for x in attributions
        if x["method_class"] == DETERMINISTIC and x["confidence"] >= COURT_CONFIDENCE and x["evidence"]
    ]
    court_defensible = bool(deterministic_backed)
    primary = attributions[0] if attributions else None
    categories = sorted({x["category"] for x in attributions if x["category"] != "unknown"})
    actors = sorted({x["actor"] for x in attributions if x["actor"]})

    return {
        "address": address,
        "chain": chain or "",
        "attribution_count": len(attributions),
        "court_defensible": court_defensible,
        "court_defensible_reason": (
            f"{len(deterministic_backed)} deterministic exact-match attribution(s) with cited evidence "
            f"and confidence ≥ {COURT_CONFIDENCE}." if court_defensible
            else "No deterministic, evidence-backed exact-match attribution — treat as investigative lead only."
        ),
        "primary": primary,
        "overall_confidence": round(max([x["confidence"] for x in attributions], default=0.0), 4),
        "categories": categories,
        "actors": actors,
        "attributions": attributions,
        "checked_at": _now(),
        "disclaimer": "Attributions are sourced and provenance-tracked. Deterministic exact-match labels are "
                      "court-defensible; heuristic labels are investigative leads requiring corroboration.",
    }


def add_attribution(
    address: str, category: str, actor: str = "", label: str = "", source: str = "",
    confidence: float = 0.6, evidence: Optional[list[dict[str, Any]]] = None,
    chain: str = "", assigned_by: str = "analyst", method_class: str = ANALYST,
    method: str = "analyst_assertion", note: str = "",
) -> dict[str, Any]:
    a = _addr(address)
    if not a:
        raise ValueError("address is required")
    if category not in CATEGORIES:
        category = "unknown"
    if method_class not in METHOD_CLASSES:
        method_class = ANALYST
    confidence = max(0.0, min(1.0, float(confidence)))
    aid = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            """INSERT INTO attributions
               (id, address, chain, category, actor, label, source, method, method_class,
                confidence, evidence, assigned_by, assigned_at, valid, note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
            (aid, a, chain, category, actor, label or f"{actor or category}",
             source or f"Analyst: {assigned_by}", method, method_class, confidence,
             json.dumps(evidence or []), assigned_by, _now(), note),
        )
        con.commit()
    return {"id": aid, **attribute(a, chain or None)}


def bulk_import(items: list[dict[str, Any]], source: str, assigned_by: str = "import",
                method: str = "bulk_import", method_class: str = DETERMINISTIC,
                default_confidence: float = 0.9) -> dict[str, Any]:
    """
    Bulk-import labels (OFAC CSV, Dune exports, GitHub label repos, victim feeds).
    Dedupes on (address, source, label). Every record keeps full provenance.
    Item shape: {address, chain?, category?, actor?, label?, confidence?, note?, evidence?}
    """
    imported, skipped, errors = 0, 0, 0
    now = _now()
    with _conn() as con:
        for item in items:
            a = _addr(item.get("address", ""))
            if not a:
                errors += 1
                continue
            label = str(item.get("label") or item.get("actor") or item.get("category") or "imported")[:200]
            src = str(item.get("source") or source)[:200]
            dup = con.execute(
                "SELECT 1 FROM attributions WHERE address=? AND source=? AND label=? AND valid=1 LIMIT 1",
                (a, src, label),
            ).fetchone()
            if dup:
                skipped += 1
                continue
            category = item.get("category") or "unknown"
            if category not in CATEGORIES:
                category = "unknown"
            conf = max(0.0, min(1.0, float(item.get("confidence", default_confidence))))
            con.execute(
                """INSERT INTO attributions
                   (id, address, chain, category, actor, label, source, method, method_class,
                    confidence, evidence, assigned_by, assigned_at, valid, note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (str(uuid.uuid4()), a, item.get("chain", ""), category,
                 str(item.get("actor", ""))[:200], label, src, method, method_class,
                 conf, json.dumps(item.get("evidence") or []), assigned_by, now,
                 str(item.get("note", ""))[:500]),
            )
            imported += 1
        con.commit()
    return {"imported": imported, "skipped_duplicates": skipped, "errors": errors, "source": source}


def search_entities(query: str, limit: int = 25) -> list[dict[str, Any]]:
    """Search stored attributions by actor / label / source (entity-search backend)."""
    if not query.strip():
        return []
    q = f"%{query.strip().lower()}%"
    with _conn() as con:
        rows = con.execute(
            """SELECT address, chain, category, actor, label, source, confidence, method_class
               FROM attributions
               WHERE valid=1 AND (LOWER(actor) LIKE ? OR LOWER(label) LIKE ? OR LOWER(source) LIKE ?)
               ORDER BY confidence DESC LIMIT ?""",
            (q, q, q, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def revoke_attribution(attr_id: str, revoked_by: str = "analyst") -> dict[str, Any]:
    with _conn() as con:
        cur = con.execute(
            "UPDATE attributions SET valid = 0, note = note || ? WHERE id = ? AND valid = 1",
            (f" [revoked by {revoked_by} {_now()}]", attr_id),
        )
        con.commit()
        changed = cur.rowcount
    return {"revoked": bool(changed), "id": attr_id}


def audit(address: str) -> dict[str, Any]:
    """Full provenance/audit trail for an address, including revoked attributions."""
    a = _addr(address)
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM attributions WHERE address = ? ORDER BY assigned_at DESC", (a,)
        ).fetchall()
    return {
        "address": address,
        "records": [
            {**dict(r), "evidence": json.loads(r["evidence"] or "[]")} for r in rows
        ],
        "count": len(rows),
    }


def methods_catalog() -> dict[str, Any]:
    return {
        "method_classes": [
            {"class": DETERMINISTIC, "description": "Exact, reproducible match against an authoritative registry. Court-defensible.", "confidence": "pinned (≥0.95)"},
            {"class": ANALYST, "description": "Human assertion attributed to a named analyst, with optional evidence.", "confidence": "analyst-set"},
            {"class": HEURISTIC, "description": "Probabilistic inference from behaviour. Investigative lead only.", "confidence": "model-scored"},
        ],
        "deterministic_sources": [
            "OFAC + multi-jurisdiction sanctions lists (sanctions_engine)",
            "CrypTX VASP Directory (vasp_directory)",
            "CrypTX Contract Registry — mixers, bridges, DEX routers (holistic_trace_engine)",
        ],
        "categories": list(CATEGORIES),
        "court_confidence_threshold": COURT_CONFIDENCE,
    }


if __name__ == "__main__":
    try:
        import sanctions_engine, vasp_directory
        sanctions_engine.init_sanctions_tables(); vasp_directory.init_vasp_tables()
    except Exception:
        pass
    init_attribution_tables()
    r = attribute("0x8589427373d6d84e98730d7795d8f6f8731fda16")  # Tornado Cash router (sanctioned + mixer)
    print("court_defensible:", r["court_defensible"], "| categories:", r["categories"])
    print("primary:", r["primary"]["source"], r["primary"]["method"], r["primary"]["confidence"] if r["primary"] else None)
    r2 = attribute("0x28c6c06298d514db089934071355e5743bf21d60")  # Binance
    print("binance primary:", r2["primary"]["actor"] if r2["primary"] else None, "| defensible:", r2["court_defensible"])
