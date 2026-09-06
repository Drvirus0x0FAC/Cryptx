"""
Public/free enrichment providers for cryptocurrency investigations.

This module keeps third-party OSINT enrichment separate from core chain lookup
logic. Each provider returns normalized, provenance-rich records and degrades
cleanly when a public endpoint is down, rate-limited, or not configured.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
import config as _config

DB_PATH = _config.DB_PATH
DEFAULT_TTL_SECONDS = int(os.getenv("PUBLIC_ENRICHMENT_TTL", "21600"))
ENRICHMENT_CACHE_VERSION = "v2"

BTC_RE = re.compile(r"^(bc1[a-zA-HJ-NP-Z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
EVM_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "TRX": "tron",
    "SOL": "solana",
    "LTC": "litecoin",
    "DOGE": "dogecoin",
    "BCH": "bitcoin-cash",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "MATIC": "matic-network",
    "AVAX": "avalanche-2",
    "ADA": "cardano",
    "DOT": "polkadot",
    "ATOM": "cosmos",
    "NEAR": "near",
    "APT": "aptos",
    "SUI": "sui",
    "TON": "the-open-network",
    "ALGO": "algorand",
    "XLM": "stellar",
    "USDT": "tether",
    "USDC": "usd-coin",
}

DEFILLAMA_CHAIN_MAP = {
    "ETH": "Ethereum",
    "BTC": "Bitcoin",
    "TRX": "Tron",
    "SOL": "Solana",
    "BSC": "BSC",
    "BNB": "BSC",
    "MATIC": "Polygon",
    "POLYGON": "Polygon",
    "ARB": "Arbitrum",
    "ARBITRUM": "Arbitrum",
    "OP": "Optimism",
    "OPTIMISM": "Optimism",
    "BASE": "Base",
    "AVAX": "Avalanche",
}

OPEN_DATASETS = [
    {
        "id": "ransomwhere",
        "label": "OpenSanctions Ransomwhere",
        "url": "https://data.opensanctions.org/datasets/latest/ransomwhere/targets.simple.csv",
        "category": "ransomware",
    },
    {
        "id": "opensanctions_sanctions",
        "label": "OpenSanctions Consolidated Sanctions",
        "url": "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv",
        "category": "sanctions",
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _addr(value: Any) -> str:
    return str(value or "").strip().lower()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip().strip("\"'")


def _source(name: str, url: str, ok: bool, detail: str = "", configured: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "url": url,
        "ok": ok,
        "configured": configured,
        "detail": detail,
        "checked_at": _now(),
    }


def init_public_enrichment_tables() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS public_enrichment_cache (
                cache_key  TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS public_enrichment_feed_items (
                address     TEXT NOT NULL,
                chain       TEXT DEFAULT '',
                category    TEXT NOT NULL,
                label       TEXT NOT NULL,
                source      TEXT NOT NULL,
                source_url  TEXT DEFAULT '',
                evidence    TEXT DEFAULT '{}',
                updated_at  TEXT NOT NULL,
                PRIMARY KEY(address, category, label, source)
            );
            CREATE INDEX IF NOT EXISTS idx_public_feed_address ON public_enrichment_feed_items(address);
            """
        )


def _cache_get(key: str, ttl: int = DEFAULT_TTL_SECONDS) -> Optional[dict[str, Any]]:
    with _conn() as con:
        row = con.execute("SELECT value, fetched_at FROM public_enrichment_cache WHERE cache_key = ?", (key,)).fetchone()
    if not row:
        return None
    if ttl > 0 and time.time() - int(row["fetched_at"]) > ttl:
        return None
    try:
        return json.loads(row["value"])
    except Exception:
        return None


