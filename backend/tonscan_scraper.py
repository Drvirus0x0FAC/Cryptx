"""
TONScan profile enricher — builds a tonscan.com-style profile for TON addresses.

Strategy:
  tonscan.com is a Vue SPA (client-side rendered) with bot protection, so its
  HTML can't be reliably scraped via plain HTTP. However, tonscan.com is built
  on top of the public tonapi.io v2 API — the data displayed is identical.

  This module builds the tonscan-style profile from data that ton_engine's
  investigate_ton() ALREADY fetched (no duplicate API calls), and optionally
  tries tonscan.com for marketplace-only stats (floor price, volume) as a
  best-effort enhancement.

The result mirrors what an investigator sees on tonscan.com:
  • Name / DNS domain (e.g. "alice.ton")
  • Entity type (wallet / NFT collection / NFT item / jetton)
  • Balance + USD value
  • Contract hash and interfaces
  • NFT collection stats (floor price, volume) when applicable
  • NFT items with images, names, and sale status
  • Direct tonscan.com link
"""
from __future__ import annotations

import re
import logging
from typing import Any
from urllib.parse import quote

import aiohttp

log = logging.getLogger("tonscan_scraper")

TONSCAN_BASE = "https://tonscan.com"

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── tonscan.com marketplace enrichment (best-effort, only for collections) ─────

async def try_tonscan_marketplace(address: str) -> dict[str, str]:
    """Try to scrape floor price / volume from tonscan.com.

    tonscan.com is a Vue SPA; depending on caching/bots it may return SSR HTML
    with marketplace stats, or a JS shell. This is best-effort — returns empty
    strings if nothing is parseable. Only useful for NFT collections.
    """
    out: dict[str, str] = {"floor_price": "", "volume": ""}
    url = f"{TONSCAN_BASE}/{quote(address)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_BROWSER_HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status >= 400:
                    return out
                html = await resp.text()
    except Exception:  # noqa: BLE001
        return out

    # Bail if it's a JS shell (Vue SPA returns near-empty HTML to bots)
    if '<div id="app"></div>' in html or len(html) < 2000:
        return out

    for label, key in (("Floor price", "floor_price"), ("Floor", "floor_price"),
                       ("Volume", "volume")):
        m = re.search(rf'{re.escape(label)}\s*[:：]\s*\$?([^\n<,]+)', html, re.I)
        if m and not out[key]:
            val = m.group(1).strip()
            if val and val.lower() not in ("—", "-", "n/a", ""):
                out[key] = val
    return out


# ── profile builder (uses data already fetched by investigate_ton) ─────────────

def build_tonscan_profile_from_tonapi(
    address: str,
    kind: str,
    account: dict[str, Any],
    parsed: dict[str, Any] | None,
    ton_price: float,
    nfts: list[dict[str, Any]],
    nft_item: dict[str, Any] | None,
    interfaces: list[str],
) -> dict[str, Any]:
    """Build a tonscan.com-style profile dict from data investigate_ton already has.

    No additional API calls — just restructures the tonapi.io data into the
    tonscan display format. The frontend TonScanSection renders this directly.
    """
    addr = address.strip()
    balance_ton = float((account.get("balance_ton") if "balance_ton" in account else 0) or 0)
    # account from ton_engine's return shape has balance_ton/balance_usd already computed
    balance_usd = account.get("balance_usd")
    if balance_ton == 0 and account.get("balance_ton") is None:
        # fallback: not pre-computed
        pass

    dns_name = account.get("name") or ""
    collection_name = ""

    # Build NFT items list depending on entity type
    nft_items: list[dict[str, Any]] = []

    if kind == "nft_item" and nft_item and not nft_item.get("error"):
        collection_name = (nft_item.get("collection") or {}).get("name", "")
        nft_items = [{
            "name": nft_item.get("name") or "Unnamed item",
            "image": nft_item.get("image") or "",
            "sale_status": "for_sale" if nft_item.get("on_sale") else "not_for_sale",
            "last_sale_ton": _parse_ton_from_sale_price(nft_item.get("sale_price")),
        }]
    elif kind == "nft_collection":
        # nfts list holds the collection's items
        for n in nfts[:24]:
            nft_items.append({
                "name": n.get("name") or "Item",
                "image": n.get("image") or "",
                "sale_status": "not_for_sale",
                "last_sale_ton": None,
            })
    else:
        # Wallet: nfts holds the wallet's NFT holdings
        for n in nfts[:24]:
            nft_items.append({
                "name": n.get("name") or "Item",
                "image": n.get("image") or "",
                "sale_status": "not_for_sale",
                "last_sale_ton": None,
            })

    display_name = dns_name or collection_name or ""
    if kind == "wallet" and not display_name:
        display_name = ""

    description = ""
    if nft_item and not nft_item.get("error"):
        description = nft_item.get("description") or ""

    raw_addr = (parsed or {}).get("raw_form") or account.get("address") or addr
    bounceable = ((parsed or {}).get("bounceable") or {}).get("b64url", "")

    # Balance display
    if balance_usd:
        balance_str = f"{balance_ton:,.4f} TON (~${balance_usd:,.2f})"
    elif balance_ton:
        balance_str = f"{balance_ton:,.4f} TON"
    else:
        balance_str = ""

    return {
        "tonscan_url": f"{TONSCAN_BASE}/{quote(addr)}",
        "tonscan_name": display_name,
        "tonscan_dns": dns_name,
        "tonscan_description": description,
        "tonscan_entity_type": kind,
        "tonscan_balance": balance_str,
        "tonscan_contract_hash": raw_addr,
        "tonscan_interfaces": interfaces[:12],
        "tonscan_floor_price": "",  # filled by marketplace enrichment (collections only)
        "tonscan_volume": "",
        "tonscan_nft_items": nft_items,
        "tonscan_nft_images": [n.get("image", "") for n in nft_items if n.get("image")],
        "tonscan_address_bounceable": bounceable,
        "tonscan_ton_price_usd": ton_price or None,
        "tonscan_balance_ton": balance_ton,
        "tonscan_balance_usd": balance_usd,
    }


def _parse_ton_from_sale_price(sale_price: str | None) -> float | None:
    """Extract TON amount from a sale price string like '1.5 TON'."""
    if not sale_price:
        return None
    m = re.search(r'([\d,.]+)', sale_price)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None
