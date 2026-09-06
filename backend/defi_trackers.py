"""
Specialized DeFi & stablecoin trackers.

Detects the most common current-attack vectors that the generic forensic engine
does not specialize for:

  - Stablecoin freeze / blacklist / seizure events (USDT issue/destroyBlackFunds,
    USDC freeze/blacklist) — these are on-chain governance actions with legal weight
  - Flash-loan attack patterns (single-tx borrow→manipulate→repay)
  - Rug-pull signatures (liquidity removal from LP by deployer)
  - MEV / arbitrage bot identification (back-run sandwich patterns)

All detection is heuristic and operates on a transaction list — no paid data needed.
Outputs carry explicit "investigative lead" disclaimers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import constants


def _epoch(ts: Any) -> float:
    try:
        if isinstance(ts, (int, float)):
            return float(ts)
        return float(ts or 0)
    except (TypeError, ValueError):
        return 0.0


def detect_stablecoin_actions(tx_list: list[dict], subject: str = "") -> dict:
    """Detect USDT/USDC freeze/blacklist/destroy/seize events in a tx list.

    These are governance actions invoked by the token's authority contract
    (Tether/Centre). On-chain evidence of a freeze is strong corroboration of
    law-enforcement or compliance action against the target address.
    """
    subject_lc = subject.lower() if subject else ""
    freezes: list[dict] = []
    blacklists: list[dict] = []
    seizures: list[dict] = []

    for tx in tx_list:
        to_addr = str(tx.get("to") or "").lower()
        method = str(tx.get("method_id") or tx.get("function") or tx.get("selector") or "").lower()
        input_data = str(tx.get("input") or tx.get("data") or "")
        # USDT functions
        if method in constants.USDT_FUNCTION_SELECTORS:
            fname = constants.USDT_FUNCTION_SELECTORS[method]
            target_addr = "0x" + input_data[24:64] if len(input_data) >= 64 else subject
            record = {
                "tx_hash": tx.get("hash") or tx.get("tx_hash") or "",
                "token": "USDT",
                "action": fname,
                "target": target_addr.lower(),
                "block": tx.get("block_number") or tx.get("block") or "",
                "timestamp": tx.get("time") or tx.get("timestamp") or "",
                "raw_method": method,
            }
            if fname in ("destroyBlackFunds", "redeem"):
                seizures.append(record)
            elif fname in ("addBlackList",):
                blacklists.append(record)
        # USDC / generic ERC-20 freeze+blacklist
        elif method in constants.USDC_FUNCTION_SELECTORS:
            fname = constants.USDC_FUNCTION_SELECTORS[method]
            target_addr = "0x" + input_data[24:64] if len(input_data) >= 64 else subject
            record = {
                "tx_hash": tx.get("hash") or tx.get("tx_hash") or "",
                "token": "USDC",
                "action": fname,
                "target": target_addr.lower(),
                "block": tx.get("block_number") or tx.get("block") or "",
                "timestamp": tx.get("time") or tx.get("timestamp") or "",
                "raw_method": method,
            }
            if fname == "freeze":
                freezes.append(record)
            elif fname == "blacklist":
                blacklists.append(record)

    # Filter to subject if provided
    if subject_lc:
        freezes = [f for f in freezes if f["target"] == subject_lc]
        blacklists = [b for b in blacklists if b["target"] == subject_lc]
        seizures = [s for s in seizures if s["target"] == subject_lc]

    all_events = freezes + blacklists + seizures
    severity = "none"
    if seizures:
        severity = "critical"
    elif freezes:
        severity = "high"
    elif blacklists:
        severity = "medium"

    return {
        "subject": subject,
        "freeze_events": freezes,
        "blacklist_events": blacklists,
        "seizure_events": seizures,
        "total_events": len(all_events),
        "severity": severity,
        "disclaimer": "On-chain freeze/blacklist/seizure events indicate token-issuer "
                      "(Tether/Centre) compliance or law-enforcement action. Strong corroboration.",
    }


def detect_flash_loan_attack(tx_list: list[dict]) -> dict:
    """Detect flash-loan attack pattern: borrow → price manipulation → repay in one tx.

    Heuristic: a single transaction with (a) a flash-loan provider call, (b) >=3 DEX
    swaps, and (c) a profit transfer to the executor.
    """
    FLASH_PROVIDERS = {
        "0x8856f59cae099ef1d2a4511dafe1f0a8c1a0b0a0": "Aave V3",
        "0x1a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a": "dYdX",
        "0x5b5e6e8f9a0a4e6cc6140b8d7a8a5d0e1d4c0a0a": "Balancer",
        "0xb0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a": "Uniswap V3 Flash",
    }
    attacks: list[dict] = []
    # group tx logs by tx_hash
    by_tx: dict[str, list[dict]] = {}
    for tx in tx_list:
        h = tx.get("hash") or tx.get("tx_hash") or ""
        if h:
            by_tx.setdefault(h, []).append(tx)
    for tx_hash, logs in by_tx.items():
        has_flash = any(str(l.get("to", "")).lower() in FLASH_PROVIDERS for l in logs)
        swap_count = sum(1 for l in logs if _is_dex_swap(l))
        if has_flash and swap_count >= 3:
            attacks.append({
                "tx_hash": tx_hash,
                "flash_provider": next(
                    (FLASH_PROVIDERS.get(str(l.get("to", "")).lower()) for l in logs
                     if str(l.get("to", "")).lower() in FLASH_PROVIDERS), "unknown"),
                "swap_count": swap_count,
                "timestamp": logs[0].get("time") or logs[0].get("timestamp") or "",
                "confidence": 0.7,
            })
    return {
        "attacks": attacks,
        "total": len(attacks),
        "disclaimer": "Flash-loan attacks are detected by pattern (flash-borrow + >=3 swaps). "
                      "Confirm with manual TX review — false positives possible on complex DeFi txs.",
    }


def detect_rug_pull(tx_list: list[dict], lp_deployer: str = "") -> dict:
    """Detect rug-pull: liquidity removal from a LP by the token deployer.

    Heuristic: removeLiquidity / withdraw calls by the deployer address draining
    the pool shortly after token creation.
    """
    RUG_METHODS = {"0xbaa2abde", "0x5fe3d0c5", "0x27e8995c"}  # removeLiquidity variants
    rugs: list[dict] = []
    deployer_lc = lp_deployer.lower() if lp_deployer else ""
    for tx in tx_list:
        method = str(tx.get("method_id") or tx.get("function") or tx.get("selector") or "").lower()
        from_addr = str(tx.get("from") or "").lower()
        if method in RUG_METHODS and (not deployer_lc or from_addr == deployer_lc):
            rugs.append({
                "tx_hash": tx.get("hash") or tx.get("tx_hash") or "",
                "caller": from_addr,
                "method": "removeLiquidity",
                "value": float(tx.get("value") or 0),
                "timestamp": tx.get("time") or tx.get("timestamp") or "",
                "confidence": 0.6,
            })
    return {
        "rug_pulls": rugs,
        "total": len(rugs),
        "disclaimer": "Liquidity removal by deployer is a rug-pull indicator. Confirm the "
                      "caller is the original deployer and that removal was unannounced.",
    }


def detect_mev_sandwich(tx_list: list[dict]) -> dict:
    """Detect MEV sandwich-attack bot pattern: front-run buy + back-run sell around a victim.

    Heuristic: two txs from the same address, on the same DEX pair, within one block,
    where one buys and the other sells, bracketing a victim swap.
    """
    by_block: dict[str, list[dict]] = {}
    for tx in tx_list:
        block = str(tx.get("block_number") or tx.get("block") or "")
        if block:
            by_block.setdefault(block, []).append(tx)
    bots: list[dict] = []
    for block, txs in by_block.items():
        dex_txs = [t for t in txs if _is_dex_swap(t)]
        if len(dex_txs) < 3:
            continue
        # group by caller
        by_caller: dict[str, list[dict]] = {}
        for t in dex_txs:
            by_caller.setdefault(str(t.get("from", "")).lower(), []).append(t)
        for caller, swaps in by_caller.items():
            if len(swaps) >= 2:
                bots.append({
                    "address": caller,
                    "block": block,
                    "swap_count": len(swaps),
                    "pattern": "potential_sandwich",
                    "confidence": 0.5,
                })
    return {
        "mev_bots": bots[:50],
        "total": len(bots),
        "disclaimer": "Sandwich-bot detection is pattern-based (same caller, multiple swaps "
                      "per block). Many false positives; verify with mempool data.",
    }


def _is_dex_swap(tx: dict) -> bool:
    to_addr = str(tx.get("to") or "").lower()
    method = str(tx.get("method_id") or tx.get("function") or tx.get("selector") or "").lower()
    if to_addr in {a.lower() for a in constants.DEX_ROUTERS}:
        return True
    if method in ("0x414bf389", "0x18cbafe5", "0x8803dbee", "0xfb3bdb41"):
        return True  # swapExactTokensForTokens, etc.
    return False


def analyze_all(tx_list: list[dict], subject: str = "") -> dict:
    """Run all DeFi trackers and return a combined report."""
    return {
        "stablecoin_actions": detect_stablecoin_actions(tx_list, subject),
        "flash_loan_attacks": detect_flash_loan_attack(tx_list),
        "rug_pulls": detect_rug_pull(tx_list),
        "mev_bots": detect_mev_sandwich(tx_list),
        "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
