"""
Unified async HTTP cache + concurrency-control layer.

Solves three performance problems at once:
  P2 — TTL cache so re-tracing the same address doesn't re-hit external APIs.
       Cached in SQLite (survives restarts) keyed by (cache_namespace, key).
  P3 — async-aware: all fetches go through aiohttp; never blocks the event loop.
       A `cached_fetch_sync` helper wraps blocking calls via run_in_executor so the
       sync `requests`-based engines can participate without blocking.
  P4 — global CoinGecko throttle with a proper lock + batch support.

Design: one in-process LRU memory cache (fast path) + SQLite backing (persistent).
The memory cache is checked first; on miss we check SQLite; on miss we fetch.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional

import aiohttp

import database as db

log = logging.getLogger("http_cache")

# ── In-process LRU cache (fast path) ──────────────────────────────────────────
_MEM_CACHE: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_MEM_CACHE_MAX = 2000
_MEM_LOCK = asyncio.Lock()


def _cache_key(namespace: str, key: str) -> str:
    raw = f"{namespace}:{key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def cache_get(namespace: str, key: str, ttl: int) -> Optional[Any]:
    """Return cached value if present and fresh, else None. Checks memory then SQLite."""
    ck = _cache_key(namespace, key)
    now = time.time()
    # 1. memory
    if ck in _MEM_CACHE:
        expires, val = _MEM_CACHE[ck]
        if now < expires:
            _MEM_CACHE.move_to_end(ck)
            return val
        _MEM_CACHE.pop(ck, None)
    # 2. SQLite backing store
    try:
        def _sqlite_get():
            with db.get_connection() as con:
                row = con.execute(
                    "SELECT value_json, expires_at FROM http_cache WHERE cache_key=?",
                    (ck,),
                ).fetchone()
                if not row:
                    return None
                if float(row["expires_at"]) < now:
                    return None  # expired
                return row["value_json"]
        raw = await asyncio.to_thread(_sqlite_get)
        if raw:
            val = json.loads(raw)
            _MEM_CACHE[ck] = (now + ttl, val)
            _MEM_CACHE.move_to_end(ck)
            return val
    except Exception:
        pass
    return None


async def cache_set(namespace: str, key: str, value: Any, ttl: int) -> None:
    ck = _cache_key(namespace, key)
    now = time.time()
    expires = now + ttl
    _MEM_CACHE[ck] = (expires, value)
    _MEM_CACHE.move_to_end(ck)
    async with _MEM_LOCK:
        while len(_MEM_CACHE) > _MEM_CACHE_MAX:
            _MEM_CACHE.popitem(last=False)
    # also persist to SQLite (best-effort, non-blocking)
    try:
        def _sqlite_set():
            with db.get_connection() as con:
                con.execute(
                    """INSERT OR REPLACE INTO http_cache
                       (cache_key, namespace, key, value_json, cached_at, expires_at)
                       VALUES (?,?,?,?,?,?)""",
                    (ck, namespace, key[:500], json.dumps(value, default=str),
                     str(now), str(expires)),
                )
        await asyncio.to_thread(_sqlite_set)
    except Exception:
        pass  # memory cache is still valid


def init_http_cache_tables() -> None:
    with db.get_connection() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS http_cache (
            cache_key   TEXT PRIMARY KEY,
            namespace   TEXT NOT NULL,
            key         TEXT NOT NULL,
            value_json  TEXT NOT NULL,
            cached_at   TEXT NOT NULL,
            expires_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_httpcache_ns ON http_cache(namespace, expires_at);
        """)
        # Purge expired entries on startup (cheap maintenance)
        con.execute("DELETE FROM http_cache WHERE CAST(expires_at AS REAL) < ?", (str(time.time()),))


# ── Cached async HTTP GET ─────────────────────────────────────────────────────

async def cached_get_json(
    url: str,
    *,
    namespace: str = "default",
    ttl: int = 300,
    timeout: int = 20,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    cache_bust: bool = False,
) -> Optional[Any]:
    """GET a URL, return parsed JSON, with TTL caching. None on failure."""
    # build cache key from url + sorted params
    param_str = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    key = f"{url}?{param_str}"
    if not cache_bust:
        cached = await cache_get(namespace, key, ttl)
        if cached is not None:
            return cached
    try:
        timeout_cfg = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status >= 400:
                    log.debug("cached_get_json %s -> HTTP %s", url, resp.status)
                    return None
                data = await resp.json(content_type=None)
        await cache_set(namespace, key, data, ttl)
        return data
    except Exception as exc:  # noqa: BLE001
        log.debug("cached_get_json %s failed: %s", url, exc)
        return None


