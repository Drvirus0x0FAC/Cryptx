"""
Collaborative multi-user investigation — real-time presence.

Tracks who is viewing/editing which case or board, and broadcasts presence
(via the SSE infrastructure) so investigators see each other's cursors and active
panels in real time.

Presence is in-memory (process-local) with a heartbeat timeout. For multi-process
deployments this would need Redis pub/sub; for the single-process SQLite deployment
this is sufficient.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

# In-process presence store: room_id → {user_id → {name, cursor, last_seen, panel}}
_PRESENCE: dict[str, dict[str, dict]] = {}
_HEARTBEAT_TIMEOUT = 60  # seconds before a user is considered gone


def join_room(room_id: str, user_id: str, user_name: str = "") -> None:
    _PRESENCE.setdefault(room_id, {})[user_id] = {
        "user_id": user_id, "name": user_name or user_id,
        "cursor": None, "panel": "", "last_seen": time.time(),
    }


def leave_room(room_id: str, user_id: str) -> None:
    _PRESENCE.get(room_id, {}).pop(user_id, None)


def heartbeat(room_id: str, user_id: str, cursor: dict | None = None,
              panel: str = "") -> list[dict]:
    """Update a user's presence and return the current room roster."""
    room = _PRESENCE.setdefault(room_id, {})
    if user_id in room:
        room[user_id]["last_seen"] = time.time()
        if cursor is not None:
            room[user_id]["cursor"] = cursor
        if panel:
            room[user_id]["panel"] = panel
    # expire stale
    now = time.time()
    expired = [uid for uid, data in room.items() if now - data["last_seen"] > _HEARTBEAT_TIMEOUT]
    for uid in expired:
        room.pop(uid, None)
    return list(room.values())


def get_room_presence(room_id: str) -> list[dict]:
    room = _PRESENCE.get(room_id, {})
    now = time.time()
    return [data for data in room.values() if now - data["last_seen"] <= _HEARTBEAT_TIMEOUT]


def list_active_rooms() -> dict[str, list[dict]]:
    now = time.time()
    out = {}
    for room_id, room in _PRESENCE.items():
        active = [data for data in room.values() if now - data["last_seen"] <= _HEARTBEAT_TIMEOUT]
        if active:
            out[room_id] = active
    return out


# ── Case lock (prevent simultaneous edits) ────────────────────────────────────
_CASE_LOCKS: dict[str, str] = {}  # case_id → user_id


def acquire_case_lock(case_id: str, user_id: str) -> bool:
    current = _CASE_LOCKS.get(case_id)
    if current and current != user_id:
        # Check if the lock holder is still present
        holder_present = any(
            room.get(case_id, {}).get(current)
            for room in [_PRESENCE]
        )
        if holder_present:
            return False
    _CASE_LOCKS[case_id] = user_id
    return True


def release_case_lock(case_id: str, user_id: str) -> None:
    if _CASE_LOCKS.get(case_id) == user_id:
        _CASE_LOCKS.pop(case_id, None)


def case_lock_holder(case_id: str) -> str | None:
    return _CASE_LOCKS.get(case_id)
