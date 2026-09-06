"""
SQLite database layer for CryptoOSINT case management and local evidence.
Tables: cases, case_addresses, case_notes, address_cache_v2, graph evidence.
"""
import sqlite3
import uuid
import json
from datetime import datetime, timezone
from typing import Any, Optional

# Centralized DB path — overridable via DB_PATH env for Docker volumes.
import config as _config
DB_PATH = _config.DB_PATH


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def get_connection() -> sqlite3.Connection:
    return _conn()


def init_db() -> None:
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            description  TEXT DEFAULT '',
            status       TEXT DEFAULT 'active',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_addresses (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id      TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            address      TEXT NOT NULL,
            chain        TEXT DEFAULT '',
            label        TEXT DEFAULT '',
            notes        TEXT DEFAULT '',
            risk_score   INTEGER DEFAULT -1,
            risk_level   TEXT DEFAULT '',
            added_at     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_notes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id      TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            note         TEXT NOT NULL,
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS address_cache (
            address      TEXT PRIMARY KEY,
            intel_json   TEXT,
            risk_json    TEXT,
            cached_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS address_cache_v2 (
            chain        TEXT NOT NULL DEFAULT '',
            address      TEXT NOT NULL,
            intel_json   TEXT,
            risk_json    TEXT,
            cached_at    TEXT NOT NULL,
            PRIMARY KEY (chain, address)
        );
        CREATE TABLE IF NOT EXISTS forensic_runs (
            id           TEXT PRIMARY KEY,
            subject      TEXT NOT NULL,
            chain        TEXT DEFAULT '',
            algorithm_version TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS graph_addresses (
            address      TEXT NOT NULL,
            chain        TEXT NOT NULL DEFAULT '',
            first_seen   TEXT,
            last_seen    TEXT,
            label        TEXT DEFAULT '',
            role         TEXT DEFAULT '',
            risk_score   INTEGER DEFAULT -1,
            features_json TEXT DEFAULT '{}',
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (chain, address)
        );
        CREATE TABLE IF NOT EXISTS graph_transactions (
            tx_hash      TEXT NOT NULL,
            chain        TEXT NOT NULL DEFAULT '',
            timestamp    TEXT DEFAULT '',
            token        TEXT DEFAULT '',
            value        REAL DEFAULT 0,
            raw_json     TEXT DEFAULT '{}',
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (chain, tx_hash)
        );
        CREATE TABLE IF NOT EXISTS graph_edges (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       TEXT REFERENCES forensic_runs(id) ON DELETE SET NULL,
            chain        TEXT NOT NULL DEFAULT '',
            tx_hash      TEXT DEFAULT '',
            source       TEXT NOT NULL,
            target       TEXT NOT NULL,
            token        TEXT DEFAULT '',
            value        REAL DEFAULT 0,
            timestamp    TEXT DEFAULT '',
            evidence_json TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS algorithm_outputs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       TEXT NOT NULL REFERENCES forensic_runs(id) ON DELETE CASCADE,
            address      TEXT NOT NULL,
            chain        TEXT DEFAULT '',
            algorithm    TEXT NOT NULL,
            output_json  TEXT NOT NULL,
            confidence   REAL DEFAULT 0,
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS local_labels (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chain        TEXT NOT NULL DEFAULT '',
            address      TEXT NOT NULL,
            label        TEXT NOT NULL,
            category     TEXT DEFAULT '',
            risk_weight  INTEGER DEFAULT 0,
            confidence   REAL DEFAULT 1,
            source       TEXT DEFAULT 'investigator',
            notes        TEXT DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            UNIQUE(chain, address, label, source)
        );
        CREATE TABLE IF NOT EXISTS report_artifacts (
            id           TEXT PRIMARY KEY,
            subject      TEXT NOT NULL,
            chain        TEXT DEFAULT '',
            case_id      TEXT DEFAULT '',
            title        TEXT NOT NULL,
            format       TEXT NOT NULL,
            content      TEXT NOT NULL,
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clustering_runs (
            id           TEXT PRIMARY KEY,
            subject      TEXT NOT NULL,
            chain        TEXT DEFAULT '',
            cluster_json TEXT NOT NULL,
            methods      TEXT DEFAULT '',
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cashout_sessions (
            id           TEXT PRIMARY KEY,
            subject      TEXT NOT NULL,
            chain        TEXT DEFAULT '',
            result_json  TEXT NOT NULL,
            risk_level   TEXT DEFAULT '',
            created_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_clustering_runs_subject ON clustering_runs(subject);
        CREATE INDEX IF NOT EXISTS idx_cashout_sessions_subject ON cashout_sessions(subject);
        CREATE INDEX IF NOT EXISTS idx_case_addresses_case ON case_addresses(case_id);
        CREATE INDEX IF NOT EXISTS idx_case_notes_case ON case_notes(case_id);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(chain, source);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(chain, target);
        CREATE INDEX IF NOT EXISTS idx_algorithm_outputs_run ON algorithm_outputs(run_id);
        CREATE INDEX IF NOT EXISTS idx_local_labels_address ON local_labels(chain, address);
        CREATE INDEX IF NOT EXISTS idx_report_artifacts_case ON report_artifacts(case_id);
        """)
        con.execute("""
            DELETE FROM case_addresses
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM case_addresses
                GROUP BY case_id, address, chain
            )
        """)
        con.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_case_addresses_unique
            ON case_addresses(case_id, address, chain)
        """)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ── Cases ─────────────────────────────────────────────────────────────────────

def create_case(name: str, description: str = "") -> dict:
    cid = str(uuid.uuid4())
    now = _now()
    with _conn() as con:
        con.execute(
            "INSERT INTO cases (id, name, description, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (cid, name, description, "active", now, now),
        )
    return get_case(cid)  # type: ignore[return-value]


def list_cases() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """
            SELECT c.*,
                   COUNT(ca.id) AS address_count,
                   MAX(ca.risk_score) AS max_risk_score
            FROM cases c
            LEFT JOIN case_addresses ca ON ca.case_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            """
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_case(case_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not row:
            return None
        case = _row_to_dict(row)
        case["addresses"] = [
            _row_to_dict(r)
            for r in con.execute(
                "SELECT * FROM case_addresses WHERE case_id = ? ORDER BY added_at",
                (case_id,),
            ).fetchall()
        ]
        case["notes"] = [
            _row_to_dict(r)
            for r in con.execute(
                "SELECT * FROM case_notes WHERE case_id = ? ORDER BY created_at",
                (case_id,),
            ).fetchall()
        ]
    return case


def update_case(case_id: str, **kwargs: Any) -> Optional[dict]:
    allowed = {"name", "description", "status"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_case(case_id)
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _conn() as con:
        con.execute(
            f"UPDATE cases SET {set_clause} WHERE id = ?",
            list(updates.values()) + [case_id],
        )
    return get_case(case_id)


def delete_case(case_id: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    return cur.rowcount > 0


# ── Case Addresses ─────────────────────────────────────────────────────────────

def add_address_to_case(
    case_id: str,
    address: str,
    chain: str = "",
    label: str = "",
    notes: str = "",
    risk_score: int = -1,
    risk_level: str = "",
) -> dict:
    now = _now()
    with _conn() as con:
        con.execute(
            """INSERT INTO case_addresses
               (case_id, address, chain, label, notes, risk_score, risk_level, added_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(case_id, address, chain) DO UPDATE SET
                   label=excluded.label,
                   notes=excluded.notes,
                   risk_score=excluded.risk_score,
                   risk_level=excluded.risk_level""",
            (case_id, address, chain, label, notes, risk_score, risk_level, now),
        )
        con.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (now, case_id))
    return {"case_id": case_id, "address": address}


def remove_address_from_case(case_id: str, address: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM case_addresses WHERE case_id = ? AND address = ?",
            (case_id, address),
        )
    return cur.rowcount > 0


def update_case_address_risk(case_id: str, address: str, risk_score: int, risk_level: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE case_addresses SET risk_score=?, risk_level=? WHERE case_id=? AND address=?",
            (risk_score, risk_level, case_id, address),
        )


# ── Case Notes ────────────────────────────────────────────────────────────────

def add_note(case_id: str, note: str) -> dict:
    now = _now()
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO case_notes (case_id, note, created_at) VALUES (?,?,?)",
            (case_id, note, now),
        )
        con.execute("UPDATE cases SET updated_at = ? WHERE id = ?", (now, case_id))
    return {"id": cur.lastrowid, "case_id": case_id, "note": note, "created_at": now}


def delete_note(note_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM case_notes WHERE id = ?", (note_id,))
    return cur.rowcount > 0


# ── Address cache ─────────────────────────────────────────────────────────────

def cache_get(address: str, chain: str = "") -> tuple[Optional[str], Optional[str]]:
    with _conn() as con:
        row = con.execute(
            "SELECT intel_json, risk_json FROM address_cache_v2 WHERE chain = ? AND address = ?",
            (chain, address),
        ).fetchone()
    if row:
        return row["intel_json"], row["risk_json"]
    return None, None


def cache_set(address: str, intel_json: str, risk_json: str, chain: str = "") -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO address_cache_v2 (chain, address, intel_json, risk_json, cached_at) VALUES (?,?,?,?,?)",
            (chain, address, intel_json, risk_json, _now()),
        )


# -- Local forensic evidence ---------------------------------------------------

def save_forensic_run(
    subject: str,
    chain: str,
    summary: dict,
    addresses: list[dict],
    transactions: list[dict],
    edges: list[dict],
    outputs: list[dict],
    algorithm_version: str,
) -> str:
    run_id = str(uuid.uuid4())
    now = _now()
    with _conn() as con:
        con.execute(
            """INSERT INTO forensic_runs
               (id, subject, chain, algorithm_version, summary_json, created_at)
               VALUES (?,?,?,?,?,?)""",
            (run_id, subject, chain, algorithm_version, json.dumps(summary), now),
        )
        for addr in addresses:
            con.execute(
                """INSERT OR REPLACE INTO graph_addresses
                   (address, chain, first_seen, last_seen, label, role, risk_score, features_json, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    addr.get("address", ""),
                    addr.get("chain", chain) or "",
                    addr.get("first_seen", ""),
                    addr.get("last_seen", ""),
                    addr.get("label", ""),
                    addr.get("role", ""),
                    int(addr.get("risk_score", -1) or -1),
                    json.dumps(addr.get("features", {})),
                    now,
                ),
            )
        for tx in transactions:
            tx_hash = tx.get("hash") or tx.get("txid") or tx.get("tx_hash") or ""
            if not tx_hash:
                continue
            con.execute(
                """INSERT OR REPLACE INTO graph_transactions
                   (tx_hash, chain, timestamp, token, value, raw_json, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    tx_hash,
                    tx.get("chain", chain) or "",
                    tx.get("time") or tx.get("timestamp") or "",
                    tx.get("token", ""),
                    float(tx.get("value", 0) or 0),
                    json.dumps(tx),
                    now,
                ),
            )
        for edge in edges:
            con.execute(
                """INSERT INTO graph_edges
                   (run_id, chain, tx_hash, source, target, token, value, timestamp, evidence_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    edge.get("chain", chain) or "",
                    edge.get("hash") or edge.get("tx_hash") or "",
                    edge.get("source", ""),
                    edge.get("target", ""),
                    edge.get("token", ""),
                    float(edge.get("value", 0) or 0),
                    edge.get("time") or edge.get("timestamp") or "",
                    json.dumps(edge.get("evidence", {})),
                ),
            )
        for output in outputs:
            con.execute(
                """INSERT INTO algorithm_outputs
                   (run_id, address, chain, algorithm, output_json, confidence, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    run_id,
                    output.get("address", subject),
                    output.get("chain", chain) or "",
                    output.get("algorithm", ""),
                    json.dumps(output.get("output", {})),
                    float(output.get("confidence", 0) or 0),
                    now,
                ),
            )
    return run_id


def list_forensic_runs(limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT id, subject, chain, algorithm_version, summary_json, created_at
               FROM forensic_runs
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    out = []
    for row in rows:
        item = _row_to_dict(row)
        try:
            item["summary"] = json.loads(item.pop("summary_json") or "{}")
        except json.JSONDecodeError:
            item["summary"] = {}
        out.append(item)
    return out


def get_forensic_run(run_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            """SELECT id, subject, chain, algorithm_version, summary_json, created_at
               FROM forensic_runs WHERE id = ?""",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        item = _row_to_dict(row)
        try:
            item["summary"] = json.loads(item.pop("summary_json") or "{}")
        except json.JSONDecodeError:
            item["summary"] = {}
        return item


def latest_forensic_run(subject: str, chain: str = "") -> Optional[dict]:
    params: list[Any] = [subject]
    chain_clause = ""
    if chain:
        chain_clause = "AND chain = ?"
        params.append(chain)
    with _conn() as con:
        row = con.execute(
            f"""SELECT id, subject, chain, algorithm_version, summary_json, created_at
                FROM forensic_runs
                WHERE subject = ? {chain_clause}
                ORDER BY created_at DESC
                LIMIT 1""",
            params,
        ).fetchone()
    if not row:
        return None
    item = _row_to_dict(row)
    try:
        item["summary"] = json.loads(item.pop("summary_json") or "{}")
    except json.JSONDecodeError:
        item["summary"] = {}
    return item


# -- Investigator-owned label intelligence ------------------------------------

def upsert_local_label(
    address: str,
    chain: str = "",
    label: str = "",
    category: str = "",
    risk_weight: int = 0,
    confidence: float = 1.0,
    source: str = "investigator",
    notes: str = "",
) -> dict:
    now = _now()
    with _conn() as con:
        con.execute(
            """INSERT INTO local_labels
               (chain, address, label, category, risk_weight, confidence, source, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(chain, address, label, source) DO UPDATE SET
                   category=excluded.category,
                   risk_weight=excluded.risk_weight,
                   confidence=excluded.confidence,
                   notes=excluded.notes,
                   updated_at=excluded.updated_at""",
            (chain, address, label, category, risk_weight, confidence, source, notes, now, now),
        )
        row = con.execute(
            """SELECT * FROM local_labels
               WHERE chain=? AND address=? AND label=? AND source=?""",
            (chain, address, label, source),
        ).fetchone()
    return _row_to_dict(row)


def list_local_labels(query: str = "", chain: str = "", limit: int = 200) -> list[dict]:
    clauses = []
    params: list[Any] = []
    if query:
        clauses.append("(address LIKE ? OR label LIKE ? OR category LIKE ? OR notes LIKE ?)")
        q = f"%{query}%"
        params.extend([q, q, q, q])
    if chain:
        clauses.append("chain = ?")
        params.append(chain)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    with _conn() as con:
        rows = con.execute(
            f"""SELECT * FROM local_labels
                {where}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?""",
            params,
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def labels_for_address(address: str, chain: str = "") -> list[dict]:
    params: list[Any] = [address]
    chain_clause = ""
    if chain:
        chain_clause = "AND chain = ?"
        params.append(chain)
    with _conn() as con:
        rows = con.execute(
            f"""SELECT * FROM local_labels
                WHERE address = ? {chain_clause}
                ORDER BY risk_weight DESC, confidence DESC""",
            params,
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_local_label(label_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM local_labels WHERE id = ?", (label_id,))
    return cur.rowcount > 0


def save_report_artifact(
    subject: str,
    title: str,
    content: str,
    chain: str = "",
    case_id: str = "",
    fmt: str = "html",
) -> str:
    rid = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            """INSERT INTO report_artifacts
               (id, subject, chain, case_id, title, format, content, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rid, subject, chain, case_id, title, fmt, content, _now()),
        )
    return rid
