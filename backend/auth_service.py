"""
SQLite-backed authentication for CrypTX.

Uses PBKDF2 password hashes, HMAC-signed bearer tokens, and stateful
server-side sessions. Password-reset and refresh tokens are stored hashed so
leaked database rows are not usable as credentials.

Stored in the same `cryptoosint.db` SQLite database as the rest of the app, so
no separate database server is required.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Centralized config — single source of truth for DB path, auth secret, TTLs.
# auth_service re-exports these so existing `from auth_service import DB_PATH`
# style imports keep working without touching call sites.
import config as _config

DB_PATH = _config.DB_PATH
AUTH_SECRET = _config.AUTH_SECRET
TOKEN_TTL_MINUTES = _config.TOKEN_TTL_MINUTES
ACCESS_TOKEN_TTL_MINUTES = _config.ACCESS_TOKEN_TTL_MINUTES
REFRESH_TOKEN_TTL_DAYS = _config.REFRESH_TOKEN_TTL_DAYS
RESET_TTL_MINUTES = _config.RESET_TTL_MINUTES
DEV_RESET_TOKENS = _config.DEV_RESET_TOKENS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(v: datetime) -> str:
    return v.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _query_one(sql: str, params: tuple = ()) -> Optional[dict[str, Any]]:
    with _connect() as con:
        row = con.execute(sql, params).fetchone()
    return dict(row) if row else None


def _execute(sql: str, params: tuple = ()) -> None:
    with _connect() as con:
        con.execute(sql, params)
        con.commit()


# ---------------------------------------------------------------------------
# Password hashing + token signing (stdlib only)
# ---------------------------------------------------------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
    return f"pbkdf2_sha256$210000${_b64url(salt)}${_b64url(digest)}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, digest_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = _b64url_decode(salt_b64)
        expected = _b64url_decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sign(data: str) -> str:
    return _b64url(hmac.new(AUTH_SECRET.encode("utf-8"), data.encode("ascii"), hashlib.sha256).digest())


def create_access_token(user: dict[str, Any], session_id: str | None = None, token_id: str | None = None) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = _now()
    payload = {
        "sub": user["id"],
        "sid": session_id or "",
        "jti": token_id or str(uuid.uuid4()),
        "email": user["email"],
        "name": user.get("name") or "",
        "role": user.get("role") or "analyst",
        # Multi-tenancy: org_id travels in the JWT so every request resolves the
        # caller's tenant without an extra DB lookup. The DB row is the source of
        # truth; if a user is moved between orgs, a new token picks up the change.
        "tid": user.get("org_id") or "",
        "org_role": user.get("org_role") or "analyst",
        "exp": int((now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)).timestamp()),
        "iat": int(now.timestamp()),
    }
    head = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{head}.{body}"
    return f"{signing_input}.{_sign(signing_input)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        head, body, sig = token.split(".", 2)
        signing_input = f"{head}.{body}"
        if not hmac.compare_digest(sig, _sign(signing_input)):
            raise ValueError("bad signature")
        payload = json.loads(_b64url_decode(body))
        if int(payload.get("exp", 0)) < int(_now().timestamp()):
            raise ValueError("token expired")
        return payload
    except Exception as exc:
        raise ValueError("invalid token") from exc


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def init_auth_db() -> None:
    with _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_users (
                id              TEXT PRIMARY KEY,
                email           TEXT NOT NULL UNIQUE,
                name            TEXT NOT NULL DEFAULT '',
                password_hash   TEXT NOT NULL,
                role            TEXT NOT NULL DEFAULT 'analyst',
                is_active       INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                last_login_at   TEXT
            );
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
                token_hash  TEXT NOT NULL UNIQUE,
                expires_at  TEXT NOT NULL,
                used_at     TEXT,
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id);
            CREATE INDEX IF NOT EXISTS idx_password_reset_token ON password_reset_tokens(token_hash);
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id                  TEXT PRIMARY KEY,
                user_id             TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
                access_jti          TEXT NOT NULL UNIQUE,
                refresh_token_hash  TEXT NOT NULL UNIQUE,
                user_agent          TEXT NOT NULL DEFAULT '',
                ip_address          TEXT NOT NULL DEFAULT '',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                last_seen_at        TEXT NOT NULL,
                access_expires_at   TEXT NOT NULL,
                refresh_expires_at  TEXT NOT NULL,
                revoked_at          TEXT,
                revoked_reason      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_refresh ON auth_sessions(refresh_token_hash);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_access ON auth_sessions(access_jti);
            """
        )
        # Multi-tenancy columns — added via ALTER TABLE so existing DBs migrate
        # in place. tenancy.init_tenancy_tables() also adds these but we keep them
        # here so app_users is org-aware even before the tenancy engine loads.
        _cols = {r["name"] for r in con.execute("PRAGMA table_info(app_users)").fetchall()}
        if "org_id" not in _cols:
            con.execute("ALTER TABLE app_users ADD COLUMN org_id TEXT DEFAULT ''")
        if "org_role" not in _cols:
            con.execute("ALTER TABLE app_users ADD COLUMN org_role TEXT DEFAULT 'analyst'")
        if "registration_type" not in _cols:
            con.execute("ALTER TABLE app_users ADD COLUMN registration_type TEXT DEFAULT 'researcher'")
        if "must_change_password" not in _cols:
            con.execute("ALTER TABLE app_users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        if "totp_secret" not in _cols:
            con.execute("ALTER TABLE app_users ADD COLUMN totp_secret TEXT DEFAULT ''")
        if "totp_enabled" not in _cols:
            con.execute("ALTER TABLE app_users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0")
        con.commit()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "name": row.get("name") or "",
        "role": row.get("role") or "analyst",
        "registration_type": row.get("registration_type") or "researcher",
        "must_change_password": bool(row.get("must_change_password")),
        "totp_enabled": bool(row.get("totp_enabled")),
        "org_id": row.get("org_id") or "",
        "org_role": row.get("org_role") or "analyst",
        "created_at": str(row.get("created_at") or ""),
        "last_login_at": str(row.get("last_login_at")) if row.get("last_login_at") else None,
    }


