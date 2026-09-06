"""
Case Task Management Router — /api/cases/{case_id}/tasks
Task assignment, chat, and deliverable tracking within investigation cases.

Permissions:
  - Owner / admin: full task management (create, assign, close, delete).
  - full_access members: create tasks, send messages, submit deliverables.
  - reviewer members: read-only — view tasks, messages, deliverables.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import database as db
from routers.cases import _acl_init, _can_edit, _can_manage, _user, _forbid, _check_org_access, _audit

router = APIRouter(tags=["Case Tasks"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _require_case_access(case_id: str, request: Request) -> dict:
    """Ensure the caller can see this case. Returns the user dict."""
    _check_org_access(case_id, request)
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return _user(request)


# ── Request models ────────────────────────────────────────────────────────────

class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    assigned_to: str
    priority: str = "medium"
    due_date: str = ""


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    assigned_to: Optional[str] = None


class SendMessageRequest(BaseModel):
    message: str
    msg_type: str = "chat"


class CreateDeliverableRequest(BaseModel):
    title: str
    description: str = ""
    content: str = ""


class ReviewDeliverableRequest(BaseModel):
    status: str = "approved"
    review_note: str = ""


# ── Task CRUD ─────────────────────────────────────────────────────────────────

@router.get("/cases/{case_id}/tasks")
def list_tasks(case_id: str, request: Request):
    _require_case_access(case_id, request)
    _acl_init()
    with db.get_connection() as con:
        rows = con.execute(
            "SELECT * FROM case_tasks WHERE case_id=? ORDER BY created_at DESC",
            (case_id,),
        ).fetchall()
    tasks = [dict(r) for r in rows]
    # attach assignee names
    import auth_service
    for t in tasks:
        assignee = auth_service.get_user_by_id(t["assigned_to"])
        t["assignee_name"] = (assignee.get("name") or assignee.get("email") or "") if assignee else ""
        assigner = auth_service.get_user_by_id(t["assigned_by"])
        t["assigner_name"] = (assigner.get("name") or assigner.get("email") or "") if assigner else ""
    return {"tasks": tasks}


@router.post("/cases/{case_id}/tasks")
def create_task(case_id: str, req: CreateTaskRequest, request: Request):
    user = _require_case_access(case_id, request)
    if not _can_edit(request, case_id):
        _forbid("You don't have edit access on this case")
    if req.priority not in ("low", "medium", "high", "urgent"):
        raise HTTPException(status_code=400, detail="priority must be low|medium|high|urgent")
    task_id = _new_id()
    now = _now()
    _acl_init()
    with db.get_connection() as con:
        con.execute(
            """INSERT INTO case_tasks
               (id, case_id, title, description, status, priority, assigned_to, assigned_by, due_date, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, case_id, req.title.strip(), req.description.strip(),
             "open", req.priority, req.assigned_to, str(user.get("id", "")),
             req.due_date, now, now),
        )
    # Notify the assignee about the new task
    if req.assigned_to and req.assigned_to != str(user.get("id", "")):
        from routers.notifications import create_notification
        create_notification(
            user_id=req.assigned_to,
            actor_id=str(user.get("id", "")),
            actor_name=user.get("name") or user.get("email", ""),
            notif_type="task_assigned",
            case_id=case_id,
            task_id=task_id,
            title=f"You were assigned a new task",
            message=req.title.strip()[:120],
        )

    _audit(case_id, request, "task.created", target=req.title, detail=f"assignee={req.assigned_to} priority={req.priority}")
    return {"task_id": task_id, "status": "open"}


