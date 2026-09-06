"""
SSO router — /api/auth/sso/oidc/*

OIDC login/callback endpoints. These are PUBLIC (no bearer required) — they're
added to PUBLIC_PREFIXES in main.py. After a successful callback, we issue a
CrypTX JWT + session identical to password login so the frontend needs no changes.

For a logged-in user wanting to link an additional IdP, POST /api/auth/sso/link
requires a bearer token.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel

import auth_service
import sso_service
import config as _config

router = APIRouter(prefix="/auth/sso", tags=["SSO"])


def _redirect_uri(provider: str, request: Request) -> str:
    """Build the callback URL for this provider.

    Uses BASE_URL env (so it works behind a reverse proxy) falling back to the
    incoming request's base.
    """
    base = _config.BASE_URL or str(request.base_url).rstrip("/")
    return f"{base}/api/auth/sso/oidc/{provider}/callback"


def _open_session(user: dict, request: Request) -> dict:
    """Open a CrypTX session for the SSO-authenticated user (mirrors auth.py)."""
    ua = request.headers.get("user-agent", "")
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else ""
    )
    return auth_service.create_session(user, ua, ip)


# ── Login + callback ────────────────────────────────────────────────────────

@router.get("/providers")
def list_providers():
    """List configured OIDC providers (for the login page to render buttons)."""
    return {"providers": sso_service.list_configured_providers()}


@router.get("/oidc/{provider}/login")
async def oidc_login(provider: str, request: Request):
    """Redirect the user to the IdP's authorization endpoint."""
    cfg = sso_service.get_provider_config(provider)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"OIDC provider '{provider}' is not configured")
    state = secrets.token_urlsafe(24)
    redirect_uri = _redirect_uri(provider, request)
    auth_url = sso_service.get_authorization_url(provider, redirect_uri, state)
    if not auth_url:
        raise HTTPException(status_code=502, detail="could not reach IdP discovery endpoint")
    # Redirect to IdP; carry state in a cookie for CSRF protection on callback.
    resp = RedirectResponse(url=auth_url)
    resp.set_cookie("sso_state", state, httponly=True, samesite="lax", max_age=600, secure=request.url.scheme == "https")
    resp.set_cookie("sso_redirect_uri", redirect_uri, httponly=True, samesite="lax", max_age=600)
    return resp


@router.get("/oidc/{provider}/callback")
async def oidc_callback(provider: str, request: Request):
    """Handle the IdP redirect: exchange code, match/provision user, open session."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    cookie_state = request.cookies.get("sso_state")
    redirect_uri = request.cookies.get("sso_redirect_uri") or _redirect_uri(provider, request)

    if not code:
        raise HTTPException(status_code=400, detail="missing authorization code")
    # SECURITY: both state and cookie_state MUST be present AND match.
    # The old check (`if state and cookie_state and state != cookie_state`)
    # was bypassable by stripping either parameter.
    if not state or not cookie_state or state != cookie_state:
        raise HTTPException(status_code=400, detail="SSO state mismatch (possible CSRF)")

    userinfo = await sso_service.exchange_code_for_userinfo(provider, code, redirect_uri)
    if not userinfo:
        raise HTTPException(status_code=502, detail="failed to fetch userinfo from IdP")

    subject = str(userinfo.get("sub") or "")
    email = str(userinfo.get("email") or "").strip().lower()
    name = str(userinfo.get("name") or userinfo.get("preferred_username") or "")

    if not subject:
        raise HTTPException(status_code=502, detail="IdP returned no subject")

    user = sso_service.match_or_provision(provider, subject, email, name)
    if not user:
        raise HTTPException(
            status_code=403,
            detail="No matching account and JIT provisioning is disabled. Ask an admin to create your account.",
        )

    session = _open_session(user, request)
    # Return JSON (the frontend's SSO handler stores the tokens). Also clear the
    # SSO cookies. A future enhancement can redirect to a frontend deep-link.
    resp = JSONResponse(content=session)
    resp.delete_cookie("sso_state")
    resp.delete_cookie("sso_redirect_uri")
    return resp


# ── Link an additional IdP to the current user ──────────────────────────────

class LinkIdentityRequest(BaseModel):
    provider: str
    subject: str
    email: str = ""


@router.post("/link")
def link_identity(req: LinkIdentityRequest, request: Request):
    """Link an IdP identity to the logged-in user (requires bearer token).

    SECURITY: Only admins can link identities manually. The normal flow is
    automatic via the callback's match_or_provision step. Manual linking
    without proof-of-ownership of the IdP identity is a privilege escalation
    vector — restricted to admins who understand the risk.
    """
    user = getattr(request.state, "user", None) or {}
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="authentication required")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin role required to link identities manually")
    return sso_service.link_identity_for_current_user(
        user, req.provider, req.subject, req.email
    )


@router.get("/identities")
def my_identities(request: Request):
    """List the IdP identities linked to the current user."""
    user = getattr(request.state, "user", None) or {}
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="authentication required")
    return {"identities": sso_service.list_user_identities(str(user["id"]))}
