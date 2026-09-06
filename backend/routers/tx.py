"""
Transaction detail lookup endpoint.
Supports EVM chains (via Etherscan v2), Bitcoin (Blockstream), and Tron (Tronscan).
"""
import asyncio
import os
import re
import time
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from tgbot_runtime import ensure_tgbot_path, tgbot_env

router = APIRouter()

# ── env ─────────────────────────────────────────────────────────────────────
_TGBOT_ENV = tgbot_env()


def _read_saved_env() -> Dict[str, str]:
    if not _TGBOT_ENV.exists():
        return {}
    env: Dict[str, str] = {}
    for line in _TGBOT_ENV.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip("\"'")
    return env


def _env(k: str, d: str = "") -> str:
    return os.environ.get(k) or _read_saved_env().get(k) or d

HTTP_TIMEOUT  = 25


def _etherscan_key() -> str:
    return _env("ETHERSCAN_API_KEY")

# ── EVM chain registry ───────────────────────────────────────────────────────
EVM_CHAINS: Dict[str, Dict[str, Any]] = {
    "ETH":   {"chainid": 1,     "label": "Ethereum",       "unit": "ETH",   "explorer": "https://etherscan.io"},
    "MATIC": {"chainid": 137,   "label": "Polygon",        "unit": "MATIC", "explorer": "https://polygonscan.com"},
    "BSC":   {"chainid": 56,    "label": "BNB Smart Chain","unit": "BNB",   "explorer": "https://bscscan.com"},
    "ARB":   {"chainid": 42161, "label": "Arbitrum",       "unit": "ETH",   "explorer": "https://arbiscan.io"},
    "OP":    {"chainid": 10,    "label": "Optimism",       "unit": "ETH",   "explorer": "https://optimistic.etherscan.io"},
    "BASE":  {"chainid": 8453,  "label": "Base",           "unit": "ETH",   "explorer": "https://basescan.org"},
}

PUBLIC_EVM_RPC: Dict[str, List[str]] = {
    "ETH": [
        "https://ethereum-rpc.publicnode.com",
        "https://cloudflare-eth.com",
    ],
    "MATIC": [
        "https://polygon.drpc.org",
    ],
    "BSC": [
        "https://bsc-dataseed.bnbchain.org",
        "https://bsc-rpc.publicnode.com",
    ],
    "ARB": [
        "https://arb1.arbitrum.io/rpc",
    ],
    "OP": [
        "https://mainnet.optimism.io",
    ],
    "BASE": [
        "https://mainnet.base.org",
    ],
}

# ERC-20 Transfer topic0
_ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


# ── helpers ──────────────────────────────────────────────────────────────────
def _is_eth_tx(h: str) -> bool:
    return bool(re.match(r"^0x[a-fA-F0-9]{64}$", (h or "").strip()))

def _is_btc_tx(h: str) -> bool:
    return bool(re.match(r"^[a-fA-F0-9]{64}$", (h or "").strip()))

def _detect_chain(tx_hash: str, hint: str = "") -> str:
    if hint.upper() in EVM_CHAINS:
        return hint.upper()
    if hint.upper() == "BTC":
        return "BTC"
    if hint.upper() == "TRX":
        return "TRX"
    if _is_eth_tx(tx_hash):
        return "ETH"
    if _is_btc_tx(tx_hash):
        return "BTC"
    return "ETH"

def _wei_to_eth(val: str, decimals: int = 18) -> float:
    try:
        return int(val, 16) / (10 ** decimals) if val.startswith("0x") else int(val) / (10 ** decimals)
    except Exception:
        return 0.0

def _hex_to_int(val: str) -> int:
    try:
        return int(val, 16) if val and val.startswith("0x") else int(val or 0)
    except Exception:
        return 0

def _from_unix(ts: Any) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))
    except Exception:
        return str(ts)


async def _http_get(url: str, params: dict | None = None) -> Optional[dict]:
    try:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url, params=params) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
    except Exception:
        pass
    return None

async def _http_post(url: str, payload: dict) -> Optional[dict]:
    try:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(url, json=payload, headers={"Content-Type": "application/json"}) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
    except Exception:
        pass
    return None


# ── EVM via Etherscan v2 ─────────────────────────────────────────────────────
async def _etherscan_rpc(method: str, params: list, chainid: int) -> Any:
    key = _etherscan_key()
    if not key:
        return None

    query: Dict[str, Any] = {
        "chainid": chainid,
        "module":  "proxy",
        "action":  method,
        "apikey":  key,
    }
    if method in {"eth_getTransactionByHash", "eth_getTransactionReceipt"}:
        query["txhash"] = params[0] if params else ""
    elif method == "eth_getBlockByNumber":
        query["tag"] = params[0] if params else "latest"
        query["boolean"] = str(params[1] if len(params) > 1 else False).lower()
    else:
        for i, value in enumerate(params):
            query[f"param{i + 1}"] = value

    data = await _http_get("https://api.etherscan.io/v2/api", query)
    if not isinstance(data, dict):
        return None
    result = data.get("result")
    if isinstance(result, dict) or isinstance(result, list):
        return result
    return None