async def cached_get_text(
    url: str,
    *,
    namespace: str = "default_text",
    ttl: int = 300,
    timeout: int = 20,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
) -> Optional[str]:
    """GET a URL, return text, with TTL caching."""
    param_str = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    key = f"{url}?{param_str}"
    cached = await cache_get(namespace, key, ttl)
    if cached is not None:
        return cached
    try:
        timeout_cfg = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status >= 400:
                    return None
                text = await resp.text()
        await cache_set(namespace, key, text, ttl)
        return text
    except Exception:
        return None


# ── Concurrent bounded fan-out helper (P1) ────────────────────────────────────

async def gather_with_concurrency(
    n: int,
    *coros: Awaitable,
) -> list[Any]:
    """Run N coroutines with at most `n` concurrent. Returns results in order.

    This is the fix for the sequential-await problem in the trace engines:
    instead of awaiting each address fetch one-at-a-time in a BFS loop, gather
    the frontier's fetches with a bounded semaphore.
    """
    sem = asyncio.Semaphore(n)

    async def _bound(coro: Awaitable) -> Any:
        async with sem:
            try:
                return await coro
            except Exception as exc:  # noqa: BLE001
                return exc

    return await asyncio.gather(*[_bound(c) for c in coros])


# ── Offload sync (blocking) calls off the event loop (P3) ─────────────────────

async def run_sync(func: Callable, *args, **kwargs) -> Any:
    """Run a blocking function in a thread pool so it doesn't stall the event loop.

    Use this to wrap the sync `requests`-based fetchers (public_enrichment_engine,
    price_service, sanctions_engine.refresh) when called from async handlers.
    """
    return await asyncio.to_thread(func, *args, **kwargs)


# ── Global CoinGecko throttle (P4 fix) ────────────────────────────────────────
# The old price_service used a module-level `_last_call` with time.sleep and NO lock,
# so concurrent calls under-throttled and tripped rate limits. This version uses an
# asyncio.Lock + batching.

_CG_LOCK = asyncio.Lock()
_CG_LAST_CALL = 0.0
_CG_MIN_INTERVAL = 1.6  # seconds between CoinGecko calls (free tier politeness)


async def coingecko_throttled_get(url: str, params: Optional[dict] = None,
                                  timeout: int = 15) -> Optional[Any]:
    """CoinGecko GET with a process-global throttle + lock. Replaces the buggy sleeper."""
    global _CG_LAST_CALL
    async with _CG_LOCK:
        now = time.time()
        wait = _CG_MIN_INTERVAL - (now - _CG_LAST_CALL)
        if wait > 0:
            await asyncio.sleep(wait)
        _CG_LAST_CALL = time.time()
    try:
        timeout_cfg = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.get(url, params=params) as resp:
                if resp.status == 429:
                    # rate limited — back off harder
                    await asyncio.sleep(8)
                    return None
                if resp.status >= 400:
                    return None
                return await resp.json(content_type=None)
    except Exception:
        return None


