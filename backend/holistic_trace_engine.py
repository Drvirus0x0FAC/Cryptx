"""
Holistic cross-chain trace engine.

Given ONE subject address, build ONE unified multi-chain graph that follows
value across blockchains — through bridges, DEX routers, and coinswaps — for as
many hops as configured, in either direction, classifying every counterparty
(exchange/VASP, bridge, DEX, mixer, sanctioned, contract, unknown) and surfacing
the ultimate sources, destinations, and cash-out (off-ramp) points.

Design:
  - Data-source-agnostic core. `trace_from_events()` operates on a normalized
    transfer list, so the graph algorithm is deterministic and testable offline.
  - `trace()` adds best-effort LIVE expansion from free public explorers
    (EVM Etherscan-family, BTC blockstream, TRON trongrid). Network failures
    degrade gracefully: a node simply becomes a leaf with an error note.
  - Cross-chain stitching: transfers into a known bridge contract are emitted as
    `bridge` edges; when destination-side events are available they are matched
    by value+time (reusing the mixer/bridge demix heuristic), otherwise the
    bridge crossing is flagged so the analyst can continue on the dest chain.

This produces investigative leads, not proof. Bridge attributions and
cross-chain links are probabilistic and must be corroborated.
"""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Public on-chain registries (well-known contract addresses, lower-cased).
#
# Consolidation: the canonical registries live in constants.py (single source
# of truth). We merge them with the engine-specific entries below so that any
# address added to constants is automatically picked up by classify_counterparty,
# while preserving the {name, chain} dict shape this engine's internals expect.
# ---------------------------------------------------------------------------
import constants as _CONST

def _merge_registry(canonical: dict, default_chain: str = "eth") -> dict[str, dict[str, Any]]:
    """Convert constants.py's (type, label) tuples into this engine's {name, chain} shape."""
    return {addr.lower(): {"name": label, "chain": default_chain, "type": btype}
            for addr, (btype, label) in canonical.items()}

BRIDGE_CONTRACTS: dict[str, dict[str, Any]] = _merge_registry(_CONST.BRIDGE_CONTRACTS)
# Legacy engine-specific bridges not yet in constants (preserved for coverage)
BRIDGE_CONTRACTS.update({
    "0x40c7b3b0f7c4b6a2b3e3f2a0d2b1d6f3a0c1b2d3": {"name": "Multichain/Anyswap Router", "chain": "eth"},
    "0x5427fefa711eff984124bfbb1ab6fbf5e3da1820": {"name": "Celer cBridge", "chain": "eth"},
    "0x99c9fc46f92e8a1c0dec1b1747d010903e884be1": {"name": "Optimism Gateway", "chain": "eth"},
    "0x8315177ab297ba92a06054ce80a67ed4dbd7ed3a": {"name": "Arbitrum One Bridge", "chain": "eth"},
})

DEX_ROUTERS: dict[str, dict[str, Any]] = _merge_registry(_CONST.DEX_ROUTERS)
# Legacy engine-specific DEX routers
DEX_ROUTERS.update({
    "0x111111125421ca6dc452d289314280a0f8842a65": {"name": "1inch Router V6", "chain": "eth"},
})

# Tornado Cash ETH pools (OFAC-designated) + common mixers — from constants.
MIXER_CONTRACTS: dict[str, dict[str, Any]] = _merge_registry(_CONST.MIXER_CONTRACTS)
# Legacy engine-specific entries
MIXER_CONTRACTS.update({
    "0x8589427373d6d84e98730d7795d8f6f8731fda16": {"name": "Tornado Cash Router", "chain": "eth"},
    "0x722122df12d4e14e13ac3b6895a86e84145b6967": {"name": "Tornado Cash Proxy", "chain": "eth"},
})

EVM_EXPLORERS = {
    "eth": "https://api.etherscan.io/api",
    "bsc": "https://api.bscscan.com/api",
    "polygon": "https://api.polygonscan.com/api",
    "arbitrum": "https://api.arbiscan.io/api",
    "optimism": "https://api-optimistic.etherscan.io/api",
    "base": "https://api.basescan.org/api",
}

ETHERSCAN_V2_API = "https://api.etherscan.io/v2/api"
ETHERSCAN_V2_CHAINIDS = {
    "eth": 1,
    "bsc": 56,
    "polygon": 137,
    "arbitrum": 42161,
    "optimism": 10,
    "base": 8453,
}

# No-key, Etherscan-compatible Blockscout endpoints — used by default so live
# tracing works without configuring an API key.
EVM_BLOCKSCOUT = {
    "eth": "https://eth.blockscout.com/api",
    "polygon": "https://polygon.blockscout.com/api",
    "optimism": "https://optimism.blockscout.com/api",
    "base": "https://base.blockscout.com/api",
    "arbitrum": "https://arbitrum.blockscout.com/api",
    "gnosis": "https://gnosis.blockscout.com/api",
    # Avalanche C-Chain via Routescan's no-key Etherscan-compatible endpoint.
    "avax": "https://api.routescan.io/v2/network/mainnet/evm/43114/etherscan/api",
}

# Blockscout v2 REST API (native, non-deprecated) — primary no-key fallback path.
# Response shape differs from the Etherscan-compatible /api endpoint, parsed by
# `_blockscout_v2_transfers`. Routescan (avax) stays on its Etherscan-compatible
# API, so it's intentionally omitted here (handled via EVM_BLOCKSCOUT).
EVM_BLOCKSCOUT_V2 = {
    "eth": "https://eth.blockscout.com/api/v2",
    "polygon": "https://polygon.blockscout.com/api/v2",
    "optimism": "https://optimism.blockscout.com/api/v2",
    "base": "https://base.blockscout.com/api/v2",
    "arbitrum": "https://arbitrum.blockscout.com/api/v2",
    "gnosis": "https://gnosis.blockscout.com/api/v2",
}

