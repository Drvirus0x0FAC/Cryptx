#!/usr/bin/env python3
"""
crypto_osint.py — Cryptocurrency address OSINT module for Stage 08 bot.

Deterministic chain detection + free-API address intelligence:
  BTC         -> Blockstream.info          (no key)
  ETH         -> Etherscan (if key) else Blockchair
  TRX         -> Tronscan public API
  LTC/DOGE/
  BCH/XRP     -> Blockchair                (no key for basic info)
  Sanctions   -> Chainalysis public screening API (free, no key)

Env vars (all optional):
  ETHERSCAN_API_KEY     improves ETH detail + rate limits
  ETHPLORER_API_KEY     ETH fallback key; defaults to public "freekey"
  CRYPTO_HTTP_TIMEOUT   default 25 seconds
  CRYPTO_MAX_TXS        default 25 recent transactions
"""

import os
import re
import asyncio
import logging
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from html import escape
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiohttp


def _load_local_env() -> None:
    """Load .env when this module is imported outside FBOsinter.py."""
    for env_file in (os.getcwd(), os.path.dirname(__file__)):
        path = os.path.join(env_file, ".env")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("\"'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except Exception as exc:
            logging.getLogger("crypto_osint").warning(
                "Unable to load .env from %s: %s", path, exc
            )


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip().strip("\"'")


_load_local_env()

# Optional Arkham Intelligence integration (phase 3.5)
try:
    from arkham_osint import lookup_address as arkham_lookup
    from arkham_osint import format_arkham_section_html
    _ARKHAM_AVAILABLE = True
except ImportError:
    _ARKHAM_AVAILABLE = False
    async def arkham_lookup(address: str, chain: str = ""):  # type: ignore
        return None
    def format_arkham_section_html(arkham):  # type: ignore
        return ""

# Optional ScamSearch integration — reports crypto scam addresses
try:
    from scamsearch import search_exact as _scamsearch_lookup
    from scamsearch import format_scamsearch_html as _format_scamsearch_html
    _SCAMSEARCH_AVAILABLE = True
except ImportError:
    _SCAMSEARCH_AVAILABLE = False
    async def _scamsearch_lookup(value: str, search_type: str):  # type: ignore
        return None
    def _format_scamsearch_html(result):  # type: ignore
        return ""

# Optional DeBank integration — profile name + portfolio attribution
try:
    from debank_osint import lookup_address as debank_lookup
    from debank_osint import format_debank_section_html
    _DEBANK_AVAILABLE = True
except ImportError:
    _DEBANK_AVAILABLE = False
    async def debank_lookup(address: str, chain: str = ""):  # type: ignore
        return None
    def format_debank_section_html(debank):  # type: ignore
        return ""

log = logging.getLogger("crypto_osint")

ETHERSCAN_API_KEY   = _env("ETHERSCAN_API_KEY")
ETHPLORER_API_KEY   = _env("ETHPLORER_API_KEY", "freekey") or "freekey"
CHAINALYSIS_API_KEY = _env("CHAINALYSIS_API_KEY")  # optional
BLOCKCYPHER_TOKEN   = _env("BLOCKCYPHER_TOKEN")    # optional, improves BTC
HTTP_TIMEOUT        = int(_env("CRYPTO_HTTP_TIMEOUT", "25"))
MAX_TXS             = int(_env("CRYPTO_MAX_TXS", "25"))
CRYPTO_CACHE_TTL    = int(_env("CRYPTO_CACHE_TTL", "300"))
CRYPTO_API_CONCURRENCY = int(_env("CRYPTO_API_CONCURRENCY", "4"))
_CACHE_DIR          = (Path(__file__).resolve().parent / "reports" / ".api_cache").resolve()
_DOMAIN_SEMAPHORES: Dict[str, asyncio.Semaphore] = {}


def _cache_key(method: str, url: str, params: Optional[dict] = None, payload: Optional[dict] = None) -> Path:
    raw = json.dumps([method, url, params or {}, payload or {}], sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{digest}.json"


def _cache_get(path: Path) -> Optional[Any]:
    if CRYPTO_CACHE_TTL <= 0:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(data.get("saved_at", 0)) > CRYPTO_CACHE_TTL:
            return None
        return data.get("value")
    except Exception:
        return None


def _cache_set(path: Path, value: Any) -> None:
    if CRYPTO_CACHE_TTL <= 0:
        return
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"saved_at": time.time(), "value": value}, default=str), encoding="utf-8")
    except Exception as exc:
        log.debug("API cache write failed: %s", exc)


def _domain_semaphore(url: str) -> asyncio.Semaphore:
    domain = urlparse(url).netloc or "default"
    if domain not in _DOMAIN_SEMAPHORES:
        _DOMAIN_SEMAPHORES[domain] = asyncio.Semaphore(max(1, CRYPTO_API_CONCURRENCY))
    return _DOMAIN_SEMAPHORES[domain]

# ERC20 token contracts (Ethereum mainnet)
ERC20_CONTRACTS = {
    "USDT": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "USDC": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
}

# TRC20 token contracts (Tron mainnet)
TRC20_CONTRACTS = {
    "USDT": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    "USDC": "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8",
}

