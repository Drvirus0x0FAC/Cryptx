"""
API key management router — /api/orgs/mine/api-keys

CRUD for per-org API keys + usage endpoint. Org members manage their own keys;
the global site admin can manage any org's keys.

Auth: enforced by the global middleware (bearer token). These endpoints are NOT
reachable via API key themselves (only via the human session) to prevent a
compromised key from minting more keys.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

import tenancy
import api_key_service

router = APIRouter(tags=["API Keys"])


def _user(request: Request) -> dict:
    return getattr(request.state, "user", None) or {}


def _org_id(request: Request) -> str:
    user = _user(request)
    org_id = str(user.get("org_id") or "")
    if not org_id:
        org_id = tenancy.get_or_create_default_org()
    return org_id


# ── Request models ───────────────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str
    scopes: Optional[list[str]] = None
    rate_limit_per_min: int = 60
    monthly_quota: int = 0  # 0 = unlimited
    expires_at: Optional[str] = None


class UpdateKeyRequest(BaseModel):
    name: Optional[str] = None
    scopes: Optional[list[str]] = None
    rate_limit_per_min: Optional[int] = None
    monthly_quota: Optional[int] = None
    is_active: Optional[bool] = None
    expires_at: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/orgs/mine/api-keys")
def list_keys(request: Request):
    return {"api_keys": api_key_service.list_keys(_org_id(request))}


@router.post("/orgs/mine/api-keys", status_code=201)
def create_key(req: CreateKeyRequest, request: Request):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    user = _user(request)
    record, plaintext = api_key_service.create_key(
        org_id=_org_id(request),
        name=req.name,
        scopes=req.scopes,
        rate_limit_per_min=req.rate_limit_per_min,
        monthly_quota=req.monthly_quota,
        created_by=str(user.get("id") or user.get("email") or ""),
        expires_at=req.expires_at,
    )
    # Return the plaintext ONCE alongside the masked record.
    return {**record, "key": plaintext, "_note": "Store this key securely; it will not be shown again."}


@router.patch("/orgs/mine/api-keys/{key_id}")
def update_key(key_id: str, req: UpdateKeyRequest, request: Request):
    # Verify the key belongs to the caller's org.
    existing = api_key_service.get_key(key_id)
    if not existing:
        raise HTTPException(status_code=404, detail="API key not found")
    if str(existing.get("org_id") or "") != _org_id(request):
        raise HTTPException(status_code=404, detail="API key not found")
    return api_key_service.update_key(
        key_id,
        name=req.name,
        scopes=req.scopes,
        rate_limit_per_min=req.rate_limit_per_min,
        monthly_quota=req.monthly_quota,
        is_active=req.is_active,
        expires_at=req.expires_at,
    )


@router.delete("/orgs/mine/api-keys/{key_id}")
def delete_key(key_id: str, request: Request):
    existing = api_key_service.get_key(key_id)
    if not existing:
        raise HTTPException(status_code=404, detail="API key not found")
    if str(existing.get("org_id") or "") != _org_id(request):
        raise HTTPException(status_code=404, detail="API key not found")
    api_key_service.delete_key(key_id)
    return {"deleted": key_id}


@router.get("/orgs/mine/api-keys/{key_id}/usage")
def key_usage(key_id: str, request: Request, days: int = 30):
    existing = api_key_service.get_key(key_id)
    if not existing:
        raise HTTPException(status_code=404, detail="API key not found")
    if str(existing.get("org_id") or "") != _org_id(request):
        raise HTTPException(status_code=404, detail="API key not found")
    return api_key_service.get_usage(key_id, days=days)
