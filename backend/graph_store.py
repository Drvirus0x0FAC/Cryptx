"""
Graph persistence & incremental investigation store.

Turns one-shot NexusGraph/Trace queries into living investigations:
  - Save a full investigation graph (nodes + edges + run metadata) keyed by subject
  - Re-open it later without re-fetching from external APIs
  - Expand incrementally: add a single node's neighbors → append to the existing graph
    rather than rebuilding from scratch
  - Diff two snapshots to show what changed since the investigator's last visit

Storage is SQLite (consistent with the rest of the app — no new infra required).
Nodes and edges are normalized into tables for efficient adjacency queries; full
graph JSON is also cached for fast page loads.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import database as db

DB_PATH = db.DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_graph_store_tables() -> None:
    with db.get_connection() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS investigations (
            id            TEXT PRIMARY KEY,
            subject       TEXT NOT NULL,
            chain         TEXT DEFAULT '',
            name          TEXT DEFAULT '',
            case_id       TEXT DEFAULT '',
            params_json   TEXT DEFAULT '{}',
            graph_json    TEXT DEFAULT '{}',
            node_count    INTEGER DEFAULT 0,
            edge_count    INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS investigation_nodes (
            investigation_id TEXT NOT NULL,
            address          TEXT NOT NULL,
            chain            TEXT DEFAULT '',
            label            TEXT DEFAULT '',
            node_type        TEXT DEFAULT 'unknown',
            risk_score       INTEGER DEFAULT -1,
            extra_json       TEXT DEFAULT '{}',
            first_seen       TEXT DEFAULT '',
            updated_at       TEXT NOT NULL,
            PRIMARY KEY (investigation_id, chain, address)
        );
        CREATE TABLE IF NOT EXISTS investigation_edges (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            investigation_id TEXT NOT NULL,
            source           TEXT NOT NULL,
            target           TEXT NOT NULL,
            chain            TEXT DEFAULT '',
            tx_hash          TEXT DEFAULT '',
            token            TEXT DEFAULT '',
            value            REAL DEFAULT 0,
            value_usd        REAL DEFAULT 0,
            timestamp        TEXT DEFAULT '',
            edge_type        TEXT DEFAULT 'transfer',
            extra_json       TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_inv_subject ON investigations(subject);
        CREATE INDEX IF NOT EXISTS idx_inv_case ON investigations(case_id);
        CREATE INDEX IF NOT EXISTS idx_invnodes_addr ON investigation_nodes(address);
        CREATE INDEX IF NOT EXISTS idx_invedges_inv ON investigation_edges(investigation_id);
        CREATE INDEX IF NOT EXISTS idx_invedges_source ON investigation_edges(source);
        CREATE INDEX IF NOT EXISTS idx_invedges_target ON investigation_edges(target);
        CREATE TABLE IF NOT EXISTS investigation_snapshots (
            id               TEXT PRIMARY KEY,
            investigation_id TEXT NOT NULL,
            node_count       INTEGER,
            edge_count       INTEGER,
            graph_json       TEXT,
            note             TEXT DEFAULT '',
            created_at       TEXT NOT NULL
        );
        """)


def _norm_addr(v: Any) -> str:
    s = str(v or "").strip()
    return s.lower() if s.startswith("0x") else s


