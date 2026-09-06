"""
Historical price service — fiat valuation *at time of transaction*.

Backs the board/graph USD↔native toggle. Uses the free CoinGecko history API
(`/coins/{id}/history?date=dd-mm-yyyy`) with a permanent SQLite cache so each
(asset, day) pair is fetched at most once. Falls back to current price when
history is unavailable, and reports the valuation basis on every quote.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import config as _config

DB_PATH = _config.DB_PATH
COINGECKO = "https://api.coingecko.com/api/v3"

# symbol → CoinGecko coin id (extend freely; unknown symbols degrade gracefully)
SYMBOL_MAP: dict[str, str] = {
    "btc": "bitcoin", "eth": "ethereum", "trx": "tron", "sol": "solana",
    "bnb": "binancecoin", "matic": "matic-network", "pol": "matic-network",
    "arb": "arbitrum", "op": "optimism", "avax": "avalanche-2", "ftm": "fantom",
    "xrp": "ripple", "ada": "cardano", "dot": "polkadot", "atom": "cosmos",
    "ltc": "litecoin", "bch": "bitcoin-cash", "doge": "dogecoin", "xlm": "stellar",
    "near": "near", "ton": "the-open-network", "apt": "aptos", "sui": "sui",
    "algo": "algorand", "xmr": "monero", "zec": "zcash", "dash": "dash",
    "usdt": "tether", "usdc": "usd-coin", "dai": "dai", "busd": "binance-usd",
    "tusd": "true-usd", "usdd": "usdd", "weth": "weth", "wbtc": "wrapped-bitcoin",
    "steth": "staked-ether", "link": "chainlink", "uni": "uniswap", "aave": "aave",
    "shib": "shiba-inu", "pepe": "pepe", "etc": "ethereum-classic",
}
STABLECOINS = {"usdt", "usdc", "dai", "busd", "tusd", "usdd"}

_MIN_INTERVAL = 1.6  # seconds between CoinGecko calls (free-tier politeness)
_last_call = 0.0
# P4 fix: thread lock so concurrent callers don't all pass the throttle check
# simultaneously and under-throttle (tripping CoinGecko rate limits). The old
# module-level _last_call had no synchronization.
import threading as _threading
_THROTTLE_LOCK = _threading.Lock()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_price_tables() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS price_cache (
                coin_id    TEXT NOT NULL,
                date       TEXT NOT NULL,          -- YYYY-MM-DD ('' = spot)
                usd        REAL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (coin_id, date)
            );
            """
        )
        con.commit()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _throttle() -> None:
    global _last_call
    with _THROTTLE_LOCK:
        wait = _MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def _cache_get(coin_id: str, date: str, max_age_s: Optional[int] = None) -> Optional[float]:
    with _conn() as con:
        r = con.execute("SELECT usd, fetched_at FROM price_cache WHERE coin_id=? AND date=?",
                        (coin_id, date)).fetchone()
    if not r:
        return None
    if max_age_s is not None:  # spot prices expire; historical never do
        try:
            fetched = datetime.strptime(r["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - fetched).total_seconds() > max_age_s:
                return None
        except Exception:  # noqa: BLE001
            return None
    return r["usd"]


def _cache_set(coin_id: str, date: str, usd: Optional[float]) -> None:
    with _conn() as con:
        con.execute("INSERT OR REPLACE INTO price_cache (coin_id, date, usd, fetched_at) VALUES (?,?,?,?)",
                    (coin_id, date, usd, _now()))
        con.commit()


def resolve_coin_id(asset: str) -> Optional[str]:
    sym = (asset or "").strip().lower()
    # strip common wrappers like "USDT (TRC20)" / "ETH-mainnet"
    for sep in (" ", "(", "-", "/"):
        if sep in sym:
            sym = sym.split(sep, 1)[0]
    return SYMBOL_MAP.get(sym)


def historical_usd(asset: str, ts: Optional[int] = None) -> dict[str, Any]:
    """USD price of 1 unit of `asset` on the UTC day of `ts` (epoch). Cached permanently."""
    sym = (asset or "").strip().lower()
    if sym in STABLECOINS:
        return {"asset": asset, "usd": 1.0, "basis": "stablecoin_peg", "date": None}

    coin_id = resolve_coin_id(asset)
    if not coin_id:
        return {"asset": asset, "usd": None, "basis": "unsupported_asset", "date": None}

    if not ts:
        return spot_usd(asset)

    day = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    date_key = day.strftime("%Y-%m-%d")

    cached = _cache_get(coin_id, date_key)
    if cached is not None:
        return {"asset": asset, "usd": cached, "basis": "historical_close", "date": date_key, "cached": True}

    try:
        _throttle()
        resp = requests.get(f"{COINGECKO}/coins/{coin_id}/history",
                            params={"date": day.strftime("%d-%m-%Y"), "localization": "false"},
                            timeout=20)
        resp.raise_for_status()
        usd = (((resp.json().get("market_data") or {}).get("current_price") or {}).get("usd"))
        if usd is not None:
            _cache_set(coin_id, date_key, float(usd))
            return {"asset": asset, "usd": float(usd), "basis": "historical_close", "date": date_key}
    except Exception:  # noqa: BLE001
        pass

    # graceful fallback: spot price, clearly labeled
    spot = spot_usd(asset)
    spot["basis"] = "spot_fallback"
    spot["date"] = date_key
    return spot


def spot_usd(asset: str) -> dict[str, Any]:
    sym = (asset or "").strip().lower()
    if sym in STABLECOINS:
        return {"asset": asset, "usd": 1.0, "basis": "stablecoin_peg", "date": None}
    coin_id = resolve_coin_id(asset)
    if not coin_id:
        return {"asset": asset, "usd": None, "basis": "unsupported_asset", "date": None}
    cached = _cache_get(coin_id, "", max_age_s=15 * 60)
    if cached is not None:
        return {"asset": asset, "usd": cached, "basis": "spot", "date": None, "cached": True}
    try:
        _throttle()
        resp = requests.get(f"{COINGECKO}/simple/price",
                            params={"ids": coin_id, "vs_currencies": "usd"}, timeout=15)
        resp.raise_for_status()
        usd = (resp.json().get(coin_id) or {}).get("usd")
        if usd is not None:
            _cache_set(coin_id, "", float(usd))
            return {"asset": asset, "usd": float(usd), "basis": "spot", "date": None}
    except Exception:  # noqa: BLE001
        pass
    return {"asset": asset, "usd": None, "basis": "unavailable", "date": None}


def convert_batch(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """items: [{asset, amount, ts?}] → adds usd_at_time / unit price / basis per item."""
    out = []
    for it in items[:500]:
        asset = str(it.get("asset") or "")
        amount = float(it.get("amount") or 0)
        ts = it.get("ts")
        quote = historical_usd(asset, int(ts) if ts else None)
        usd_val = round(amount * quote["usd"], 2) if quote.get("usd") is not None else None
        out.append({**it, "unit_usd": quote.get("usd"), "usd_at_time": usd_val,
                    "basis": quote.get("basis"), "price_date": quote.get("date")})
    return out
