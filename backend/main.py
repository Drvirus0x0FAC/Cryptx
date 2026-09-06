"""
CryptoOSINT Investigator — FastAPI backend.
Wraps the bundled Python intelligence modules and exposes them as REST endpoints.
v2.0: Added risk scoring, case management, batch screening, report generation.
"""
from tgbot_runtime import ensure_tgbot_path

# Make bundled/sibling Python modules importable.
_PYTHON_MODULES = ensure_tgbot_path()

import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from routers import address, trace, dex, settings as settings_router
from routers import risk, cases, batch, tx as tx_router, forensics, ai, threat_intel, nexus, tx_investigation, intelligence, identity, evidence, ai_agent, victim_report as victim_report_router, monitor, nft_tron
from routers import sanctions as sanctions_router, regulatory as regulatory_router, demix as demix_router
from routers import public_enrichment as public_enrichment_router
from routers import holistic as holistic_router
from routers import attribution as attribution_router
from routers import autopilot as autopilot_router
from routers import analytics as analytics_router
from routers import auth as auth_router
from routers import case_tasks as case_tasks_router
from routers import notifications as notifications_router
import auth_service
import database

# ── Security: disable Swagger/ReDoc in production ────────────────────────────
_is_prod = os.getenv("ENVIRONMENT", "development").lower() == "production"

app = FastAPI(
    title="CryptoOSINT Investigator API",
    description="Cryptocurrency cybercrime investigation platform — Caudena Prism + Uppsala CARA/CATV/KYT capabilities",
    version="2.0.0",
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

# CORS: dev origins + production origins configurable via CORS_ORIGINS env var
# (comma-separated). If unset, only localhost dev ports are allowed.
_dev_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://localhost:3000",
]
_extra = os.getenv("CORS_ORIGINS", "")
if _extra:
    _dev_origins.extend([o.strip() for o in _extra.split(",") if o.strip()])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_dev_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Requested-With"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
    max_age=600,
)


PUBLIC_PREFIXES = ("/api/auth", "/api/boards/shared/", "/api/portal/")
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


# ── Security headers middleware ────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Remove server identification
    if "server" in response.headers:
        del response.headers["server"]
    return response


# ── Global API rate limiting (per-IP, in-process) ─────────────────────────────
from collections import defaultdict as _dd
import time as _time

_API_RATE: dict[str, list[float]] = _dd(list)
_API_RATE_WINDOW = 60       # 1-minute rolling window
_API_RATE_MAX = 120         # max requests per window per IP


def _check_api_rate_limit(ip: str) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    now = _time.time()
    requests = [t for t in _API_RATE[ip] if now - t < _API_RATE_WINDOW]
    _API_RATE[ip] = requests
    if len(requests) >= _API_RATE_MAX:
        retry_in = int(_API_RATE_WINDOW - (now - requests[0]))
        return False, max(1, retry_in)
    _API_RATE[ip].append(now)
    return True, 0


