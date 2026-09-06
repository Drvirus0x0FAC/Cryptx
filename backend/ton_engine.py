"""
TON engine — TonViewer-style enrichment for The Open Network.

Given a TON wallet OR NFT address, this resolves a full profile from the public
tonapi.io v2 API (the same data source TonViewer uses):

  • Address forms (raw / bounceable / non-bounceable)
  • Account: status, TON balance (+ USD), interfaces, scam flag, last activity
  • Jetton (token) balances with USD valuation
  • NFT holdings (for wallets) or full NFT item detail (for NFT addresses)
  • Recent on-chain activity (human-readable action previews)
  • Local, deterministic risk signals (scam flags, unverified assets, drains)

An optional TONAPI_KEY (env / Settings) raises the rate limit but is not required.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import aiohttp

TONAPI_BASE = "https://tonapi.io/v2"

# User-friendly base64url TON address: 48 chars, mainnet/testnet prefixes E/U/k/0.
TON_FRIENDLY_RE = re.compile(r"^[EUkK0][A-Za-z0-9_\-]{47}$")
# Raw form: workchain:hex256, e.g. 0:abcd... or -1:abcd...
TON_RAW_RE = re.compile(r"^-?[0-9]:[0-9a-fA-F]{64}$")

_PROJECT_ENV = Path(__file__).resolve().parent.parent / ".env"
_LOCAL_ENV = Path(__file__).resolve().parent / ".env"


def _env(key: str, default: str = "") -> str:
    if os.environ.get(key):
        return os.environ[key]
    for path in (_LOCAL_ENV, _PROJECT_ENV):
        try:
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    s = line.strip()
                    if s and not s.startswith("#") and "=" in s:
                        k, v = s.split("=", 1)
                        if k.strip() == key:
                            return v.strip().strip("\"'")
        except Exception:  # noqa: BLE001
            pass
    return default


def is_ton_address(value: str) -> bool:
    v = (value or "").strip()
    if TON_RAW_RE.match(v):
        return True
    # Exclude EVM (0x…) and rely on the friendly prefix + length for base64url.
    if v.startswith("0x"):
        return False
    return bool(TON_FRIENDLY_RE.match(v))


def _headers() -> dict[str, str]:
    h = {"User-Agent": "CryptoOSINT-TON/1.0", "Accept": "application/json"}
    key = _env("TONAPI_KEY") or _env("TON_API_KEY")
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


async def _get(session: aiohttp.ClientSession, path: str, params: dict[str, Any] | None = None) -> tuple[Any, str | None]:
    url = f"{TONAPI_BASE}{path}"
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=18)) as resp:
            if resp.status == 404:
                return None, "not_found"
            if resp.status == 429:
                return None, "rate_limited"
            if resp.status >= 400:
                return None, f"http_{resp.status}"
            return await resp.json(content_type=None), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}"


def _nano_to_ton(v: Any) -> float:
    try:
        return round(int(v) / 1e9, 4)
    except Exception:  # noqa: BLE001
        return 0.0


def _img(previews: list[dict[str, Any]] | None, fallback: str = "") -> str:
    if previews:
        # prefer a mid-size preview
        for res in ("500x500", "1500x1500", "100x100"):
            for p in previews:
                if p.get("resolution") == res and p.get("url"):
                    return p["url"]
        if previews[0].get("url"):
            return previews[0]["url"]
    return fallback


async def _ton_price(session: aiohttp.ClientSession) -> float:
    data, _ = await _get(session, "/rates", {"tokens": "ton", "currencies": "usd"})
    try:
        return float(((data or {}).get("rates", {}).get("TON", {}).get("prices", {}) or {}).get("USD") or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def _account_kind(interfaces: list[str]) -> str:
    ints = [str(i).lower() for i in (interfaces or [])]
    if any("nft_item" in i for i in ints):
        return "nft_item"
    if any("nft_collection" in i for i in ints):
        return "nft_collection"
    if any("jetton_master" in i for i in ints):
        return "jetton_master"
    if any("wallet" in i for i in ints):
        return "wallet"
    return "contract"


def _parse_jettons(raw: dict[str, Any] | None) -> tuple[list[dict[str, Any]], float]:
    out: list[dict[str, Any]] = []
    total_usd = 0.0
    for b in ((raw or {}).get("balances") or []):
        jetton = b.get("jetton") or {}
        decimals = int(jetton.get("decimals") or 9)
        try:
            amount = int(b.get("balance") or 0) / (10 ** decimals)
        except Exception:  # noqa: BLE001
            amount = 0.0
        price_usd = 0.0
        try:
            price_usd = float(((b.get("price") or {}).get("prices", {}) or {}).get("USD") or 0)
        except Exception:  # noqa: BLE001
            price_usd = 0.0
        value_usd = round(amount * price_usd, 2) if price_usd else None
        if value_usd:
            total_usd += value_usd
        out.append({
            "symbol": jetton.get("symbol") or "?",
            "name": jetton.get("name") or "Unknown jetton",
            "address": jetton.get("address") or "",
            "image": jetton.get("image") or "",
            "decimals": decimals,
            "balance": round(amount, 6),
            "price_usd": price_usd or None,
            "value_usd": value_usd,
            "verification": jetton.get("verification") or "none",
        })
    out.sort(key=lambda j: (j.get("value_usd") or 0), reverse=True)
    return out, round(total_usd, 2)


def _parse_nfts(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n in ((raw or {}).get("nft_items") or []):
        meta = n.get("metadata") or {}
        col = n.get("collection") or {}
        out.append({
            "address": n.get("address") or "",
            "name": meta.get("name") or f"Item #{n.get('index', '?')}",
            "image": _img(n.get("previews"), meta.get("image") or ""),
            "collection": col.get("name") or "No collection",
            "collection_address": col.get("address") or "",
            "verified": bool(n.get("verified")),
            "trust": n.get("trust") or "none",
        })
    return out


def _parse_events(raw: dict[str, Any] | None, subject: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in ((raw or {}).get("events") or []):
        actions = e.get("actions") or []
        first = actions[0] if actions else {}
        preview = first.get("simple_preview") or {}
        accounts = preview.get("accounts") or []
        out.append({
            "event_id": e.get("event_id") or "",
            "timestamp": e.get("timestamp") or 0,
            "type": first.get("type") or "Unknown",
            "status": first.get("status") or "",
            "description": preview.get("description") or preview.get("name") or first.get("type") or "",
            "value": preview.get("value") or "",
            "is_scam": bool(e.get("is_scam")),
            "action_count": len(actions),
            "counterparties": [
                {"address": a.get("address") or "", "name": a.get("name") or ""}
                for a in accounts if a.get("address") and a.get("address") != subject
            ][:4],
        })
    return out


async def _fetch_nft_item(session: aiohttp.ClientSession, addr: str) -> dict[str, Any]:
    data, err = await _get(session, f"/nfts/{addr}")
    if err or not data:
        return {"error": err or "no_data"}
    meta = data.get("metadata") or {}
    col = data.get("collection") or {}
    owner = data.get("owner") or {}
    sale = data.get("sale") or {}
    price = sale.get("price") or {}
    return {
        "address": data.get("address") or addr,
        "name": meta.get("name") or "Unnamed item",
        "description": meta.get("description") or "",
        "image": _img(data.get("previews"), meta.get("image") or ""),
        "collection": {
            "name": col.get("name") or "No collection",
            "address": col.get("address") or "",
            "description": col.get("description") or "",
        },
        "owner": {"address": owner.get("address") or "", "name": owner.get("name") or ""},
        "verified": bool(data.get("verified")),
        "trust": data.get("trust") or "none",
        "index": data.get("index"),
        "dns": data.get("dns"),
        "on_sale": bool(sale),
        "sale_price": (
            f"{_nano_to_ton(price.get('value'))} {price.get('token_name', 'TON')}" if price.get("value") else None
        ),
        "attributes": [
            {"trait": a.get("trait_type") or "", "value": a.get("value")}
            for a in (meta.get("attributes") or []) if isinstance(a, dict)
        ][:24],
    }


def _risk_signals(account: dict[str, Any], kind: str, jettons: list[dict[str, Any]],
                  nfts: list[dict[str, Any]], events: list[dict[str, Any]],
                  nft_item: dict[str, Any] | None) -> tuple[list[dict[str, Any]], int]:
    signals: list[dict[str, Any]] = []
    score = 0

    if account.get("is_scam"):
        score += 55
        signals.append({"title": "Flagged as Scam by TON API", "severity": "CRITICAL", "score": 55,
                        "detail": "tonapi.io marks this account as scam.",
                        "evidence": ["Account carries the is_scam flag from the public TON index."]})

    scam_events = [e for e in events if e.get("is_scam")]
    if scam_events:
        score += 18
        signals.append({"title": "Scam Activity in Recent Events", "severity": "HIGH", "score": 18,
                        "detail": "One or more recent events are flagged as scam (dusting, fake jetton, phishing comment).",
                        "evidence": [f"{len(scam_events)} recent event(s) flagged is_scam."]})

    unverified_jettons = [j for j in jettons if j.get("verification") == "none"]
    if len(unverified_jettons) >= 3:
        score += 12
        signals.append({"title": "Unverified Jetton Cluster", "severity": "MEDIUM", "score": 12,
                        "detail": "Multiple unverified jettons can indicate airdrop-scam dusting or fake-token bait.",
                        "evidence": [f"{len(unverified_jettons)} unverified jettons held."]})

    if nft_item and not nft_item.get("verified"):
        score += 10
        signals.append({"title": "Unverified NFT Item", "severity": "MEDIUM", "score": 10,
                        "detail": "NFT is not verified/approved — confirm the collection is authentic before valuing.",
                        "evidence": [f"Trust level: {nft_item.get('trust', 'none')}."]})

    status = str(account.get("status") or "").lower()
    if status and status != "active":
        score += 8
        signals.append({"title": f"Account Status: {status}", "severity": "LOW", "score": 8,
                        "detail": "Non-active accounts (uninit/frozen) can be fresh, emptied, or dormant.",
                        "evidence": [f"Account status is '{status}'."]})

    if not signals:
        signals.append({"title": "No Strong TON Crime Signal", "severity": "LOW", "score": 0,
                        "detail": "Local heuristics found no strong scam/abuse signal in the available TON telemetry.",
                        "evidence": ["Absence of signal is not proof of legitimacy — corroborate off-chain."]})
    return signals, min(100, score)


async def investigate_ton(subject: str) -> dict[str, Any]:
    """Full TonViewer-style profile for a TON wallet or NFT address."""
    addr = subject.strip()
    async with aiohttp.ClientSession(headers=_headers()) as session:
        parsed, _ = await _get(session, f"/address/{addr}/parse")
        account, acc_err = await _get(session, f"/accounts/{addr}")
        ton_price = await _ton_price(session)

        interfaces = list((account or {}).get("interfaces") or [])
        kind = _account_kind(interfaces)

        jettons: list[dict[str, Any]] = []
        jetton_total_usd = 0.0
        nfts: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        nft_item: dict[str, Any] | None = None
        errors: list[str] = []
        if acc_err:
            errors.append(f"account:{acc_err}")

        if kind == "nft_item":
            nft_item = await _fetch_nft_item(session, addr)
            ev_raw, ev_err = await _get(session, f"/accounts/{addr}/events", {"limit": 15})
            if ev_err:
                errors.append(f"events:{ev_err}")
            events = _parse_events(ev_raw, addr)
        else:
            jraw, jerr = await _get(session, f"/accounts/{addr}/jettons", {"currencies": "usd"})
            nraw, nerr = await _get(session, f"/accounts/{addr}/nfts", {"limit": 60, "indirect_ownership": "false"})
            eraw, eerr = await _get(session, f"/accounts/{addr}/events", {"limit": 20})
            for tag, err in (("jettons", jerr), ("nfts", nerr), ("events", eerr)):
                if err:
                    errors.append(f"{tag}:{err}")
            jettons, jetton_total_usd = _parse_jettons(jraw)
            nfts = _parse_nfts(nraw)
            events = _parse_events(eraw, addr)

    account = account or {}
    balance_ton = _nano_to_ton(account.get("balance"))
    balance_usd = round(balance_ton * ton_price, 2) if ton_price else None
    signals, score = _risk_signals(account, kind, jettons, nfts, events, nft_item)
    risk_level = "CRITICAL" if score >= 80 else "HIGH" if score >= 55 else "MEDIUM" if score >= 25 else "LOW"

    address_forms = {
        "given": addr,
        "raw": (parsed or {}).get("raw_form") or account.get("address") or addr,
        "bounceable": ((parsed or {}).get("bounceable") or {}).get("b64url") or "",
        "non_bounceable": ((parsed or {}).get("non_bounceable") or {}).get("b64url") or "",
        "testnet": bool((parsed or {}).get("test_only")),
    }

    # TONScan enrichment — builds a tonscan.com-style profile from the data we
    # already fetched (no duplicate API calls). For NFT collections, also tries
    # tonscan.com for marketplace stats (floor price, volume) — best-effort.
    tonscan = None
    try:
        from tonscan_scraper import build_tonscan_profile_from_tonapi, try_tonscan_marketplace
        tonscan = build_tonscan_profile_from_tonapi(
            address=addr,
            kind=kind,
            account={
                "name": account.get("name") or "",
                "balance_ton": balance_ton,
                "balance_usd": balance_usd,
                "address": address_forms["raw"],
            },
            parsed=parsed,
            ton_price=ton_price,
            nfts=nfts,
            nft_item=nft_item,
            interfaces=interfaces,
        )
        # For NFT collections, try to get marketplace floor price + volume from tonscan.com
        if kind == "nft_collection" and tonscan:
            mkt = await try_tonscan_marketplace(addr)
            tonscan["tonscan_floor_price"] = mkt.get("floor_price", "")
            tonscan["tonscan_volume"] = mkt.get("volume", "")
    except Exception:  # noqa: BLE001 — enrichment is best-effort
        tonscan = None

    return {
        "address": address_forms,
        "kind": kind,
        "explorer": f"https://tonviewer.com/{addr}",
        "tonscan": tonscan,
        "ton_price_usd": ton_price or None,
        "account": {
            "status": account.get("status") or "unknown",
            "balance_ton": balance_ton,
            "balance_usd": balance_usd,
            "name": account.get("name") or "",
            "icon": account.get("icon") or "",
            "is_scam": bool(account.get("is_scam")),
            "is_wallet": bool(account.get("is_wallet")),
            "interfaces": interfaces,
            "last_activity": account.get("last_activity") or 0,
            "get_methods": (account.get("get_methods") or [])[:12],
        },
        "totals": {
            "balance_ton": balance_ton,
            "balance_usd": balance_usd,
            "jetton_count": len(jettons),
            "jetton_value_usd": jetton_total_usd or None,
            "nft_count": len(nfts) if nft_item is None else 1,
            "portfolio_usd": round((balance_usd or 0) + (jetton_total_usd or 0), 2) if (balance_usd or jetton_total_usd) else None,
        },
        "jettons": jettons[:50],
        "nfts": nfts[:60],
        "nft_item": nft_item,
        "events": events[:20],
        "risk_score": score,
        "risk_level": risk_level,
        "signals": signals,
        "errors": errors,
        "generated_at": int(time.time()),
        "disclaimer": "TON telemetry is sourced live from the public tonapi.io index. Verify context before "
                      "treating any flag as attribution evidence.",
    }
