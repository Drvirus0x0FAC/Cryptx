#!/usr/bin/env python3
"""
ens_resolver.py — ENS & Unstoppable Domains resolution module.

Resolves Ethereum addresses <-> human-readable domain names:
  • ENS (.eth)               — via Ethereum RPC eth_call
  • Unstoppable Domains      — (.crypto / .x / .nft / .wallet / .bitcoin /
                               .dao / .888 / .zil / .blockchain)

APIs used:
  • Any Ethereum RPC endpoint (default: https://ethereum.publicnode.com)
  • Unstoppable Domains Resolution API (optional API key)

Env vars (all optional):
  ETH_RPC_URL          — default Ethereum RPC endpoint
  UD_API_KEY           — Unstoppable Domains API key
  ENS_HTTP_TIMEOUT     — HTTP timeout in seconds (default 15)
"""

from __future__ import annotations

import os
import re
import asyncio
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

import aiohttp


log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────
_DEFAULT_RPC = (
    os.getenv("ETH_RPC_URL", "https://ethereum.publicnode.com").strip().strip("\"'")
)
_UD_API_KEY = os.getenv("UD_API_KEY", "").strip().strip("\"'")
_HTTP_TIMEOUT = int(os.getenv("ENS_HTTP_TIMEOUT", "15"))

# ── Contract addresses ────────────────────────────────────────────────────
ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
ENS_REVERSE_REGISTRAR = "0xA2C122BE93d007F0E68028B8d8da13506eF52100"
UNS_PROXY = "0xc3C2BAB5e3e52E2a28da5d7e64F8bECDD9C0C7f6"

# ── Function selectors (keccak256 first 4 bytes) ─────────────────────────
_SEL_RESOLVER = "0x0178b8bf"       # resolver(bytes32)
_SEL_ADDR = "0x3b3b57de"           # addr(bytes32)
_SEL_NAME = "0x691f3431"           # name(bytes32)  — reverse
_SEL_TEXT = "0x59d1d43c"           # text(bytes32,string)
_SEL_GET = "0x1be5e7ed"            # get(string, uint256) — UNS

# ── ENS text record keys ──────────────────────────────────────────────────
_TEXT_RECORD_KEYS = [
    "email",
    "url",
    "avatar",
    "description",
    "notice",
    "keywords",
    "com.discord",
    "com.github",
    "com.reddit",
    "com.twitter",
    "org.telegram",
]

# ── Domain suffixes ───────────────────────────────────────────────────────
_UD_SUFFIXES = (
    ".crypto", ".x", ".nft", ".wallet", ".bitcoin",
    ".dao", ".888", ".zil", ".blockchain",
)


__all__ = [
    "resolve_ens_name",
    "resolve_ens_address",
    "resolve_unstoppable_domain",
    "resolve_all_domains",
    "resolve_domain_async",
    "format_domain_resolution_html",
]


# =========================================================================
# Helpers
# =========================================================================

def _namehash(name: str) -> str:
    """ENS namehash algorithm — returns hex string of the 32-byte node.

    Example:
        _namehash("eth") -> "0x93cdeb708b7545dc668eb9280176169d1c33cfd8ed6f04690a0bcc88a93fc4ae"
        _namehash("vitalik.eth") -> "0xee6c4522aab0003e8d14cd40a6af439055fd2577951148c14b6cea9a53475835"
    """
    if not name:
        return "0x" + "00" * 32
    node = bytearray(32)
    labels = name.lower().split(".")
    for label in reversed(labels):
        label_hash = _keccak256(label.encode("utf-8"))
        node = _keccak256(bytes(node) + label_hash)
    return "0x" + node.hex()


def _dns_encode(name: str) -> bytes:
    """DNS-encoded name for contract calls — length-prefixed labels.

    Example: "vitalik.eth" -> b'\x07vitalik\x03eth\x00'
    """
    parts = name.lower().split(".")
    out = bytearray()
    for part in parts:
        out.append(len(part))
        out.extend(part.encode("utf-8"))
    out.append(0)
    return bytes(out)


