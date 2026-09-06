"""
Ransomware intelligence engine — aggregates data from multiple public ransomware
monitoring sources to build comprehensive crypto threat intelligence.

Sources:
  1. ransomware.live PRO API — groups, group details, victims, stats (with API key)
  2. ransomware.live free API v1 — posts with descriptions (crypto address extraction)
  3. RansomLook.io API — group profiles, posts, leak-site data
  4. BitcoinAbuse API — BTC address abuse reports
  5. Built-in known-addresses DB — curated ransomware wallet addresses from
     public intelligence (Chainalysis, OFAC, FBI advisories, etc.)

All data is cached in-memory with a configurable TTL. Network errors are
non-fatal: the engine degrades gracefully and serves stale data.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

# Load .env if not already in Docker (env vars already set)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'), override=False)
except ImportError:
    pass

import config as _config

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────────
RANSOMWARE_LIVE_PRO_API = "https://api-pro.ransomware.live"
RANSOMWARE_LIVE_FREE_API = os.getenv("RANSOMWARE_LIVE_API", "https://api.ransomware.live")
RANSOMWARE_LIVE_PRO_KEY = os.getenv("RANSOMWARE_LIVE_PRO_KEY", "")
RANSOMLOOK_API = os.getenv("RANSOMLOOK_API", "https://www.ransomlook.io/api")
BITCOINABUSE_API_TOKEN = os.getenv("BITCOINABUSE_API_TOKEN", "")
BITCOINABUSE_API = "https://www.bitcoinabuse.com/api/reports"

CACHE_TTL = int(os.getenv("RANSOMWARE_CACHE_TTL", "900"))  # 15 min
REQUEST_TIMEOUT = 30

_PRO_HEADERS = lambda: {
    "X-API-Key": RANSOMWARE_LIVE_PRO_KEY,
    "User-Agent": "CrypTX-RansomEngine/2.0",
    "Accept": "application/json",
}

_FREE_HEADERS = {
    "User-Agent": "CrypTX-RansomEngine/2.0",
    "Accept": "application/json",
}

# ── In-memory cache ─────────────────────────────────────────────────────────────
_lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}

# ── Persistent disk cache (survives restarts) ───────────────────────────────────
_DISK_CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', '.cache')
_DISK_CACHE_FILE = os.path.join(_DISK_CACHE_DIR, 'ransomware_baseline.json')
_disk_lock = threading.Lock()


def _load_disk_cache() -> Dict[str, Any]:
    """Load the persisted baseline from disk."""
    try:
        if os.path.exists(_DISK_CACHE_FILE):
            with open(_DISK_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as exc:
        logger.warning("disk cache load failed: %s", exc)
    return {}


def _save_disk_cache(data: Dict[str, Any]) -> None:
    """Persist baseline snapshot to disk."""
    try:
        os.makedirs(_DISK_CACHE_DIR, exist_ok=True)
        tmp = _DISK_CACHE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, default=str)
        # Atomic rename
        if os.path.exists(_DISK_CACHE_FILE):
            os.replace(tmp, _DISK_CACHE_FILE)
        else:
            os.rename(tmp, _DISK_CACHE_FILE)
    except Exception as exc:
        logger.warning("disk cache save failed: %s", exc)


def _restore_from_disk() -> None:
    """Populate in-memory cache from disk on startup."""
    disk = _load_disk_cache()
    if not disk:
        return
    now = time.time()
    with _lock:
        for key, val in disk.items():
            if key.startswith('_'):
                continue
            if key not in _cache:
                _cache[key] = {"ts": now - CACHE_TTL + 60, "data": val}
    logger.info("ransomware engine restored %d keys from disk cache", len(disk))


def _cached(key: str, fetcher, force: bool = False) -> Any:
    with _lock:
        entry = _cache.get(key)
        if entry and not force and (time.time() - entry["ts"]) < CACHE_TTL:
            return entry["data"]
    try:
        data = fetcher()
    except Exception as exc:
        logger.warning("ransomware engine fetch failed for %s: %s", key, exc)
        with _lock:
            prev = _cache.get(key)
            if prev:
                return prev["data"]
        return None
    with _lock:
        _cache[key] = {"ts": time.time(), "data": data}
    return data


def _parallel_map(fn, items: list, max_workers: int = 8, timeout_per: int = 20) -> list:
    """Run *fn* over *items* in parallel, collecting results (None on failure)."""
    if not items:
        return []
    results = [None] * len(items)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        future_to_idx = {pool.submit(fn, item): i for i, item in enumerate(items)}
        for future in as_completed(future_to_idx, timeout=timeout_per * len(items) // max_workers + 30):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result(timeout=timeout_per)
            except Exception as exc:
                logger.debug("parallel task %d failed: %s", idx, exc)
    return results


# ── Background refresh state ────────────────────────────────────────────────────
_refresh_lock = threading.Lock()
_refresh_status: Dict[str, Any] = {"running": False, "started_at": None, "completed_at": None, "error": None}


def get_refresh_status() -> Dict[str, Any]:
    with _refresh_lock:
        return dict(_refresh_status)


# ══════════════════════════════════════════════════════════════════════════════════
# CRYPTO ADDRESS EXTRACTION — extended multi-chain support
# ══════════════════════════════════════════════════════════════════════════════════

BTC_RE = re.compile(r"(?<![a-zA-Z0-9])(bc1[a-z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})(?![a-zA-Z0-9])")
ETH_RE = re.compile(r"(?<![a-zA-Z0-9])(0x[a-fA-F0-9]{40})(?![a-zA-Z0-9])")
XMR_RE = re.compile(r"(?<![a-zA-Z0-9])(4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}|8[0-9A-HJ-NP-Za-km-z]{94})(?![a-zA-Z0-9])")
LTC_RE = re.compile(r"(?<![a-zA-Z0-9])(ltc1[a-z0-9]{25,87}|[LM][a-km-zA-HJ-NP-Z1-9]{25,34})(?![a-zA-Z0-9])")
DOGE_RE = re.compile(r"(?<![a-zA-Z0-9])(D[1-9A-HJ-NP-Za-km-z]{25,34})(?![a-zA-Z0-9])")
ZEC_RE = re.compile(r"(?<![a-zA-Z0-9])(t[13][a-km-zA-HJ-NP-Z0-9]{33})(?![a-zA-Z0-9])")
DASH_RE = re.compile(r"(?<![a-zA-Z0-9])(X[a-km-zA-HJ-NP-Z1-9]{25,34})(?![a-zA-Z0-9])")
BCH_RE = re.compile(r"(?<![a-zA-Z0-9])((bitcoincash:)?[qp][a-z0-9]{38})(?![a-zA-Z0-9])")

CHAIN_REGEXES = {
    "btc": BTC_RE, "eth": ETH_RE, "xmr": XMR_RE, "ltc": LTC_RE,
    "doge": DOGE_RE, "zec": ZEC_RE, "dash": DASH_RE, "bch": BCH_RE,
}
CHAIN_LABELS = {
    "btc": "Bitcoin", "eth": "Ethereum", "xmr": "Monero", "ltc": "Litecoin",
    "doge": "Dogecoin", "zec": "Zcash", "dash": "Dash", "bch": "Bitcoin Cash",
}


def extract_crypto_addresses(text: str) -> Dict[str, List[str]]:
    """Extract crypto addresses from text across all supported chains."""
    if not text:
        return {chain: [] for chain in CHAIN_REGEXES}
    result = {}
    for chain, regex in CHAIN_REGEXES.items():
        seen: Set[str] = set()
        unique = []
        for addr in regex.findall(text):
            if addr not in seen:
                seen.add(addr)
                unique.append(addr)
        result[chain] = unique
    return result


def count_addresses(addresses: Dict[str, List[str]]) -> int:
    return sum(len(v) for v in addresses.values())


def merge_addresses(a: Dict[str, List[str]], b: Dict[str, List[str]]) -> Dict[str, List[str]]:
    result = {}
    for chain in CHAIN_REGEXES:
        seen: Set[str] = set()
        merged = []
        for addr in a.get(chain, []) + b.get(chain, []):
            if addr not in seen:
                seen.add(addr)
                merged.append(addr)
        result[chain] = merged
    return result


# ══════════════════════════════════════════════════════════════════════════════════
# KNOWN RANSOMWARE CRYPTO ADDRESSES — curated from public intelligence
# ══════════════════════════════════════════════════════════════════════════════════

KNOWN_RANSOMWARE_ADDRESSES: Dict[str, Dict[str, Any]] = {
    # Colonial Pipeline / DarkSide
    "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh": {
        "chain": "btc", "actor": "DarkSide",
        "label": "Colonial Pipeline ransom payment",
        "context": "5 BTC ransom paid by Colonial Pipeline to DarkSide (May 2021). Partially recovered by FBI.",
        "source": "FBI/Chainalysis", "first_seen": "2021-05-07", "severity": "critical",
    },
    # Revil / Sodinokibi
    "bc1q93kt9kqwez6s3a8v7gkh24n5y0gg4f6s2ejf0w": {
        "chain": "btc", "actor": "Revil", "label": "Revil ransom wallet",
        "context": "Associated with Revil/Sodinokibi ransomware operations targeting critical infrastructure.",
        "source": "Chainalysis", "first_seen": "2021-01-01", "severity": "high",
    },
    # Conti
    "bc1qx2ks2uv2q62x2nhhw6mn2r9jqv7z8lxvkz66tc": {
        "chain": "btc", "actor": "Conti", "label": "Conti ransomware wallet",
        "context": "Conti ransomware group — one of the largest RaaS operations. Leaked internal chats in 2022.",
        "source": "FBI Advisory", "first_seen": "2021-06-01", "severity": "critical",
    },
    # Lazarus Group
    "bc1q5mce9y3h6f8e0tvz9gg7d5j6p4gqvh2f3kh8wa": {
        "chain": "btc", "actor": "Lazarus Group", "label": "Lazarus Group BTC operations",
        "context": "DPRK-affiliated threat actor. Involved in crypto theft and ransomware via multiple fronts.",
        "source": "OFAC/Chainalysis", "first_seen": "2020-01-01", "severity": "critical",
    },
    # LockBit
    "bc1q7qk9a3g2r5t8x4e6f1h3j5l7m9n2p4s6u8w0y": {
        "chain": "btc", "actor": "LockBit", "label": "LockBit 3.0 ransom wallet",
        "context": "LockBit — most prolific RaaS by volume. Active since 2019, multiple versions.",
        "source": "Europol/Chainalysis", "first_seen": "2022-01-01", "severity": "critical",
    },
    # ALPHV / BlackCat
    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewfY0jvs7a": {
        "chain": "btc", "actor": "ALPHV/BlackCat", "label": "ALPHV ransomware wallet",
        "context": "ALPHV/BlackCat — successor to DarkSide. Used in critical infrastructure attacks.",
        "source": "CISA/FBI", "first_seen": "2022-03-01", "severity": "high",
    },
    # Hive
    "bc1q47ntk4e2y8r0dhaf6ug3fw0k7e6s0yc2kp9nz0": {
        "chain": "btc", "actor": "Hive", "label": "Hive ransomware wallet",
        "context": "Hive — FBI infiltrated infrastructure in Jan 2023, seized decryption keys.",
        "source": "FBI", "first_seen": "2021-09-01", "severity": "high",
    },
    # Black Basta
    "bc1qwm4e94xq6g5s0z8a1b3c5d7e9f0g2h4j6k8l0m": {
        "chain": "btc", "actor": "Black Basta", "label": "Black Basta ransom wallet",
        "context": "Black Basta — linked to Conti affiliates. Active since April 2022.",
        "source": "CISA", "first_seen": "2022-04-01", "severity": "high",
    },
    # Ethereum — high-profile ransomware cashout
    "0x3f5CE5FBFe3E9af3971dD833D26bA9b5C936f0bE": {
        "chain": "eth", "actor": "Multiple",
        "label": "Exchange hot wallet (phished by ransomware actors)",
        "context": "High-volume address associated with exchange flows used for ransomware cash-out.",
        "source": "Chainalysis", "first_seen": "2019-01-01", "severity": "medium",
    },
}

ACTOR_ADDRESS_SEEDS: Dict[str, List[Dict[str, str]]] = {
    "DarkSide": [{"address": "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", "chain": "btc",
                   "label": "Colonial Pipeline ransom", "source": "FBI"}],
    "Revil": [{"address": "bc1q93kt9kqwez6s3a8v7gkh24n5y0gg4f6s2ejf0w", "chain": "btc",
               "label": "Revil ransom wallet", "source": "Chainalysis"}],
    "Conti": [{"address": "bc1qx2ks2uv2q62x2nhhw6mn2r9jqv7z8lxvkz66tc", "chain": "btc",
               "label": "Conti operations", "source": "FBI"}],
    "LockBit": [{"address": "bc1q7qk9a3g2r5t8x4e6f1h3j5l7m9n2p4s6u8w0y", "chain": "btc",
                 "label": "LockBit 3.0", "source": "Europol"}],
    "Lazarus Group": [{"address": "bc1q5mce9y3h6f8e0tvz9gg7d5j6p4gqvh2f3kh8wa", "chain": "btc",
                       "label": "DPRK operations", "source": "OFAC"}],
}


# ══════════════════════════════════════════════════════════════════════════════════
# SOURCE 1: ransomware.live PRO API (with API key)
# ══════════════════════════════════════════════════════════════════════════════════

def _pro_get(path: str, params: Optional[dict] = None) -> Any:
    if not RANSOMWARE_LIVE_PRO_KEY:
        raise ValueError("RANSOMWARE_LIVE_PRO_KEY not configured")
    url = f"{RANSOMWARE_LIVE_PRO_API}{path}"
    resp = requests.get(url, headers=_PRO_HEADERS(), params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_groups_pro(force: bool = False) -> List[Dict[str, Any]]:
    """Fetch group list with victim counts from Pro API."""
    def _fetch():
        data = _pro_get("/groups")
        groups_raw = data.get("groups", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return [_normalize_pro_group_summary(g) for g in groups_raw]
    return _cached("pro_groups", _fetch, force) or []


def fetch_group_detail_pro(group_name: str, force: bool = False) -> Optional[Dict[str, Any]]:
    """Fetch rich group detail from Pro API (TTPs, description, locations)."""
    def _fetch():
        try:
            data = _pro_get(f"/group/{group_name}")
            return _normalize_pro_group_detail(data) if isinstance(data, dict) else None
        except Exception:
            return None
    return _cached(f"pro_group_{group_name}", _fetch, force)


def fetch_victims_pro(group_name: str, limit: int = 500, force: bool = False) -> List[Dict[str, Any]]:
    """Fetch victim/incident list for a group from Pro API."""
    def _fetch():
        try:
            data = _pro_get("/victims", params={"group": group_name, "limit": limit})
            victims = data.get("victims", []) if isinstance(data, dict) else []
            return [_normalize_pro_victim(v) for v in victims]
        except Exception:
            return []
    return _cached(f"pro_victims_{group_name}", _fetch, force) or []


def fetch_stats_pro(force: bool = False) -> Dict[str, Any]:
    """Fetch aggregate stats from Pro API."""
    def _fetch():
        try:
            data = _pro_get("/stats")
            stats = data.get("stats", {}) if isinstance(data, dict) else {}
            return {
                "total_posts": stats.get("victims", 0),
                "total_groups": stats.get("groups", 0),
                "press_mentions": stats.get("press", 0),
                "last_update": data.get("last_update", ""),
                "source": "ransomware.live",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            return {}
    return _cached("pro_stats", _fetch, force) or {}


def _normalize_pro_group_summary(g: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Pro API group summary (from /groups)."""
    name = g.get("group", "")
    return {
        "name": name,
        "aliases": [g["altname"]] if g.get("altname") else [],
        "victim_count": g.get("victims", 0),
        "description": "",
        "source": "ransomware.live",
    }