def _cache_set(key: str, value: dict[str, Any]) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO public_enrichment_cache(cache_key, value, fetched_at)
               VALUES (?, ?, ?)
               ON CONFLICT(cache_key) DO UPDATE SET value=excluded.value, fetched_at=excluded.fetched_at""",
            (key, json.dumps(value, default=str), int(time.time())),
        )


def _http_json(url: str, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None, timeout: int = 20) -> tuple[Any, Optional[str]]:
    try:
        resp = requests.get(url, params=params, headers=headers or {"User-Agent": "CryptoOSINT/2.0"}, timeout=timeout)
        if resp.status_code >= 400:
            return None, f"HTTP {resp.status_code}"
        return resp.json(), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _http_text(url: str, timeout: int = 45) -> tuple[str, Optional[str]]:
    try:
        resp = requests.get(url, headers={"User-Agent": "CryptoOSINT/2.0"}, timeout=timeout)
        if resp.status_code >= 400:
            return "", f"HTTP {resp.status_code}"
        return resp.text, None
    except Exception as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__}: {exc}"


def refresh_public_feeds() -> dict[str, Any]:
    """Download open datasets into the local feed table."""
    init_public_enrichment_tables()
    reports: list[dict[str, Any]] = []
    imported = 0
    wallet_re = re.compile(r"(0x[a-fA-F0-9]{40}|bc1[a-z0-9]{20,}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|T[1-9A-HJ-NP-Za-km-z]{33})")

    with _conn() as con:
        for dataset in OPEN_DATASETS:
            text, err = _http_text(dataset["url"])
            report = {"dataset": dataset["id"], "source": dataset["label"], "ok": not err, "items": 0, "error": err}
            if err:
                reports.append(report)
                continue
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                raw = ";".join(str(row.get(k) or "") for k in ("addresses", "identifiers", "name", "aliases"))
                wallets = sorted(set(wallet_re.findall(raw)))
                if not wallets:
                    continue
                label = row.get("name") or row.get("id") or dataset["label"]
                evidence = {
                    "dataset": dataset["id"],
                    "entity_id": row.get("id", ""),
                    "schema": row.get("schema", ""),
                    "sanctions": row.get("sanctions", ""),
                    "first_seen": row.get("first_seen", ""),
                    "last_seen": row.get("last_seen", ""),
                }
                for wallet in wallets:
                    con.execute(
                        """INSERT OR REPLACE INTO public_enrichment_feed_items
                           (address, chain, category, label, source, source_url, evidence, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            _addr(wallet), "", dataset["category"], label,
                            dataset["label"], dataset["url"], json.dumps(evidence), _now(),
                        ),
                    )
                    imported += 1
                    report["items"] += 1
            reports.append(report)
    return {"refreshed_at": _now(), "imported": imported, "sources": reports}


def _feeds_stale(max_age_days: int = 7) -> bool:
    """True if the open-dataset feed table is empty or older than max_age_days."""
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT COUNT(*) AS n, MAX(updated_at) AS u FROM public_enrichment_feed_items"
            ).fetchone()
    except Exception:  # noqa: BLE001
        return True
    if not row or not row["n"]:
        return True
    try:
        ts = datetime.fromisoformat(str(row["u"]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() > max_age_days * 86400
    except Exception:  # noqa: BLE001
        return True


def refresh_public_feeds_if_stale(max_age_days: int = 7) -> Optional[dict[str, Any]]:
    """Download the open datasets only when missing or stale (avoids re-downloading
    on every restart)."""
    init_public_enrichment_tables()
    if _feeds_stale(max_age_days):
        return refresh_public_feeds()
    return None


def start_feed_refresh(max_age_days: int = 7) -> None:
    """Kick off a non-blocking background refresh of the open OSINT datasets."""
    import threading

    def _run() -> None:
        try:
            refresh_public_feeds_if_stale(max_age_days)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, name="public-feed-refresh", daemon=True).start()


def _local_feed_matches(address: str) -> list[dict[str, Any]]:
    a = _addr(address)
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM public_enrichment_feed_items WHERE address = ? ORDER BY category, source",
            (a,),
        ).fetchall()
    out = []
    for row in rows:
        try:
            evidence = json.loads(row["evidence"] or "{}")
        except Exception:
            evidence = {}
        out.append({
            "category": row["category"],
            "label": row["label"],
            "source": row["source"],
            "source_url": row["source_url"],
            "confidence": 0.95,
            "method": "open_dataset_exact_address_match",
            "evidence": evidence,
        })
    return out


