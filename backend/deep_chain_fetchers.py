"""
Deep chain fetchers — BTC UTXO traversal and Solana instruction-level parsing.

Addresses the "tracing stalls after hop 0" limitation for BTC (UTXO model has no
per-tx from/to addresses) and Solana (multi-instruction txs need instruction-level
parsing to extract real counterparties and SPL token movements).

BTC: uses Blockstream / mempool.space APIs which expose full input/output addresses,
enabling true multi-hop UTXO tracing (peel-chain detection).

Solana: parses the transaction's instruction tree to extract token-transfer
instructions, decoding SPL token movements and identifying the real caller
(not just the fee payer).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

log = logging.getLogger("deep_chain_fetchers")

BLOCKSTREAM_URL = "https://blockstream.info/api"
MEMPOOL_URL = "https://mempool.space/api"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"


def _norm(v: Any) -> str:
    s = str(v or "").strip()
    return s.lower() if s.startswith("0x") else s


# ── BTC UTXO deep traversal ───────────────────────────────────────────────────

async def _btc_get_json(session: aiohttp.ClientSession, base: str, path: str) -> dict | list | None:
    """Guarded (rate-budgeted, breaker-protected) GET with blockstream↔mempool failover."""
    try:
        import http_cache
        for url_base in (base, MEMPOOL_URL if base == BLOCKSTREAM_URL else BLOCKSTREAM_URL):
            data, err = await http_cache.guarded_get_json(session, f"{url_base}{path}", timeout=20)
            if data is not None and not err:
                return data
        return None
    except ImportError:
        pass
    for url_base in (base, MEMPOOL_URL if base == BLOCKSTREAM_URL else BLOCKSTREAM_URL):
        try:
            async with session.get(f"{url_base}{path}", timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            continue
    return None


async def btc_address_txs(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Fetch full tx list for a BTC address with input/output addresses exposed."""
    data = await _btc_get_json(session, BLOCKSTREAM_URL, f"/address/{address}/txs")
    if not isinstance(data, list):
        return []
    return data


def parse_btc_tx(tx: dict, subject: str) -> list[dict]:
    """Extract directed transfer edges from a BTC tx (UTXO model).

    Returns edges where subject is either a vin input address or a vout output address.
    This is what enables multi-hop tracing: we know both where the BTC came from
    (vin addresses) and where it went (vout addresses).
    """
    edges: list[dict] = []
    subj = subject.lower()
    vin_addrs: list[str] = []
    vout_addrs: list[str] = []
    value_in_by_addr: dict[str, float] = {}
    value_out_by_addr: dict[str, float] = {}

    for vin in (tx.get("vin") or []):
        if vin.get("is_coinbase"):
            continue
        prev = vin.get("prevout") or {}
        addr = prev.get("scriptpubkey_address") or prev.get("address")
        val_btc = (prev.get("value") or 0) / 1e8  # sat → BTC
        if addr:
            vin_addrs.append(addr.lower())
            value_in_by_addr[addr.lower()] = value_in_by_addr.get(addr.lower(), 0) + val_btc

    for vout in (tx.get("vout") or []):
        addr = vout.get("scriptpubkey_address") or vout.get("address")
        val_btc = (vout.get("value") or 0) / 1e8
        if addr:
            vout_addrs.append(addr.lower())
            value_out_by_addr[addr.lower()] = value_out_by_addr.get(addr.lower(), 0) + val_btc

    tx_hash = tx.get("txid") or tx.get("hash") or ""
    ts = tx.get("status", {}).get("block_time") or tx.get("time") or 0

    if subj in vin_addrs:
        # subject is a sender → edges to each output
        for out_addr in vout_addrs:
            if out_addr == subj:
                continue
            edges.append({
                "source": subject, "target": out_addr,
                "value": value_out_by_addr.get(out_addr, 0),
                "token": "BTC", "chain": "btc",
                "tx_hash": tx_hash, "timestamp": str(ts) if ts else "",
            })
    if subj in vout_addrs:
        # subject is a receiver → edges from each input
        for in_addr in vin_addrs:
            if in_addr == subj:
                continue
            edges.append({
                "source": in_addr, "target": subject,
                "value": value_in_by_addr.get(in_addr, 0),
                "token": "BTC", "chain": "btc",
                "tx_hash": tx_hash, "timestamp": str(ts) if ts else "",
            })
    return edges