@router.get("/cases/{case_id}/tasks/{task_id}")
def get_task(case_id: str, task_id: str, request: Request):
    _require_case_access(case_id, request)
    _acl_init()
    with db.get_connection() as con:
        row = con.execute(
            "SELECT * FROM case_tasks WHERE id=? AND case_id=?", (task_id, case_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    task = dict(row)
    import auth_service
    assignee = auth_service.get_user_by_id(task["assigned_to"])
    task["assignee_name"] = (assignee.get("name") or assignee.get("email") or "") if assignee else ""
    return {"task": task}


@router.patch("/cases/{case_id}/tasks/{task_id}")
def update_task(case_id: str, task_id: str, req: UpdateTaskRequest, request: Request):
    _require_case_access(case_id, request)
    if not _can_edit(request, case_id):
        _forbid("You don't have edit access on this case")
    _acl_init()
    with db.get_connection() as con:
        row = con.execute(
            "SELECT * FROM case_tasks WHERE id=? AND case_id=?", (task_id, case_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        if not updates:
            return {"task": dict(row)}
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values())
        values.append(_now())
        values.extend([task_id, case_id])
        # auto-set completed_at when status changes to done/closed
        if updates.get("status") in ("done", "closed"):
            set_clause += ", completed_at=?"
            values.insert(-2, _now())
        con.execute(
            f"UPDATE case_tasks SET {set_clause}, updated_at=? WHERE id=? AND case_id=?",
            values,
        )
        updated = con.execute(
            "SELECT * FROM case_tasks WHERE id=? AND case_id=?", (task_id, case_id),
        ).fetchone()
    _audit(case_id, request, "task.updated", target=task_id,
           detail=", ".join(f"{k}={v}" for k, v in updates.items()))
    return {"task": dict(updated)}


@router.delete("/cases/{case_id}/tasks/{task_id}")
def delete_task(case_id: str, task_id: str, request: Request):
    user = _require_case_access(case_id, request)
    if not _can_manage(request, case_id):
        _forbid("Only the case owner or an admin can delete tasks")
    _acl_init()
    with db.get_connection() as con:
        cur = con.execute("DELETE FROM case_tasks WHERE id=? AND case_id=?", (task_id, case_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    _audit(case_id, request, "task.deleted", target=task_id)
    return {"deleted": task_id}


# ── Task chat messages ────────────────────────────────────────────────────────

@router.get("/cases/{case_id}/tasks/{task_id}/messages")
def list_messages(case_id: str, task_id: str, request: Request):
    _require_case_access(case_id, request)
    _acl_init()
    with db.get_connection() as con:
        task = con.execute(
            "SELECT id FROM case_tasks WHERE id=? AND case_id=?", (task_id, case_id),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        rows = con.execute(
            "SELECT * FROM task_messages WHERE task_id=? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
    return {"messages": [dict(r) for r in rows]}


@router.post("/cases/{case_id}/tasks/{task_id}/messages")
def send_message(case_id: str, task_id: str, req: SendMessageRequest, request: Request):
    user = _require_case_access(case_id, request)
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    sender_id = str(user.get("id", ""))
    sender_name = user.get("name") or user.get("email", "")
    _acl_init()
    with db.get_connection() as con:
        task = con.execute(
            "SELECT id, title, assigned_to, assigned_by FROM case_tasks WHERE id=? AND case_id=?",
            (task_id, case_id),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        con.execute(
            "INSERT INTO task_messages (task_id, user_id, user_name, message, msg_type, created_at) VALUES (?,?,?,?,?,?)",
            (task_id, sender_id, sender_name,
             req.message.strip(), req.msg_type, _now()),
        )
        # Gather who to notify (exclude the sender)
        task_assigned_to = task["assigned_to"] or ""
        task_assigned_by = task["assigned_by"] or ""
        case_row = con.execute(
            "SELECT owner_id FROM cases WHERE id=?", (case_id,),
        ).fetchone()
        case_owner_id = (case_row["owner_id"] if case_row else "") or ""

    # Build notification targets (deduplicated, excluding sender)
    import auth_service
    targets: set[str] = set()
    if task_assigned_to and task_assigned_to != sender_id:
        targets.add(task_assigned_to)
    if task_assigned_by and task_assigned_by != sender_id:
        targets.add(task_assigned_by)
    if case_owner_id and case_owner_id != sender_id:
        targets.add(case_owner_id)

    task_title = task["title"] if task else "a task"
    preview = req.message.strip()[:120]

    from routers.notifications import create_notification
    for uid in targets:
        create_notification(
            user_id=uid,
            actor_id=sender_id,
            actor_name=sender_name,
            notif_type="task_reply",
            case_id=case_id,
            task_id=task_id,
            title=f"{sender_name} replied on \"{task_title}\"",
            message=preview,
        )

    _audit(case_id, request, "task.message", target=task_id, detail=req.message[:200])
    return {"sent": True}


# ── Task deliverables ─────────────────────────────────────────────────────────

@router.get("/cases/{case_id}/tasks/{task_id}/deliverables")
def list_deliverables(case_id: str, task_id: str, request: Request):
    _require_case_access(case_id, request)
    _acl_init()
    with db.get_connection() as con:
        task = con.execute(
            "SELECT id FROM case_tasks WHERE id=? AND case_id=?", (task_id, case_id),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        rows = con.execute(
            "SELECT * FROM task_deliverables WHERE task_id=? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
    return {"deliverables": [dict(r) for r in rows]}


@router.post("/cases/{case_id}/tasks/{task_id}/deliverables")
def submit_deliverable(case_id: str, task_id: str, req: CreateDeliverableRequest, request: Request):
    user = _require_case_access(case_id, request)
    if not _can_edit(request, case_id):
        _forbid("You don't have edit access on this case")
    _acl_init()
    with db.get_connection() as con:
        task = con.execute(
            "SELECT id FROM case_tasks WHERE id=? AND case_id=?", (task_id, case_id),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        d_id = _new_id()
        now = _now()
        con.execute(
            """INSERT INTO task_deliverables
               (id, task_id, title, description, content, status, submitted_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (d_id, task_id, req.title.strip(), req.description.strip(),
             req.content.strip(), "submitted", str(user.get("id", "")), now, now),
        )
    _audit(case_id, request, "deliverable.submitted", target=d_id, detail=req.title)
    return {"deliverable_id": d_id, "status": "submitted"}


@router.put("/cases/{case_id}/tasks/{task_id}/deliverables/{deliverable_id}/review")
def review_deliverable(case_id: str, task_id: str, deliverable_id: str,
                       req: ReviewDeliverableRequest, request: Request):
    user = _require_case_access(case_id, request)
    if not _can_manage(request, case_id):
        _forbid("Only the case owner or an admin can review deliverables")
    if req.status not in ("approved", "rejected", "revision_requested"):
        raise HTTPException(status_code=400, detail="status must be approved|rejected|revision_requested")
    _acl_init()
    with db.get_connection() as con:
        cur = con.execute(
            """UPDATE task_deliverables
               SET status=?, reviewed_by=?, review_note=?, updated_at=?
               WHERE id=? AND task_id=?""",
            (req.status, str(user.get("id", "")), req.review_note.strip(), _now(),
             deliverable_id, task_id),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    _audit(case_id, request, "deliverable.reviewed", target=deliverable_id, detail=f"status={req.status}")
    return {"deliverable_id": deliverable_id, "status": req.status}
