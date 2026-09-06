"""
Case Evidence Vault.
Stores, hashes, and retrieves investigation artifacts with a full audit log.

Evidence types:
  - graph_snapshot  : serialized NexusGraph or TraceGraph state
  - tx_snapshot     : raw transaction detail + interpretation
  - address_intel   : address lookup result
  - cluster_report  : wallet clustering result
  - cashout_report  : cashout detection result
  - path_report     : multi-route pathfinding result
  - timeline        : investigation timeline
  - raw_api         : any raw API response
  - analyst_note    : free-text analyst annotation

Each artifact gets:
  - SHA-256 content hash
  - UTC timestamp (immutable)
  - Evidence quality score (0-100)
  - Audit log entry
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config as _config
DB_PATH = _config.DB_PATH


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


_QUALITY_SCORES: dict[str, int] = {
    "graph_snapshot":  80,
    "tx_snapshot":     90,
    "address_intel":   75,
    "cluster_report":  70,
    "cashout_report":  75,
    "path_report":     70,
    "timeline":        65,
    "raw_api":         85,
    "analyst_note":    60,
    "graph_exhibit":      90,
    "report_export":      85,
    "regulatory_export":  90,
}


def _quality_score(evidence_type: str, content: dict) -> int:
    base = _QUALITY_SCORES.get(evidence_type, 50)
    # Boost if content has key richness indicators
    if evidence_type == "tx_snapshot" and content.get("hash"):
        base = min(100, base + 5)
    if evidence_type in ("cluster_report", "cashout_report"):
        indicators = content.get("indicators") or content.get("clusters") or []
        if len(indicators) >= 3:
            base = min(100, base + 10)
    if evidence_type == "analyst_note":
        text = str(content.get("note") or "")
        if len(text) > 200:
            base = min(100, base + 10)
    return base


def _migrate_custody_columns(con: sqlite3.Connection) -> None:
    """Tamper-evident hash chain columns (added for chain-of-custody hardening)."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(evidence_vault)").fetchall()}
    if "prev_chain_hash" not in cols:
        con.execute("ALTER TABLE evidence_vault ADD COLUMN prev_chain_hash TEXT DEFAULT ''")
    if "chain_hash" not in cols:
        con.execute("ALTER TABLE evidence_vault ADD COLUMN chain_hash TEXT DEFAULT ''")
    # RFC-3161 TSA token column (court-admissibility hardening). The token is
    #附加 to the row; it is NOT part of the chain_hash formula, so existing
    # exhibits' chains remain valid and verifiable.
    if "tsa_token" not in cols:
        con.execute("ALTER TABLE evidence_vault ADD COLUMN tsa_token TEXT DEFAULT ''")


