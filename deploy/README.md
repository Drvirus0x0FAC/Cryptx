# CrypTX Deployment Guide

This covers the three supported deployment modes. For a commercial launch, use
**Docker Compose** (mode 2) or **Docker + external reverse proxy** (mode 3).

---

## Mode 1 — Local development (quick start)

Two terminals:

```bash
# Terminal 1 — backend
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev   # http://localhost:5173
```

The Vite dev server proxies `/api` and `/health` to `:8000` (see `vite.config.ts`).
On first run, CrypTX auto-creates the SQLite DB and a default org.

---

## Mode 2 — Docker Compose (recommended for production)

### Prerequisites
- Docker 24+ and Docker Compose v2.

### Steps
1. **Configure secrets:**
   ```bash
   cp .env.example .env
   # Edit .env — at minimum set AUTH_SECRET (generate with:
   #   python -c "import secrets; print(secrets.token_urlsafe(48))")
   ```

2. **Build and start:**
   ```bash
   docker compose up -d --build
   ```
   This starts:
   - `cryptx` — FastAPI backend (4 workers, Playwright/Chromium bundled).
   - `nginx` — serves the frontend + reverse-proxies `/api` to the backend.
   - A `cryptx_data` volume persisting the SQLite DB.

3. **Open the app:** http://localhost

4. **Create your first admin account:** register via the UI — the first account
   becomes the global site admin and is assigned to the default org.

5. **Check health:**
   ```bash
   docker compose ps
   curl http://localhost/health   # → {"status":"ok"}
   ```

### Common operations
```bash
docker compose logs -f cryptx        # tail backend logs
docker compose restart cryptx        # restart after .env change
docker compose down                  # stop (data volume persists)
docker compose down -v               # stop AND delete data ⚠️
docker compose exec cryptx python -m pytest  # run tests in-container
```

### Backups
The SQLite DB lives in the `cryptx_data` volume at `/app/backend/data/cryptoosint.db`.
```bash
docker compose exec cryptx cp /app/backend/data/cryptoosint.db /tmp/backup.db
docker cp cryptx-backend:/tmp/backup.db ./backup-$(date +%F).db
```

---

## Mode 3 — Docker with an external reverse proxy / load balancer

For Kubernetes, ECS, or a custom nginx/Traefik/Caddy setup, build the image and
run the backend container directly, letting your own proxy handle TLS + static:

```bash
docker build -t cryptx .
docker run -d --name cryptx \
  -p 8000:8000 \
  -v cryptx_data:/app/backend/data \
  --env-file .env \
  cryptx
```

Your reverse proxy should:
- Serve the built frontend (`frontend/dist/`) for non-`/api` routes (SPA fallback).
- Proxy `/api/*` and `/health` to `:8000` with a long read timeout (360s) for traces.
- Pass `X-Forwarded-For`, `X-Forwarded-Proto`, `Host` headers.

> **Workers & rate limiting:** the API-key rate limiter is in-process (per-worker).
> For exact per-key limits under load, run a single worker (`--workers 1`) until
> the Redis-backed counter lands in Phase 2. For throughput over precise limits,
> use 4 workers (limits become 4× the configured rate).

---

## Configuration reference

All config is env-driven (see `backend/config.py` and `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_SECRET` | auto-generated | JWT signing secret. **Set in production.** |
| `DB_PATH` | `backend/cryptoosint.db` | SQLite path (persisted via volume in Docker). |
| `MULTI_TENANT` | `1` | Set `0` to disable org scoping (legacy mode). |
| `TSA_URL` | unset | RFC-3161 TSA for court-admissible timestamps. |
| `CORS_ORIGINS` | localhost dev ports | Comma-separated allowed origins. |
| `BASE_URL` | `http://localhost:8000` | Deployment URL (SSO callbacks). |
| `OIDC_*` | unset | SSO provider config (see `.env.example`). |
| `ETHERSCAN_API_KEY` etc. | unset | External data-source keys. |

---

## Postgres (Phase 2 — not yet)

SQLite is the zero-dependency default and is fine for single-org / small-agency
deployments. Postgres support (driver + connection abstraction) is deferred to
Phase 2. The `config.DB_PATH` centralization (Task 1) makes this a clean add-on:
swapping the driver requires no query changes, only a connection-layer refactor.
