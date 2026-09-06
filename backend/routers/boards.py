"""
Boards router — persistent investigation canvases (Tracker-style Boards).

  Folders:   POST/GET /boards/folders, PATCH/DELETE /boards/folders/{id}
  Boards:    POST/GET /boards, GET/PUT/DELETE /boards/{id}, POST /boards/{id}/duplicate
  Shares:    POST /boards/{id}/share, GET /boards/{id}/shares, POST /boards/share/{token}/revoke
             GET  /boards/shared/{token}/meta, POST /boards/shared/{token}   (PUBLIC, no auth)
  Comments:  GET/POST /boards/{id}/comments, POST /boards/comments/{id}/resolve, DELETE .../{id}
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import boards_engine as be
import tenancy

router = APIRouter(tags=["Boards"])


def _actor(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("username") or user.get("email") or "analyst")


def _user(request: Request) -> dict:
    return getattr(request.state, "user", None) or {}


def _guard_case(request: Request, case_id: str) -> None:
    """Guard a board endpoint that references a case_id."""
    if not case_id:
        return
    try:
        tenancy.guard_case(case_id, _user(request))
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")


def _org_id(request: Request) -> str:
    """Return the caller's org_id for stamping/filtering (or '' if tenancy off)."""
    s = tenancy.scope(_user(request))
    return s.get("org_id", "")


# ── models ───────────────────────────────────────────────────────────────────

class FolderRequest(BaseModel):
    name: str
    case_id: str = ""


class BoardCreateRequest(BaseModel):
    name: str
    description: str = ""
    folder_id: str = ""
    case_id: str = ""
    state: Optional[dict[str, Any]] = None


class BoardUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    folder_id: Optional[str] = None
    case_id: Optional[str] = None
    state: Optional[dict[str, Any]] = None


class ShareRequest(BaseModel):
    mode: str = "public"           # public | private
    password: str = ""
    live: bool = True              # False = frozen snapshot (court exhibit)
    expires_hours: int = 0


class SharedAccessRequest(BaseModel):
    password: str = ""


class CommentRequest(BaseModel):
    body: str
    node_ref: str = ""


class LinkRequest(BaseModel):
    kind: str = "address"          # nexus_subject | address | tx | case
    ref: str
    ref_chain: str = ""
    label: str = ""


# ── folders ──────────────────────────────────────────────────────────────────

@router.post("/boards/folders")
async def create_folder(req: FolderRequest, request: Request):
    _guard_case(request, req.case_id)
    try:
        folder = be.create_folder(req.name, req.case_id, _actor(request))
        # Stamp org_id for tenant isolation.
        oid = _org_id(request)
        if oid and folder.get("id"):
            import sqlite3
            with sqlite3.connect(be.DB_PATH) as con:
                con.execute("UPDATE board_folders SET org_id=? WHERE id=?", (oid, folder["id"]))
                con.commit()
        return folder
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/boards/folders")
async def list_folders(request: Request, case_id: str = ""):
    _guard_case(request, case_id)
    folders = be.list_folders(case_id)
    # Org filter: when tenancy is on, hide folders from other orgs.
    s = tenancy.scope(_user(request))
    if s.get("enabled"):
        oid = s["org_id"]
        folders = [f for f in folders if not f.get("org_id") or f.get("org_id") == oid]
    return {"folders": folders}


@router.patch("/boards/folders/{folder_id}")
async def rename_folder(folder_id: str, req: FolderRequest, request: Request):
    folder = be.rename_folder(folder_id, req.name)
    if not folder:
        raise HTTPException(status_code=404, detail="folder not found")
    return folder


@router.delete("/boards/folders/{folder_id}")
async def delete_folder(folder_id: str, request: Request):
    if not be.delete_folder(folder_id):
        raise HTTPException(status_code=404, detail="folder not found")
    return {"deleted": True}


# ── boards ───────────────────────────────────────────────────────────────────

@router.post("/boards")
async def create_board(req: BoardCreateRequest, request: Request):
    _guard_case(request, req.case_id)
    try:
        board = be.create_board(req.name, req.description, req.folder_id, req.case_id,
                                req.state, _actor(request))
        oid = _org_id(request)
        if oid and board.get("id"):
            import sqlite3
            with sqlite3.connect(be.DB_PATH) as con:
                con.execute("UPDATE boards SET org_id=? WHERE id=?", (oid, board["id"]))
                con.commit()
        return board
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/boards")
async def list_boards(request: Request, folder_id: str = "", case_id: str = ""):
    _guard_case(request, case_id)
    boards = be.list_boards(folder_id, case_id)
    s = tenancy.scope(_user(request))
    if s.get("enabled"):
        oid = s["org_id"]
        boards = [b for b in boards if not b.get("org_id") or b.get("org_id") == oid]
    return {"boards": boards}


