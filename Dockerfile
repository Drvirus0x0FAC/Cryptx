# CrypTX — Production Docker image (multi-stage)
#
# Stage 1: builds the Vite frontend → static assets.
# Stage 2: Python backend + bundled OSINT modules + Playwright/Chromium, serving
#           the built frontend as static assets behind the FastAPI app.
#
# Build:  docker build -t cryptx .
# Run:    docker run -p 8000:8000 -v cryptx_data:/app/backend/data -e AUTH_SECRET=... cryptx
#
# The SQLite DB lives at /app/backend/cryptoosint.db by default; override with
# DB_PATH env. Persist it via a volume (see docker-compose.yml).

# ── Stage 1: frontend build ─────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build  # outputs to /build/dist (tsc typecheck + vite build)

# ── Stage 2: backend runtime ────────────────────────────────────────────────
FROM python:3.12-slim AS backend

# System deps for Playwright/Chromium (used by OpenSea/DeBank/Arkham scrapers)
# and for lxml build. Keep the layer small by combining installs.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libxml2-dev libxslt1-dev \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Install Python deps first (better layer caching — code changes don't bust this).
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

# Copy the backend + sibling python-modules (added to sys.path at runtime).
COPY backend/ /app/backend/
COPY python-modules/ /app/python-modules/

# Copy the built frontend into a static dir served by nginx in compose, or
# directly by FastAPI in the single-container case.
COPY --from=frontend-build /build/dist /app/frontend/dist

# Persist the SQLite DB + auth secret under /app/backend/data when a volume is
# mounted there. Default DB_PATH points at the backend dir.
ENV DB_PATH=/app/backend/data/cryptoosint.db \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /app/backend/data

EXPOSE 8000

# Production ASGI serve: 4 workers, honor proxy headers (behind nginx in compose).
# --reload is intentionally omitted (dev-only). Drop --workers to 1 if the
# in-process rate limiter (api_key_service) must be globally consistent until
# the Redis-backed counter lands in Phase 2.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