def public_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "created_at": str(row.get("created_at") or ""),
        "last_seen_at": str(row.get("last_seen_at") or ""),
        "access_expires_at": str(row.get("access_expires_at") or ""),
        "refresh_expires_at": str(row.get("refresh_expires_at") or ""),
        "revoked_at": str(row.get("revoked_at")) if row.get("revoked_at") else None,
        "revoked_reason": row.get("revoked_reason") or None,
        "user_agent": row.get("user_agent") or "",
        "ip_address": row.get("ip_address") or "",
    }


def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    return _query_one("SELECT * FROM app_users WHERE lower(email) = lower(?)", (email.strip(),))


def get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    return _query_one("SELECT * FROM app_users WHERE id = ?", (str(user_id),))


def register_user(
    email: str,
    password: str,
    name: str = "",
    registration_type: str = "researcher",
    team_name: str = "",
) -> dict[str, Any]:
    email = email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise ValueError("enter a valid email address")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if registration_type not in ("researcher", "team_leader"):
        registration_type = "researcher"
    if get_user_by_email(email):
        # SECURITY: don't reveal whether the email exists (prevents user enumeration).
        raise ValueError("registration submitted — if this email is new, an account will be created")
    uid = str(uuid.uuid4())
    now = _dt(_now())
    # RBAC bootstrap: the very first account becomes the admin.
    existing = _query_one("SELECT COUNT(*) AS n FROM app_users")
    role = "admin" if not existing or not existing.get("n") else "analyst"
    try:
        _execute(
            """INSERT INTO app_users
               (id, email, name, password_hash, role, is_active, created_at, updated_at, registration_type)
               VALUES (?,?,?,?,?,1,?,?,?)""",
            (uid, email, name.strip(), _password_hash(password), role, now, now, registration_type),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("registration submitted — if this email is new, an account will be created") from exc
    row = get_user_by_id(uid)
    if not row:
        raise ValueError("could not create account")
    # Multi-tenancy: attach the new user to an org.
    # - First user (site admin) → default org, org_admin
    # - Team leader → create a dedicated org, user is org_admin of that org
    # - Researcher → default org, analyst
    try:
        import tenancy as _tenancy
        if _tenancy.MULTI_TENANT:
            if registration_type == "team_leader" and team_name.strip():
                org = _tenancy.create_org(team_name.strip())
                _tenancy.assign_user_to_org(uid, org["id"], "org_admin")
            else:
                org_id = _tenancy.get_or_create_default_org()
                org_role = "org_admin" if role == "admin" else "analyst"
                _tenancy.assign_user_to_org(uid, org_id, org_role)
            row = get_user_by_id(uid) or row
    except Exception:
        pass  # tenancy is best-effort on registration; never block signup
    return row


def create_team_member(
    leader_user: dict[str, Any],
    email: str,
    name: str,
    temp_password: str = "",
) -> dict[str, Any]:
    """Create a new team member account under the leader's org.

    The leader must be a team_leader (or admin). The new member gets
    must_change_password=1 so they are forced to set their own password
    on first login.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        raise ValueError("enter a valid email address")
    if not name.strip():
        raise ValueError("name is required")
    if not temp_password:
        temp_password = secrets.token_urlsafe(12)
    if len(temp_password) < 8:
        raise ValueError("temporary password must be at least 8 characters")
    if get_user_by_email(email):
        raise ValueError("a user with this email already exists")
    leader_org_id = str(leader_user.get("org_id") or "")
    if not leader_org_id:
        raise ValueError("team leader has no organization")
    uid = str(uuid.uuid4())
    now = _dt(_now())
    _execute(
        """INSERT INTO app_users
           (id, email, name, password_hash, role, is_active, created_at, updated_at,
            registration_type, must_change_password, org_id, org_role)
           VALUES (?,?,?,?,?,1,?,?,?,?,?,?)""",
        (uid, email, name.strip(), _password_hash(temp_password), "analyst",
         now, now, "researcher", 1, leader_org_id, "analyst"),
    )
    row = get_user_by_id(uid)
    if not row:
        raise ValueError("could not create team member account")
    return {**public_user(row), "temp_password": temp_password}


def authenticate(email: str, password: str) -> Optional[dict[str, Any]]:
    row = get_user_by_email(email)
    if not row or not row.get("is_active"):
        return None
    if not _verify_password(password, row["password_hash"]):
        return None
    now = _dt(_now())
    _execute("UPDATE app_users SET last_login_at=?, updated_at=? WHERE id=?", (now, now, row["id"]))
    return get_user_by_id(row["id"])


VALID_ROLES = ("admin", "analyst", "viewer")


def list_users() -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM app_users ORDER BY created_at ASC").fetchall()
    return [{**public_user(dict(r)), "is_active": bool(dict(r).get("is_active", 1))} for r in rows]


def set_user_role(user_id: str, role: str, acting_admin_id: str) -> dict[str, Any]:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}")
    row = get_user_by_id(user_id)
    if not row:
        raise ValueError("user not found")
    if str(user_id) == str(acting_admin_id) and role != "admin":
        raise ValueError("admins cannot demote themselves")
    _execute("UPDATE app_users SET role=?, updated_at=? WHERE id=?", (role, _dt(_now()), str(user_id)))
    return public_user(get_user_by_id(user_id) or row)


def set_user_active(user_id: str, is_active: bool, acting_admin_id: str) -> dict[str, Any]:
    row = get_user_by_id(user_id)
    if not row:
        raise ValueError("user not found")
    if str(user_id) == str(acting_admin_id) and not is_active:
        raise ValueError("admins cannot deactivate themselves")
    _execute("UPDATE app_users SET is_active=?, updated_at=? WHERE id=?",
             (1 if is_active else 0, _dt(_now()), str(user_id)))
    if not is_active:
        revoke_user_sessions(str(user_id), reason="account_deactivated")
    return public_user(get_user_by_id(user_id) or row)


def update_user_profile(user_id: str, name: str) -> dict[str, Any]:
    now = _dt(_now())
    _execute("UPDATE app_users SET name=?, updated_at=? WHERE id=?", (name.strip(), now, user_id))
    row = get_user_by_id(user_id)
    if not row:
        raise ValueError("account no longer exists")
    return row


def change_password(user_id: str, current_password: str, new_password: str) -> dict[str, Any]:
    if len(new_password) < 8:
        raise ValueError("password must be at least 8 characters")
    row = get_user_by_id(user_id)
    if not row or not _verify_password(current_password, row["password_hash"]):
        raise ValueError("current password is incorrect")
    now = _dt(_now())
    _execute(
        "UPDATE app_users SET password_hash=?, must_change_password=0, updated_at=? WHERE id=?",
        (_password_hash(new_password), now, user_id),
    )
    revoke_user_sessions(user_id, reason="password_changed")
    refreshed = get_user_by_id(user_id)
    if not refreshed:
        raise ValueError("account no longer exists")
    return refreshed


# ---------------------------------------------------------------------------
# Stateful sessions
# ---------------------------------------------------------------------------
def create_session(user: dict[str, Any], user_agent: str = "", ip_address: str = "") -> dict[str, Any]:
    now = _now()
    sid = str(uuid.uuid4())
    access_jti = str(uuid.uuid4())
    refresh_token = secrets.token_urlsafe(48)
    access_expires = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    refresh_expires = now + timedelta(days=REFRESH_TOKEN_TTL_DAYS)
    public = public_user(user)
    access_token = create_access_token(public, sid, access_jti)
    _execute(
        """INSERT INTO auth_sessions
           (id, user_id, access_jti, refresh_token_hash, user_agent, ip_address, created_at, updated_at,
            last_seen_at, access_expires_at, refresh_expires_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            sid, user["id"], access_jti, _token_hash(refresh_token), user_agent[:500], ip_address[:80],
            _dt(now), _dt(now), _dt(now), _dt(access_expires), _dt(refresh_expires),
        ),
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_at": _dt(access_expires),
        "refresh_expires_at": _dt(refresh_expires),
        "session": public_session(get_session(sid) or {}),
        "user": public,
    }


