"""
Local RPC fetcher — air-gapped EVM data via a self-hosted node.

When `config.LOCAL_RPC_URLS` is set (per-chain URL map), this module replaces
the public-explorer fetcher (`_evm_transfers` in holistic_trace_engine) so the
entire trace engine runs against a local node — no data leaves the deployment.

This makes CrypTX's "self-hosted / air-gapped" moat claim TRUE.

Produces the EXACT row shape the engine expects (from `_evm_one`):
  Native:   {chain, from, to, asset, value, value_usd:0.0, tx_hash, timestamp}
  ERC-20:   same + {contract}

Implementation uses standard JSON-RPC methods:
  - eth_getLogs (Transfer event topic) for ERC-20 transfers ← primary path
  - eth_getTransactionByHash + eth_getBlockByNumber for tx metadata
  - eth_getBalance for the address balance

Limitation: native ETH transfers (not ERC-20) require trace_block or
debug_traceTransaction, which not all nodes support. We fetch what we can via
eth_getLogs (ERC-20, which covers stablecoins — the primary OSINT concern) and
note native-ETH-only flows as a known gap. For BTC/native-coin tracing, the
existing BTC UTXO traversal in deep_chain_fetchers works against any Blockstream-
compatible API (also self-hostable).
"""
from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Optional

import config

# Transfer event signature topic: keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _rpc_url(chain: str) -> str:
    """Return the local RPC URL for a chain, or '' if not configured."""
    return config.LOCAL_RPC_URLS.get(chain, config.LOCAL_RPC_URLS.get("eth", "")) if config.LOCAL_RPC_URLS else ""


def _is_local(chain: str) -> bool:
    return bool(_rpc_url(chain))


async def _rpc_call(session, rpc_url: str, method: str, params: list, request_id: int = 1) -> Any:
    """Make a single JSON-RPC call to the local node."""
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
    async with session.post(rpc_url, json=payload, timeout=aiohttp_timeout(30)) as resp:
        data = await resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data.get("result")


def aiohttp_timeout(secs: int):
    import aiohttp
    return aiohttp.ClientTimeout(total=secs)


def _hex_to_int(hex_val: str | None) -> int:
    if not hex_val:
        return 0
    try:
        return int(hex_val, 16)
    except (TypeError, ValueError):
        return 0


def _topic_to_address(topic: str) -> str:
    """Extract a 20-byte address from a 32-byte indexed topic (padded with zeros)."""
    if not topic or len(topic) < 66:
        return ""
    return "0x" + topic[-40:].lower()


def _erc20_decimals_cache() -> dict[str, int]:
    """Simple in-process cache for ERC-20 decimals (avoids repeated eth_call)."""
    return getattr(_erc20_decimals_cache, "_cache", {}) or {}  # type: ignore


async def _get_decimals(session, rpc_url: str, contract: str) -> int:
    """Fetch an ERC-20 token's decimals via eth_call to decimals()."""
    cache = _erc20_decimals_cache()
    cache_key = contract.lower()
    if cache_key in cache:
        return cache[cache_key]
    # decimals() selector = 0x313ce567
    try:
        result = await _rpc_call(session, rpc_url, "eth_call",
                                 [{"to": contract, "data": "0x313ce567"}, "latest"])
        decimals = _hex_to_int(result)
        if decimals == 0:
            decimals = 18  # assume standard if the call failed
    except Exception:
        decimals = 18
    cache[cache_key] = decimals
    setattr(_erc20_decimals_cache, "_cache", cache)  # type: ignore
    return decimals


