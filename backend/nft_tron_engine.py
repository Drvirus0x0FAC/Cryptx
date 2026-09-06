"""
NFT/TRON investigation engine.

The engine is intentionally evidence-first: it can enrich from public no-key
endpoints when available, but the risk model and investigation pivots are local
and deterministic so the feature still produces useful leads offline.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

import aiohttp


EVM_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TX_RE = re.compile(r"^(0x)?[a-fA-F0-9]{64}$")
TRON_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

NFT_MARKETPLACES = {
    "opensea": "OpenSea marketplace activity",
    "blur": "Blur marketplace activity",
    "looksrare": "LooksRare marketplace activity",
    "x2y2": "X2Y2 marketplace activity",
    "magiceden": "Magic Eden marketplace activity",
}

NFT_CRIME_MOTIFS = [
    {
        "id": "approval_drainer",
        "title": "Approval Drainer Exposure",
        "severity": "HIGH",
        "logic": "Looks for wallet/transaction subjects that should be reviewed for setApprovalForAll, permit, delegate registry, and marketplace proxy abuse.",
        "next_steps": [
            "Inspect ERC-721/ERC-1155 approval events around the compromise window.",
            "Pivot to operator addresses that received approval before NFT movement.",
            "Compare operator reuse across other victims and collections.",
        ],
    },
    {
        "id": "wash_trade_loop",
        "title": "Wash Trading Loop Candidate",
        "severity": "MEDIUM",
        "logic": "Flags repeated collection movement, rapid relisting, circular buyer/seller flows, and abnormal price oscillation as leads.",
        "next_steps": [
            "Trace buyer and seller funding sources.",
            "Look for repeated token IDs moving between the same wallet cluster.",
            "Compare sale prices against floor and recent legitimate sales.",
        ],
    },
    {
        "id": "mint_scam",
        "title": "Malicious Mint / Fake Drop Pattern",
        "severity": "HIGH",
        "logic": "Highlights mint-related subjects where exploit paths often include fake collection pages, high-volume victim mints, and immediate NFT or native-token extraction.",
        "next_steps": [
            "Check domain and social profile age for the mint campaign.",
            "Inspect contract creation, verified source, ownership renounce, and mint recipient concentration.",
            "Correlate mint proceeds to bridges, mixers, exchanges, or fresh wallets.",
        ],
    },
    {
        "id": "stolen_nft_fence",
        "title": "Stolen NFT Fencing Route",
        "severity": "HIGH",
        "logic": "Prioritizes rapid post-theft transfers to marketplaces, OTC wallets, aggregators, bridges, and fresh buyer wallets.",
        "next_steps": [
            "Build a token-ID timeline from theft to listing to sale.",
            "Preserve marketplace listing URLs and transaction evidence.",
            "Cluster recipient wallets by funding, timing, and repeated collection exposure.",
        ],
    },
]

TRON_RISK_RULES = [
    ("trc20_usdt_velocity", "TRC20 Stablecoin Velocity", 18, "High TRC20 transfer count or USDT-heavy flow suggests laundering/payment rail activity."),
    ("fresh_tron_wallet", "Fresh TRON Wallet", 10, "Recently created or low-age TRON wallet requires extra attribution caution."),
    ("contract_interaction", "TRON Contract Interaction", 12, "Contract-trigger transactions can include swaps, approvals, staking, or scam contract calls."),
    ("high_counterparty_fanout", "High Counterparty Fan-out", 14, "Many unique counterparties can indicate collection, distribution, or mule coordination."),
]


@dataclass
class Signal:
    title: str
    severity: str
    score: int
    detail: str
    evidence: list[str]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _short(value: str) -> str:
    return value[:10] + "..." + value[-8:] if len(value) > 24 else value


def _base58_decode(value: str) -> bytes:
    num = 0
    for char in value:
        num *= 58
        if char not in BASE58_ALPHABET:
            raise ValueError("invalid base58 character")
        num += BASE58_ALPHABET.index(char)
    combined = num.to_bytes((num.bit_length() + 7) // 8, byteorder="big")
    padding = 0
    for char in value:
        if char == "1":
            padding += 1
        else:
            break
    return b"\x00" * padding + combined


def is_valid_tron_address(value: str) -> bool:
    if not TRON_RE.match(value):
        return False
    try:
        raw = _base58_decode(value)
    except ValueError:
        return False
    if len(raw) != 25 or raw[0] != 0x41:
        return False
    body, checksum = raw[:-4], raw[-4:]
    digest = hashlib.sha256(hashlib.sha256(body).digest()).digest()
    return checksum == digest[:4]


def classify_subject(subject: str, chain_hint: str = "auto") -> dict[str, Any]:
    value = subject.strip()
    chain = (chain_hint or "auto").lower()
    try:
        from ton_engine import is_ton_address
        if chain == "ton" or is_ton_address(value):
            return {"kind": "address", "chain": "TON", "normalized": value, "valid": True}
    except Exception:  # noqa: BLE001
        pass
    if is_valid_tron_address(value):
        return {"kind": "address", "chain": "TRON", "normalized": value, "valid": True}
    if EVM_RE.match(value):
        return {"kind": "address", "chain": "EVM", "normalized": value.lower(), "valid": True}
    if TX_RE.match(value):
        return {"kind": "transaction", "chain": "AUTO", "normalized": value if value.startswith("0x") else f"0x{value}", "valid": True}
    if chain == "tron" and TRON_RE.match(value):
        return {"kind": "address", "chain": "TRON", "normalized": value, "valid": False}
    return {"kind": "unknown", "chain": chain.upper(), "normalized": value, "valid": False}


async def _fetch_json(session: aiohttp.ClientSession, url: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=16)) as resp:
            if resp.status >= 400:
                return None, f"{resp.status} {url}"
            return await resp.json(content_type=None), None
    except Exception as exc:  # noqa: BLE001 - surface endpoint failure as evidence.
        return None, f"{type(exc).__name__}: {exc}"


async def fetch_tron_public(address: str) -> dict[str, Any]:
    base = "https://api.trongrid.io/v1"
    errors: list[str] = []
    async with aiohttp.ClientSession(headers={"User-Agent": "CryptoOSINT-Prism/1.0"}) as session:
        account, err = await _fetch_json(session, f"{base}/accounts/{address}")
        if err:
            errors.append(err)
        txs, err = await _fetch_json(
            session,
            f"{base}/accounts/{address}/transactions",
            {"limit": 40, "only_confirmed": "true", "order_by": "block_timestamp,desc"},
        )
        if err:
            errors.append(err)
        trc20, err = await _fetch_json(
            session,
            f"{base}/accounts/{address}/transactions/trc20",
            {"limit": 60, "only_confirmed": "true", "order_by": "block_timestamp,desc"},
        )
        if err:
            errors.append(err)
    return {
        "account": (account or {}).get("data", []),
        "transactions": (txs or {}).get("data", []),
        "trc20": (trc20 or {}).get("data", []),
        "errors": errors,
        "source": "public_tron_telemetry" if not errors else "partial_public_tron_telemetry",
    }


async def fetch_reservoir_nfts(address: str) -> dict[str, Any]:
    url = f"https://api.reservoir.tools/users/{address}/tokens/v10"
    errors: list[str] = []
    async with aiohttp.ClientSession(headers={"User-Agent": "CryptoOSINT-Prism/1.0"}) as session:
        data, err = await _fetch_json(
            session,
            url,
            {"limit": 50, "includeTopBid": "true", "includeAttributes": "false", "sortBy": "floorAskPrice"},
        )
        if err:
            errors.append(err)
    tokens = (data or {}).get("tokens", []) if isinstance(data, dict) else []
    return {
        "tokens": tokens,
        "errors": errors,
        "source": "public_nft_telemetry" if tokens else "local_nft_heuristics",
    }


OPENSEA_SCRAPER_PATH = __import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__)),
    "opensea_scraper.py",
)


def _opensea_graphql_profile(address: str) -> tuple[dict[str, Any] | None, bool]:
    """In-process GraphQL-only profile fetch (no browser).

    Returns (profile_dict, has_data). has_data is False when OpenSea returned
    no public profile for the address.
    """
    from opensea_scraper import OpenSeaGraphQLClient, OpenSeaProfile

    data = OpenSeaGraphQLClient().fetch_profile(address)
    prof = OpenSeaProfile(address=address.lower().strip())
    if not data:
        return prof.to_dict(), False
    prof.display_name = data.get("display_name")
    prof.username = data.get("username")
    prof.bio = data.get("bio", "")
    prof.follower_count = data.get("follower_count", 0)
    prof.following_count = data.get("following_count", 0)
    prof.is_verified = data.get("is_verified", False)
    prof.is_staff = data.get("is_staff", False)
    prof.portfolio_value_usd = data.get("portfolio_value_usd", 0.0)
    prof.nft_percentage = data.get("nft_percentage", 0.0)
    prof.token_percentage = data.get("token_percentage", 0.0)
    return prof.to_dict(), True


def _humanize_scrape_error(returncode: int, stderr: str, stdout: str) -> str:
    """Turn raw subprocess output into a short, actionable diagnostic."""
    blob = f"{stderr}\n{stdout}".lower()
    if "executable doesn't exist" in blob or "playwright install" in blob:
        return ("Chromium browser is not installed for Playwright. "
                "Run: playwright install chromium")
    if "modulenotfounderror" in blob and "playwright" in blob:
        return ("Playwright is not installed. Run: pip install playwright "
                "&& playwright install chromium")
    if "timeout" in blob or returncode == -9:
        return "OpenSea scrape timed out (page slow, rate-limited, or bot-challenged)."
    # Fall back to the last meaningful stderr line.
    lines = [ln.strip() for ln in (stderr or stdout or "").splitlines() if ln.strip()]
    tail = lines[-1] if lines else f"scraper exited with code {returncode}"
    return f"OpenSea scrape failed: {tail}"


def _opensea_scrape_sync(address: str) -> dict[str, Any]:
    """Run the OpenSea scraper and return a normalized-ready raw payload.

    The full Playwright scrape runs as an isolated subprocess (its intended CLI
    usage) so Playwright never touches this event loop / thread. On any failure
    we degrade to the in-process GraphQL profile so the panel still renders
    identity/portfolio stats, and we surface a real diagnostic.
    """
    import json
    import os
    import subprocess
    import sys
    import tempfile

    full_error: str | None = None

    if not os.path.exists(OPENSEA_SCRAPER_PATH):
        full_error = f"opensea_scraper.py not found at {OPENSEA_SCRAPER_PATH}"
    else:
        tmp_path = ""
        try:
            fd, tmp_path = tempfile.mkstemp(prefix="opensea_", suffix=".json")
            os.close(fd)
            proc = subprocess.run(
                [sys.executable, OPENSEA_SCRAPER_PATH, address,
                 "--headless", "--wait", "9", "-o", tmp_path],
                cwd=os.path.dirname(OPENSEA_SCRAPER_PATH),
                capture_output=True,
                text=True,
                timeout=90,
            )
            if proc.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 2:
                with open(tmp_path, "r", encoding="utf-8") as fh:
                    pdict = json.load(fh)
                has_data = bool(
                    pdict.get("nfts") or pdict.get("collections")
                    or pdict.get("display_name") or pdict.get("portfolio_value_usd")
                )
                if has_data:
                    return {"available": True, "degraded": False, "error": None, "profile": pdict}
                full_error = "OpenSea returned an empty profile (page may have been bot-challenged)."
            else:
                full_error = _humanize_scrape_error(proc.returncode, proc.stderr, proc.stdout)
        except subprocess.TimeoutExpired:
            full_error = "OpenSea scrape timed out after 90s (page slow, rate-limited, or bot-challenged)."
        except Exception as exc:  # noqa: BLE001
            full_error = f"OpenSea scrape failed: {type(exc).__name__}: {exc}".rstrip(": ")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # Fallback: GraphQL-only profile (no browser required).
    try:
        pdict, has_data = _opensea_graphql_profile(address)
        if has_data:
            return {"available": True, "degraded": True,
                    "error": f"Showing OpenSea profile stats only - {full_error}",
                    "profile": pdict}
        return {"available": False, "degraded": True,
                "error": f"{full_error} GraphQL also returned no public OpenSea profile for this address.",
                "profile": pdict}
    except Exception as exc2:  # noqa: BLE001
        return {"available": False, "degraded": False,
                "error": f"{full_error} GraphQL fallback error: {type(exc2).__name__}: {exc2}",
                "profile": None}


def _normalize_opensea(raw: dict[str, Any]) -> dict[str, Any]:
    """Shape the scraper output into the response contract the UI consumes."""
    profile = raw.get("profile") or {}
    collections = profile.get("collections") or []
    nfts = profile.get("nfts") or []
    events = profile.get("events") or []

    norm_collections = [
        {
            "name": c.get("name") or "Unknown Collection",
            "slug": c.get("slug") or "",
            "image_url": c.get("image_url"),
            "category": c.get("category") or "",
            "item_count": c.get("item_count") or 0,
            "floor_price": c.get("floor_price") or 0.0,
            "floor_currency": c.get("floor_price_currency") or "ETH",
            "total_volume": c.get("total_volume") or 0.0,
            "volume_currency": c.get("total_volume_currency") or "ETH",
        }
        for c in collections[:24]
    ]

    norm_nfts = [
        {
            "token_id": n.get("token_id") or "",
            "name": n.get("name") or f"Token {n.get('token_id', '')}",
            "collection_name": n.get("collection_name") or "",
            "collection_slug": n.get("collection_slug") or "",
            "image_url": n.get("image_url"),
            "permalink": n.get("permalink"),
            "contract_address": n.get("contract_address") or "",
            "schema_name": n.get("schema_name") or "",
            "last_sale_price": n.get("last_sale_price") or 0.0,
            "last_sale_currency": n.get("last_sale_currency") or "",
            "current_price": n.get("current_price") or 0.0,
            "current_price_currency": n.get("current_price_currency") or "",
            "rarity_rank": n.get("rarity_rank"),
        }
        for n in nfts[:60]
    ]

    norm_events = [
        {
            "event_type": e.get("event_type") or "",
            "created_date": e.get("created_date") or "",
            "asset_name": e.get("asset_name") or "",
            "asset_token_id": e.get("asset_token_id") or "",
            "collection_slug": e.get("collection_slug") or "",
            "from_address": e.get("from_address"),
            "to_address": e.get("to_address"),
            "price": e.get("price") or 0.0,
            "currency": e.get("currency") or "ETH",
            "transaction_hash": e.get("transaction_hash"),
            "quantity": e.get("quantity") or 1,
        }
        for e in events[:40]
    ]

    return {
        "available": bool(raw.get("available")),
        "degraded": bool(raw.get("degraded")),
        "error": raw.get("error"),
        "profile": {
            "address": profile.get("address") or "",
            "display_name": profile.get("display_name"),
            "username": profile.get("username"),
            "bio": profile.get("bio") or "",
            "profile_image_url": profile.get("profile_image_url"),
            "banner_image_url": profile.get("banner_image_url"),
            "follower_count": profile.get("follower_count") or 0,
            "following_count": profile.get("following_count") or 0,
            "is_verified": bool(profile.get("is_verified")),
            "is_staff": bool(profile.get("is_staff")),
            "portfolio_value_usd": profile.get("portfolio_value_usd") or 0.0,
            "nft_percentage": profile.get("nft_percentage") or 0.0,
            "token_percentage": profile.get("token_percentage") or 0.0,
        } if profile else None,
        "counts": {
            "collections": len(collections),
            "nfts": len(nfts),
            "events": len(events),
        },
        "collections": norm_collections,
        "nfts": norm_nfts,
        "events": norm_events,
        "profile_url": f"https://opensea.io/{(profile.get('address') or raw.get('address') or '').lower()}",
    }


async def fetch_opensea(address: str) -> dict[str, Any]:
    """Async wrapper: run the blocking OpenSea scrape off the event loop."""
    raw = await asyncio.to_thread(_opensea_scrape_sync, address)
    raw.setdefault("address", address)
    return _normalize_opensea(raw)


def _tron_metrics(telemetry: dict[str, Any]) -> dict[str, Any]:
    txs = telemetry.get("transactions") or []
    trc20 = telemetry.get("trc20") or []
    account = (telemetry.get("account") or [{}])[0] if telemetry.get("account") else {}
    counterparties: set[str] = set()
    usdt_count = 0
    inbound = 0
    outbound = 0
    for item in trc20:
        token = (item.get("token_info") or {}).get("symbol", "")
        if token.upper() == "USDT":
            usdt_count += 1
        if item.get("from"):
            counterparties.add(item["from"])
        if item.get("to"):
            counterparties.add(item["to"])
        if item.get("type") == "Transfer":
            inbound += 1
    for item in txs:
        raw = item.get("raw_data", {})
        contracts = raw.get("contract", [])
        for contract in contracts:
            ctype = contract.get("type", "")
            if ctype:
                counterparties.add(ctype)
            if "TriggerSmartContract" in ctype:
                outbound += 1
    created = account.get("create_time") or account.get("latest_opration_time") or 0
    age_days = max(0, (_now_ms() - int(created or _now_ms())) / 86_400_000) if created else None
    balance_sun = account.get("balance", 0) or 0
    return {
        "native_balance_trx": round(balance_sun / 1_000_000, 6),
        "tx_count": len(txs),
        "trc20_count": len(trc20),
        "usdt_transfer_count": usdt_count,
        "unique_counterparties": len(counterparties),
        "contract_call_count": outbound,
        "age_days": round(age_days, 2) if age_days is not None else None,
    }


def _nft_metrics(nft_data: dict[str, Any]) -> dict[str, Any]:
    tokens = nft_data.get("tokens") or []
    collections: dict[str, dict[str, Any]] = {}
    estimated_value = 0.0
    suspicious = 0
    for row in tokens:
        token = row.get("token") or {}
        market = row.get("market") or {}
        collection = token.get("collection") or {}
        cid = collection.get("id") or token.get("contract") or "unknown"
        entry = collections.setdefault(cid, {
            "id": cid,
            "name": collection.get("name") or token.get("name") or "Unknown Collection",
            "count": 0,
            "floor_usd": 0,
            "sample_tokens": [],
        })
        entry["count"] += 1
        if len(entry["sample_tokens"]) < 4:
            entry["sample_tokens"].append({
                "name": token.get("name") or f"Token {token.get('tokenId', '')}",
                "token_id": token.get("tokenId"),
                "contract": token.get("contract"),
            })
        floor = ((market.get("floorAsk") or {}).get("price") or {}).get("amount", {})
        usd = float(floor.get("usd") or 0)
        entry["floor_usd"] = max(entry["floor_usd"], usd)
        estimated_value += usd
        if token.get("isFlagged") or token.get("isSpam"):
            suspicious += 1
    return {
        "nft_count": len(tokens),
        "collection_count": len(collections),
        "estimated_floor_value_usd": round(estimated_value, 2),
        "suspicious_token_count": suspicious,
        "collections": sorted(collections.values(), key=lambda c: c["count"], reverse=True)[:12],
    }


def _build_osint_pivots(subject: str, classification: dict[str, Any]) -> list[dict[str, str]]:
    q = subject.strip()
    chain = classification["chain"]
    pivots = [
        {"title": "Universal web search", "kind": "search", "url": f"https://www.google.com/search?q=%22{q}%22+NFT+scam+wallet"},
        {"title": "X / social search", "kind": "social", "url": f"https://x.com/search?q=%22{q}%22&src=typed_query"},
        {"title": "GitHub leak/code search", "kind": "code", "url": f"https://github.com/search?q=%22{q}%22&type=code"},
        {"title": "Domain and scam reports", "kind": "victim-osint", "url": f"https://www.google.com/search?q=%22{q}%22+phishing+drainer+mint"},
    ]
    if chain == "TRON":
        pivots.extend([
            {"title": "TRON explorer", "kind": "explorer", "url": f"https://tronscan.org/#/address/{q}"},
            {"title": "TRON contract events", "kind": "events", "url": f"https://tronscan.org/#/address/{q}/transfers"},
        ])
    elif classification["kind"] == "address":
        pivots.extend([
            {"title": "Ethereum NFT holdings", "kind": "nft", "url": f"https://etherscan.io/address/{q}#tokentxnsErc721"},
            {"title": "NFT marketplace profile", "kind": "marketplace", "url": f"https://opensea.io/{q}"},
            {"title": "Approval checker", "kind": "approval", "url": f"https://revoke.cash/address/{q}"},
        ])
    return pivots


def _risk_signals(classification: dict[str, Any], tron_metrics: dict[str, Any], nft_metrics: dict[str, Any], errors: list[str]) -> list[Signal]:
    signals: list[Signal] = []
    if classification["chain"] == "TRON":
        if tron_metrics.get("usdt_transfer_count", 0) >= 10:
            signals.append(Signal(*TRON_RISK_RULES[0], evidence=[f"{tron_metrics['usdt_transfer_count']} TRC20 USDT transfers observed."]))
        if tron_metrics.get("age_days") is not None and tron_metrics["age_days"] < 14:
            signals.append(Signal(*TRON_RISK_RULES[1], evidence=[f"Wallet age is approximately {tron_metrics['age_days']} days."]))
        if tron_metrics.get("contract_call_count", 0) >= 4:
            signals.append(Signal(*TRON_RISK_RULES[2], evidence=[f"{tron_metrics['contract_call_count']} smart-contract trigger transactions observed."]))
        if tron_metrics.get("unique_counterparties", 0) >= 20:
            signals.append(Signal(*TRON_RISK_RULES[3], evidence=[f"{tron_metrics['unique_counterparties']} unique counterparties or interaction markers."]))
    if nft_metrics.get("nft_count", 0) >= 25:
        signals.append(Signal(
            "High NFT Inventory Concentration",
            "MEDIUM",
            12,
            "Large NFT inventory can indicate collector, marketplace operator, bulk sweeper, compromised wallet, or fencing wallet.",
            [f"{nft_metrics['nft_count']} NFT/token records observed across {nft_metrics.get('collection_count', 0)} collections."],
        ))
    if nft_metrics.get("suspicious_token_count", 0) > 0:
        signals.append(Signal(
            "Flagged NFT Exposure",
            "HIGH",
            18,
            "One or more NFT records are flagged or spam-like in public telemetry.",
            [f"{nft_metrics['suspicious_token_count']} suspicious NFT records observed."],
        ))
    if errors:
        signals.append(Signal(
            "Telemetry Gaps",
            "LOW",
            4,
            "Some public telemetry was unavailable. Treat absence of findings as incomplete, not exculpatory.",
            errors[:4],
        ))
    if not signals:
        signals.append(Signal(
            "No High-Confidence Crime Signal",
            "LOW",
            2,
            "No strong NFT/TRON crime signal was detected by local heuristics from the available telemetry.",
            ["Run deeper graph tracing or add transaction IDs for a higher-confidence assessment."],
        ))
    return signals


def _build_graph(subject: str, classification: dict[str, Any], tron: dict[str, Any], nft: dict[str, Any]) -> dict[str, Any]:
    nodes = [{"id": subject, "label": _short(subject), "type": classification["chain"], "risk": 45}]
    edges: list[dict[str, Any]] = []
    if classification["chain"] == "TRON":
        for idx, tx in enumerate((tron.get("trc20") or [])[:16]):
            cp = tx.get("from") if tx.get("to") == subject else tx.get("to") or f"tron-event-{idx}"
            if not cp:
                continue
            nodes.append({"id": cp, "label": _short(cp), "type": "TRC20 counterparty", "risk": 35 + min(idx, 20)})
            edges.append({"source": subject, "target": cp, "label": (tx.get("token_info") or {}).get("symbol", "TRC20"), "weight": 1})
    for col in (nft.get("collections") or [])[:8]:
        cid = col["id"]
        nodes.append({"id": cid, "label": col["name"][:28], "type": "NFT collection", "risk": 30 + min(col["count"] * 4, 35)})
        edges.append({"source": subject, "target": cid, "label": f"{col['count']} NFTs", "weight": col["count"]})
    return {"nodes": nodes[:40], "edges": edges[:60]}


async def _investigate_ton_subject(subject: str, classification: dict[str, Any], focus: str) -> dict[str, Any]:
    """TON wallet / NFT profile (TonViewer-style) wrapped in the Sentinel result shape."""
    from ton_engine import investigate_ton
    ton = await investigate_ton(subject)
    kind_label = {"nft_item": "NFT item", "nft_collection": "NFT collection",
                  "jetton_master": "Jetton", "wallet": "wallet"}.get(ton.get("kind", ""), "account")
    return {
        "subject": subject,
        "submitted_subject": subject,
        "classification": {**classification, "kind": "nft_item" if ton.get("kind") == "nft_item" else "address"},
        "risk_score": ton.get("risk_score", 0),
        "risk_level": ton.get("risk_level", "LOW"),
        "summary": {
            "headline": f"TON {kind_label} profile",
            "assessment": "Live TON telemetry resolved from the public tonapi.io index (TonViewer's data source). "
                          "Risk signals are local, deterministic leads — not proof of guilt.",
            "focus": focus.strip(),
        },
        "signals": ton.get("signals", []),
        "ton_profile": ton,
        # Keep the legacy sections present-but-empty so the shared UI shell stays happy.
        "nft": {"source": "not_applicable", "metrics": {"nft_count": ton.get("totals", {}).get("nft_count", 0),
                "collection_count": 0, "estimated_floor_value_usd": 0, "collections": []}, "collections": []},
        "opensea": {"available": False, "degraded": False, "error": None, "profile": None,
                    "counts": {"collections": 0, "nfts": 0, "events": 0}, "collections": [], "nfts": [],
                    "events": [], "profile_url": ""},
        "tron": {"source": "not_applicable", "metrics": {}, "recent_trc20": [], "recent_transactions": []},
        "motifs": [],
        "osint_pivots": [
            {"title": "TonViewer", "kind": "explorer", "url": ton.get("explorer", "")},
            {"title": "Tonscan", "kind": "explorer", "url": f"https://tonscan.org/address/{subject}"},
            {"title": "TON API (raw JSON)", "kind": "api", "url": f"https://tonapi.io/v2/accounts/{subject}"},
        ],
        "graph": _build_ton_graph(subject, ton),
        "investigation_playbook": [
            "Confirm the address form (bounceable vs non-bounceable) before quoting it in a report.",
            "For jetton dusting, ignore unverified airdropped tokens — they are bait, not holdings.",
            "For NFT cases, verify the collection address and 'approved_by' trust before valuing the item.",
            "Trace scam-flagged events to their counterparties and pivot into Nexus for flow analysis.",
        ],
        "limitations": [
            "Public TON telemetry can be rate-limited; add a TONAPI_KEY in Settings for higher limits.",
            "USD valuations use live tonapi rates and are approximate.",
            "Attribution to a real-world owner requires corroborated off-chain evidence.",
        ],
        "generated_at": ton.get("generated_at", int(time.time())),
    }


def _build_ton_graph(subject: str, ton: dict[str, Any]) -> dict[str, Any]:
    short = _short(subject)
    nodes = [{"id": subject, "label": ton.get("account", {}).get("name") or short,
              "type": f"TON {ton.get('kind', 'account')}", "risk": ton.get("risk_score", 40)}]
    edges: list[dict[str, Any]] = []
    if ton.get("nft_item"):
        item = ton["nft_item"]
        col = item.get("collection") or {}
        if col.get("address"):
            nodes.append({"id": col["address"], "label": col.get("name", "collection")[:28], "type": "NFT collection", "risk": 30})
            edges.append({"source": subject, "target": col["address"], "label": "member of", "weight": 1})
        owner = item.get("owner") or {}
        if owner.get("address"):
            nodes.append({"id": owner["address"], "label": owner.get("name") or _short(owner["address"]), "type": "owner", "risk": 35})
            edges.append({"source": owner["address"], "target": subject, "label": "owns", "weight": 1})
    for ev in (ton.get("events") or [])[:14]:
        for cp in ev.get("counterparties", []):
            if not cp.get("address"):
                continue
            nodes.append({"id": cp["address"], "label": cp.get("name") or _short(cp["address"]),
                          "type": "counterparty", "risk": 50 if ev.get("is_scam") else 32})
            edges.append({"source": subject, "target": cp["address"],
                          "label": ev.get("type", "tx"), "weight": 1})
    # de-dupe nodes by id
    seen: set[str] = set()
    uniq = []
    for n in nodes:
        if n["id"] in seen:
            continue
        seen.add(n["id"])
        uniq.append(n)
    return {"nodes": uniq[:40], "edges": edges[:60]}


async def investigate_nft_tron(subject: str, chain_hint: str = "auto", focus: str = "") -> dict[str, Any]:
    classification = classify_subject(subject, chain_hint)
    if classification["chain"] == "TON":
        return await _investigate_ton_subject(classification["normalized"], classification, focus)
    normalized = classification["normalized"]
    tron_data: dict[str, Any] = {"account": [], "transactions": [], "trc20": [], "errors": [], "source": "not_applicable"}
    nft_data: dict[str, Any] = {"tokens": [], "errors": [], "source": "not_applicable"}
    opensea_data: dict[str, Any] = {
        "available": False, "degraded": False, "error": None, "profile": None,
        "counts": {"collections": 0, "nfts": 0, "events": 0},
        "collections": [], "nfts": [], "events": [],
        "profile_url": "",
    }

    is_evm_address = classification["chain"] in {"EVM", "AUTO"} and classification["kind"] == "address"

    tasks = []
    if classification["chain"] == "TRON" and classification["kind"] == "address" and classification["valid"]:
        tasks.append(("tron", fetch_tron_public(normalized)))
    if is_evm_address:
        tasks.append(("nft", fetch_reservoir_nfts(normalized)))
        # Live OpenSea lookup on submit (full Playwright scrape, GraphQL fallback).
        tasks.append(("opensea", fetch_opensea(normalized)))
    if tasks:
        gathered = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        for (name, _), result in zip(tasks, gathered):
            if isinstance(result, Exception):
                if name == "tron":
                    tron_data["errors"].append(str(result))
                elif name == "opensea":
                    opensea_data["error"] = str(result)
                else:
                    nft_data["errors"].append(str(result))
            elif name == "tron":
                tron_data = result
            elif name == "opensea":
                opensea_data = result
            else:
                nft_data = result

    tron_metrics = _tron_metrics(tron_data)
    nft_metrics = _nft_metrics(nft_data)
    errors = list(tron_data.get("errors") or []) + list(nft_data.get("errors") or [])
    signals = _risk_signals(classification, tron_metrics, nft_metrics, errors)
    score = min(100, max(0, sum(s.score for s in signals)))
    if classification["kind"] == "unknown" or not classification["valid"]:
        score = max(score, 35)
        signals.insert(0, Signal(
            "Subject Format Requires Review",
            "MEDIUM",
            8,
            "The submitted value does not validate cleanly as an EVM address, TRON address, or transaction hash.",
            [f"Submitted subject: {subject}"],
        ))
    risk_level = "CRITICAL" if score >= 80 else "HIGH" if score >= 60 else "MEDIUM" if score >= 35 else "LOW"

    motifs = []
    for motif in NFT_CRIME_MOTIFS:
        relevance = 0.35
        if motif["id"] in {"approval_drainer", "stolen_nft_fence"} and classification["chain"] == "EVM":
            relevance += 0.25
        if motif["id"] == "wash_trade_loop" and nft_metrics.get("collection_count", 0) > 1:
            relevance += 0.2
        if motif["id"] == "mint_scam" and classification["kind"] == "transaction":
            relevance += 0.25
        motifs.append({**motif, "relevance": round(min(relevance, 0.95), 2)})

    return {
        "subject": normalized,
        "submitted_subject": subject,
        "classification": classification,
        "risk_score": score,
        "risk_level": risk_level,
        "summary": {
            "headline": f"{classification['chain']} {classification['kind']} NFT/TRON investigation profile",
            "assessment": "Local algorithms generated cybercrime leads, telemetry gaps, and OSINT pivots. Findings are investigative leads, not proof of ownership or guilt.",
            "focus": focus.strip(),
        },
        "signals": [s.__dict__ for s in signals],
        "nft": {
            "source": nft_data.get("source"),
            "metrics": nft_metrics,
            "collections": nft_metrics.get("collections", []),
        },
        "opensea": opensea_data,
        "tron": {
            "source": tron_data.get("source"),
            "metrics": tron_metrics,
            "recent_trc20": (tron_data.get("trc20") or [])[:20],
            "recent_transactions": (tron_data.get("transactions") or [])[:20],
        },
        "motifs": motifs,
        "osint_pivots": _build_osint_pivots(normalized, classification),
        "graph": _build_graph(normalized, classification, tron_data, nft_metrics),
        "investigation_playbook": [
            "Preserve marketplace pages, token IDs, listing IDs, transaction hashes, screenshots, and UTC timestamps.",
            "Trace approval operator wallets before NFT movement; prioritize repeated operator reuse across victims.",
            "For stolen NFT cases, build token-ID custody timeline from victim wallet to marketplace sale to cash-out.",
            "For TRON cases, separate TRX fee funding, TRC20 USDT flow, exchange deposits, and contract-trigger transactions.",
            "Use OSINT pivots to connect wallet, collection slug, token ID, domains, social handles, and victim reports.",
        ],
        "limitations": [
            "Public telemetry can be rate-limited or incomplete.",
            "Attribution to a real-world owner requires corroborated off-chain evidence.",
            "NFT floor values are volatile and should be treated as approximate.",
        ],
        "generated_at": int(time.time()),
    }