def _bitcoinabuse(address: str) -> dict[str, Any]:
    token = _env("BITCOINABUSE_API_TOKEN") or _env("BITCOINABUSE_API_KEY")
    url = "https://www.bitcoinabuse.com/api/reports/check"
    if not BTC_RE.match(address or ""):
        return {"source": _source("BitcoinAbuse", url, True, "not a BTC address"), "found": False, "count": 0, "records": []}
    if not token:
        return {"source": _source("BitcoinAbuse", url, False, "BITCOINABUSE_API_TOKEN not configured", configured=False), "found": False, "count": 0, "records": []}
    data, err = _http_json(url, params={"address": address, "api_token": token})
    if err:
        return {"source": _source("BitcoinAbuse", url, False, err), "found": False, "count": 0, "records": []}
    count = int((data or {}).get("count") or (data or {}).get("total_report_count") or 0)
    recent = (data or {}).get("recent") or (data or {}).get("reports") or []
    return {
        "source": _source("BitcoinAbuse", url, True),
        "found": count > 0,
        "count": count,
        "records": recent[:10] if isinstance(recent, list) else [],
    }


def _cryptoscamdb(address: str) -> dict[str, Any]:
    normalized = str(address or "").strip()
    # CryptoScamDB's hosted API can be intermittent. Use only canonical lookup
    # forms so transient upstream errors do not get amplified by bad fallback URLs.
    urls = [f"https://api.cryptoscamdb.org/v1/check/{normalized}"]
    errors: list[str] = []
    for url in [u for u in urls if u]:
        data, err = _http_json(url)
        if err:
            errors.append(f"{url}: {err}")
            continue
        records = []
        if isinstance(data, dict):
            if isinstance(data.get("result"), list):
                records = data["result"]
            elif isinstance(data.get("entries"), list):
                records = data["entries"]
            elif data.get("success") and data.get("result"):
                records = [data["result"]]
        found = bool(records) or bool(isinstance(data, dict) and data.get("scam"))
        return {
            "source": _source("CryptoScamDB", url, True),
            "found": found,
            "count": len(records) if records else int(found),
            "records": records[:10],
        }
    return {
        "source": _source(
            "CryptoScamDB",
            "https://cryptoscamdb.org/",
            False,
            "public API unavailable; retry later" if errors else "unavailable",
        ),
        "found": False,
        "count": 0,
        "records": [],
        "transient": True,
    }


def _dune_labels(address: str) -> dict[str, Any]:
    api_key = _env("DUNE_API_KEY")
    query_id = _env("DUNE_LABELS_QUERY_ID")
    url = f"https://api.dune.com/api/v1/query/{query_id}/results" if query_id else "https://api.dune.com/api/v1/query/{DUNE_LABELS_QUERY_ID}/results"
    if not api_key or not query_id:
        return {"source": _source("Dune Labels", url, False, "DUNE_API_KEY and DUNE_LABELS_QUERY_ID not configured", configured=False), "labels": []}
    data, err = _http_json(url, params={"address": address}, headers={"X-Dune-API-Key": api_key, "User-Agent": "CryptoOSINT/2.0"})
    if err:
        return {"source": _source("Dune Labels", url, False, err), "labels": []}
    rows = (((data or {}).get("result") or {}).get("rows") or [])
    labels = []
    for row in rows[:25]:
        labels.append({
            "label": row.get("label") or row.get("name") or row.get("address_label") or "",
            "category": row.get("category") or row.get("label_type") or "label",
            "source": row.get("source") or "Dune",
            "confidence": 0.75,
            "method": "dune_curated_label_query",
        })
    return {"source": _source("Dune Labels", url, True), "labels": [l for l in labels if l["label"]]}