def get_session(session_id: str) -> Optional[dict[str, Any]]:
    return _query_one("SELECT * FROM auth_sessions WHERE id=?", (session_id,))


def _active_session_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sid = str(payload.get("sid") or "")
    jti = str(payload.get("jti") or "")
    if not sid or not jti:
        raise ValueError("token is not tied to a server session")
    session = get_session(sid)
    if not session or session.get("access_jti") != jti:
        raise ValueError("session token was revoked")
    if session.get("revoked_at"):
        raise ValueError("session was revoked")
    if (_parse_dt(session.get("access_expires_at")) or _now()) < _now():
        raise ValueError("token expired")
    return session


def refresh_session(refresh_token: str, user_agent: str = "", ip_address: str = "") -> dict[str, Any]:
    hashed = _token_hash(refresh_token.strip())
    session = _query_one("SELECT * FROM auth_sessions WHERE refresh_token_hash=?", (hashed,))
    now = _now()
    if not session or session.get("revoked_at"):
        raise ValueError("refresh token is invalid")
    if (_parse_dt(session.get("refresh_expires_at")) or now) < now:
        revoke_session(session["id"], "refresh_expired")
        raise ValueError("refresh token is expired")
    user = get_user_by_id(session["user_id"])
    if not user or not user.get("is_active"):
        revoke_session(session["id"], "user_inactive")
        raise ValueError("user is inactive")
    access_jti = str(uuid.uuid4())
    refresh_token_next = secrets.token_urlsafe(48)
    access_expires = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    refresh_expires = now + timedelta(days=REFRESH_TOKEN_TTL_DAYS)
    public = public_user(user)
    access_token = create_access_token(public, session["id"], access_jti)
    _execute(
        """UPDATE auth_sessions
           SET access_jti=?, refresh_token_hash=?, user_agent=?, ip_address=?, updated_at=?, last_seen_at=?,
               access_expires_at=?, refresh_expires_at=?
           WHERE id=?""",
        (
            access_jti, _token_hash(refresh_token_next), (user_agent or session.get("user_agent") or "")[:500],
            (ip_address or session.get("ip_address") or "")[:80], _dt(now), _dt(now),
            _dt(access_expires), _dt(refresh_expires), session["id"],
        ),
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token_next,
        "token_type": "bearer",
        "expires_at": _dt(access_expires),
        "refresh_expires_at": _dt(refresh_expires),
        "session": public_session(get_session(session["id"]) or {}),
        "user": public,
    }


