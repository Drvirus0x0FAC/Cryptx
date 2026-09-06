"""
Victim Report & Scam Intelligence module.
Manages victim intake, scam-address clustering, and cross-victim pattern analysis.
"""
from __future__ import annotations
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

import database

logger = logging.getLogger(__name__)

SCAM_TYPES: dict[str, dict] = {
    "pig_butchering":   {"label": "Pig Butchering",   "severity": "critical"},
    "investment_fraud": {"label": "Investment Fraud",  "severity": "critical"},
    "ponzi_scheme":     {"label": "Ponzi Scheme",      "severity": "critical"},
    "wallet_drainer":   {"label": "Wallet Drainer",    "severity": "critical"},
    "rug_pull":         {"label": "Rug Pull",           "severity": "high"},
    "phishing":         {"label": "Phishing",           "severity": "high"},
    "romance_scam":     {"label": "Romance Scam",       "severity": "high"},
    "exchange_fraud":   {"label": "Exchange Fraud",     "severity": "high"},
    "fake_exchange":    {"label": "Fake Exchange",      "severity": "high"},
    "nft_fraud":        {"label": "NFT Fraud",          "severity": "medium"},
    "airdrop_scam":     {"label": "Airdrop Scam",       "severity": "medium"},
    "impersonation":    {"label": "Impersonation",      "severity": "medium"},
    "other":            {"label": "Other",              "severity": "medium"},
}

REPORT_STATUSES = ["open", "under_review", "escalated", "referred", "closed"]


