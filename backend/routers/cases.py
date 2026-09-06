"""
Case Management Router — /api/cases
Full CRUD for investigation cases, addresses within cases, and notes.

RBAC (per-case permissions):
  - Every case gets an owner (the authenticated creator).
  - Owners and admins can delete a case and manage its member list.
  - Members with "full_access" role can modify case contents.
  - Members with "reviewer" role have read-only access.
  - Legacy cases with no owner remain open to all analysts.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import database as db
import tenancy

router = APIRouter(tags=["cases"])

VALID_CASE_ROLES = ("full_access", "reviewer")


# ── Per-case ACL helpers ──────────────────────────────────────────────────────

def _acl_init() -> None:
    with db.get_connection() as con:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(cases)").fetchall()}
        if "owner_id" not in cols:
            con.execute("ALTER TABLE cases ADD COLUMN owner_id TEXT DEFAULT ''")
        if "owner_email" not in cols:
            con.execute("ALTER TABLE cases ADD COLUMN owner_email TEXT DEFAULT ''")
        con.execute("""
            CREATE TABLE IF NOT EXISTS case_members (
                case_id    TEXT NOT NULL,
                user_id    TEXT NOT NULL,
                email      TEXT DEFAULT '',
                case_role  TEXT DEFAULT 'full_access',
                added_by   TEXT DEFAULT '',
                added_at   TEXT DEFAULT '',
                PRIMARY KEY (case_id, user_id)
            )
        """)
        # migrate existing tables that lack case_role
        mem_cols = {r["name"] for r in con.execute("PRAGMA table_info(case_members)").fetchall()}
        if "case_role" not in mem_cols:
            con.execute("ALTER TABLE case_members ADD COLUMN case_role TEXT DEFAULT 'full_access'")
        # ── Task management tables ────────────────────────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS case_tasks (
                id           TEXT PRIMARY KEY,
                case_id      TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                title        TEXT NOT NULL,
                description  TEXT DEFAULT '',
                status       TEXT DEFAULT 'open',
                priority     TEXT DEFAULT 'medium',
                assigned_to  TEXT NOT NULL,
                assigned_by  TEXT NOT NULL,
                due_date     TEXT DEFAULT '',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                completed_at TEXT DEFAULT ''
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS task_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id    TEXT NOT NULL REFERENCES case_tasks(id) ON DELETE CASCADE,
                user_id    TEXT NOT NULL,
                user_name  TEXT DEFAULT '',
                message    TEXT NOT NULL,
                msg_type   TEXT DEFAULT 'chat',
                created_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS task_deliverables (
                id           TEXT PRIMARY KEY,
                task_id      TEXT NOT NULL REFERENCES case_tasks(id) ON DELETE CASCADE,
                title        TEXT NOT NULL,
                description  TEXT DEFAULT '',
                content      TEXT DEFAULT '',
                status       TEXT DEFAULT 'pending',
                submitted_by TEXT NOT NULL,
                reviewed_by  TEXT DEFAULT '',
                review_note  TEXT DEFAULT '',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS case_audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id    TEXT NOT NULL,
                user_id    TEXT DEFAULT '',
                user_name  TEXT DEFAULT '',
                user_role  TEXT DEFAULT '',
                action     TEXT NOT NULL,
                target     TEXT DEFAULT '',
                detail     TEXT DEFAULT '',
                timestamp  TEXT NOT NULL
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_audit_case ON case_audit_log(case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON case_audit_log(timestamp)")


def _user(request: Request) -> dict:
    return getattr(request.state, "user", None) or {}


def _can_manage(request: Request, case_id: str) -> bool:
    """Owner or admin: delete case, manage members."""
    user = _user(request)
    if not user:
        return True  # auth middleware disabled — fail open for local use
    if (user.get("role") or "") == "admin":
        return True
    _acl_init()
    with db.get_connection() as con:
        row = con.execute("SELECT owner_id FROM cases WHERE id=?", (case_id,)).fetchone()
    owner = (row["owner_id"] if row else "") or ""
    return owner == "" or owner == str(user.get("id", ""))


def _can_edit(request: Request, case_id: str) -> bool:
    """Owner, full_access member, or admin: modify case contents.
    Reviewers are read-only — they cannot edit case data."""
    if _can_manage(request, case_id):
        return True
    user = _user(request)
    _acl_init()
    with db.get_connection() as con:
        row = con.execute(
            "SELECT case_role FROM case_members WHERE case_id=? AND user_id=?",
            (case_id, str(user.get("id", ""))),
        ).fetchone()
    if not row:
        return False
    return (row["case_role"] or "full_access") != "reviewer"


def _get_case_role(case_id: str, user_id: str) -> str:
    """Return the user's case_role for a given case. Empty string if not a member."""
    _acl_init()
    with db.get_connection() as con:
        row = con.execute(
            "SELECT case_role FROM case_members WHERE case_id=? AND user_id=?",
            (case_id, str(user_id)),
        ).fetchone()
    return (row["case_role"] or "full_access") if row else ""