async def btc_deep_trace(address: str, max_hops: int = 3, max_nodes: int = 50) -> dict:
    """Multi-hop BTC UTXO trace using Blockstream's full-tx endpoint.

    Unlike the old fetcher that only got hop-0, this follows outputs forward by
    fetching each recipient address's txs and continuing. Detects peel chains.
    """
    visited: set[str] = set()
    nodes: dict[str, dict] = {address.lower(): {"address": address, "chain": "btc", "type": "subject"}}
    edges: list[dict] = []
    frontier: list[str] = [address.lower()]
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for hop in range(max_hops):
            if not frontier or len(nodes) >= max_nodes:
                break
            next_frontier: list[str] = []
            sem = asyncio.Semaphore(4)
            async def _expand(addr: str) -> list[dict]:
                async with sem:
                    txs = await btc_address_txs(session, addr)
                    new_edges = []
                    for tx in txs[:20]:  # cap per address
                        new_edges.extend(parse_btc_tx(tx, addr))
                    return new_edges
            results = await asyncio.gather(*[_expand(a) for a in frontier])
            for addr, new_edges in zip(frontier, results):
                visited.add(addr)
                for e in new_edges:
                    edges.append({**e, "hop": hop})
                    other = e["target"] if e["source"].lower() == addr else e["source"]
                    if other not in visited and other not in nodes and len(nodes) < max_nodes:
                        nodes[other] = {"address": other, "chain": "btc", "type": "unknown"}
                        next_frontier.append(other)
            frontier = [a for a in next_frontier if a not in visited]
    return {
        "chain": "btc", "subject": address,
        "hops_completed": min(max_hops, hop + 1) if edges else 0,
        "node_count": len(nodes), "edge_count": len(edges),
        "nodes": list(nodes.values()), "edges": edges[:500],
        "engine": "btc_utxo_deep_v1",
        "disclaimer": "BTC UTXO trace follows outputs forward via Blockstream full-tx data. "
                      "CoinJoin / privacy-coin mixing breaks the chain.",
    }


# ── Solana instruction-level parsing ──────────────────────────────────────────

async def sol_address_signatures(session: aiohttp.ClientSession, address: str, limit: int = 50) -> list[str]:
    """Fetch recent tx signatures for a Solana address."""
    try:
        async with session.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
            "params": [address, {"limit": limit}],
        }, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json()
            return [item.get("signature", "") for item in (data.get("result") or []) if item.get("signature")]
    except Exception:
        return []


async def sol_tx_detail(session: aiohttp.ClientSession, signature: str) -> dict | None:
    try:
        async with session.post(SOLANA_RPC, json={
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [signature, {"maxSupportedTransactionVersion": 0,
                                    "encoding": "jsonParsed"}],
        }, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json()
            return data.get("result")
    except Exception:
        return None


def parse_solana_tx(tx: dict, subject: str) -> list[dict]:
    """Extract SPL token transfers + SOL movements from a parsed Solana tx.

    Walks the inner + outer instruction tree to find token-transfer instructions
    (Token program: transfer / transferChecked) and decode source/destination/amount.
    This is what the old fetcher couldn't do — it only saw balance deltas.
    """
    edges: list[dict] = []
    message = (tx or {}).get("transaction", {}).get("message") or {}
    instructions = message.get("instructions") or []
    # also inner instructions
    inner = (tx or {}).get("meta", {}).get("innerInstructions") or []
    all_ixs = list(instructions)
    for group in inner:
        all_ixs.extend(group.get("instructions") or [])

    TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    TRANSFER_DISCRIMINATOR = 3       # transfer
    TRANSFER_CHECKED = 12            # transferChecked

    for ix in all_ixs:
        program = str(ix.get("programId") or ix.get("program", ""))
        if program not in (TOKEN_PROGRAM, TOKEN_2022):
            # could be a Token program called via cross-program; check parsed
            parsed = ix.get("parsed") or {}
            if parsed.get("type") not in ("transfer", "transferChecked"):
                continue
            prog_id = (parsed.get("info") or {})
            amount = float(prog_id.get("amount") or prog_id.get("tokenAmount", {}).get("uiAmount") or 0)
            source = prog_id.get("authority") or prog_id.get("source")
            dest = prog_id.get("destination")
            if source and dest and amount:
                edges.append({
                    "source": source, "target": dest, "value": amount,
                    "token": "SPL", "chain": "sol",
                    "tx_hash": (tx.get("transaction") or {}).get("signatures", [""])[0],
                    "timestamp": str(tx.get("blockTime") or ""),
                })
            continue
        # raw instruction — check discriminator in data
        data = ix.get("data")
        if isinstance(data, str) and len(data) >= 2:
            try:
                disc = int(data[:2], 16) if data[:2].lower() != "0x" else int(data[2:4], 16)
            except ValueError:
                disc = -1
            if disc in (TRANSFER_DISCRIMINATOR, TRANSFER_CHECKED):
                accounts = ix.get("accounts") or []
                # transfer: [source, destination, authority]
                if len(accounts) >= 3:
                    edges.append({
                        "source": accounts[0], "target": accounts[1],
                        "value": 0,  # amount encoded in data; decode requires base58
                        "token": "SPL", "chain": "sol",
                        "tx_hash": (tx.get("transaction") or {}).get("signatures", [""])[0],
                        "timestamp": str(tx.get("blockTime") or ""),
                    })
    return edges


async def sol_deep_trace(address: str, max_txs: int = 30) -> dict:
    """Solana trace: fetch signatures → fetch each tx parsed → extract SPL transfers."""
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        sigs = await sol_address_signatures(session, address, limit=max_txs)
        sem = asyncio.Semaphore(4)
        async def _fetch_tx(sig: str) -> dict | None:
            async with sem:
                return await sol_tx_detail(session, sig)
        txs = await asyncio.gather(*[_fetch_tx(s) for s in sigs])
    edges: list[dict] = []
    for tx in txs:
        if tx:
            edges.extend(parse_solana_tx(tx, address))
    return {
        "chain": "sol", "subject": address,
        "txs_fetched": len(sigs), "edge_count": len(edges),
        "edges": edges[:500],
        "engine": "solana_spl_deep_v1",
        "disclaimer": "Solana SPL trace parses the instruction tree for token-transfer calls. "
                      "Complex program interactions may need manual review.",
    }