def init_victim_tables() -> None:
    conn = database.get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS victim_reports (
            id            TEXT PRIMARY KEY,
            case_id       TEXT,
            scam_type     TEXT NOT NULL,
            scammer_address TEXT NOT NULL,
            victim_address  TEXT DEFAULT '',
            amount_usd    REAL DEFAULT 0,
            token         TEXT DEFAULT 'Unknown',
            chain         TEXT NOT NULL DEFAULT 'ETH',
            incident_date TEXT DEFAULT '',
            report_date   TEXT NOT NULL,
            description   TEXT DEFAULT '',
            contact_name  TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            jurisdiction  TEXT DEFAULT '',
            status        TEXT DEFAULT 'open',
            evidence_hashes TEXT DEFAULT '[]',
            tx_hashes     TEXT DEFAULT '[]',
            tags          TEXT DEFAULT '[]',
            analyst_notes TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vr_scammer ON victim_reports(scammer_address);
        CREATE INDEX IF NOT EXISTS idx_vr_case    ON victim_reports(case_id);
        CREATE INDEX IF NOT EXISTS idx_vr_type    ON victim_reports(scam_type);
        CREATE INDEX IF NOT EXISTS idx_vr_status  ON victim_reports(status);

        CREATE TABLE IF NOT EXISTS scam_intel_cache (
            scammer_address TEXT PRIMARY KEY,
            victim_count    INTEGER DEFAULT 0,
            total_damage_usd REAL DEFAULT 0,
            scam_types      TEXT DEFAULT '[]',
            chains          TEXT DEFAULT '[]',
            first_incident  TEXT,
            last_incident   TEXT,
            report_ids      TEXT DEFAULT '[]',
            updated_at      TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jload(s: Optional[str], default=None):
    if s is None:
        return [] if default is None else default
    try:
        return json.loads(s)
    except Exception:
        return [] if default is None else default


def _row_to_report(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    for f in ("evidence_hashes", "tx_hashes", "tags"):
        d[f] = _jload(d.get(f))
    return d


def _update_intel_cache(conn, addr: str) -> None:
    rows = conn.execute("""
        SELECT id, amount_usd, scam_type, chain, incident_date
        FROM victim_reports WHERE scammer_address=?
    """, (addr,)).fetchall()

    if not rows:
        conn.execute("DELETE FROM scam_intel_cache WHERE scammer_address=?", (addr,))
        return

    total  = sum(r["amount_usd"] or 0 for r in rows)
    types  = list({r["scam_type"] for r in rows})
    chains = list({r["chain"] for r in rows})
    # sqlite3.Row supports key/index access but not .get(); the SELECT above
    # always includes `incident_date`, so direct key access is safe.
    dates  = [r["incident_date"] for r in rows if r["incident_date"]]
    ids    = [r["id"] for r in rows]

    conn.execute("""
        INSERT OR REPLACE INTO scam_intel_cache
        (scammer_address, victim_count, total_damage_usd, scam_types, chains,
         first_incident, last_incident, report_ids, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        addr, len(rows), total,
        json.dumps(types), json.dumps(chains),
        min(dates) if dates else None,
        max(dates) if dates else None,
        json.dumps(ids), _now(),
    ))


# ── CRUD ──────────────────────────────────────────────────────────────────────

def submit_report(
    scam_type: str,
    scammer_address: str,
    chain: str = "ETH",
    victim_address: str = "",
    amount_usd: float = 0.0,
    token: str = "Unknown",
    incident_date: str = "",
    description: str = "",
    contact_name: str = "",
    contact_email: str = "",
    jurisdiction: str = "",
    tx_hashes: list | None = None,
    tags: list | None = None,
    case_id: str = "",
) -> dict:
    report_id = str(uuid.uuid4())
    now  = _now()
    addr = scammer_address.strip().lower()
    conn = database.get_connection()
    try:
        conn.execute("""
            INSERT INTO victim_reports
            (id, case_id, scam_type, scammer_address, victim_address,
             amount_usd, token, chain, incident_date, report_date,
             description, contact_name, contact_email, jurisdiction,
             status, evidence_hashes, tx_hashes, tags, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            report_id, case_id or None, scam_type, addr, victim_address,
            amount_usd, token, chain, incident_date, now[:10],
            description, contact_name, contact_email, jurisdiction,
            "open", "[]", json.dumps(tx_hashes or []),
            json.dumps(tags or []), now, now,
        ))
        conn.commit()
        _update_intel_cache(conn, addr)
        conn.commit()
        return get_report(report_id)
    finally:
        conn.close()


def get_report(report_id: str) -> dict:
    conn = database.get_connection()
    try:
        return _row_to_report(
            conn.execute("SELECT * FROM victim_reports WHERE id=?", (report_id,)).fetchone()
        )
    finally:
        conn.close()


def list_reports(
    scammer_address: str = "",
    scam_type: str = "",
    status: str = "",
    case_id: str = "",
    chain: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict:
    conn = database.get_connection()
    try:
        clauses, params = [], []
        if scammer_address:
            clauses.append("scammer_address=?"); params.append(scammer_address.lower())
        if scam_type:
            clauses.append("scam_type=?");   params.append(scam_type)
        if status:
            clauses.append("status=?");       params.append(status)
        if case_id:
            clauses.append("case_id=?");      params.append(case_id)
        if chain:
            clauses.append("chain=?");        params.append(chain)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM victim_reports {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM victim_reports {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return {
            "reports": [_row_to_report(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        conn.close()


def update_report(report_id: str, **updates) -> dict:
    allowed = {
        "status", "analyst_notes", "case_id", "jurisdiction",
        "contact_name", "contact_email", "tags", "description",
        "amount_usd", "incident_date",
    }
    fields: dict = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if not fields:
        return get_report(report_id)
    if "tags" in fields and isinstance(fields["tags"], list):
        fields["tags"] = json.dumps(fields["tags"])
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn = database.get_connection()
    try:
        conn.execute(
            f"UPDATE victim_reports SET {set_clause} WHERE id=?",
            list(fields.values()) + [report_id],
        )
        conn.commit()
        return get_report(report_id)
    finally:
        conn.close()


def delete_report(report_id: str) -> bool:
    conn = database.get_connection()
    try:
        cur = conn.execute("DELETE FROM victim_reports WHERE id=?", (report_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Scam Intelligence ─────────────────────────────────────────────────────────

def get_scam_intel(scammer_address: str) -> dict:
    addr = scammer_address.strip().lower()
    conn = database.get_connection()
    try:
        _update_intel_cache(conn, addr)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM scam_intel_cache WHERE scammer_address=?", (addr,)
        ).fetchone()
        if not row:
            return {"scammer_address": addr, "victim_count": 0, "total_damage_usd": 0,
                    "scam_types": [], "chains": [], "report_ids": []}
        d = dict(row)
        for f in ("scam_types", "chains", "report_ids"):
            d[f] = _jload(d.get(f))
        return d
    finally:
        conn.close()


def list_scam_clusters(
    min_victims: int = 1,
    scam_type: str = "",
    limit: int = 50,
) -> list:
    conn = database.get_connection()
    try:
        rows = conn.execute("""
            SELECT scammer_address,
                   COUNT(*) as victim_count,
                   SUM(amount_usd) as total_damage_usd,
                   GROUP_CONCAT(DISTINCT scam_type) as scam_types,
                   GROUP_CONCAT(DISTINCT chain) as chains,
                   MIN(NULLIF(incident_date,'')) as first_incident,
                   MAX(NULLIF(incident_date,'')) as last_incident
            FROM victim_reports
            GROUP BY scammer_address
            HAVING victim_count >= ?
            ORDER BY total_damage_usd DESC
            LIMIT ?
        """, (min_victims, limit)).fetchall()

        clusters = []
        for row in rows:
            d = dict(row)
            d["scam_types"] = [x for x in (d.get("scam_types") or "").split(",") if x]
            d["chains"]     = [x for x in (d.get("chains") or "").split(",") if x]
            if scam_type and scam_type not in d["scam_types"]:
                continue
            clusters.append(d)
        return clusters
    finally:
        conn.close()


def scam_intelligence_summary() -> dict:
    conn = database.get_connection()
    try:
        totals = conn.execute("""
            SELECT COUNT(*) as total_reports,
                   COUNT(DISTINCT scammer_address) as unique_scammers,
                   SUM(amount_usd) as total_damage_usd,
                   COUNT(DISTINCT chain) as chains_affected
            FROM victim_reports
        """).fetchone()

        by_type = conn.execute("""
            SELECT scam_type, COUNT(*) as count, SUM(amount_usd) as damage
            FROM victim_reports GROUP BY scam_type ORDER BY damage DESC
        """).fetchall()

        by_status = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM victim_reports GROUP BY status
        """).fetchall()

        recent = conn.execute("""
            SELECT id, scam_type, scammer_address, amount_usd, chain, status, created_at
            FROM victim_reports ORDER BY created_at DESC LIMIT 5
        """).fetchall()

        top_scammers = conn.execute("""
            SELECT scammer_address,
                   COUNT(*) as victims,
                   SUM(amount_usd) as damage,
                   GROUP_CONCAT(DISTINCT scam_type) as types
            FROM victim_reports
            GROUP BY scammer_address ORDER BY damage DESC LIMIT 10
        """).fetchall()

        return {
            "total_reports":   totals["total_reports"] if totals else 0,
            "unique_scammers": totals["unique_scammers"] if totals else 0,
            "total_damage_usd": float(totals["total_damage_usd"] or 0) if totals else 0,
            "chains_affected": totals["chains_affected"] if totals else 0,
            "by_scam_type":    [dict(r) for r in by_type],
            "by_status":       [dict(r) for r in by_status],
            "recent_reports":  [dict(r) for r in recent],
            "top_scammers":    [
                {**dict(r), "types": (r["types"] or "").split(",")}
                for r in top_scammers
            ],
        }
    finally:
        conn.close()


def export_report_bundle(report_ids: list) -> dict:
    """Law-enforcement-ready bundle from selected reports."""
    conn = database.get_connection()
    try:
        reports = [
            _row_to_report(conn.execute("SELECT * FROM victim_reports WHERE id=?", (rid,)).fetchone())
            for rid in report_ids
        ]
    finally:
        conn.close()

    reports = [r for r in reports if r]
    if not reports:
        return {"error": "No reports found"}

    return {
        "bundle_id":         str(uuid.uuid4()),
        "generated_at":      _now(),
        "report_count":      len(reports),
        "scammer_addresses": list({r["scammer_address"] for r in reports}),
        "total_damage_usd":  sum(r.get("amount_usd") or 0 for r in reports),
        "scam_types":        list({r["scam_type"] for r in reports}),
        "chains":            list({r["chain"] for r in reports}),
        "jurisdictions":     list({r["jurisdiction"] for r in reports if r.get("jurisdiction")}),
        "reports":           reports,
        "disclaimer": (
            "This bundle was generated by the CryptoOSINT Investigator platform. "
            "All data is based on victim-submitted information and on-chain evidence. "
            "Intended for law enforcement use only. "
            "Handle victim contact information per applicable privacy laws."
        ),
    }
