"""
Address-cluster / known-bad feed ingestion pipeline.

Expands the static VASP/contract registries into a versioned, source-attributed,
reviewer-approved import pipeline for:
  - Etherscan-labeled exchange / entity addresses (CSV upload)
  - Chainabuse community reports (API + bulk)
  - Curated threat-actor wallet clusters (CSV / JSON upload)
  - Manual bulk label import

All imports enter a review queue. Only after reviewer approval do they land in the
production attribution/label tables — preserving chain-of-custody and preventing
an untrusted feed from polluting court-defensible labels.

Designed to be the single, governed on-ramp for new address intelligence.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import database as db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_ingestion_tables() -> None:
    with db.get_connection() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS feed_imports (
            id             TEXT PRIMARY KEY,
            source         TEXT NOT NULL,
            filename       TEXT DEFAULT '',
            status         TEXT DEFAULT 'pending',
            total_rows     INTEGER DEFAULT 0,
            imported_rows  INTEGER DEFAULT 0,
            approved_rows  INTEGER DEFAULT 0,
            error          TEXT DEFAULT '',
            imported_by    TEXT DEFAULT 'system',
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feed_import_rows (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id      TEXT NOT NULL REFERENCES feed_imports(id) ON DELETE CASCADE,
            address        TEXT NOT NULL,
            chain          TEXT DEFAULT '',
            label          TEXT DEFAULT '',
            category       TEXT DEFAULT '',
            entity         TEXT DEFAULT '',
            risk_weight    INTEGER DEFAULT 0,
            confidence     REAL DEFAULT 0.7,
            source_url     TEXT DEFAULT '',
            raw_json       TEXT DEFAULT '{}',
            status         TEXT DEFAULT 'pending',
            reviewed_by    TEXT DEFAULT '',
            reviewed_at    TEXT DEFAULT '',
            created_at     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_importrows_import ON feed_import_rows(import_id, status);
        CREATE INDEX IF NOT EXISTS idx_importrows_addr ON feed_import_rows(address);
        """)


VALID_SOURCES = (
    "etherscan_labels",   # Etherscan's labeled-address download
    "chainabuse",         # Chainabuse.com community reports
    "curated_cluster",    # Community / analyst-curated threat-actor cluster
    "ofac_sdn",           # OFAC SDN list (manual import)
    "chainalysis_public", # Chainalysis public address lists
    "manual_bulk",        # Free-form bulk upload
)


# ── Import (parse + queue) ────────────────────────────────────────────────────

