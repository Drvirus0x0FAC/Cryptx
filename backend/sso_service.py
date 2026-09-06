"""
OIDC Single Sign-On for CrypTX.

Enables enterprise login via Google, Microsoft Entra, Okta, Keycloak, or any
OIDC-compliant IdP. Password login stays fully functional alongside SSO.

Flow:
  1. GET /api/auth/sso/oidc/{provider}/login  → redirect to IdP authorization.
  2. IdP redirects to GET /api/auth/sso/oidc/{provider}/callback?code=...
  3. We exchange the code for tokens, fetch userinfo, then:
     a. Match by (provider, subject) → existing link → issue CrypTX JWT.
     b. Match by email → existing user → link identity → issue JWT.
     c. No match → JIT-provision (if OIDC_JIT_PROVISION=auto) into
        OIDC_DEFAULT_ORG_ID (or the default org), role analyst.

Provider config is env-driven:
  OIDC_{PROVIDER}_CLIENT_ID, OIDC_{PROVIDER}_CLIENT_SECRET,
  OIDC_{PROVIDER}_DISCOVERY_URL (or ISSUER), OIDC_{PROVIDER}_SCOPES (default
  "openid email profile").

authlib is imported lazily inside the functions that need it so this module
loads (and the app runs) even when SSO is unconfigured or authlib absent.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH

JIT_PROVISION = os.getenv("OIDC_JIT_PROVISION", "auto").lower() in {"auto", "1", "true", "yes"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_sso_tables() -> None:
    """Create the user_identities link table. Idempotent."""
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS user_identities (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                org_id       TEXT NOT NULL DEFAULT '',
                provider     TEXT NOT NULL,
                subject      TEXT NOT NULL,
                email_at_link TEXT DEFAULT '',
                linked_at    TEXT NOT NULL,
                UNIQUE (provider, subject)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_user_identities_lookup ON user_identities(provider, subject)")
        con.commit()


# ── Provider config ─────────────────────────────────────────────────────────

def list_configured_providers() -> list[str]:
    """Return the list of provider names that have client_id + secret configured."""
    providers = set()
    for key in os.environ:
        if key.startswith("OIDC_") and key.endswith("_CLIENT_ID"):
            name = key[len("OIDC_"):-len("_CLIENT_ID")].lower()
            if os.environ.get(f"OIDC_{name.upper()}_CLIENT_SECRET"):
                providers.add(name)
    return sorted(providers)


def get_provider_config(provider: str) -> Optional[dict]:
    """Return the config for a provider, or None if not configured."""
    p = provider.upper()
    client_id = os.getenv(f"OIDC_{p}_CLIENT_ID", "").strip()
    client_secret = os.getenv(f"OIDC_{p}_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    discovery_url = (
        os.getenv(f"OIDC_{p}_DISCOVERY_URL", "").strip()
        or os.getenv(f"OIDC_{p}_ISSUER", "").strip()
    )
    scopes = os.getenv(f"OIDC_{p}_SCOPES", "openid email profile").strip()
    return {
        "provider": provider.lower(),
        "client_id": client_id,
        "client_secret": client_secret,
        "discovery_url": discovery_url,
        "scopes": scopes.split(),
    }


# ── OAuth client construction ───────────────────────────────────────────────

def _build_oauth_client(cfg: dict):
    """Build an authlib OIDC client from discovery. Raises if authlib missing."""
    from authlib.integrations.httpx_client import AsyncOAuth2Client  # type: ignore
    return AsyncOAuth2Client(
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        scope=" ".join(cfg["scopes"]),
    )


def get_authorization_url(provider: str, redirect_uri: str, state: str) -> Optional[str]:
    """Build the IdP authorization URL to redirect the user to."""
    cfg = get_provider_config(provider)
    if not cfg or not cfg["discovery_url"]:
        return None
    try:
        from authlib.oauth2.rfc6749 import OAuth2Request  # type: ignore
        from authlib.integrations.httpx_client import AsyncOAuth2Client  # type: ignore
    except ImportError:
        return None

    # Discover the authorization endpoint from the IdP's well-known config.
    import httpx
    well_known = cfg["discovery_url"].rstrip("/") + "/.well-known/openid-configuration"
    try:
        resp = httpx.get(well_known, timeout=10)
        meta = resp.json()
        auth_endpoint = meta["authorization_endpoint"]
    except Exception:
        return None

    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": " ".join(cfg["scopes"]),
        "state": state,
    }
    return f"{auth_endpoint}?{urlencode(params)}"


async def exchange_code_for_userinfo(
    provider: str, code: str, redirect_uri: str
) -> Optional[dict]:
    """Exchange the authorization code for tokens + userinfo. Returns the IdP's
    userinfo dict (sub, email, name, ...) or None on failure."""
    cfg = get_provider_config(provider)
    if not cfg:
        return None
    try:
        from authlib.integrations.httpx_client import AsyncOAuth2Client  # type: ignore
    except ImportError:
        return None

    import httpx
    well_known = cfg["discovery_url"].rstrip("/") + "/.well-known/openid-configuration"
    try:
        meta = httpx.get(well_known, timeout=10).json()
        token_endpoint = meta["token_endpoint"]
        userinfo_endpoint = meta["userinfo_endpoint"]
    except Exception:
        return None

    async with AsyncOAuth2Client(
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        scope=" ".join(cfg["scopes"]),
        redirect_uri=redirect_uri,
        token_endpoint=token_endpoint,
    ) as client:
        try:
            token = await client.fetch_token(token_endpoint, authorization_response=f"?code={code}", code=code)
        except Exception:
            return None
        try:
            userinfo_resp = await client.get(userinfo_endpoint)
            return userinfo_resp.json()
        except Exception:
            return None


# ── Identity matching + JIT provisioning ────────────────────────────────────

def match_or_provision(provider: str, subject: str, email: str, name: str = "") -> Optional[dict]:
    """Resolve an IdP userinfo to a CrypTX user. Returns the user row or None.

    1. Match by (provider, subject) → existing link.
    2. Match by email → link the identity to that user.
    3. No match → JIT-provision a new user (if enabled).
    """
    import auth_service
    import tenancy

    # 1. Existing link?
    with _connect() as con:
        row = con.execute(
            "SELECT user_id FROM user_identities WHERE provider=? AND subject=?",
            (provider, subject),
        ).fetchone()
    if row:
        return auth_service.get_user_by_id(row["user_id"])

    # 2. Match by email?
    if email:
        existing = auth_service.get_user_by_email(email)
        if existing:
            _link_identity(existing["id"], existing.get("org_id") or "", provider, subject, email)
            return existing

    # 3. JIT provision?
    if not JIT_PROVISION:
        return None
    if not email:
        return None  # can't provision without an email

    # Generate a random password (SSO users don't use password login, but the
    # column is NOT NULL). The user can set one later via password-reset if needed.
    import secrets as _secrets
    random_pw = _secrets.token_urlsafe(32) + "!1Aa"
    try:
        new_user = auth_service.register_user(email, random_pw, name or email.split("@")[0])
    except ValueError:
        return None

    # Attach to the configured/default org and link the identity.
    org_id = _config.DEFAULT_ORG_ID or tenancy.get_or_create_default_org()
    tenancy.assign_user_to_org(new_user["id"], org_id, "analyst")
    _link_identity(new_user["id"], org_id, provider, subject, email)
    return auth_service.get_user_by_id(new_user["id"])


def _link_identity(user_id: str, org_id: str, provider: str, subject: str, email: str = "") -> None:
    """Record a (provider, subject) → user_id link."""
    with _connect() as con:
        con.execute(
            """INSERT OR IGNORE INTO user_identities (id, user_id, org_id, provider, subject, email_at_link, linked_at)
               VALUES (?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), str(user_id), str(org_id), provider, subject, email, _now_iso()),
        )
        con.commit()


def link_identity_for_current_user(user: dict, provider: str, subject: str, email: str = "") -> dict:
    """Link an additional IdP identity to an already-logged-in user."""
    _link_identity(str(user["id"]), str(user.get("org_id") or ""), provider, subject, email)
    return {"linked": True, "provider": provider}


def list_user_identities(user_id: str) -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT provider, email_at_link, linked_at FROM user_identities WHERE user_id=?",
            (str(user_id),),
        ).fetchall()
    return [dict(r) for r in rows]