def save_investigation(
    subject: str,
    chain: str,
    graph: dict,
    name: str = "",
    case_id: str = "",
    params: Optional[dict] = None,
    investigation_id: str = "",
) -> dict:
    """Persist (or update) an investigation graph. Returns the investigation record."""
    init_graph_store_tables()
    now = _now()
    inv_id = investigation_id or str(uuid.uuid4())
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    with db.get_connection() as con:
        exists = con.execute(
            "SELECT id FROM investigations WHERE id=?", (inv_id,)
        ).fetchone()
        if exists:
            con.execute(
                """UPDATE investigations SET graph_json=?, node_count=?, edge_count=?,
                   chain=?, updated_at=? WHERE id=?""",
                (json.dumps(graph), len(nodes), len(edges), chain, now, inv_id),
            )
        else:
            con.execute(
                """INSERT INTO investigations
                   (id, subject, chain, name, case_id, params_json, graph_json,
                    node_count, edge_count, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (inv_id, _norm_addr(subject), chain, name or f"Investigation {subject[:12]}…",
                 case_id, json.dumps(params or {}), json.dumps(graph),
                 len(nodes), len(edges), now, now),
            )
        # Upsert nodes
        for node in nodes:
            addr = _norm_addr(node.get("address") or node.get("id") or "")
            if not addr:
                continue
            con.execute(
                """INSERT INTO investigation_nodes
                   (investigation_id, address, chain, label, node_type, risk_score,
                    extra_json, first_seen, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(investigation_id, chain, address) DO UPDATE SET
                     label=excluded.label,
                     node_type=excluded.node_type,
                     risk_score=excluded.risk_score,
                     extra_json=excluded.extra_json,
                     updated_at=excluded.updated_at""",
                (inv_id, addr, node.get("chain", chain),
                 node.get("label") or node.get("name") or "",
                 node.get("type") or node.get("node_type") or "unknown",
                 int(node.get("risk_score", node.get("risk", -1)) or -1),
                 json.dumps({k: v for k, v in node.items()
                             if k not in ("address", "id", "chain", "label", "type", "risk_score", "risk")},
                            default=str),
                 node.get("first_seen", ""),
                 now),
            )
        # Replace edges (delete + insert in one transaction)
        con.execute("DELETE FROM investigation_edges WHERE investigation_id=?", (inv_id,))
        for edge in edges:
            src = _norm_addr(edge.get("source") or edge.get("from") or "")
            tgt = _norm_addr(edge.get("target") or edge.get("to") or "")
            if not src or not tgt:
                continue
            con.execute(
                """INSERT INTO investigation_edges
                   (investigation_id, source, target, chain, tx_hash, token, value,
                    value_usd, timestamp, edge_type, extra_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (inv_id, src, tgt, edge.get("chain", chain),
                 edge.get("tx_hash") or edge.get("hash") or "",
                 edge.get("token") or edge.get("asset") or "",
                 float(edge.get("value") or edge.get("amount") or 0),
                 float(edge.get("value_usd") or 0),
                 edge.get("timestamp") or edge.get("time") or "",
                 edge.get("edge_type") or edge.get("type") or "transfer",
                 json.dumps({k: v for k, v in edge.items()
                             if k not in ("source", "target", "from", "to", "tx_hash",
                                          "hash", "token", "asset", "value", "amount",
                                          "value_usd", "timestamp", "time", "type", "edge_type")},
                            default=str)),
            )
        row = con.execute("SELECT * FROM investigations WHERE id=?", (inv_id,)).fetchone()
    return _row_to_investigation(row) if row else {}


def expand_investigation(
    investigation_id: str,
    new_graph: dict,
) -> dict:
    """Merge a freshly-fetched sub-graph (e.g. one node's neighbors) into an existing
    investigation. Nodes are unioned; new edges are appended. Returns the updated graph.

    This is the 'incremental' operation: instead of rebuilding the whole trace from
    the subject each time, the investigator expands one node and we append the result.
    """
    init_graph_store_tables()
    inv = get_investigation(investigation_id)
    if not inv:
        raise ValueError(f"investigation {investigation_id} not found")
    existing = inv["graph"]
    existing_nodes = {n.get("address") or n.get("id"): n for n in (existing.get("nodes") or [])}
    new_nodes = new_graph.get("nodes") or []
    merged_nodes = list(existing_nodes.values())
    seen = set(existing_nodes.keys())
    for node in new_nodes:
        key = node.get("address") or node.get("id")
        if key and key not in seen:
            seen.add(key)
            merged_nodes.append(node)
        elif key:
            # merge: prefer richer data (non-empty label/type)
            cur = existing_nodes[key]
            for k in ("label", "type", "risk_score"):
                if not cur.get(k) and node.get(k):
                    cur[k] = node[k]
    # edges: dedupe by (source, target, tx_hash, token)
    edge_keys: set[tuple] = set()
    merged_edges = list(existing.get("edges") or [])
    for e in merged_edges:
        edge_keys.add((_norm_addr(e.get("source") or e.get("from")),
                       _norm_addr(e.get("target") or e.get("to")),
                       e.get("tx_hash") or e.get("hash") or "",
                       e.get("token") or e.get("asset") or ""))
    for e in (new_graph.get("edges") or []):
        k = (_norm_addr(e.get("source") or e.get("from")),
             _norm_addr(e.get("target") or e.get("to")),
             e.get("tx_hash") or e.get("hash") or "",
             e.get("token") or e.get("asset") or "")
        if k not in edge_keys:
            edge_keys.add(k)
            merged_edges.append(e)
    merged = {"nodes": merged_nodes, "edges": merged_edges,
              "subject": existing.get("subject") or inv["subject"],
              "chain": inv["chain"]}
    return save_investigation(inv["subject"], inv["chain"], merged,
                              name=inv.get("name", ""), case_id=inv.get("case_id", ""),
                              investigation_id=investigation_id)


def snapshot_investigation(investigation_id: str, note: str = "") -> dict:
    """Save a point-in-time snapshot for diffing later (what changed since last visit)."""
    init_graph_store_tables()
    inv = get_investigation(investigation_id)
    if not inv:
        raise ValueError("investigation not found")
    sid = str(uuid.uuid4())
    now = _now()
    with db.get_connection() as con:
        con.execute(
            """INSERT INTO investigation_snapshots
               (id, investigation_id, node_count, edge_count, graph_json, note, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (sid, investigation_id, inv["node_count"], inv["edge_count"],
             json.dumps(inv["graph"]), note, now),
        )
    return {"id": sid, "investigation_id": investigation_id, "created_at": now, "note": note}


def diff_snapshots(inv_id: str, older_snap_id: str, newer_snap_id: str = "") -> dict:
    """Diff two snapshots: added/removed nodes & edges, risk deltas."""
    init_graph_store_tables()
    with db.get_connection() as con:
        old = con.execute("SELECT * FROM investigation_snapshots WHERE id=?", (older_snap_id,)).fetchone()
        new = con.execute(
            "SELECT * FROM investigation_snapshots WHERE id=? ORDER BY created_at DESC LIMIT 1",
            (newer_snap_id,)
        ).fetchone() if newer_snap_id else con.execute(
            "SELECT * FROM investigations WHERE id=?", (inv_id,)
        ).fetchone()
    if not old or not new:
        raise ValueError("snapshot(s) not found")
    old_graph = json.loads(old["graph_json"] or "{}") if "graph_json" in old.keys() else json.loads(new["graph_json"] or "{}")
    new_graph = json.loads(new["graph_json"] or "{}") if "graph_json" in new.keys() else {}
    old_nodes = {_norm_addr(n.get("address") or n.get("id")): n for n in (old_graph.get("nodes") or [])}
    new_nodes = {_norm_addr(n.get("address") or n.get("id")): n for n in (new_graph.get("nodes") or [])}
    added = [a for a in new_nodes if a not in old_nodes]
    removed = [a for a in old_nodes if a not in new_nodes]
    risk_deltas = []
    for a, n in new_nodes.items():
        if a in old_nodes:
            old_r = int(old_nodes[a].get("risk_score", -1) or -1)
            new_r = int(n.get("risk_score", -1) or -1)
            if old_r != new_r:
                risk_deltas.append({"address": a, "old": old_r, "new": new_r})
    return {
        "added_nodes": len(added),
        "removed_nodes": len(removed),
        "added_addresses": added[:100],
        "removed_addresses": removed[:100],
        "risk_deltas": risk_deltas[:100],
        "old_count": len(old_nodes),
        "new_count": len(new_nodes),
    }


def list_investigations(case_id: str = "", limit: int = 50) -> list[dict]:
    init_graph_store_tables()
    with db.get_connection() as con:
        if case_id:
            rows = con.execute(
                "SELECT id, subject, chain, name, case_id, node_count, edge_count, created_at, updated_at"
                " FROM investigations WHERE case_id=? ORDER BY updated_at DESC LIMIT ?",
                (case_id, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, subject, chain, name, case_id, node_count, edge_count, created_at, updated_at"
                " FROM investigations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_investigation(investigation_id: str) -> Optional[dict]:
    init_graph_store_tables()
    with db.get_connection() as con:
        row = con.execute("SELECT * FROM investigations WHERE id=?", (investigation_id,)).fetchone()
        if not row:
            return None
        return _row_to_investigation(row)


def find_by_subject(subject: str, chain: str = "") -> Optional[dict]:
    """Return the most recent investigation for a subject address, if one exists."""
    init_graph_store_tables()
    with db.get_connection() as con:
        if chain:
            row = con.execute(
                "SELECT * FROM investigations WHERE subject=? AND chain=? ORDER BY updated_at DESC LIMIT 1",
                (_norm_addr(subject), chain),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT * FROM investigations WHERE subject=? ORDER BY updated_at DESC LIMIT 1",
                (_norm_addr(subject),),
            ).fetchone()
    return _row_to_investigation(row) if row else None


def delete_investigation(investigation_id: str) -> bool:
    init_graph_store_tables()
    with db.get_connection() as con:
        con.execute("DELETE FROM investigation_nodes WHERE investigation_id=?", (investigation_id,))
        con.execute("DELETE FROM investigation_edges WHERE investigation_id=?", (investigation_id,))
        con.execute("DELETE FROM investigation_snapshots WHERE investigation_id=?", (investigation_id,))
        cur = con.execute("DELETE FROM investigations WHERE id=?", (investigation_id,))
    return cur.rowcount > 0


def list_snapshots(investigation_id: str) -> list[dict]:
    init_graph_store_tables()
    with db.get_connection() as con:
        rows = con.execute(
            "SELECT id, node_count, edge_count, note, created_at"
            " FROM investigation_snapshots WHERE investigation_id=? ORDER BY created_at DESC",
            (investigation_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _row_to_investigation(row) -> dict:
    item = dict(row)
    try:
        item["graph"] = json.loads(item.pop("graph_json") or "{}")
    except json.JSONDecodeError:
        item["graph"] = {}
    try:
        item["params"] = json.loads(item.pop("params_json") or "{}")
    except json.JSONDecodeError:
        item["params"] = {}
    return item