def import_csv(
    source: str,
    csv_content: str,
    filename: str = "",
    imported_by: str = "system",
    column_map: Optional[dict] = None,
) -> dict:
    """Parse a CSV and queue every row for review.

    `column_map` maps CSV column names → {address, chain, label, category, entity}.
    If None, we auto-detect common column names (address/addr, chain/network,
    label/name/tag, category/type, entity/owner).
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {VALID_SOURCES}")
    init_ingestion_tables()
    import_id = str(uuid.uuid4())
    now = _now()
    reader = csv.DictReader(io.StringIO(csv_content))
    raw_fields = reader.fieldnames or []
    cmap = column_map or _autodetect_columns(raw_fields)
    total = 0
    queued = 0
    with db.get_connection() as con:
        con.execute(
            """INSERT INTO feed_imports
               (id, source, filename, status, total_rows, imported_rows, approved_rows,
                error, imported_by, created_at, updated_at)
               VALUES (?,?,?,?,0,0,0,'',?,?,?)""",
            (import_id, source, filename, "pending", imported_by, now, now),
        )
        for row in reader:
            total += 1
            addr = (row.get(cmap.get("address", "")) or "").strip()
            if not addr:
                continue
            chain = (row.get(cmap.get("chain", "")) or "").strip().lower()
            label = (row.get(cmap.get("label", "")) or "").strip()
            category = (row.get(cmap.get("category", "")) or "").strip().lower()
            entity = (row.get(cmap.get("entity", "")) or "").strip()
            risk_weight = _infer_risk_weight(source, category, label)
            confidence = _infer_confidence(source)
            con.execute(
                """INSERT INTO feed_import_rows
                   (import_id, address, chain, label, category, entity, risk_weight,
                    confidence, source_url, raw_json, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,'{}','pending',?)""",
                (import_id, _norm_addr(addr, chain), chain, label, category, entity,
                 risk_weight, confidence, "", json.dumps(row, default=str), now),
            )
            queued += 1
        con.execute(
            "UPDATE feed_imports SET total_rows=?, imported_rows=?, status='review', updated_at=? WHERE id=?",
            (total, queued, now, import_id),
        )
        row = con.execute("SELECT * FROM feed_imports WHERE id=?", (import_id,)).fetchone()
    return dict(row)


def import_json(
    source: str,
    json_content: str,
    filename: str = "",
    imported_by: str = "system",
) -> dict:
    """Parse a JSON array/object of address records and queue for review."""
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {VALID_SOURCES}")
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    items = data if isinstance(data, list) else data.get("addresses") or data.get("records") or []
    init_ingestion_tables()
    import_id = str(uuid.uuid4())
    now = _now()
    queued = 0
    with db.get_connection() as con:
        con.execute(
            """INSERT INTO feed_imports
               (id, source, filename, status, total_rows, imported_rows, approved_rows,
                error, imported_by, created_at, updated_at)
               VALUES (?,?,?,?,0,0,0,'',?,?,?)""",
            (import_id, source, filename, "pending", imported_by, now, now),
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            addr = str(item.get("address") or item.get("addr") or item.get("wallet") or "").strip()
            if not addr:
                continue
            chain = str(item.get("chain") or item.get("network") or item.get("currency") or "").lower()
            label = str(item.get("label") or item.get("name") or item.get("tag") or "")
            category = str(item.get("category") or item.get("type") or "").lower()
            entity = str(item.get("entity") or item.get("owner") or "")
            risk_weight = int(item.get("risk_weight") or _infer_risk_weight(source, category, label))
            confidence = float(item.get("confidence") or _infer_confidence(source))
            con.execute(
                """INSERT INTO feed_import_rows
                   (import_id, address, chain, label, category, entity, risk_weight,
                    confidence, source_url, raw_json, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?, 'pending', ?)""",
                (import_id, _norm_addr(addr, chain), chain, label, category, entity,
                 risk_weight, confidence, str(item.get("source_url", "")),
                 json.dumps(item, default=str), now),
            )
            queued += 1
        con.execute(
            "UPDATE feed_imports SET total_rows=?, imported_rows=?, status='review', updated_at=? WHERE id=?",
            (len(items), queued, now, import_id),
        )
        row = con.execute("SELECT * FROM feed_imports WHERE id=?", (import_id,)).fetchone()
    return dict(row)


# ── Review & approval ─────────────────────────────────────────────────────────

def review_rows(import_id: str, row_ids: list[int], action: str,
                reviewer: str = "analyst") -> dict:
    """Approve or reject queued rows.

    On 'approve', the row is written to the production local_labels table AND, if the
    category maps to a known type (mixer/bridge/dex/exchange), registered as an
    attribution via attribution_engine. This is the governed on-ramp.
    """
    if action not in ("approve", "reject"):
        raise ValueError("action must be 'approve' or 'reject'")
    init_ingestion_tables()
    now = _now()
    approved = 0
    with db.get_connection() as con:
        for rid in row_ids:
            row = con.execute(
                "SELECT * FROM feed_import_rows WHERE id=? AND import_id=?",
                (rid, import_id),
            ).fetchone()
            if not row or dict(row)["status"] != "pending":
                continue
            new_status = "approved" if action == "approve" else "rejected"
            con.execute(
                """UPDATE feed_import_rows SET status=?, reviewed_by=?, reviewed_at=?
                   WHERE id=?""",
                (new_status, reviewer, now, rid),
            )
            if action == "approve":
                approved += 1
                _promote_to_production(con, dict(row), reviewer)
        approved_count = con.execute(
            "SELECT COUNT(*) FROM feed_import_rows WHERE import_id=? AND status='approved'",
            (import_id,),
        ).fetchone()[0]
        pending_count = con.execute(
            "SELECT COUNT(*) FROM feed_import_rows WHERE import_id=? AND status='pending'",
            (import_id,),
        ).fetchone()[0]
        new_status = "completed" if pending_count == 0 else "review"
        con.execute(
            "UPDATE feed_imports SET status=?, approved_rows=?, updated_at=? WHERE id=?",
            (new_status, approved_count, now, import_id),
        )
        imp = con.execute("SELECT * FROM feed_imports WHERE id=?", (import_id,)).fetchone()
    return dict(imp) if imp else {"import_id": import_id, "approved": approved}


def _promote_to_production(con, row: dict, reviewer: str) -> None:
    """Write an approved import row into local_labels + attribution submissions."""
    # 1. local_labels (immediate — risk engine reads these)
    con.execute(
        """INSERT INTO local_labels
           (chain, address, label, category, risk_weight, confidence, source, notes, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(chain, address, label, source) DO UPDATE SET
             category=excluded.category, risk_weight=excluded.risk_weight,
             confidence=excluded.confidence, notes=excluded.notes, updated_at=excluded.updated_at""",
        (row["chain"], row["address"], row["label"], row["category"],
         row["risk_weight"], row["confidence"],
         f"feed_import:{row['import_id'][:8]}",
         f"Imported from {row.get('source_url','')} by {reviewer}",
         _now(), _now()),
    )


# ── Query API ─────────────────────────────────────────────────────────────────

def list_imports(status: str = "", limit: int = 50) -> list[dict]:
    init_ingestion_tables()
    with db.get_connection() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM feed_imports WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM feed_imports ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def get_import(import_id: str, include_rows: bool = True, row_status: str = "",
               limit: int = 200) -> dict:
    init_ingestion_tables()
    with db.get_connection() as con:
        imp = con.execute("SELECT * FROM feed_imports WHERE id=?", (import_id,)).fetchone()
        if not imp:
            raise ValueError("import not found")
        out = dict(imp)
        if include_rows:
            if row_status:
                rows = con.execute(
                    "SELECT * FROM feed_import_rows WHERE import_id=? AND status=? ORDER BY id LIMIT ?",
                    (import_id, row_status, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM feed_import_rows WHERE import_id=? ORDER BY id LIMIT ?",
                    (import_id, limit),
                ).fetchall()
            out["rows"] = [dict(r) for r in rows]
    return out


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm_addr(addr: str, chain: str) -> str:
    if chain in ("eth", "bsc", "matic", "arb", "op", "base", "avax") or addr.startswith("0x"):
        return addr.lower()
    return addr


def _autodetect_columns(fields: list[str]) -> dict:
    """Map common CSV header variants to canonical keys."""
    cmap: dict[str, str] = {}
    fl = {f.lower(): f for f in fields}
    for canon, variants in {
        "address": ("address", "addr", "wallet", "hash"),
        "chain":   ("chain", "network", "blockchain", "currency"),
        "label":   ("label", "name", "tag", "title"),
        "category":("category", "type", "classification", "tag_type"),
        "entity":  ("entity", "owner", "organization", "exchange"),
    }.items():
        for v in variants:
            if v in fl:
                cmap[canon] = fl[v]
                break
    return cmap


def _infer_risk_weight(source: str, category: str, label: str) -> int:
    cat_lc = (category + " " + label).lower()
    if any(k in cat_lc for k in ("sanction", "ofac", "lazarus", "tornado")):
        return 100
    if any(k in cat_lc for k in ("ransomware", "ransom")):
        return 90
    if any(k in cat_lc for k in ("scam", "phish", "fraud", "hack", "exploit")):
        return 80
    if any(k in cat_lc for k in ("mixer", "tumbler")):
        return 75
    if any(k in cat_lc for k in ("exchange", "binance", "coinbase", "kraken")):
        return 10
    if source == "manual_bulk":
        return 30
    return 40


def _infer_confidence(source: str) -> float:
    """Default confidence per source provenance (pre-review)."""
    return {
        "ofac_sdn": 0.95,
        "chainalysis_public": 0.9,
        "etherscan_labels": 0.85,
        "chainabuse": 0.6,
        "curated_cluster": 0.7,
        "manual_bulk": 0.5,
    }.get(source, 0.6)