def _keccak256(data: bytes) -> bytes:
    """Keccak-256 hash (the Ethereum flavour, not SHA3-256).

    Tries multiple backends: sha3 (pysha3), pycryptodome, eth-hash.
    """
    # Try pysha3 first (fastest C impl)
    try:
        import sha3 as _sha3
        k = _sha3.keccak_256()
        k.update(data)
        return k.digest()
    except Exception:
        pass
    # pycryptodome (widely available)
    try:
        from Crypto.Hash import keccak as _keccak
        k = _keccak.new(digest_bits=256)
        k.update(data)
        return k.digest()
    except Exception:
        pass
    # eth-hash (if installed)
    try:
        from eth_hash.auto import keccak as _eth_keccak
        return _eth_keccak(data)
    except Exception:
        pass
    # Last resort: hashlib.sha3_256 (note: this is SHA3-256, NOT keccak-256;
    # only used as absolute fallback and may produce different hashes!)
    import hashlib
    return hashlib.sha3_256(data).digest()


def _normalize_address(addr: str) -> str:
    """Lowercase Ethereum address with 0x prefix."""
    addr = addr.strip().lower()
    if not addr.startswith("0x"):
        addr = "0x" + addr
    return addr


def _is_address(query: str) -> bool:
    """Check if query looks like an Ethereum address."""
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", query.strip()))


def _is_domain(query: str) -> bool:
    """Check if query looks like a domain name."""
    q = query.strip().lower()
    return (
        q.endswith(".eth")
        or q.endswith(_UD_SUFFIXES)
        or ("." in q and not _is_address(q))
    )


