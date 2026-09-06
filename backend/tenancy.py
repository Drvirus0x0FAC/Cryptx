"""
Multi-tenancy layer for CrypTX — row-level org_id scoping.

Design (see DELEGATION_HANDOFF.md Task 2 + CRYPTX_COMMERCIAL_BENCHMARK §5 Blocker 1):

  * `organizations` table — one row per customer org (agency, firm, exchange).
  * `app_users.org_id` — added via ALTER TABLE (mirrors cases.py ACL idiom) so
    existing single-user deployments keep working without a reschema.
  * Every tenant-owned query is scoped by `org_id` via the `scope()` helper.
  * Tables split into GLOBAL (shared intel, no org_id) vs TENANT-OWNED.

Backward compatibility:
  * Legacy rows with org_id='' are attached to a DEFAULT org on first access.
  * If MULTI_TENANT is disabled (config), scope() returns a permissive wildcard
    so the app behaves exactly as before.

Org roles (distinct from the global bootstrap `admin`):
  * org_admin — manages org members + settings, within their org only.
  * analyst  — full read/write within their org (default).
  * viewer   — read-only (enforced by the global middleware already).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH

MULTI_TENANT = _config.MULTI_TENANT
DEFAULT_ORG_ID = _config.DEFAULT_ORG_ID

# ── Table classification ────────────────────────────────────────────────────
# GLOBAL tables carry shared reference intel and must NOT get an org_id column.
# TENANT-OWNED tables hold customer data and are scoped by org_id at query time.
#
# Keep this list authoritative — the audit script (scripts/audit_tenant_isolation.py)
# reads it to verify every tenant-owned table's queries carry an org_id predicate.

GLOBAL_TABLES: frozenset[str] = frozenset({
    "sanctions_entities", "sanctions_addresses", "sanctions_meta",
    "vasp_directory",
    "public_enrichment_cache", "public_enrichment_feed_items",
    "price_cache", "http_cache",
})

TENANT_TABLES: frozenset[str] = frozenset({
    # Case management
    "cases", "case_addresses", "case_notes", "case_members", "report_artifacts",
    # Evidence & attribution
    "evidence_vault", "evidence_audit_log", "evidence_deletions",
    "attributions", "attribution_submissions", "local_labels",
    # Graph & forensics
    "forensic_runs", "graph_addresses", "graph_transactions", "graph_edges",
    "algorithm_outputs", "clustering_runs", "cashout_sessions",
    "investigations", "investigation_nodes", "investigation_edges", "investigation_snapshots",
    # Victim & scam
    "victim_reports", "scam_intel_cache", "scam_networks",
    # Collaboration
    "board_folders", "boards", "board_shares", "board_comments", "board_links",
    "osint_sweeps",
    # Monitoring & feeds
    "alert_destinations", "alert_deliveries",
    "feed_imports", "feed_import_rows", "feed_sync_state", "feed_sync_records", "feed_diff_alerts",
    # Compliance & recovery (Next-Horizon)
    "comply_programs", "comply_addresses", "comply_screenings", "comply_audit",
    "freeze_watchlist", "freeze_watch_events", "recovery_requests",
    # Predictive
    "predictive_models", "predictive_baselines", "predictive_predictions", "predictive_features",
    # Auth/API keys (org-scoped credentials)
    "api_keys", "api_usage_daily",
    # SSO identity links
    "user_identities",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


# ── Schema initialization ───────────────────────────────────────────────────

def init_tenancy_tables() -> None:
    """Create the organizations table and add org_id to app_users + tenant tables.

    Idempotent: safe to call on every startup. Uses ALTER TABLE ADD COLUMN
    (the same idiom as routers/cases.py:_acl_init) so existing DBs migrate in
    place without data loss.
    """
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL DEFAULT '',
                slug          TEXT NOT NULL DEFAULT '',
                plan          TEXT NOT NULL DEFAULT 'investigator',
                status        TEXT NOT NULL DEFAULT 'active',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                settings_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_slug ON organizations(slug) WHERE slug != ''"
        )

        # Add org_id to app_users if missing.
        _ensure_column(con, "app_users", "org_id", "TEXT DEFAULT ''")

        # Add org_id to every tenant-owned table that exists in this DB.
        # Tables that haven't been created yet by their engine will be skipped
        # here and picked up by ensure_tenant_columns() after their init runs.
        ensure_tenant_columns(con)

        con.commit()


def _ensure_column(con: sqlite3.Connection, table: str, column: str, decl: str) -> bool:
    """Add `column` to `table` if it doesn't exist. Returns True if added."""
    cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        return True
    return False


