"""
Notifications Router — /api/notifications
In-app notification system for task replies, assignments, and other events.

Endpoints:
  GET  /api/notifications              — list current user's notifications (newest first)
  POST /api/notifications/{id}/read    — mark one notification as read
  POST /api/notifications/read-all     — mark all as read for current user
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import database as db
from routers.cases import _user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _acl_init():
    """Ensure the notifications table exists."""
    with db.get_connection() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS user_notifications (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                actor_id    TEXT DEFAULT '',
                actor_name  TEXT DEFAULT '',
                type        TEXT NOT NULL DEFAULT 'info',
                case_id     TEXT DEFAULT '',
                task_id     TEXT DEFAULT '',
                title       TEXT DEFAULT '',
                message     TEXT DEFAULT '',
                is_read     INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_notif_user
            ON user_notifications(user_id, is_read, created_at)
        """)


def create_notification(
    user_id: str,
    actor_id: str = "",
    actor_name: str = "",
    notif_type: str = "info",
    case_id: str = "",
    task_id: str = "",
    title: str = "",
    message: str = "",
):
    """Insert a notification for a user. Safe to call from other routers."""
    _acl_init()
    with db.get_connection() as con:
        con.execute(
            """INSERT INTO user_notifications
               (id, user_id, actor_id, actor_name, type, case_id, task_id, title, message, is_read, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (_new_id(), user_id, actor_id, actor_name, notif_type,
             case_id, task_id, title, message, 0, _now()),
        )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
def list_notifications(request: Request, unread_only: bool = False, limit: int = 50):
    """Return the current user's notifications, newest first."""
    user = _user(request)
    uid = str(user.get("id", ""))
    _acl_init()
    with db.get_connection() as con:
        where = "WHERE user_id=?"
        params: list = [uid]
        if unread_only:
            where += " AND is_read=0"
        rows = con.execute(
            f"SELECT * FROM user_notifications {where} ORDER BY created_at DESC LIMIT ?",
            params + [min(limit, 200)],
        ).fetchall()
    return {"notifications": [dict(r) for r in rows]}


@router.get("/unread-count")
def unread_count(request: Request):
    """Return just the count of unread notifications — lightweight poll target."""
    user = _user(request)
    uid = str(user.get("id", ""))
    _acl_init()
    with db.get_connection() as con:
        row = con.execute(
            "SELECT COUNT(*) c FROM user_notifications WHERE user_id=? AND is_read=0",
            (uid,),
        ).fetchone()
    return {"count": row["c"] if row else 0}


@router.post("/{notif_id}/read")
def mark_read(notif_id: str, request: Request):
    """Mark a single notification as read."""
    user = _user(request)
    uid = str(user.get("id", ""))
    _acl_init()
    with db.get_connection() as con:
        cur = con.execute(
            "UPDATE user_notifications SET is_read=1 WHERE id=? AND user_id=?",
            (notif_id, uid),
        )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(request: Request):
    """Mark all of the current user's notifications as read."""
    user = _user(request)
    uid = str(user.get("id", ""))
    _acl_init()
    with db.get_connection() as con:
        con.execute(
            "UPDATE user_notifications SET is_read=1 WHERE user_id=? AND is_read=0",
            (uid,),
        )
    return {"ok": True}