# =========================================================================
# Known mixer / tumbler / obfuscation infrastructure
# =========================================================================
KNOWN_MIXERS: Dict[str, Dict] = {
    # ── Tornado Cash (ETH / ERC20 pools) ─────────────────────────────────
    "0x12d66f87a04a9e220c9d2949b76397c4cf6a909b": {"name": "Tornado Cash 0.1 ETH",  "type": "mixer", "chain": "ETH"},
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936": {"name": "Tornado Cash 1 ETH",    "type": "mixer", "chain": "ETH"},
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": {"name": "Tornado Cash 10 ETH",   "type": "mixer", "chain": "ETH"},
    "0xa160cdab225685da1d56aa342ad8841c3b53f291": {"name": "Tornado Cash 100 ETH",  "type": "mixer", "chain": "ETH"},
    "0xd4b88df4d29f5cedd6857912842cff3b20c8cfa3": {"name": "Tornado Cash 100 DAI",  "type": "mixer", "chain": "ETH"},
    "0xfd8610d20aa15b7b2e3be39b396a1bc3516c7144": {"name": "Tornado Cash 1000 DAI", "type": "mixer", "chain": "ETH"},
    "0x07687e702b410fa43f4cb4af7fa097918ffd2730": {"name": "Tornado Cash 10K DAI",  "type": "mixer", "chain": "ETH"},
    "0x23773e65ed146a459667e82fea04097fe455e4b7": {"name": "Tornado Cash 100K DAI", "type": "mixer", "chain": "ETH"},
    "0x22aaa7720ddd5388a3c0a3333430953c68f1849b": {"name": "Tornado Cash cDAI",     "type": "mixer", "chain": "ETH"},
    "0x03893a7c7463ae47d46bc7f091665f1893656003": {"name": "Tornado Cash 5K cDAI",  "type": "mixer", "chain": "ETH"},
    "0x2717c5e28cf931547b621a5dddb772ab6a35b701": {"name": "Tornado Cash 50K cDAI", "type": "mixer", "chain": "ETH"},
    "0xd21be7248e0197ee08e0c20d4a96debdac3d20af": {"name": "Tornado Cash 500K cDAI","type": "mixer", "chain": "ETH"},
    "0x4736dcf1b7a3d580672cce6e7c65cd5cc9cfba9d": {"name": "Tornado Cash 100 USDC", "type": "mixer", "chain": "ETH"},
    "0xd96f2b1c14db8458374d9aca76e26c3950113464": {"name": "Tornado Cash 1000 USDC","type": "mixer", "chain": "ETH"},
    "0x169ad27a470d064dede56a2d3ff727986b15d52b": {"name": "Tornado Cash 100 USDT", "type": "mixer", "chain": "ETH"},
    "0x0836222f2b2b5a6a49a90e85a3cd0f373f5c73c9": {"name": "Tornado Cash 1000 USDT","type": "mixer", "chain": "ETH"},
    "0x178169b423a011fff22b9e3f3abea13414ddd0f1": {"name": "Tornado Cash WBTC",     "type": "mixer", "chain": "ETH"},
    "0x610b717796ad172b316836ac5a2fffa0ab1aa1a5": {"name": "Tornado Cash WBTC",     "type": "mixer", "chain": "ETH"},
    "0xbb93e510bbcd0b7beb5a853875f9ec60275cf498": {"name": "Tornado Cash WBTC",     "type": "mixer", "chain": "ETH"},
    # Tornado Cash router / relayer infrastructure
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b": {"name": "Tornado Cash Router",   "type": "mixer", "chain": "ETH"},
    "0x722122df12d4e14e13ac3b6895a86e84145b6967": {"name": "Tornado Cash Proxy",    "type": "mixer", "chain": "ETH"},

    # ── Tornado Cash on BSC ───────────────────────────────────────────────
    "0x84443cfd09a48af6ef360c6976c5392ac5023a1f": {"name": "Tornado Cash BSC 0.1 BNB",  "type": "mixer", "chain": "BSC"},
    "0xd47438c816c9e7f2e2888a5c0cb69bf3388aed4b": {"name": "Tornado Cash BSC 1 BNB",    "type": "mixer", "chain": "BSC"},
    "0x330bdfade01ee9bf63c209ee33102dd334618e0a": {"name": "Tornado Cash BSC 10 BNB",   "type": "mixer", "chain": "BSC"},
    "0x1e34a77868e19a6647b1f2f47b51ed72dede95dd": {"name": "Tornado Cash BSC 100 BNB",  "type": "mixer", "chain": "BSC"},

    # ── eXch (ETH no-KYC swap) ────────────────────────────────────────────
    "0x0000000000a84d1a9b0063a910315c7ffa9cd248": {"name": "eXch Exchange",         "type": "no_kyc_swap", "chain": "ETH"},

    # ── FixedFloat ────────────────────────────────────────────────────────
    "0xfbe89d6e7e7dad658fcb87fdfe3e4dff81d01d2a": {"name": "FixedFloat",            "type": "no_kyc_swap", "chain": "ETH"},

    # ── Bitcoin mixing patterns (addresses known from blockchain analysis) ─
    "1CWUFsS73PFPJxK6TcqZZc7eN5yzNQm8bN": {"name": "Bitcoin Fog (historical)",  "type": "mixer", "chain": "BTC"},
    "1KUUJPkyDhamZXgpsyXqNGc3x1QPXtdhgz": {"name": "Helix Mixer (historical)",  "type": "mixer", "chain": "BTC"},

    # ── Sinbad.io (BTC mixer, OFAC sanctioned Nov 2023) ──────────────────
    "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh": {"name": "Sinbad.io",          "type": "mixer", "chain": "BTC"},

    # ── Chipmixer (seized Feb 2023) ───────────────────────────────────────
    "bc1q5shngj24323nsrmxv99652zqqvcpxszqp86wm4": {"name": "ChipMixer",           "type": "mixer", "chain": "BTC"},

    # ── Wasabi Wallet CoinJoin coordinator ───────────────────────────────
    "bc1qs604c7jv6amk4cxqlnvuxv26hv3e48cds4m0ew": {"name": "Wasabi Wallet CoinJoin", "type": "coinjoin", "chain": "BTC"},
    "bc1qa24tsgchvuxsoen6rs5pkj5b4e8qk8e62awqm4": {"name": "Wasabi Wallet CoinJoin", "type": "coinjoin", "chain": "BTC"},

    # ── JoinMarket coordinator ───────────────────────────────────────────
    "3PfcrxHCiem7qCFkqAN7oMqnSfnCAPMKdW": {"name": "JoinMarket",               "type": "coinjoin", "chain": "BTC"},
}

# Normalise all mixer keys to lowercase for case-insensitive matching
KNOWN_MIXERS = {k.lower(): v for k, v in KNOWN_MIXERS.items()}


# =========================================================================
# Known chain-hopping bridges and chain-swapping routers
# =========================================================================
KNOWN_BRIDGES: Dict[str, Dict[str, str]] = {
    "0x3ee18b2214aff97000d974cf647e7c347e8fa585": {"name": "Wormhole: ETH", "type": "bridge", "chain": "ETH"},
    "0x40ec5b33f54e0e8a33a975908c5ba1c14e5bbbdf": {"name": "Polygon PoS Bridge", "type": "bridge", "chain": "ETH"},
    "0xa0c68c638235ee32657e8f720e23cec1bfc77c77": {"name": "Polygon Bridge", "type": "bridge", "chain": "ETH"},
    "0x3014ca10b91cb3d0ad85fef7a3cb95bcac9c0f79": {"name": "Polygon Bridge", "type": "bridge", "chain": "ETH"},
    "0x99c9fc46f92e8a1c0dec1b1747d010903e884be1": {"name": "Optimism Gateway", "type": "bridge", "chain": "ETH"},
    "0x4dbd4fc535ac27206064b68ffcf827b0a60bab3f": {"name": "Arbitrum Delayed Inbox", "type": "bridge", "chain": "ETH"},
    "0x011b6e24ffb0b5f5fcc564cf4183c5bbbc96d515": {"name": "Across Bridge", "type": "bridge", "chain": "ETH"},
    "0x5427fefa711eff984124bfbb1ab6fbf5e3da1820": {"name": "Synapse Bridge", "type": "bridge", "chain": "ETH"},
    "0x2796317b0ff8538f253012862c06787adfb8ceb6": {"name": "Synapse Bridge v2", "type": "bridge", "chain": "ETH"},
    "0x737b7867d945e5c24ba47cfa5d68e4b0de230550": {"name": "Ronin Bridge", "type": "bridge", "chain": "ETH"},
    "0x8731d54e9d02c286767d56ac03e8037c07e01e98": {"name": "Stargate Router", "type": "bridge", "chain": "ETH"},
    "0x00000000006c3852cbef3e08e8df289169ede581": {"name": "Seaport", "type": "marketplace_router", "chain": "ETH"},
    "tlmvixq5bscidfbxgatu1fwe7wfa1rdowu": {"name": "Sun.io Bridge", "type": "bridge", "chain": "TRX"},
}

KNOWN_DEX_ROUTERS: Dict[str, Dict[str, str]] = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": {"name": "Uniswap V2 Router", "type": "dex_router", "chain": "ETH"},
    "0xe592427a0aece92de3edee1f18e0157c05861564": {"name": "Uniswap V3 Router", "type": "dex_router", "chain": "ETH"},
    "0x68b3465833fb72e5f1d90e5f2408e5f2408e5f": {"name": "Uniswap Router", "type": "dex_router", "chain": "ETH"},
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": {"name": "Uniswap Universal Router", "type": "dex_router", "chain": "ETH"},
    "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b": {"name": "Uniswap Universal Router 2", "type": "dex_router", "chain": "ETH"},
    "0x1111111254eeb25477b68fb85ed929f73a960582": {"name": "1inch V5 Router", "type": "swap_aggregator", "chain": "ETH"},
    "0x1111111254fb6c44bac0bed2854e76f90643097d": {"name": "1inch V4 Router", "type": "swap_aggregator", "chain": "ETH"},
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": {"name": "0x Exchange Proxy", "type": "swap_aggregator", "chain": "ETH"},
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": {"name": "SushiSwap Router", "type": "dex_router", "chain": "ETH"},
    "0x10ed43c718714eb63d5aa57b78b54704e256024e": {"name": "PancakeSwap V2 Router", "type": "dex_router", "chain": "BSC"},
}