@app.middleware("http")
async def global_rate_limit(request: Request, call_next):
    # Skip rate limiting for public paths and non-API routes
    path = request.url.path
    if request.method == "OPTIONS" or path in PUBLIC_PATHS or not path.startswith("/api"):
        return await call_next(request)
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)

    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",", 1)[0].strip() or (request.client.host if request.client else "unknown")

    allowed, retry_after = _check_api_rate_limit(ip)
    if not allowed:
        return JSONResponse(
            {"detail": "rate limit exceeded", "retry_after": retry_after},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    response = await call_next(request)
    # Add rate limit info headers
    remaining = max(0, _API_RATE_MAX - len(_API_RATE.get(ip, [])))
    response.headers["X-RateLimit-Limit"] = str(_API_RATE_MAX)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


@app.middleware("http")
async def require_authenticated_user(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)
    if path.startswith("/api"):
        # Auth: prefer bearer token; fall back to X-API-Key header.
        auth_header = request.headers.get("authorization")
        api_key_header = request.headers.get("x-api-key")
        try:
            if auth_header and auth_header.lower().startswith("bearer "):
                request.state.user = auth_service.user_from_bearer(auth_header)
            elif api_key_header:
                # API-key auth path. Resolve the key, rate-limit, meter.
                import api_key_service
                key_rec = api_key_service.lookup_by_plaintext(api_key_header.strip())
                if not key_rec:
                    return JSONResponse({"detail": "invalid or inactive API key"}, status_code=401)
                allowed, retry_after, rl_headers = api_key_service.check_rate_limit(key_rec)
                if not allowed:
                    return JSONResponse(
                        {"detail": "rate limit exceeded", "retry_after": retry_after},
                        status_code=429,
                        headers=rl_headers,
                    )
                request.state.user = api_key_service.resolve_user_from_key(key_rec)
                request.state._api_key_id = key_rec["id"]
            else:
                return JSONResponse({"detail": "missing bearer token or X-API-Key"}, status_code=401)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=401)
        # RBAC: 'viewer' accounts are read-only across the whole API.
        user = getattr(request.state, "user", None) or {}
        if user.get("role") == "viewer" and request.method not in ("GET", "HEAD"):
            return JSONResponse(
                {"detail": "Your role (viewer) is read-only. Ask an admin for analyst access."},
                status_code=403,
            )
        # Force password change: users with must_change_password=1 (e.g. team
        # members created with a temporary password) must rotate their password
        # before accessing any other API. Auth endpoints are already excluded
        # via PUBLIC_PREFIXES so /auth/change-password and /auth/me still work.
        if user.get("must_change_password") and path not in ("/api/auth/me",):
            return JSONResponse(
                {"detail": "You must change your password before continuing.", "must_change_password": True},
                status_code=403,
            )
        response = await call_next(request)
        # Meter API-key usage after the request completes (best-effort).
        api_key_id = getattr(request.state, "_api_key_id", None)
        if api_key_id:
            try:
                import api_key_service
                api_key_service.record_usage(api_key_id, error=response.status_code >= 400)
            except Exception:
                pass
            # Surface rate-limit headers on successful API-key responses too.
            if "X-RateLimit-Limit" not in response.headers:
                response.headers["X-RateLimit-Limit"] = "60"
        return response
    return await call_next(request)


@app.get("/health", tags=["Health"])
async def health():
    """Liveness probe used by the frontend to show Online/Offline status."""
    return {"status": "ok"}


# Core intelligence routers
app.include_router(auth_router.router, prefix="/api", tags=["Authentication"])
app.include_router(address.router, prefix="/api", tags=["Address Intel"])
app.include_router(trace.router, prefix="/api", tags=["Fund Tracer"])
app.include_router(dex.router, prefix="/api", tags=["DEX Analysis"])
app.include_router(settings_router.router, prefix="/api", tags=["Settings"])

# Enhanced investigation routers (v2)
app.include_router(risk.router, prefix="/api", tags=["Risk Scoring"])
app.include_router(cases.router, prefix="/api", tags=["Case Management"])
app.include_router(case_tasks_router.router, prefix="/api", tags=["Case Tasks"])
app.include_router(notifications_router.router, prefix="/api", tags=["Notifications"])
app.include_router(batch.router, prefix="/api", tags=["Batch Screening"])
app.include_router(tx_router.router, prefix="/api", tags=["Transaction Detail"])
app.include_router(forensics.router, prefix="/api", tags=["Forensic Analysis"])
app.include_router(ai.router, prefix="/api", tags=["AI Copilot"])
app.include_router(threat_intel.router, prefix="/api", tags=["Threat Intelligence"])
app.include_router(nexus.router, prefix="/api", tags=["Nexus Graph"])
app.include_router(tx_investigation.router, prefix="/api", tags=["TX Lens"])
app.include_router(intelligence.router, prefix="/api", tags=["Intelligence"])
app.include_router(identity.router, prefix="/api", tags=["Identity Lens"])
app.include_router(evidence.router, prefix="/api", tags=["Evidence Vault"])
app.include_router(ai_agent.router, prefix="/api", tags=["AI Agent"])
app.include_router(victim_report_router.router, prefix="/api", tags=["Victim Reports"])
app.include_router(monitor.router, prefix="/api", tags=["Wallet Monitor"])
app.include_router(nft_tron.router, prefix="/api", tags=["NFT/TRON Sentinel"])

# Compliance & advanced analysis routers (v3)
app.include_router(sanctions_router.router, prefix="/api", tags=["Sanctions"])
app.include_router(regulatory_router.router, prefix="/api", tags=["Regulatory & KYV"])
app.include_router(demix_router.router, prefix="/api", tags=["Demixing"])
app.include_router(holistic_router.router, prefix="/api", tags=["Holistic Trace"])
app.include_router(attribution_router.router, prefix="/api", tags=["Attribution"])
app.include_router(autopilot_router.router, prefix="/api", tags=["Auto Investigation"])
app.include_router(analytics_router.router, prefix="/api", tags=["Analytics"])
app.include_router(public_enrichment_router.router, prefix="/api", tags=["Public Enrichment"])

