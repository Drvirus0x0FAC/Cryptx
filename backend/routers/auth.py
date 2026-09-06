from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

import auth_service

router = APIRouter(tags=["Authentication"])


# ── Lightweight brute-force rate limiter for auth endpoints ───────────────────
# Tracks per-IP failed-attempt counts; locks out for a window after N failures.
# In-process (sufficient for single-process SQLite deployment).
_AUTH_RATE: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 300       # 5 min rolling window
_RATE_MAX_FAILURES = 10  # lockout threshold


def _check_rate_limit(ip: str) -> None:
    now = time.time()
    attempts = [t for t in _AUTH_RATE[ip] if now - t < _RATE_WINDOW]
    _AUTH_RATE[ip] = attempts
    if len(attempts) >= _RATE_MAX_FAILURES:
        retry_in = int(_RATE_WINDOW - (now - attempts[0]))
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {retry_in}s.",
        )


def _record_auth_failure(ip: str) -> None:
    _AUTH_RATE[ip].append(time.time())


def _clear_auth_failures(ip: str) -> None:
    _AUTH_RATE.pop(ip, None)


import re
import secrets
import hashlib
import time

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_PASSWORD_MIN_LENGTH = 10
_PASSWORD_MAX_LENGTH = 128

# ── 2FA pending login tokens (in-memory, short-lived) ────────────────────────
# When a user has 2FA enabled, login returns a temporary token instead of a
# session. The client then POSTs the TOTP code with this token to get the
# real session. Entries expire after 5 minutes.
_2FA_PENDING: dict[str, dict] = {}  # token -> {user_id, created_at}
_2FA_PENDING_TTL = 300  # 5 minutes


def _create_2fa_pending(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    _2FA_PENDING[token] = {"user_id": user_id, "created_at": time.time()}
    # Prune expired entries
    now = time.time()
    expired = [k for k, v in _2FA_PENDING.items() if now - v["created_at"] > _2FA_PENDING_TTL]
    for k in expired:
        del _2FA_PENDING[k]
    return token


def _validate_email(email: str) -> str:
    email = email.strip().lower()
    if not email or len(email) > 254:
        raise ValueError("invalid email address")
    if not _EMAIL_RE.match(email):
        raise ValueError("invalid email format")
    return email


def _validate_password(password: str) -> str:
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"password must be at least {_PASSWORD_MIN_LENGTH} characters")
    if len(password) > _PASSWORD_MAX_LENGTH:
        raise ValueError(f"password must be at most {_PASSWORD_MAX_LENGTH} characters")
    # Require at least 3 of: uppercase, lowercase, digit, special
    checks = [
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[0-9]", password)),
        bool(re.search(r"[^A-Za-z0-9]", password)),
    ]
    if sum(checks) < 3:
        raise ValueError("password must contain at least 3 of: uppercase, lowercase, digit, special character")
    return password


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""
    registration_type: str = "researcher"
    team_name: str = ""

    def validate_fields(self):
        self.email = _validate_email(self.email)
        self.password = _validate_password(self.password)
        if self.name and len(self.name) > 120:
            raise ValueError("name too long")
        if self.registration_type not in ("researcher", "team_leader"):
            self.registration_type = "researcher"
        if self.registration_type == "team_leader" and not self.team_name.strip():
            raise ValueError("team name is required for team leader registration")


class LoginRequest(BaseModel):
    email: str
    password: str

    def validate_fields(self):
        self.email = _validate_email(self.email)


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    def validate_fields(self):
        self.password = _validate_password(self.password)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class UpdateProfileRequest(BaseModel):
    name: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    def validate_fields(self):
        self.new_password = _validate_password(self.new_password)


def _client_meta(request: Request) -> tuple[str, str]:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",", 1)[0].strip() or (request.client.host if request.client else "")
    return request.headers.get("user-agent", ""), ip


def _session(user: dict, request: Request):
    ua, ip = _client_meta(request)
    return auth_service.create_session(user, ua, ip)


