"""
Centralized configuration for CrypTX.

Single source of truth for paths, secrets, and feature flags. Every engine and
router should read runtime configuration from here instead of hardcoding paths
or env lookups — this keeps the app overridable for Docker volumes,
air-gapped deployments, and future Postgres support.

Design rules:
  * Pure stdlib only (no pydantic, no heavy deps) so it imports from anywhere.
  * Every value has a sensible default so a `python -c "import main"` just works.
  * Env vars are read once at import time and frozen into module-level constants.
"""
from __future__ import annotations

import os
import secrets
import warnings
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

#: Backend directory (where this file lives, e.g. .../CryptoOSINT-Production/backend)
BACKEND_DIR: Path = Path(__file__).resolve().parent

#: Project root (parent of backend/)
PROJECT_ROOT: Path = BACKEND_DIR.parent

#: SQLite database path. Overridable via DB_PATH env for Docker volumes and
#: multi-instance deploys. Defaults to backend/cryptoosint.db (legacy location).
#:
#: When a relative path is given, it is resolved against the backend dir so the
#: app behaves identically regardless of the current working directory.
_db_path_env = os.getenv("DB_PATH", "").strip()
if _db_path_env:
    _DB_PATH = Path(_db_path_env)
    DB_PATH: Path = _DB_PATH if _DB_PATH.is_absolute() else (BACKEND_DIR / _DB_PATH)
else:
    DB_PATH = BACKEND_DIR / "cryptoosint.db"

#: Sibling python-modules directory (the bundled OSINT modules added to sys.path
#: at runtime by tgbot_runtime). Exposed here so other code can locate it without
#: re-deriving the lookup logic.
def _resolve_python_modules() -> Path:
    candidates = [
        PROJECT_ROOT / "python-modules",
        PROJECT_ROOT.parent / "python-modules",
        PROJECT_ROOT / "TGBot",
        PROJECT_ROOT.parent / "TGBot",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


PYTHON_MODULES_DIR: Path = _resolve_python_modules()

# ── Auth secret ──────────────────────────────────────────────────────────────
# SECURITY: never fall back to a hard-coded secret. If AUTH_SECRET/SECRET_KEY is
# unset, generate a persistent random secret and store it in a file next to the
# DB so tokens survive restarts but are never committed to source. Emit a loud
# warning so operators know to set a proper secret in production.
#
# Resolved here (centralized) so every module reads the same secret. auth_service
# re-exports AUTH_SECRET from here for backward compatibility.
_env_secret = os.getenv("AUTH_SECRET") or os.getenv("SECRET_KEY")
if _env_secret:
    AUTH_SECRET: str = _env_secret
else:
    _secret_file = DB_PATH.parent / ".auth_secret"
    if _secret_file.exists():
        AUTH_SECRET = _secret_file.read_text(encoding="utf-8").strip()
    else:
        AUTH_SECRET = secrets.token_urlsafe(48)
        try:
            _secret_file.write_text(AUTH_SECRET, encoding="utf-8")
            # best-effort restrict permissions (POSIX only; Windows uses ACLs)
            try:
                os.chmod(_secret_file, 0o600)
            except OSError:
                pass
        except OSError:
            pass  # read-only filesystem — in-memory secret will rotate on restart
        warnings.warn(
            "AUTH_SECRET/SECRET_KEY not set. Generated a random secret at "
            f"{_secret_file}. Set AUTH_SECRET in your environment for production "
            "so tokens persist across deployments.",
            stacklevel=2,
        )

# ── Auth token TTLs ──────────────────────────────────────────────────────────

TOKEN_TTL_MINUTES: int = int(os.getenv("AUTH_TOKEN_TTL_MINUTES", "720"))
ACCESS_TOKEN_TTL_MINUTES: int = int(os.getenv("AUTH_ACCESS_TOKEN_TTL_MINUTES", "15"))
REFRESH_TOKEN_TTL_DAYS: int = int(os.getenv("AUTH_REFRESH_TOKEN_TTL_DAYS", "7"))
RESET_TTL_MINUTES: int = int(os.getenv("AUTH_RESET_TTL_MINUTES", "30"))
# SECURITY: dev reset-token disclosure defaults OFF. Operators who want dev
# convenience must explicitly opt in via AUTH_DEV_RESET_TOKENS=1.
DEV_RESET_TOKENS: bool = os.getenv("AUTH_DEV_RESET_TOKENS", "0").lower() in {"1", "true", "yes"}

# ── Feature flags ────────────────────────────────────────────────────────────

#: Multi-tenancy master switch. When True, the org_id scoping layer is active.
#: Defaults True for commercial deployments; set MULTI_TENANT=0 to disable for
#: legacy single-user / air-gapped installs that don't want the org concept.
MULTI_TENANT: bool = os.getenv("MULTI_TENANT", "1").lower() in {"1", "true", "yes"}

#: Optional pre-seeded default org id. When set, existing rows without an org_id
#: and JIT-provisioned users are attached to this org. If unset, the tenancy
#: layer creates a default org on first user registration.
DEFAULT_ORG_ID: str = os.getenv("DEFAULT_ORG_ID", "").strip()

#: RFC-3161 Trusted Timestamp Authority URL. When set, daubert notarizations and
#: evidence-vault exports are timestamped by this TSA (tamper-evident, externally
#: datable — a court-admissibility asset). Leave empty to keep the local
#: hash-chain-only behavior. For air-gapped deployments, point this at a
#: self-hosted TSA on the local network.
TSA_URL: str = os.getenv("TSA_URL", "").strip()

#: Deployment URL used to build absolute callback URLs (SSO, email links).
#: Falls back to http://localhost:8000 for local dev.
BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

#: Deployment environment label (surfaced in /health for ops dashboards).
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

# ── Local node / air-gap RPC ────────────────────────────────────────────────
#: When set, EVM fetchers prefer a local node over public block explorers.
#: This makes the "air-gapped / self-hosted" deployment claim TRUE: an agency
#: that cannot ship data to Etherscan/Blockscout can run their own node and
#: CrypTX traces through it. Format: a JSON map of chain→URL, e.g.
#:   LOCAL_RPC_URLS='{"eth":"http://localhost:8545","base":"http://localhost:8547"}'
#: Or a single URL for all EVM chains: LOCAL_RPC_URLS='http://localhost:8545'
#: Leave empty to use public explorers (default behavior).
_local_rpcs_raw = os.getenv("LOCAL_RPC_URLS", "").strip()
ETH_RPC_URL: str = os.getenv("ETH_RPC_URL", "").strip()  # legacy single-chain shortcut
try:
    import json as _json
    if _local_rpcs_raw.startswith("{"):
        LOCAL_RPC_URLS: dict[str, str] = _json.loads(_local_rpcs_raw)
    elif _local_rpcs_raw:
        LOCAL_RPC_URLS = {"eth": _local_rpcs_raw}  # single URL → eth only
    else:
        LOCAL_RPC_URLS = {}
    if ETH_RPC_URL and "eth" not in LOCAL_RPC_URLS:
        LOCAL_RPC_URLS["eth"] = ETH_RPC_URL
except Exception:
    LOCAL_RPC_URLS = {}

#: Whether local-RPC mode is active for ANY chain.
LOCAL_RPC_ENABLED: bool = bool(LOCAL_RPC_URLS)