@router.get("/boards/{board_id}")
async def get_board(board_id: str):
    board = be.get_board(board_id)
    if not board:
        raise HTTPException(status_code=404, detail="board not found")
    return board


@router.put("/boards/{board_id}")
async def update_board(board_id: str, req: BoardUpdateRequest):
    board = be.update_board(board_id, name=req.name, description=req.description,
                            folder_id=req.folder_id, case_id=req.case_id, state=req.state)
    if not board:
        raise HTTPException(status_code=404, detail="board not found")
    return board


@router.delete("/boards/{board_id}")
async def delete_board(board_id: str):
    if not be.delete_board(board_id):
        raise HTTPException(status_code=404, detail="board not found")
    return {"deleted": True}


@router.post("/boards/{board_id}/duplicate")
async def duplicate_board(board_id: str, request: Request):
    board = be.duplicate_board(board_id, _actor(request))
    if not board:
        raise HTTPException(status_code=404, detail="board not found")
    return board


# ── share links ──────────────────────────────────────────────────────────────

@router.post("/boards/{board_id}/share")
async def create_share(board_id: str, req: ShareRequest, request: Request):
    try:
        return be.create_share(board_id, req.mode, req.password, req.live,
                               req.expires_hours, _actor(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/boards/{board_id}/shares")
async def list_shares(board_id: str):
    return {"shares": be.list_shares(board_id)}


@router.post("/boards/share/{token}/revoke")
async def revoke_share(token: str):
    if not be.revoke_share(token):
        raise HTTPException(status_code=404, detail="share not found")
    return {"revoked": True}


# PUBLIC endpoints (whitelisted in main.py) — external parties open share links
# without a CrypTX account. Private links additionally require the password.

@router.get("/boards/shared/{token}/meta")
async def shared_meta(token: str):
    try:
        return be.share_meta(token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/boards/shared/{token}")
async def shared_access(token: str, req: SharedAccessRequest):
    try:
        return be.resolve_share(token, req.password)
    except ValueError as exc:
        detail = str(exc)
        code = 401 if "password" in detail else 404 if "not found" in detail else 410
        raise HTTPException(status_code=code, detail=detail)


# ── comments ─────────────────────────────────────────────────────────────────

@router.get("/boards/{board_id}/comments")
async def list_comments(board_id: str, include_resolved: bool = True):
    return {"comments": be.list_comments(board_id, include_resolved)}


@router.post("/boards/{board_id}/comments")
async def add_comment(board_id: str, req: CommentRequest, request: Request):
    try:
        return be.add_comment(board_id, req.body, _actor(request), req.node_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/boards/comments/{comment_id}/resolve")
async def resolve_comment(comment_id: str, resolved: bool = True):
    if not be.resolve_comment(comment_id, resolved):
        raise HTTPException(status_code=404, detail="comment not found")
    return {"resolved": resolved}


@router.delete("/boards/comments/{comment_id}")
async def delete_comment(comment_id: str):
    if not be.delete_comment(comment_id):
        raise HTTPException(status_code=404, detail="comment not found")
    return {"deleted": True}


# ── board ↔ investigation links (bidirectional Nexus bridge) ─────────────────

@router.post("/boards/{board_id}/links")
async def add_link(board_id: str, req: LinkRequest, request: Request):
    try:
        return be.add_link(board_id, req.kind, req.ref, req.ref_chain, req.label, _actor(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/boards/{board_id}/links")
async def board_links(board_id: str):
    return {"links": be.links_for_board(board_id)}


@router.get("/board-links")
async def links_for_ref(ref: str, kind: str = ""):
    """All boards linked to an address / subject / tx — powers the Nexus 'Linked boards' panel."""
    return {"ref": ref, "boards": be.boards_for_ref(ref, kind)}


@router.delete("/board-links/{link_id}")
async def delete_link(link_id: str):
    if not be.delete_link(link_id):
        raise HTTPException(status_code=404, detail="link not found")
    return {"deleted": True}
