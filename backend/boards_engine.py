"""
Boards engine — persistent, editable investigation canvases (Tracker-style "Boards").

Features
  • Named boards organized into per-case Folders
  • Autosaved canvas state (nodes / edges / custom clusters / annotations / viewport)
  • Public & private (password-gated) read-only share links with expiry + revocation
  • Optional at-rest encryption of shared snapshots (Fernet, if `cryptography` installed;
    otherwise PBKDF2-gated access — password is never stored in clear either way)
  • Threaded comments for investigator handoff

State is a frontend-owned JSON document; the backend treats it opaquely but
records a SHA-256 of every save for chain-of-custody exhibits.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH

_PBKDF2_ITERS = 200_000

try:  # optional at-rest encryption for shared snapshots
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore

    _HAS_FERNET = True
except Exception:  # noqa: BLE001
    _HAS_FERNET = False


# ── helpers ──────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"{salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ITERS)
        # Bug #8 fix: use constant-time comparison to prevent timing side-channel
        # on share passwords (matches auth_service's use of hmac.compare_digest).
        import hmac
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:  # noqa: BLE001
        return False


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return base64.urlsafe_b64encode(dk)


def _row(r: sqlite3.Row) -> dict[str, Any]:
    return dict(r)


EMPTY_STATE: dict[str, Any] = {
    "nodes": [], "edges": [], "clusters": [], "viewport": {"x": 0, "y": 0, "z": 1},
    "preferences": {"fiat": True, "showGlyphs": True, "labelDensity": "normal"},
}


# ── schema ───────────────────────────────────────────────────────────────────

def init_boards_tables() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS board_folders (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                case_id    TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS boards (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                folder_id   TEXT DEFAULT '',
                case_id     TEXT DEFAULT '',
                state       TEXT NOT NULL DEFAULT '{}',
                state_hash  TEXT DEFAULT '',
                version     INTEGER NOT NULL DEFAULT 0,
                created_by  TEXT DEFAULT '',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS board_shares (
                token         TEXT PRIMARY KEY,
                board_id      TEXT NOT NULL,
                mode          TEXT NOT NULL DEFAULT 'public',   -- public | private
                password_hash TEXT DEFAULT '',
                live          INTEGER NOT NULL DEFAULT 1,       -- 1 = live board, 0 = frozen snapshot
                snapshot      TEXT DEFAULT '',                  -- frozen (optionally encrypted) state
                snapshot_enc  INTEGER NOT NULL DEFAULT 0,       -- 1 = Fernet-encrypted with share password
                enc_salt      TEXT DEFAULT '',
                snapshot_hash TEXT DEFAULT '',
                created_by    TEXT DEFAULT '',
                created_at    TEXT NOT NULL,
                expires_at    TEXT DEFAULT '',
                revoked       INTEGER NOT NULL DEFAULT 0,
                access_count  INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS board_comments (
                id         TEXT PRIMARY KEY,
                board_id   TEXT NOT NULL,
                author     TEXT DEFAULT '',
                body       TEXT NOT NULL,
                node_ref   TEXT DEFAULT '',                     -- optional node/edge id anchor
                resolved   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS board_links (
                id         TEXT PRIMARY KEY,
                board_id   TEXT NOT NULL,
                kind       TEXT NOT NULL DEFAULT 'address',      -- nexus_subject | address | tx | case
                ref        TEXT NOT NULL,                        -- e.g. the address / subject / tx hash
                ref_chain  TEXT DEFAULT '',
                label      TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_boards_folder ON boards(folder_id);
            CREATE INDEX IF NOT EXISTS idx_boards_case ON boards(case_id);
            CREATE INDEX IF NOT EXISTS idx_shares_board ON board_shares(board_id);
            CREATE INDEX IF NOT EXISTS idx_comments_board ON board_comments(board_id);
            CREATE INDEX IF NOT EXISTS idx_links_board ON board_links(board_id);
            CREATE INDEX IF NOT EXISTS idx_links_ref ON board_links(ref);
            """
        )
        con.commit()