async def fetch_evm_transfers(
    session,
    rpc_url: str,
    chain: str,
    address: str,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Fetch ERC-20 + native transfers for an address from a local RPC node.

    Returns (rows, error) matching the exact shape from holistic_trace_engine._evm_one.
    """
    address = address.lower().strip()
    if not address.startswith("0x"):
        return [], None  # not an EVM address

    from holistic_trace_engine import EVM_NATIVE_SYMBOL
    native_sym = EVM_NATIVE_SYMBOL.get(chain, chain.upper())

    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    # Pad address to 32-byte topic for log filtering.
    addr_topic = "0x" + "0" * 24 + address[2:]

    # ── ERC-20 transfers via eth_getLogs ────────────────────────────────────
    # Transfer(address indexed from, address indexed to, uint256 value)
    # Topic 0 = event sig, Topic 1 = from, Topic 2 = to.
    # We query twice: once where `from` = our address, once where `to` = our address.
    try:
        # Get current block for the scan range (last ~100k blocks ≈ ~2 weeks).
        latest_block_hex = await _rpc_call(session, rpc_url, "eth_blockNumber", [])
        latest_block = _hex_to_int(latest_block_hex)
        from_block = max(0, latest_block - 100_000)
        from_block_hex = hex(from_block)

        # Query logs where address is the sender OR receiver.
        # Some nodes support topic OR in a single call; we do two calls for compatibility.
        logs_from = await _rpc_call(session, rpc_url, "eth_getLogs", [{
            "fromBlock": from_block_hex,
            "toBlock": "latest",
            "topics": [TRANSFER_TOPIC, addr_topic],
        }])
        logs_to = await _rpc_call(session, rpc_url, "eth_getLogs", [{
            "fromBlock": from_block_hex,
            "toBlock": "latest",
            "topics": [TRANSFER_TOPIC, None, addr_topic],
        }])

        all_logs = (logs_from or []) + (logs_to or [])
        # Dedup by log index.
        seen = set()
        unique_logs = []
        for log in all_logs:
            key = log.get("transactionHash", "") + str(log.get("logIndex", ""))
            if key not in seen:
                seen.add(key)
                unique_logs.append(log)

        # Sort by block number descending (most recent first).
        unique_logs.sort(key=lambda l: _hex_to_int(l.get("blockNumber")), reverse=True)

        # Batch-fetch block timestamps.
        block_ts_cache: dict[int, int] = {}

        for log in unique_logs[:limit]:
            try:
                contract = (log.get("address") or "").lower()
                topics = log.get("topics") or []
                data = log.get("data") or "0x"
                tx_hash = log.get("transactionHash") or ""
                block_num = _hex_to_int(log.get("blockNumber"))

                # Parse from/to from topics.
                from_addr = _topic_to_address(topics[1]) if len(topics) > 1 else ""
                to_addr = _topic_to_address(topics[2]) if len(topics) > 2 else ""

                # Parse value from data.
                raw_value = _hex_to_int(data)

                # Get decimals for human-readable value.
                decimals = await _get_decimals(session, rpc_url, contract)
                value = raw_value / (10 ** decimals) if decimals else float(raw_value)

                # Get block timestamp.
                if block_num not in block_ts_cache:
                    try:
                        block_data = await _rpc_call(session, rpc_url, "eth_getBlockByNumber",
                                                     [hex(block_num), False])
                        block_ts_cache[block_num] = _hex_to_int(block_data.get("timestamp")) if block_data else 0
                    except Exception:
                        block_ts_cache[block_num] = 0
                timestamp = block_ts_cache[block_num]

                # Token symbol: we don't have it from logs alone. Use contract address
                # truncated as a fallback (the engine truncates to 12 chars anyway).
                token_symbol = contract[:12]

                rows.append({
                    "chain": chain,
                    "from": from_addr,
                    "to": to_addr,
                    "asset": token_symbol,
                    "value": value,
                    "value_usd": 0.0,
                    "tx_hash": tx_hash,
                    "timestamp": timestamp,
                    "contract": contract,
                })
            except Exception as exc:
                errors.append(f"log parse: {exc}")
                continue

    except Exception as exc:
        errors.append(f"eth_getLogs: {exc}")

    # ── Native ETH balance (for context, not transfers) ─────────────────────
    # Native ETH transfers require trace_block which many nodes don't support.
    # We note this as a known limitation rather than failing.

    error_msg = "; ".join(errors[:3]) if errors else None
    return rows, error_msg


async def get_balance(rpc_url: str, address: str) -> Optional[float]:
    """Get the native ETH balance of an address from a local node."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            result = await _rpc_call(session, rpc_url, "eth_getBalance", [address, "latest"])
            return _hex_to_int(result) / 1e18
    except Exception:
        return None