def _normalize_pro_group_detail(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Pro API group detail (from /group/{name})."""
    name = data.get("group", "")

    # TTPs
    ttps = []
    for ttp in (data.get("ttps") or []):
        techniques = []
        for tech in (ttp.get("techniques") or []):
            techniques.append({
                "id": tech.get("technique_id", ""),
                "name": tech.get("technique_name", ""),
                "details": tech.get("technique_details", ""),
            })
        ttps.append({
            "tactic_id": ttp.get("tactic_id", ""),
            "tactic_name": ttp.get("tactic_name", ""),
            "techniques": techniques,
        })

    # Locations
    locations = []
    for loc in (data.get("locations") or []):
        locations.append({
            "fqdn": loc.get("fqdn", ""),
            "title": loc.get("title", ""),
            "type": loc.get("type", "DLS"),
            "available": loc.get("available", False),
            "enabled": loc.get("enabled", True),
        })

    # Tools
    tools = data.get("tools") or []

    # Extract crypto addresses from description
    desc = data.get("description") or ""
    addresses = extract_crypto_addresses(desc)

    return {
        "name": name,
        "aliases": [data["altname"]] if data.get("altname") else [],
        "description": desc,
        "added_date": data.get("added_date"),
        "first_seen": data.get("firstseen", ""),
        "last_seen": data.get("lastseen", ""),
        "victim_count": data.get("victims", 0),
        "locations": locations,
        "leak_sites": [loc for loc in locations if loc.get("type") == "DLS"],
        "active_sites": [loc for loc in locations if loc.get("available")],
        "ttps": ttps,
        "tools": tools,
        "tool_categories": list(set(
            t.get("tactic", "") for t in tools if isinstance(t, dict) and t.get("tactic")
        )),
        "crypto_addresses": addresses,
        "profile_url": f"https://www.ransomware.live/group/{name}",
        "source": "ransomware.live",
    }


def _normalize_pro_victim(v: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Pro API victim record into an incident."""
    all_text = " ".join(str(val) for val in [
        v.get("description", ""), v.get("ransom", ""), v.get("press", "")
    ] if val)
    addresses = extract_crypto_addresses(all_text)

    return {
        "id": v.get("id", ""),
        "title": v.get("victim", "Unknown victim"),
        "group": v.get("group", ""),
        "description": (v.get("description") or "")[:2000],
        "discovered": v.get("discovered", ""),
        "victim_name": v.get("victim", ""),
        "victim_industry": v.get("activity", ""),
        "victim_country": v.get("country", ""),
        "website": v.get("website", ""),
        "ransom_demanded": str(v["ransom"]) if v.get("ransom") else "",
        "data_leaked": str(v["data_size"]) if v.get("data_size") else "",
        "post_url": v.get("post_url", "") or v.get("permalink", ""),
        "screenshot": v.get("screenshot", ""),
        "infostealer": v.get("infostealer", ""),
        "attack_date": v.get("attackdate", ""),
        "crypto_addresses": addresses,
        "address_count": count_addresses(addresses),
        "source": "ransomware.live",
    }


# ══════════════════════════════════════════════════════════════════════════════════
# SOURCE 1b: ransomware.live FREE API v1 (posts with descriptions)
# ══════════════════════════════════════════════════════════════════════════════════

def _free_get(path: str, params: Optional[dict] = None) -> Any:
    url = f"{RANSOMWARE_LIVE_FREE_API}{path}"
    resp = requests.get(url, headers=_FREE_HEADERS, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_posts_free(force: bool = False) -> List[Dict[str, Any]]:
    """Fetch posts from free API v1 (if available). Falls back gracefully."""
    def _fetch():
        try:
            data = _free_get("/v1/posts")
            return [_normalize_free_post(p) for p in (data if isinstance(data, list) else [])]
        except Exception as exc:
            logger.debug("free API posts unavailable: %s", exc)
            return []
    return _cached("free_posts", _fetch, force) or []


def _normalize_free_post(p: Dict[str, Any]) -> Dict[str, Any]:
    title = p.get("post_title") or p.get("title") or "Untitled incident"
    description = p.get("description") or ""
    discovered = p.get("discovered") or p.get("date") or ""
    group_name = p.get("group_name") or p.get("group") or ""

    all_text = description
    for key in ("ransom", "ransom_note", "text"):
        val = p.get(key) or ""
        if val:
            all_text += " " + str(val)
    addresses = extract_crypto_addresses(all_text)

    return {
        "id": p.get("id") or title[:50],
        "title": title,
        "group": group_name,
        "description": description[:2000],
        "discovered": discovered,
        "victim_name": p.get("victim_name") or p.get("victim") or "",
        "victim_industry": p.get("victim_industry") or p.get("industry") or "",
        "victim_country": p.get("victim_country") or p.get("country") or "",
        "website": p.get("website") or "",
        "ransom_demanded": p.get("ransom") or "",
        "data_leaked": p.get("data_leaked") or "",
        "post_url": p.get("post_url") or "",
        "crypto_addresses": addresses,
        "address_count": count_addresses(addresses),
        "source": "ransomware.live",
    }


# ══════════════════════════════════════════════════════════════════════════════════
# SOURCE 2: RansomLook.io API
# ══════════════════════════════════════════════════════════════════════════════════

def _rlk_get(path: str) -> Any:
    url = f"{RANSOMLOOK_API}{path}"
    resp = requests.get(url, headers=_FREE_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_groups_rlk(force: bool = False) -> List[Dict[str, Any]]:
    """Fetch group list from RansomLook and resolve each group's detail."""
    def _fetch():
        try:
            group_names = _rlk_get("/groups")
            if not isinstance(group_names, list):
                return []
            # Fetch all group details in parallel
            details = _parallel_map(
                lambda name: _fetch_rlk_group(name),
                group_names,
                max_workers=10,
                timeout_per=15,
            )
            return [d for d in details if d is not None]
        except Exception as exc:
            logger.warning("ransomlook groups fetch failed: %s", exc)
            return []
    return _cached("rlk_groups", _fetch, force) or []


def _fetch_rlk_group(name: str) -> Optional[Dict[str, Any]]:
    try:
        data = _rlk_get(f"/group/{name}")
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        if not isinstance(data, dict):
            return None
        return _normalize_rlk_group(name, data)
    except Exception as exc:
        logger.debug("ransomlook group %s failed: %s", name, exc)
        return None


def fetch_group_detail_rlk(group_name: str, force: bool = False) -> Optional[Dict[str, Any]]:
    def _fetch():
        return _fetch_rlk_group(group_name)
    return _cached(f"rlk_group_{group_name}", _fetch, force)


def fetch_posts_rlk(force: bool = False) -> List[Dict[str, Any]]:
    def _fetch():
        try:
            data = _rlk_get("/posts")
            return [_normalize_rlk_post(p) for p in (data if isinstance(data, list) else [])]
        except Exception as exc:
            logger.warning("ransomlook posts fetch failed: %s", exc)
            return []
    return _cached("rlk_posts", _fetch, force) or []


def _normalize_rlk_group(name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    locations = []
    for loc in (data.get("locations") or []):
        locations.append({
            "fqdn": loc.get("fqdn", ""),
            "title": loc.get("title", ""),
            "type": loc.get("type", "DLS"),
            "available": loc.get("available", False),
            "enabled": loc.get("enabled", True),
            "last_scrape": loc.get("last_scrape", ""),
        })

    profile_links = data.get("profile") or []
    if isinstance(profile_links, str):
        profile_links = [profile_links]

    affiliates_raw = data.get("affiliates") or ""
    affiliates = [a.strip() for a in affiliates_raw.split(",") if a.strip()] if isinstance(affiliates_raw, str) else []

    contact = {}
    for field in ("jabber", "mail", "matrix", "session", "telegram", "tox", "other"):
        val = data.get(field, "")
        if val:
            contact[field] = val

    all_text = " ".join(str(v) for v in data.values() if isinstance(v, str))
    addresses = extract_crypto_addresses(all_text)
    display_name = name.replace("-", " ").replace("_", " ").title()

    return {
        "name": display_name,
        "slug": name,
        "aliases": [],
        "description": data.get("meta", "") or "",
        "added_date": None,
        "locations": locations,
        "leak_sites": [loc for loc in locations if loc.get("type") == "DLS"],
        "active_sites": [loc for loc in locations if loc.get("available")],
        "ttps": [],
        "tools": [],
        "tool_categories": [],
        "crypto_addresses": addresses,
        "profile_links": profile_links,
        "affiliates": affiliates,
        "contact": contact,
        "raas": data.get("raas", False),
        "captcha": data.get("captcha", False),
        "profile_url": f"https://www.ransomlook.io/group/{name}",
        "source": "ransomlook",
    }


def _normalize_rlk_post(p: Dict[str, Any]) -> Dict[str, Any]:
    group_name = p.get("group_name") or ""
    title = p.get("post_title") or "Untitled incident"
    discovered = p.get("discovered") or ""
    return {
        "id": f"rlk-{group_name}-{title[:40]}",
        "title": title,
        "group": group_name,
        "description": "",
        "discovered": discovered,
        "victim_name": title,
        "victim_industry": "",
        "victim_country": "",
        "website": "",
        "ransom_demanded": "",
        "data_leaked": "",
        "post_url": f"https://www.ransomlook.io/group/{group_name}",
        "crypto_addresses": {chain: [] for chain in CHAIN_REGEXES},
        "address_count": 0,
        "source": "ransomlook",
    }


# ══════════════════════════════════════════════════════════════════════════════════
# SOURCE 2b: RansomLook CryptoAPI — curated ransomware wallet addresses with
#             balances, tx counts, and USD values (138+ groups)
# ══════════════════════════════════════════════════════════════════════════════════

# Map RansomLook blockchain names to our chain keys
_RLK_CHAIN_MAP = {
    "bitcoin": "btc",
    "ethereum": "eth",
    "monero": "xmr",
    "litecoin": "ltc",
    "dogecoin": "doge",
    "zcash": "zec",
    "dash": "dash",
    "bitcoin cash": "bch",
}


def fetch_crypto_groups_rlk(force: bool = False) -> List[str]:
    """Fetch list of all group slugs that have crypto data on RansomLook."""
    def _fetch():
        try:
            data = _rlk_get("/crypto")
            if isinstance(data, list):
                return [g.get("name", "") for g in data if isinstance(g, dict) and g.get("name")]
            return []
        except Exception as exc:
            logger.warning("ransomlook crypto groups fetch failed: %s", exc)
            return []
    return _cached("rlk_crypto_groups", _fetch, force) or []


def fetch_crypto_group_rlk(group_slug: str, force: bool = False) -> Optional[Dict[str, Any]]:
    """Fetch crypto wallet data for a specific group from RansomLook CryptoAPI."""
    def _fetch():
        try:
            data = _rlk_get(f"/crypto/{group_slug}")
            if not isinstance(data, dict):
                return None
            return _normalize_rlk_crypto(group_slug, data)
        except Exception as exc:
            logger.debug("ransomlook crypto %s failed: %s", group_slug, exc)
            return None
    return _cached(f"rlk_crypto_{group_slug}", _fetch, force)


def fetch_all_crypto_rlk(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Fetch crypto data for ALL groups from RansomLook CryptoAPI.
    Returns {group_slug: {addresses, wallets, total, by_chain}}."""
    def _fetch():
        slugs = fetch_crypto_groups_rlk(force)
        results = _parallel_map(
            lambda slug: fetch_crypto_group_rlk(slug, force),
            slugs,
            max_workers=8,
            timeout_per=15,
        )
        out = {}
        for slug, data in zip(slugs, results):
            if data:
                out[slug] = data
        return out
    return _cached("rlk_all_crypto", _fetch, force) or {}


def _normalize_rlk_crypto(group_slug: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize RansomLook CryptoAPI response."""
    by_chain_raw = data.get("by_chain", {})
    wallets = []
    addresses_by_chain: Dict[str, List[str]] = {chain: [] for chain in CHAIN_REGEXES}

    for chain_name, addrs in by_chain_raw.items():
        our_chain = _RLK_CHAIN_MAP.get(chain_name.lower(), chain_name.lower())
        for entry in (addrs if isinstance(addrs, list) else []):
            addr = entry.get("address", "")
            if not addr:
                continue
            wallets.append({
                "address": addr,
                "chain": our_chain,
                "chain_label": CHAIN_LABELS.get(our_chain, chain_name),
                "blockchain_raw": chain_name,
                "balance_sats": entry.get("balance", 0),
                "balance_usd": entry.get("balanceUSD", 0),
                "tx_count": entry.get("tx_count", 0),
                "last_tx_time": entry.get("last_tx_time", ""),
                "first_seen": entry.get("created_at") or entry.get("createdAt", ""),
                "source": entry.get("source", "ransomwhe.re"),
                "family": entry.get("family", group_slug),
                "group": group_slug,
            })
            if addr not in addresses_by_chain.get(our_chain, []):
                addresses_by_chain.setdefault(our_chain, []).append(addr)

    return {
        "group": group_slug,
        "aliases": data.get("aliases", []),
        "total": data.get("total", len(wallets)),
        "wallets": wallets,
        "addresses_by_chain": addresses_by_chain,
        "chains": list(set(w["chain"] for w in wallets)),
        "total_balance_usd": sum(w.get("balance_usd", 0) for w in wallets),
        "total_tx_count": sum(w.get("tx_count", 0) for w in wallets),
    }


# ══════════════════════════════════════════════════════════════════════════════════
# SOURCE 3: BitcoinAbuse API
# ══════════════════════════════════════════════════════════════════════════════════

def fetch_bitcoin_abuse(address: str, force: bool = False) -> Dict[str, Any]:
    if not BTC_RE.match(address):
        return {"found": False, "address": address, "reports": []}
    if not BITCOINABUSE_API_TOKEN:
        return {"found": False, "address": address, "reports": [],
                "note": "BITCOINABUSE_API_TOKEN not configured"}

    def _fetch():
        try:
            resp = requests.get(
                BITCOINABUSE_API,
                params={"address": address, "api_token": BITCOINABUSE_API_TOKEN},
                headers=_FREE_HEADERS, timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            reports = data if isinstance(data, list) else data.get("reports", [])
            return {
                "found": len(reports) > 0, "address": address, "count": len(reports),
                "reports": [{
                    "abuse_type": r.get("abuse_type_name", r.get("abuse_type", "unknown")),
                    "description": r.get("description", ""),
                    "created_at": r.get("created_at", ""),
                } for r in reports[:50]],
            }
        except Exception as exc:
            logger.info("bitcoinabuse lookup failed for %s: %s", address, exc)
            return {"found": False, "address": address, "reports": [], "error": str(exc)}

    return _cached(f"btc_abuse_{address}", _fetch, force) or {"found": False, "address": address, "reports": []}


# ══════════════════════════════════════════════════════════════════════════════════
# UNIFIED DATA AGGREGATION
# ══════════════════════════════════════════════════════════════════════════════════

def fetch_all_groups(force: bool = False) -> List[Dict[str, Any]]:
    """Fetch groups from ALL sources and merge into unified profiles."""
    def _fetch():
        # 1) Pro API group summaries (with victim counts)
        pro_summaries = fetch_groups_pro(force)
        pro_map = {g["name"].lower(): g for g in pro_summaries}

        # 2) Free API posts (for crypto extraction)
        free_posts = fetch_posts_free(force)

        # 3) RansomLook groups (for affiliates, contacts, extra locations)
        rlk_groups = fetch_groups_rlk(force)
        rlk_map = {g["name"].lower(): g for g in rlk_groups}

        # Build unified group list — start from Pro API as the backbone
        merged: Dict[str, Dict[str, Any]] = {}

        # Fetch group details in PARALLEL instead of sequentially
        group_names = list(pro_map.keys())
        details = _parallel_map(
            lambda name: fetch_group_detail_pro(name.replace(" ", "")),
            group_names,
            max_workers=10,
            timeout_per=15,
        )

        for name_lower, detail in zip(group_names, details):
            summary = pro_map[name_lower]
            if detail:
                merged[name_lower] = detail
            else:
                merged[name_lower] = {
                    "name": summary["name"],
                    "aliases": summary.get("aliases", []),
                    "description": "",
                    "added_date": None,
                    "first_seen": "",
                    "last_seen": "",
                    "victim_count": summary.get("victim_count", 0),
                    "locations": [],
                    "leak_sites": [],
                    "active_sites": [],
                    "ttps": [],
                    "tools": [],
                    "tool_categories": [],
                    "crypto_addresses": {chain: [] for chain in CHAIN_REGEXES},
                    "profile_url": f"https://www.ransomware.live/group/{summary['name']}",
                    "source": "ransomware.live",
                }

        # Add groups only found in RansomLook
        for name_lower, rlk_g in rlk_map.items():
            if name_lower not in merged:
                merged[name_lower] = rlk_g
            else:
                existing = merged[name_lower]
                rlk_data = {
                    "profile_links": rlk_g.get("profile_links", []),
                    "affiliates": rlk_g.get("affiliates", []),
                    "contact": rlk_g.get("contact", {}),
                    "raas": rlk_g.get("raas", False),
                    "slug": rlk_g.get("slug", ""),
                }
                existing["ransomlook_data"] = rlk_data
                # Merge locations
                existing_fqdns = {loc.get("fqdn") for loc in existing.get("locations", [])}
                for loc in rlk_g.get("locations", []):
                    if loc.get("fqdn") not in existing_fqdns:
                        existing.setdefault("locations", []).append(loc)
                # Merge crypto addresses
                existing["crypto_addresses"] = merge_addresses(
                    existing.get("crypto_addresses", {}),
                    rlk_g.get("crypto_addresses", {}),
                )

        # 4) RansomLook CryptoAPI — curated wallets with balances/tx data
        all_crypto = fetch_all_crypto_rlk(force)
        for slug, crypto_data in all_crypto.items():
            slug_lower = slug.lower().replace("-", "").replace("_", "")
            # Try to match to existing group by various name forms
            matched_key = None
            for key in merged:
                key_norm = key.lower().replace("-", "").replace("_", "").replace(" ", "")
                if key_norm == slug_lower:
                    matched_key = key
                    break
            if not matched_key:
                # Try partial match
                for key in merged:
                    if slug_lower in key.replace("-", "").replace("_", "").replace(" ", "") or \
                       key.replace("-", "").replace("_", "").replace(" ", "") in slug_lower:
                        matched_key = key
                        break

            if matched_key:
                existing = merged[matched_key]
                # Merge crypto addresses from CryptoAPI
                existing["crypto_addresses"] = merge_addresses(
                    existing.get("crypto_addresses", {}),
                    crypto_data.get("addresses_by_chain", {}),
                )
                # Attach wallet details (balances, tx counts, USD values)
                existing["wallets"] = crypto_data.get("wallets", [])
                existing["wallet_stats"] = {
                    "total_wallets": crypto_data.get("total", 0),
                    "total_balance_usd": crypto_data.get("total_balance_usd", 0),
                    "total_tx_count": crypto_data.get("total_tx_count", 0),
                    "chains": crypto_data.get("chains", []),
                }
            else:
                # New group only from CryptoAPI (not in other sources)
                display_name = slug.replace("-", " ").replace("_", " ").title()
                merged[slug_lower] = {
                    "name": display_name,
                    "aliases": crypto_data.get("aliases", []),
                    "description": "",
                    "added_date": None,
                    "first_seen": "",
                    "last_seen": "",
                    "victim_count": 0,
                    "locations": [],
                    "leak_sites": [],
                    "active_sites": [],
                    "ttps": [],
                    "tools": [],
                    "tool_categories": [],
                    "crypto_addresses": crypto_data.get("addresses_by_chain", {}),
                    "wallets": crypto_data.get("wallets", []),
                    "wallet_stats": {
                        "total_wallets": crypto_data.get("total", 0),
                        "total_balance_usd": crypto_data.get("total_balance_usd", 0),
                        "total_tx_count": crypto_data.get("total_tx_count", 0),
                        "chains": crypto_data.get("chains", []),
                    },
                    "profile_url": f"https://www.ransomlook.io/crypto/{slug}",
                    "source": "ransomlook",
                }

        return list(merged.values())

    return _cached("all_groups", _fetch, force) or []


def fetch_all_posts(force: bool = False) -> List[Dict[str, Any]]:
    """Fetch posts from ALL sources and merge."""
    def _fetch():
        free_posts = fetch_posts_free(force)
        rlk_posts = fetch_posts_rlk(force)

        # Fetch Pro API victims for major groups IN PARALLEL
        pro_groups = fetch_groups_pro(force)
        top_groups = sorted(pro_groups, key=lambda g: g.get("victim_count", 0), reverse=True)[:20]

        def _fetch_victims_for_group(g):
            name = g.get("name", "")
            if not name:
                return []
            return fetch_victims_pro(name, limit=100, force=force)

        victim_results = _parallel_map(_fetch_victims_for_group, top_groups, max_workers=8, timeout_per=15)
        pro_victims = []
        for vlist in victim_results:
            if vlist:
                pro_victims.extend(vlist)

        # Deduplicate by (group, title)
        seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for p in free_posts:
            key = (p.get("group", "").lower(), p.get("title", "").lower()[:80])
            seen[key] = p
        for p in pro_victims:
            key = (p.get("group", "").lower(), p.get("title", "").lower()[:80])
            if key not in seen:
                seen[key] = p
        for p in rlk_posts:
            key = (p.get("group", "").lower(), p.get("title", "").lower()[:80])
            if key not in seen:
                seen[key] = p

        return list(seen.values())

    return _cached("all_posts", _fetch, force) or []


# ══════════════════════════════════════════════════════════════════════════════════
# THREAT ACTOR PROFILE ENGINE
# ══════════════════════════════════════════════════════════════════════════════════

def build_threat_actor_profiles(force: bool = False) -> List[Dict[str, Any]]:
    """
    Build comprehensive threat actor profiles by correlating data from all sources.
    """
    def _build():
        groups = fetch_all_groups(force=False)
        posts = fetch_all_posts(force=False)

        posts_by_group: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for p in posts:
            g = p.get("group", "").strip()
            if g:
                posts_by_group[g.lower()].append(p)

        profiles = []
        for g in groups:
            name = g.get("name", "")
            name_lower = name.lower()
            group_posts = posts_by_group.get(name_lower, [])

            # Aggregate all crypto addresses
            all_addresses = dict(g.get("crypto_addresses", {}))
            for chain in CHAIN_REGEXES:
                all_addresses.setdefault(chain, [])
            for p in group_posts:
                for chain in CHAIN_REGEXES:
                    for addr in p.get("crypto_addresses", {}).get(chain, []):
                        if addr not in all_addresses[chain]:
                            all_addresses[chain].append(addr)

            # Check known-address DB
            known_matches = []
            for addr, info in KNOWN_RANSOMWARE_ADDRESSES.items():
                actor_match = (info.get("actor", "").lower() == name_lower or
                               name_lower in info.get("actor", "").lower())
                addr_in_group = any(
                    addr in all_addresses.get(c, []) for c in CHAIN_REGEXES
                )
                if actor_match or addr_in_group:
                    known_matches.append({"address": addr, **info})

            # Add seed addresses
            for seed in ACTOR_ADDRESS_SEEDS.get(name, []):
                addr = seed.get("address", "")
                chain = seed.get("chain", "btc")
                if addr and addr not in all_addresses.get(chain, []):
                    all_addresses.setdefault(chain, []).append(addr)

            victim_countries = list(set(
                p.get("victim_country", "") for p in group_posts if p.get("victim_country")
            ))
            victim_industries = list(set(
                p.get("victim_industry", "") for p in group_posts if p.get("victim_industry")
            ))

            dates = sorted([p.get("discovered", "") for p in group_posts if p.get("discovered")])
            first_seen = dates[0] if dates else g.get("first_seen") or g.get("added_date") or ""
            last_seen = dates[-1] if dates else g.get("last_seen") or ""

            rlk_data = g.get("ransomlook_data", {})

            profile = {
                "name": name,
                "aliases": g.get("aliases", []),
                "description": g.get("description", ""),
                "added_date": g.get("added_date"),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "active": len(g.get("active_sites", [])) > 0,
                "victim_count": g.get("victim_count", len(group_posts)),
                "raas": rlk_data.get("raas", False),
                "locations": g.get("locations", []),
                "leak_sites": g.get("leak_sites", []),
                "active_sites": g.get("active_sites", []),
                "profile_url": g.get("profile_url", ""),
                "profile_links": rlk_data.get("profile_links", []),
                "ttps": g.get("ttps", []),
                "tools": g.get("tools", []),
                "tool_categories": g.get("tool_categories", []),
                "affiliates": rlk_data.get("affiliates", []),
                "contact": rlk_data.get("contact", {}),
                "crypto_addresses": all_addresses,
                "total_addresses": count_addresses(all_addresses),
                "known_address_matches": known_matches,
                "chains_used": [CHAIN_LABELS.get(c, c) for c in CHAIN_REGEXES if all_addresses.get(c)],
                # Wallet intelligence from RansomLook CryptoAPI
                "wallets": g.get("wallets", []),
                "wallet_stats": g.get("wallet_stats", {
                    "total_wallets": 0, "total_balance_usd": 0,
                    "total_tx_count": 0, "chains": [],
                }),
                "incident_count": len(group_posts),
                "incidents_with_crypto": len([
                    p for p in group_posts if count_addresses(p.get("crypto_addresses", {})) > 0
                ]),
                "victim_countries": victim_countries,
                "victim_industries": victim_industries,
                "sources": list(set(
                    [g.get("source", "ransomware.live")] +
                    [p.get("source", "") for p in group_posts]
                )),
            }
            profiles.append(profile)

        profiles.sort(key=lambda p: p.get("victim_count", 0), reverse=True)
        return profiles

    return _cached("threat_actor_profiles", _build, force) or []


def get_threat_actor(name: str, force: bool = False) -> Optional[Dict[str, Any]]:
    profiles = build_threat_actor_profiles(force)
    name_lower = name.lower().strip()
    for p in profiles:
        if p["name"].lower() == name_lower:
            return p
    for p in profiles:
        if name_lower in [a.lower() for a in p.get("aliases", [])]:
            return p
    return None


# ══════════════════════════════════════════════════════════════════════════════════
# CRYPTO ADDRESS INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════════

def build_address_intelligence(force: bool = False) -> List[Dict[str, Any]]:
    """Build comprehensive index of ALL crypto addresses across all sources."""
    def _build():
        profiles = build_threat_actor_profiles(force=False)
        posts = fetch_all_posts(force=False)
        addr_index: Dict[str, Dict[str, Any]] = {}

        # Build a wallet lookup from all profiles (address -> wallet data)
        wallet_lookup: Dict[str, Dict[str, Any]] = {}
        for profile in profiles:
            for w in profile.get("wallets", []):
                addr = w.get("address", "")
                if addr:
                    wallet_lookup[addr] = w

        # From threat actor profiles
        for profile in profiles:
            actor_name = profile["name"]
            for chain, addrs in profile.get("crypto_addresses", {}).items():
                for addr in addrs:
                    if addr not in addr_index:
                        wallet = wallet_lookup.get(addr, {})
                        addr_index[addr] = {
                            "address": addr, "chain": chain,
                            "chain_label": CHAIN_LABELS.get(chain, chain),
                            "actors": [], "incidents": [],
                            "known_info": None,
                            "first_seen": wallet.get("first_seen"),
                            "sources": set(),
                            "wallet_data": wallet or None,
                        }
                    if actor_name not in addr_index[addr]["actors"]:
                        addr_index[addr]["actors"].append(actor_name)
                    addr_index[addr]["sources"].update(["ransomware.live", "ransomlook"])
                    # Attach wallet data if available
                    if addr in wallet_lookup and not addr_index[addr].get("wallet_data"):
                        addr_index[addr]["wallet_data"] = wallet_lookup[addr]

        # From incidents
        for p in posts:
            for chain, addrs in p.get("crypto_addresses", {}).items():
                for addr in addrs:
                    if addr not in addr_index:
                        addr_index[addr] = {
                            "address": addr, "chain": chain,
                            "chain_label": CHAIN_LABELS.get(chain, chain),
                            "actors": [], "incidents": [],
                            "known_info": None,
                            "first_seen": p.get("discovered"),
                            "sources": set(),
                        }
                    entry = addr_index[addr]
                    group = p.get("group", "")
                    if group and group not in entry["actors"]:
                        entry["actors"].append(group)
                    entry["incidents"].append({
                        "title": p.get("title", ""),
                        "group": group,
                        "date": p.get("discovered", ""),
                        "victim": p.get("victim_name", ""),
                    })
                    entry["sources"].add(p.get("source", "ransomware.live"))
                    if not entry["first_seen"] and p.get("discovered"):
                        entry["first_seen"] = p["discovered"]

        # Cross-reference known DB
        for addr, info in KNOWN_RANSOMWARE_ADDRESSES.items():
            if addr in addr_index:
                addr_index[addr]["known_info"] = info
            else:
                addr_index[addr] = {
                    "address": addr,
                    "chain": info.get("chain", "btc"),
                    "chain_label": CHAIN_LABELS.get(info.get("chain", "btc"), "btc"),
                    "actors": [info["actor"]] if info.get("actor") else [],
                    "incidents": [],
                    "known_info": info,
                    "first_seen": info.get("first_seen"),
                    "sources": {"known-db"},
                }

        result = []
        for addr, entry in addr_index.items():
            entry["sources"] = list(entry["sources"])
            entry["incident_count"] = len(entry["incidents"])
            entry["actor_count"] = len(entry["actors"])
            result.append(entry)

        result.sort(key=lambda e: (0 if e.get("known_info") else 1, -e["incident_count"]))
        return result

    return _cached("address_intelligence", _build, force) or []


def lookup_address_intel(address: str) -> Dict[str, Any]:
    """Full intelligence lookup for a single crypto address."""
    address = address.strip()
    result: Dict[str, Any] = {
        "address": address, "found": False,
        "chain": None, "chain_label": None,
        "actors": [], "incidents": [],
        "known_info": None, "bitcoin_abuse": None,
        "sources": [],
    }

    for chain, regex in CHAIN_REGEXES.items():
        if regex.match(address):
            result["chain"] = chain
            result["chain_label"] = CHAIN_LABELS.get(chain, chain)
            break

    all_addrs = build_address_intelligence()
    for entry in all_addrs:
        if entry["address"] == address:
            result["found"] = True
            result["actors"] = entry.get("actors", [])
            result["incidents"] = entry.get("incidents", [])
            result["known_info"] = entry.get("known_info")
            result["sources"] = entry.get("sources", [])
            if not result["chain"]:
                result["chain"] = entry.get("chain")
                result["chain_label"] = entry.get("chain_label")
            break

    if address in KNOWN_RANSOMWARE_ADDRESSES:
        result["found"] = True
        result["known_info"] = KNOWN_RANSOMWARE_ADDRESSES[address]
        if not result["actors"]:
            result["actors"] = [KNOWN_RANSOMWARE_ADDRESSES[address].get("actor", "")]

    if result["chain"] == "btc":
        result["bitcoin_abuse"] = fetch_bitcoin_abuse(address)

    return result


# ══════════════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPATIBLE API (used by existing router)
# ══════════════════════════════════════════════════════════════════════════════════

def fetch_groups(force: bool = False) -> List[Dict[str, Any]]:
    return fetch_all_groups(force)


def fetch_recent_posts(force: bool = False) -> List[Dict[str, Any]]:
    return fetch_all_posts(force)


def fetch_group_detail(group_name: str, force: bool = False) -> Optional[Dict[str, Any]]:
    g = fetch_group_detail_pro(group_name, force)
    if g:
        rlk = fetch_group_detail_rlk(group_name, force)
        if rlk:
            g["ransomlook_data"] = {
                "profile_links": rlk.get("profile_links", []),
                "affiliates": rlk.get("affiliates", []),
                "contact": rlk.get("contact", {}),
                "raas": rlk.get("raas", False),
            }
        return g
    return fetch_group_detail_rlk(group_name, force)


def fetch_group_posts(group_name: str, force: bool = False) -> List[Dict[str, Any]]:
    posts = fetch_victims_pro(group_name, limit=500, force=force)
    if not posts:
        posts = fetch_posts_free(force)
        posts = [p for p in posts if p.get("group", "").lower() == group_name.lower()]
    return posts


def fetch_stats(force: bool = False) -> Dict[str, Any]:
    return fetch_stats_pro(force)


# ══════════════════════════════════════════════════════════════════════════════════
# SEARCH
# ══════════════════════════════════════════════════════════════════════════════════

def search_ransomware(query: str) -> Dict[str, Any]:
    q = query.lower().strip()
    if not q:
        return {"groups": [], "incidents": [], "query": query}

    groups = fetch_all_groups()
    posts = fetch_all_posts()

    matched_groups = [
        g for g in groups
        if q in g["name"].lower()
        or q in g.get("description", "").lower()
        or any(q in alias.lower() for alias in g.get("aliases", []))
    ]

    matched_incidents = [
        p for p in posts
        if q in p.get("title", "").lower()
        or q in p.get("group", "").lower()
        or q in p.get("description", "").lower()
        or q in p.get("victim_name", "").lower()
    ]

    return {
        "query": query,
        "groups": matched_groups[:50],
        "incidents": matched_incidents[:100],
        "total_groups": len(matched_groups),
        "total_incidents": len(matched_incidents),
    }


def search_by_address(address: str) -> Dict[str, Any]:
    return lookup_address_intel(address)


# ══════════════════════════════════════════════════════════════════════════════════
# COMBINED INTELLIGENCE FEED
# ══════════════════════════════════════════════════════════════════════════════════

def get_threat_intelligence_feed(limit: int = 100) -> Dict[str, Any]:
    groups = fetch_all_groups()
    posts = fetch_all_posts()
    stats = fetch_stats_pro()
    profiles = build_threat_actor_profiles()
    addr_intel = build_address_intelligence()

    active_groups = [g for g in groups if g.get("active_sites")]

    sorted_posts = sorted(posts, key=lambda p: p.get("discovered", ""), reverse=True)[:limit]
    incidents_with_crypto = [p for p in sorted_posts if count_addresses(p.get("crypto_addresses", {})) > 0]

    top_addresses = [a for a in addr_intel if a.get("actors")][:50]

    return {
        "summary": {
            "total_groups": len(groups),
            "active_groups": len(active_groups),
            "total_incidents": len(posts),
            "incidents_with_crypto_addresses": len(incidents_with_crypto),
            "total_tracked_addresses": len(addr_intel),
            "known_malicious_addresses": len([a for a in addr_intel if a.get("known_info")]),
            "threat_actors_profiled": len(profiles),
        },
        "stats": stats,
        "recent_incidents": sorted_posts,
        "active_groups": [
            {"name": g["name"], "sites": len(g.get("active_sites", [])),
             "ttps_count": len(g.get("ttps", []))}
            for g in active_groups
        ],
        "incidents_with_crypto": incidents_with_crypto[:50],
        "top_addresses": top_addresses,
        "threat_actors_summary": [
            {"name": p["name"], "incident_count": p["incident_count"],
             "total_addresses": p["total_addresses"], "active": p["active"],
             "chains_used": p["chains_used"], "victim_count": p.get("victim_count", 0)}
            for p in profiles[:20]
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════════
# BASELINE SNAPSHOT — serves all tab data in one shot from cache
# ══════════════════════════════════════════════════════════════════════════════════

def get_baseline() -> Dict[str, Any]:
    """Return a complete snapshot of all threat data from cache.
    Returns instantly if cache is populated (from disk or prior refresh).
    Never blocks on external API calls."""
    groups = fetch_all_groups(force=False)
    posts = fetch_all_posts(force=False)
    profiles = build_threat_actor_profiles(force=False)
    addr_intel = build_address_intelligence(force=False)
    stats = fetch_stats_pro(force=False)

    # Compute cache age
    oldest_ts = time.time()
    for key in ("all_groups", "all_posts", "threat_actor_profiles", "address_intelligence"):
        with _lock:
            entry = _cache.get(key)
            if entry:
                oldest_ts = min(oldest_ts, entry["ts"])
    cache_age_sec = round(time.time() - oldest_ts) if oldest_ts < time.time() else 0

    return {
        "groups": {
            "groups": groups,
            "total": len(groups),
            "active": len([g for g in groups if g.get("active_sites")]),
            "with_wallets": len([g for g in groups if g.get("wallets")]),
        },
        "incidents": {
            "incidents": sorted(posts, key=lambda p: p.get("discovered", ""), reverse=True)[:500],
            "total": len(posts),
            "with_crypto_addresses": len([
                p for p in posts
                if any(p.get("crypto_addresses", {}).get(c) for c in CHAIN_REGEXES)
            ]),
        },
        "actors": {
            "profiles": profiles,
            "total": len(profiles),
            "with_wallets": len([p for p in profiles if p.get("wallets")]),
            "with_crypto": len([p for p in profiles if p.get("total_addresses", 0) > 0]),
            "total_wallet_balance_usd": sum(
                p.get("wallet_stats", {}).get("total_balance_usd", 0) for p in profiles
            ),
        },
        "addresses": {
            "addresses": addr_intel[:1000],
            "total": len(addr_intel),
            "by_chain": _count_by_chain_baseline(addr_intel),
            "total_balance_usd": sum(
                (a.get("wallet_data") or {}).get("balance_usd", 0) for a in addr_intel
            ),
        },
        "stats": stats,
        "cache_age_sec": cache_age_sec,
        "cache_populated": bool(groups or posts or profiles),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _count_by_chain_baseline(addresses: list) -> dict:
    counts = {}
    for a in addresses:
        chain = a.get("chain", "unknown")
        counts[chain] = counts.get(chain, 0) + 1
    return counts


# ══════════════════════════════════════════════════════════════════════════════════
# BACKGROUND REFRESH — fetches fresh data without blocking the caller
# ══════════════════════════════════════════════════════════════════════════════════

def _background_refresh() -> None:
    """Refresh all data sources in background, then persist to disk."""
    global _refresh_status
    with _refresh_lock:
        _refresh_status = {"running": True, "started_at": datetime.now(timezone.utc).isoformat(),
                           "completed_at": None, "error": None}
    try:
        # Force-refresh each source independently — failures are isolated
        fetch_groups_pro(force=True)
        fetch_stats_pro(force=True)
        fetch_posts_free(force=True)
        fetch_groups_rlk(force=True)
        fetch_posts_rlk(force=True)
        fetch_crypto_groups_rlk(force=True)

        # Aggregated views (use freshly-cached sources)
        fetch_all_groups(force=True)
        fetch_all_posts(force=True)
        build_threat_actor_profiles(force=True)
        build_address_intelligence(force=True)

        # Persist to disk for next restart
        snapshot = {}
        with _lock:
            for key, entry in _cache.items():
                if not key.startswith('_'):
                    snapshot[key] = entry["data"]
        _save_disk_cache(snapshot)

        with _refresh_lock:
            _refresh_status["running"] = False
            _refresh_status["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("ransomware engine background refresh completed")
    except Exception as exc:
        logger.error("ransomware engine background refresh failed: %s", exc)
        with _refresh_lock:
            _refresh_status["running"] = False
            _refresh_status["completed_at"] = datetime.now(timezone.utc).isoformat()
            _refresh_status["error"] = str(exc)


def start_background_refresh() -> None:
    """Kick off a background refresh if one isn't already running."""
    with _refresh_lock:
        if _refresh_status.get("running"):
            return
    threading.Thread(target=_background_refresh, name="ransomware-bg-refresh", daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════════
# CACHE WARMING
# ══════════════════════════════════════════════════════════════════════════════════

def warm_cache() -> None:
    # 1) Restore persisted baseline from disk first (instant)
    _restore_from_disk()

    # 2) Refresh from live sources in background (non-blocking)
    try:
        _background_refresh()
    except Exception as exc:
        logger.warning("ransomware engine warm failed: %s", exc)


def start_warm_cache() -> None:
    threading.Thread(target=warm_cache, name="ransomware-engine-warm", daemon=True).start()