# Boards / prices / OSINT sweep (Tracker-parity feature set)
from routers import boards as boards_router
from routers import prices as prices_router
from routers import osint_sweep as osint_sweep_router
from routers import threat_feed as threat_feed_router
from routers import ransomware as ransomware_router
from routers import reports as reports_router
app.include_router(boards_router.router, prefix="/api", tags=["Boards"])
app.include_router(prices_router.router, prefix="/api", tags=["Prices"])
app.include_router(osint_sweep_router.router, prefix="/api", tags=["OSINT Sweep"])
app.include_router(threat_feed_router.router, prefix="/api", tags=["Blockchain Threat Landscape"])
app.include_router(ransomware_router.router, prefix="/api", tags=["Ransomware Intelligence"])
app.include_router(reports_router.router, prefix="/api", tags=["Reports"])  # live data only

# V2 feature routers — graph store, exports, feed sync, ingestion, DeFi trackers,
# entity investigation, time-travel, deep chain fetchers, case QA, custody audit,
# collaboration, victim portal.
from routers import v2_features
app.include_router(v2_features.router, prefix="/api", tags=["V2 Features"])

# 2026 enhancement domains (additive) — smart-contract forensics, modern
# laundering/tracing, court-readiness/Daubert, and recovery last-mile.
from routers import contract_forensics as contract_forensics_router
from routers import laundering as laundering_router
from routers import daubert as daubert_router
from routers import recovery as recovery_router
app.include_router(contract_forensics_router.router, prefix="/api", tags=["Contract Forensics"])
app.include_router(laundering_router.router, prefix="/api", tags=["Laundering Trace"])
app.include_router(daubert_router.router, prefix="/api", tags=["Court Readiness"])
app.include_router(recovery_router.router, prefix="/api", tags=["Recovery Ops"])
from routers import agent as agent_router
app.include_router(agent_router.router, prefix="/api", tags=["AI Investigator"])

# Next-Horizon 2026-07 domains (additive) — stablecoin compliance suite,
# freeze-network operationalization, scam-infrastructure forensics, perp-DEX intel.
from routers import comply as comply_router
from routers import freeze_net as freeze_net_router
from routers import scam_infra as scam_infra_router
from routers import perp_dex as perp_dex_router
app.include_router(comply_router.router, prefix="/api", tags=["Stablecoin Compliance"])
app.include_router(freeze_net_router.router, prefix="/api", tags=["Freeze Network"])
app.include_router(scam_infra_router.router, prefix="/api", tags=["Scam Network Atlas"])
app.include_router(perp_dex_router.router, prefix="/api", tags=["Perp DEX Intel"])

# Predictive Intelligence + shared Investigator Insight layer (2026-07-25)
from routers import predictive as predictive_router
app.include_router(predictive_router.router, prefix="/api", tags=["Predictive Intelligence"])

# Organizations (multi-tenancy management — Phase 0 commercial launch)
from routers import orgs as orgs_router
app.include_router(orgs_router.router, prefix="/api", tags=["Organizations"])

# Entity search + VASP dossiers (Phase 1 demo-superiority features)
from routers import entity_search as entity_search_router
app.include_router(entity_search_router.router, prefix="/api", tags=["Entity Search"])

# No-code alert rules (composite conditions + templates + dry-run — Phase 1)
from routers import rules as rules_router
app.include_router(rules_router.router, prefix="/api", tags=["Alert Rules"])

# NL-driven multi-step investigation agent (Phase 1 — trace/cash-out/SAR/freeze by prompt)
from routers import nl_agent as nl_agent_router
app.include_router(nl_agent_router.router, prefix="/api", tags=["NL Agent"])

# Memecoin insider-network forensics (Phase 2 — pump.fun/sniper/bundler detection)
from routers import memecoin as memecoin_router
app.include_router(memecoin_router.router, prefix="/api", tags=["Memecoin Forensics"])

# Label-growth loop (Phase 2 — auto-feed victim reports + bulk label import)
from routers import label_growth as label_growth_router
app.include_router(label_growth_router.router, prefix="/api", tags=["Label Growth"])