def ensure_tenant_columns(con: Optional[sqlite3.Connection] = None) -> list[str]:
    """Add org_id to every tenant-owned table that currently exists in the DB.

    Call this AFTER all engine init_*_tables() have run, so every table exists.
    Returns the list of tables that had the column added (useful for logging).

    Safe to call repeatedly — no-ops on tables that already have org_id.
    """
    own_con = con is None
    if own_con:
        con = _connect()
    assert con is not None
    added: list[str] = []
    try:
        existing = {
            r["name"]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in TENANT_TABLES:
            if table in existing:
                if _ensure_column(con, table, "org_id", "TEXT NOT NULL DEFAULT ''"):
                    added.append(table)
        if own_con:
            con.commit()
    finally:
        if own_con:
            con.close()
    return added


# ── Default org provisioning ────────────────────────────────────────────────

def get_or_create_default_org() -> str:
    """Return the default org id, creating it if necessary.

    Used to attach legacy rows (org_id='') and JIT-provisioned users so that
    single-user deployments keep working under the multi-tenant model.
    """
    # Explicit override wins.
    if DEFAULT_ORG_ID:
        with _connect() as con:
            row = con.execute("SELECT id FROM organizations WHERE id=?", (DEFAULT_ORG_ID,)).fetchone()
            if not row:
                now = _now_iso()
                con.execute(
                    "INSERT INTO organizations (id, name, slug, plan, status, created_at, updated_at, settings_json) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (DEFAULT_ORG_ID, "Default Organization", "default", "investigator", "active", now, now, "{}"),
                )
                con.commit()
        return DEFAULT_ORG_ID

    # Look for an existing default org (marked by slug='default' or the first org).
    with _connect() as con:
        row = con.execute(
            "SELECT id FROM organizations WHERE slug='default' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if row:
            return str(row["id"])
        row = con.execute("SELECT id FROM organizations ORDER BY created_at ASC LIMIT 1").fetchone()
        if row:
            return str(row["id"])

        # Create one.
        oid = str(uuid.uuid4())
        now = _now_iso()
        con.execute(
            "INSERT INTO organizations (id, name, slug, plan, status, created_at, updated_at, settings_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (oid, "Default Organization", "default", "investigator", "active", now, now, "{}"),
        )
        con.commit()
        return oid


def attach_legacy_rows_to_default_org() -> int:
    """Assign org_id='' rows in all tenant tables to the default org.

    Call once during startup (after init_tenancy_tables + engine inits). Returns
    the total number of rows updated across all tables. Idempotent.
    """
    if not MULTI_TENANT:
        return 0
    default_org = get_or_create_default_org()
    total = 0
    with _connect() as con:
        for table in TENANT_TABLES:
            try:
                cur = con.execute(f"UPDATE {table} SET org_id=? WHERE org_id=''", (default_org,))
                if cur.rowcount > 0:
                    total += cur.rowcount
            except sqlite3.OperationalError:
                # Table doesn't exist in this deployment — skip.
                pass
        con.commit()
    return total


# ── Org CRUD ────────────────────────────────────────────────────────────────

def create_org(name: str, slug: str = "", plan: str = "investigator", settings: Optional[dict] = None) -> dict:
    """Create a new organization. Returns the org row as a dict."""
    oid = str(uuid.uuid4())
    now = _now_iso()
    slug = (slug or name).strip().lower().replace(" ", "-")[:40] or oid[:8]
    settings_json = json.dumps(settings or {})
    with _connect() as con:
        con.execute(
            "INSERT INTO organizations (id, name, slug, plan, status, created_at, updated_at, settings_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (oid, name.strip(), slug, plan, "active", now, now, settings_json),
        )
        con.commit()
    return get_org(oid)  # type: ignore[return-value]


def get_org(org_id: str) -> Optional[dict]:
    with _connect() as con:
        row = con.execute("SELECT * FROM organizations WHERE id=?", (str(org_id),)).fetchone()
    return dict(row) if row else None


def get_org_by_slug(slug: str) -> Optional[dict]:
    with _connect() as con:
        row = con.execute("SELECT * FROM organizations WHERE slug=?", (slug,)).fetchone()
    return dict(row) if row else None


def list_orgs() -> list[dict]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM organizations ORDER BY created_at ASC").fetchall()
    return [dict(r) for r in rows]


def update_org(org_id: str, **fields) -> Optional[dict]:
    """Update mutable org fields (name, slug, plan, status, settings_json)."""
    allowed = {"name", "slug", "plan", "status", "settings_json"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_org(org_id)
    updates["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with _connect() as con:
        con.execute(f"UPDATE organizations SET {set_clause} WHERE id=?", (*updates.values(), str(org_id)))
        con.commit()
    return get_org(org_id)


def assign_user_to_org(user_id: str, org_id: str, role: str = "analyst") -> Optional[dict]:
    """Assign (or move) a user to an org with a given org-level role.

    The org role is stored on app_users.org_role (added by init_tenancy_tables).
    Returns the updated user row (without password_hash) or None.
    """
    with _connect() as con:
        _ensure_column(con, "app_users", "org_role", "TEXT DEFAULT 'analyst'")
        con.execute(
            "UPDATE app_users SET org_id=?, org_role=?, updated_at=? WHERE id=?",
            (str(org_id), role, _now_iso(), str(user_id)),
        )
        con.commit()
    import auth_service
    row = auth_service.get_user_by_id(user_id)
    return row


# ── Scoping helper (the core of row-level isolation) ────────────────────────

def scope(user: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Return a scoping context for the current request's user.

    Returns a dict with:
      * `org_id`   — the user's org id (or '' if multi-tenancy is off / no user).
      * `enabled`  — whether org scoping is active for this request.
      * `is_global_admin` — True if the user has the global bootstrap `admin` role
        (site-wide superuser; bypasses org scoping for cross-org admin tooling).

    Use this in engines/routers to build WHERE clauses:
        s = tenancy.scope(request.state.user)
        if s["enabled"]:
            rows = con.execute(f"SELECT ... WHERE org_id=? {s['and_org']}", (s['org_id'], ...))
    """
    if not MULTI_TENANT:
        return {"org_id": "", "enabled": False, "is_global_admin": False}

    if not user:
        # No authenticated user (e.g. internal/system call) — permissive.
        return {"org_id": "", "enabled": False, "is_global_admin": False}

    role = str(user.get("role") or "analyst")
    is_global_admin = role == "admin"
    org_id = str(user.get("org_id") or "")

    # Global site admins operate across all orgs (for cross-org user management).
    if is_global_admin:
        return {"org_id": org_id, "enabled": False, "is_global_admin": True}

    # Regular users are scoped to their org.
    if not org_id:
        # User has no org yet — attach to default so they can work.
        org_id = get_or_create_default_org()
    return {"org_id": org_id, "enabled": True, "is_global_admin": False}


def scoped_param(s: dict[str, Any], *extra_params) -> tuple[str, tuple]:
    """Build a reusable `(where_clause, params)` fragment for org scoping.

    Returns ("AND org_id=?", (org_id,)) when scoping is enabled, else ("", ()).

    Example:
        s = tenancy.scope(request.state.user)
        wc, wp = tenancy.scoped_param(s)
        rows = con.execute(f"SELECT * FROM cases WHERE 1=1 {wc}", wp)
    """
    if s.get("enabled"):
        return " AND org_id=?", (s["org_id"],)
    return "", ()


def stamp_org_id(user: Optional[dict[str, Any]]) -> str:
    """Return the org_id to stamp on a newly-created tenant row.

    Uses the caller's org_id, or the default org if the caller has none yet.
    Returns '' when multi-tenancy is disabled.
    """
    if not MULTI_TENANT:
        return ""
    if user and user.get("org_id"):
        return str(user["org_id"])
    return get_or_create_default_org()


def guard_case(case_id: str, user: Optional[dict[str, Any]]) -> None:
    """Verify that a case belongs to the caller's org. Raises ValueError if not.

    This is the reusable form of cases.py:_check_org_access — call it at the top
    of any case-keyed endpoint (evidence, reports, forensics, etc.) to enforce
    tenant isolation through the case hierarchy.

    Returns silently if: multi-tenancy is off, the user is a global admin, the
    case has no org_id (legacy), or the case belongs to the caller's org.
    Raises ValueError("not found") if the case belongs to a different org.
    """
    if not MULTI_TENANT:
        return
    if not user:
        return
    if str(user.get("role") or "") == "admin":
        return  # global site admin
    org_id = str(user.get("org_id") or "")
    if not org_id:
        return  # user has no org yet — permissive
    import sqlite3
    try:
        with _connect() as con:
            row = con.execute("SELECT org_id FROM cases WHERE id=?", (str(case_id),)).fetchone()
        if not row:
            return  # let the downstream 404 handle missing cases
        case_org = str(row["org_id"] or "")
        if case_org and case_org != org_id:
            raise ValueError("not found")
    except ValueError:
        raise
    except Exception:
        pass  # never block on a DB error; the endpoint's own logic handles it


def org_id_for_case(case_id: str) -> str:
    """Return the org_id of a case (or '' if unset/missing)."""
    try:
        with _connect() as con:
            row = con.execute("SELECT org_id FROM cases WHERE id=?", (str(case_id),)).fetchone()
        return str(row["org_id"]) if row else ""
    except Exception:
        return ""


# ── Org membership listing ──────────────────────────────────────────────────

def list_org_members(org_id: str) -> list[dict]:
    """List all users in an org (public fields only, no password_hash)."""
    with _connect() as con:
        rows = con.execute(
            "SELECT id, email, name, role, org_role, is_active, created_at, last_login_at "
            "FROM app_users WHERE org_id=? ORDER BY created_at ASC",
            (str(org_id),),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["is_active"] = bool(d.get("is_active", 1))
        out.append(d)
    return out


def set_org_member_role(org_id: str, user_id: str, role: str) -> Optional[dict]:
    """Set a user's org-level role (org_admin / analyst / viewer)."""
    if role not in ("org_admin", "analyst", "viewer"):
        raise ValueError("org role must be org_admin, analyst, or viewer")
    with _connect() as con:
        # Verify the user is in this org (don't allow cross-org role changes).
        row = con.execute(
            "SELECT id FROM app_users WHERE id=? AND org_id=?", (str(user_id), str(org_id))
        ).fetchone()
        if not row:
            return None
        con.execute(
            "UPDATE app_users SET org_role=?, updated_at=? WHERE id=?",
            (role, _now_iso(), str(user_id)),
        )
        con.commit()
    import auth_service
    return auth_service.get_user_by_id(user_id)


if __name__ == "__main__":
    init_tenancy_tables()
    oid = get_or_create_default_org()
    print("default org:", oid)
    print("orgs:", list_orgs())