async def _eth_call(
    rpc_url: str,
    to: str,
    data: str,
    timeout: int = _HTTP_TIMEOUT,
) -> Optional[str]:
    """Execute an eth_call via JSON-RPC. Returns hex result or None."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }
    try:
        t = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.post(rpc_url, json=payload) as r:
                if r.status != 200:
                    log.warning("eth_call HTTP %s on %s", r.status, rpc_url)
                    return None
                resp = await r.json()
                if not isinstance(resp, dict):
                    return None
                result = resp.get("result")
                if result and result.startswith("0x"):
                    return result
                error = resp.get("error")
                if error:
                    log.debug("eth_call error: %s", error)
                return None
    except asyncio.TimeoutError:
        log.warning("eth_call timeout on %s", rpc_url)
    except Exception as exc:
        log.warning("eth_call error %s: %s", rpc_url, exc)
    return None


async def _http_get_json(
    url: str,
    headers: Optional[dict] = None,
    timeout: int = _HTTP_TIMEOUT,
) -> Optional[dict]:
    """HTTP GET helper returning parsed JSON."""
    try:
        t = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=t) as s:
            async with s.get(url, headers=headers) as r:
                if r.status != 200:
                    log.warning("HTTP GET %s on %s", r.status, url)
                    return None
                return await r.json()
    except asyncio.TimeoutError:
        log.warning("HTTP GET timeout on %s", url)
    except Exception as exc:
        log.warning("HTTP GET error %s: %s", url, exc)
    return None


def _decode_address(hex_result: str) -> str:
    """Decode a 32-byte padded address from eth_call result."""
    if not hex_result or hex_result == "0x" or len(hex_result) < 42:
        return ""
    # Last 20 bytes (40 hex chars) are the address
    addr = "0x" + hex_result[-40:].lower()
    # Checksum encode (simple check)
    if addr == "0x" + "0" * 40:
        return ""
    return addr


def _decode_string(hex_result: str) -> str:
    """Decode ABI-encoded string from eth_call result.

    Layout: [32-byte offset][32-byte length][string data padded to 32 bytes]
    """
    if not hex_result or hex_result == "0x" or len(hex_result) < 130:
        return ""
    try:
        hex_body = hex_result[2:]  # strip 0x
        # offset (first 32 bytes) — usually 0x20 = 32
        _ = int(hex_body[0:64], 16)
        # length (second 32 bytes)
        length = int(hex_body[64:128], 16)
        # string data starts at byte 64
        data_start = 128
        data_end = data_start + length * 2
        if data_end > len(hex_body):
            data_end = len(hex_body)
        raw = hex_body[data_start:data_end]
        return bytes.fromhex(raw).decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _abi_encode_string(key: str) -> str:
    """ABI-encode a string parameter for eth_call data."""
    try:
        key_bytes = key.encode("utf-8")
        # offset to string (always 0x40 = 64 bytes for single string)
        offset = "0000000000000000000000000000000000000000000000000000000000000040"
        length = hex(len(key_bytes))[2:].zfill(64)
        # pad key bytes to 32-byte boundary
        padded = key_bytes.hex().ljust(64, "0")
        data = offset + length + padded
        return data
    except Exception:
        return ""


# =========================================================================
# ENS resolution
# =========================================================================

@lru_cache(maxsize=256)
def _cached_namehash(name: str) -> str:
    """LRU-cached namehash for frequently queried domains."""
    return _namehash(name)


async def resolve_ens_name(
    domain: str,
    rpc_url: str = "",
) -> dict:
    """Forward ENS resolution: domain name -> Ethereum address.

    Args:
        domain: ENS domain (e.g. "vitalik.eth")
        rpc_url: Ethereum RPC endpoint (defaults to ETH_RPC_URL env var)

    Returns:
        dict with keys: resolved_address, resolver_address, ttl, text_records,
                        source, error
    """
    result: Dict[str, Any] = {
        "resolved_address": "",
        "resolver_address": "",
        "ttl": 0,
        "text_records": {},
        "source": "ens",
        "error": "",
    }
    rpc = (rpc_url or _DEFAULT_RPC).strip()
    domain = domain.strip().lower()

    if not domain.endswith(".eth"):
        result["error"] = f"Not an ENS domain: {domain}"
        return result

    try:
        node = _cached_namehash(domain)

        # 1) Query ENS registry for resolver
        resolver_data = _SEL_RESOLVER + node[2:].zfill(64)
        resolver_hex = await _eth_call(rpc, ENS_REGISTRY, resolver_data)
        if not resolver_hex:
            result["error"] = "No resolver found for domain"
            return result

        resolver_addr = _decode_address(resolver_hex)
        if not resolver_addr:
            result["error"] = "Resolver address is zero"
            return result
        result["resolver_address"] = resolver_addr

        # 2) Call resolver.addr(node)
        addr_data = _SEL_ADDR + node[2:].zfill(64)
        addr_hex = await _eth_call(rpc, resolver_addr, addr_data)
        if addr_hex:
            resolved = _decode_address(addr_hex)
            if resolved:
                result["resolved_address"] = resolved

        # 3) Fetch text records
        text_records = await _resolve_ens_text_records(
            resolver_addr, node, rpc
        )
        result["text_records"] = text_records

    except Exception as exc:
        log.warning("ENS forward resolution error for %s: %s", domain, exc)
        result["error"] = str(exc)[:200]

    return result


async def _resolve_ens_text_records(
    resolver_addr: str,
    node: str,
    rpc_url: str,
) -> Dict[str, str]:
    """Fetch available ENS text records from resolver contract."""
    records: Dict[str, str] = {}

    async def _fetch_one(key: str) -> None:
        try:
            # text(bytes32 node, string key) selector + node + encoded string
            encoded_key = _abi_encode_string(key)
            data = _SEL_TEXT + node[2:].zfill(64) + encoded_key
            result = await _eth_call(rpc_url, resolver_addr, data)
            if result and len(result) > 66:
                value = _decode_string(result)
                if value:
                    records[key] = value
        except Exception:
            pass

    # Fetch text records concurrently
    await asyncio.gather(*[_fetch_one(k) for k in _TEXT_RECORD_KEYS])
    return records


async def resolve_ens_address(
    address: str,
    rpc_url: str = "",
) -> dict:
    """Reverse ENS resolution: Ethereum address -> primary name.

    Args:
        address: Ethereum address (0x...)
        rpc_url: Ethereum RPC endpoint (defaults to ETH_RPC_URL env var)

    Returns:
        dict with keys: primary_name, address, source, error
    """
    result: Dict[str, Any] = {
        "primary_name": "",
        "address": address,
        "source": "ens",
        "error": "",
    }
    rpc = (rpc_url or _DEFAULT_RPC).strip()

    try:
        addr = _normalize_address(address)
        result["address"] = addr

        # Reverse node: <addr_no_0x>.addr.reverse
        reverse_name = f"{addr[2:]}.addr.reverse"
        node = _cached_namehash(reverse_name)

        # Step 1: Query ENS registry for resolver of reverse node
        resolver_data = _SEL_RESOLVER + node[2:].zfill(64)
        resolver_hex = await _eth_call(rpc, ENS_REGISTRY, resolver_data)
        if not resolver_hex or resolver_hex == "0x" + "0" * 64:
            result["error"] = "No reverse resolver found"
            return result

        resolver_addr = _decode_address(resolver_hex)
        if not resolver_addr:
            result["error"] = "Reverse resolver address is zero"
            return result

        # Step 2: Call resolver.name(node) to get primary name
        name_data = _SEL_NAME + node[2:].zfill(64)
        name_hex = await _eth_call(rpc, resolver_addr, name_data)
        if name_hex and len(name_hex) >= 130:
            primary = _decode_string(name_hex)
            if primary:
                result["primary_name"] = primary
        if not result["primary_name"]:
            result["error"] = "No reverse ENS record found"

    except Exception as exc:
        log.warning("ENS reverse resolution error for %s: %s", address, exc)
        result["error"] = str(exc)[:200]

    return result


# =========================================================================
# Unstoppable Domains resolution
# =========================================================================

async def resolve_unstoppable_domain(
    domain: str,
    api_key: str = "",
) -> dict:
    """Resolve an Unstoppable Domain to addresses and records.

    Args:
        domain: Unstoppable domain (e.g. "brad.crypto")
        api_key: Unstoppable Domains API key (optional, uses UD_API_KEY env)

    Returns:
        dict with keys: resolved_address, records, source, error
    """
    result: Dict[str, Any] = {
        "resolved_address": "",
        "records": {},
        "source": "unstoppable_domains",
        "error": "",
    }
    domain = domain.strip().lower()

    key = (api_key or _UD_API_KEY).strip()

    # Try resolution API first if key available
    if key:
        try:
            url = f"https://resolve.unstoppabledomains.com/domains/{domain}"
            headers = {"Authorization": f"Bearer {key}"}
            data = await _http_get_json(url, headers=headers)
            if data and isinstance(data, dict):
                meta = data.get("meta", {})
                records = data.get("records", {})
                result["records"] = records
                # Primary ETH address
                eth_addr = (
                    records.get("crypto.ETH.address")
                    or records.get("crypto.ETH.version.ERC20.address")
                    or ""
                )
                if eth_addr:
                    result["resolved_address"] = eth_addr.lower()
                owner = meta.get("owner") or meta.get("domain")
                if not result["resolved_address"] and owner:
                    result["resolved_address"] = owner.lower()
                if result["resolved_address"]:
                    return result
        except Exception as exc:
            log.debug("UD API resolution failed for %s: %s", domain, exc)

    # Fallback: RPC-based resolution via UNS Proxy
    try:
        resolved = await _resolve_ud_onchain(domain)
        if resolved.get("resolved_address"):
            result["resolved_address"] = resolved["resolved_address"]
            result["records"] = resolved.get("records", {})
            result["source"] = "unstoppable_domains_onchain"
            return result
    except Exception as exc:
        log.debug("UD on-chain resolution failed for %s: %s", domain, exc)

    result["error"] = f"Could not resolve Unstoppable Domain: {domain}"
    return result


async def _resolve_ud_onchain(domain: str) -> dict:
    """On-chain UNS resolution via Ethereum RPC."""
    result: Dict[str, Any] = {
        "resolved_address": "",
        "records": {},
        "source": "uns_onchain",
        "error": "",
    }
    rpc = _DEFAULT_RPC

    try:
        # Compute tokenId from namehash of domain
        token_id = _cached_namehash(domain)

        # UNS getData keys for ETH and BTC
        keys = [
            "crypto.ETH.address",
            "crypto.BTC.address",
            "crypto.LTC.address",
            "crypto.DOGE.address",
        ]

        # Call UNS proxy getData(keys, tokenId)
        # getData(string[] keys, uint256 tokenId)
        # selector: 0x1be5e7ed for get(string,uint256) - use multiGet
        # Simpler: call get(key, tokenId) for each key
        sel_get = "0x1be5e7ed"  # get(string,uint256)

        for key in keys:
            try:
                encoded_key = _abi_encode_string(key)
                # tokenId is already a 32-byte hex string from namehash
                data = sel_get + encoded_key + token_id[2:].zfill(64)
                resp = await _eth_call(rpc, UNS_PROXY, data)
                if resp and len(resp) > 66:
                    addr = _decode_string(resp)
                    if addr and addr != "0x" + "0" * 40:
                        result["records"][key] = addr
                        if key == "crypto.ETH.address" and not result["resolved_address"]:
                            result["resolved_address"] = addr.lower()
            except Exception:
                continue

    except Exception as exc:
        result["error"] = str(exc)[:200]

    return result


# =========================================================================
# Unified resolution dispatcher
# =========================================================================

async def resolve_all_domains(
    query: str,
    eth_rpc: str = "",
    ud_api_key: str = "",
) -> dict:
    """Resolve both ENS and Unstoppable Domains for a query.

    Auto-detects whether the query is an Ethereum address (reverse lookup)
    or a domain name (forward lookup). Attempts both ENS and UD in parallel.

    Args:
        query: Domain name (e.g. "vitalik.eth") or ETH address (0x...)
        eth_rpc: Ethereum RPC endpoint URL
        ud_api_key: Unstoppable Domains API key

    Returns:
        Structured dict with ens / unstoppable / query metadata.
    """
    query = query.strip()
    result: Dict[str, Any] = {
        "query": query,
        "query_type": "",
        "ens": {
            "resolved_address": "",
            "reverse_name": "",
            "text_records": {},
            "resolver_address": "",
            "ttl": 0,
            "source": "ens",
        },
        "unstoppable": {
            "resolved_address": "",
            "records": {},
            "source": "unstoppable_domains",
        },
        "error": "",
    }

    # Determine query type
    if _is_address(query):
        result["query_type"] = "address"
    elif _is_domain(query):
        result["query_type"] = "domain"
    else:
        result["error"] = (
            "Unrecognized query format. Expected: ETH address (0x...) or domain name"
        )
        return result

    try:
        if result["query_type"] == "domain":
            # Forward resolution: try both ENS and UD in parallel
            ens_coro = resolve_ens_name(query, eth_rpc)
            ud_coro = resolve_unstoppable_domain(query, ud_api_key)
            ens_res, ud_res = await asyncio.gather(ens_coro, ud_coro)

            result["ens"]["resolved_address"] = ens_res.get("resolved_address", "")
            result["ens"]["text_records"] = ens_res.get("text_records", {})
            result["ens"]["resolver_address"] = ens_res.get("resolver_address", "")
            result["ens"]["ttl"] = ens_res.get("ttl", 0)
            if ens_res.get("error") and not ens_res.get("resolved_address"):
                result["ens"]["error"] = ens_res["error"]

            result["unstoppable"]["resolved_address"] = ud_res.get("resolved_address", "")
            result["unstoppable"]["records"] = ud_res.get("records", {})
            if ud_res.get("error") and not ud_res.get("resolved_address"):
                result["unstoppable"]["error"] = ud_res["error"]

            # If it's .eth, set reverse name from ENS
            if query.endswith(".eth") and ens_res.get("resolved_address"):
                result["ens"]["reverse_name"] = query

        else:  # address reverse lookup
            # Reverse ENS only (UD doesn't have standard reverse)
            ens_res = await resolve_ens_address(query, eth_rpc)
            result["ens"]["reverse_name"] = ens_res.get("primary_name", "")
            result["ens"]["resolved_address"] = query
            if ens_res.get("error") and not result["ens"]["reverse_name"]:
                result["ens"]["error"] = ens_res["error"]

            # Also try forward-resolving the reverse name to verify
            if result["ens"]["reverse_name"]:
                fwd = await resolve_ens_name(result["ens"]["reverse_name"], eth_rpc)
                result["ens"]["text_records"] = fwd.get("text_records", {})
                result["ens"]["resolver_address"] = fwd.get("resolver_address", "")

    except Exception as exc:
        log.warning("resolve_all_domains error for %s: %s", query, exc)
        result["error"] = str(exc)[:200]

    # Overall error if nothing resolved
    has_ens = bool(result["ens"].get("resolved_address")) or bool(
        result["ens"].get("reverse_name")
    )
    has_ud = bool(result["unstoppable"].get("resolved_address"))
    if not has_ens and not has_ud and not result["error"]:
        result["error"] = "No resolution found"

    return result


async def resolve_domain_async(
    query: str,
    eth_rpc: str = "",
    ud_api_key: str = "",
) -> dict:
    """Main entry point used by bot handlers — same as resolve_all_domains.

    Args:
        query: Domain name or Ethereum address
        eth_rpc: Ethereum RPC endpoint
        ud_api_key: Unstoppable Domains API key

    Returns:
        Resolution result dict (same structure as resolve_all_domains).
    """
    return await resolve_all_domains(query, eth_rpc, ud_api_key)


# =========================================================================
# Telegram HTML formatting
# =========================================================================

def format_domain_resolution_html(result: dict) -> str:
    """Format domain resolution result as Telegram-safe HTML.

    Uses only <b>, <i>, <code> tags. All user data is escaped.

    Args:
        result: Output dict from resolve_all_domains() or resolve_domain_async()

    Returns:
        HTML string suitable for Telegram send_message parse_mode="HTML".
    """
    if not isinstance(result, dict):
        return "<b>Domain lookup failed</b>\n<i>Invalid result format</i>"

    def esc(text: str) -> str:
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    query = result.get("query", "")
    qtype = result.get("query_type", "")

    lines: List[str] = []
    lines.append(f"<b>═══ Domain Resolution ═══</b>")
    lines.append(f"<b>Query:</b> <code>{esc(query)}</code>")
    if qtype:
        lines.append(f"<b>Type:</b> <code>{esc(qtype)}</code>")

    # ── ENS section ──
    ens = result.get("ens", {}) or {}
    ens_addr = ens.get("resolved_address", "")
    ens_name = ens.get("reverse_name", "")
    ens_records = ens.get("text_records", {})
    ens_resolver = ens.get("resolver_address", "")
    ens_error = ens.get("error", "")

    has_ens_data = ens_addr or ens_name or ens_records
    if has_ens_data or not ens_error:
        lines.append("")
        lines.append("<b>── ENS ──</b>")
        if ens_addr:
            lines.append(f"<b>Address:</b> <code>{esc(ens_addr)}</code>")
        if ens_name:
            lines.append(f"<b>Name:</b> <code>{esc(ens_name)}</code>")
        if ens_resolver:
            lines.append(f"<b>Resolver:</b> <code>{esc(ens_resolver)}</code>")

        # Text records
        if ens_records:
            lines.append("<b>Text Records:</b>")
            for key, value in ens_records.items():
                if value:
                    # Format known keys nicely
                    display_key = key
                    if key.startswith("com."):
                        display_key = key[4:].capitalize()
                    elif key.startswith("org."):
                        display_key = key[4:].capitalize()
                    lines.append(f"  • <i>{esc(display_key)}:</i> {esc(value)}")
        if ens_error and not has_ens_data:
            lines.append(f"<i>{esc(ens_error)}</i>")

    # ── Unstoppable Domains section ──
    ud = result.get("unstoppable", {}) or {}
    ud_addr = ud.get("resolved_address", "")
    ud_records = ud.get("records", {})
    ud_error = ud.get("error", "")
    ud_source = ud.get("source", "unstoppable_domains")

    has_ud_data = ud_addr or ud_records
    if has_ud_data or not ud_error:
        lines.append("")
        lines.append("<b>── Unstoppable Domains ──</b>")
        if ud_addr:
            lines.append(f"<b>Address:</b> <code>{esc(ud_addr)}</code>")
        if ud_records:
            lines.append("<b>Records:</b>")
            for key, value in ud_records.items():
                if value:
                    # Format key for display
                    display_key = key.replace("crypto.", "").replace(".address", "").replace(".version.ERC20", "")
                    lines.append(f"  • <i>{esc(display_key)}:</i> <code>{esc(value)}</code>")
        if ud_source:
            lines.append(f"<i>Source: {esc(ud_source)}</i>")
        if ud_error and not has_ud_data:
            lines.append(f"<i>{esc(ud_error)}</i>")

    # ── Overall error ──
    overall_error = result.get("error", "")
    if overall_error:
        lines.append("")
        lines.append(f"⚠️ <b>Error:</b> <code>{esc(overall_error)[:300]}</code>")

    # Summary
    if not has_ens_data and not has_ud_data:
        lines.append("")
        lines.append("<i>No resolution found for this query.</i>")
    elif has_ens_data or has_ud_data:
        lines.append("")
        resolved_to = []
        if ens_addr:
            resolved_to.append("ENS")
        if ud_addr:
            resolved_to.append("UD")
        lines.append(
            f"✅ Resolved via: <b>{esc(', '.join(resolved_to))}</b>"
        )

    return "\n".join(lines)
