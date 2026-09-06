#!/usr/bin/env python3
"""
dex_trader.py — DEX (Decentralized Exchange) trade history module for OSINT Telegram bot.

Queries DEX trading history on Ethereum and BSC using TheGraph subgraphs:
  - Uniswap v3 (Ethereum): swaps + positions
  - Uniswap v2 (Ethereum): swaps
  - PancakeSwap v2 (BSC): swaps

Provides pattern analysis (buy/sell ratios, token concentration, wash-trading
detection) and Telegram-safe HTML formatting.

Env vars (all optional):
  THEGRAPH_API_KEY      — gateway API key for higher rate limits
  DEX_HTTP_TIMEOUT      — default 20 seconds
  DEX_MAX_SWAPS         — default 50 swaps per DEX
"""

import os
import re
import asyncio
import logging
from datetime import datetime, timezone
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

log = logging.getLogger(__name__)

__all__ = [
    "get_uniswap_v3_swaps",
    "get_uniswap_v2_swaps",
    "get_pancakeswap_swaps",
    "get_all_dex_activity",
    "analyze_dex_patterns",
    "format_dex_activity_html",
    "lookup_dex_activity_async",
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_DEX_HTTP_TIMEOUT = int(os.getenv("DEX_HTTP_TIMEOUT", "20"))
_DEX_MAX_SWAPS    = int(os.getenv("DEX_MAX_SWAPS", "50"))

# TheGraph subgraph endpoints
# Uniswap v3 — Ethereum mainnet
_UNISWAP_V3_SUBGRAPH = (
    "https://gateway.thegraph.com/api/{api_key}/subgraphs/id/"
    "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV"
)
_UNISWAP_V3_SUBGRAPH_PUBLIC = (
    "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3"
)

# Uniswap v2 — Ethereum mainnet
_UNISWAP_V2_SUBGRAPH = (
    "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
)

# PancakeSwap v2 — BSC
_PANCAKESWAP_SUBGRAPH = (
    "https://api.thegraph.com/subgraphs/name/pancakeswap/exchange-v2-bsc"
)

# Stablecoin addresses for USD-estimation heuristics
_STABLECOINS = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",   # USDC
    "0xdac17f958d2ee523a2206206994597c13d831ec7",   # USDT
    "0x6b175474e89094c44da98b954eedeac495271d0f",   # DAI
    "0x4fabb145d64652a948d72533023f6e7a623c7c53",   # BUSD (ETH)
    "0xe9e7cea3dedca5984780bafc599bd69add087d56",   # BUSD (BSC)
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",   # USDC (BSC)
    "0x55d398326f99059ff775485246999027b3197955",   # USDT (BSC)
}

# WETH / WBNB wrappers for native pair identification
_WRAPPED_NATIVE = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",   # WETH
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",   # WBNB
    "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270",   # WMATIC
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fmt_ts(epoch: Optional[int]) -> str:
    """Convert Unix timestamp to ISO-style string."""
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    except Exception:
        return ""


def _fmt_date_only(epoch: Optional[int]) -> str:
    """Convert Unix timestamp to YYYY-MM-DD."""
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _num(v: Any, default: float = 0.0) -> float:
    """Safe numeric conversion."""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _is_eth_address(addr: str) -> bool:
    """Validate Ethereum/BSC address format."""
    return bool(re.match(r"^0x[a-fA-F0-9]{40}$", (addr or "").strip()))


def _to_checksum(addr: str) -> str:
    """Return lowercased address (TheGraph expects lowercase)."""
    return addr.strip().lower()