def touch_session(session_id: str) -> None:
    now = _dt(_now())
    _execute("UPDATE auth_sessions SET last_seen_at=?, updated_at=? WHERE id=? AND revoked_at IS NULL", (now, now, session_id))


def revoke_session(session_id: str, reason: str = "logout") -> None:
    now = _dt(_now())
    _execute(
        "UPDATE auth_sessions SET revoked_at=COALESCE(revoked_at, ?), revoked_reason=COALESCE(revoked_reason, ?) WHERE id=?",
        (now, reason, session_id),
    )


def revoke_refresh_token(refresh_token: str, reason: str = "logout") -> None:
    session = _query_one("SELECT * FROM auth_sessions WHERE refresh_token_hash=?", (_token_hash(refresh_token.strip()),))
    if session:
        revoke_session(session["id"], reason)


def revoke_user_sessions(user_id: str, reason: str = "user_logout_all", except_session_id: str | None = None) -> None:
    now = _dt(_now())
    if except_session_id:
        _execute(
            """UPDATE auth_sessions SET revoked_at=COALESCE(revoked_at, ?), revoked_reason=COALESCE(revoked_reason, ?)
               WHERE user_id=? AND id<>? AND revoked_at IS NULL""",
            (now, reason, user_id, except_session_id),
        )
    else:
        _execute(
            """UPDATE auth_sessions SET revoked_at=COALESCE(revoked_at, ?), revoked_reason=COALESCE(revoked_reason, ?)
               WHERE user_id=? AND revoked_at IS NULL""",
            (now, reason, user_id),
        )