def _chain_tip(con: sqlite3.Connection) -> str:
    row = con.execute(
        "SELECT chain_hash FROM evidence_vault WHERE chain_hash != '' ORDER BY created_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return row["chain_hash"] if row else "GENESIS"


def _compute_chain_hash(prev: str, eid: str, content_hash: str, created_at: str) -> str:
    return _sha256(f"{prev}|{eid}|{content_hash}|{created_at}")


def init_evidence_tables() -> None:
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS evidence_vault (
            id            TEXT PRIMARY KEY,
            case_id       TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            title         TEXT NOT NULL,
            subject       TEXT DEFAULT '',
            chain         TEXT DEFAULT '',
            content_hash  TEXT NOT NULL,
            content_json  TEXT NOT NULL,
            quality_score INTEGER DEFAULT 0,
            tags          TEXT DEFAULT '',
            analyst_notes TEXT DEFAULT '',
            created_at    TEXT NOT NULL,
            FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS evidence_audit_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            evidence_id  TEXT NOT NULL REFERENCES evidence_vault(id) ON DELETE CASCADE,
            action       TEXT NOT NULL,
            actor        TEXT DEFAULT 'system',
            detail       TEXT DEFAULT '',
            timestamp    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_case   ON evidence_vault(case_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_type   ON evidence_vault(evidence_type);
        CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence_vault(subject);
        CREATE INDEX IF NOT EXISTS idx_audit_evidence  ON evidence_audit_log(evidence_id);
        """)
        _migrate_custody_columns(con)


def save_evidence(
    case_id:       str,
    evidence_type: str,
    title:         str,
    content:       dict,
    subject:       str = "",
    chain:         str = "",
    tags:          list[str] | None = None,
    analyst_notes: str = "",
    actor:         str = "system",
) -> dict:
    """
    Save an evidence artifact. Returns the saved evidence record.
    Automatically hashes content and scores quality.
    """
    eid          = str(uuid.uuid4())
    now          = _now()
    content_str  = json.dumps(content, ensure_ascii=False, sort_keys=True)
    content_hash = _sha256(content_str)
    quality      = _quality_score(evidence_type, content)
    tags_str     = json.dumps(tags or [])

    # RFC-3161 trusted timestamp (optional). When config.TSA_URL is set, submit
    # the content to a TSA and store the verified token alongside the hash chain.
    # Best-effort: never blocks a save on a TSA outage. The token is NOT part of
    # the chain_hash formula, so backward compatibility with existing chains holds.
    tsa_token_str = ""
    tsa_note = ""
    try:
        import config as _cfg
        if getattr(_cfg, "TSA_URL", ""):
            import tsa_client
            tsa_result = tsa_client.request_timestamp(content_str.encode("utf-8"))
            if tsa_result.get("tsa_verified"):
                tsa_token_str = tsa_result.get("tsa_token_b64", "")
                tsa_note = f" (RFC-3161 TSA verified @ {tsa_result.get('tsa_timestamp','')})"
            elif tsa_result.get("tsa_error"):
                tsa_note = f" (TSA attempted: {tsa_result.get('tsa_error')})"
    except Exception:
        pass  # TSA is purely additive; never fail a save here

    with _conn() as con:
        _migrate_custody_columns(con)
        prev = _chain_tip(con)
        chain_hash = _compute_chain_hash(prev, eid, content_hash, now)
        con.execute(
            """INSERT INTO evidence_vault
               (id, case_id, evidence_type, title, subject, chain,
                content_hash, content_json, quality_score, tags, analyst_notes, created_at,
                prev_chain_hash, chain_hash, tsa_token)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (eid, case_id, evidence_type, title, subject, chain,
             content_hash, content_str, quality, tags_str, analyst_notes, now,
             prev, chain_hash, tsa_token_str),
        )
        con.execute(
            """INSERT INTO evidence_audit_log (evidence_id, action, actor, detail, timestamp)
               VALUES (?,?,?,?,?)""",
            (eid, "created", actor,
             f"Evidence artifact '{title}' saved (chain {chain_hash[:16]}… ← {prev[:16]}…){tsa_note}", now),
        )

    return get_evidence(eid)  # type: ignore[return-value]


def verify_chain(case_id: str | None = None) -> dict:
    """
    Verify the tamper-evident hash chain.
    Recomputes every content hash and chain link; returns first break if any.
    The chain is GLOBAL (across cases) so a deleted or reordered record in any
    case breaks verification — by design.
    """
    with _conn() as con:
        _migrate_custody_columns(con)
        rows = con.execute(
            "SELECT id, case_id, title, content_json, content_hash, created_at,"
            "       prev_chain_hash, chain_hash"
            " FROM evidence_vault WHERE chain_hash != ''"
            " ORDER BY created_at ASC, rowid ASC"
        ).fetchall()
        # Load tombstoned (authorized-deleted) record hashes so chain gaps from
        # soft-deletions are tolerated rather than flagged as tampering (bug #7).
        try:
            deleted_hashes = {r["chain_hash"] for r in con.execute(
                "SELECT chain_hash FROM evidence_deletions WHERE chain_hash != ''"
            ).fetchall()}
        except sqlite3.OperationalError:
            deleted_hashes = set()

    prev = "GENESIS"
    checked = 0
    deleted_gaps = 0
    problems: list[dict] = []
    for row in rows:
        r = dict(row)
        recomputed_content = _sha256(r["content_json"])
        if recomputed_content != r["content_hash"]:
            problems.append({"id": r["id"], "title": r["title"], "error": "content_hash mismatch (content altered)"})
        expected = _compute_chain_hash(prev, r["id"], r["content_hash"], r["created_at"])
        if expected != r["chain_hash"]:
            # If the gap is caused by an authorized soft-deletion, tolerate it.
            if r["prev_chain_hash"] in deleted_hashes:
                deleted_gaps += 1
            else:
                problems.append({"id": r["id"], "title": r["title"], "error": "chain link broken (record inserted, removed, or reordered)"})
        prev = r["chain_hash"]
        checked += 1

    case_records = 0
    if case_id:
        with _conn() as con:
            case_records = con.execute(
                "SELECT COUNT(*) AS n FROM evidence_vault WHERE case_id = ?", (case_id,)
            ).fetchone()["n"]

    return {
        "valid": len(problems) == 0,
        "records_checked": checked,
        "case_records": case_records,
        "chain_tip": prev,
        "problems": problems[:20],
        "authorized_deletions": deleted_gaps,
        "verified_at": _now(),
        "note": "Chain is global and append-only; authorized soft-deletions are tracked "
                "in evidence_deletions and tolerated. Legacy pre-custody records excluded.",
    }


def register_export(
    case_id: str,
    kind: str,
    title: str,
    content: dict,
    subject: str = "",
    actor: str = "system",
) -> dict:
    """Register any export (exhibit, report, regulatory draft) into the custody chain."""
    return save_evidence(
        case_id=case_id,
        evidence_type=kind,
        title=title,
        content=content,
        subject=subject,
        tags=["export", kind],
        actor=actor,
    )


def get_evidence(evidence_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM evidence_vault WHERE id = ?", (evidence_id,)
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["content"] = json.loads(item.pop("content_json") or "{}")
        except json.JSONDecodeError:
            item["content"] = {}
        try:
            item["tags"] = json.loads(item.get("tags") or "[]")
        except json.JSONDecodeError:
            item["tags"] = []
        return item


def list_evidence(
    case_id: str,
    evidence_type: str | None = None,
    subject: str | None = None,
    limit: int = 100,
) -> list[dict]:
    clauses = ["case_id = ?"]
    params: list[Any] = [case_id]
    if evidence_type:
        clauses.append("evidence_type = ?")
        params.append(evidence_type)
    if subject:
        clauses.append("subject LIKE ?")
        params.append(f"%{subject}%")
    params.append(limit)
    with _conn() as con:
        rows = con.execute(
            f"""SELECT id, case_id, evidence_type, title, subject, chain,
                       content_hash, quality_score, tags, analyst_notes, created_at
                FROM evidence_vault
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT ?""",
            params,
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["tags"] = json.loads(item.get("tags") or "[]")
        except json.JSONDecodeError:
            item["tags"] = []
        result.append(item)
    return result


def get_audit_log(evidence_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT * FROM evidence_audit_log
               WHERE evidence_id = ? ORDER BY timestamp ASC""",
            (evidence_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def annotate_evidence(
    evidence_id: str,
    notes: str,
    tags: list[str] | None = None,
    actor: str = "analyst",
) -> dict | None:
    now = _now()
    with _conn() as con:
        # Existence check FIRST: the audit log has a foreign key to evidence_vault,
        # so inserting an audit row for a non-existent evidence_id raises
        # IntegrityError (surfaced as a 500). Return None so the router emits 404.
        exists = con.execute(
            "SELECT 1 FROM evidence_vault WHERE id = ?", (evidence_id,)
        ).fetchone()
        if not exists:
            return None
        updates: dict[str, Any] = {"analyst_notes": notes}
        if tags is not None:
            updates["tags"] = json.dumps(tags)
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        con.execute(
            f"UPDATE evidence_vault SET {set_clause} WHERE id = ?",
            list(updates.values()) + [evidence_id],
        )
        con.execute(
            """INSERT INTO evidence_audit_log (evidence_id, action, actor, detail, timestamp)
               VALUES (?,?,?,?,?)""",
            (evidence_id, "annotated", actor, f"Notes/tags updated", now),
        )
    return get_evidence(evidence_id)


def delete_evidence(evidence_id: str, actor: str = "analyst") -> bool:
    """Soft-delete an evidence artifact, preserving chain-of-custody integrity.

    Bug #7 fix: the old hard-delete dropped the audit trail and broke the global
    hash chain for ALL cases. We now record a 'deleted' audit entry on a side
    table BEFORE removing the row, so verify_chain() can exclude tombstoned rows
    while the deletion itself is still auditable.
    """
    now = _now()
    with _conn() as con:
        # 1. Capture a deletion record BEFORE the cascade removes the audit log
        row = con.execute(
            "SELECT id, case_id, title, content_hash, chain_hash FROM evidence_vault WHERE id=?",
            (evidence_id,),
        ).fetchone()
        if not row:
            return False
        # 2. Persist the deletion event to a tombstone table (survives the cascade)
        con.execute(
            """CREATE TABLE IF NOT EXISTS evidence_deletions (
                evidence_id   TEXT PRIMARY KEY,
                case_id       TEXT,
                title         TEXT,
                content_hash  TEXT,
                chain_hash    TEXT,
                deleted_by    TEXT,
                deleted_at    TEXT NOT NULL
            )"""
        )
        con.execute(
            """INSERT OR REPLACE INTO evidence_deletions
               (evidence_id, case_id, title, content_hash, chain_hash, deleted_by, deleted_at)
               VALUES (?,?,?,?,?,?,?)""",
            (row["id"], row["case_id"], row["title"], row["content_hash"],
             row["chain_hash"], actor, now),
        )
        # 3. Now hard-delete the row (cascade removes its audit log, but the
        #    tombstone preserves the fact + content hash for chain verification)
        cur = con.execute("DELETE FROM evidence_vault WHERE id = ?", (evidence_id,))
    return cur.rowcount > 0


def case_evidence_summary(case_id: str) -> dict:
    with _conn() as con:
        rows = con.execute(
            """SELECT evidence_type, COUNT(*) as cnt, AVG(quality_score) as avg_q
               FROM evidence_vault WHERE case_id = ?
               GROUP BY evidence_type""",
            (case_id,),
        ).fetchall()
        total = con.execute(
            "SELECT COUNT(*) FROM evidence_vault WHERE case_id = ?", (case_id,)
        ).fetchone()[0]
        avg_q = con.execute(
            "SELECT AVG(quality_score) FROM evidence_vault WHERE case_id = ?", (case_id,)
        ).fetchone()[0]

    by_type = {r["evidence_type"]: {"count": r["cnt"], "avg_quality": round(r["avg_q"] or 0, 1)}
               for r in rows}
    return {
        "case_id":        case_id,
        "total":          total,
        "avg_quality":    round(float(avg_q or 0), 1),
        "by_type":        by_type,
    }