# ── folders ──────────────────────────────────────────────────────────────────

def create_folder(name: str, case_id: str = "", created_by: str = "") -> dict[str, Any]:
    if not name.strip():
        raise ValueError("folder name is required")
    fid = _uid("fld")
    with _conn() as con:
        con.execute(
            "INSERT INTO board_folders (id, name, case_id, created_by, created_at) VALUES (?,?,?,?,?)",
            (fid, name.strip(), case_id, created_by, _now()),
        )
        con.commit()
    return get_folder(fid)  # type: ignore[return-value]


def get_folder(folder_id: str) -> Optional[dict[str, Any]]:
    with _conn() as con:
        r = con.execute("SELECT * FROM board_folders WHERE id=?", (folder_id,)).fetchone()
    return _row(r) if r else None


def list_folders(case_id: str = "") -> list[dict[str, Any]]:
    with _conn() as con:
        if case_id:
            rows = con.execute(
                "SELECT f.*, (SELECT COUNT(*) FROM boards b WHERE b.folder_id=f.id) AS board_count"
                " FROM board_folders f WHERE f.case_id=? ORDER BY f.created_at DESC", (case_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT f.*, (SELECT COUNT(*) FROM boards b WHERE b.folder_id=f.id) AS board_count"
                " FROM board_folders f ORDER BY f.created_at DESC",
            ).fetchall()
    return [_row(r) for r in rows]


def rename_folder(folder_id: str, name: str) -> Optional[dict[str, Any]]:
    with _conn() as con:
        con.execute("UPDATE board_folders SET name=? WHERE id=?", (name.strip(), folder_id))
        con.commit()
    return get_folder(folder_id)


def delete_folder(folder_id: str) -> bool:
    with _conn() as con:
        con.execute("UPDATE boards SET folder_id='' WHERE folder_id=?", (folder_id,))
        cur = con.execute("DELETE FROM board_folders WHERE id=?", (folder_id,))
        con.commit()
    return cur.rowcount > 0


# ── boards ───────────────────────────────────────────────────────────────────

def create_board(name: str, description: str = "", folder_id: str = "", case_id: str = "",
                 state: Optional[dict[str, Any]] = None, created_by: str = "") -> dict[str, Any]:
    if not name.strip():
        raise ValueError("board name is required")
    bid = _uid("brd")
    now = _now()
    state_json = json.dumps(state or EMPTY_STATE)
    with _conn() as con:
        con.execute(
            "INSERT INTO boards (id, name, description, folder_id, case_id, state, state_hash,"
            " version, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,0,?,?,?)",
            (bid, name.strip(), description, folder_id, case_id, state_json, _sha256(state_json),
             created_by, now, now),
        )
        con.commit()
    return get_board(bid)  # type: ignore[return-value]


def get_board(board_id: str, include_state: bool = True) -> Optional[dict[str, Any]]:
    with _conn() as con:
        r = con.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
    if not r:
        return None
    board = _row(r)
    if include_state:
        try:
            board["state"] = json.loads(board["state"] or "{}")
        except Exception:  # noqa: BLE001
            board["state"] = dict(EMPTY_STATE)
    else:
        board.pop("state", None)
    return board


def list_boards(folder_id: str = "", case_id: str = "") -> list[dict[str, Any]]:
    q = ("SELECT id, name, description, folder_id, case_id, state, state_hash, version, created_by,"
         " created_at, updated_at,"
         " (SELECT COUNT(*) FROM board_comments c WHERE c.board_id=boards.id AND c.resolved=0) AS open_comments,"
         " (SELECT COUNT(*) FROM board_shares s WHERE s.board_id=boards.id AND s.revoked=0) AS active_shares"
         " FROM boards")
    cond, args = [], []
    if folder_id:
        cond.append("folder_id=?"); args.append(folder_id)
    if case_id:
        cond.append("case_id=?"); args.append(case_id)
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY updated_at DESC"
    with _conn() as con:
        rows = con.execute(q, args).fetchall()
    out = []
    for r in rows:
        b = _row(r)
        try:
            st = json.loads(b.pop("state") or "{}")
            nodes = st.get("nodes", [])
            edges = st.get("edges", [])
            b["node_count"] = len(nodes)
            b["edge_count"] = len(edges)
            b["zone_count"] = len(st.get("zones", []) or [])
            # lightweight thumbnail payload for the boards home page
            pn = nodes[:60]
            idx = {n.get("id"): i for i, n in enumerate(pn)}
            b["preview"] = {
                "nodes": [
                    {"x": round(float(n.get("x", 0)), 1), "y": round(float(n.get("y", 0)), 1),
                     "c": n.get("color", "#8e9db5"), "k": n.get("kind", "address")}
                    for n in pn
                ],
                "edges": [
                    [idx[e.get("source")], idx[e.get("target")]]
                    for e in edges[:100]
                    if e.get("source") in idx and e.get("target") in idx
                ],
            }
        except Exception:  # noqa: BLE001
            b.pop("state", None)
            b["node_count"] = b["edge_count"] = 0
            b["preview"] = None
        out.append(b)
    return out


def update_board(board_id: str, *, name: Optional[str] = None, description: Optional[str] = None,
                 folder_id: Optional[str] = None, case_id: Optional[str] = None,
                 state: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    sets, args = [], []
    if name is not None:
        sets.append("name=?"); args.append(name.strip())
    if description is not None:
        sets.append("description=?"); args.append(description)
    if folder_id is not None:
        sets.append("folder_id=?"); args.append(folder_id)
    if case_id is not None:
        sets.append("case_id=?"); args.append(case_id)
    if state is not None:
        sj = json.dumps(state)
        sets.append("state=?"); args.append(sj)
        sets.append("state_hash=?"); args.append(_sha256(sj))
        sets.append("version=version+1")
    if not sets:
        return get_board(board_id)
    sets.append("updated_at=?"); args.append(_now())
    args.append(board_id)
    with _conn() as con:
        con.execute(f"UPDATE boards SET {', '.join(sets)} WHERE id=?", args)
        con.commit()
    return get_board(board_id, include_state=False)


def delete_board(board_id: str) -> bool:
    with _conn() as con:
        con.execute("DELETE FROM board_shares WHERE board_id=?", (board_id,))
        con.execute("DELETE FROM board_comments WHERE board_id=?", (board_id,))
        cur = con.execute("DELETE FROM boards WHERE id=?", (board_id,))
        con.commit()
    return cur.rowcount > 0


def duplicate_board(board_id: str, created_by: str = "") -> Optional[dict[str, Any]]:
    src = get_board(board_id)
    if not src:
        return None
    return create_board(f"{src['name']} (copy)", src.get("description", ""), src.get("folder_id", ""),
                        src.get("case_id", ""), src.get("state"), created_by)


# ── share links ──────────────────────────────────────────────────────────────

def create_share(board_id: str, mode: str = "public", password: str = "", live: bool = True,
                 expires_hours: int = 0, created_by: str = "") -> dict[str, Any]:
    board = get_board(board_id)
    if not board:
        raise ValueError("board not found")
    if mode not in ("public", "private"):
        raise ValueError("mode must be 'public' or 'private'")
    if mode == "private" and not password:
        raise ValueError("private shares require a password")

    token = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    expires_at = ""
    if expires_hours > 0:
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    snapshot, snapshot_enc, enc_salt, snapshot_hash = "", 0, "", ""
    if not live:
        raw = json.dumps({"name": board["name"], "description": board.get("description", ""),
                          "state": board["state"], "frozen_at": _now()})
        snapshot_hash = _sha256(raw)
        if mode == "private" and _HAS_FERNET:
            salt = os.urandom(16)
            f = Fernet(_derive_fernet_key(password, salt))
            snapshot = f.encrypt(raw.encode("utf-8")).decode("ascii")
            snapshot_enc, enc_salt = 1, salt.hex()
        else:
            snapshot = raw

    with _conn() as con:
        con.execute(
            "INSERT INTO board_shares (token, board_id, mode, password_hash, live, snapshot,"
            " snapshot_enc, enc_salt, snapshot_hash, created_by, created_at, expires_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (token, board_id, mode, _hash_password(password) if password else "", 1 if live else 0,
             snapshot, snapshot_enc, enc_salt, snapshot_hash, created_by, _now(), expires_at),
        )
        con.commit()
    return {
        "token": token, "board_id": board_id, "mode": mode, "live": live,
        "expires_at": expires_at, "encrypted_at_rest": bool(snapshot_enc),
        "snapshot_hash": snapshot_hash,
        "url_path": f"/board-share/{token}",
    }


def list_shares(board_id: str) -> list[dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT token, board_id, mode, live, snapshot_enc, snapshot_hash, created_by,"
            " created_at, expires_at, revoked, access_count FROM board_shares WHERE board_id=?"
            " ORDER BY created_at DESC", (board_id,),
        ).fetchall()
    return [_row(r) for r in rows]


def revoke_share(token: str) -> bool:
    with _conn() as con:
        cur = con.execute("UPDATE board_shares SET revoked=1 WHERE token=?", (token,))
        con.commit()
    return cur.rowcount > 0


def resolve_share(token: str, password: str = "") -> dict[str, Any]:
    """Resolve a share token to a read-only board payload. Raises ValueError on any failure."""
    with _conn() as con:
        r = con.execute("SELECT * FROM board_shares WHERE token=?", (token,)).fetchone()
    if not r:
        raise ValueError("share link not found")
    share = _row(r)
    if share["revoked"]:
        raise ValueError("share link has been revoked")
    if share["expires_at"] and share["expires_at"] < _now():
        raise ValueError("share link has expired")
    if share["mode"] == "private":
        if not password:
            raise ValueError("password required")
        if not _verify_password(password, share["password_hash"]):
            raise ValueError("invalid password")

    with _conn() as con:
        con.execute("UPDATE board_shares SET access_count=access_count+1 WHERE token=?", (token,))
        con.commit()

    if share["live"]:
        board = get_board(share["board_id"])
        if not board:
            raise ValueError("board no longer exists")
        payload = {"name": board["name"], "description": board.get("description", ""),
                   "state": board["state"], "state_hash": board.get("state_hash", ""),
                   "live": True, "updated_at": board.get("updated_at")}
    else:
        raw = share["snapshot"] or ""
        if share["snapshot_enc"]:
            if not _HAS_FERNET:
                raise ValueError("server cannot decrypt this snapshot (cryptography not installed)")
            try:
                f = Fernet(_derive_fernet_key(password, bytes.fromhex(share["enc_salt"])))
                raw = f.decrypt(raw.encode("ascii")).decode("utf-8")
            except InvalidToken:
                raise ValueError("invalid password")
        doc = json.loads(raw)
        payload = {"name": doc.get("name"), "description": doc.get("description", ""),
                   "state": doc.get("state"), "state_hash": share.get("snapshot_hash", ""),
                   "live": False, "frozen_at": doc.get("frozen_at")}
    payload["mode"] = share["mode"]
    payload["read_only"] = True
    return payload


def share_meta(token: str) -> dict[str, Any]:
    """Public metadata for the share landing page (does it need a password?)."""
    with _conn() as con:
        r = con.execute("SELECT mode, live, revoked, expires_at FROM board_shares WHERE token=?", (token,)).fetchone()
    if not r:
        raise ValueError("share link not found")
    s = _row(r)
    expired = bool(s["expires_at"] and s["expires_at"] < _now())
    return {"mode": s["mode"], "live": bool(s["live"]),
            "needs_password": s["mode"] == "private",
            "revoked": bool(s["revoked"]), "expired": expired}


# ── comments (investigator handoff) ──────────────────────────────────────────

def add_comment(board_id: str, body: str, author: str = "", node_ref: str = "") -> dict[str, Any]:
    if not body.strip():
        raise ValueError("comment body is required")
    if not get_board(board_id, include_state=False):
        raise ValueError("board not found")
    cid = _uid("cmt")
    with _conn() as con:
        con.execute(
            "INSERT INTO board_comments (id, board_id, author, body, node_ref, created_at)"
            " VALUES (?,?,?,?,?,?)", (cid, board_id, author, body.strip(), node_ref, _now()),
        )
        con.commit()
        r = con.execute("SELECT * FROM board_comments WHERE id=?", (cid,)).fetchone()
    return _row(r)


def list_comments(board_id: str, include_resolved: bool = True) -> list[dict[str, Any]]:
    q = "SELECT * FROM board_comments WHERE board_id=?"
    if not include_resolved:
        q += " AND resolved=0"
    q += " ORDER BY created_at ASC"
    with _conn() as con:
        rows = con.execute(q, (board_id,)).fetchall()
    return [_row(r) for r in rows]


def resolve_comment(comment_id: str, resolved: bool = True) -> bool:
    with _conn() as con:
        cur = con.execute("UPDATE board_comments SET resolved=? WHERE id=?", (1 if resolved else 0, comment_id))
        con.commit()
    return cur.rowcount > 0


def delete_comment(comment_id: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM board_comments WHERE id=?", (comment_id,))
        con.commit()
    return cur.rowcount > 0


# ── board ↔ investigation links (bidirectional Nexus / address bridge) ────────

def add_link(board_id: str, kind: str, ref: str, ref_chain: str = "", label: str = "",
             created_by: str = "") -> dict[str, Any]:
    if not get_board(board_id, include_state=False):
        raise ValueError("board not found")
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("ref is required")
    with _conn() as con:
        existing = con.execute(
            "SELECT * FROM board_links WHERE board_id=? AND kind=? AND LOWER(ref)=LOWER(?)",
            (board_id, kind, ref),
        ).fetchone()
        if existing:
            return _row(existing)
        lid = _uid("lnk")
        con.execute(
            "INSERT INTO board_links (id, board_id, kind, ref, ref_chain, label, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (lid, board_id, kind, ref, ref_chain, label, created_by, _now()),
        )
        con.commit()
        r = con.execute("SELECT * FROM board_links WHERE id=?", (lid,)).fetchone()
    return _row(r)


def links_for_board(board_id: str) -> list[dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM board_links WHERE board_id=? ORDER BY created_at ASC", (board_id,),
        ).fetchall()
    return [_row(r) for r in rows]


def boards_for_ref(ref: str, kind: str = "") -> list[dict[str, Any]]:
    """All boards linked to a given address / subject / tx — powers the Nexus 'Linked boards' panel."""
    ref = (ref or "").strip()
    if not ref:
        return []
    q = ("SELECT l.id AS link_id, l.kind, l.ref, l.ref_chain, l.label, l.created_at,"
         " b.id AS board_id, b.name, b.case_id, b.updated_at,"
         " (SELECT COUNT(*) FROM board_comments c WHERE c.board_id=b.id AND c.resolved=0) AS open_comments"
         " FROM board_links l JOIN boards b ON b.id = l.board_id"
         " WHERE LOWER(l.ref)=LOWER(?)")
    args: list[Any] = [ref]
    if kind:
        q += " AND l.kind=?"
        args.append(kind)
    q += " ORDER BY b.updated_at DESC"
    with _conn() as con:
        rows = con.execute(q, args).fetchall()
    return [_row(r) for r in rows]


def delete_link(link_id: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM board_links WHERE id=?", (link_id,))
        con.commit()
    return cur.rowcount > 0


# ── entity-search helper (boards by name, for unified search) ────────────────

def search_boards(query: str, limit: int = 10) -> list[dict[str, Any]]:
    q = f"%{query.strip().lower()}%"
    with _conn() as con:
        rows = con.execute(
            "SELECT id, name, case_id, updated_at FROM boards WHERE LOWER(name) LIKE ?"
            " ORDER BY updated_at DESC LIMIT ?", (q, limit),
        ).fetchall()
    return [_row(r) for r in rows]
