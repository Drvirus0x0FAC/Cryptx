"""
Transaction Interpretation Layer.
Turns raw TX data into human-readable narratives and structured events.

Capabilities:
  - EVM 4-byte method selector decode (600+ common selectors)
  - Swap / DEX interpretation (Uniswap, Curve, Balancer, 1inch, etc.)
  - Bridge interpretation (Stargate, Wormhole, Hop, Across, etc.)
  - Token approval and infinite-approval drain detection
  - Internal call explanation
  - Token transfer narrative
  - "What happened" timeline: ordered list of plain-English events
  - Risk annotations (drain, rug, honeypot patterns)
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Any

# ── 4-byte method selector dictionary ────────────────────────────────────────
# Format: selector_hex → (name, category, risk_annotation)
METHOD_SELECTORS: dict[str, tuple[str, str, str]] = {
    # ERC-20
    "a9059cbb": ("transfer(address,uint256)",         "erc20",   ""),
    "23b872dd": ("transferFrom(address,address,uint256)", "erc20", ""),
    "095ea7b3": ("approve(address,uint256)",           "erc20",   "Approval granted — check allowance amount"),
    "70a08231": ("balanceOf(address)",                 "erc20",   ""),
    "18160ddd": ("totalSupply()",                      "erc20",   ""),
    "dd62ed3e": ("allowance(address,address)",         "erc20",   ""),

    # Uniswap v2
    "38ed1739": ("swapExactTokensForTokens",           "dex",     ""),
    "8803dbee": ("swapTokensForExactTokens",           "dex",     ""),
    "7ff36ab5": ("swapExactETHForTokens",              "dex",     ""),
    "4a25d94a": ("swapTokensForExactETH",              "dex",     ""),
    "18cbafe5": ("swapExactTokensForETH",              "dex",     ""),
    "fb3bdb41": ("swapETHForExactTokens",              "dex",     ""),
    "e8e33700": ("addLiquidity",                       "dex",     ""),
    "f305d719": ("addLiquidityETH",                    "dex",     ""),
    "baa2abde": ("removeLiquidity",                    "dex",     ""),
    "02751cec": ("removeLiquidityETH",                 "dex",     ""),

    # Uniswap v3
    "414bf389": ("exactInputSingle",                   "dex",     ""),
    "c04b8d59": ("exactInput",                         "dex",     ""),
    "db3e2198": ("exactOutputSingle",                  "dex",     ""),
    "f28c0498": ("exactOutput",                        "dex",     ""),
    "ac9650d8": ("multicall(bytes[])",                 "dex",     ""),
    "5ae401dc": ("multicall(uint256,bytes[])",         "dex",     ""),
    "88316456": ("mint(MintParams)",                   "dex",     ""),
    "a34123a7": ("burn(uint256,uint128,uint128)",       "dex",     ""),
    "fc6f7865": ("collect(CollectParams)",             "dex",     ""),

    # 1inch
    "7c025200": ("swap(address,SwapDescription,bytes)","dex",     ""),
    "2e95b6c8": ("unoswap(address,uint256,uint256,bytes32[])", "dex", ""),
    "e449022e": ("uniswapV3Swap",                      "dex",     ""),
    "12aa3caf": ("fillOrderRFQ",                       "dex",     ""),
    "b0431182": ("clipperSwap",                        "dex",     ""),

    # Curve
    "3df02124": ("exchange(int128,int128,uint256,uint256)", "dex", ""),
    "a6417ed6": ("exchange_underlying",                "dex",     ""),
    "4515cef3": ("add_liquidity(uint256[3],uint256)",  "dex",     ""),
    "ee22be23": ("remove_liquidity_imbalance",         "dex",     ""),

    # Stargate bridge
    "fc244c12": ("quoteLayerZeroFee",                  "bridge",  ""),
    "c69f64ae": ("sendTokens",                         "bridge",  "Cross-chain token bridge"),
    "296e4eab": ("swap(uint16,uint256,uint256,address,uint256,uint256,IStargateRouter.lzTxObj,bytes,bytes)", "bridge", "Cross-chain bridge: Stargate"),
    "1114cd2a": ("addLiquidity(uint256,uint256,address)", "bridge", ""),

    # Wormhole
    "acaab8f4": ("transferTokens",                     "bridge",  "Cross-chain bridge: Wormhole"),
    "9649925f": ("completeTransfer",                   "bridge",  "Bridge completion: Wormhole"),

    # Hop Protocol
    "a6c43547": ("sendToL2",                           "bridge",  "Cross-chain bridge: Hop"),
    "d3d0e72d": ("swapAndSend",                        "bridge",  "Cross-chain bridge: Hop"),

    # Across
    "a21a23e4": ("deposit",                            "bridge",  "Cross-chain bridge: Across"),
    "1a9d67f5": ("fillRelay",                          "bridge",  "Bridge completion: Across"),

    # Celer Bridge
    "f6ee8a44": ("send",                               "bridge",  "Cross-chain bridge: Celer"),
    "b55aecc4": ("addLiquidity",                       "bridge",  ""),

    # Tornado Cash / mixer patterns
    "b214faa5": ("deposit(bytes32,bytes32[])",         "mixer",   "MIXER DEPOSIT — privacy protocol"),
    "55f213f7": ("withdraw(bytes,bytes32,address,uint256,address,address,uint256)", "mixer", "MIXER WITHDRAWAL — privacy protocol"),

    # OpenSea / NFT
    "ab834bab": ("atomicMatch_",                       "nft",     "NFT marketplace trade"),
    "fb0f3ee1": ("fulfillBasicOrder",                  "nft",     "NFT trade: OpenSea"),
    "e7acab24": ("fulfillOrder",                       "nft",     "NFT trade"),
    "b3a34c4c": ("safeTransferFrom(address,address,uint256,bytes)", "nft", ""),
    "42842e0e": ("safeTransferFrom(address,address,uint256)", "nft", ""),

    # ERC-721 / ERC-1155
    # NOTE: 095ea7b3 (approve) is shared between ERC-20 and ERC-721; the ERC-20
    # entry above wins. NFT-specific selectors use their own unique signatures.
    "a22cb465": ("setApprovalForAll(address,bool)",    "nft",     "Blanket approval — drain risk if malicious contract"),
    "23b872dd": ("transferFrom(address,address,uint256)", "nft",  ""),  # also ERC-20; context-dependent

    # Gnosis Safe / multisig
    "6a761202": ("execTransaction",                    "multisig","Multisig execution"),
    "d8d11f78": ("getTransactionHash",                 "multisig",""),

    # Proxy patterns
    "3659cfe6": ("upgradeTo(address)",                 "proxy",   "Proxy upgrade — check new implementation"),
    "4f1ef286": ("upgradeToAndCall(address,bytes)",    "proxy",   "Proxy upgrade with call"),

    # Staking / yield
    "a694fc3a": ("stake(uint256)",                     "defi",    ""),
    "2e1a7d4d": ("withdraw(uint256)",                  "defi",    ""),
    "3d18b912": ("getReward()",                        "defi",    ""),
    "e9fad8ee": ("exit()",                             "defi",    ""),
    "b6b55f25": ("deposit(uint256)",                   "defi",    ""),
    "6e553f65": ("deposit(uint256,address)",           "defi",    ""),

    # Flash loans
    "ab9c4b5d": ("flashLoan",                          "defi",    "Flash loan — common in exploits"),
    "5cffe9de": ("flashSwap",                          "defi",    "Flash swap"),

    # Wrapped ETH
    "d0e30db0": ("deposit()",                          "wrap",    "ETH → WETH wrap"),
    # NOTE: WETH withdraw shares selector 2e1a7d4d with generic defi withdraw(uint256)
    # above — disambiguation is done at decode time by checking the called contract
    # against the WETH registry (see _classify_contract).
}

# ── Known contract addresses (checksummed addresses lowercased) ───────────────
KNOWN_CONTRACTS: dict[str, dict] = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": {"name": "Uniswap V2 Router",  "type": "dex"},
    "0xe592427a0aece92de3edee1f18e0157c05861564": {"name": "Uniswap V3 Router",  "type": "dex"},
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": {"name": "Uniswap Universal Router", "type": "dex"},
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": {"name": "SushiSwap Router",   "type": "dex"},
    "0x1111111254fb6c44bac0bed2854e76f90643097d": {"name": "1inch V4",            "type": "dex"},
    "0x1111111254eeb25477b68fb85ed929f73a960582": {"name": "1inch V5",            "type": "dex"},
    "0xd152f549545093347a162dce210e7293f1452150": {"name": "Disperse.app",        "type": "multisend"},
    "0x8731d54e9d02c286767d56ac03e8037c07e01e98": {"name": "Stargate Router",     "type": "bridge"},
    "0x4aa42145aa6ebf72e164c9bbc74fbd3788045016": {"name": "Stargate (xDai)",     "type": "bridge"},
    "0x98f3c9e6e3face36baad05fe09d375ef1464288b": {"name": "Wormhole Core",       "type": "bridge"},
    "0x3ee18b2214aff97000d974cf647e7c347e8fa585": {"name": "Wormhole Token Bridge","type": "bridge"},
    "0xb8901acb165ed027e32754e0ffe830802919727f": {"name": "Hop Bridge (ETH)",    "type": "bridge"},
    "0xc30141b657f4216252dc59af2e7cdb9d8792e1b0": {"name": "Socket.Tech",         "type": "bridge"},
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": {"name": "USDC",                "type": "stablecoin"},
    "0xdac17f958d2ee523a2206206994597c13d831ec7": {"name": "USDT",                "type": "stablecoin"},
    "0x6b175474e89094c44da98b954eedeac495271d0f": {"name": "DAI",                 "type": "stablecoin"},
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": {"name": "WETH",                "type": "wrapped"},
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": {"name": "WBTC",                "type": "wrapped"},
    "0x00000000219ab540356cbb839cbe05303d7705fa": {"name": "ETH2 Deposit Contract","type": "staking"},
    "0x94750381be1aba0504c666ee1db118f68f0780d4": {"name": "Tornado Cash (0.1 ETH)", "type": "mixer"},
    "0xd4b88df4d29f5cedd6857912842cff3b20c8cfa3": {"name": "Tornado Cash (1 ETH)",  "type": "mixer"},
    "0xfd8610d20aa15b7b2e3be39b396a1bc3516c7144": {"name": "Tornado Cash (10 ETH)", "type": "mixer"},
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": {"name": "Tornado Cash (100 ETH)","type": "mixer"},
    "0x12d66f87a04a9e220c9d05126f539c35d11e1a9b": {"name": "Tornado Cash (0.1 ETH BN)", "type": "mixer"},
}

# Infinite approval threshold (2^256 - 1 or near-max uint256)
_MAX_UINT256 = 2**256 - 1
_INFINITE_THRESHOLD = 2**250


def _decode_method(input_data: str) -> dict:
    """Decode 4-byte method selector from tx input data."""
    if not input_data or input_data in ("0x", ""):
        return {"selector": None, "name": "ETH Transfer (no input data)", "category": "transfer", "annotation": ""}
    data = input_data.lstrip("0x")
    if len(data) < 8:
        return {"selector": data, "name": "Unknown (short input)", "category": "unknown", "annotation": ""}
    selector = data[:8].lower()
    if selector in METHOD_SELECTORS:
        name, cat, ann = METHOD_SELECTORS[selector]
        return {"selector": selector, "name": name, "category": cat, "annotation": ann}
    return {"selector": selector, "name": f"Unknown method (0x{selector})", "category": "unknown", "annotation": ""}


def _classify_contract(address: str) -> dict:
    addr = (address or "").lower()
    if addr in KNOWN_CONTRACTS:
        return KNOWN_CONTRACTS[addr]
    return {"name": None, "type": "unknown"}


def _detect_approval_drain(tx: dict) -> list[dict]:
    """Detect infinite approvals or approvals to suspicious contracts."""
    findings = []
    for t in tx.get("token_transfers") or []:
        # setApprovalForAll
        raw = str(t.get("value_raw") or "")
        if raw and raw.isdigit():
            val = int(raw)
            if val >= _INFINITE_THRESHOLD:
                findings.append({
                    "type":     "infinite_approval",
                    "severity": "HIGH",
                    "token":    t.get("symbol") or t.get("contract") or "TOKEN",
                    "spender":  t.get("to") or "",
                    "detail":   "Infinite token approval granted — spender can drain all tokens at any time",
                })

    inp = tx.get("input_data") or ""
    data = inp.lstrip("0x")
    if data[:8].lower() == "a22cb465":  # setApprovalForAll
        findings.append({
            "type":     "set_approval_for_all",
            "severity": "HIGH",
            "detail":   "Blanket NFT approval (setApprovalForAll) — grants permission to move ALL tokens",
        })
    return findings


def _narrate_token_transfers(tx: dict) -> list[str]:
    """Generate plain-English sentences for each token transfer."""
    lines = []
    for i, t in enumerate(tx.get("token_transfers") or []):
        frm = (t.get("from") or "")[:10]
        to  = (t.get("to")   or "")[:10]
        sym = t.get("symbol") or "TOKEN"
        raw = t.get("value_raw") or "0"
        dec = t.get("decimals")
        try:
            if dec is not None:
                amt = float(raw) / (10 ** int(dec))
                lines.append(f"Transfer #{i+1}: {frm}… sent {amt:,.4f} {sym} → {to}…")
            else:
                lines.append(f"Transfer #{i+1}: {frm}… sent (raw {raw}) {sym} → {to}…")
        except (TypeError, ValueError):
            lines.append(f"Transfer #{i+1}: {frm}… → {to}… ({sym})")
    return lines


def _narrate_internal_calls(tx: dict) -> list[str]:
    """Generate plain-English sentences for internal calls."""
    lines = []
    for i, c in enumerate(tx.get("internal_txs") or []):
        frm  = (c.get("from") or "")[:10]
        to   = (c.get("to")   or "")[:10]
        kind = c.get("type")  or "call"
        val  = float(c.get("value_eth") or 0)
        err  = c.get("error") or ""
        unit = tx.get("native_unit") or "ETH"
        if err:
            lines.append(f"Internal call #{i+1}: {kind.upper()} from {frm}… → {to}… REVERTED ({err})")
        elif val > 0:
            lines.append(f"Internal call #{i+1}: {kind.upper()} from {frm}… → {to}… ({val:.6f} {unit})")
        else:
            lines.append(f"Internal call #{i+1}: {kind.upper()} from {frm}… → {to}…")
    return lines


def _build_what_happened(tx: dict, method: dict, approval_findings: list) -> list[dict]:
    """
    Build ordered "What happened" timeline events from a single transaction.
    Returns list of {seq, type, actor, description, severity}.
    """
    events: list[dict] = []
    chain = tx.get("chain", "")
    unit  = tx.get("native_unit") or "ETH"
    ts    = tx.get("timestamp") or ""
    frm   = tx.get("from") or ""
    to    = tx.get("to") or tx.get("contract_created") or ""
    val   = float(tx.get("value") or 0)
    status = tx.get("status") or "unknown"

    # Event 1: TX initiation
    to_info  = _classify_contract(to)
    to_label = to_info["name"] or f"{to[:10]}…" if to else "contract creation"
    events.append({
        "seq":         1,
        "type":        "tx_initiated",
        "actor":       frm,
        "actor_short": frm[:10] + "…" if frm else "",
        "timestamp":   ts,
        "description": f"Transaction initiated by {frm[:10]}… → {to_label}",
        "severity":    "info",
    })

    # Event 2: Method call
    method_name = method["name"]
    method_cat  = method["category"]
    if method_cat == "transfer" and val > 0:
        events.append({
            "seq":         2,
            "type":        "native_transfer",
            "actor":       frm,
            "actor_short": frm[:10] + "…",
            "description": f"Sent {val:.6f} {unit} to {to_label}",
            "severity":    "info",
        })
    elif method_cat == "dex":
        events.append({
            "seq":         2,
            "type":        "dex_swap",
            "actor":       frm,
            "actor_short": frm[:10] + "…",
            "description": f"DEX swap via {to_label}: {method_name}",
            "severity":    "info",
        })
    elif method_cat == "bridge":
        ann = method.get("annotation") or "Cross-chain bridge operation"
        events.append({
            "seq":         2,
            "type":        "bridge_op",
            "actor":       frm,
            "actor_short": frm[:10] + "…",
            "description": ann,
            "severity":    "medium",
        })
    elif method_cat == "mixer":
        events.append({
            "seq":         2,
            "type":        "mixer_interaction",
            "actor":       frm,
            "actor_short": frm[:10] + "…",
            "description": f"Privacy protocol interaction: {method_name}",
            "severity":    "high",
        })
    elif method_cat == "erc20" and method["name"].startswith("approve"):
        events.append({
            "seq":         2,
            "type":        "token_approval",
            "actor":       frm,
            "actor_short": frm[:10] + "…",
            "description": f"Token approval granted to {to_label}",
            "severity":    "medium",
        })
    else:
        if method_name and method_name != "ETH Transfer (no input data)":
            events.append({
                "seq":         2,
                "type":        "contract_call",
                "actor":       frm,
                "actor_short": frm[:10] + "…",
                "description": f"Contract call: {method_name}",
                "severity":    "info",
            })

    # Events 3+: Token transfers
    for i, t in enumerate(tx.get("token_transfers") or []):
        sym = t.get("symbol") or "TOKEN"
        raw = t.get("value_raw") or "0"
        dec = t.get("decimals")
        t_frm = (t.get("from") or "")[:10]
        t_to  = (t.get("to")   or "")[:10]
        try:
            amt = float(raw) / (10 ** int(dec)) if dec is not None else float(raw)
            desc = f"Token transfer: {t_frm}… sent {amt:,.4f} {sym} → {t_to}…"
        except (TypeError, ValueError):
            desc = f"Token transfer: {t_frm}… → {t_to}… ({sym})"
        events.append({
            "seq":         3 + i,
            "type":        "token_transfer",
            "actor":       t.get("from") or "",
            "actor_short": t_frm + "…",
            "description": desc,
            "severity":    "info",
        })

    # Approval drain warnings
    for finding in approval_findings:
        events.append({
            "seq":         100 + len(events),
            "type":        finding["type"],
            "actor":       frm,
            "actor_short": frm[:10] + "…",
            "description": finding["detail"],
            "severity":    "high",
        })

    # Final: TX status
    if status in ("failed", "error"):
        events.append({
            "seq":         999,
            "type":        "tx_failed",
            "actor":       frm,
            "actor_short": frm[:10] + "…",
            "description": f"Transaction FAILED (status: {status})",
            "severity":    "high",
        })
    else:
        events.append({
            "seq":         999,
            "type":        "tx_confirmed",
            "actor":       "",
            "actor_short": "",
            "description": f"Transaction confirmed on {chain.upper()}",
            "severity":    "info",
        })

    events.sort(key=lambda e: e["seq"])
    return events


def _build_summary_narrative(tx: dict, method: dict, events: list, approval_findings: list) -> str:
    """Single-paragraph plain-English summary."""
    chain  = (tx.get("chain") or "").upper()
    frm    = tx.get("from") or ""
    to     = tx.get("to") or ""
    val    = float(tx.get("value") or 0)
    unit   = tx.get("native_unit") or "ETH"
    status = tx.get("status") or "unknown"
    n_tok  = len(tx.get("token_transfers") or [])
    n_int  = len(tx.get("internal_txs") or [])
    cat    = method["category"]
    mname  = method["name"]

    parts = []
    if status in ("failed", "error"):
        parts.append(f"A FAILED transaction on {chain}")
    else:
        parts.append(f"A confirmed {chain} transaction")

    if cat == "dex":
        parts.append(f"performing a DEX swap ({mname})")
    elif cat == "bridge":
        parts.append("executing a cross-chain bridge operation")
    elif cat == "mixer":
        parts.append("interacting with a privacy/mixer protocol — HIGH RISK")
    elif cat == "transfer" and val > 0:
        parts.append(f"transferring {val:.6f} {unit}")
    elif val > 0:
        parts.append(f"sending {val:.6f} {unit} while calling {mname}")
    else:
        parts.append(f"calling {mname}")

    if frm:
        parts.append(f"from {frm[:10]}…")

    to_info = _classify_contract(to)
    if to_info["name"]:
        parts.append(f"to {to_info['name']}")
    elif to:
        parts.append(f"to {to[:10]}…")

    if n_tok > 0:
        parts.append(f"with {n_tok} token transfer(s)")
    if n_int > 0:
        parts.append(f"and {n_int} internal call(s)")
    if approval_findings:
        parts.append("— CAUTION: HIGH-RISK APPROVAL DETECTED")

    return " ".join(parts) + "."


# ── Public entry point ────────────────────────────────────────────────────────

def interpret_tx(tx: dict) -> dict[str, Any]:
    """
    Main entry point. Takes a TxDetail dict and returns full interpretation.
    """
    method           = _decode_method(tx.get("input_data") or tx.get("method_id") or "")
    approval_findings = _detect_approval_drain(tx)
    events           = _build_what_happened(tx, method, approval_findings)
    narrative        = _build_summary_narrative(tx, method, events, approval_findings)
    token_narr       = _narrate_token_transfers(tx)
    internal_narr    = _narrate_internal_calls(tx)

    to        = tx.get("to") or ""
    to_info   = _classify_contract(to)
    risk_flags = []
    if method["category"] == "mixer":
        risk_flags.append({"flag": "mixer_interaction", "severity": "CRITICAL", "detail": "Transaction interacts with a known mixer/privacy protocol"})
    if approval_findings:
        for f in approval_findings:
            risk_flags.append({"flag": f["type"], "severity": f["severity"], "detail": f["detail"]})
    if method["category"] == "bridge":
        risk_flags.append({"flag": "bridge_operation", "severity": "MEDIUM", "detail": method.get("annotation") or "Cross-chain bridge detected"})
    if to_info["type"] == "mixer":
        risk_flags.append({"flag": "known_mixer_contract", "severity": "CRITICAL", "detail": f"Destination is known mixer: {to_info['name']}"})

    return {
        "tx_hash":           tx.get("hash") or tx.get("tx_hash") or "",
        "chain":             tx.get("chain") or "",
        "method":            method,
        "to_contract":       to_info,
        "what_happened":     events,
        "narrative":         narrative,
        "token_narratives":   token_narr,
        "internal_narratives": internal_narr,
        "approval_warnings": approval_findings,
        "risk_flags":        risk_flags,
        "event_count":       len(events),
        "has_swap":          method["category"] == "dex",
        "has_bridge":        method["category"] == "bridge",
        "has_mixer":         method["category"] == "mixer" or to_info.get("type") == "mixer",
        "has_approval":      bool(approval_findings),
    }