KNOWN_BRIDGES = {k.lower(): v for k, v in KNOWN_BRIDGES.items()}
KNOWN_DEX_ROUTERS = {k.lower(): v for k, v in KNOWN_DEX_ROUTERS.items()}


def check_mixer_interactions(tx_list: list, address: str) -> List[Dict]:
    """
    Cross-reference every tx counterparty against KNOWN_MIXERS.
    Returns a list of hit records with mixer metadata.
    """
    hits = []
    seen = set()
    for tx in tx_list:
        for field in ("from", "to", "hash"):
            counterparty = (tx.get(field) or "").lower()
            if counterparty and counterparty in KNOWN_MIXERS and counterparty not in seen:
                seen.add(counterparty)
                hits.append({
                    "counterparty": counterparty,
                    "mixer_name":   KNOWN_MIXERS[counterparty]["name"],
                    "mixer_type":   KNOWN_MIXERS[counterparty]["type"],
                    "chain":        KNOWN_MIXERS[counterparty]["chain"],
                    "tx_hash":      tx.get("hash") or tx.get("txid") or "",
                    "direction":    tx.get("direction", ""),
                    "time":         tx.get("time", ""),
                })
    return hits


def detect_chain_hopping_and_swaps(tx_list: list, address: str) -> Dict[str, Any]:
    """
    Deterministically flag bridge/router/swap interactions from fetched TX rows.
    This does not prove a completed cross-chain hop by itself; it surfaces
    evidence that should be investigated as possible chain-hopping/layering.
    """
    bridge_hits: List[Dict[str, Any]] = []
    swap_hits: List[Dict[str, Any]] = []
    seen = set()
    infrastructure = {**KNOWN_BRIDGES, **KNOWN_DEX_ROUTERS}
    for tx in tx_list or []:
        tx_hash = tx.get("hash") or tx.get("txid") or tx.get("transactionHash") or ""
        direction = tx.get("direction") or ""
        token = tx.get("token") or ""
        value = tx.get("value") or tx.get("value_eth") or tx.get("value_trx") or tx.get("delta_btc") or ""
        for field in ("from", "to"):
            counterparty = (tx.get(field) or "").strip().lower()
            if not counterparty or counterparty not in infrastructure:
                continue
            meta = infrastructure[counterparty]
            key = (counterparty, tx_hash, field)
            if key in seen:
                continue
            seen.add(key)
            hit = {
                "counterparty": counterparty,
                "name": meta["name"],
                "type": meta["type"],
                "chain": meta["chain"],
                "tx_hash": tx_hash,
                "direction": direction,
                "side": field,
                "time": tx.get("time", ""),
                "token": token,
                "value": value,
            }
            if meta["type"] == "bridge":
                bridge_hits.append(hit)
            else:
                swap_hits.append(hit)

    tx_tokens = {
        str(tx.get("token") or "").upper()
        for tx in tx_list or []
        if tx.get("token")
    }
    heuristic_flags = []
    if len(tx_tokens) >= 3:
        heuristic_flags.append({
            "type": "multi_token_activity",
            "severity": "medium",
            "evidence": f"Fetched activity includes {len(tx_tokens)} distinct tokens: {', '.join(sorted(tx_tokens)[:8])}",
        })
    if bridge_hits and swap_hits:
        heuristic_flags.append({
            "type": "bridge_plus_swap_layering",
            "severity": "high",
            "evidence": "Wallet has both bridge infrastructure and swap/router interactions in fetched activity.",
        })

    risk_level = "clean"
    if bridge_hits and swap_hits:
        risk_level = "high"
    elif bridge_hits or swap_hits or heuristic_flags:
        risk_level = "medium"

    return {
        "bridge_hits": bridge_hits,
        "swap_hits": swap_hits,
        "bridge_count": len(bridge_hits),
        "swap_count": len(swap_hits),
        "heuristics": heuristic_flags,
        "possible_chain_hopping": bool(bridge_hits),
        "possible_chain_swapping": bool(swap_hits),
        "risk_level": risk_level,
    }