def list_user_sessions(user_id: str) -> list[dict[str, Any]]:
    with _connect() as con:
      rows = con.execute(
          """SELECT * FROM auth_sessions WHERE user_id=? ORDER BY revoked_at IS NULL DESC, last_seen_at DESC""",
          (user_id,),
      ).fetchall()
    return [public_session(dict(row)) for row in rows]


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
def create_password_reset(email: str) -> dict[str, Any]:
    row = get_user_by_email(email)
    if not row:
        # Do not reveal whether the email exists.
        return {"sent": True, "dev_reset_token": None}
    token = secrets.token_urlsafe(32)
    now = _now()
    _execute(
        """INSERT INTO password_reset_tokens (id, user_id, token_hash, expires_at, created_at)
           VALUES (?,?,?,?,?)""",
        (str(uuid.uuid4()), row["id"], _token_hash(token), _dt(now + timedelta(minutes=RESET_TTL_MINUTES)), _dt(now)),
    )
    return {"sent": True, "dev_reset_token": token if DEV_RESET_TOKENS else None}


def reset_password(token: str, password: str) -> dict[str, Any]:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    hashed = _token_hash(token.strip())
    now = _dt(_now())
    reset = _query_one(
        """SELECT * FROM password_reset_tokens
           WHERE token_hash=? AND used_at IS NULL AND expires_at > ?""",
        (hashed, now),
    )
    if not reset:
        raise ValueError("reset token is invalid or expired")
    _execute("UPDATE app_users SET password_hash=?, updated_at=? WHERE id=?",
             (_password_hash(password), now, reset["user_id"]))
    _execute("UPDATE password_reset_tokens SET used_at=? WHERE id=?", (now, reset["id"]))
    revoke_user_sessions(reset["user_id"], reason="password_reset")
    user = get_user_by_id(reset["user_id"])
    if not user:
        raise ValueError("account no longer exists")
    return user