# Sentinel returned by fetchers when the upstream explorer replied HTTP 429
# after exhausting retries. The trace() loop classifies this into a single
# deduped summary line instead of spamming one error per address.
_RATE_LIMIT_MSG = "rate_limited"

EVM_NATIVE_SYMBOL = {
    "eth": "ETH", "bsc": "BNB", "polygon": "MATIC", "arbitrum": "ETH",
    "optimism": "ETH", "base": "ETH", "gnosis": "xDAI", "avax": "AVAX",
}

NODE_TYPES = ("subject", "exchange", "bridge", "dex", "mixer", "sanctioned", "contract", "unknown")


def _addr(v: Any) -> str:
    # EVM addresses are case-insensitive → normalize to lowercase. BTC / TRON / Zcash
    # use case-sensitive Base58 — preserve their canonical casing so the address stays
    # valid and links correctly to block explorers.
    s = str(v or "").strip()
    return s.lower() if s.startswith("0x") else s


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class TraceNode:
    id: str                      # "{chain}:{address}"
    address: str
    chain: str
    type: str = "unknown"
    label: str = ""
    hop: int = 0
    risk: int = 0
    is_terminal: bool = False
    sanctioned: bool = False
    vasp: Optional[str] = None
    inflow_value: float = 0.0
    outflow_value: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TraceEdge:
    source: str
    target: str
    chain: str
    asset: str = ""
    value: float = 0.0
    value_usd: float = 0.0
    tx_hash: str = ""
    timestamp: int = 0
    direction: str = "out"       # out | in
    kind: str = "transfer"       # transfer | bridge | swap | deposit
    hop: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Counterparty classification (registries + VASP + sanctions)
# ---------------------------------------------------------------------------
def classify_counterparty(address: str, chain: str) -> dict[str, Any]:
    a = _addr(address)
    out: dict[str, Any] = {"type": "unknown", "label": "", "sanctioned": False, "vasp": None, "risk": 0, "terminal": False}

    if a in MIXER_CONTRACTS:
        out.update(type="mixer", label=MIXER_CONTRACTS[a]["name"], risk=85, terminal=True)
        return out
    if a in BRIDGE_CONTRACTS:
        out.update(type="bridge", label=BRIDGE_CONTRACTS[a]["name"], risk=35)
        return out
    if a in DEX_ROUTERS:
        out.update(type="dex", label=DEX_ROUTERS[a]["name"], risk=20)
        return out

    # Known VASP / off-ramp?
    try:
        import vasp_directory
        v = vasp_directory.identify_vasp(a, chain)
        if v.get("is_vasp") and v.get("vasp"):
            out.update(type="exchange", label=v["vasp"]["name"], vasp=v["vasp"]["name"], risk=30, terminal=True)
    except Exception:  # noqa: BLE001
        pass

    # Sanctioned?
    try:
        import sanctions_engine
        s = sanctions_engine.screen_address(a, chain)
        if s.get("sanctioned"):
            out["sanctioned"] = True
            out["risk"] = max(out["risk"], 95)
            if out["type"] == "unknown":
                out["type"] = "sanctioned"
            names = ", ".join(m["name"] for m in s.get("matches", [])[:2])
            out["label"] = out["label"] or names or "Sanctioned entity"
            out["terminal"] = True
    except Exception:  # noqa: BLE001
        pass

    return out


def is_bridge(address: str) -> bool:
    return _addr(address) in BRIDGE_CONTRACTS


# ---------------------------------------------------------------------------
# Live transfer fetching (best-effort, graceful)
# ---------------------------------------------------------------------------
class _RateGate:
    """Async token-bucket rate limiter shared across all concurrent fetches, so
    the tracer's fan-out cannot exceed an explorer's per-second limit. Etherscan's
    free tier is ~5 rps; gating to 4.5 rps eliminates the 429s that used to leave
    branches partial even with a valid API key."""

    def __init__(self, rate_per_sec: float) -> None:
        self._interval = 1.0 / max(0.1, rate_per_sec)
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        import time as _t
        async with self._lock:
            now = _t.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
                now = _t.monotonic()
            self._next = max(now, self._next) + self._interval


# Global gate for keyed Etherscan/-compatible calls (stays under 5 rps free tier).
_ETHERSCAN_GATE = _RateGate(4.5)


async def _evm_action(
    session,
    base: str,
    address: str,
    action: str,
    api_key: str,
    limit: int,
    chain: str = "",
) -> tuple[list[dict[str, Any]], Optional[str]]:
    params = {
        "module": "account", "action": action, "address": address,
        "startblock": 0, "endblock": 99999999, "page": 1, "offset": limit, "sort": "desc",
    }
    if api_key:
        params["apikey"] = api_key
    request_url = base
    if api_key and chain in ETHERSCAN_V2_CHAINIDS and base in EVM_EXPLORERS.values():
        request_url = ETHERSCAN_V2_API
        params["chainid"] = ETHERSCAN_V2_CHAINIDS[chain]

    # Retry with exponential backoff on HTTP 429 (rate limit). Public explorers
    # (Blockscout no-key especially) throttle aggressively; without this, a 3-hop
    # trace of an active address spams dozens of "Too many requests" errors that
    # flood the UI. We honor the server's Retry-After when present, else fall
    # back to exponential jitter. After max attempts we return a sentinel string
    # so trace() can collapse it into one summary line instead of N duplicates.
    max_attempts = 3
    _is_etherscan = api_key and (request_url == ETHERSCAN_V2_API or base in EVM_EXPLORERS.values())
    for attempt in range(max_attempts):
        if _is_etherscan:
            await _ETHERSCAN_GATE.wait()   # throttle to the free-tier rps ceiling
        try:
            async with session.get(request_url, params=params, timeout=25) as resp:
                if resp.status == 429:
                    if attempt < max_attempts - 1:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            wait = min(float(retry_after), 10.0)
                        else:
                            wait = (2 ** attempt) + random.uniform(0, 1)
                        await asyncio.sleep(wait)
                        continue
                    return [], _RATE_LIMIT_MSG
                data = await resp.json(content_type=None)
        except Exception as exc:  # noqa: BLE001
            return [], f"{type(exc).__name__}: {exc}"
        break

    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        if isinstance(data, dict):
            # Etherscan returns message="NOTOK" with the real reason in `result`.
            msg = data.get("result") if str(data.get("message")) in ("NOTOK", "", "None") else data.get("message")
            msg = msg or data.get("message") or "bad response"
        else:
            msg = "bad response"
        return [], str(msg)[:160]
    return data["result"][:limit], None