# =========================================================================
# Chain detection (order matters — most specific first)
# =========================================================================
_CHAIN_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("ETH",  re.compile(r"^0x[a-fA-F0-9]{40}$")),
    ("BTC",  re.compile(r"^(bc1[a-zA-HJ-NP-Z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")),
    ("LTC",  re.compile(r"^(ltc1[a-zA-HJ-NP-Z0-9]{25,87}|[LM][a-km-zA-HJ-NP-Z1-9]{25,34})$")),
    ("DOGE", re.compile(r"^D[5-9A-HJ-NP-U][1-9A-HJ-NP-Za-km-z]{32}$")),
    ("BCH",  re.compile(r"^(bitcoincash:)?[qp][a-z0-9]{41}$")),
    ("TRX",  re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")),
    ("XRP",  re.compile(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$")),
    ("SOL",  re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")),  # catch-all base58
]


def detect_chain(address: str) -> Optional[str]:
    a = (address or "").strip()
    for chain, pat in _CHAIN_PATTERNS:
        if pat.match(a):
            return chain
    return None


# =========================================================================
# HTTP helper
# =========================================================================
async def _http_get_json(url: str, params: Optional[dict] = None,
                         headers: Optional[dict] = None) -> Optional[dict]:
    cache_path = _cache_key("GET", url, params=params)
    cached = _cache_get(cache_path)
    if cached is not None:
        return cached
    try:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with _domain_semaphore(url):
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(url, params=params, headers=headers) as r:
                    if r.status != 200:
                        log.warning("HTTP %s on %s", r.status, url)
                        return None
                    data = await r.json()
                    _cache_set(cache_path, data)
                    return data
    except asyncio.TimeoutError:
        log.warning("HTTP timeout on %s", url)
    except Exception as e:
        log.warning("HTTP error %s: %s", url, e)
    return None


async def _http_post_json(url: str, payload: dict,
                           headers: Optional[dict] = None) -> Optional[dict]:
    """HTTP POST helper — used for JSON-RPC endpoints (Solana, etc.)."""
    cache_path = _cache_key("POST", url, payload=payload)
    cached = _cache_get(cache_path)
    if cached is not None:
        return cached
    try:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with _domain_semaphore(url):
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(url, json=payload, headers=headers) as r:
                    if r.status != 200:
                        log.warning("HTTP POST %s on %s", r.status, url)
                        return None
                    data = await r.json(content_type=None)
                    _cache_set(cache_path, data)
                    return data
    except asyncio.TimeoutError:
        log.warning("HTTP POST timeout on %s", url)
    except Exception as e:
        log.warning("HTTP POST error %s: %s", url, e)
    return None


def _fmt_ts(epoch: Optional[float]) -> str:
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ""


def _num(v: Any, default: float = 0.0) -> float:
    """Safe numeric conversion — API fields may come back as str or None."""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _etherscan_error(data: Optional[dict], *, allow_no_transactions: bool = False) -> str:
    """Return a human-readable Etherscan API error, or empty string on usable data."""
    if not data:
        return "empty response"
    status = str(data.get("status", ""))
    result = data.get("result")
    message = str(data.get("message", ""))
    result_text = str(result)
    if allow_no_transactions and "No transactions found" in result_text:
        return ""
    if status == "0" and message.upper() == "NOTOK":
        return result_text or message
    if isinstance(result, str) and not result.isdigit() and result_text:
        return result_text
    return ""


# =========================================================================
# BTC — BlockCypher (with token) or Blockstream fallback
# =========================================================================
async def lookup_btc(address: str) -> Dict[str, Any]:
    if BLOCKCYPHER_TOKEN:
        return await _lookup_btc_blockcypher(address)
    return await _lookup_btc_blockstream(address)


async def _lookup_btc_blockcypher(address: str) -> Dict[str, Any]:
    """BlockCypher provides richer TX detail + confidence scores."""
    params: Dict[str, Any] = {"limit": MAX_TXS, "token": BLOCKCYPHER_TOKEN}
    data = await _http_get_json(
        f"https://api.blockcypher.com/v1/btc/main/addrs/{address}/full", params
    )
    if not data:
        return await _lookup_btc_blockstream(address)  # fallback

    balance_sat    = _num(data.get("balance"))
    total_recv_sat = _num(data.get("total_received"))
    tx_count       = _int(data.get("n_tx"))
    tx_list = []
    for t in (data.get("txs") or [])[:MAX_TXS]:
        received = sum(_num(o.get("value")) for o in (t.get("outputs") or [])
                       if address in (o.get("addresses") or []))
        sent     = sum(_num(i.get("output_value")) for i in (t.get("inputs") or [])
                       if address in (i.get("addresses") or []))
        direction = "OUT" if sent > received else "IN"
        delta_btc = (received - sent) / 1e8
        confirmed = t.get("confirmations", 0) > 0
        tx_list.append({
            "txid":       t.get("hash", ""),
            "time":       _fmt_ts(
                datetime.strptime(t["confirmed"], "%Y-%m-%dT%H:%M:%SZ").timestamp()
                if t.get("confirmed") else None
            ),
            "direction":  direction,
            "delta_btc":  round(delta_btc, 8),
            "confirmations": t.get("confirmations", 0),
            "confirmed":  confirmed,
        })

    return {
        "chain":          "BTC",
        "address":        address,
        "balance":        round(balance_sat / 1e8, 8),
        "balance_unit":   "BTC",
        "total_received": round(total_recv_sat / 1e8, 8),
        "tx_count":       tx_count,
        "first_seen":     tx_list[-1]["time"] if tx_list else "",
        "last_seen":      tx_list[0]["time"]  if tx_list else "",
        "recent_txs":     tx_list,
        "mixer_hits":     check_mixer_interactions(tx_list, address),
        "explorer":       f"https://www.blockchain.com/btc/address/{address}",
        "source":         "blockcypher",
    }


async def _lookup_btc_blockstream(address: str) -> Dict[str, Any]:
    base = "https://blockstream.info/api"
    addr = await _http_get_json(f"{base}/address/{address}")
    if not addr:
        return {"chain": "BTC", "address": address, "error": "Blockstream API unavailable"}

    stats = addr.get("chain_stats", {}) or {}
    mempool = addr.get("mempool_stats", {}) or {}
    funded = _num(stats.get("funded_txo_sum")) + _num(mempool.get("funded_txo_sum"))
    spent  = _num(stats.get("spent_txo_sum"))  + _num(mempool.get("spent_txo_sum"))
    tx_cnt = _int(stats.get("tx_count")) + _int(mempool.get("tx_count"))

    balance_btc        = (funded - spent) / 1e8
    total_received_btc = funded / 1e8

    txs_raw = await _http_get_json(f"{base}/address/{address}/txs") or []
    tx_list = []
    for t in txs_raw[:MAX_TXS]:
        bt = t.get("status", {}).get("block_time")
        vout_total = sum(_num(v.get("value")) for v in t.get("vout", []))
        # Determine if this address was credited or debited in this tx
        credited = sum(_num(v.get("value")) for v in t.get("vout", [])
                       if v.get("scriptpubkey_address") == address)
        debited = sum(_num((v.get("prevout") or {}).get("value")) for v in t.get("vin", [])
                      if (v.get("prevout") or {}).get("scriptpubkey_address") == address)
        direction = "IN" if credited > debited else "OUT"
        delta = (credited - debited) / 1e8
        tx_list.append({
            "txid": t.get("txid", ""),
            "time": _fmt_ts(bt),
            "direction": direction,
            "delta_btc": round(delta, 8),
            "total_out_btc": round(vout_total / 1e8, 8),
            "confirmed": t.get("status", {}).get("confirmed", False),
        })

    first_seen = tx_list[-1]["time"] if tx_list else ""
    last_seen  = tx_list[0]["time"] if tx_list else ""

    return {
        "chain": "BTC",
        "address": address,
        "balance": round(balance_btc, 8),
        "balance_unit": "BTC",
        "total_received": round(total_received_btc, 8),
        "tx_count": tx_cnt,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "recent_txs": tx_list,
        "mixer_hits": check_mixer_interactions(tx_list, address),
        "explorer": f"https://blockstream.info/address/{address}",
        "source": "blockstream.info",
    }


# =========================================================================
# ETH — Etherscan V2 (multi-chain: ETH mainnet + Polygon auto-detect)
# =========================================================================

# Etherscan V2 supported chain IDs and their labels
ETHERSCAN_CHAINS = {
    1:   {"label": "ETH",     "unit": "ETH",   "explorer": "https://etherscan.io"},
    137: {"label": "MATIC",   "unit": "MATIC", "explorer": "https://polygonscan.com"},
    56:  {"label": "BSC",     "unit": "BNB",   "explorer": "https://bscscan.com"},
    42161: {"label": "ARB",   "unit": "ETH",   "explorer": "https://arbiscan.io"},
    10:  {"label": "OP",      "unit": "ETH",   "explorer": "https://optimistic.etherscan.io"},
    8453: {"label": "BASE",   "unit": "ETH",   "explorer": "https://basescan.org"},
}


async def lookup_eth(address: str) -> Dict[str, Any]:
    if ETHERSCAN_API_KEY:
        return await _lookup_eth_etherscan_multichain(address)
    return await _lookup_eth_keyless(address)


async def _lookup_eth_keyless(address: str) -> Dict[str, Any]:
    """
    Ethereum fallback when no Etherscan key is configured.

    Blockchair's ETH dashboard can return empty/zero address data for some
    high-profile/token-heavy wallets. Ethplorer's public API is a better
    no-key fallback for ETH balances, token balances, and recent history.
    """
    ethplorer = await _lookup_eth_ethplorer(address)
    if ethplorer and not ethplorer.get("error"):
        return ethplorer
    blockchair = await _lookup_blockchair("ethereum", address, unit="ETH")
    if ethplorer and ethplorer.get("error") and not blockchair.get("error"):
        blockchair["fallback_warning"] = ethplorer.get("error")
    return blockchair


async def _detect_active_chain(address: str) -> int:
    """
    Query ETH mainnet + Polygon + BSC + Arbitrum + Base concurrently.
    Return the chainid with the most transactions — that's where this address lives.
    Falls back to chainid=1 (ETH mainnet) if nothing found.
    """
    base = "https://api.etherscan.io/v2/api"

    async def _tx_count(chainid: int) -> tuple:
        data = await _http_get_json(base, {
            "chainid": chainid,
            "module": "account", "action": "txlist",
            "address": address,
            "page": 1, "offset": 5, "sort": "desc",
            "apikey": ETHERSCAN_API_KEY,
        })
        result = (data or {}).get("result", [])
        count = len(result) if isinstance(result, list) else 0
        return chainid, count

    results = await asyncio.gather(*[_tx_count(cid) for cid in ETHERSCAN_CHAINS])
    best_chain, best_count = max(results, key=lambda x: x[1])
    return best_chain if best_count > 0 else 1


async def _lookup_eth_etherscan_multichain(address: str) -> Dict[str, Any]:
    # Auto-detect which chain has activity
    chainid = await _detect_active_chain(address)
    result = await _lookup_eth_etherscan(address, chainid)
    if result.get("error") and chainid == 1:
        fallback = await _lookup_eth_keyless(address)
        fallback["fallback_warning"] = result.get("error")
        return fallback
    return result


async def _lookup_eth_etherscan(address: str, chainid: int = 1) -> Dict[str, Any]:
    chain_info = ETHERSCAN_CHAINS.get(chainid, ETHERSCAN_CHAINS[1])
    chain_label = chain_info["label"]
    unit        = chain_info["unit"]
    explorer    = chain_info["explorer"]

    base = "https://api.etherscan.io/v2/api"
    bal = await _http_get_json(base, {
        "chainid": chainid,
        "module": "account", "action": "balance",
        "address": address, "tag": "latest",
        "apikey": ETHERSCAN_API_KEY,
    })
    txs = await _http_get_json(base, {
        "chainid": chainid,
        "module": "account", "action": "txlist",
        "address": address, "startblock": 0, "endblock": 99999999,
        "page": 1, "offset": MAX_TXS, "sort": "desc",
        "apikey": ETHERSCAN_API_KEY,
    })
    bal_error = _etherscan_error(bal)
    tx_error = _etherscan_error(txs, allow_no_transactions=True)
    if bal_error or tx_error:
        return {
            "chain": chain_label,
            "address": address,
            "error": "Etherscan API error: " + "; ".join(
                p for p in (f"balance={bal_error}" if bal_error else "",
                            f"txlist={tx_error}" if tx_error else "") if p
            ),
            "explorer": f"{explorer}/address/{address}",
            "source": f"etherscan-v2 (chain {chainid})",
            "chainid": chainid,
        }

    balance_wei = _num((bal or {}).get("result"))
    balance_eth = balance_wei / 1e18

    raw_txs = (txs or {}).get("result", [])
    tx_list = []
    if isinstance(raw_txs, list):
        for t in raw_txs:
            ts = _fmt_ts(_num(t.get("timeStamp")))
            val_eth = _num(t.get("value")) / 1e18
            direction = "OUT" if t.get("from", "").lower() == address.lower() else "IN"
            tx_list.append({
                "hash": t.get("hash", ""),
                "time": ts,
                "from": t.get("from", ""),
                "to": t.get("to", ""),
                "value_eth": round(val_eth, 8),
                "direction": direction,
                "is_error": t.get("isError") == "1",
            })
    else:
        message = (txs or {}).get("message") or (txs or {}).get("result") or "Etherscan txlist unavailable"
        return {
            "chain": chain_label,
            "address": address,
            "error": f"Etherscan API error: {message}",
            "explorer": f"{explorer}/address/{address}",
            "source": f"etherscan-v2 (chain {chainid})",
            "chainid": chainid,
        }

    # ── ERC20 token balances (USDT, USDC) ────────────────────────────────────
    tokens = []
    for symbol, contract in ERC20_CONTRACTS.items():
        tok_bal = await _http_get_json(base, {
            "chainid": chainid,
            "module": "account", "action": "tokenbalance",
            "contractaddress": contract,
            "address": address, "tag": "latest",
            "apikey": ETHERSCAN_API_KEY,
        })
        raw = _num((tok_bal or {}).get("result"))
        if raw > 0:
            decimals = 6
            tokens.append({
                "symbol": symbol,
                "balance": round(raw / (10 ** decimals), 4),
                "contract": contract,
            })

    # ── All ERC20 token transfers (any token, recent activity) ───────────────
    token_txs = []
    erc20_all = await _http_get_json(base, {
        "chainid": chainid,
        "module": "account", "action": "tokentx",
        "address": address,
        "page": 1, "offset": MAX_TXS, "sort": "desc",
        "apikey": ETHERSCAN_API_KEY,
    })
    erc20_error = _etherscan_error(erc20_all, allow_no_transactions=True)
    erc20_rows = [] if erc20_error else ((erc20_all or {}).get("result", []) or [])
    for t in erc20_rows:
        direction = "OUT" if t.get("from", "").lower() == address.lower() else "IN"
        decimals  = _int(t.get("tokenDecimal"), 6)
        value     = _num(t.get("value")) / (10 ** max(decimals, 1))
        token_txs.append({
            "hash":      t.get("hash", ""),
            "time":      _fmt_ts(_num(t.get("timeStamp"))),
            "token":     t.get("tokenSymbol", "?"),
            "from":      t.get("from", ""),
            "to":        t.get("to", ""),
            "value":     round(value, 4),
            "direction": direction,
        })

    token_txs.sort(key=lambda x: x["time"], reverse=True)
    token_txs = token_txs[:MAX_TXS]
    activity_hashes = {
        str(t.get("hash") or "")
        for t in (tx_list + token_txs)
        if t.get("hash")
    }
    activity_count = len(activity_hashes) or len(tx_list) or len(token_txs)
    activity_txs = tx_list or token_txs

    return {
        "chain":        chain_label,
        "address":      address,
        "balance":      round(balance_eth, 8),
        "balance_unit": unit,
        "tx_count":     activity_count,
        "native_tx_count": len(tx_list),
        "token_tx_count":  len(token_txs),
        "first_seen":   activity_txs[-1]["time"] if activity_txs else "",
        "last_seen":    activity_txs[0]["time"]  if activity_txs else "",
        "recent_txs":   tx_list,
        "tokens":       tokens,
        "token_txs":    token_txs,
        "mixer_hits":   check_mixer_interactions(tx_list + token_txs, address),
        "explorer":     f"{explorer}/address/{address}",
        "source":       f"etherscan-v2 (chain {chainid})",
        "chainid":      chainid,
        "fallback_warning": f"ERC20 txlist unavailable: {erc20_error}" if erc20_error else "",
    }


async def _lookup_eth_ethplorer(address: str) -> Dict[str, Any]:
    """Keyless Ethereum fallback via Ethplorer public API."""
    base = "https://api.ethplorer.io"
    params = {"apiKey": ETHPLORER_API_KEY}
    info, history = await asyncio.gather(
        _http_get_json(f"{base}/getAddressInfo/{address}", params),
        _http_get_json(
            f"{base}/getAddressHistory/{address}",
            {"apiKey": ETHPLORER_API_KEY, "limit": MAX_TXS},
        ),
    )
    if not info or info.get("error"):
        err = info.get("error", {}).get("message") if isinstance(info, dict) else ""
        return {"chain": "ETH", "address": address, "error": err or "Ethplorer API unavailable"}

    eth = info.get("ETH") or {}
    balance_eth = _num(eth.get("balance"))
    tx_count = _int(info.get("countTxs"))

    tokens = []
    portfolio_usd = _num(eth.get("price", {}).get("rate")) * balance_eth
    for tok in (info.get("tokens") or [])[:100]:
        token_info = tok.get("tokenInfo") or {}
        decimals = _int(token_info.get("decimals"), 0)
        raw_balance = tok.get("rawBalance", tok.get("balance"))
        token_balance = _num(raw_balance) / (10 ** decimals) if decimals else _num(tok.get("balance"))
        if token_balance <= 0:
            continue
        price = token_info.get("price") or {}
        rate = _num(price.get("rate"))
        usd_value = token_balance * rate if rate else None
        if usd_value:
            portfolio_usd += usd_value
        tokens.append({
            "symbol": token_info.get("symbol", ""),
            "name": token_info.get("name", ""),
            "balance": round(token_balance, 6),
            "contract": token_info.get("address", ""),
            "usd_value": round(usd_value, 2) if usd_value else None,
        })

    tx_list = []
    hist_rows = []
    if isinstance(history, list):
        hist_rows = history
    elif isinstance(history, dict):
        hist_rows = history.get("operations") or history.get("result") or []

    for t in hist_rows[:MAX_TXS]:
        ts = _fmt_ts(_num(t.get("timestamp") or t.get("timeStamp") or t.get("time")))
        from_addr = t.get("from") or ""
        to_addr = t.get("to") or ""
        direction = "OUT" if from_addr.lower() == address.lower() else "IN"
        token_info = t.get("tokenInfo") or {}
        token = token_info.get("symbol") or t.get("symbol") or "ETH"
        decimals = _int(token_info.get("decimals"), 18 if token == "ETH" else 0)
        raw_value = t.get("value", 0)
        value = _num(raw_value) / (10 ** decimals) if decimals else _num(raw_value)
        tx_list.append({
            "hash": t.get("transactionHash") or t.get("hash") or "",
            "time": ts,
            "from": from_addr,
            "to": to_addr,
            "value_eth": round(value, 8) if token == "ETH" else 0,
            "value": round(value, 8),
            "token": token,
            "direction": direction,
        })

    first_seen = tx_list[-1]["time"] if tx_list else ""
    last_seen = tx_list[0]["time"] if tx_list else ""

    return {
        "chain": "ETH",
        "address": address,
        "balance": round(balance_eth, 8),
        "balance_unit": "ETH",
        "portfolio_usd": round(portfolio_usd, 2) if portfolio_usd else None,
        "tx_count": tx_count or len(tx_list),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "recent_txs": tx_list,
        "tokens": tokens,
        "token_txs": tx_list,
        "mixer_hits": check_mixer_interactions(tx_list, address),
        "explorer": f"https://etherscan.io/address/{address}",
        "source": "ethplorer",
    }


# =========================================================================
# TRX — Tronscan public API (USDT-TRC20 tokens included)
# =========================================================================
async def lookup_trx(address: str) -> Dict[str, Any]:
    base = "https://apilist.tronscanapi.com/api"
    info = await _http_get_json(f"{base}/account", {"address": address})
    if not info:
        return {"chain": "TRX", "address": address, "error": "Tronscan API unavailable"}

    balance_trx = _num(info.get("balance")) / 1e6

    # TRC20 tokens (USDT, USDC, etc.)
    tokens = []
    for tok in (info.get("trc20token_balances") or []):
        raw_bal = _num(tok.get("balance"))
        decimals = _int(tok.get("tokenDecimal"), 6)
        human = raw_bal / (10 ** decimals) if decimals else raw_bal
        tokens.append({
            "symbol": tok.get("tokenAbbr", ""),
            "name": tok.get("tokenName", ""),
            "balance": human,
            "contract": tok.get("tokenId", ""),
        })

    # Recent transactions
    txs_raw = await _http_get_json(f"{base}/transaction", {
        "address": address, "limit": MAX_TXS, "start": 0, "sort": "-timestamp",
    })
    tx_list = []
    for t in (txs_raw or {}).get("data", []) or []:
        ts_ms = _num(t.get("timestamp"))
        ts = _fmt_ts(ts_ms / 1000) if ts_ms else ""
        amt_sun = _num(t.get("amount"))
        owner = t.get("ownerAddress", "")
        direction = "OUT" if owner == address else "IN"
        tx_list.append({
            "hash": t.get("hash", ""),
            "time": ts,
            "from": owner,
            "to": t.get("toAddress", ""),
            "value_trx": round(amt_sun / 1e6, 6),
            "direction": direction,
            "type": t.get("contractType", ""),
        })

    first_seen = _fmt_ts(_num(info.get("date_created")) / 1000)
    last_seen  = tx_list[0]["time"] if tx_list else ""

    return {
        "chain": "TRX",
        "address": address,
        "balance": round(balance_trx, 6),
        "balance_unit": "TRX",
        "tx_count": _int(info.get("totalTransactionCount")),
        "tokens": tokens,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "recent_txs": tx_list,
        "explorer": f"https://tronscan.org/#/address/{address}",
        "source": "tronscan",
    }


# =========================================================================
# SOL — Solana mainnet JSON-RPC (no API key required)
# =========================================================================
_SOL_RPC           = "https://api.mainnet-beta.solana.com"
_SOL_RPC_HEADERS   = {"Content-Type": "application/json"}
_SOL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
# Well-known SPL token mints
_SOL_TOKEN_LABELS: Dict[str, str] = {
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "So11111111111111111111111111111111111111112":    "wSOL",
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": "ETH",   # Wormhole ETH
    "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh": "WBTC",  # Wormhole BTC
}


async def lookup_sol(address: str) -> Dict[str, Any]:
    """
    Query the Solana mainnet JSON-RPC for account balance, recent signatures,
    and SPL token holdings. Falls back to Blockchair if the RPC is unavailable.
    """
    rpc = _SOL_RPC
    hdrs = _SOL_RPC_HEADERS

    # Fire all three RPC calls concurrently
    bal_resp, sigs_resp, tok_resp = await asyncio.gather(
        _http_post_json(rpc, {
            "jsonrpc": "2.0", "id": 1,
            "method": "getBalance",
            "params": [address],
        }, headers=hdrs),
        _http_post_json(rpc, {
            "jsonrpc": "2.0", "id": 2,
            "method": "getSignaturesForAddress",
            "params": [address, {"limit": MAX_TXS}],
        }, headers=hdrs),
        _http_post_json(rpc, {
            "jsonrpc": "2.0", "id": 3,
            "method": "getTokenAccountsByOwner",
            "params": [
                address,
                {"programId": _SOL_TOKEN_PROGRAM},
                {"encoding": "jsonParsed"},
            ],
        }, headers=hdrs),
    )

    # ── Balance ──────────────────────────────────────────────────────────────
    lamports = 0
    if bal_resp and "result" in bal_resp:
        lamports = _int((bal_resp["result"] or {}).get("value", 0))
    balance_sol = lamports / 1e9

    if not bal_resp and not sigs_resp:
        # RPC completely unreachable — fall back to Blockchair
        log.warning("Solana RPC unreachable, falling back to Blockchair")
        return await _lookup_blockchair("solana", address, unit="SOL")

    # ── Recent transactions (signatures only — no per-tx detail fetch) ────────
    tx_list = []
    sigs = (sigs_resp or {}).get("result") or []
    for sig in sigs[:MAX_TXS]:
        block_time = sig.get("blockTime")
        tx_list.append({
            "hash":      sig.get("signature", ""),
            "time":      _fmt_ts(block_time) if block_time else "",
            "direction": "",            # direction needs full tx parse — not available here
            "confirmed": sig.get("confirmationStatus") in ("finalized", "confirmed"),
            "error":     sig.get("err") is not None,
        })

    # ── SPL token balances ────────────────────────────────────────────────────
    tokens = []
    tok_accounts = ((tok_resp or {}).get("result") or {}).get("value") or []
    for acc in tok_accounts:
        parsed = (
            (acc.get("account") or {})
            .get("data", {})
            .get("parsed", {})
            .get("info", {})
        )
        mint       = parsed.get("mint", "")
        tok_amount = parsed.get("tokenAmount") or {}
        amount_raw = _int(tok_amount.get("amount", 0))
        decimals   = _int(tok_amount.get("decimals", 6), 6)
        if amount_raw == 0:
            continue
        symbol = _SOL_TOKEN_LABELS.get(mint, mint[:8] + "…" if len(mint) > 8 else mint)
        tokens.append({
            "symbol":   symbol,
            "balance":  round(amount_raw / (10 ** max(decimals, 1)), 6),
            "contract": mint,
        })

    first_seen = tx_list[-1]["time"] if tx_list else ""
    last_seen  = tx_list[0]["time"]  if tx_list else ""

    return {
        "chain":        "SOL",
        "address":      address,
        "balance":      round(balance_sol, 9),
        "balance_unit": "SOL",
        "tx_count":     len(tx_list),   # count of fetched signatures (capped at MAX_TXS)
        "first_seen":   first_seen,
        "last_seen":    last_seen,
        "recent_txs":   tx_list,
        "tokens":       tokens,
        "mixer_hits":   [],             # SOL mixer detection planned for future phase
        "explorer":     f"https://solscan.io/account/{address}",
        "source":       "solana-rpc",
    }


# =========================================================================
# Blockchair — generic fallback (LTC / DOGE / BCH / XRP / ETH / SOL)
# =========================================================================
_BLOCKCHAIR_CHAINS = {
    "LTC":  "litecoin",
    "DOGE": "dogecoin",
    "BCH":  "bitcoin-cash",
    "XRP":  "ripple",
    "ETH":  "ethereum",
    "BTC":  "bitcoin",
    "SOL":  "solana",   # fallback only — lookup_sol() uses RPC as primary
}


async def _lookup_blockchair(chain_slug: str, address: str,
                              unit: str = "") -> Dict[str, Any]:
    url = f"https://api.blockchair.com/{chain_slug}/dashboards/address/{address}"
    data = await _http_get_json(url, {"limit": MAX_TXS})
    if not data or "data" not in data:
        return {"chain": unit or chain_slug.upper(), "address": address,
                "error": "Blockchair unavailable"}

    payload = (data.get("data") or {}).get(address) or {}
    addr_info = payload.get("address", {}) or {}

    divisor = 1e18 if chain_slug == "ethereum" else 1e8
    try:
        balance = float(addr_info.get("balance", 0)) / divisor
    except Exception:
        balance = 0.0
    try:
        total_received = float(addr_info.get("received", 0)) / divisor
    except Exception:
        total_received = 0.0

    tx_ids = payload.get("transactions") or []
    tx_list = [{"hash": str(t), "time": "", "direction": ""} for t in tx_ids[:MAX_TXS]]

    return {
        "chain": unit or chain_slug.upper(),
        "address": address,
        "balance": round(balance, 8),
        "balance_unit": unit or chain_slug.upper(),
        "total_received": round(total_received, 8),
        "tx_count": addr_info.get("transaction_count", 0),
        "first_seen": addr_info.get("first_seen_receiving", "") or "",
        "last_seen":  addr_info.get("last_seen_spending", "")
                      or addr_info.get("last_seen_receiving", "") or "",
        "recent_txs": tx_list,
        "explorer": f"https://blockchair.com/{chain_slug}/address/{address}",
        "source": "blockchair",
    }


# =========================================================================
# Sanctions screening — OFAC lists (cached) + optional Chainalysis
# =========================================================================
# Maintained open-source mirror of OFAC SDN crypto addresses.
# Chainalysis "public" API now requires a real registered key; OFAC is free
# and updated daily. We fetch once at startup, cache in memory.

_OFAC_URLS = {
    "ETH":  "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_ETH.txt",
    "BTC":  "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_XBT.txt",
    "LTC":  "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_LTC.txt",
    "BCH":  "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_BCH.txt",
    "XRP":  "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_XRP.txt",
    "USDT": "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists/sanctioned_addresses_USDT.txt",
}

_OFAC_SETS: Dict[str, set] = {}
_OFAC_LOADED = False
_OFAC_LOCK: Optional[asyncio.Lock] = None


def _get_ofac_lock() -> asyncio.Lock:
    global _OFAC_LOCK
    if _OFAC_LOCK is None:
        _OFAC_LOCK = asyncio.Lock()
    return _OFAC_LOCK


async def _load_ofac_lists() -> None:
    """Fetch all OFAC lists once and cache in memory."""
    global _OFAC_LOADED
    async with _get_ofac_lock():
        if _OFAC_LOADED:
            return
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                for chain, url in _OFAC_URLS.items():
                    try:
                        async with s.get(url) as r:
                            if r.status != 200:
                                log.warning("OFAC %s fetch HTTP %s", chain, r.status)
                                continue
                            text = await r.text()
                            addrs = {
                                line.strip().lower()
                                for line in text.splitlines()
                                if line.strip() and not line.lstrip().startswith("#")
                            }
                            _OFAC_SETS[chain] = addrs
                            log.info("Loaded %d OFAC %s addresses", len(addrs), chain)
                    except Exception as e:
                        log.warning("OFAC %s fetch failed: %s", chain, e)
        finally:
            _OFAC_LOADED = True  # even on partial failure, avoid retry storms


async def _chainalysis_check(address: str) -> Optional[Dict[str, Any]]:
    """Optional: query Chainalysis public API if a real key is configured."""
    if not CHAINALYSIS_API_KEY:
        return None
    url = f"https://public.chainalysis.com/api/v1/address/{address}"
    try:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url, headers={
                "X-API-Key": CHAINALYSIS_API_KEY,
                "Accept": "application/json",
            }) as r:
                if r.status == 200:
                    data = await r.json()
                    ids = data.get("identifications", []) or []
                    return {
                        "sanctioned": bool(ids),
                        "identifications": ids,
                        "source": "chainalysis",
                    }
                log.warning("Chainalysis HTTP %s", r.status)
    except Exception as e:
        log.warning("Chainalysis error: %s", e)
    return None


async def check_sanctions(address: str) -> Dict[str, Any]:
    """
    Returns {'sanctioned': bool, 'identifications': [...], 'source': str}.
    Uses Chainalysis if CHAINALYSIS_API_KEY is set (overrides on hit),
    otherwise falls back to the cached OFAC lists.
    """
    # Primary: Chainalysis if key configured
    ca = await _chainalysis_check(address)
    if ca is not None:
        return ca

    # Fallback: local OFAC lists
    await _load_ofac_lists()
    addr_lower = address.strip().lower()
    hits = [c for c, addrs in _OFAC_SETS.items() if addr_lower in addrs]
    if hits:
        return {
            "sanctioned": True,
            "identifications": [{
                "name": "OFAC SDN Listed",
                "category": "sanctions",
                "description": f"Matched in OFAC list(s): {', '.join(hits)}",
            }],
            "source": "ofac_local",
        }
    return {"sanctioned": False, "source": "ofac_local"}


# =========================================================================
# Main dispatcher
# =========================================================================
async def lookup_crypto_address(address: str) -> Dict[str, Any]:
    address = (address or "").strip()

    chain = detect_chain(address)
    if not chain:
        return {
            "address": address,
            "error": "Unsupported or invalid address format. "
                     "Supported: BTC, ETH, TRX, LTC, DOGE, BCH, XRP, SOL.",
        }

    if chain == "BTC":
        lookup_coro = lookup_btc(address)
    elif chain == "ETH":
        lookup_coro = lookup_eth(address)
    elif chain == "TRX":
        lookup_coro = lookup_trx(address)
    elif chain == "SOL":
        lookup_coro = lookup_sol(address)
    elif chain in _BLOCKCHAIR_CHAINS:
        lookup_coro = _lookup_blockchair(_BLOCKCHAIR_CHAINS[chain], address, unit=chain)
    else:
        # Anything we detected but can't query live yet
        sanctions, arkham, debank, scam = await asyncio.gather(
            check_sanctions(address),
            arkham_lookup(address, chain),
            debank_lookup(address, chain),
            _scamsearch_lookup(address, "address"),
        )
        return {
            "address": address, "detected_chain": chain,
            "chain": chain,
            "error": f"{chain} address format detected, but live lookups not wired yet.",
            "sanctions": sanctions,
            "arkham": arkham,
            "debank": debank,
            "scam_reports": scam,
            "explorer": _generic_explorer(chain, address),
        }

    intel, sanctions, arkham, debank, scam = await asyncio.gather(
        lookup_coro,
        check_sanctions(address),
        arkham_lookup(address, chain),
        debank_lookup(address, chain),
        _scamsearch_lookup(address, "address"),
    )
    intel["sanctions"]      = sanctions
    intel["arkham"]         = arkham
    intel["debank"]         = debank
    intel["scam_reports"]   = scam
    intel["detected_chain"] = chain
    tx_evidence = (intel.get("recent_txs") or []) + (intel.get("token_txs") or [])
    intel["chain_hop_swap"] = detect_chain_hopping_and_swaps(tx_evidence, address)
    return intel


def _generic_explorer(chain: str, address: str) -> str:
    if chain == "SOL":
        return f"https://solscan.io/account/{address}"
    return ""


# =========================================================================
# Telegram output formatting
# =========================================================================
def format_crypto_report_html(intel: Dict[str, Any]) -> str:
    """Telegram HTML-safe report."""
    if intel.get("error") and not intel.get("balance") and not intel.get("sanctions"):
        return (f"<b>Crypto lookup failed</b>\n"
                f"Address: <code>{escape(intel.get('address', ''))}</code>\n"
                f"Error: <code>{escape(str(intel['error'])[:300])}</code>")

    chain = intel.get("chain", "?")
    addr  = intel.get("address", "")
    lines = [f"<b>═══ {escape(chain)} Address Intel ═══</b>"]
    lines.append(f"<b>Address:</b> <code>{escape(addr)}</code>")
    lines.append(f"<b>Balance:</b> <code>{intel.get('balance', 0)} {escape(str(intel.get('balance_unit', '')))}</code>")
    if intel.get("portfolio_usd") is not None:
        lines.append(f"<b>Estimated portfolio:</b> <code>${float(intel['portfolio_usd']):,.2f}</code>")
    if intel.get("total_received"):
        lines.append(f"<b>Total received:</b> <code>{intel['total_received']} {escape(str(intel.get('balance_unit', '')))}</code>")
    lines.append(f"<b>Tx count:</b> <code>{intel.get('tx_count', 0)}</code>")
    if intel.get("first_seen"):
        lines.append(f"<b>First seen:</b> <code>{escape(intel['first_seen'])}</code>")
    if intel.get("last_seen"):
        lines.append(f"<b>Last seen:</b>  <code>{escape(intel['last_seen'])}</code>")
    if intel.get("native_tx_count") is not None or intel.get("token_tx_count") is not None:
        lines.append(
            f"<b>Fetched activity:</b> native <code>{intel.get('native_tx_count', 0)}</code>"
            f" / token <code>{intel.get('token_tx_count', 0)}</code>"
        )
    if intel.get("explorer"):
        lines.append(f"<b>Explorer:</b> {escape(intel['explorer'])}")
    if intel.get("source"):
        lines.append(f"<b>Source:</b> <code>{escape(str(intel['source']))}</code>")
    if intel.get("fallback_warning"):
        lines.append(f"<i>Data note: {escape(str(intel['fallback_warning'])[:200])}</i>")

    # Arkham attribution
    arkham_block = format_arkham_section_html(intel.get("arkham"))
    if arkham_block:
        lines.append("")
        lines.append(arkham_block)

    # DeBank profile / owner name
    debank_block = format_debank_section_html(intel.get("debank"))
    if debank_block:
        lines.append("")
        lines.append(debank_block)

    # Sanctions
    sanctions = intel.get("sanctions", {}) or {}
    src = sanctions.get("source", "ofac")
    src_label = {"chainalysis": "Chainalysis", "ofac_local": "OFAC"}.get(src, src)
    lines.append("")
    if sanctions.get("sanctioned"):
        lines.append(f"🚨 <b>SANCTIONED ADDRESS</b> ({escape(src_label)}) 🚨")
        for ident in sanctions.get("identifications", [])[:5]:
            name = escape(str(ident.get("name", "")))
            cat  = escape(str(ident.get("category", "")))
            lines.append(f"• <b>{name}</b> <i>({cat})</i>")
            desc = ident.get("description") or ""
            if desc:
                lines.append(f"  <i>{escape(desc[:200])}</i>")
    elif sanctions.get("error"):
        lines.append(f"⚠️ <b>Sanctions check:</b> <code>{escape(sanctions['error'])}</code>")
    else:
        lines.append(f"✅ <b>Sanctions:</b> clean ({escape(src_label)})")

    # ScamSearch community reports
    scam_block = _format_scamsearch_html(intel.get("scam_reports"))
    if scam_block:
        lines.append("")
        lines.append(scam_block)

    # Chain hopping / swap infrastructure
    hop_swap = intel.get("chain_hop_swap") or {}
    bridge_hits = hop_swap.get("bridge_hits") or []
    swap_hits = hop_swap.get("swap_hits") or []
    heuristics = hop_swap.get("heuristics") or []
    if bridge_hits or swap_hits or heuristics:
        lines.append("")
        lines.append("<b>── Chain Hopping / Swap Signals ──</b>")
        lines.append(
            f"Risk: <b>{escape(str(hop_swap.get('risk_level', 'unknown')).upper())}</b>  |  "
            f"Bridge hits: <code>{hop_swap.get('bridge_count', 0)}</code>  |  "
            f"Swap/router hits: <code>{hop_swap.get('swap_count', 0)}</code>"
        )
        for h in bridge_hits[:5]:
            lines.append(
                f"🌉 <b>{escape(str(h.get('name', 'Bridge')))}</b> "
                f"{escape(str(h.get('direction', '')))} "
                f"<code>{escape(str(h.get('value', '')))} {escape(str(h.get('token', '') or intel.get('balance_unit', '')))}</code>"
                + (f"\n   tx: <code>{escape(str(h.get('tx_hash', ''))[:24])}…</code>" if h.get("tx_hash") else "")
            )
        for h in swap_hits[:5]:
            lines.append(
                f"🔁 <b>{escape(str(h.get('name', 'Swap Router')))}</b> "
                f"{escape(str(h.get('direction', '')))} "
                f"<code>{escape(str(h.get('value', '')))} {escape(str(h.get('token', '') or intel.get('balance_unit', '')))}</code>"
                + (f"\n   tx: <code>{escape(str(h.get('tx_hash', ''))[:24])}…</code>" if h.get("tx_hash") else "")
            )
        for h in heuristics[:3]:
            lines.append(f"⚑ <i>{escape(str(h.get('evidence', '')))}</i>")

    # Token Holdings (ERC20 / TRC20)
    tokens = intel.get("tokens") or []
    if tokens:
        lines.append("")
        lines.append("<b>── Token Holdings ──</b>")
        for t in tokens[:10]:
            sym = escape(str(t.get("symbol", "?")))
            bal = t.get("balance", "")
            nm  = escape(str(t.get("name", "")))
            contract = escape(str(t.get("contract", "")))
            usd_value = t.get("usd_value")
            lines.append(f"• <b>{sym}</b>: <code>{bal}</code>"
                         + (f"  <code>${float(usd_value):,.2f}</code>" if usd_value else "")
                         + (f"  <i>{nm}</i>" if nm else "")
                         + (f"\n  Contract: <code>{contract[:20]}…</code>" if contract else ""))

    # Token transfers
    token_txs = intel.get("token_txs") or []
    if token_txs:
        lines.append("")
        lines.append(f"<b>── Token Transfers (top {min(len(token_txs), 10)}) ──</b>")
        for t in token_txs[:10]:
            arrow     = "⬅️" if t.get("direction") == "IN" else "➡️"
            token     = escape(t.get("token", ""))
            value     = t.get("value", "")
            ts        = escape((t.get("time") or "")[:19])
            h         = escape((t.get("hash") or "")[:18])
            lines.append(f"{arrow} <b>{token}</b> <code>{value}</code>  {ts}"
                         + (f"\n   tx: <code>{h}…</code>" if h else ""))

    # Native coin recent transactions
    txs = intel.get("recent_txs") or []
    if txs:
        lines.append("")
        lines.append(f"<b>── Recent Transactions (top {min(len(txs), 10)}) ──</b>")
        for t in txs[:10]:
            h         = t.get("txid") or t.get("hash") or ""
            ts        = t.get("time", "")
            direction = t.get("direction", "")
            arrow     = "⬅️" if direction == "IN" else ("➡️" if direction == "OUT" else "•")
            value     = ""
            if "value_trx" in t:
                value = f"{t['value_trx']} TRX"
            elif "value_eth" in t:
                value = f"{t['value_eth']} ETH"
            elif "delta_btc" in t:
                value = f"{t['delta_btc']:+} BTC"
            lines.append(f"{arrow} <code>{escape(h[:20])}…</code> {escape(ts[:19])} {escape(value)}")

    if intel.get("error"):
        lines.append("")
        lines.append(f"<i>Partial data — {escape(str(intel['error'])[:200])}</i>")

    return "\n".join(lines)