@router.post("/auth/register")
async def register(req: RegisterRequest, request: Request):
    try:
        req.validate_fields()
        user = auth_service.register_user(
            req.email, req.password, req.name,
            registration_type=req.registration_type,
            team_name=req.team_name,
        )
        return _session(user, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/login")
async def login(req: LoginRequest, request: Request):
    _, ip = _client_meta(request)
    _check_rate_limit(ip)  # brute-force protection
    try:
        req.validate_fields()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid email format")
    user = auth_service.authenticate(req.email, req.password)
    if not user:
        _record_auth_failure(ip)
        raise HTTPException(status_code=401, detail="invalid email or password")
    _clear_auth_failures(ip)  # successful login resets the counter
    # 2FA check: if user has TOTP enabled, require a second factor
    if user.get("totp_enabled"):
        pending_token = _create_2fa_pending(str(user["id"]))
        return {"requires_2fa": True, "pending_token": pending_token}
    return _session(user, request)


@router.post("/auth/refresh")
async def refresh(req: RefreshRequest, request: Request):
    try:
        ua, ip = _client_meta(request)
        return auth_service.refresh_session(req.refresh_token, ua, ip)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/auth/logout")
async def logout(req: LogoutRequest, authorization: str | None = Header(default=None)):
    try:
        _, session = auth_service.user_and_session_from_bearer(authorization)
        auth_service.revoke_session(session["id"], "logout")
    except ValueError:
        if req.refresh_token:
            auth_service.revoke_refresh_token(req.refresh_token, "logout")
    return {"revoked": True}


@router.get("/auth/me")
async def me(authorization: str | None = Header(default=None)):
    try:
        user, session = auth_service.user_and_session_from_bearer(authorization)
        return {"user": auth_service.public_user(user), "session": auth_service.public_session(session)}
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.patch("/auth/profile")
async def update_profile(req: UpdateProfileRequest, authorization: str | None = Header(default=None)):
    try:
        user, _ = auth_service.user_and_session_from_bearer(authorization)
        updated = auth_service.update_user_profile(user["id"], req.name)
        return {"user": auth_service.public_user(updated)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/change-password")
async def change_password(req: ChangePasswordRequest, request: Request, authorization: str | None = Header(default=None)):
    try:
        req.validate_fields()
        user, session = auth_service.user_and_session_from_bearer(authorization)
        updated = auth_service.change_password(user["id"], req.current_password, req.new_password)
        # Password rotation revokes every existing session; return a fresh one for this browser.
        return _session(updated, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/auth/sessions")
async def sessions(authorization: str | None = Header(default=None)):
    try:
        user, session = auth_service.user_and_session_from_bearer(authorization)
        return {"current_session_id": session["id"], "sessions": auth_service.list_user_sessions(user["id"])}
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.delete("/auth/sessions/{session_id}")
async def revoke_session(session_id: str, authorization: str | None = Header(default=None)):
    try:
        user, current = auth_service.user_and_session_from_bearer(authorization)
        sessions = auth_service.list_user_sessions(user["id"])
        if not any(s["id"] == session_id for s in sessions):
            raise HTTPException(status_code=404, detail="session not found")
        if session_id == current["id"]:
            raise HTTPException(status_code=400, detail="use logout to revoke the current session")
        auth_service.revoke_session(session_id, "revoked_from_profile")
        return {"revoked": True}
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ── RBAC: admin user management ───────────────────────────────────────────────

def _require_admin(authorization: str | None) -> dict:
    try:
        user, _ = auth_service.user_and_session_from_bearer(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if (user.get("role") or "analyst") != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


class SetRoleRequest(BaseModel):
    role: str


class SetActiveRequest(BaseModel):
    is_active: bool


@router.get("/auth/users")
async def admin_list_users(authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    return {"users": auth_service.list_users(), "roles": list(auth_service.VALID_ROLES)}


@router.patch("/auth/users/{user_id}/role")
async def admin_set_role(user_id: str, req: SetRoleRequest, authorization: str | None = Header(default=None)):
    admin = _require_admin(authorization)
    try:
        return {"user": auth_service.set_user_role(user_id, req.role, str(admin["id"]))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/auth/users/{user_id}/active")
async def admin_set_active(user_id: str, req: SetActiveRequest, authorization: str | None = Header(default=None)):
    admin = _require_admin(authorization)
    try:
        return {"user": auth_service.set_user_active(user_id, req.is_active, str(admin["id"]))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/logout-all")
async def logout_all(authorization: str | None = Header(default=None)):
    try:
        user, current = auth_service.user_and_session_from_bearer(authorization)
        auth_service.revoke_user_sessions(user["id"], "logout_all", except_session_id=current["id"])
        return {"revoked": True}
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    try:
        email = _validate_email(req.email)
    except ValueError:
        # Don't reveal whether the email exists — always return success
        return {"reset_requested": True}
    return auth_service.create_password_reset(email)


@router.post("/auth/reset-password")
async def reset_password(req: ResetPasswordRequest):
    try:
        req.validate_fields()
        user = auth_service.reset_password(req.token, req.password)
        return {
            "reset": True,
            "user": auth_service.public_user(user),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Team management (team leaders) ────────────────────────────────────────────

def _require_team_leader(authorization: str | None) -> dict:
    """Require the caller to be a team_leader or global admin."""
    try:
        user, _ = auth_service.user_and_session_from_bearer(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    reg_type = user.get("registration_type") or "researcher"
    global_role = user.get("role") or "analyst"
    if reg_type != "team_leader" and global_role != "admin":
        raise HTTPException(status_code=403, detail="team leader role required")
    return user


class CreateTeamMemberRequest(BaseModel):
    email: str
    name: str
    temp_password: str = ""

    def validate_fields(self):
        self.email = _validate_email(self.email)
        if not self.name.strip():
            raise ValueError("name is required")
        if self.temp_password and len(self.temp_password) < 8:
            raise ValueError("temporary password must be at least 8 characters")


class UpdateTeamNameRequest(BaseModel):
    team_name: str

    def validate_fields(self):
        if not self.team_name.strip():
            raise ValueError("team name cannot be empty")
        if len(self.team_name) > 120:
            raise ValueError("team name too long")


@router.get("/auth/team/info")
async def team_info(authorization: str | None = Header(default=None)):
    user = _require_team_leader(authorization)
    import tenancy
    org = tenancy.get_org(user["org_id"]) if user.get("org_id") else None
    if not org:
        raise HTTPException(status_code=404, detail="team not found")
    members = tenancy.list_org_members(org["id"])
    return {
        "team": {
            "id": org["id"],
            "name": org["name"],
            "slug": org.get("slug") or "",
            "plan": org.get("plan") or "investigator",
            "created_at": org.get("created_at") or "",
        },
        "members": members,
        "member_count": len(members),
    }


@router.patch("/auth/team/name")
async def update_team_name(req: UpdateTeamNameRequest, authorization: str | None = Header(default=None)):
    user = _require_team_leader(authorization)
    try:
        req.validate_fields()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    import tenancy
    org = tenancy.update_org(user["org_id"], name=req.team_name.strip())
    if not org:
        raise HTTPException(status_code=404, detail="team not found")
    return {"team": {"id": org["id"], "name": org["name"], "slug": org.get("slug") or ""}}


@router.post("/auth/team/members")
async def create_team_member(req: CreateTeamMemberRequest, authorization: str | None = Header(default=None)):
    user = _require_team_leader(authorization)
    try:
        req.validate_fields()
        result = auth_service.create_team_member(user, req.email, req.name, req.temp_password)
        return {"member": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/auth/team/members")
async def list_team_members(authorization: str | None = Header(default=None)):
    user = _require_team_leader(authorization)
    import tenancy
    members = tenancy.list_org_members(user["org_id"])
    return {"members": members}


@router.delete("/auth/team/members/{member_id}")
async def remove_team_member(member_id: str, authorization: str | None = Header(default=None)):
    user = _require_team_leader(authorization)
    if str(member_id) == str(user["id"]):
        raise HTTPException(status_code=400, detail="cannot remove yourself from the team")
    target = auth_service.get_user_by_id(member_id)
    if not target:
        raise HTTPException(status_code=404, detail="member not found")
    if str(target.get("org_id") or "") != str(user.get("org_id") or ""):
        raise HTTPException(status_code=403, detail="member belongs to a different team")
    auth_service.set_user_active(member_id, False, user["id"])
    return {"removed": True}


# ── 2FA endpoints ─────────────────────────────────────────────────────────────

class TwoFAVerifyLoginRequest(BaseModel):
    pending_token: str
    code: str


class TwoFACodeRequest(BaseModel):
    code: str


class TwoFATeamDisableRequest(BaseModel):
    member_id: str


@router.post("/auth/2fa/verify")
async def verify_2fa_login(req: TwoFAVerifyLoginRequest, request: Request):
    """Complete a 2FA login by verifying the TOTP code with the pending token."""
    _, ip = _client_meta(request)
    _check_rate_limit(ip)
    pending = _2FA_PENDING.get(req.pending_token)
    if not pending:
        raise HTTPException(status_code=401, detail="invalid or expired 2FA token")
    if time.time() - pending["created_at"] > _2FA_PENDING_TTL:
        del _2FA_PENDING[req.pending_token]
        raise HTTPException(status_code=401, detail="2FA token expired")
    user_id = pending["user_id"]
    if not auth_service.verify_totp_login(user_id, req.code):
        _record_auth_failure(ip)
        raise HTTPException(status_code=401, detail="invalid 2FA code")
    _clear_auth_failures(ip)
    del _2FA_PENDING[req.pending_token]
    user = auth_service.get_user_by_id(user_id)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="user is inactive")
    return _session(user, request)


@router.post("/auth/2fa/setup")
async def setup_2fa(authorization: str | None = Header(default=None)):
    """Generate a TOTP secret and QR code for the user."""
    try:
        user, _ = auth_service.user_and_session_from_bearer(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    result = auth_service.setup_totp(user["id"])
    return result


@router.post("/auth/2fa/enable")
async def enable_2fa(req: TwoFACodeRequest, authorization: str | None = Header(default=None)):
    """Enable 2FA after verifying the TOTP code from the setup step."""
    try:
        user, _ = auth_service.user_and_session_from_bearer(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        auth_service.enable_totp(user["id"], req.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"totp_enabled": True}


@router.post("/auth/2fa/disable")
async def disable_2fa(req: TwoFACodeRequest, authorization: str | None = Header(default=None)):
    """Disable own 2FA — requires a valid TOTP code.
    Team members (org_role != org_admin) are NOT allowed to disable 2FA."""
    try:
        user, _ = auth_service.user_and_session_from_bearer(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    # Team members cannot disable their own 2FA
    if user.get("registration_type") == "researcher" and user.get("org_id"):
        org_role = user.get("org_role") or "analyst"
        if org_role != "org_admin":
            raise HTTPException(status_code=403, detail="team members cannot disable 2FA — contact your team leader")
    try:
        auth_service.disable_totp_self(user["id"], req.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"totp_enabled": False}


@router.post("/auth/2fa/team-disable")
async def team_disable_2fa(req: TwoFATeamDisableRequest, authorization: str | None = Header(default=None)):
    """Team leader disables 2FA for a team member (no code required from the member)."""
    leader = _require_team_leader(authorization)
    target = auth_service.get_user_by_id(req.member_id)
    if not target:
        raise HTTPException(status_code=404, detail="member not found")
    if str(target.get("org_id") or "") != str(leader.get("org_id") or ""):
        raise HTTPException(status_code=403, detail="member belongs to a different team")
    auth_service.disable_totp(req.member_id)
    return {"totp_enabled": False, "user_id": req.member_id}


# ── Beacon logout (tab close) ────────────────────────────────────────────────

@router.post("/auth/beacon-logout")
async def beacon_logout(authorization: str | None = Header(default=None)):
    """Revoke the current session — called from beforeunload beacon on tab close."""
    try:
        _, session = auth_service.user_and_session_from_bearer(authorization)
        auth_service.revoke_session(session["id"], "tab_closed")
    except ValueError:
        pass  # best-effort; token may already be invalid
    return {"revoked": True}
