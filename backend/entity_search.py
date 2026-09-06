"""
Unified entity search for CrypTX.

One search box → typed results across attribution labels, VASP/KYV directory,
sanctions entities, local labels, and case subjects. This is the table-stakes
"search Binance / Lazarus / FixedFloat" feature every competitor demos.

Returns ranked, de-duplicated entity cards with pivots (addresses, chains,
sources, risk) so the investigator can jump to any module from a single result.

Aggregates across:
  * attribution_engine  — `attributions` table (labels/categories per address)
  * vasp_directory      — `vasp_directory` table (exchange/VASP identities)
  * sanctions_engine    — `sanctions_entities` + `sanctions_addresses` (OFAC etc.)
  * database.local_labels — investigator-added labels
  * constants           — known mixers/bridges/services

This is a read-only aggregation layer — it never writes. Each source degrades
gracefully (a missing table or engine import error is caught, not fatal).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _score(query: str, text: str) -> float:
    """Simple relevance score: 1.0 exact, 0.85 starts-with, 0.7 contains, else 0.4 per token overlap."""
    q = _norm(query)
    t = _norm(text)
    if not q or not t:
        return 0.0
    if q == t:
        return 1.0
    if t.startswith(q):
        return 0.85
    if q in t:
        return 0.75
    # token overlap
    qt = set(q.split())
    tt = set(t.split())
    overlap = len(qt & tt)
    if overlap:
        return min(0.4 + 0.1 * overlap, 0.7)
    return 0.0


# ── Per-source searches ─────────────────────────────────────────────────────

def _search_vasps(query: str, limit: int) -> list[dict[str, Any]]:
    """Search the VASP directory by name. Returns entity cards."""
    out: list[dict[str, Any]] = []
    try:
        with _conn() as con:
            if not _table_exists(con, "vasp_directory"):
                return out
            rows = con.execute("SELECT * FROM vasp_directory").fetchall()
        # Aggregate addresses by vasp_name (the table is address-keyed).
        by_name: dict[str, dict[str, Any]] = {}
        for r in rows:
            d = dict(r)
            name = d.get("vasp_name") or ""
            if not name:
                continue
            if name not in by_name:
                by_name[name] = {
                    "entity_id": f"vasp:{name.lower().replace(' ', '-')}",
                    "name": name,
                    "type": "vasp",
                    "subtype": d.get("vasp_type") or "exchange",
                    "category": "exchange",
                    "jurisdiction": d.get("jurisdiction") or "",
                    "country": d.get("country") or "",
                    "addresses": [],
                    "sources": set(),
                }
            by_name[name]["addresses"].append({
                "chain": d.get("chain") or "",
                "address": d.get("address") or "",
                "label": d.get("label") or "",
            })
            by_name[name]["sources"].add(d.get("source") or "seed")
        for name, card in by_name.items():
            score = _score(query, name)
            if score <= 0:
                continue
            card["relevance"] = score
            card["sources"] = sorted(card["sources"])
            out.append(card)
    except Exception:
        pass
    out.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    return out[:limit]


def _search_sanctions(query: str, limit: int) -> list[dict[str, Any]]:
    """Search sanctions entities by name (fuzzy)."""
    out: list[dict[str, Any]] = []
    try:
        import sanctions_engine
        result = sanctions_engine.search_name(query, limit=limit, min_score=0.4)
        # search_name returns {"matches": [...]}, not "entities".
        for ent in result.get("matches") or result.get("entities") or []:
            name = ent.get("name") or ent.get("caption") or ""
            # Fetch the full entity to get addresses (search_name doesn't return them).
            addresses = []
            uid = ent.get("uid") or ent.get("id")
            if uid:
                full = sanctions_engine.get_entity(uid)
                if full:
                    addresses = full.get("addresses") or []
            out.append({
                "entity_id": f"sanctions:{uid or _norm(name)}",
                "name": name,
                "type": "sanctioned_entity",
                "subtype": ent.get("type") or "entity",
                "category": "sanctioned",
                "jurisdiction": "",
                "country": ent.get("country") or "",
                "addresses": [{"chain": a.get("chain", ""), "address": a.get("address", ""), "label": ""} for a in addresses],
                "sources": [ent.get("source") or "OFAC"],
                "programs": ent.get("programs") or [],
                "listed_on": ent.get("listed_on") or "",
                "relevance": ent.get("score") or _score(query, name),
            })
    except Exception:
        pass
    out.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    return out[:limit]


def _search_attribution_labels(query: str, limit: int) -> list[dict[str, Any]]:
    """Search attribution labels (actors) by name/label text."""
    out: list[dict[str, Any]] = []
    try:
        with _conn() as con:
            if not _table_exists(con, "attributions"):
                return out
            q = f"%{_norm(query)}%"
            rows = con.execute(
                """SELECT DISTINCT actor, label, category, chain, source, method_class,
                          COUNT(*) as addr_count, MAX(confidence) as max_conf
                   FROM attributions
                   WHERE valid=1 AND (lower(actor) LIKE ? OR lower(label) LIKE ?)
                   GROUP BY actor, label, category
                   ORDER BY max_conf DESC, addr_count DESC
                   LIMIT ?""",
                (q, q, limit * 3),
            ).fetchall()
        for r in rows:
            d = dict(r)
            actor = d.get("actor") or d.get("label") or ""
            if not actor:
                continue
            label = d.get("label") or actor
            out.append({
                "entity_id": f"attribution:{_norm(actor)}:{d.get('category','')}",
                "name": actor,
                "type": "attribution_label",
                "subtype": d.get("category") or "unknown",
                "category": d.get("category") or "unknown",
                "jurisdiction": "",
                "country": "",
                "addresses": [],  # populated on-demand via the entity detail endpoint
                "address_count": d.get("addr_count", 0),
                "sources": [d.get("source") or "attribution"],
                "method_class": d.get("method_class") or "analyst",
                "max_confidence": d.get("max_conf", 0),
                "relevance": _score(query, actor) or _score(query, label) or 0.5,
            })
    except Exception:
        pass
    out.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    return out[:limit]


def _search_local_labels(query: str, limit: int) -> list[dict[str, Any]]:
    """Search investigator-added local labels."""
    out: list[dict[str, Any]] = []
    try:
        with _conn() as con:
            if not _table_exists(con, "local_labels"):
                return out
            q = f"%{_norm(query)}%"
            rows = con.execute(
                """SELECT label, category, chain, address, source, confidence
                   FROM local_labels
                   WHERE lower(label) LIKE ? OR lower(category) LIKE ?
                   ORDER BY confidence DESC LIMIT ?""",
                (q, q, limit),
            ).fetchall()
        for r in rows:
            d = dict(r)
            out.append({
                "entity_id": f"label:{d.get('address','')}:{d.get('chain','')}",
                "name": d.get("label") or "",
                "type": "local_label",
                "subtype": d.get("category") or "unknown",
                "category": d.get("category") or "unknown",
                "addresses": [{"chain": d.get("chain", ""), "address": d.get("address", ""), "label": d.get("label", "")}],
                "sources": [d.get("source") or "investigator"],
                "confidence": d.get("confidence", 0),
                "relevance": _score(query, d.get("label") or "") or 0.4,
            })
    except Exception:
        pass
    out.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    return out[:limit]


# ── Unified search ──────────────────────────────────────────────────────────

def search_entities(query: str, limit: int = 20) -> dict[str, Any]:
    """Unified entity search across all sources.

    Returns ranked, de-duplicated results. Each result is an "entity card" with:
      * entity_id, name, type, subtype, category
      * jurisdiction, country
      * addresses (list of {chain, address, label})
      * sources, relevance (0-1), and source-specific fields.

    De-duplication: if the same name appears in VASP + sanctions, both are
    returned (they're different evidence types) but flagged via `also_in`.
    """
    query = (query or "").strip()
    if not query or len(query) < 2:
        return {"query": query, "count": 0, "entities": [], "sources_searched": []}

    per_source_limit = max(limit, 10)
    vasp = _search_vasps(query, per_source_limit)
    sanc = _search_sanctions(query, per_source_limit)
    attr = _search_attribution_labels(query, per_source_limit)
    locl = _search_local_labels(query, per_source_limit)

    # Merge + rank.
    all_results = vasp + sanc + attr + locl
    # Cross-reference: flag entities that appear in multiple sources.
    name_index: dict[str, list[str]] = {}
    for r in all_results:
        key = _norm(r.get("name") or "")
        name_index.setdefault(key, []).append(r["entity_id"])
    for r in all_results:
        key = _norm(r.get("name") or "")
        peers = [pid for pid in name_index.get(key, []) if pid != r["entity_id"]]
        if peers:
            r["also_in"] = peers

    all_results.sort(key=lambda x: x.get("relevance", 0), reverse=True)

    return {
        "query": query,
        "count": len(all_results[:limit]),
        "entities": all_results[:limit],
        "sources_searched": [
            {"source": "vasp_directory", "results": len(vasp)},
            {"source": "sanctions", "results": len(sanc)},
            {"source": "attribution_labels", "results": len(attr)},
            {"source": "local_labels", "results": len(locl)},
        ],
    }


def get_entity_detail(entity_id: str) -> Optional[dict[str, Any]]:
    """Fetch full detail for a single entity by its entity_id.

    For attribution labels, this populates the full address list (the search
    result omits it for brevity).
    """
    if not entity_id:
        return None
    # Parse the entity_id prefix.
    if entity_id.startswith("vasp:"):
        name = entity_id[5:].replace("-", " ")
        results = _search_vasps(name, 5)
        for r in results:
            if _norm(r["name"]) == _norm(name):
                return r
    elif entity_id.startswith("sanctions:"):
        uid = entity_id[len("sanctions:"):]
        try:
            import sanctions_engine
            ent = sanctions_engine.get_entity(uid)
            if ent:
                return {
                    "entity_id": entity_id,
                    "name": ent.get("name") or "",
                    "type": "sanctioned_entity",
                    "category": "sanctioned",
                    "country": ent.get("country") or "",
                    "addresses": [{"chain": a.get("chain", ""), "address": a.get("address", ""), "label": ""} for a in (ent.get("addresses") or [])],
                    "sources": [ent.get("source") or "OFAC"],
                    "programs": ent.get("programs") or [],
                    "aliases": ent.get("aliases") or [],
                    "_raw": ent,
                }
        except Exception:
            pass
    elif entity_id.startswith("attribution:"):
        # Re-query the full address set for this actor.
        parts = entity_id.split(":", 2)
        actor_key = parts[2] if len(parts) > 2 else ""
        try:
            with _conn() as con:
                if _table_exists(con, "attributions"):
                    rows = con.execute(
                        """SELECT address, chain, label, category, source, confidence, method_class
                           FROM attributions WHERE valid=1 AND lower(actor)=? ORDER BY confidence DESC LIMIT 100""",
                        (actor_key.split(":")[0],),
                    ).fetchall()
                    if rows:
                        d0 = dict(rows[0])
                        return {
                            "entity_id": entity_id,
                            "name": d0.get("label") or actor_key,
                            "type": "attribution_label",
                            "category": d0.get("category") or "unknown",
                            "addresses": [{"chain": dict(r).get("chain", ""), "address": dict(r).get("address", ""), "label": dict(r).get("label", "")} for r in rows],
                            "address_count": len(rows),
                            "sources": sorted({dict(r).get("source") or "" for r in rows if dict(r).get("source")}),
                            "max_confidence": max((dict(r).get("confidence") or 0) for r in rows),
                        }
        except Exception:
            pass
    elif entity_id.startswith("label:"):
        # local_labels are already complete in the search result; re-search.
        pass
    return None
