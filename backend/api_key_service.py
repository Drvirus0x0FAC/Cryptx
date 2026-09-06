"""
API key service for CrypTX — per-org API keys with rate limiting + usage metering.

Enables the "API/MCP" commercial tier: customers authenticate with an
X-API-Key header instead of a bearer token, and every request is metered for
billing and rate-limited per key.

Design (see DELEGATION_HANDOFF.md Task 3):
  * Keys are org-scoped (each key belongs to exactly one org).
  * Key format: ctxk_<32 random urlsafe chars>. Prefix makes leaked keys
    greppable in logs/scratch; the full key is shown ONCE on creation.
  * Storage: SHA-256 hash of the full key (never the plaintext).
  * Rate limiting: in-process sliding-window counter keyed by api_key_id
    (v1, single-worker — documented limitation; Redis-backed in Phase 2).
  * Metering: one row per key per day in api_usage_daily, upserted best-effort.

Tables: api_keys, api_usage_daily (both tenant-owned, in tenancy.TENANT_TABLES).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH

KEY_PREFIX = "ctxk_"  # CrypTX API key prefix — greppable in logs.
_DEFAULT_RATE_PER_MIN = 60  # conservative default; override per key.
_DEFAULT_MONTHLY_QUOTA = 50_000  # requests/month; 0 = unlimited.

# ── In-process rate-limit state (v1, single-worker) ─────────────────────────
# Sliding window of request timestamps per api_key_id. Mirrors the auth.py:17
# pattern. For multi-worker deploys, back this with Redis in Phase 2.
_rate_log: dict[str, list[float]] = {}
import time as _time


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def init_api_key_tables() -> None:
    """Create the api_keys + api_usage_daily tables. Idempotent."""
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id                TEXT PRIMARY KEY,
                org_id            TEXT NOT NULL DEFAULT '',
                name              TEXT NOT NULL DEFAULT '',
                key_prefix        TEXT NOT NULL DEFAULT '',
                key_hash          TEXT NOT NULL UNIQUE,
                scopes            TEXT NOT NULL DEFAULT '[]',
                rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
                monthly_quota     INTEGER NOT NULL DEFAULT 0,
                is_active         INTEGER NOT NULL DEFAULT 1,
                created_at        TEXT NOT NULL,
                last_used_at      TEXT,
                created_by        TEXT NOT NULL DEFAULT '',
                expires_at        TEXT
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_org ON api_keys(org_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS api_usage_daily (
                api_key_id    TEXT NOT NULL,
                date          TEXT NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                error_count   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (api_key_id, date)
            )
            """
        )
        con.commit()


# ── Key lifecycle ───────────────────────────────────────────────────────────

def create_key(
    org_id: str,
    name: str,
    *,
    scopes: Optional[list[str]] = None,
    rate_limit_per_min: int = _DEFAULT_RATE_PER_MIN,
    monthly_quota: int = _DEFAULT_MONTHLY_QUOTA,
    created_by: str = "",
    expires_at: Optional[str] = None,
) -> tuple[dict, str]:
    """Create a new API key. Returns (key_record, plaintext_key_shown_once).

    The plaintext key is returned ONLY here — store it securely; it is never
    retrievable again (only its SHA-256 hash is persisted).
    """
    kid = str(uuid.uuid4())
    plaintext = KEY_PREFIX + secrets.token_urlsafe(32)
    now = _now_iso()
    scopes_json = json.dumps(scopes or [])
    with _connect() as con:
        con.execute(
            """INSERT INTO api_keys
               (id, org_id, name, key_prefix, key_hash, scopes, rate_limit_per_min,
                monthly_quota, is_active, created_at, created_by, expires_at)
               VALUES (?,?,?,?,?,?,?,?,1,?,?,?)""",
            (kid, str(org_id), name.strip()[:120], plaintext[:12], _hash_key(plaintext),
             scopes_json, int(rate_limit_per_min), int(monthly_quota), now, created_by, expires_at),
        )
        con.commit()
    record = get_key(kid)
    return record, plaintext


def get_key(key_id: str) -> Optional[dict]:
    with _connect() as con:
        row = con.execute("SELECT * FROM api_keys WHERE id=?", (str(key_id),)).fetchone()
    return dict(row) if row else None


def list_keys(org_id: str) -> list[dict]:
    """List all keys for an org (masked — no hash exposed)."""
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM api_keys WHERE org_id=? ORDER BY created_at DESC",
            (str(org_id),),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["is_active"] = bool(d.get("is_active", 1))
        d.pop("key_hash", None)  # never expose the hash
        out.append(d)
    return out


def lookup_by_plaintext(plaintext: str) -> Optional[dict]:
    """Resolve an API key by its plaintext value (used by the auth middleware).

    Returns the key record (with org_id + scopes) or None if not found/inactive.
    Also updates last_used_at (best-effort).
    """
    if not plaintext.startswith(KEY_PREFIX):
        return None
    kh = _hash_key(plaintext)
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM api_keys WHERE key_hash=? AND is_active=1", (kh,)
        ).fetchone()
        if row:
            now = _now_iso()
            con.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now, row["id"]))
            con.commit()
    if not row:
        return None
    d = dict(row)
    # Check expiry.
    if d.get("expires_at"):
        try:
            if datetime.fromisoformat(d["expires_at"]) < datetime.now(timezone.utc):
                return None
        except Exception:
            pass
    return d