def user_from_bearer(auth_header: str | None) -> dict[str, Any]:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise ValueError("missing bearer token")
    payload = decode_access_token(auth_header.split(" ", 1)[1].strip())
    session = _active_session_from_payload(payload)
    row = get_user_by_id(str(payload["sub"]))
    if not row or not row.get("is_active"):
        raise ValueError("user is inactive")
    touch_session(session["id"])
    return row


def user_and_session_from_bearer(auth_header: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise ValueError("missing bearer token")
    payload = decode_access_token(auth_header.split(" ", 1)[1].strip())
    session = _active_session_from_payload(payload)
    row = get_user_by_id(str(payload["sub"]))
    if not row or not row.get("is_active"):
        raise ValueError("user is inactive")
    touch_session(session["id"])
    return row, session


# ---------------------------------------------------------------------------
# TOTP two-factor authentication
# ---------------------------------------------------------------------------
def _generate_totp_secret() -> str:
    import pyotp
    return pyotp.random_base32()


def _totp_uri(secret: str, email: str) -> str:
    import pyotp
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name="CrypTX")


def _verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.verify(code.strip(), valid_window=1)
    except Exception:
        return False


def setup_totp(user_id: str) -> dict[str, str]:
    """Generate a new TOTP secret for the user (not yet enabled)."""
    secret = _generate_totp_secret()
    row = get_user_by_id(user_id)
    if not row:
        raise ValueError("user not found")
    _execute("UPDATE app_users SET totp_secret=?, updated_at=? WHERE id=?",
             (secret, _dt(_now()), user_id))
    uri = _totp_uri(secret, row["email"])
    # Generate QR code as SVG string
    try:
        import qrcode
        import qrcode.image.svg
        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(uri, image_factory=factory, box_size=10, border=1)
        import io
        buf = io.BytesIO()
        img.save(buf)
        qr_svg = buf.getvalue().decode("utf-8")
    except Exception:
        qr_svg = ""
    return {"secret": secret, "uri": uri, "qr_svg": qr_svg}


def enable_totp(user_id: str, code: str) -> bool:
    """Verify the code and enable 2FA for the user."""
    row = get_user_by_id(user_id)
    if not row:
        raise ValueError("user not found")
    secret = row.get("totp_secret") or ""
    if not secret:
        raise ValueError("call setup first")
    if not _verify_totp(secret, code):
        raise ValueError("invalid code")
    _execute("UPDATE app_users SET totp_enabled=1, updated_at=? WHERE id=?",
             (_dt(_now()), user_id))
    return True


def verify_totp_login(user_id: str, code: str) -> bool:
    """Verify a TOTP code during login."""
    row = get_user_by_id(user_id)
    if not row or not row.get("totp_enabled"):
        return False
    return _verify_totp(row.get("totp_secret") or "", code)


def disable_totp(user_id: str) -> None:
    """Disable 2FA for a user (admin/team-leader action)."""
    _execute("UPDATE app_users SET totp_enabled=0, totp_secret='', updated_at=? WHERE id=?",
             (_dt(_now()), user_id))


def disable_totp_self(user_id: str, code: str) -> bool:
    """User disables their own 2FA — requires a valid TOTP code."""
    row = get_user_by_id(user_id)
    if not row:
        raise ValueError("user not found")
    if not row.get("totp_enabled"):
        return True  # already disabled
    if not _verify_totp(row.get("totp_secret") or "", code):
        raise ValueError("invalid 2FA code")
    _execute("UPDATE app_users SET totp_enabled=0, totp_secret='', updated_at=? WHERE id=?",
             (_dt(_now()), user_id))
    return True


if __name__ == "__main__":
    init_auth_db()
    u = register_user("analyst@example.com", "supersecret1", "Test Analyst")
    print("registered:", public_user(u))
    tok = create_access_token(public_user(u))
    print("token ok:", decode_access_token(tok)["email"])
    print("auth ok:", bool(authenticate("analyst@example.com", "supersecret1")))
    print("bad pw:", authenticate("analyst@example.com", "wrong"))