async def _etherscan_module(module: str, action: str, chainid: int, **kwargs) -> Any:
    key = _etherscan_key()
    if not key:
        return None
    params = {"chainid": chainid, "module": module, "action": action, "apikey": key, **kwargs}
    data = await _http_get("https://api.etherscan.io/v2/api", params)
    if data and data.get("status") == "1":
        return data.get("result")
    return None


async def _public_evm_rpc(chain: str, method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for url in PUBLIC_EVM_RPC.get(chain, []):
        data = await _http_post(url, payload)
        if not isinstance(data, dict):
            continue
        result = data.get("result")
        if isinstance(result, dict) or isinstance(result, list):
            return result
    return None


def _decode_erc20_log(log: dict, chain_info: dict) -> Optional[dict]:
    """Decode an ERC-20 Transfer log entry."""
    topics = log.get("topics", [])
    if not topics or topics[0].lower() != _ERC20_TRANSFER_TOPIC:
        return None
    if len(topics) < 3:
        return None
    def pad_addr(t: str) -> str:
        return "0x" + t[-40:] if len(t) >= 42 else t
    from_addr = pad_addr(topics[1])
    to_addr   = pad_addr(topics[2])
    data_hex  = log.get("data", "0x")
    try:
        raw_val = int(data_hex, 16)
    except Exception:
        raw_val = 0
    return {
        "from":            from_addr,
        "to":              to_addr,
        "value_raw":       str(raw_val),
        "contract":        log.get("address", ""),
        "log_index":       _hex_to_int(log.get("logIndex", "0x0")),
        "tx_hash":         log.get("transactionHash", ""),
    }


async def _lookup_evm_tx(tx_hash: str, chain: str) -> dict:
    chain_info = EVM_CHAINS.get(chain, EVM_CHAINS["ETH"])
    chainid    = chain_info["chainid"]
    has_etherscan_key = bool(_etherscan_key())

    # Parallel fetch: tx + receipt + internal txs
    tx_raw, receipt_raw, internal_raw = await asyncio.gather(
        _etherscan_rpc("eth_getTransactionByHash", [tx_hash], chainid),
        _etherscan_rpc("eth_getTransactionReceipt", [tx_hash], chainid),
        _etherscan_module("account", "txlistinternal", chainid,
                          txhash=tx_hash, sort="asc"),
        return_exceptions=True,
    )

    if isinstance(tx_raw, Exception):
        tx_raw = None
    if isinstance(receipt_raw, Exception):
        receipt_raw = None
    if isinstance(internal_raw, Exception):
        internal_raw = None
    if not isinstance(tx_raw, dict):
        tx_raw = None
    if not isinstance(receipt_raw, dict):
        receipt_raw = None
    if not isinstance(internal_raw, list):
        internal_raw = None

    rpc_fallback_used = False
    if tx_raw is None:
        tx_raw = await _public_evm_rpc(chain, "eth_getTransactionByHash", [tx_hash])
        rpc_fallback_used = isinstance(tx_raw, dict)
    if receipt_raw is None:
        receipt_raw = await _public_evm_rpc(chain, "eth_getTransactionReceipt", [tx_hash])
        rpc_fallback_used = rpc_fallback_used or isinstance(receipt_raw, dict)

    if tx_raw is None and receipt_raw is None:
        if not has_etherscan_key:
            return {
                "hash": tx_hash, "chain": chain,
                "chain_label": chain_info["label"],
                "error": "Could not fetch EVM transaction from Etherscan or public RPC. Check the tx hash, selected chain, and public RPC availability.",
                "explorer_url": f"{chain_info['explorer']}/tx/{tx_hash}",
            }
        return {
            "hash": tx_hash, "chain": chain,
            "chain_label": chain_info["label"],
            "error": "Could not fetch EVM transaction from Etherscan or public RPC. Check the tx hash, selected chain, API key permissions, and public RPC availability.",
            "explorer_url": f"{chain_info['explorer']}/tx/{tx_hash}",
        }

    tx      = tx_raw or {}
    receipt = receipt_raw or {}

    # Decode status
    status_hex = receipt.get("status", "0x1")
    status = "success" if _hex_to_int(status_hex) == 1 else "failed"

    # Basic values
    value_eth    = _wei_to_eth(tx.get("value", "0x0"))
    gas_limit    = _hex_to_int(tx.get("gas", "0x0"))
    gas_used     = _hex_to_int(receipt.get("gasUsed", "0x0"))
    gas_price_w  = _hex_to_int(tx.get("gasPrice", "0x0"))
    gas_price_gwei = gas_price_w / 1e9
    fee_eth      = (gas_used * gas_price_w) / 1e18
    nonce        = _hex_to_int(tx.get("nonce", "0x0"))
    block_num    = _hex_to_int(tx.get("blockNumber", "0x0"))
    tx_index     = _hex_to_int(receipt.get("transactionIndex", "0x0"))

    # Block timestamp via eth_getBlockByNumber
    block_data = None
    if block_num:
        if _etherscan_key():
            block_data = await _etherscan_rpc(
                "eth_getBlockByNumber", [hex(block_num), False], chainid
            )
        if not isinstance(block_data, dict):
            block_data = await _public_evm_rpc(chain, "eth_getBlockByNumber", [hex(block_num), False])
    timestamp = ""
    if isinstance(block_data, dict):
        ts = _hex_to_int(block_data.get("timestamp", "0x0"))
        timestamp = _from_unix(ts) if ts else ""

    # Token transfers from logs
    logs = receipt.get("logs", []) if isinstance(receipt, dict) else []
    token_transfers = []
    for lg in logs:
        decoded = _decode_erc20_log(lg, chain_info)
        if decoded:
            token_transfers.append(decoded)

    # Input data decoding
    input_data  = tx.get("input", "0x")
    method_id   = input_data[:10] if len(input_data) >= 10 else None
    is_contract = bool(input_data and input_data != "0x")

    # Internal transactions
    internals = []
    if isinstance(internal_raw, list):
        for itx in internal_raw[:20]:
            internals.append({
                "from":        itx.get("from", ""),
                "to":          itx.get("to", ""),
                "value_eth":   int(itx.get("value", "0")) / 1e18,
                "type":        itx.get("type", "call"),
                "gas":         itx.get("gas", ""),
                "gas_used":    itx.get("gasUsed", ""),
                "error":       itx.get("errCode", "") or itx.get("isError", ""),
            })

    return {
        "hash":             tx_hash,
        "chain":            chain,
        "chain_label":      chain_info["label"],
        "native_unit":      chain_info["unit"],
        "status":           status,
        "block":            block_num,
        "timestamp":        timestamp,
        "confirmations":    None,
        "from":             tx.get("from", ""),
        "to":               tx.get("to", "") or receipt.get("contractAddress", ""),
        "contract_created": receipt.get("contractAddress") if not tx.get("to") else None,
        "value":            value_eth,
        "value_usd":        None,
        "gas_limit":        gas_limit,
        "gas_used":         gas_used,
        "gas_efficiency":   round(gas_used / gas_limit * 100, 1) if gas_limit > 0 else None,
        "gas_price_gwei":   round(gas_price_gwei, 3),
        "tx_fee":           round(fee_eth, 8),
        "nonce":            nonce,
        "tx_index":         tx_index,
        "is_contract_call": is_contract,
        "method_id":        method_id,
        "input_data":       input_data if len(input_data) < 2000 else input_data[:2000] + "...",
        "token_transfers":  token_transfers,
        "internal_txs":     internals,
        "log_count":        len(logs),
        "lookup_source":    "public_rpc_fallback" if rpc_fallback_used else "etherscan_v2",
        "explorer_url":     f"{chain_info['explorer']}/tx/{tx_hash}",
    }


# ── Bitcoin via Blockstream ──────────────────────────────────────────────────
async def _lookup_btc_tx(tx_hash: str) -> dict:
    data = await _http_get(f"https://blockstream.info/api/tx/{tx_hash}")
    if not data:
        return {
            "hash": tx_hash, "chain": "BTC", "chain_label": "Bitcoin",
            "error": "Could not fetch BTC transaction from Blockstream",
            "explorer_url": f"https://blockstream.info/tx/{tx_hash}",
        }

    status = data.get("status", {})
    vin    = data.get("vin", [])
    vout   = data.get("vout", [])

    total_in  = sum(v.get("prevout", {}).get("value", 0) for v in vin) / 1e8
    total_out = sum(v.get("value", 0) for v in vout) / 1e8
    fee_btc   = round(total_in - total_out, 8) if total_in > 0 else None

    inputs = [
        {
            "address": v.get("prevout", {}).get("scriptpubkey_address", ""),
            "value_btc": v.get("prevout", {}).get("value", 0) / 1e8,
        }
        for v in vin
    ]
    outputs = [
        {
            "address": v.get("scriptpubkey_address", ""),
            "value_btc": v.get("value", 0) / 1e8,
            "type": v.get("scriptpubkey_type", ""),
        }
        for v in vout
    ]

    ts = status.get("block_time")
    return {
        "hash":         tx_hash,
        "chain":        "BTC",
        "chain_label":  "Bitcoin",
        "native_unit":  "BTC",
        "status":       "confirmed" if status.get("confirmed") else "mempool",
        "block":        status.get("block_height"),
        "timestamp":    _from_unix(ts) if ts else "",
        "confirmations": None,
        "from":         inputs[0]["address"] if inputs else "",
        "to":           outputs[0]["address"] if outputs else "",
        "value":        total_out,
        "value_usd":    None,
        "fee_btc":      fee_btc,
        "size_bytes":   data.get("size"),
        "vsize":        data.get("vsize"),
        "weight":       data.get("weight"),
        "inputs":       inputs[:20],
        "outputs":      outputs[:20],
        "input_count":  len(vin),
        "output_count": len(vout),
        "is_coinbase":  bool(vin and vin[0].get("is_coinbase")),
        "token_transfers": [],
        "internal_txs": [],
        "explorer_url": f"https://blockstream.info/tx/{tx_hash}",
    }


# ── Tron via Tronscan ────────────────────────────────────────────────────────
async def _lookup_trx_tx(tx_hash: str) -> dict:
    data = await _http_get(
        "https://apilist.tronscanapi.com/api/transaction-info",
        {"hash": tx_hash},
    )
    if not data or "hash" not in (data or {}):
        return {
            "hash": tx_hash, "chain": "TRX", "chain_label": "Tron",
            "error": "Could not fetch TRX transaction from Tronscan",
            "explorer_url": f"https://tronscan.org/#/transaction/{tx_hash}",
        }

    contracts = data.get("contractRet", "")
    status = "success" if contracts == "SUCCESS" else ("failed" if contracts else "unknown")

    # Token transfers
    token_transfers = []
    for t in (data.get("trc20TransferInfo") or []):
        token_transfers.append({
            "from":     t.get("from_address", ""),
            "to":       t.get("to_address", ""),
            "value_raw": t.get("amount_str", ""),
            "contract": t.get("contract_address", ""),
            "symbol":   t.get("symbol", ""),
            "decimals": t.get("decimals", 6),
        })

    return {
        "hash":         tx_hash,
        "chain":        "TRX",
        "chain_label":  "Tron",
        "native_unit":  "TRX",
        "status":       status,
        "block":        data.get("block"),
        "timestamp":    _from_unix(data["timestamp"] / 1000) if data.get("timestamp") else "",
        "confirmations": data.get("confirmed", False),
        "from":         data.get("ownerAddress", ""),
        "to":           data.get("toAddress", ""),
        "value":        (data.get("amount") or 0) / 1e6,
        "fee_trx":      (data.get("cost", {}).get("fee") or 0) / 1e6,
        "energy_used":  data.get("cost", {}).get("energy_usage", 0),
        "bandwidth":    data.get("cost", {}).get("net_usage", 0),
        "contract_type": data.get("contractType"),
        "token_transfers": token_transfers,
        "internal_txs": [],
        "explorer_url": f"https://tronscan.org/#/transaction/{tx_hash}",
    }


# ── Router endpoint ──────────────────────────────────────────────────────────
class TxRequest(BaseModel):
    hash: str
    chain: Optional[str] = None


@router.post("/tx")
async def lookup_transaction(req: TxRequest):
    """
    Fetch full transaction details for forensic analysis.
    Supports EVM (ETH/MATIC/BSC/ARB/OP/BASE), BTC, and TRX.
    """
    tx_hash = req.hash.strip()
    chain   = _detect_chain(tx_hash, req.chain or "")

    try:
        if chain == "BTC":
            result = await _lookup_btc_tx(tx_hash)
        elif chain == "TRX":
            result = await _lookup_trx_tx(tx_hash)
        else:
            result = await _lookup_evm_tx(tx_hash, chain)

        # Risk-assess from/to addresses inline (lightweight)
        result["risk_hints"] = {}
        from_addr = result.get("from", "")
        to_addr   = result.get("to", "")
        if from_addr or to_addr:
            try:
                ensure_tgbot_path()
                from crypto_osint import check_sanctions
                # Only check the addresses asynchronously - quick sanction check
                addrs_to_check = [a for a in [from_addr, to_addr] if a][:2]
                hints = await asyncio.gather(
                    *[check_sanctions(a) for a in addrs_to_check],
                    return_exceptions=True,
                )
                for addr, hint in zip(addrs_to_check, hints):
                    if isinstance(hint, dict) and hint.get("sanctioned"):
                        result["risk_hints"][addr] = {"sanctioned": True, "source": hint.get("source", "")}
            except Exception:
                pass

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tx/chains")
async def list_supported_chains():
    return {"evm": list(EVM_CHAINS.keys()), "other": ["BTC", "TRX"]}