def _forbid(detail: str = "You don't have permission on this case (owner/member/admin required)"):
    raise HTTPException(status_code=403, detail=detail)


def _scope(request: Request) -> dict:
    """Return the tenancy scope for this request (org_id + enabled flag)."""
    return tenancy.scope(_user(request))


def _check_org_access(case_id: str, request: Request) -> None:
    """Ensure the case belongs to the caller's org. 404 (not 403) if not, to
    avoid leaking the existence of other orgs' cases. No-op when tenancy is off."""
    s = _scope(request)
    if not s["enabled"]:
        return
    with db.get_connection() as con:
        row = con.execute("SELECT org_id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return  # let the downstream 404 handle missing cases
    case_org = str(row["org_id"] or "")
    # Empty org_id = legacy case; allow if caller is in the default org.
    if case_org and case_org != s["org_id"]:
        raise HTTPException(status_code=404, detail="Case not found")


# ── Audit trail helper ────────────────────────────────────────────────────────

def _audit(case_id: str, request: Request, action: str, target: str = "", detail: str = "") -> None:
    """Append a row to case_audit_log.  Best-effort — never raises."""
    try:
        from datetime import datetime, timezone
        user = _user(request)
        _acl_init()
        with db.get_connection() as con:
            con.execute(
                """INSERT INTO case_audit_log
                   (case_id, user_id, user_name, user_role, action, target, detail, timestamp)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (case_id,
                 str(user.get("id", "")),
                 user.get("name") or user.get("email", ""),
                 user.get("role", ""),
                 action, target, detail,
                 datetime.now(timezone.utc).isoformat()),
            )
    except Exception:
        pass  # audit must never break the calling flow


# ── Audit trail endpoint ──────────────────────────────────────────────────────

from datetime import datetime as _Dt

@router.get("/cases/{case_id}/audit")
def list_audit(case_id: str, request: Request, limit: int = 200, offset: int = 0,
               action: str = "", user_id: str = "", from_ts: str = "", to_ts: str = ""):
    _check_org_access(case_id, request)
    if not _can_manage(request, case_id):
        _forbid("Only the case owner or an admin can view the audit log")
    _acl_init()
    clauses, params = ["case_id=?"], [case_id]
    if action:
        clauses.append("action=?"); params.append(action)
    if user_id:
        clauses.append("user_id=?"); params.append(user_id)
    if from_ts:
        clauses.append("timestamp>=?"); params.append(from_ts)
    if to_ts:
        clauses.append("timestamp<=?"); params.append(to_ts)
    where = " AND ".join(clauses)
    with db.get_connection() as con:
        rows = con.execute(
            f"SELECT * FROM case_audit_log WHERE {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        total = con.execute(
            f"SELECT COUNT(*) FROM case_audit_log WHERE {where}", params,
        ).fetchone()[0]
    return {"entries": [dict(r) for r in rows], "total": total}


# ── Request models ────────────────────────────────────────────────────────────

class CreateCaseRequest(BaseModel):
    name: str
    description: str = ""


class UpdateCaseRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class AddAddressRequest(BaseModel):
    address: str
    chain: str = ""
    label: str = ""
    notes: str = ""
    risk_score: int = -1
    risk_level: str = ""


class AddNoteRequest(BaseModel):
    note: str


# ── Cases CRUD ────────────────────────────────────────────────────────────────

@router.get("/cases")
def list_cases(request: Request):
    s = _scope(request)
    if not s["enabled"]:
        return {"cases": db.list_cases()}
    # Tenant-scoped: only cases belonging to the caller's org.
    with db.get_connection() as con:
        rows = con.execute(
            "SELECT * FROM cases WHERE org_id=? ORDER BY created_at DESC", (s["org_id"],)
        ).fetchall()
    # Reuse get_case to hydrate addresses/notes for each — keeps shape identical.
    cases = []
    for r in rows:
        c = db.get_case(r["id"])
        if c:
            cases.append(c)
    return {"cases": cases}


@router.post("/cases")
def create_case(req: CreateCaseRequest, request: Request):
    case = db.create_case(req.name, req.description)
    user = _user(request)
    s = _scope(request)
    if user and case.get("id"):
        _acl_init()
        with db.get_connection() as con:
            # Stamp owner + org_id so the case is scoped to this tenant.
            con.execute(
                "UPDATE cases SET owner_id=?, owner_email=?, org_id=? WHERE id=?",
                (str(user.get("id", "")), user.get("email", ""), s["org_id"], case["id"]),
            )
        case["owner_id"] = str(user.get("id", ""))
        case["owner_email"] = user.get("email", "")
        case["org_id"] = s["org_id"]
        _audit(case["id"], request, "case.created", target=req.name, detail=req.description)
    return case


@router.get("/cases/{case_id}")
def get_case(case_id: str, request: Request):
    _check_org_access(case_id, request)
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.patch("/cases/{case_id}")
def update_case(case_id: str, req: UpdateCaseRequest, request: Request):
    _check_org_access(case_id, request)
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if not _can_edit(request, case_id):
        _forbid()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    _audit(case_id, request, "case.updated", detail=", ".join(f"{k}={v}" for k, v in updates.items()))
    return db.update_case(case_id, **updates)


@router.delete("/cases/{case_id}")
def delete_case(case_id: str, request: Request):
    _check_org_access(case_id, request)
    if not _can_manage(request, case_id):
        _forbid("Only the case owner or an admin can delete a case")
    ok = db.delete_case(case_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Case not found")
    _audit(case_id, request, "case.deleted")
    return {"deleted": case_id}


# ── Case members (per-case permissions) ───────────────────────────────────────

class AddMemberRequest(BaseModel):
    email: str
    case_role: str = "full_access"


class UpdateMemberRoleRequest(BaseModel):
    case_role: str


@router.get("/cases/{case_id}/members")
def list_members(case_id: str):
    _acl_init()
    with db.get_connection() as con:
        rows = con.execute("SELECT * FROM case_members WHERE case_id=?", (case_id,)).fetchall()
        owner = con.execute("SELECT owner_id, owner_email FROM cases WHERE id=?", (case_id,)).fetchone()
    members = []
    for r in rows:
        m = dict(r)
        m["case_role"] = m.get("case_role") or "full_access"
        members.append(m)
    return {
        "owner": dict(owner) if owner else {},
        "members": members,
    }


@router.post("/cases/{case_id}/members")
def add_member(case_id: str, req: AddMemberRequest, request: Request):
    if not _can_manage(request, case_id):
        _forbid("Only the case owner or an admin can manage members")
    if req.case_role not in VALID_CASE_ROLES:
        raise HTTPException(status_code=400, detail=f"case_role must be one of {VALID_CASE_ROLES}")
    import auth_service
    target = auth_service.get_user_by_email(req.email.strip())
    if not target:
        raise HTTPException(status_code=404, detail=f"No user with email {req.email}")
    _acl_init()
    from datetime import datetime, timezone
    with db.get_connection() as con:
        con.execute(
            "INSERT OR REPLACE INTO case_members (case_id, user_id, email, case_role, added_by, added_at) VALUES (?,?,?,?,?,?)",
            (case_id, str(target["id"]), target["email"], req.case_role,
             _user(request).get("email", ""),
             datetime.now(timezone.utc).isoformat()),
        )
    _audit(case_id, request, "member.added", target=target["email"], detail=f"role={req.case_role}")
    return {"added": target["email"], "case_role": req.case_role}


@router.put("/cases/{case_id}/members/{user_id}/role")
def update_member_role(case_id: str, user_id: str, req: UpdateMemberRoleRequest, request: Request):
    if not _can_manage(request, case_id):
        _forbid("Only the case owner or an admin can assign roles")
    if req.case_role not in VALID_CASE_ROLES:
        raise HTTPException(status_code=400, detail=f"case_role must be one of {VALID_CASE_ROLES}")
    _acl_init()
    with db.get_connection() as con:
        cur = con.execute(
            "UPDATE case_members SET case_role=? WHERE case_id=? AND user_id=?",
            (req.case_role, case_id, user_id),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Member not found on this case")
    _audit(case_id, request, "member.role_changed", target=user_id, detail=f"role={req.case_role}")
    return {"user_id": user_id, "case_role": req.case_role}


@router.delete("/cases/{case_id}/members/{user_id}")
def remove_member(case_id: str, user_id: str, request: Request):
    if not _can_manage(request, case_id):
        _forbid("Only the case owner or an admin can manage members")
    _acl_init()
    with db.get_connection() as con:
        cur = con.execute("DELETE FROM case_members WHERE case_id=? AND user_id=?", (case_id, user_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Member not found")
    _audit(case_id, request, "member.removed", target=user_id)
    return {"removed": user_id}


# ── Case Addresses ────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/addresses")
def add_address(case_id: str, req: AddAddressRequest, request: Request):
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    result = db.add_address_to_case(
        case_id,
        req.address,
        chain=req.chain,
        label=req.label,
        notes=req.notes,
        risk_score=req.risk_score,
        risk_level=req.risk_level,
    )
    _audit(case_id, request, "address.added", target=req.address, detail=f"chain={req.chain} label={req.label}")
    return result


@router.delete("/cases/{case_id}/addresses/{address}")
def remove_address(case_id: str, address: str, request: Request):
    ok = db.remove_address_from_case(case_id, address)
    if not ok:
        raise HTTPException(status_code=404, detail="Address not found in case")
    _audit(case_id, request, "address.removed", target=address)
    return {"removed": address}


# ── Case Notes ────────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/notes")
def add_note(case_id: str, req: AddNoteRequest, request: Request):
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    result = db.add_note(case_id, req.note)
    _audit(case_id, request, "note.added", detail=req.note[:200])
    return result


@router.delete("/cases/{case_id}/notes/{note_id}")
def delete_note(case_id: str, note_id: int, request: Request):
    ok = db.delete_note(note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found")
    _audit(case_id, request, "note.deleted", target=str(note_id))
    return {"deleted": note_id}