def _coingecko_prices(intel: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not intel:
        return {"source": _source("CoinGecko", "https://api.coingecko.com/api/v3/simple/price", True, "no intel supplied"), "assets": {}, "portfolio_usd": None}
    symbols = {str(intel.get("balance_unit") or intel.get("chain") or "").upper()}
    for token in intel.get("tokens") or []:
        sym = str(token.get("symbol") or "").upper()
        if sym:
            symbols.add(sym)
    ids = {sym: COINGECKO_IDS[sym] for sym in symbols if sym in COINGECKO_IDS}
    if not ids:
        return {"source": _source("CoinGecko", "https://api.coingecko.com/api/v3/simple/price", True, "no mapped assets"), "assets": {}, "portfolio_usd": None}
    url = "https://api.coingecko.com/api/v3/simple/price"
    data, err = _http_json(url, params={"ids": ",".join(ids.values()), "vs_currencies": "usd", "include_24hr_change": "true"})
    if err:
        return {"source": _source("CoinGecko", url, False, err), "assets": {}, "portfolio_usd": None}
    assets = {}
    portfolio = 0.0
    unit = str(intel.get("balance_unit") or intel.get("chain") or "").upper()
    for sym, cid in ids.items():
        price = float(((data or {}).get(cid) or {}).get("usd") or 0)
        assets[sym] = {
            "coingecko_id": cid,
            "usd": price,
            "usd_24h_change": ((data or {}).get(cid) or {}).get("usd_24h_change"),
        }
        if sym == unit:
            portfolio += float(intel.get("balance") or 0) * price
    for token in intel.get("tokens") or []:
        sym = str(token.get("symbol") or "").upper()
        if sym in assets:
            portfolio += float(token.get("balance") or 0) * float(assets[sym]["usd"] or 0)
    return {"source": _source("CoinGecko", url, True), "assets": assets, "portfolio_usd": round(portfolio, 2) if portfolio else None}


def _defillama_context(chain: str) -> dict[str, Any]:
    chain_name = DEFILLAMA_CHAIN_MAP.get(str(chain or "").upper())
    if not chain_name:
        return {"source": _source("DefiLlama", "https://api.llama.fi/v2/chains", True, "chain not mapped"), "chain": None}
    data, err = _http_json("https://api.llama.fi/v2/chains")
    if err:
        return {"source": _source("DefiLlama", "https://api.llama.fi/v2/chains", False, err), "chain": None}
    match = None
    for row in data or []:
        if str(row.get("name") or "").lower() == chain_name.lower():
            match = row
            break
    stable_data, stable_err = _http_json("https://stablecoins.llama.fi/stablecoins")
    stablecoins = []
    if not stable_err:
        for asset in (stable_data or {}).get("peggedAssets") or []:
            chain_circulating = ((asset.get("chainCirculating") or {}).get("current") or {}).get(chain_name)
            if chain_circulating:
                stablecoins.append({
                    "symbol": asset.get("symbol"),
                    "name": asset.get("name"),
                    "circulating_usd": chain_circulating,
                })
    stablecoins.sort(key=lambda x: float(x.get("circulating_usd") or 0), reverse=True)
    return {
        "source": _source("DefiLlama", "https://api.llama.fi/v2/chains", True),
        "chain": match,
        "stablecoins": stablecoins[:8],
    }


def public_enrichment_status() -> dict[str, Any]:
    init_public_enrichment_tables()
    with _conn() as con:
        feeds = con.execute(
            "SELECT source, category, COUNT(*) AS n, MAX(updated_at) AS updated_at FROM public_enrichment_feed_items GROUP BY source, category"
        ).fetchall()
        cache_count = con.execute("SELECT COUNT(*) AS n FROM public_enrichment_cache").fetchone()["n"]
    return {
        "cache_entries": cache_count,
        "feeds": [dict(r) for r in feeds],
        "providers": [
            {"id": "opensanctions_ransomwhere", "configured": True},
            {"id": "bitcoinabuse", "configured": bool(_env("BITCOINABUSE_API_TOKEN") or _env("BITCOINABUSE_API_KEY"))},
            {"id": "cryptoscamdb", "configured": True},
            {"id": "dune_labels", "configured": bool(_env("DUNE_API_KEY") and _env("DUNE_LABELS_QUERY_ID"))},
            {"id": "coingecko", "configured": True},
            {"id": "defillama", "configured": True},
        ],
    }


def _internal_labels(address: str, chain: str, intel: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Labels derived from CrypTX's own knowledge — registries (mixer/bridge/DEX/
    VASP/sanctions) and the current investigation's intel — so known and risky
    addresses are labeled even when external OSINT feeds have no match."""
    a = _addr(address)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def push(label, category, source, conf, method, evidence=None):
        key = (label, category)
        if not label or key in seen:
            return
        seen.add(key)
        out.append({"label": label, "category": category, "source": source, "source_url": "",
                    "confidence": conf, "method": method, "evidence": evidence or {}})

    # 1) Is the address itself a known entity? (registry / VASP / sanctions)
    try:
        import holistic_trace_engine as hte
        c = hte.classify_counterparty(a, chain or "eth")
        if c.get("label") and c.get("type") not in (None, "", "unknown"):
            push(c["label"], c["type"], "CrypTX registry",
                 0.97 if c.get("sanctioned") else 0.9, "internal_registry_exact_match",
                 {"sanctioned": bool(c.get("sanctioned")), "vasp": c.get("vasp")})
    except Exception:  # noqa: BLE001
        pass

    # 2) Labels derived from this investigation's intel
    intel = intel or {}
    mh = intel.get("mixer_hits") or []
    if mh:
        names = sorted({m.get("mixer_name") for m in mh if m.get("mixer_name")})
        if names:
            push("Interacts with mixer(s): " + ", ".join(names[:4]), "mixer-exposure",
                 "CrypTX behavioral", 0.85, "derived_from_mixer_interactions", {"interactions": len(mh)})
    sanc = intel.get("sanctions") or {}
    if sanc.get("sanctioned"):
        ids = ", ".join(i.get("name", "") for i in (sanc.get("identifications") or [])[:2] if i.get("name"))
        push("Sanctions listed" + (f": {ids}" if ids else ""), "sanctions", "OFAC SDN",
             0.99, "sanctions_screen")
    scam = intel.get("scam_reports") or {}
    if int(scam.get("count") or 0) > 0:
        push(f"Scam reports on file: {int(scam.get('count'))}", "scam", "CrypTX scam intel",
             0.8, "scam_reports")
    chs = intel.get("chain_hop_swap") or {}
    if chs.get("risk_level") in ("high", "medium"):
        push(f"Cross-chain swap activity ({chs.get('risk_level')} risk)", "bridge-swap",
             "CrypTX behavioral", 0.7, "chain_hop_swap")
    return out


def enrich_address(address: str, chain: str = "", intel: Optional[dict[str, Any]] = None, refresh: bool = False) -> dict[str, Any]:
    init_public_enrichment_tables()
    a = _addr(address)
    cache_key = f"public_enrichment:{ENRICHMENT_CACHE_VERSION}:{a}:{chain}:{bool(intel)}"
    if not refresh:
        cached = _cache_get(cache_key)
        if cached:
            return cached

    local_matches = _local_feed_matches(a)
    abuse_sources = [_bitcoinabuse(address), _cryptoscamdb(address)]
    labels = _dune_labels(address)
    prices = _coingecko_prices(intel)
    defi = _defillama_context(chain or (intel or {}).get("chain", ""))

    internal = _internal_labels(address, chain or (intel or {}).get("chain", ""), intel)
    public_labels = internal + list(local_matches) + labels.get("labels", [])
    abuse_count = sum(int(src.get("count") or 0) for src in abuse_sources)
    ransomware_hits = [m for m in local_matches if m.get("category") == "ransomware"]
    sanctions_hits = [m for m in local_matches if m.get("category") == "sanctions"] \
        + [m for m in internal if m.get("category") == "sanctions"]

    result = {
        "address": address,
        "chain": chain or (intel or {}).get("chain", ""),
        "summary": {
            "label_count": len(public_labels),
            "abuse_report_count": abuse_count,
            "ransomware_hit_count": len(ransomware_hits),
            "sanctions_dataset_hit_count": len(sanctions_hits),
            "portfolio_usd": prices.get("portfolio_usd"),
            "defi_chain_tvl": (defi.get("chain") or {}).get("tvl") if isinstance(defi.get("chain"), dict) else None,
        },
        "labels": public_labels,
        "abuse": {
            "found": abuse_count > 0,
            "count": abuse_count,
            "sources": abuse_sources,
        },
        "ransomware": {
            "found": bool(ransomware_hits),
            "matches": ransomware_hits,
        },
        "prices": prices,
        "defi": defi,
        "sources": [
            prices.get("source"),
            defi.get("source"),
            labels.get("source"),
            *[src.get("source") for src in abuse_sources],
        ],
        "generated_at": _now(),
        "disclaimer": "Public/free enrichment is investigative intelligence. Confirm source records before legal or compliance action.",
    }
    _cache_set(cache_key, result)
    return result
