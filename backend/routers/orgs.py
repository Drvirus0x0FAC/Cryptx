"""
Organization management router — /api/orgs

Endpoints for org CRUD and membership. All scoped by the caller's org:
  * Regular users see/manage only their own org.
  * Global site admins (role='admin', the bootstrap superuser) can list/create
    all orgs — this is how a SaaS operator provisions new customer orgs.

Mounted under /api in main.py. Auth enforced by the global middleware.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

import tenancy
import auth_service

router = APIRouter(prefix="/orgs", tags=["Organizations"])


def _user(request: Request) -> dict:
    return getattr(request.state, "user", None) or {}


def _require_org_admin(request: Request, org_id: str) -> dict:
    """Ensure the caller may manage the given org: org_admin of that org, or global admin."""
    user = _user(request)
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    if str(user.get("role") or "") == "admin":
        return user  # global site admin
    if str(user.get("org_id") or "") != str(org_id):
        raise HTTPException(status_code=403, detail="not a member of this organization")
    if str(user.get("org_role") or "analyst") != "org_admin":
        raise HTTPException(status_code=403, detail="organization admin role required")
    return user


# ── Request models ───────────────────────────────────────────────────────────

class CreateOrgRequest(BaseModel):
    name: str
    slug: str = ""
    plan: str = "investigator"
    settings: Optional[dict] = None


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    settings: Optional[dict] = None


class SetMemberRoleRequest(BaseModel):
    role: str  # org_admin | analyst | viewer


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "analyst"


# ── Org CRUD ─────────────────────────────────────────────────────────────────

@router.get("")
def list_orgs(request: Request):
    """List orgs. Global admins see all; everyone else sees only their own."""
    user = _user(request)
    if str(user.get("role") or "") == "admin":
        return {"organizations": tenancy.list_orgs()}
    org_id = str(user.get("org_id") or "")
    if not org_id:
        return {"organizations": []}
    org = tenancy.get_org(org_id)
    return {"organizations": [org] if org else []}


@router.post("", status_code=201)
def create_org(req: CreateOrgRequest, request: Request):
    """Create a new org. Global site admin only (SaaS operator provisioning)."""
    user = _user(request)
    if str(user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="global site admin required to create organizations")
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    try:
        org = tenancy.create_org(req.name, req.slug, req.plan, req.settings)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return org


@router.get("/mine")
def get_my_org(request: Request):
    """Return the caller's organization."""
    user = _user(request)
    org_id = str(user.get("org_id") or "")
    if not org_id:
        return {"organization": None}
    return {"organization": tenancy.get_org(org_id)}


@router.get("/{org_id}")
def get_org(org_id: str, request: Request):
    user = _user(request)
    # Members see their own org; global admins see any.
    if str(user.get("role") or "") != "admin" and str(user.get("org_id") or "") != str(org_id):
        raise HTTPException(status_code=403, detail="not a member of this organization")
    org = tenancy.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="organization not found")
    return org


@router.patch("/{org_id}")
def update_org(org_id: str, req: UpdateOrgRequest, request: Request):
    _require_org_admin(request, org_id)
    org = tenancy.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="organization not found")
    fields = req.model_dump()
    if fields.get("settings") is not None:
        import json
        fields["settings_json"] = json.dumps(fields.pop("settings"))
    else:
        fields.pop("settings", None)
    return tenancy.update_org(org_id, **fields)


# ── Membership ───────────────────────────────────────────────────────────────

@router.get("/{org_id}/members")
def list_members(org_id: str, request: Request):
    user = _user(request)
    if str(user.get("role") or "") != "admin" and str(user.get("org_id") or "") != str(org_id):
        raise HTTPException(status_code=403, detail="not a member of this organization")
    org = tenancy.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="organization not found")
    return {"members": tenancy.list_org_members(org_id)}


@router.patch("/{org_id}/members/{user_id}/role")
def set_member_role(org_id: str, user_id: str, req: SetMemberRoleRequest, request: Request):
    _require_org_admin(request, org_id)
    try:
        updated = tenancy.set_org_member_role(org_id, user_id, req.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="user not found in this organization")
    # Revoke the affected user's sessions so their new role takes effect on next login.
    try:
        auth_service.revoke_user_sessions(user_id, reason="org_role_changed")
    except Exception:
        pass
    return auth_service.public_user(updated)


@router.post("/{org_id}/members")
def invite_member(org_id: str, req: InviteMemberRequest, request: Request):
    """Add an existing user (by email) to this org. Org admin only.

    NOTE: this is a same-instance invite (the user must already have an account).
    Email-based out-of-band invitations are a Phase 1 concern (need an email
    sender). For now this lets an org_admin pull in an analyst who already
    registered on this deployment.
    """
    _require_org_admin(request, org_id)
    target = auth_service.get_user_by_email(req.email.strip())
    if not target:
        raise HTTPException(status_code=404, detail="no account found with that email; ask them to register first")
    if req.role not in ("org_admin", "analyst", "viewer"):
        raise HTTPException(status_code=400, detail="role must be org_admin, analyst, or viewer")
    updated = tenancy.assign_user_to_org(str(target["id"]), org_id, req.role)
    if not updated:
        raise HTTPException(status_code=500, detail="could not assign user to org")
    # Revoke sessions so the move takes effect.
    try:
        auth_service.revoke_user_sessions(str(target["id"]), reason="org_membership_changed")
    except Exception:
        pass
    return auth_service.public_user(updated)