def _esc(text: str) -> str:
    """Escape for Telegram HTML: <b>, <i>, <code> safe."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _graphql_url(endpoint: str, api_key: str = "") -> str:
    """Return the appropriate endpoint URL, substituting API key if available."""
    if api_key and "{api_key}" in endpoint:
        return endpoint.format(api_key=api_key)
    # Strip gateway pattern if no key — fall back to public endpoint
    if "{api_key}" in endpoint:
        # Return the public fallback for Uniswap v3
        return _UNISWAP_V3_SUBGRAPH_PUBLIC
    return endpoint


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
async def _graphql_query(
    endpoint: str,
    query: str,
    variables: dict,
    api_key: str = "",
) -> Optional[dict]:
    """
    Execute a GraphQL query against a TheGraph endpoint.
    Returns the parsed JSON response or None on failure.
    """
    url = _graphql_url(endpoint, api_key)
    payload = {"query": query, "variables": variables}
    headers = {"Content-Type": "application/json"}
    try:
        timeout = aiohttp.ClientTimeout(total=_DEX_HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(url, json=payload, headers=headers) as r:
                if r.status != 200:
                    log.warning("GraphQL HTTP %s on %s", r.status, url)
                    return None
                data = await r.json()
                if "errors" in (data or {}):
                    errs = data["errors"]
                    log.warning(
                        "GraphQL errors on %s: %s",
                        url,
                        errs[0].get("message", errs) if isinstance(errs, list) else errs,
                    )
                    return None
                return data
    except asyncio.TimeoutError:
        log.warning("GraphQL timeout on %s", url)
    except Exception as exc:
        log.warning("GraphQL error on %s: %s", url, exc)
    return None


# ---------------------------------------------------------------------------
# GraphQL query strings
# ---------------------------------------------------------------------------
_UNISWAP_V3_SWAPS_QUERY = """
query($addr: String!, $first: Int!) {
  swaps(
    where: {origin: $addr}
    orderBy: timestamp
    orderDirection: desc
    first: $first
  ) {
    timestamp
    token0 { symbol decimals }
    token1 { symbol decimals }
    amount0
    amount1
    sqrtPriceX96
    tick
    transaction { id blockNumber gasPrice }
    pool { id token0 { id symbol } token1 { id symbol } feeTier }
  }
}
"""

_UNISWAP_V3_POSITIONS_QUERY = """
query($addr: String!) {
  positions(where: {owner: $addr}) {
    id
    pool { token0 { symbol } token1 { symbol } feeTier }
    liquidity
    depositedToken0
    depositedToken1
  }
}
"""

_UNISWAP_V2_SWAPS_QUERY = """
query($addr: String!, $first: Int!) {
  swaps(
    where: { to: $addr }
    orderBy: timestamp
    orderDirection: desc
    first: $first
  ) {
    timestamp
    pair {
      token0 { symbol id }
      token1 { symbol id }
    }
    amount0In
    amount0Out
    amount1In
    amount1Out
    amountUSD
    transaction { id blockNumber }
    to
    sender
  }
}
"""

_PANCAKESWAP_SWAPS_QUERY = """
query($addr: String!, $first: Int!) {
  swaps(
    where: { to: $addr }
    orderBy: timestamp
    orderDirection: desc
    first: $first
  ) {
    timestamp
    pair {
      token0 { symbol id }
      token1 { symbol id }
    }
    amount0In
    amount0Out
    amount1In
    amount1Out
    amountUSD
    transaction { id blockNumber }
    to
    sender
  }
}
"""


# ---------------------------------------------------------------------------
# Raw swap normalisers
# ---------------------------------------------------------------------------
def _normalize_uniswap_v3_swap(raw: dict) -> dict:
    """Convert a raw Uniswap v3 swap subgraph row into a normalized dict."""
    t0 = raw.get("token0") or {}
    t1 = raw.get("token1") or {}
    tx = raw.get("transaction") or {}
    pool = raw.get("pool") or {}
    amt0 = _num(raw.get("amount0"))
    amt1 = _num(raw.get("amount1"))

    # Determine direction: if amount0 > 0, token0 went into pool (user sold token0)
    # if amount0 < 0, token0 came out of pool (user bought token0)
    direction = "BUY" if amt0 < 0 else "SELL"

    # Price estimate from sqrtPriceX96 (token1 per token0)
    sqrt_p = _num(raw.get("sqrtPriceX96"))
    price = 0.0
    if sqrt_p > 0:
        try:
            price = (sqrt_p ** 2) / (2 ** 192)
        except Exception:
            price = 0.0

    return {
        "timestamp": _int(raw.get("timestamp")),
        "datetime": _fmt_ts(raw.get("timestamp")),
        "date": _fmt_date_only(raw.get("timestamp")),
        "token0_symbol": t0.get("symbol", "?"),
        "token1_symbol": t1.get("symbol", "?"),
        "token0_decimals": _int(t0.get("decimals"), 18),
        "token1_decimals": _int(t1.get("decimals"), 18),
        "amount0": amt0,
        "amount1": amt1,
        "direction": direction,
        "price": price,
        "pool_id": (pool.get("id") or "")[:12],
        "pool_token0": (pool.get("token0") or {}).get("symbol", "?"),
        "pool_token1": (pool.get("token1") or {}).get("symbol", "?"),
        "fee_tier": pool.get("feeTier", ""),
        "tx_hash": tx.get("id", ""),
        "block_number": _int(tx.get("blockNumber")),
        "gas_price": _num(tx.get("gasPrice")),
        "tick": _int(raw.get("tick")),
        "version": "uniswap_v3",
    }


def _normalize_uniswap_v2_swap(raw: dict) -> dict:
    """Convert a raw Uniswap v2 swap subgraph row into a normalized dict."""
    pair = raw.get("pair") or {}
    t0 = pair.get("token0") or {}
    t1 = pair.get("token1") or {}
    tx = raw.get("transaction") or {}

    a0_in  = _num(raw.get("amount0In"))
    a0_out = _num(raw.get("amount0Out"))
    a1_in  = _num(raw.get("amount1In"))
    a1_out = _num(raw.get("amount1Out"))

    # V2: amountXIn means user sold tokenX; amountXOut means user bought tokenX
    if a0_in > 0 and a1_out > 0:
        direction = "SELL"  # sold token0, bought token1
    elif a1_in > 0 and a0_out > 0:
        direction = "BUY"   # bought token0, sold token1
    else:
        direction = "UNKNOWN"

    return {
        "timestamp": _int(raw.get("timestamp")),
        "datetime": _fmt_ts(raw.get("timestamp")),
        "date": _fmt_date_only(raw.get("timestamp")),
        "token0_symbol": t0.get("symbol", "?"),
        "token1_symbol": t1.get("symbol", "?"),
        "token0_decimals": 18,
        "token1_decimals": 18,
        "amount0": a0_out - a0_in,
        "amount1": a1_out - a1_in,
        "direction": direction,
        "amount_usd": _num(raw.get("amountUSD")),
        "pool_id": (pair.get("id") or "")[:12],
        "pool_token0": t0.get("symbol", "?"),
        "pool_token1": t1.get("symbol", "?"),
        "fee_tier": "3000",  # V2 uses 0.3% fee
        "tx_hash": tx.get("id", ""),
        "block_number": _int(tx.get("blockNumber")),
        "gas_price": 0.0,
        "tick": 0,
        "version": "uniswap_v2",
    }


def _normalize_pancakeswap_swap(raw: dict) -> dict:
    """Convert a raw PancakeSwap v2 swap subgraph row into a normalized dict."""
    # PancakeSwap v2 schema is identical to Uniswap v2
    pair = raw.get("pair") or {}
    t0 = pair.get("token0") or {}
    t1 = pair.get("token1") or {}
    tx = raw.get("transaction") or {}

    a0_in  = _num(raw.get("amount0In"))
    a0_out = _num(raw.get("amount0Out"))
    a1_in  = _num(raw.get("amount1In"))
    a1_out = _num(raw.get("amount1Out"))

    if a0_in > 0 and a1_out > 0:
        direction = "SELL"
    elif a1_in > 0 and a0_out > 0:
        direction = "BUY"
    else:
        direction = "UNKNOWN"

    return {
        "timestamp": _int(raw.get("timestamp")),
        "datetime": _fmt_ts(raw.get("timestamp")),
        "date": _fmt_date_only(raw.get("timestamp")),
        "token0_symbol": t0.get("symbol", "?"),
        "token1_symbol": t1.get("symbol", "?"),
        "token0_decimals": 18,
        "token1_decimals": 18,
        "amount0": a0_out - a0_in,
        "amount1": a1_out - a1_in,
        "direction": direction,
        "amount_usd": _num(raw.get("amountUSD")),
        "pool_id": (pair.get("id") or "")[:12],
        "pool_token0": t0.get("symbol", "?"),
        "pool_token1": t1.get("symbol", "?"),
        "fee_tier": "2500",  # PancakeSwap v2 = 0.25%
        "tx_hash": tx.get("id", ""),
        "block_number": _int(tx.get("blockNumber")),
        "gas_price": 0.0,
        "tick": 0,
        "version": "pancakeswap_v2",
    }


# ---------------------------------------------------------------------------
# Core query functions
# ---------------------------------------------------------------------------
async def get_uniswap_v3_swaps(
    address: str,
    graph_api_key: str = "",
    limit: int = 50,
) -> dict:
    """
    Fetch Uniswap v3 swap history for an address from TheGraph.

    Args:
        address: Ethereum wallet address (0x...).
        graph_api_key: Optional TheGraph gateway API key.
        limit: Maximum swaps to retrieve (default 50).

    Returns:
        dict with keys: address, chain, dex, swaps, positions, swap_count, error.
    """
    addr = _to_checksum(address)
    if not _is_eth_address(addr):
        return {"address": address, "chain": "ETH", "dex": "uniswap_v3",
                "swaps": [], "positions": [], "swap_count": 0,
                "error": "Invalid Ethereum address"}

    # Query swaps + positions concurrently
    swaps_resp, pos_resp = await asyncio.gather(
        _graphql_query(
            _UNISWAP_V3_SUBGRAPH,
            _UNISWAP_V3_SWAPS_QUERY,
            {"addr": addr, "first": min(limit, 100)},
            api_key=graph_api_key,
        ),
        _graphql_query(
            _UNISWAP_V3_SUBGRAPH,
            _UNISWAP_V3_POSITIONS_QUERY,
            {"addr": addr},
            api_key=graph_api_key,
        ),
        return_exceptions=True,
    )

    swaps_raw = []
    positions_raw = []
    error_parts = []

    if isinstance(swaps_resp, Exception):
        error_parts.append(f"swaps: {swaps_resp}")
    elif swaps_resp is None:
        error_parts.append("swaps: TheGraph returned no data")
    else:
        swaps_raw = (swaps_resp.get("data") or {}).get("swaps") or []

    if isinstance(pos_resp, Exception):
        error_parts.append(f"positions: {pos_resp}")
    elif pos_resp is not None:
        positions_raw = (pos_resp.get("data") or {}).get("positions") or []

    normalized_swaps = [_normalize_uniswap_v3_swap(s) for s in swaps_raw]
    positions = []
    for p in positions_raw:
        pool = p.get("pool") or {}
        positions.append({
            "id": p.get("id", ""),
            "pool_id": pool.get("id", ""),
            "token0": (pool.get("token0") or {}).get("symbol", "?"),
            "token1": (pool.get("token1") or {}).get("symbol", "?"),
            "fee_tier": pool.get("feeTier", ""),
            "liquidity": _num(p.get("liquidity")),
            "deposited_token0": _num(p.get("depositedToken0")),
            "deposited_token1": _num(p.get("depositedToken1")),
        })

    error_msg = "; ".join(error_parts) if error_parts else ""

    return {
        "address": addr,
        "chain": "ETH",
        "dex": "uniswap_v3",
        "swaps": normalized_swaps,
        "positions": positions,
        "swap_count": len(normalized_swaps),
        "error": error_msg,
    }


async def get_uniswap_v2_swaps(
    address: str,
    graph_api_key: str = "",
    limit: int = 50,
) -> dict:
    """
    Fetch Uniswap v2 swap history for an address from TheGraph.

    Args:
        address: Ethereum wallet address (0x...).
        graph_api_key: Unused (public endpoint), kept for API consistency.
        limit: Maximum swaps to retrieve (default 50).

    Returns:
        dict with keys: address, chain, dex, swaps, swap_count, error.
    """
    addr = _to_checksum(address)
    if not _is_eth_address(addr):
        return {"address": address, "chain": "ETH", "dex": "uniswap_v2",
                "swaps": [], "swap_count": 0,
                "error": "Invalid Ethereum address"}

    resp = await _graphql_query(
        _UNISWAP_V2_SUBGRAPH,
        _UNISWAP_V2_SWAPS_QUERY,
        {"addr": addr, "first": min(limit, 100)},
    )

    if resp is None:
        return {"address": addr, "chain": "ETH", "dex": "uniswap_v2",
                "swaps": [], "swap_count": 0,
                "error": "TheGraph (Uniswap v2) returned no data"}
    if isinstance(resp, Exception):
        return {"address": addr, "chain": "ETH", "dex": "uniswap_v2",
                "swaps": [], "swap_count": 0,
                "error": f"TheGraph error: {resp}"}

    raw_swaps = (resp.get("data") or {}).get("swaps") or []
    normalized = [_normalize_uniswap_v2_swap(s) for s in raw_swaps]

    return {
        "address": addr,
        "chain": "ETH",
        "dex": "uniswap_v2",
        "swaps": normalized,
        "swap_count": len(normalized),
        "error": "",
    }


async def get_pancakeswap_swaps(
    address: str,
    graph_api_key: str = "",
    limit: int = 50,
) -> dict:
    """
    Fetch PancakeSwap v2 swap history for an address from TheGraph (BSC).

    Args:
        address: BSC wallet address (0x...).
        graph_api_key: Unused (public endpoint), kept for API consistency.
        limit: Maximum swaps to retrieve (default 50).

    Returns:
        dict with keys: address, chain, dex, swaps, swap_count, error.
    """
    addr = _to_checksum(address)
    if not _is_eth_address(addr):
        return {"address": address, "chain": "BSC", "dex": "pancakeswap_v2",
                "swaps": [], "swap_count": 0,
                "error": "Invalid BSC address"}

    resp = await _graphql_query(
        _PANCAKESWAP_SUBGRAPH,
        _PANCAKESWAP_SWAPS_QUERY,
        {"addr": addr, "first": min(limit, 100)},
    )

    if resp is None:
        return {"address": addr, "chain": "BSC", "dex": "pancakeswap_v2",
                "swaps": [], "swap_count": 0,
                "error": "TheGraph (PancakeSwap) returned no data"}
    if isinstance(resp, Exception):
        return {"address": addr, "chain": "BSC", "dex": "pancakeswap_v2",
                "swaps": [], "swap_count": 0,
                "error": f"TheGraph error: {resp}"}

    raw_swaps = (resp.get("data") or {}).get("swaps") or []
    normalized = [_normalize_pancakeswap_swap(s) for s in raw_swaps]

    return {
        "address": addr,
        "chain": "BSC",
        "dex": "pancakeswap_v2",
        "swaps": normalized,
        "swap_count": len(normalized),
        "error": "",
    }


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------
async def get_all_dex_activity(
    address: str,
    graph_api_key: str = "",
    limit: int = 50,
) -> dict:
    """
    Aggregate DEX activity across Uniswap v3, Uniswap v2 (ETH) and PancakeSwap (BSC).

    Queries all three endpoints concurrently.  Returns a unified result dict with
    individual DEX results preserved for downstream analysis.

    Args:
        address: Wallet address (0x...).  Same format for ETH and BSC.
        graph_api_key: Optional TheGraph gateway API key.
        limit: Per-DEX swap limit (default 50).

    Returns:
        dict with keys:
          address, chain, uniswap_v3, uniswap_v2, pancakeswap,
          all_swaps, errors, total_swap_count.
    """
    addr = _to_checksum(address)
    if not _is_eth_address(addr):
        return {
            "address": address,
            "chain": "UNKNOWN",
            "uniswap_v3": None,
            "uniswap_v2": None,
            "pancakeswap": None,
            "all_swaps": [],
            "errors": ["Invalid address format"],
            "total_swap_count": 0,
        }

    # Fire all three queries concurrently
    u3, u2, pcs = await asyncio.gather(
        get_uniswap_v3_swaps(addr, graph_api_key, limit),
        get_uniswap_v2_swaps(addr, graph_api_key, limit),
        get_pancakeswap_swaps(addr, graph_api_key, limit),
        return_exceptions=True,
    )

    results = [u3, u2, pcs]
    errors = []
    all_swaps: List[dict] = []

    for r in results:
        if isinstance(r, Exception):
            errors.append(str(r))
            continue
        if r.get("error"):
            errors.append(f"{r.get('dex', '?')}: {r['error']}")
        all_swaps.extend(r.get("swaps") or [])

    # Sort all swaps by timestamp descending
    all_swaps.sort(key=lambda s: s.get("timestamp", 0), reverse=True)

    total_count = len(all_swaps)

    # Determine primary chain label
    chains_seen = set()
    if u3 and not isinstance(u3, Exception) and u3.get("swap_count", 0) > 0:
        chains_seen.add("ETH")
    if u2 and not isinstance(u2, Exception) and u2.get("swap_count", 0) > 0:
        chains_seen.add("ETH")
    if pcs and not isinstance(pcs, Exception) and pcs.get("swap_count", 0) > 0:
        chains_seen.add("BSC")
    primary_chain = "/".join(sorted(chains_seen)) if chains_seen else "ETH/BSC"

    return {
        "address": addr,
        "chain": primary_chain,
        "uniswap_v3": u3 if not isinstance(u3, Exception) else None,
        "uniswap_v2": u2 if not isinstance(u2, Exception) else None,
        "pancakeswap": pcs if not isinstance(pcs, Exception) else None,
        "all_swaps": all_swaps,
        "errors": errors,
        "total_swap_count": total_count,
    }


# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------
def analyze_dex_patterns(swaps: List[dict]) -> dict:
    """
    Analyse a list of normalized swaps for trading patterns and suspicious activity.

    Identifies:
      - Most traded tokens (by frequency + estimated volume)
      - Buy / sell ratio
      - Trading frequency (days active)
      - Pool concentration
      - Potential wash-trading (self-trades, round-trip within 1 hour)
      - Token concentration alerts
      - Activity gaps

    Args:
        swaps: List of normalized swap dicts from _normalize_* functions.

    Returns:
        dict with pattern analysis results and alert strings.
    """
    if not swaps:
        return {
            "total_swaps": 0,
            "total_volume_usd": 0.0,
            "first_trade": "",
            "last_trade": "",
            "trading_days": 0,
            "most_traded_tokens": [],
            "buy_sell_ratio": {"buys": 0, "sells": 0, "ratio": "0:1"},
            "pools_used": [],
            "pattern_alerts": ["No swap data available for analysis"],
        }

    # Basic stats
    total_swaps = len(swaps)
    timestamps = [s.get("timestamp", 0) for s in swaps if s.get("timestamp")]
    first_ts = min(timestamps) if timestamps else 0
    last_ts = max(timestamps) if timestamps else 0

    # Trading days
    dates = {s.get("date", "") for s in swaps if s.get("date")}
    trading_days = len(dates)

    # Buy / sell counts
    buys = sum(1 for s in swaps if s.get("direction") == "BUY")
    sells = sum(1 for s in swaps if s.get("direction") == "SELL")
    unknowns = total_swaps - buys - sells
    ratio_str = f"{buys}:{sells}" if sells > 0 else f"{buys}:0"

    # Token frequency — count appearances of each non-WETH/WBNB token
    token_counts: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "buy_count": 0, "sell_count": 0, "volume_usd": 0.0})
    for s in swaps:
        t0 = s.get("token0_symbol", "?")
        t1 = s.get("token1_symbol", "?")
        direction = s.get("direction", "UNKNOWN")

        for tok in (t0, t1):
            token_counts[tok]["count"] += 1
            if direction == "BUY":
                token_counts[tok]["buy_count"] += 1
            elif direction == "SELL":
                token_counts[tok]["sell_count"] += 1

        # Accumulate USD volume when available
        usd = s.get("amount_usd")
        if usd:
            token_counts[t0]["volume_usd"] += usd / 2
            token_counts[t1]["volume_usd"] += usd / 2

    # Sort by count, exclude wrapped native tokens from "most traded"
    sorted_tokens = sorted(
        [
            {
                "symbol": sym,
                "count": data["count"],
                "buy_count": data["buy_count"],
                "sell_count": data["sell_count"],
                "volume_usd": round(data["volume_usd"], 2),
            }
            for sym, data in token_counts.items()
            if sym not in ("WETH", "WBNB", "WMATIC", "?")
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    # Pool usage
    pool_counter: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "fee_tier": "", "version": ""})
    for s in swaps:
        pair = f"{s.get('pool_token0', '?')}/{s.get('pool_token1', '?')}"
        pool_counter[pair]["count"] += 1
        pool_counter[pair]["fee_tier"] = s.get("fee_tier", "")
        pool_counter[pair]["version"] = s.get("version", "")

    sorted_pools = sorted(
        [
            {
                "pair": pair,
                "fee_tier": data["fee_tier"],
                "swap_count": data["count"],
                "version": data["version"],
            }
            for pair, data in pool_counter.items()
        ],
        key=lambda x: x["swap_count"],
        reverse=True,
    )

    # Volume estimate — sum amountUSD when available, otherwise rough heuristic
    total_volume_usd = sum(
        _num(s.get("amount_usd")) for s in swaps
    )
    if total_volume_usd == 0:
        # Fallback: count each swap as ~$100 placeholder for ranking
        total_volume_usd = total_swaps * 100.0

    # ── Pattern alerts ──────────────────────────────────────────────────────
    alerts: List[str] = []

    # 1. Heavy token concentration
    if sorted_tokens:
        top = sorted_tokens[0]
        concentration = (top["count"] / sum(t["count"] for t in sorted_tokens)) * 100 if sorted_tokens else 0
        if concentration >= 40:
            alerts.append(
                f"Heavy concentration in {top['symbol']} token ({concentration:.0f}% of token appearances)"
            )

    # 2. Only buys / only sells
    if buys > 0 and sells == 0:
        alerts.append("Only BUY trades detected — possible accumulation strategy or single-direction bot")
    elif sells > 0 and buys == 0:
        alerts.append("Only SELL trades detected — possible liquidation or exit pattern")

    # 3. Buy/sell skew
    if buys > 0 and sells > 0:
        skew = buys / sells
        if skew >= 3.0:
            alerts.append(f"Heavy buy skew ({skew:.1f}:1) — aggressive accumulation")
        elif sells / buys >= 3.0:
            alerts.append(f"Heavy sell skew ({sells / buys:.1f}:1) — aggressive distribution")

    # 4. Single pool concentration
    if sorted_pools:
        top_pool_pct = (sorted_pools[0]["swap_count"] / total_swaps) * 100
        if top_pool_pct >= 70:
            alerts.append(
                f"Concentrated in single pool {sorted_pools[0]['pair']} ({top_pool_pct:.0f}% of trades)"
            )

    # 5. Potential wash trading (rapid round-trips within 1 hour)
    wash_trade_suspects = 0
    swaps_by_ts = sorted(swaps, key=lambda s: s.get("timestamp", 0))
    for i in range(len(swaps_by_ts) - 1):
        s1 = swaps_by_ts[i]
        s2 = swaps_by_ts[i + 1]
        ts1 = s1.get("timestamp", 0)
        ts2 = s2.get("timestamp", 0)
        if ts2 - ts1 < 3600:  # within 1 hour
            # Same token pair reversed direction
            pair1 = {s1.get("token0_symbol"), s1.get("token1_symbol")}
            pair2 = {s2.get("token0_symbol"), s2.get("token1_symbol")}
            if pair1 == pair2 and s1.get("direction") != s2.get("direction"):
                wash_trade_suspects += 1
    if wash_trade_suspects >= 3:
        alerts.append(
            f"Potential wash-trading: {wash_trade_suspects} rapid round-trip swaps within 1 hour"
        )

    # 6. Activity gap (no trades in last 30 days)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if last_ts and (now_ts - last_ts) > 30 * 86400:
        days_inactive = (now_ts - last_ts) // 86400
        alerts.append(f"No trades in last {days_inactive} days — possible HODL or inactive account")

    # 7. Very high frequency on few days
    if trading_days > 0 and total_swaps / trading_days >= 10:
        alerts.append(
            f"High-frequency trading: {total_swaps / trading_days:.0f} swaps/day average"
        )

    # 8. Low diversity (only 1 unique token pair)
    unique_pairs = len(pool_counter)
    if unique_pairs == 1 and total_swaps >= 5:
        alerts.append("Single-pair trader — very low diversity")

    if not alerts:
        alerts.append("No suspicious patterns detected")

    return {
        "total_swaps": total_swaps,
        "total_volume_usd": round(total_volume_usd, 2),
        "first_trade": _fmt_date_only(first_ts) if first_ts else "",
        "last_trade": _fmt_date_only(last_ts) if last_ts else "",
        "trading_days": trading_days,
        "most_traded_tokens": sorted_tokens[:10],
        "buy_sell_ratio": {
            "buys": buys,
            "sells": sells,
            "unknown": unknowns,
            "ratio": ratio_str,
        },
        "pools_used": sorted_pools[:10],
        "pattern_alerts": alerts,
    }


# ---------------------------------------------------------------------------
# Telegram HTML formatting
# ---------------------------------------------------------------------------
def format_dex_activity_html(result: dict) -> str:
    """
    Format DEX activity result into Telegram-safe HTML.

    Uses only <b>, <i>, <code> tags.  All dynamic text is escaped.
    """
    addr = result.get("address", "")
    chain = result.get("chain", "?")
    total_swaps = result.get("total_swaps", 0)
    total_vol = result.get("total_volume_usd", 0.0)
    first_trade = result.get("first_trade", "")
    last_trade = result.get("last_trade", "")
    trading_days = result.get("trading_days", 0)
    tokens = result.get("most_traded_tokens", [])
    ratio = result.get("buy_sell_ratio", {})
    pools = result.get("pools_used", [])
    alerts = result.get("pattern_alerts", [])

    lines = [
        f"<b>═══ DEX Trading Activity ═══</b>",
        f"<b>Address:</b> <code>{_esc(addr)}</code>",
        f"<b>Chain(s):</b> <code>{_esc(chain)}</code>",
        f"<b>Total Swaps:</b> <code>{total_swaps}</code>",
    ]

    if total_vol > 0:
        if total_vol >= 1_000_000:
            lines.append(f"<b>Est. Volume:</b> <code>${total_vol:,.0f}</code>")
        elif total_vol >= 1_000:
            lines.append(f"<b>Est. Volume:</b> <code>${total_vol:,.2f}</code>")
        else:
            lines.append(f"<b>Est. Volume:</b> <code>${total_vol:.2f}</code>")

    if first_trade:
        lines.append(f"<b>First Trade:</b> <code>{_esc(first_trade)}</code>")
    if last_trade:
        lines.append(f"<b>Last Trade:</b>  <code>{_esc(last_trade)}</code>")
    if trading_days:
        lines.append(f"<b>Active Days:</b> <code>{trading_days}</code>")

    # Buy/Sell ratio
    if ratio:
        buys = ratio.get("buys", 0)
        sells = ratio.get("sells", 0)
        unknowns = ratio.get("unknown", 0)
        ratio_str = ratio.get("ratio", "0:0")
        ratio_line = f"<b>Buy/Sell:</b> <code>{buys}</code> buys / <code>{sells}</code> sells"
        if unknowns:
            ratio_line += f" (<code>{unknowns}</code> unknown)"
        ratio_line += f"  <i>({ratio_str})</i>"
        lines.append("")
        lines.append(ratio_line)

    # Most traded tokens
    if tokens:
        lines.append("")
        lines.append(f"<b>── Most Traded Tokens ──</b>")
        for t in tokens[:8]:
            sym = _esc(t.get("symbol", "?"))
            cnt = t.get("count", 0)
            vol = t.get("volume_usd", 0.0)
            b = t.get("buy_count", 0)
            sl = t.get("sell_count", 0)
            vol_str = f"  ${vol:,.2f}" if vol > 0 else ""
            lines.append(f"• <b>{sym}</b>: <code>{cnt}</code> swaps ({b}B/{sl}S){vol_str}")

    # Pools used
    if pools:
        lines.append("")
        lines.append(f"<b>── Pools Used ──</b>")
        for p in pools[:8]:
            pair = _esc(p.get("pair", "?"))
            fee = p.get("fee_tier", "")
            cnt = p.get("swap_count", 0)
            ver = _esc(p.get("version", "").replace("_", " "))
            fee_str = f" {int(fee) / 10000:.2f}%" if fee else ""
            lines.append(f"• <b>{pair}</b>{_esc(fee_str)} — <code>{cnt}</code> swaps  <i>({ver})</i>")

    # Alerts
    lines.append("")
    lines.append(f"<b>── Pattern Alerts ──</b>")
    for alert in alerts:
        if "suspicious" in alert.lower() or "wash" in alert.lower() or "Heavy" in alert or "Only" in alert or "skew" in alert.lower():
            lines.append(f"⚠️ <i>{_esc(alert)}</i>")
        else:
            lines.append(f"• {_esc(alert)}")

    # Error summary
    errors = result.get("errors", [])
    if errors:
        lines.append("")
        lines.append(f"<b>── Errors ──</b>")
        for e in errors[:3]:
            lines.append(f"⚠️ <i>{_esc(str(e)[:200])}</i>")

    # Append a subset of raw recent swaps for quick reference
    all_swaps = result.get("all_swaps", [])
    v3_swaps = result.get("uniswap_v3_swaps", [])
    v2_swaps = result.get("uniswap_v2_swaps", [])
    pcs_swaps = result.get("pancakeswap_swaps", [])

    # Prefer explicit per-dex lists if present, else fall back to all_swaps
    display_swaps = []
    if v3_swaps:
        display_swaps.extend([("UV3", s) for s in v3_swaps[:5]])
    if v2_swaps:
        display_swaps.extend([("UV2", s) for s in v2_swaps[:5]])
    if pcs_swaps:
        display_swaps.extend([("PCS", s) for s in pcs_swaps[:5]])
    if not display_swaps and all_swaps:
        display_swaps = [(s.get("version", "?").replace("uniswap_", "U").replace("pancakeswap_", "PCS")[:4], s) for s in all_swaps[:10]]

    if display_swaps:
        lines.append("")
        lines.append(f"<b>── Recent Swaps ──</b>")
        for label, s in display_swaps[:12]:
            t0 = _esc(s.get("token0_symbol", "?"))
            t1 = _esc(s.get("token1_symbol", "?"))
            direction = s.get("direction", "?")
            arrow = "▲" if direction == "BUY" else ("▼" if direction == "SELL" else "•")
            ts = _esc((s.get("datetime") or "")[:16])
            pair = f"{t0}/{t1}"
            usd = s.get("amount_usd")
            usd_str = f"  ${usd:,.2f}" if usd else ""
            lines.append(f"{arrow} <code>[{_esc(label)}]</code> <b>{pair}</b> {direction}{usd_str}  <i>{ts}</i>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point (matches bot architecture)
# ---------------------------------------------------------------------------
async def lookup_dex_activity_async(
    address: str,
    graph_api_key: str = "",
    limit: int = 50,
) -> dict:
    """
    Main async entry point for the OSINT bot.

    Retrieves all DEX activity, runs pattern analysis, and returns a
    consolidated result dict suitable for both programmatic use and
    Telegram display via :func:`format_dex_activity_html`.

    Args:
        address: Wallet address (0x...).
        graph_api_key: Optional TheGraph gateway API key.
        limit: Maximum swaps per DEX (default 50).

    Returns:
        Consolidated result dict matching the spec in the module docstring.
    """
    addr = (address or "").strip()

    if not _is_eth_address(addr):
        empty = {
            "address": addr,
            "chain": "UNKNOWN",
            "total_swaps": 0,
            "total_volume_usd": 0.0,
            "first_trade": "",
            "last_trade": "",
            "trading_days": 0,
            "most_traded_tokens": [],
            "buy_sell_ratio": {"buys": 0, "sells": 0, "ratio": "0:1"},
            "pools_used": [],
            "uniswap_v3_swaps": [],
            "uniswap_v2_swaps": [],
            "pancakeswap_swaps": [],
            "all_swaps": [],
            "pattern_alerts": ["Invalid address format — expected 0x... (40 hex chars)"],
            "errors": ["Invalid address"],
            "error": "Invalid address format",
        }
        empty["html"] = format_dex_activity_html(empty)
        return empty

    # Fetch aggregated activity
    activity = await get_all_dex_activity(addr, graph_api_key, limit)

    # Flatten per-dex swap lists for convenience
    u3_swaps = []
    u2_swaps = []
    pcs_swaps = []
    if activity.get("uniswap_v3"):
        u3_swaps = activity["uniswap_v3"].get("swaps", [])
    if activity.get("uniswap_v2"):
        u2_swaps = activity["uniswap_v2"].get("swaps", [])
    if activity.get("pancakeswap"):
        pcs_swaps = activity["pancakeswap"].get("swaps", [])

    all_swaps = activity.get("all_swaps", [])

    # Run pattern analysis
    patterns = analyze_dex_patterns(all_swaps)

    # Compose final result
    result = {
        "address": activity.get("address", addr),
        "chain": activity.get("chain", "ETH/BSC"),
        "total_swaps": patterns.get("total_swaps", 0),
        "total_volume_usd": patterns.get("total_volume_usd", 0.0),
        "first_trade": patterns.get("first_trade", ""),
        "last_trade": patterns.get("last_trade", ""),
        "trading_days": patterns.get("trading_days", 0),
        "most_traded_tokens": patterns.get("most_traded_tokens", []),
        "buy_sell_ratio": patterns.get("buy_sell_ratio", {}),
        "pools_used": patterns.get("pools_used", []),
        "uniswap_v3_swaps": u3_swaps,
        "uniswap_v2_swaps": u2_swaps,
        "pancakeswap_swaps": pcs_swaps,
        "all_swaps": all_swaps,
        "pattern_alerts": patterns.get("pattern_alerts", []),
        "errors": activity.get("errors", []),
        "error": "; ".join(activity.get("errors", [])) if activity.get("errors") else "",
    }

    # Pre-render HTML for bot convenience
    result["html"] = format_dex_activity_html(result)

    return result


# ---------------------------------------------------------------------------
# Synchronous wrapper for simple usage
# ---------------------------------------------------------------------------
def lookup_dex_activity(
    address: str,
    graph_api_key: str = "",
    limit: int = 50,
) -> dict:
    """
    Synchronous wrapper around :func:`lookup_dex_activity_async`.
    Spins up a temporary event loop (or uses the existing one).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(lookup_dex_activity_async(address, graph_api_key, limit))
    # If we're already in an async context, schedule it
    return loop.run_until_complete(lookup_dex_activity_async(address, graph_api_key, limit))