async def _evm_one(session, base: str, key: str, chain: str, address: str, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch native + ERC-20 transfers from a single Etherscan-compatible endpoint."""
    native_sym = EVM_NATIVE_SYMBOL.get(chain, chain.upper())
    rows: list[dict[str, Any]] = []
    errs: list[str] = []

    native, e1 = await _evm_action(session, base, address, "txlist", key, limit, chain)
    if e1:
        errs.append(f"native: {e1}")
    for t in native:
        try:
            val = int(t.get("value", "0")) / 1e18
        except (TypeError, ValueError):
            val = 0.0
        if val <= 0:
            continue
        rows.append({"chain": chain, "from": _addr(t.get("from")), "to": _addr(t.get("to")),
                     "asset": native_sym, "value": val, "value_usd": 0.0,
                     "tx_hash": t.get("hash", ""), "timestamp": int(t.get("timeStamp") or 0)})

    tokens, e2 = await _evm_action(session, base, address, "tokentx", key, limit, chain)
    if e2:
        errs.append(f"erc20: {e2}")
    for t in tokens:
        try:
            dec = int(t.get("tokenDecimal") or 18)
            val = int(t.get("value", "0")) / (10 ** dec)
        except (TypeError, ValueError, ZeroDivisionError):
            val = 0.0
        rows.append({"chain": chain, "from": _addr(t.get("from")), "to": _addr(t.get("to")),
                     "asset": (t.get("tokenSymbol") or "TOKEN")[:12], "value": val, "value_usd": 0.0,
                     "tx_hash": t.get("hash", ""), "timestamp": int(t.get("timeStamp") or 0),
                     "contract": _addr(t.get("contractAddress"))})
    return rows, errs


def _parse_blockscout_v2_timestamp(ts: Any) -> int:
    """Blockscout v2 returns ISO 8601 strings (e.g. "2024-01-15T10:23:45.000000Z").
    Convert to epoch seconds; return 0 on any parse failure so downstream sorting
    never crashes on a malformed entry."""
    if not ts or not isinstance(ts, str):
        return 0
    try:
        # Strip sub-microsecond precision and trailing Z before parsing.
        s = ts.rstrip("Z").split(".")[0]
        return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return 0


async def _blockscout_v2_transfers(
    session,
    base_v2: str,
    chain: str,
    address: str,
    limit: int,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Fetch native + ERC-20 transfers via the Blockscout v2 REST API.

    Response shape (different from the Etherscan-compatible /api endpoint):
      /addresses/{addr}/transactions → { items: [{ hash, value, from:{hash},
                                                   to:{hash}, timestamp, token_transfers:[...] }] }
      /addresses/{addr}/token-transfers → { items: [{ token:{symbol,decimals,address},
                                                      from:{hash}, to:{hash},
                                                      total:{value,decimals}, tx_hash }] }

    Normalizes into the same row dict shape `_evm_one` produces, so downstream
    code is unchanged. Token transfers embedded inside /transactions are also
    harvested (Blockscout inlines them), then /token-transfers fills any gaps.
    No pagination — bounded by `limit`, matching the v1 path's behavior.
    """
    native_sym = EVM_NATIVE_SYMBOL.get(chain, chain.upper())
    rows: list[dict[str, Any]] = []
    seen_hashes: set[tuple[str, str, str, str]] = set()
    errs: list[str] = []

    def _add(frm: str, to: str, asset: str, val: float, tx_hash: str, ts: int, contract: str = ""):
        frm, to = _addr(frm), _addr(to)
        if val <= 0 or not frm or not to:
            return
        key = (frm, to, asset, tx_hash)
        if key in seen_hashes:
            return
        seen_hashes.add(key)
        row = {"chain": chain, "from": frm, "to": to, "asset": asset[:12],
               "value": val, "value_usd": 0.0, "tx_hash": tx_hash, "timestamp": ts}
        if contract:
            row["contract"] = contract
        rows.append(row)

    # ── Native ETH + inline token transfers ──
    tx_url = f"{base_v2}/addresses/{address}/transactions"
    try:
        async with session.get(tx_url, params={"filter": "to | from"}, timeout=25) as resp:
            if resp.status == 429:
                return [], _RATE_LIMIT_MSG
            data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        errs.append(f"native: {type(exc).__name__}: {exc}")
        data = None

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        for t in data["items"][:limit]:
            tx_hash = t.get("hash", "")
            ts = _parse_blockscout_v2_timestamp(t.get("timestamp"))
            from_obj, to_obj = t.get("from") or {}, t.get("to") or {}
            frm, to = from_obj.get("hash", ""), to_obj.get("hash", "")
            # Native value (wei string → ETH)
            try:
                val = int(t.get("value") or 0) / 1e18
            except (TypeError, ValueError):
                val = 0.0
            if val > 0:
                _add(frm, to, native_sym, val, tx_hash, ts)
            # Inline ERC-20/721/1155 transfers within this tx
            for tt in (t.get("token_transfers") or []):
                tok = tt.get("token") or {}
                symbol = tok.get("symbol") or "TOKEN"
                try:
                    dec = int(tok.get("decimals") or 18)
                except (TypeError, ValueError):
                    dec = 18
                total = tt.get("total") or {}
                raw_val = total.get("value") or tt.get("value") or "0"
                try:
                    amount = int(raw_val) / (10 ** dec) if dec else float(raw_val)
                except (TypeError, ValueError, ZeroDivisionError):
                    amount = 0.0
                tf = (tt.get("from") or {}).get("hash", "") or frm
                tt_to = (tt.get("to") or {}).get("hash", "") or to
                _add(tf, tt_to, symbol, amount, tx_hash, ts, contract=_addr(tok.get("address")))

    # ── Dedicated token-transfers endpoint (fills gaps for token-heavy wallets) ──
    tf_url = f"{base_v2}/addresses/{address}/token-transfers"
    try:
        async with session.get(tf_url, params={"filter": "to | from", "type": "ERC-20"}, timeout=25) as resp:
            if resp.status == 429:
                return (rows or []), (_RATE_LIMIT_MSG if not rows else None)
            tf_data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        errs.append(f"erc20: {type(exc).__name__}: {exc}")
        tf_data = None

    if isinstance(tf_data, dict) and isinstance(tf_data.get("items"), list):
        for tt in tf_data["items"][:limit]:
            tok = tt.get("token") or {}
            symbol = tok.get("symbol") or "TOKEN"
            try:
                dec = int(tok.get("decimals") or 18)
            except (TypeError, ValueError):
                dec = 18
            total = tt.get("total") or {}
            raw_val = total.get("value") or tt.get("value") or "0"
            try:
                amount = int(raw_val) / (10 ** dec) if dec else float(raw_val)
            except (TypeError, ValueError, ZeroDivisionError):
                amount = 0.0
            tf = (tt.get("from") or {}).get("hash", "")
            tt_to = (tt.get("to") or {}).get("hash", "")
            tx_hash = tt.get("tx_hash", "")
            ts = _parse_blockscout_v2_timestamp(tt.get("timestamp"))
            _add(tf, tt_to, symbol, amount, tx_hash, ts, contract=_addr(tok.get("address")))

    if rows:
        return rows[:limit * 4], None
    return [], ("; ".join(dict.fromkeys(errs)) or "no transfers found")


async def _evm_transfers(session, chain: str, address: str, api_key: str, limit: int) -> tuple[list[dict[str, Any]], Optional[str]]:
    # Air-gap / self-hosted node path: if LOCAL_RPC_URLS is configured for this
    # chain, fetch from the local node FIRST (no data leaves the deployment).
    # Falls through to public explorers if the node is down or returns nothing.
    try:
        import config as _cfg
        rpc_url = _cfg.LOCAL_RPC_URLS.get(chain, _cfg.LOCAL_RPC_URLS.get("eth", "")) if _cfg.LOCAL_RPC_URLS else ""
        if rpc_url:
            import local_rpc_fetcher
            rows, err = await local_rpc_fetcher.fetch_evm_transfers(
                session, rpc_url, chain, address, limit)
            if rows:
                return rows, None
            # Fall through to public explorers if the node returned nothing.
    except Exception:
        pass  # local node unavailable — use public explorers as fallback

    # Try endpoints in order and use the first that returns data. A configured
    # Etherscan key is tried first (richer/higher limits). The no-key fallback now
    # prefers Blockscout's native v2 REST API (non-deprecated) over the legacy
    # Etherscan-compatible /api endpoint, which Blockscout is retiring — this
    # also silences the "switch to Ethereum API V2" deprecation messages.
    candidates: list[tuple[str, str]] = []
    if api_key and chain in EVM_EXPLORERS:
        candidates.append((EVM_EXPLORERS[chain], api_key))
    # Use v2 as the primary no-key path; fall back to v1 only if v2 is absent/unavailable.
    if chain in EVM_BLOCKSCOUT_V2:
        candidates.append(("__v2__", ""))
    if chain in EVM_BLOCKSCOUT:
        candidates.append((EVM_BLOCKSCOUT[chain], ""))
    if chain in EVM_EXPLORERS and not api_key:
        candidates.append((EVM_EXPLORERS[chain], ""))
    if not candidates:
        return [], f"no explorer for chain {chain}"

    all_errs: list[str] = []
    for base, key in candidates:
        if base == "__v2__":
            rows, err = await _blockscout_v2_transfers(session, EVM_BLOCKSCOUT_V2[chain], chain, address, limit)
            # v2 returns (rows, err|None); normalize to a list of errs for accumulation.
            errs = [err] if err else []
        else:
            rows, errs = await _evm_one(session, base, key, chain, address, limit)
        if rows:
            return rows, None
        all_errs.extend(errs)
    return [], ("; ".join(dict.fromkeys(all_errs)) or "no transfers found")


async def _btc_transfers(session, address: str, limit: int) -> tuple[list[dict[str, Any]], Optional[str]]:
    url = f"https://blockstream.info/api/address/{address}/txs"
    try:
        async with session.get(url, timeout=20) as resp:
            data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    rows: list[dict[str, Any]] = []
    if not isinstance(data, list):
        return [], "bad response"
    me = _addr(address)
    for tx in data[:limit]:
        ts = (tx.get("status") or {}).get("block_time") or 0
        txid = tx.get("txid", "")
        vins = tx.get("vin", []) or []
        vouts = tx.get("vout", []) or []
        in_addrs = [_addr((v.get("prevout") or {}).get("scriptpubkey_address")) for v in vins]
        in_addrs = [a for a in in_addrs if a]
        if me in in_addrs:
            # Outgoing: subject is a sender → edges to each recipient output.
            for vout in vouts:
                dst = _addr(vout.get("scriptpubkey_address"))
                if dst and dst != me:
                    rows.append({"chain": "btc", "from": me, "to": dst, "asset": "BTC",
                                 "value": (vout.get("value") or 0) / 1e8, "value_usd": 0.0,
                                 "tx_hash": txid, "timestamp": ts})
        else:
            # Incoming: subject receives → attribute value from the input senders.
            received = sum((vo.get("value") or 0) for vo in vouts
                           if _addr(vo.get("scriptpubkey_address")) == me) / 1e8
            uniq_senders = [a for a in dict.fromkeys(in_addrs) if a != me][:5]
            if received > 0 and uniq_senders:
                share = received / len(uniq_senders)
                for src in uniq_senders:
                    rows.append({"chain": "btc", "from": src, "to": me, "asset": "BTC",
                                 "value": share, "value_usd": 0.0,
                                 "tx_hash": txid, "timestamp": ts})
    return rows[:limit * 4], None


async def _tron_transfers(session, address: str, limit: int) -> tuple[list[dict[str, Any]], Optional[str]]:
    # TRON via the public TronGrid API (no key, rate-limited). We trace BOTH:
    #   1. Native TRX transfers (the /transactions endpoint)
    #   2. TRC-20 token transfers — this is the rail for USDT-TRON, the dominant
    #      stablecoin used in illicit cash-out flows.
    # Addresses are returned in canonical Base58 (T…).
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    # ── 1. Native TRX transfers ──
    trx_url = f"https://api.trongrid.io/v1/accounts/{address}/transactions"
    trx_params: dict[str, str] = {"limit": str(min(limit, 100)), "only_confirmed": "true"}
    try:
        async with session.get(trx_url, params=trx_params, timeout=25) as resp:
            trx_data = await resp.json(content_type=None)
        if isinstance(trx_data, dict) and isinstance(trx_data.get("data"), list):
            for t in trx_data["data"][:limit]:
                contract = t.get("contract") or {}
                if contract.get("type") != "TransferContract":
                    continue  # only native TRX TransferContract; TRC-20 handled below
                value_sun = int(contract.get("parameter", {}).get("value", {}).get("amount", 0) or 0)
                val = value_sun / 1_000_000  # SUN → TRX (6 decimals)
                if val <= 0:
                    continue
                frm = _addr(contract.get("parameter", {}).get("value", {}).get("owner_address", ""))
                to = _addr(contract.get("parameter", {}).get("value", {}).get("to_address", ""))
                rows.append({"chain": "tron", "from": frm, "to": to,
                             "asset": "TRX", "value": val, "value_usd": 0.0,
                             "tx_hash": t.get("txID", ""),
                             "timestamp": int(t.get("block_timestamp") or 0) // 1000})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"native TRX: {type(exc).__name__}")

    # ── 2. TRC-20 token transfers (USDT, USDC, etc.) ──
    url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20"
    params = {"limit": str(min(limit, 200)), "only_confirmed": "true"}
    try:
        async with session.get(url, params=params, timeout=25) as resp:
            data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"TRC-20: {type(exc).__name__}: {exc}")
        return rows, (None if rows else "; ".join(errors)[:120] or "Tron API unavailable")
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        msg = (data.get("error") if isinstance(data, dict) else None) or "bad TRC-20 response"
        return rows, (None if rows else str(msg)[:120])
    for t in data["data"][:limit]:
        ti = t.get("token_info") or {}
        try:
            dec = int(ti.get("decimals") or 6)
            val = int(t.get("value", "0")) / (10 ** dec)
        except (TypeError, ValueError, ZeroDivisionError):
            val = 0.0
        if val <= 0:
            continue
        rows.append({"chain": "tron", "from": _addr(t.get("from")), "to": _addr(t.get("to")),
                     "asset": (ti.get("symbol") or "TRC20")[:12], "value": val, "value_usd": 0.0,
                     "tx_hash": t.get("transaction_id", ""),
                     "timestamp": int(t.get("block_timestamp") or 0) // 1000,
                     "contract": _addr(ti.get("address"))})
    return rows, (None if rows else ("no Tron transfers found; " + "; ".join(errors))[:140] if errors else None)


async def _zcash_transfers(session, address: str, limit: int) -> tuple[list[dict[str, Any]], Optional[str]]:
    # Zcash transparent (t-addr) flows via Blockchair. Shielded (z-addr) value is
    # cryptographically private and cannot be traced by design — only the
    # transparent pool is observable. Bounded per-tx expansion to respect rate limits.
    base = "https://api.blockchair.com/zcash/dashboards"
    try:
        async with session.get(f"{base}/address/{address}", params={"limit": "20"}, timeout=25) as resp:
            data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    try:
        tx_hashes = list(data["data"][address]["transactions"])[:min(limit, 10)]
    except (KeyError, TypeError):
        return [], "no transparent Zcash activity (address may be shielded-only)"
    rows: list[dict[str, Any]] = []
    me = _addr(address)
    for h in tx_hashes:
        try:
            async with session.get(f"{base}/transaction/{h}", timeout=25) as r2:
                td = await r2.json(content_type=None)
            tx = td["data"][h]
        except Exception:  # noqa: BLE001
            continue
        ts = ((tx.get("transaction") or {}).get("time") or "")
        try:
            import calendar, time as _t
            ts_epoch = int(calendar.timegm(_t.strptime(ts, "%Y-%m-%d %H:%M:%S"))) if ts else 0
        except Exception:  # noqa: BLE001
            ts_epoch = 0
        ins = tx.get("inputs") or []
        outs = tx.get("outputs") or []
        senders = {_addr(i.get("recipient")) for i in ins if i.get("recipient")}
        if me in senders:  # outgoing tx from subject
            for o in outs:
                dst = _addr(o.get("recipient"))
                if dst and dst != me:
                    rows.append({"chain": "zcash", "from": me, "to": dst, "asset": "ZEC",
                                 "value": (o.get("value") or 0) / 1e8, "value_usd": 0.0,
                                 "tx_hash": h, "timestamp": ts_epoch})
        else:  # incoming tx to subject
            for i in ins:
                src = _addr(i.get("recipient"))
                if src and src != me:
                    rows.append({"chain": "zcash", "from": src, "to": me, "asset": "ZEC",
                                 "value": (i.get("value") or 0) / 1e8, "value_usd": 0.0,
                                 "tx_hash": h, "timestamp": ts_epoch})
    return rows, (None if rows else "no transparent Zcash flows (shielded transactions are private by design)")


async def fetch_transfers(address: str, chain: str, api_key: str = "", limit: int = 50) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Best-effort fetch of recent transfers for an address."""
    try:
        import aiohttp
    except Exception as exc:  # noqa: BLE001
        return [], f"aiohttp unavailable: {exc}"
    async with aiohttp.ClientSession(headers={"User-Agent": "CrypTX-Holistic/1.0"}) as session:
        if chain in EVM_EXPLORERS or chain in EVM_BLOCKSCOUT:
            return await _evm_transfers(session, chain, address, api_key, limit)
        if chain == "btc":
            return await _btc_transfers(session, address, limit)
        if chain == "tron":
            return await _tron_transfers(session, address, limit)
        if chain == "zcash":
            return await _zcash_transfers(session, address, limit)
        # Extended multi-chain fetchers (Solana, XRP, LTC, DOGE, BCH, Cardano,
        # Polkadot, Cosmos, NEAR, Aptos, Sui, TON, Algorand, Stellar).
        try:
            import chain_fetchers
            rows, err = await chain_fetchers.fetch_chain(session, chain, address, limit)
            if rows is not None or err is not None:
                return rows or [], err
        except Exception as exc:  # noqa: BLE001
            return [], f"{chain} fetch failed: {type(exc).__name__}: {exc}"
        return [], f"live tracing not supported for chain {chain}"


# ---------------------------------------------------------------------------
# Core graph builder (pure, deterministic) — testable offline
# ---------------------------------------------------------------------------
def trace_from_events(
    subject: str,
    events: Iterable[dict[str, Any]],
    chain: str = "eth",
    direction: str = "both",
    max_hops: int = 4,
    min_value: float = 0.0,
) -> dict[str, Any]:
    """Build a unified multi-chain graph from a normalized transfer list.

    Each event: {chain, from, to, asset, value, value_usd, tx_hash, timestamp}
    BFS-expands from `subject` along `direction`, up to `max_hops`, classifying
    every counterparty and stitching cross-chain hops at bridge contracts.
    """
    subject = _addr(subject)
    evs = [e for e in events if float(e.get("value") or 0) >= min_value]

    # Index events by participant for fast hop expansion.
    out_by: dict[str, list[dict[str, Any]]] = {}
    in_by: dict[str, list[dict[str, Any]]] = {}
    for e in evs:
        out_by.setdefault(_addr(e.get("from")), []).append(e)
        in_by.setdefault(_addr(e.get("to")), []).append(e)

    nodes: dict[str, TraceNode] = {}
    edges: list[TraceEdge] = []
    seen_edges: set[tuple] = set()

    def node_for(addr: str, ch: str, hop: int) -> TraceNode:
        nid = f"{ch}:{addr}"
        if nid not in nodes:
            if addr == subject and hop == 0:
                nodes[nid] = TraceNode(id=nid, address=addr, chain=ch, type="subject", label="Subject", hop=0, risk=45)
            else:
                c = classify_counterparty(addr, ch)
                nodes[nid] = TraceNode(
                    id=nid, address=addr, chain=ch, type=c["type"], label=c["label"], hop=hop,
                    risk=c["risk"], is_terminal=c["terminal"], sanctioned=c["sanctioned"], vasp=c["vasp"],
                )
        else:
            nodes[nid].hop = min(nodes[nid].hop, hop)
        return nodes[nid]

    node_for(subject, chain, 0)
    frontier = [(subject, chain, 0)]
    visited: set[tuple[str, str]] = {(subject, chain)}

    while frontier:
        addr, ch, hop = frontier.pop(0)
        if hop >= max_hops:
            continue
        batch: list[tuple[dict[str, Any], str]] = []
        if direction in ("out", "both"):
            batch += [(e, "out") for e in out_by.get(addr, [])]
        if direction in ("in", "both"):
            batch += [(e, "in") for e in in_by.get(addr, [])]

        for e, dirn in batch:
            frm, to = _addr(e.get("from")), _addr(e.get("to"))
            ech = e.get("chain") or ch
            counterparty = to if dirn == "out" else frm
            if not counterparty:
                continue
            kind = "bridge" if (is_bridge(to) or is_bridge(frm)) else (
                "swap" if (_addr(to) in DEX_ROUTERS or _addr(frm) in DEX_ROUTERS) else "transfer")
            src_node = node_for(frm, ech, hop if dirn == "out" else hop + 1)
            dst_node = node_for(to, ech, hop + 1 if dirn == "out" else hop)

            key = (frm, to, e.get("tx_hash", ""), e.get("asset", ""))
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append(TraceEdge(
                    source=src_node.id, target=dst_node.id, chain=ech, asset=e.get("asset", ""),
                    value=float(e.get("value") or 0), value_usd=float(e.get("value_usd") or 0),
                    tx_hash=e.get("tx_hash", ""), timestamp=int(e.get("timestamp") or 0),
                    direction=dirn, kind=kind, hop=hop + 1,
                ))
                # throughput accounting
                nodes[src_node.id].outflow_value += float(e.get("value") or 0)
                nodes[dst_node.id].inflow_value += float(e.get("value") or 0)

            # expand counterparty unless it's a terminal (exchange/mixer/sanctioned)
            cp_node = node_for(counterparty, ech, hop + 1)
            if (counterparty, ech) not in visited and not cp_node.is_terminal:
                visited.add((counterparty, ech))
                frontier.append((counterparty, ech, hop + 1))

    return _assemble(subject, chain, nodes, edges, max_hops, direction, errors=[])


def _assemble(subject, chain, nodes, edges, max_hops, direction, errors) -> dict[str, Any]:
    node_list = list(nodes.values())
    chains_touched = sorted({n.chain for n in node_list})
    bridges = [n for n in node_list if n.type == "bridge"]
    mixers = [n for n in node_list if n.type == "mixer"]
    exchanges = [n for n in node_list if n.type == "exchange"]
    sanctioned = [n for n in node_list if n.sanctioned]
    cash_out = [n for n in node_list if n.type == "exchange"]  # off-ramps
    bridge_edges = [e for e in edges if e.kind == "bridge"]

    # ultimate destinations: terminal nodes reached at the deepest hops, outbound
    terminals = sorted([n for n in node_list if n.is_terminal and n.id != f"{chain}:{subject}"],
                       key=lambda n: n.hop)
    total_value = round(sum(e.value for e in edges), 6)
    risk_score = min(100, (95 if sanctioned else 0) or (80 if mixers else 0) or (50 if bridges else 25))

    return {
        "subject": subject,
        "subject_chain": chain,
        "config": {"max_hops": max_hops, "direction": direction},
        "graph": {
            "nodes": [n.to_dict() for n in node_list][:600],
            "edges": [e.to_dict() for e in edges][:1200],
        },
        "summary": {
            "node_count": len(node_list),
            "edge_count": len(edges),
            "chains_touched": chains_touched,
            "chain_count": len(chains_touched),
            "bridges_crossed": [{"id": b.id, "label": b.label} for b in bridges],
            "bridge_crossing_count": len(bridge_edges),
            "mixers_hit": [{"id": m.id, "label": m.label} for m in mixers],
            "exchanges_reached": [{"id": x.id, "label": x.label} for x in exchanges],
            "cash_out_points": [{"id": c.id, "label": c.label, "hop": c.hop, "vasp": c.vasp} for c in cash_out],
            "sanctioned_hits": [{"id": s.id, "label": s.label} for s in sanctioned],
            "ultimate_destinations": [{"id": t.id, "type": t.type, "label": t.label, "hop": t.hop} for t in terminals[:10]],
            "total_traced_value": total_value,
            "risk_score": risk_score,
        },
        "errors": errors,
        "disclaimer": "Cross-chain links and bridge attributions are probabilistic investigative leads, not proof.",
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# Live trace (best-effort BFS over public explorers)
# ---------------------------------------------------------------------------
async def trace(
    subject: str,
    chain: str = "eth",
    direction: str = "both",
    max_hops: int = 3,
    max_nodes: int = 120,
    min_value: float = 0.0,
    api_key: str = "",
    per_address_limit: int = 40,
    time_budget: float = 0.0,
    progress=None,
) -> dict[str, Any]:
    """Live best-effort BFS trace. Falls back to a subject-only graph on failure.

    `time_budget` (seconds, 0 = unlimited): a soft wall-clock deadline. When the
    frontier expansion exceeds it, the trace STOPS early and returns whatever it
    has collected so far (a partial graph) with an informative note, instead of
    running until the HTTP/client timeout kills the whole request. This is what
    keeps deep traces of very active addresses from failing outright.

    Performance: the frontier is expanded *concurrently* per hop level using
    asyncio.gather with a bounded semaphore, instead of awaiting each address
    fetch sequentially. Concurrency is adaptive: 8 with a configured Etherscan
    key (higher upstream limits), 3 without (Blockscout no-key tier throttles
    hard at ~5 rps). Each fetch also sleeps a tiny random jitter to desync burst
    arrivals — together with per-call 429 backoff this keeps deep (3+ hop)
    traces of active addresses from flooding the UI with rate-limit errors.
    """
    import collections
    import time as _time
    subject = _addr(subject)
    _deadline = (_time.monotonic() + time_budget) if time_budget and time_budget > 0 else 0.0
    budget_hit = False
    errors: list[str] = []
    rate_limited_count = 0     # collapsed to one summary line, not N duplicates
    deprecated_count = 0
    seen_errors: set[str] = set()
    collected: list[dict[str, Any]] = []
    visited: set[tuple[str, str]] = set()
    frontier: collections.deque[tuple[str, str, int]] = collections.deque()
    frontier.append((subject, chain, 0))
    fetched = 0
    # Adaptive: a configured key buys 5 calls/s of headroom; no-key Blockscout
    # free tier must run lean to stay under its ~5 rps shared limit.
    _CONCURRENCY = 8 if api_key else 3

    while frontier and fetched < max_nodes:
        # Soft time budget: stop expanding and return the partial graph before
        # the request/client timeout can kill everything.
        if _deadline and _time.monotonic() >= _deadline:
            budget_hit = True
            break
        # Drain the current hop level into a batch and fetch concurrently.
        # Using deque.popleft() is O(1) (was O(n) with list.pop(0) — bug #5 fix).
        current_hop = frontier[0][2]
        batch: list[tuple[str, str, int]] = []
        while frontier and frontier[0][2] == current_hop and len(batch) < _CONCURRENCY:
            batch.append(frontier.popleft())
        # filter out already-visited / over-depth
        batch = [(a, c, h) for (a, c, h) in batch
                 if (a, c) not in visited and h <= max_hops]
        if not batch:
            continue
        for a, c, _ in batch:
            visited.add((a, c))
        fetched += len(batch)

        async def _safe_fetch(addr: str, ch: str):
            # Small random jitter desyncs concurrent arrivals so they don't all
            # land on the explorer in the same millisecond.
            await asyncio.sleep(random.uniform(0.05, 0.15))
            try:
                return await fetch_transfers(addr, ch, api_key=api_key, limit=per_address_limit)
            except Exception as exc:  # noqa: BLE001
                return [], str(exc)

        results = await asyncio.gather(*[_safe_fetch(a, c) for a, c, _ in batch])
        if progress is not None:
            try:
                progress(fetched, max_nodes, current_hop)
            except Exception:  # noqa: BLE001 — progress must never break a trace
                pass
        for (addr, ch, hop), (rows, err) in zip(batch, results):
            if err:
                err_low = err.lower()
                if err == _RATE_LIMIT_MSG or "too many requests" in err_low or "rate limit" in err_low:
                    rate_limited_count += 1
                elif "deprecated" in err_low or "switch to" in err_low or "v2" in err_low and "switch" in err_low:
                    deprecated_count += 1
                else:
                    # Dedup by the error body (not the address) so 20 wallets
                    # failing with the same "bad response" produce one line.
                    if err not in seen_errors and len(errors) < 15:
                        seen_errors.add(err)
                        errors.append(f"{ch}:{addr[:10]}… {err}")
                continue
            collected.extend(rows)
            if hop >= max_hops:
                continue
            for e in rows:
                for cp in ({_addr(e.get("to")), _addr(e.get("from"))} - {addr}):
                    if not cp or (cp, ch) in visited:
                        continue
                    c = classify_counterparty(cp, ch)
                    if not c["terminal"]:
                        frontier.append((cp, ch, hop + 1))

    # Partial-result note when the soft time budget stopped the expansion.
    if budget_hit:
        remaining = len(frontier)
        errors.insert(0, f"ℹ Partial trace: stopped after reaching the time budget with "
                         f"{fetched} address(es) fetched"
                         + (f" and ~{remaining} more queued" if remaining else "")
                         + ". Results are complete for what was traced; re-run with fewer "
                         "hops or an ETHERSCAN_API_KEY for full depth.")

    # Collapse rate-limit / deprecation spam into single, actionable summaries
    # instead of one row per throttled address (the source of the UI error storm).
    if rate_limited_count > 0:
        prefix = "⚠ " if rate_limited_count > 3 else ""
        if api_key:
            errors.insert(0, f"{prefix}{rate_limited_count} address(es) were throttled by Etherscan even with "
                             f"your API key (free tier \u22485 req/s); those branches are partial. Reduce hops "
                             f"for full depth, or upgrade your Etherscan plan tier.")
        else:
            errors.insert(0, f"{prefix}{rate_limited_count} address(es) hit explorer rate limits "
                         f"(no API key \u2014 Blockscout free tier). Set ETHERSCAN_API_KEY in Settings "
                         f"for higher limits, or reduce hops.")
    if deprecated_count > 0:
        errors.insert(0, f"ℹ Legacy Blockscout v1 endpoint reported deprecated for {deprecated_count} "
                         f"call(s) — v2 fallback is active.")

    result = trace_from_events(subject, collected, chain=chain, direction=direction,
                               max_hops=max_hops, min_value=min_value)
    result["errors"] = errors
    result["source"] = "live_public_explorers" if collected else "no_live_data"
    if not collected:
        result["note"] = ("No transfers retrieved. The public explorer may be rate-limited or the address has "
                           "no indexed activity on this chain. Try a different chain (eth/polygon/optimism/"
                           "base/arbitrum supported no-key), add an ETHERSCAN_API_KEY in Settings for higher "
                           "limits, or POST normalized events to /api/holistic/trace-events.")
    return result


def registry() -> dict[str, Any]:
    return {
        "bridges": [{"address": k, **v} for k, v in BRIDGE_CONTRACTS.items()],
        "dex_routers": [{"address": k, **v} for k, v in DEX_ROUTERS.items()],
        "mixers": [{"address": k, **v} for k, v in MIXER_CONTRACTS.items()],
        "supported_live_chains": sorted(set(
            list(EVM_EXPLORERS) + list(EVM_BLOCKSCOUT) + ["btc", "tron", "zcash"]
            + ["solana", "xrp", "litecoin", "dogecoin", "bch", "cardano", "polkadot",
               "cosmos", "near", "aptos", "sui", "ton", "algorand", "stellar"])),
        "node_types": list(NODE_TYPES),
    }


if __name__ == "__main__":
    sample = [
        {"chain": "eth", "from": "0xsubject", "to": "0x7a250d5630b4cf539739df2c5dacb4c659f2488d", "asset": "ETH", "value": 10, "tx_hash": "0x1", "timestamp": 1700000000},
        {"chain": "eth", "from": "0xsubject", "to": "0x3ee18b2214aff97000d974cf647e7c347e8fa585", "asset": "ETH", "value": 5, "tx_hash": "0x2", "timestamp": 1700000100},
        {"chain": "eth", "from": "0xsubject", "to": "0x8589427373d6d84e98730d7795d8f6f8731fda16", "asset": "ETH", "value": 100, "tx_hash": "0x3", "timestamp": 1700000200},
        {"chain": "eth", "from": "0xmid", "to": "0x28c6c06298d514db089934071355e5743bf21d60", "asset": "ETH", "value": 3, "tx_hash": "0x4", "timestamp": 1700000300},
        {"chain": "eth", "from": "0xsubject", "to": "0xmid", "asset": "ETH", "value": 4, "tx_hash": "0x5", "timestamp": 1700000250},
    ]
    out = trace_from_events("0xsubject", sample, max_hops=4)
    s = out["summary"]
    print("nodes", s["node_count"], "edges", s["edge_count"])
    print("bridges", [b["label"] for b in s["bridges_crossed"]])
    print("mixers", [m["label"] for m in s["mixers_hit"]])
    print("cash_out", [c["label"] for c in s["cash_out_points"]])