def update_key(key_id: str, **fields) -> Optional[dict]:
    """Update mutable fields (name, scopes, rate_limit_per_min, monthly_quota,
    is_active, expires_at). Rotation = create new + deactivate old."""
    allowed = {"name", "scopes", "rate_limit_per_min", "monthly_quota", "is_active", "expires_at"}
    updates = {}
    for k, v in fields.items():
        if k in allowed and v is not None:
            if k == "scopes" and isinstance(v, list):
                updates[k] = json.dumps(v)
            elif k == "is_active":
                updates[k] = 1 if v else 0
            else:
                updates[k] = v
    if not updates:
        return get_key(key_id)
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with _connect() as con:
        con.execute(f"UPDATE api_keys SET {set_clause} WHERE id=?", (*updates.values(), str(key_id)))
        con.commit()
    return get_key(key_id)


def delete_key(key_id: str) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM api_keys WHERE id=?", (str(key_id),))
        con.commit()
        return cur.rowcount > 0


# ── Rate limiting + metering ────────────────────────────────────────────────

def check_rate_limit(key_record: dict) -> tuple[bool, int, dict]:
    """Sliding-window rate check. Returns (allowed, retry_after_seconds, headers).

    headers contains X-RateLimit-Limit / -Remaining / -Reset for the 429 response.
    """
    kid = key_record["id"]
    limit = int(key_record.get("rate_limit_per_min") or _DEFAULT_RATE_PER_MIN)
    now = _time.time()
    window = 60.0  # 1 minute

    # Prune old entries.
    log = [t for t in _rate_log.get(kid, []) if now - t < window]
    _rate_log[kid] = log

    remaining = max(0, limit - len(log))
    reset = int(window - (now - log[0])) if log else int(window)

    if len(log) >= limit:
        return False, max(1, reset), {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(reset),
            "Retry-After": str(max(1, reset)),
        }
    # Consume a slot.
    log.append(now)
    return True, 0, {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining - 1),
        "X-RateLimit-Reset": str(reset),
    }


def record_usage(key_id: str, *, error: bool = False) -> None:
    """Upsert today's usage counter for a key. Best-effort — never raises."""
    try:
        today = _today()
        with _connect() as con:
            if error:
                con.execute(
                    "INSERT INTO api_usage_daily (api_key_id, date, request_count, error_count) VALUES (?,?,1,1) "
                    "ON CONFLICT(api_key_id, date) DO UPDATE SET request_count=request_count+1, error_count=error_count+1",
                    (str(key_id), today),
                )
            else:
                con.execute(
                    "INSERT INTO api_usage_daily (api_key_id, date, request_count, error_count) VALUES (?,?,1,0) "
                    "ON CONFLICT(api_key_id, date) DO UPDATE SET request_count=request_count+1",
                    (str(key_id), today),
                )
            con.commit()
    except Exception:
        pass  # metering must never break a request


def get_usage(key_id: str, days: int = 30) -> dict:
    """Return usage summary for a key (last N days + monthly total)."""
    with _connect() as con:
        rows = con.execute(
            "SELECT date, request_count, error_count FROM api_usage_daily "
            "WHERE api_key_id=? AND date >= date('now', ?) ORDER BY date DESC",
            (str(key_id), f"-{int(days)} days"),
        ).fetchall()
    total_requests = sum(r["request_count"] for r in rows)
    total_errors = sum(r["error_count"] for r in rows)
    return {
        "key_id": str(key_id),
        "days": [dict(r) for r in rows],
        "total_requests": total_requests,
        "total_errors": total_errors,
    }


def resolve_user_from_key(key_record: dict) -> dict:
    """Build a synthetic request.state.user dict from an API key record.

    This lets the rest of the app treat API-key auth identically to bearer auth:
    the same org_id scoping applies, and role='api' marks it for any endpoint
    that wants to distinguish programmatic from human callers.
    """
    try:
        scopes = json.loads(key_record.get("scopes") or "[]")
    except Exception:
        scopes = []
    return {
        "id": f"apikey:{key_record['id']}",
        "email": "",
        "name": key_record.get("name") or "API Key",
        "role": "api",
        "org_id": key_record.get("org_id") or "",
        "org_role": "analyst",
        "is_active": True,
        "_api_key_id": key_record["id"],
        "_scopes": scopes,
    }


def has_scope(user: dict, required_scope: str) -> bool:
    """Check whether a user (from API key) has a given scope. Permissive for
    non-API users (they're governed by RBAC, not scopes)."""
    scopes = user.get("_scopes")
    if not scopes:
        return True  # not an API-key caller, or key with no scope restriction
    if "*" in scopes:
        return True
    return required_scope in scopes


if __name__ == "__main__":
    init_api_key_tables()
    rec, plain = create_key(org_id="test-org", name="smoke test key")
    print("created key:", rec["id"], "prefix:", rec["key_prefix"])
    print("plaintext (once):", plain[:16] + "...")
    resolved = lookup_by_plaintext(plain)
    print("lookup ok:", bool(resolved), "org:", resolved["org_id"] if resolved else None)