async def coingecko_batch_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch multiple coin prices in ONE CoinGecko call (vs N sequential calls).

    Replaces the convert_batch pattern that slept 1.6s per symbol.
    Uses /simple/price with a comma-joined ids list.
    """
    import constants
    ids = []
    sym_to_id = {}
    for sym in symbols:
        sym_u = sym.upper()
        # unwrap wrapped tokens for pricing
        sym_u = constants.unwrap_native(sym_u)
        cg_id = constants.COINGECKO_IDS.get(sym_u)
        if cg_id and cg_id not in ids:
            ids.append(cg_id)
            sym_to_id[sym_u] = cg_id
    if not ids:
        return {}
    # stablecoins short-circuit
    out: dict[str, float] = {}
    for sym in symbols:
        if constants.is_stable(sym.upper()):
            out[sym.upper()] = 1.0
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(ids), "vs_currencies": "usd"}
    data = await coingecko_throttled_get(url, params)
    if not data:
        return out
    for sym, cg_id in sym_to_id.items():
        price = (data.get(cg_id) or {}).get("usd")
        if price is not None:
            out[sym] = float(price)
    return out


def cache_stats() -> dict:
    """Return cache statistics for the /health or a diagnostics endpoint."""
    now = time.time()
    mem_valid = sum(1 for expires, _ in _MEM_CACHE.values() if expires > now)
    try:
        with db.get_connection() as con:
            sqlite_count = con.execute(
                "SELECT COUNT(*) FROM http_cache WHERE CAST(expires_at AS REAL) > ?",
                (str(now),),
            ).fetchone()[0]
    except Exception:
        sqlite_count = -1
    return {
        "memory_entries": len(_MEM_CACHE),
        "memory_valid": mem_valid,
        "sqlite_entries": sqlite_count,
    }


# ════════════════════════════════════════════════════════════════════════════
# Per-provider I/O discipline (Next-Horizon: async & I/O recommendation)
#
# Every external provider gets: a TTL default, a bounded-concurrency semaphore,
# a min-interval rate budget, and a circuit breaker (open after N consecutive
# failures, half-open probe after a cooldown). `guarded_get_json` /
# `guarded_post_json` are drop-in wrappers used by chain_fetchers et al.
# ════════════════════════════════════════════════════════════════════════════

PROVIDERS: dict[str, dict[str, float]] = {
    #                 ttl  conc  min_interval  fail_threshold  cooldown
    "etherscan":   {"ttl": 180, "concurrency": 4, "min_interval": 0.25, "fail_threshold": 5, "cooldown": 45},
    "blockchair":  {"ttl": 300, "concurrency": 3, "min_interval": 0.60, "fail_threshold": 4, "cooldown": 60},
    "blockcypher": {"ttl": 300, "concurrency": 3, "min_interval": 0.40, "fail_threshold": 4, "cooldown": 60},
    "blockstream": {"ttl": 240, "concurrency": 4, "min_interval": 0.25, "fail_threshold": 5, "cooldown": 45},
    "mempool":     {"ttl": 240, "concurrency": 4, "min_interval": 0.25, "fail_threshold": 5, "cooldown": 45},
    "trongrid":    {"ttl": 240, "concurrency": 3, "min_interval": 0.35, "fail_threshold": 4, "cooldown": 60},
    "solana_rpc":  {"ttl": 120, "concurrency": 4, "min_interval": 0.20, "fail_threshold": 5, "cooldown": 45},
    "coingecko":   {"ttl": 600, "concurrency": 1, "min_interval": 1.60, "fail_threshold": 3, "cooldown": 90},
    "xrpl":        {"ttl": 300, "concurrency": 3, "min_interval": 0.30, "fail_threshold": 4, "cooldown": 60},
    "tonapi":      {"ttl": 300, "concurrency": 3, "min_interval": 0.40, "fail_threshold": 4, "cooldown": 60},
    "hyperliquid": {"ttl": 120, "concurrency": 3, "min_interval": 0.30, "fail_threshold": 4, "cooldown": 60},
    "opensanctions": {"ttl": 3600, "concurrency": 2, "min_interval": 1.0, "fail_threshold": 3, "cooldown": 120},
    "default":     {"ttl": 300, "concurrency": 4, "min_interval": 0.20, "fail_threshold": 5, "cooldown": 60},
}

_DOMAIN_PROVIDER: list[tuple[str, str]] = [
    ("etherscan.io", "etherscan"), ("polygonscan.com", "etherscan"), ("bscscan.com", "etherscan"),
    ("arbiscan.io", "etherscan"), ("basescan.org", "etherscan"), ("snowtrace.io", "etherscan"),
    ("optimistic.etherscan.io", "etherscan"),
    ("blockchair.com", "blockchair"), ("blockcypher.com", "blockcypher"),
    ("blockstream.info", "blockstream"), ("mempool.space", "mempool"),
    ("trongrid.io", "trongrid"), ("tronscan.org", "trongrid"),
    ("solana.com", "solana_rpc"), ("mainnet-beta", "solana_rpc"), ("helius", "solana_rpc"),
    ("coingecko.com", "coingecko"),
    ("xrpl", "xrpl"), ("ripple.com", "xrpl"), ("livenet.xrpl.org", "xrpl"),
    ("tonapi.io", "tonapi"), ("toncenter.com", "tonapi"),
    ("hyperliquid.xyz", "hyperliquid"),
    ("opensanctions.org", "opensanctions"),
]


def provider_for_url(url: str) -> str:
    u = (url or "").lower()
    for frag, prov in _DOMAIN_PROVIDER:
        if frag in u:
            return prov
    return "default"


def provider_ttl(provider: str) -> int:
    return int((PROVIDERS.get(provider) or PROVIDERS["default"])["ttl"])


class _Breaker:
    """Consecutive-failure circuit breaker with half-open probing."""

    def __init__(self, threshold: int, cooldown: float):
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at = 0.0
        self.state = "closed"          # closed | open | half_open
        self.total_trips = 0

    def allow(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.time() - self.opened_at >= self.cooldown:
                self.state = "half_open"  # let one probe through
                return True
            return False
        return True  # half_open: probe in flight

    def record(self, ok: bool) -> None:
        if ok:
            self.failures = 0
            self.state = "closed"
            return
        self.failures += 1
        if self.state == "half_open" or self.failures >= self.threshold:
            self.state = "open"
            self.opened_at = time.time()
            self.total_trips += 1


class _ProviderState:
    def __init__(self, cfg: dict[str, float]):
        self.sem = asyncio.Semaphore(int(cfg["concurrency"]))
        self.lock = asyncio.Lock()
        self.last_call = 0.0
        self.min_interval = float(cfg["min_interval"])
        self.breaker = _Breaker(int(cfg["fail_threshold"]), float(cfg["cooldown"]))
        self.requests = 0
        self.failures = 0
        self.rejected_open = 0


_PROV_STATE: dict[str, _ProviderState] = {}


def _prov_state(provider: str) -> _ProviderState:
    st = _PROV_STATE.get(provider)
    if st is None:
        st = _ProviderState(PROVIDERS.get(provider) or PROVIDERS["default"])
        _PROV_STATE[provider] = st
    return st


async def _guarded_request(session, method: str, url: str, *, params=None, payload=None,
                           headers=None, timeout: int = 25) -> tuple[Any, Optional[str]]:
    provider = provider_for_url(url)
    st = _prov_state(provider)

    if not st.breaker.allow():
        st.rejected_open += 1
        return None, f"circuit_open:{provider} (cooling down after repeated failures)"

    async with st.sem:                       # bounded concurrency per provider
        async with st.lock:                  # min-interval rate budget
            wait = st.min_interval - (time.time() - st.last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            st.last_call = time.time()
        st.requests += 1
        try:
            if method == "GET":
                async with session.get(url, params=params, headers=headers, timeout=timeout) as resp:
                    ok = resp.status < 500 and resp.status != 429
                    data = await resp.json(content_type=None)
            else:
                h = {"Content-Type": "application/json"}
                if headers:
                    h.update(headers)
                async with session.post(url, json=payload, headers=h, timeout=timeout) as resp:
                    ok = resp.status < 500 and resp.status != 429
                    data = await resp.json(content_type=None)
            st.breaker.record(ok)
            if not ok:
                st.failures += 1
                return None, f"HTTP {resp.status} from {provider}"
            return data, None
        except Exception as exc:  # noqa: BLE001
            st.failures += 1
            st.breaker.record(False)
            return None, f"{type(exc).__name__}: {exc}"


async def guarded_get_json(session, url, params=None, headers=None, timeout: int = 25):
    """Drop-in replacement for a raw session.get(...).json() with rate budget +
    bounded concurrency + circuit breaker. Returns (data, error)."""
    return await _guarded_request(session, "GET", url, params=params, headers=headers, timeout=timeout)


async def guarded_post_json(session, url, payload, headers=None, timeout: int = 25):
    return await _guarded_request(session, "POST", url, payload=payload, headers=headers, timeout=timeout)


def provider_status() -> dict:
    """Observability: per-provider request counts, failures, breaker state."""
    out = {}
    for name, st in sorted(_PROV_STATE.items()):
        out[name] = {
            "requests": st.requests,
            "failures": st.failures,
            "rejected_while_open": st.rejected_open,
            "breaker_state": st.breaker.state,
            "breaker_trips": st.breaker.total_trips,
            "concurrency": st.sem._value if hasattr(st.sem, "_value") else None,
            "min_interval_s": st.min_interval,
            "ttl_s": provider_ttl(name),
        }
    return {"providers": out, "cache": cache_stats()}