# Detector benchmark harness (Phase 2 — Daubert error-rate measurement)
from routers import benchmark as benchmark_router
app.include_router(benchmark_router.router, prefix="/api", tags=["Benchmark"])

# API key management (per-org keys + usage metering — Phase 0 commercial launch)
from routers import api_keys as api_keys_router
app.include_router(api_keys_router.router, prefix="/api", tags=["API Keys"])

# SSO / OIDC enterprise login (Phase 0 commercial launch). Mounted under
# /api/auth/sso which is already covered by the PUBLIC_PREFIXES bypass.
from routers import sso as sso_router
app.include_router(sso_router.router, prefix="/api", tags=["SSO"])


@app.on_event("startup")
async def startup():
    # Load managed .env keys (Etherscan, AI providers, …) into the process
    # environment so live features actually pick them up. settings.py writes
    # the .env but nothing loaded it at boot — that is why a configured
    # ETHERSCAN_API_KEY was ignored and traces hit the free-tier rate limit.
    try:
        from routers import settings as _settings_router
        _loaded = []
        for _k, _v in _settings_router._read_env().items():
            if _v and not os.environ.get(_k):
                os.environ[_k] = _v
                _loaded.append(_k)
        print(f"[startup] loaded {len(_loaded)} key(s) from .env: {', '.join(sorted(_loaded)) or 'none'}")
        print(f"[startup] ETHERSCAN_API_KEY active: {bool(os.environ.get('ETHERSCAN_API_KEY'))}")
    except Exception as _e:
        print(f"[startup] env load failed: {_e}")
    auth_service.init_auth_db()
    database.init_db()
    import evidence_vault
    evidence_vault.init_evidence_tables()
    import victim_report
    victim_report.init_victim_tables()
    import sanctions_engine
    sanctions_engine.init_sanctions_tables()
    import vasp_directory
    vasp_directory.init_vasp_tables()
    import attribution_engine
    attribution_engine.init_attribution_tables()
    import public_enrichment_engine
    public_enrichment_engine.init_public_enrichment_tables()
    import boards_engine
    boards_engine.init_boards_tables()
    import price_service
    price_service.init_price_tables()
    import attribution_workflow
    attribution_workflow.init_submission_tables()
    import osint_sweep_engine
    osint_sweep_engine.init_osint_tables()
    # V2 feature engine tables
    import graph_store
    graph_store.init_graph_store_tables()
    import http_cache
    http_cache.init_http_cache_tables()
    import alert_delivery
    alert_delivery.init_delivery_tables()
    import feed_ingestion
    feed_ingestion.init_ingestion_tables()
    import feed_sync
    feed_sync.init_feed_sync_tables()
    # Next-Horizon 2026-07 engine tables
    import stablecoin_compliance
    stablecoin_compliance.init_tables()
    import freeze_network
    freeze_network.init_tables()
    import scam_infrastructure
    scam_infrastructure.init_tables()
    # API key tables (per-org keys + usage metering).
    import api_key_service
    api_key_service.init_api_key_tables()
    # SSO identity-link table.
    import sso_service
    sso_service.init_sso_tables()
    # Multi-tenancy: create the organizations table + add org_id to app_users and
    # every tenant-owned table that the engine inits above just created. This MUST
    # run after all init_*_tables() so every table exists. Legacy rows (org_id='')
    # are then attached to a default org so existing single-user deployments keep
    # working without data loss.
    try:
        import tenancy
        tenancy.init_tenancy_tables()
        added = tenancy.ensure_tenant_columns()
        if added:
            print(f"[startup] tenancy: added org_id to {len(added)} table(s): {', '.join(sorted(added))}")
        attached = tenancy.attach_legacy_rows_to_default_org()
        if attached:
            print(f"[startup] tenancy: attached {attached} legacy row(s) to the default org")
    except Exception as _e:
        print(f"[startup] tenancy init failed: {_e}")
    # Warm ransomware intelligence cache in background
    try:
        import ransomware_engine
        ransomware_engine.start_warm_cache()
        print("[startup] ransomware engine cache warming started")
    except Exception as _e:
        print(f"[startup] ransomware engine warm failed: {_e}")
    # Warm threat feed cache in background
    try:
        import threat_feed_engine
        threat_feed_engine.start_warm_cache()
        print("[startup] threat feed cache warming started")
    except Exception as _e:
        print(f"[startup] threat feed warm failed: {_e}")
    # Download open OSINT datasets (ransomware / sanctions) in the background so
    # investigations 