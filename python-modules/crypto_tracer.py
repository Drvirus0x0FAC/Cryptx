#!/usr/bin/env python3
"""
crypto_tracer.py — Multi-hop fund flow tracer for the Stage 08 bot.

Traces the movement of funds N hops forward or backward from a seed address,
building a chain-of-custody tree used for investigation reports.

Modes:
  linear  — follow the single largest outflow/inflow at each hop (peel-chain style)
  wide    — fan out to top 3 counterparties per hop (cluster tracing)

Supported chains (from/to address extraction):
  ETH / MATIC / BSC / ARB / OP / BASE — full from+to+value in every tx
  TRX                                  — full from+to+value in every tx
  BTC                                  — limited (our format lacks per-tx counterparties;
                                          use BlockCypher token for best results)
  SOL                                  — limited (RPC returns signatures only, no addresses)

Usage from bot:
  from crypto_tracer import trace_funds, format_trace_html

  result = await trace_funds(address, hops=3, mode="linear")
  html   = format_trace_html(result)

Env vars (inherited from crypto_osint):
  All env vars used by crypto_osint.lookup_crypto_address() apply here too.
"""

import asyncio
import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import zipfile

from crypto_osint import lookup_crypto_address, detect_chain

log = logging.getLogger("crypto_tracer")

# ── Safety limits ─────────────────────────────────────────────────────────────
MAX_HOPS         = 5    # hard ceiling on hops argument
MAX_WIDE_BRANCH  = 3    # counterparties per hop in wide mode
MAX_TOTAL_NODES  = 20   # absolute cap on total API lookups per trace
_TRACE_LOOKUP_MEMO: Dict[str, Dict[str, Any]] = {}


# =============================================================================
# Counterparty extraction
# =============================================================================

def _extract_counterparties(intel: Dict[str, Any],
                             seed_address: str,
                             direction: str = "out") -> List[Dict]:
    """
    Pull unique counterparty addresses out of an intel dict.

    Args:
        intel:        Result dict from lookup_crypto_address()
        seed_address: The address we already know — exclude it from results
        direction:    'out' = follow outflows (sends), 'in' = follow inflows,
                      'both' = all unique counterparties

    Returns a list of dicts sorted by amount descending:
        [{"address": str, "amount": float, "token": str,
          "time": str, "hash": str}, ...]
    """
    seen: Set[str]        = {seed_address.lower()}
    candidates: List[Dict] = []
    chain = intel.get("chain", "")

    def _add(counterparty: str, amount: float, token: str,
             time: str, tx_hash: str) -> None:
        cp = (counterparty or "").strip()
        if not cp or cp.lower() in seen:
            return
        if not detect_chain(cp):
            return   # skip non-address strings
        seen.add(cp.lower())
        candidates.append({
            "address": cp,
            "amount":  float(amount or 0),
            "token":   token or "",
            "time":    time or "",
            "hash":    tx_hash or "",
        })

    # ── Native coin transactions ───────────────────────────────────────────────
    for tx in (intel.get("recent_txs") or []):
        tx_dir = (tx.get("direction") or "").upper()
        if direction == "out" and tx_dir != "OUT":
            continue
        if direction == "in" and tx_dir != "IN":
            continue

        tx_hash = tx.get("hash") or tx.get("txid") or ""
        ts      = tx.get("time", "")

        if chain in ("ETH", "MATIC", "BSC", "ARB", "OP", "BASE"):
            cp     = tx.get("to") if tx_dir == "OUT" else tx.get("from")
            amount = tx.get("value_eth", 0.0)
            _add(cp, amount, chain, ts, tx_hash)

        elif chain == "TRX":
            cp     = tx.get("to") if tx_dir == "OUT" else tx.get("from")
            amount = tx.get("value_trx", 0.0)
            _add(cp, amount, "TRX", ts, tx_hash)

        elif chain == "BTC":
            # Our BTC format does not include explicit counterparty addresses.
            # BlockCypher full-tx mode (BLOCKCYPHER_TOKEN set) would give them,
            # but we don't store them in our compact tx_list.
            # BTC tracing is limited — the trace will stall after hop 0.
            pass

        elif chain == "SOL":
            # RPC returns signatures only; no from/to without per-tx detail fetch.
            # SOL tracing is limited — the trace will stall after hop 0.
            pass

    # ── Token transfer transactions (ETH ERC20) ───────────────────────────────
    for tx in (intel.get("token_txs") or []):
        tx_dir = (tx.get("direction") or "").upper()
        if direction == "out" and tx_dir != "OUT":
            continue
        if direction == "in" and tx_dir != "IN":
            continue

        cp      = tx.get("to") if tx_dir == "OUT" else tx.get("from")
        amount  = tx.get("value", 0.0)
        token   = tx.get("token", "ERC20")
        ts      = tx.get("time", "")
        tx_hash = tx.get("hash", "")
        _add(cp, amount, token, ts, tx_hash)

    # Sort by value descending so largest flows surface first
    candidates.sort(key=lambda x: x["amount"], reverse=True)
    return candidates


# =============================================================================
# Trace node
# =============================================================================

class TraceNode:
    """Single address vertex in the trace graph."""
    __slots__ = (
        "address", "hop", "parent_address",
        "via_hash", "via_amount", "via_token",
        "intel", "counterparties", "children",
    )

    def __init__(self, address: str, hop: int,
                 parent_address: str = "",
                 via_hash:       str = "",
                 via_amount:   float = 0.0,
                 via_token:      str = ""):
        self.address        = address
        self.hop            = hop
        self.parent_address = parent_address
        self.via_hash       = via_hash
        self.via_amount     = via_amount
        self.via_token      = via_token
        self.intel:          Optional[Dict] = None
        self.counterparties: List[Dict]     = []
        self.children:       List["TraceNode"] = []


# =============================================================================
# Main tracer
# =============================================================================

async def trace_funds(
    address:   str,
    hops:      int = 3,
    mode:      str = "linear",
    direction: str = "out",
) -> Dict[str, Any]:
    """
    Trace fund flow from a seed address.

    Args:
        address:   Seed crypto address
        hops:      Depth of trace — how many hops to follow (1–5)
        mode:      'linear'  — follow the single largest flow at each hop
                   'wide'    — fan out to top 3 counterparties per hop
        direction: 'out' — follow money being sent
                   'in'  — follow money being received

    Returns:
        {
          "seed":           str,
          "hops_requested": int,
          "mode":           str,
          "direction":      str,
          "nodes":          [serialized node dicts, ordered by discovery],
          "total_looked_up":int,
          "warnings":       [str],
          "error":          str | None,
        }
    """
    hops = max(1, min(int(hops), MAX_HOPS))
    seen_addresses: Set[str]  = set()
    all_nodes: List[TraceNode] = []
    warnings:  List[str]      = []

    result: Dict[str, Any] = {
        "seed":           address,
        "hops_requested": hops,
        "mode":           mode,
        "direction":      direction,
        "nodes":          [],
        "total_looked_up": 0,
        "warnings":       warnings,
        "error":          None,
    }

    # ── Node processor ─────────────────────────────────────────────────────
    async def _process(node: TraceNode) -> None:
        if node.address.lower() in seen_addresses:
            return
        if result["total_looked_up"] >= MAX_TOTAL_NODES:
            if "Node cap reached — trace truncated" not in warnings:
                warnings.append(
                    f"Node cap ({MAX_TOTAL_NODES}) reached — trace truncated. "
                    "Reduce hops or use linear mode for deeper traces."
                )
            return

        seen_addresses.add(node.address.lower())
        result["total_looked_up"] += 1

        try:
            memo_key = node.address.lower()
            if memo_key in _TRACE_LOOKUP_MEMO:
                intel = _TRACE_LOOKUP_MEMO[memo_key]
            else:
                intel = await lookup_crypto_address(node.address)
                _TRACE_LOOKUP_MEMO[memo_key] = intel
        except Exception as exc:
            log.warning("Tracer lookup failed for %s: %s", node.address, exc)
            intel = {"address": node.address, "error": str(exc)}

        node.intel = intel

        if not intel.get("error") or intel.get("balance") is not None:
            node.counterparties = _extract_counterparties(
                intel, node.address, direction
            )
            if not node.counterparties and node.hop == 0:
                chain = intel.get("chain", "?")
                if chain in ("BTC", "SOL"):
                    warnings.append(
                        f"{chain} tracing is limited: our compact tx format does not "
                        "store per-hop counterparty addresses. "
                        "For BTC, set BLOCKCYPHER_TOKEN for richer data."
                    )

        all_nodes.append(node)

    # ── Seed node ──────────────────────────────────────────────────────────
    seed_node = TraceNode(address=address, hop=0)
    await _process(seed_node)

    # ── BFS expansion ──────────────────────────────────────────────────────
    current_frontier: List[TraceNode] = [seed_node]

    for hop_idx in range(1, hops + 1):
        next_frontier: List[TraceNode] = []
        tasks: List[Any] = []

        max_branch = 1 if mode == "linear" else MAX_WIDE_BRANCH

        candidates: List[Tuple[float, TraceNode, Dict[str, Any]]] = []
        for parent in current_frontier:
            for cp in (parent.counterparties or []):
                candidates.append((float(cp.get("amount") or 0), parent, cp))
        candidates.sort(key=lambda x: x[0], reverse=True)
        if mode == "linear":
            candidates = candidates[:1]
        else:
            candidates = candidates[:max_branch * max(1, len(current_frontier))]

        for _, parent, cp in candidates:
            if cp["address"].lower() in seen_addresses:
                continue
            if result["total_looked_up"] >= MAX_TOTAL_NODES:
                break

            child = TraceNode(
                address       = cp["address"],
                hop           = hop_idx,
                parent_address= parent.address,
                via_hash      = cp.get("hash", ""),
                via_amount    = cp.get("amount", 0.0),
                via_token     = cp.get("token", ""),
            )
            parent.children.append(child)
            next_frontier.append(child)
            tasks.append(_process(child))

        if tasks:
            await asyncio.gather(*tasks)

        # Only keep nodes that were actually looked up
        current_frontier = [n for n in next_frontier
                            if n.intel is not None]
        if not current_frontier:
            break

    result["nodes"] = [_serialize_node(n) for n in all_nodes]
    return result


# =============================================================================
# Serialization
# =============================================================================

def _serialize_node(node: TraceNode) -> Dict[str, Any]:
    intel     = node.intel or {}
    sanctions = intel.get("sanctions") or {}
    arkham    = intel.get("arkham")    or {}
    mixer_hits = intel.get("mixer_hits") or []
    scam      = intel.get("scam_reports") or {}
    hop_swap  = intel.get("chain_hop_swap") or {}

    return {
        "address":      node.address,
        "hop":          node.hop,
        "parent":       node.parent_address,
        "via_hash":     node.via_hash,
        "via_amount":   node.via_amount,
        "via_token":    node.via_token,
        # on-chain data
        "chain":        intel.get("chain", "?"),
        "balance":      intel.get("balance", 0),
        "balance_unit": intel.get("balance_unit", ""),
        "portfolio_usd": intel.get("portfolio_usd"),
        "tx_count":     intel.get("tx_count", 0),
        "native_tx_count": intel.get("native_tx_count"),
        "token_tx_count":  intel.get("token_tx_count"),
        "first_seen":   intel.get("first_seen", ""),
        "last_seen":    intel.get("last_seen", ""),
        # risk signals
        "sanctioned":   sanctions.get("sanctioned", False),
        "sanctions_source": sanctions.get("source", ""),
        "sanction_identifications": sanctions.get("identifications", []),
        "sanction_ids": [
            i.get("name", "") for i in sanctions.get("identifications", [])[:3]
        ],
        "arkham_entity":arkham.get("name") or arkham.get("entity_name") or "",
        "arkham_type":  arkham.get("entity_type") or "",
        "arkham_label": arkham.get("label") or "",
        "arkham":       arkham,
        "mixer_hits":   len(mixer_hits),
        "mixer_names":  [h.get("mixer_name", "") for h in mixer_hits[:3]],
        "mixer_details": mixer_hits,
        "bridge_hits":  hop_swap.get("bridge_count", 0),
        "swap_hits":    hop_swap.get("swap_count", 0),
        "chain_hop_swap": hop_swap,
        "scam_reports": scam.get("count", 0) if isinstance(scam, dict) else 0,
        "scam_details": scam if isinstance(scam, dict) else {},
        "tokens":       (intel.get("tokens") or []),
        "recent_txs":   (intel.get("recent_txs") or []),
        "token_txs":    (intel.get("token_txs") or []),
        # next hops
        "top_counterparties": [
            {
                "address": cp["address"],
                "amount":  cp["amount"],
                "token":   cp.get("token", ""),
            }
            for cp in (node.counterparties or [])
        ],
        "error":    intel.get("error", ""),
        "explorer": intel.get("explorer", ""),
        "source":   intel.get("source", ""),
        "fallback_warning": intel.get("fallback_warning", ""),
    }


def trace_result_from_intel(
    intel: Dict[str, Any],
    *,
    mode: str = "seed",
    direction: str = "out",
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build a one-node trace result from an already fetched wallet intel dict.

    This is used as a graph/export fallback when multi-hop tracing returns no
    nodes, so investigators still get all primary-wallet intelligence instead
    of an empty graph shell.
    """
    address = intel.get("address") or ""
    seed_node = TraceNode(address=address, hop=0)
    seed_node.intel = intel
    seed_node.counterparties = _extract_counterparties(intel, address, direction)
    notes = list(warnings or [])
    if not seed_node.counterparties:
        notes.append(
            "Graph fallback used: no trace expansion nodes were available, "
            "so this artifact shows the seed wallet intelligence only."
        )
    return {
        "seed": address,
        "hops_requested": 0,
        "mode": mode,
        "direction": direction,
        "nodes": [_serialize_node(seed_node)] if address else [],
        "total_looked_up": 1 if address else 0,
        "warnings": notes,
        "error": None,
    }


# =============================================================================
# Telegram HTML formatter
# =============================================================================

def _e(s: Any) -> str:
    """Telegram HTML-escape helper."""
    return escape(str(s))


def _risk_profile(node: Dict[str, Any]) -> Dict[str, Any]:
    """Condense node risk signals for graph rendering."""
    labels = []
    level = "clean"
    color = "#5fd18b"
    score = 0

    if node.get("error"):
        labels.append("Lookup error")
        level = "error"
        color = "#7f8ea3"
        score = max(score, 20)
    if node.get("arkham_entity"):
        labels.append("Known entity")
        if level == "clean":
            level = "entity"
            color = "#6db8ff"
        score = max(score, 25)
    if node.get("scam_reports", 0):
        labels.append(f"Scam reports: {node.get('scam_reports')}")
        level = "scam"
        color = "#ff9f43"
        score = max(score, min(80, 45 + int(node.get("scam_reports") or 0) * 5))
    if node.get("mixer_hits", 0):
        names = ", ".join(node.get("mixer_names") or []) or "Mixer exposure"
        labels.append(names)
        level = "mixer"
        color = "#ff6b6b"
        score = max(score, min(90, 65 + int(node.get("mixer_hits") or 0) * 5))
    bridge_swap_count = int(node.get("bridge_hits") or 0) + int(node.get("swap_hits") or 0)
    if bridge_swap_count:
        labels.append(f"Bridge/swap infrastructure: {bridge_swap_count}")
        if level in ("clean", "entity"):
            level = "bridge_swap"
            color = "#60a5fa"
        score = max(score, min(75, 45 + bridge_swap_count * 5))
    if node.get("sanctioned"):
        sanc = ", ".join(node.get("sanction_ids") or []) or "Sanctioned"
        labels.append(sanc)
        level = "sanctioned"
        color = "#ff335f"
        score = 100

    return {
        "level": level,
        "color": color,
        "score": score,
        "labels": labels,
        "is_suspicious": level in {"sanctioned", "mixer", "scam", "error", "bridge_swap"},
    }


def _tx_value(tx: Dict[str, Any], default_token: str = "") -> Dict[str, str]:
    """Normalize different chain tx shapes into display fields."""
    token = str(tx.get("token") or default_token or "")
    value = ""
    for key in ("value", "value_eth", "value_trx", "delta_btc", "amount"):
        if tx.get(key) not in (None, ""):
            value = str(tx.get(key))
            if not token:
                token = {
                    "value_eth": "ETH",
                    "value_trx": "TRX",
                    "delta_btc": "BTC",
                }.get(key, "")
            break
    return {"value": value, "token": token}


def _node_transactions(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return all fetched native and token tx evidence for a serialized node."""
    out: List[Dict[str, Any]] = []
    default_token = node.get("balance_unit") or node.get("chain") or ""
    seen = set()
    for source, txs in (
        ("native", node.get("recent_txs") or []),
        ("token", node.get("token_txs") or []),
    ):
        for tx in txs:
            if not isinstance(tx, dict):
                continue
            tx_hash = tx.get("hash") or tx.get("txid") or tx.get("transactionHash") or ""
            dedupe_key = (source, tx_hash, tx.get("time"), tx.get("value"), tx.get("value_eth"))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            amount = _tx_value(tx, default_token)
            out.append({
                "source": source,
                "hash": tx_hash,
                "time": tx.get("time") or "",
                "direction": tx.get("direction") or "",
                "from": tx.get("from") or "",
                "to": tx.get("to") or "",
                "value": amount["value"],
                "token": amount["token"],
                "type": tx.get("type") or tx.get("contractType") or "",
                "confirmed": tx.get("confirmed"),
                "error": tx.get("error") or tx.get("is_error") or False,
                "raw": tx,
            })
    return out


def _float_value(value: Any) -> float:
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return 0.0


def _is_round_amount(value: Any) -> bool:
    n = _float_value(value)
    if n <= 0:
        return False
    for denom in (1, 5, 10, 25, 50, 100, 500, 1000, 0.1, 0.5, 0.01, 0.05):
        ratio = n / denom
        if ratio >= 1 and abs(ratio - round(ratio)) < 0.0001:
            return True
    return False


def _counterparty_for_tx(wallet: str, tx: Dict[str, Any]) -> str:
    direction = (tx.get("direction") or "").upper()
    if direction == "OUT":
        return tx.get("to") or ""
    if direction == "IN":
        return tx.get("from") or ""
    wallet_l = wallet.lower()
    if (tx.get("from") or "").lower() == wallet_l:
        return tx.get("to") or ""
    if (tx.get("to") or "").lower() == wallet_l:
        return tx.get("from") or ""
    return tx.get("to") or tx.get("from") or ""


def _aggregate_counterparties(wallet: str, txs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for tx in txs:
        cp = _counterparty_for_tx(wallet, tx)
        if not cp:
            continue
        direction = (tx.get("direction") or "").upper()
        amount = _float_value(tx.get("value"))
        row = grouped.setdefault(cp, {
            "address": cp,
            "tx_count": 0,
            "sent": 0.0,
            "received": 0.0,
            "tokens": set(),
            "first_seen": "",
            "last_seen": "",
            "hashes": [],
        })
        row["tx_count"] += 1
        if direction == "OUT":
            row["sent"] += amount
        elif direction == "IN":
            row["received"] += amount
        token = tx.get("token")
        if token:
            row["tokens"].add(str(token))
        ts = tx.get("time") or ""
        if ts:
            if not row["first_seen"] or ts < row["first_seen"]:
                row["first_seen"] = ts
            if not row["last_seen"] or ts > row["last_seen"]:
                row["last_seen"] = ts
        if tx.get("hash"):
            row["hashes"].append(tx["hash"])

    out = []
    for row in grouped.values():
        row["tokens"] = sorted(row["tokens"])
        row["hashes"] = row["hashes"][:25]
        row["total_volume"] = round(row["sent"] + row["received"], 10)
        row["sent"] = round(row["sent"], 10)
        row["received"] = round(row["received"], 10)
        out.append(row)
    out.sort(key=lambda r: (r["total_volume"], r["tx_count"]), reverse=True)
    return out


def _detect_node_patterns(node: Dict[str, Any], txs: List[Dict[str, Any]],
                          counterparties: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    patterns: List[Dict[str, Any]] = []
    out_cps = {
        _counterparty_for_tx(node.get("address", ""), tx)
        for tx in txs if (tx.get("direction") or "").upper() == "OUT"
    }
    in_cps = {
        _counterparty_for_tx(node.get("address", ""), tx)
        for tx in txs if (tx.get("direction") or "").upper() == "IN"
    }
    out_cps.discard("")
    in_cps.discard("")

    if len(out_cps) >= 5:
        patterns.append({
            "scope": "node",
            "node_id": node.get("id"),
            "address": node.get("address"),
            "pattern": "fan_out_distribution",
            "severity": "HIGH" if len(out_cps) >= 10 else "MEDIUM",
            "confidence": "medium",
            "evidence": f"{len(out_cps)} unique outbound counterparties in fetched transactions.",
        })
    if len(in_cps) >= 5:
        patterns.append({
            "scope": "node",
            "node_id": node.get("id"),
            "address": node.get("address"),
            "pattern": "consolidation_fan_in",
            "severity": "MEDIUM",
            "confidence": "medium",
            "evidence": f"{len(in_cps)} unique inbound counterparties in fetched transactions.",
        })

    hour_bins: Dict[str, int] = {}
    for tx in txs:
        ts = str(tx.get("time") or "")
        if len(ts) >= 13:
            key = ts[:13]
            hour_bins[key] = hour_bins.get(key, 0) + 1
    burst = max(hour_bins.values()) if hour_bins else 0
    if burst >= 5:
        patterns.append({
            "scope": "node",
            "node_id": node.get("id"),
            "address": node.get("address"),
            "pattern": "rapid_transaction_burst",
            "severity": "MEDIUM",
            "confidence": "medium",
            "evidence": f"{burst} fetched transactions occurred within the same hour bucket.",
        })

    round_count = sum(1 for tx in txs if _is_round_amount(tx.get("value")))
    if round_count >= 3:
        patterns.append({
            "scope": "node",
            "node_id": node.get("id"),
            "address": node.get("address"),
            "pattern": "round_amount_structuring",
            "severity": "MEDIUM",
            "confidence": "low",
            "evidence": f"{round_count} fetched transactions use round or denomination-like amounts.",
        })

    if node.get("risk_level") in ("sanctioned", "mixer", "scam"):
        patterns.append({
            "scope": "node",
            "node_id": node.get("id"),
            "address": node.get("address"),
            "pattern": f"{node.get('risk_level')}_exposure",
            "severity": "CRITICAL" if node.get("risk_level") == "sanctioned" else "HIGH",
            "confidence": "high",
            "evidence": "; ".join(node.get("risk_labels") or []) or "Risk signal captured on node.",
        })

    try:
        balance = float((node.get("raw") or {}).get("balance") or node.get("balance") or 0)
    except (TypeError, ValueError):
        balance = 0.0
    if txs and len(in_cps) and len(out_cps) and balance < 0.01:
        patterns.append({
            "scope": "node",
            "node_id": node.get("id"),
            "address": node.get("address"),
            "pattern": "possible_pass_through_wallet",
            "severity": "MEDIUM",
            "confidence": "low",
            "evidence": "Wallet has inbound and outbound activity in fetched data with near-zero current native balance.",
        })
    return patterns


def _build_timeline(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for node in nodes:
        for tx in node.get("transactions") or []:
            rows.append({
                "node_id": node.get("id"),
                "wallet": node.get("address"),
                "hop": node.get("hop"),
                "chain": node.get("chain"),
                "risk_level": node.get("risk_level"),
                "risk_score": node.get("risk_score"),
                "time": tx.get("time") or "",
                "source": tx.get("source") or "",
                "direction": tx.get("direction") or "",
                "hash": tx.get("hash") or "",
                "from": tx.get("from") or "",
                "to": tx.get("to") or "",
                "value": tx.get("value") or "",
                "token": tx.get("token") or "",
                "type": tx.get("type") or "",
            })
    rows.sort(key=lambda r: r.get("time") or "", reverse=True)
    return rows


def _detect_graph_patterns(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    patterns: List[Dict[str, Any]] = []
    for node in nodes:
        patterns.extend(_detect_node_patterns(
            node,
            node.get("transactions") or [],
            node.get("counterparties") or [],
        ))
    if len(edges) >= 2 and all(len([e for e in edges if e.get("source") == n.get("id")]) <= 1 for n in nodes):
        patterns.append({
            "scope": "graph",
            "node_id": "",
            "address": "",
            "pattern": "linear_peel_chain_candidate",
            "severity": "MEDIUM",
            "confidence": "low",
            "evidence": f"Trace contains {len(edges)} edge(s) with mostly linear expansion.",
        })
    risky = [n for n in nodes if n.get("risk_level") in ("sanctioned", "mixer", "scam")]
    if risky:
        patterns.append({
            "scope": "graph",
            "node_id": "",
            "address": "",
            "pattern": "high_risk_node_present",
            "severity": "HIGH",
            "confidence": "high",
            "evidence": f"{len(risky)} high-risk node(s) appear in the trace graph.",
        })
    return patterns


def build_trace_graph_model(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a deterministic graph model from trace_funds() output.

    The model is intentionally presentation-friendly so it can be rendered as
    SVG/HTML, exported to JSON, or reused by future UI clients.
    """
    nodes = result.get("nodes") or []
    node_ids: Dict[str, str] = {}
    graph_nodes: List[Dict[str, Any]] = []
    graph_edges: List[Dict[str, Any]] = []

    for idx, node in enumerate(nodes):
        addr = node.get("address") or f"unknown-{idx}"
        node_id = f"n{idx}"
        node_ids[addr] = node_id
        risk = _risk_profile(node)
        tx_evidence = _node_transactions(node)
        counterparties = _aggregate_counterparties(addr, tx_evidence)
        graph_nodes.append({
            "id": node_id,
            "address": addr,
            "short_address": _short_addr(addr, 8),
            "hop": int(node.get("hop") or 0),
            "chain": node.get("chain") or "?",
            "balance": node.get("balance", 0),
            "balance_unit": node.get("balance_unit") or "",
            "tx_count": node.get("tx_count", 0),
            "entity": node.get("arkham_entity") or node.get("arkham_label") or "",
            "risk_level": risk["level"],
            "risk_color": risk["color"],
            "risk_score": risk["score"],
            "risk_labels": risk["labels"],
            "is_suspicious": risk["is_suspicious"],
            "transactions": tx_evidence,
            "transaction_count_fetched": len(tx_evidence),
            "counterparties": counterparties,
            "raw": node,
            "explorer": node.get("explorer") or "",
            "source": node.get("source") or "",
        })

    for node in nodes:
        parent = node.get("parent") or ""
        addr = node.get("address") or ""
        if not parent or parent not in node_ids or addr not in node_ids:
            continue
        graph_edges.append({
            "source": node_ids[parent],
            "target": node_ids[addr],
            "amount": node.get("via_amount") or 0,
            "token": node.get("via_token") or "",
            "hash": node.get("via_hash") or "",
            "source_address": parent,
            "target_address": addr,
        })

    suspicious = [n for n in graph_nodes if n["is_suspicious"]]
    timeline = _build_timeline(graph_nodes)
    patterns = _detect_graph_patterns(graph_nodes, graph_edges)
    by_level: Dict[str, int] = {}
    for n in graph_nodes:
        by_level[n["risk_level"]] = by_level.get(n["risk_level"], 0) + 1

    return {
        "seed": result.get("seed") or "",
        "mode": result.get("mode") or "linear",
        "direction": result.get("direction") or "out",
        "hops_requested": result.get("hops_requested", 0),
        "nodes": graph_nodes,
        "edges": graph_edges,
        "timeline": timeline,
        "patterns": patterns,
        "warnings": result.get("warnings") or [],
        "stats": {
            "nodes": len(graph_nodes),
            "edges": len(graph_edges),
            "suspicious_nodes": len(suspicious),
            "timeline_events": len(timeline),
            "patterns": len(patterns),
            "risk_levels": by_level,
        },
    }


def _short_addr(address: str, chars: int = 6) -> str:
    if not address:
        return ""
    if len(address) <= chars * 2 + 3:
        return address
    return f"{address[:chars]}...{address[-chars:]}"


def _fmt_amount(amount: Any, token: str = "") -> str:
    try:
        n = float(amount)
    except (TypeError, ValueError):
        n = 0.0
    if not n:
        return ""
    if n >= 1000:
        text = f"{n:,.2f}"
    elif n >= 1:
        text = f"{n:.4f}".rstrip("0").rstrip(".")
    else:
        text = f"{n:.8f}".rstrip("0").rstrip(".")
    return f"{text} {token}".strip()


def format_trace_graph_html(result: Dict[str, Any], *, standalone: bool = False) -> str:
    """
    Render trace_funds() output as an interactive HTML/SVG investigation graph.
    Designed for compliance reports and standalone Telegram document exports.
    """
    graph = build_trace_graph_model(result)
    nodes = graph["nodes"]
    edges = graph["edges"]
    if not nodes:
        message = (
            "No graph nodes were available in the trace result. "
            "Run the lookup again after verifying the chain API response, "
            "or use the seed-wallet fallback from the crypto lookup flow."
        )
        graph_json = json.dumps(graph, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
        empty_html = f'''
  <section class="section ai-section trace-graph-section">
    <h2>Interactive Wallet Intelligence Graph</h2>
    <div class="graph-summary">
      <div><span>Wallets</span><strong>0</strong></div>
      <div><span>Transfers</span><strong>0</strong></div>
      <div><span>Flagged</span><strong>0</strong></div>
    </div>
    <p class="trace-notes"><strong>No graph data:</strong> {escape(message)}</p>
    <details class="raw-graph-data" open>
      <summary>Raw Empty Trace JSON</summary>
      <pre>{escape(json.dumps(result, ensure_ascii=False, indent=2))}</pre>
    </details>
    <script type="application/json" id="traceGraphData">{graph_json}</script>
  </section>'''
        if standalone:
            generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wallet Activity Graph</title>
{trace_graph_css()}
</head>
<body class="trace-graph-standalone">
<main class="graph-page">
  <header class="graph-header">
    <h1>Wallet Activity Graph</h1>
    <p>Seed: <code>{escape(str(graph.get("seed") or result.get("seed") or ""))}</code></p>
    <p>Generated: {escape(generated_at)}</p>
  </header>
  {empty_html}
</main>
</body>
</html>'''
        return empty_html

    hop_groups: Dict[int, List[Dict[str, Any]]] = {}
    for node in nodes:
        hop_groups.setdefault(node["hop"], []).append(node)

    col_w = 360
    row_h = 310
    margin_x = 52
    margin_y = 54
    max_hop = max(hop_groups.keys() or [0])
    max_rows = max(len(v) for v in hop_groups.values())
    width = max(760, margin_x * 2 + (max_hop + 1) * col_w)
    height = max(420, margin_y * 2 + max_rows * row_h)

    positions: Dict[str, Dict[str, float]] = {}
    for hop, hop_nodes in hop_groups.items():
        group_height = (len(hop_nodes) - 1) * row_h
        start_y = (height - group_height) / 2
        for idx, node in enumerate(hop_nodes):
            positions[node["id"]] = {
                "x": margin_x + hop * col_w,
                "y": start_y + idx * row_h,
            }

    edge_svg = []
    for edge in edges:
        src = positions.get(edge["source"])
        dst = positions.get(edge["target"])
        if not src or not dst:
            continue
        x1 = src["x"] + 300
        y1 = src["y"]
        x2 = dst["x"] - 8
        y2 = dst["y"]
        mid = (x1 + x2) / 2
        label = _fmt_amount(edge.get("amount"), edge.get("token", ""))
        label_x = (x1 + x2) / 2
        label_y = (y1 + y2) / 2 - 8
        edge_svg.append(
            f'<path class="edge" d="M{x1:.1f},{y1:.1f} C{mid:.1f},{y1:.1f} {mid:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" />'
            f'<polygon class="arrow" points="{x2:.1f},{y2:.1f} {x2-9:.1f},{y2-5:.1f} {x2-9:.1f},{y2+5:.1f}" />'
        )
        if label:
            edge_svg.append(
                f'<text class="edge-label" x="{label_x:.1f}" y="{label_y:.1f}">{escape(label)}</text>'
            )

    node_svg = []
    for node in nodes:
        pos = positions[node["id"]]
        x = pos["x"]
        y = pos["y"] - 130
        risk_text = ", ".join(node["risk_labels"][:2]) or node["risk_level"].title()
        entity = node["entity"] or f"{node['tx_count']} txs"
        balance = _fmt_amount(node["balance"], node["balance_unit"]) or "balance unknown"
        seed_class = " seed" if node["hop"] == 0 else ""
        tx_preview = []
        for tx in (node.get("transactions") or [])[:5]:
            left = f"{tx.get('direction') or '-'} {tx.get('source') or ''}".strip()
            val = _fmt_amount(tx.get("value"), tx.get("token", "")) or "value ?"
            h = _short_addr(str(tx.get("hash") or ""), 8)
            tx_preview.append(f"{left} | {val} | {h}")
        if len(node.get("transactions") or []) > 5:
            tx_preview.append(f"+ {len(node['transactions']) - 5} more txs in inspector")
        tx_html = "".join(f"<div class=\"node-tx-row\">{escape(row)}</div>" for row in tx_preview)
        if not tx_html:
            tx_html = "<div class=\"node-tx-row muted-row\">No fetched TX rows</div>"
        node_svg.append(f'''
      <g class="node{seed_class}" tabindex="0" data-node-id="{escape(node["id"])}" data-hop="{node["hop"]}" data-risk="{escape(node["risk_level"])}">
        <title>{escape(node["address"])} | {escape(risk_text)}</title>
        <rect x="{x:.1f}" y="{y:.1f}" width="300" height="260" rx="8" style="--risk:{node["risk_color"]}" />
        <circle cx="{x + 16:.1f}" cy="{y + 20:.1f}" r="7" fill="{node["risk_color"]}" />
        <text class="node-hop" x="{x + 30:.1f}" y="{y + 24:.1f}">Hop {node["hop"]} · {escape(node["chain"])}</text>
        <text class="node-address" x="{x + 14:.1f}" y="{y + 48:.1f}">{escape(node["short_address"])}</text>
        <text class="node-meta" x="{x + 14:.1f}" y="{y + 68:.1f}">{escape(entity[:28])}</text>
        <text class="node-balance" x="{x + 14:.1f}" y="{y + 82:.1f}">{escape(balance[:30])}</text>
        <foreignObject x="{x + 12:.1f}" y="{y + 94:.1f}" width="276" height="152">
          <div xmlns="http://www.w3.org/1999/xhtml" class="node-tx-box">
            <div class="node-tx-head">TX evidence: {len(node.get("transactions") or [])} fetched</div>
            {tx_html}
          </div>
        </foreignObject>
      </g>''')

    legend_items = [
        ("#5fd18b", "Clean"),
        ("#6db8ff", "Known entity"),
        ("#ff9f43", "Scam reports"),
        ("#60a5fa", "Bridge/swap"),
        ("#ff6b6b", "Mixer linked"),
        ("#ff335f", "Sanctioned"),
        ("#7f8ea3", "Lookup issue"),
    ]
    legend = "".join(
        f'<span><i style="background:{color}"></i>{escape(label)}</span>'
        for color, label in legend_items
    )

    suspicious_rows = []
    for node in nodes:
        if not node["is_suspicious"]:
            continue
        labels = ", ".join(node["risk_labels"]) or node["risk_level"]
        suspicious_rows.append(
            "<tr>"
            f"<td>Hop {node['hop']}</td>"
            f"<td><code>{escape(node['address'])}</code></td>"
            f"<td><strong style=\"color:{node['risk_color']}\">{escape(node['risk_level'].upper())}</strong></td>"
            f"<td>{escape(labels)}</td>"
            "</tr>"
        )
    suspicious_table = ""
    if suspicious_rows:
        suspicious_table = f'''
    <div class="graph-table">
      <h3>Suspicious Activity Nodes</h3>
      <table>
        <thead><tr><th>Hop</th><th>Wallet</th><th>Risk</th><th>Signal</th></tr></thead>
        <tbody>{''.join(suspicious_rows)}</tbody>
      </table>
    </div>'''

    warn_html = ""
    if graph["warnings"]:
        warn_html = "<p class=\"trace-notes\"><strong>Tracer notes:</strong> " + "; ".join(
            escape(str(w)) for w in graph["warnings"]
        ) + "</p>"

    stats = graph["stats"]
    direction = "Outflows" if graph["direction"] == "out" else "Inflows"
    token_options = sorted({
        str(tx.get("token") or "").upper()
        for node in nodes
        for tx in (node.get("transactions") or [])
        if tx.get("token")
    })
    graph_json = (
        json.dumps(graph, ensure_ascii=False, sort_keys=True)
        .replace("</", "<\\/")
    )
    html = f'''
  <section class="section ai-section trace-graph-section">
    <h2>Interactive Wallet Intelligence Graph</h2>
    <p class="muted">Investigator workspace for traced wallets. Click any node to inspect attribution, sanctions, scam reports, mixer exposure, balances, transfers, counterparties, and raw evidence.</p>
    <div class="graph-summary">
      <div><span>Wallets</span><strong>{stats["nodes"]}</strong></div>
      <div><span>Transfers</span><strong>{stats["edges"]}</strong></div>
      <div><span>Flagged</span><strong>{stats["suspicious_nodes"]}</strong></div>
      <div><span>Timeline Events</span><strong>{stats["timeline_events"]}</strong></div>
      <div><span>Patterns</span><strong>{stats["patterns"]}</strong></div>
      <div><span>Mode</span><strong>{escape(str(graph["mode"]).title())}</strong></div>
      <div><span>Direction</span><strong>{escape(direction)}</strong></div>
    </div>
    <div class="graph-legend">{legend}</div>
    {warn_html}
    <div class="graph-toolbar">
      <input id="graphSearch" type="search" placeholder="Search address, entity, token, hash, risk..." aria-label="Search graph intelligence">
      <select id="riskFilter" aria-label="Risk filter">
        <option value="">All risks</option>
        <option value="sanctioned">Sanctioned</option>
        <option value="mixer">Mixer linked</option>
        <option value="scam">Scam reports</option>
        <option value="bridge_swap">Bridge/swap</option>
        <option value="entity">Known entity</option>
        <option value="error">Lookup issue</option>
        <option value="clean">Clean</option>
      </select>
      <select id="hopFilter" aria-label="Hop filter">
        <option value="">All hops</option>
        {''.join(f'<option value="{h}">Hop {h}</option>' for h in sorted(hop_groups.keys()))}
      </select>
      <select id="tokenFilter" aria-label="Token filter">
        <option value="">All tokens</option>
        {''.join(f'<option value="{escape(t)}">{escape(t)}</option>' for t in token_options)}
      </select>
      <input id="minAmountFilter" type="number" min="0" step="any" placeholder="Min amount" aria-label="Minimum transaction amount">
      <button type="button" id="resetGraph">Reset</button>
    </div>
    <div class="trace-workspace">
      <div class="trace-graph-wrap">
        <svg class="trace-graph" viewBox="0 0 {width} {height}" role="img" aria-label="Wallet fund-flow graph">
          <defs>
            <filter id="nodeShadow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#000000" flood-opacity="0.26"/>
            </filter>
          </defs>
          {''.join(edge_svg)}
          {''.join(node_svg)}
        </svg>
      </div>
      <aside class="node-inspector" id="nodeInspector">
        <h3>Node Intelligence</h3>
        <p class="muted">Select a wallet node to inspect all collected intelligence.</p>
      </aside>
    </div>
    <div class="graph-table" id="patternTable"></div>
    <div class="graph-table" id="timelineTable"></div>
    <div class="graph-table" id="edgeTable"></div>
    <details class="raw-graph-data">
      <summary>Raw Graph Intelligence JSON</summary>
      <pre id="rawGraphJson"></pre>
    </details>
    {suspicious_table}
    <script type="application/json" id="traceGraphData">{graph_json}</script>
    <script>{trace_graph_js()}</script>
  </section>'''

    if standalone:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wallet Activity Graph</title>
{trace_graph_css()}
</head>
<body class="trace-graph-standalone">
<main class="graph-page">
  <header class="graph-header">
    <h1>Wallet Activity Graph</h1>
    <p>Seed: <code>{escape(graph["seed"])}</code></p>
    <p>Generated: {escape(generated_at)}</p>
  </header>
  {html}
</main>
</body>
</html>'''
    return html


def trace_graph_css() -> str:
    """CSS used by both embedded reports and standalone graph exports."""
    return '''<style>
.trace-graph-section { border-left-color:#56c7ff !important; }
.graph-summary { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; margin:14px 0; }
.graph-summary div { background:rgba(255,255,255,.045); border:1px solid rgba(255,255,255,.08); border-radius:8px; padding:12px; }
.graph-summary span { display:block; color:#9db0d0; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }
.graph-summary strong { display:block; margin-top:5px; font-size:22px; color:#dbe7ff; }
.graph-legend { display:flex; flex-wrap:wrap; gap:10px 16px; margin:12px 0 16px; color:#c7d7f2; font-size:13px; }
.graph-legend span { display:inline-flex; align-items:center; gap:7px; }
.graph-legend i { display:inline-block; width:11px; height:11px; border-radius:50%; box-shadow:0 0 0 2px rgba(255,255,255,.10); }
.trace-notes { color:#ffd166; }
.graph-toolbar { display:grid; grid-template-columns:minmax(220px,1fr) 150px 120px 140px 130px auto; gap:10px; margin:14px 0; }
.graph-toolbar input, .graph-toolbar select, .graph-toolbar button { background:#0b1426; color:#dbe7ff; border:1px solid #2a3a58; border-radius:8px; padding:10px 11px; font:14px Inter,Segoe UI,Arial,sans-serif; }
.graph-toolbar button { cursor:pointer; background:#163154; }
.trace-workspace { display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:14px; align-items:start; }
.trace-graph-wrap { overflow:auto; background:#07101f; border:1px solid #21304a; border-radius:8px; padding:12px; }
.trace-graph { width:100%; min-width:720px; height:auto; display:block; }
.edge { fill:none; stroke:#7085a6; stroke-width:2.2; opacity:.82; }
.arrow { fill:#7085a6; opacity:.9; }
.edge-label { fill:#cbd8ef; font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; paint-order:stroke; stroke:#07101f; stroke-width:5px; stroke-linejoin:round; }
.node { cursor:pointer; transition:opacity .16s ease, transform .16s ease; }
.node rect { fill:#101b31; stroke:var(--risk); stroke-width:2.4; filter:url(#nodeShadow); }
.node.seed rect { stroke-width:3.4; }
.node.selected rect { fill:#182a4a; stroke-width:4; }
.node.dimmed { opacity:.16; }
.node-hop { fill:#b5c8e8; font:600 12px Inter,Segoe UI,Arial,sans-serif; }
.node-address { fill:#ffffff; font:700 16px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
.node-meta, .node-balance { fill:#9db0d0; font:12px Inter,Segoe UI,Arial,sans-serif; }
.node-tx-box { height:146px; overflow:auto; color:#dbe7ff; font:11px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; background:rgba(4,10,20,.55); border:1px solid rgba(255,255,255,.10); border-radius:6px; padding:7px; }
.node-tx-head { color:#9dd1ff; font-weight:700; margin-bottom:5px; font-family:Inter,Segoe UI,Arial,sans-serif; }
.node-tx-row { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; border-top:1px solid rgba(255,255,255,.07); padding:4px 0; }
.node-tx-row:first-of-type { border-top:0; }
.muted-row { color:#9db0d0; }
.node-inspector { background:#0b1426; border:1px solid #243653; border-radius:8px; padding:14px; max-height:720px; overflow:auto; position:sticky; top:12px; }
.node-inspector h3 { margin:0 0 10px; }
.inspector-title { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.risk-dot { width:12px; height:12px; border-radius:50%; display:inline-block; box-shadow:0 0 0 2px rgba(255,255,255,.12); }
.intel-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:10px 0; }
.intel-grid div { background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08); border-radius:8px; padding:9px; }
.intel-grid span { display:block; color:#9db0d0; font-size:11px; text-transform:uppercase; letter-spacing:.06em; }
.intel-grid strong { display:block; margin-top:4px; overflow-wrap:anywhere; }
.chip-row { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0; }
.chip { border:1px solid #314565; background:#111f37; color:#dbe7ff; border-radius:999px; padding:4px 8px; font-size:12px; }
.intel-section { margin-top:13px; }
.intel-section h4 { margin:0 0 7px; color:#dbe7ff; }
.mini-table { width:100%; border-collapse:collapse; font-size:12px; }
.mini-table th, .mini-table td { border:1px solid #24324a; padding:7px; vertical-align:top; }
.mini-table th { background:#15213a; }
.mini-table code, .node-inspector code { color:#9dd1ff; overflow-wrap:anywhere; word-break:break-all; white-space:normal; }
.tx-evidence-table { min-width:980px; }
.tx-evidence-table td { font-size:11px; }
.raw-graph-data { margin-top:16px; border:1px solid #24324a; border-radius:8px; padding:10px 12px; background:#0b1426; }
.raw-graph-data summary { cursor:pointer; color:#cfe0fb; font-weight:700; }
.raw-graph-data pre { max-height:360px; overflow:auto; margin-top:10px; }
.graph-table { margin-top:16px; }
.graph-table table { width:100%; border-collapse:collapse; }
.graph-table th, .graph-table td { border:1px solid #24324a; padding:10px; text-align:left; vertical-align:top; }
.graph-table th { background:#15213a; }
.graph-table code { color:#9dd1ff; word-break:break-all; overflow-wrap:anywhere; white-space:normal; }
.graph-page { max-width:1280px; margin:0 auto; padding:28px 18px 46px; color:#dbe7ff; font-family:Inter,Segoe UI,Arial,sans-serif; }
.trace-graph-standalone { margin:0; background:#0b1220; }
.graph-header { margin-bottom:18px; }
.graph-header h1 { margin:0 0 8px; }
.graph-header p { margin:4px 0; color:#9db0d0; }
.trace-graph-standalone .section { margin-top:22px; background:#111a2e; border:1px solid #24324a; border-radius:8px; padding:22px; }
.muted { color:#9db0d0; }
@media (max-width: 980px) {
  .trace-workspace { grid-template-columns:1fr; }
  .node-inspector { position:static; max-height:none; }
  .graph-toolbar { grid-template-columns:1fr 1fr; }
}
</style>'''


def trace_graph_js() -> str:
    """Client-side interactivity for standalone and embedded graph exports."""
    return r'''(() => {
  const script = document.currentScript;
  const root = script.closest(".trace-graph-section");
  const dataEl = root.querySelector("#traceGraphData");
  const graph = JSON.parse(dataEl.textContent || "{}");
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  const timeline = graph.timeline || [];
  const patterns = graph.patterns || [];
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const inspector = root.querySelector("#nodeInspector");
  const search = root.querySelector("#graphSearch");
  const riskFilter = root.querySelector("#riskFilter");
  const hopFilter = root.querySelector("#hopFilter");
  const tokenFilter = root.querySelector("#tokenFilter");
  const minAmountFilter = root.querySelector("#minAmountFilter");
  const reset = root.querySelector("#resetGraph");
  const raw = root.querySelector("#rawGraphJson");
  if (raw) raw.textContent = JSON.stringify(graph, null, 2);

  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
  const short = value => {
    const s = String(value || "");
    return s.length > 24 ? `${s.slice(0, 12)}...${s.slice(-8)}` : s;
  };
  const full = value => String(value ?? "");
  const amount = (value, token) => {
    const n = Number(value || 0);
    if (!n) return "";
    const text = n >= 1000 ? n.toLocaleString(undefined, {maximumFractionDigits: 2}) :
      n >= 1 ? n.toLocaleString(undefined, {maximumFractionDigits: 6}) :
      n.toLocaleString(undefined, {maximumFractionDigits: 10});
    return `${text} ${token || ""}`.trim();
  };
  const table = (rows, cols) => {
    if (!rows || !rows.length) return '<p class="muted">None captured.</p>';
    return `<table class="mini-table"><thead><tr>${cols.map(c => `<th>${esc(c.label)}</th>`).join("")}</tr></thead><tbody>` +
      rows.map(row => `<tr>${cols.map(c => `<td>${c.code ? "<code>" : ""}${esc(c.get(row))}${c.code ? "</code>" : ""}</td>`).join("")}</tr>`).join("") +
      "</tbody></table>";
  };
  const nodeText = node => JSON.stringify(node.raw || node).toLowerCase();
  const txLink = (hash, chain) => {
    if (!hash) return "";
    const bases = {
      ETH: "https://etherscan.io/tx/",
      MATIC: "https://polygonscan.com/tx/",
      BSC: "https://bscscan.com/tx/",
      ARB: "https://arbiscan.io/tx/",
      OP: "https://optimistic.etherscan.io/tx/",
      BASE: "https://basescan.org/tx/",
      TRX: "https://tronscan.org/#/transaction/",
      BTC: "https://blockstream.info/tx/",
      LTC: "https://blockchair.com/litecoin/transaction/",
      DOGE: "https://blockchair.com/dogecoin/transaction/",
      BCH: "https://blockchair.com/bitcoin-cash/transaction/",
      XRP: "https://blockchair.com/ripple/transaction/",
      SOL: "https://solscan.io/tx/"
    };
    const base = bases[chain] || "";
    return base ? `<a href="${esc(base + hash)}" target="_blank" rel="noopener noreferrer"><code>${esc(full(hash))}</code></a>` : `<code>${esc(full(hash))}</code>`;
  };

  function renderInspector(node) {
    const rawNode = node.raw || {};
    const chips = [
      node.risk_level,
      node.chain,
      rawNode.source,
      rawNode.sanctions_source,
      rawNode.fallback_warning ? "fallback note" : ""
    ].filter(Boolean);
    const riskLabels = (node.risk_labels || []).length ? node.risk_labels : ["No high-risk flag captured"];
    const txs = node.transactions || [...(rawNode.recent_txs || []), ...(rawNode.token_txs || [])];
    const counterparties = node.counterparties || rawNode.top_counterparties || [];
    const tokens = rawNode.tokens || [];
    const sanctions = rawNode.sanction_identifications || [];
    const mixers = rawNode.mixer_details || [];
    const hopSwap = rawNode.chain_hop_swap || {};
    const bridgeSwapRows = [...(hopSwap.bridge_hits || []), ...(hopSwap.swap_hits || [])];
    const scamRecords = ((rawNode.scam_details || {}).records || []).slice(0, 8);
    const arkham = rawNode.arkham || {};
    const relatedEdges = edges.filter(e => e.source === node.id || e.target === node.id);

    inspector.innerHTML = `
      <div class="inspector-title">
        <span class="risk-dot" style="background:${esc(node.risk_color)}"></span>
        <h3>${esc(node.risk_level.toUpperCase())} Wallet</h3>
      </div>
      <p><code>${esc(node.address)}</code></p>
      ${rawNode.explorer ? `<p><a href="${esc(rawNode.explorer)}" target="_blank" rel="noopener noreferrer">Open explorer</a></p>` : ""}
      <div class="chip-row">${chips.map(c => `<span class="chip">${esc(c)}</span>`).join("")}</div>
      <div class="intel-grid">
        <div><span>Risk Score</span><strong>${esc(node.risk_score || 0)}/100</strong></div>
        <div><span>Hop</span><strong>${esc(node.hop)}</strong></div>
        <div><span>Balance</span><strong>${esc(amount(rawNode.balance, rawNode.balance_unit) || "unknown")}</strong></div>
        <div><span>Portfolio USD</span><strong>${rawNode.portfolio_usd ? "$" + Number(rawNode.portfolio_usd).toLocaleString() : "unknown"}</strong></div>
        <div><span>Transactions</span><strong>${esc(rawNode.tx_count || 0)}</strong></div>
        <div><span>Native/Token</span><strong>${esc(rawNode.native_tx_count ?? "?")} / ${esc(rawNode.token_tx_count ?? "?")}</strong></div>
        <div><span>First/Last Seen</span><strong>${esc(rawNode.first_seen || "?")}<br>${esc(rawNode.last_seen || "?")}</strong></div>
      </div>
      <div class="intel-section"><h4>Risk Signals</h4><div class="chip-row">${riskLabels.map(x => `<span class="chip">${esc(x)}</span>`).join("")}</div></div>
      <div class="intel-section"><h4>Arkham Attribution</h4>
        <div class="intel-grid">
          <div><span>Entity</span><strong>${esc(rawNode.arkham_entity || arkham.entity_name || "none")}</strong></div>
          <div><span>Type/Label</span><strong>${esc(rawNode.arkham_type || "?")} / ${esc(rawNode.arkham_label || "?")}</strong></div>
        </div>
      </div>
      <div class="intel-section"><h4>Trace Edges</h4>${table(relatedEdges, [
        {label:"Side", get:e => e.source === node.id ? "out" : "in"},
        {label:"Counterparty", get:e => full(e.source === node.id ? e.target_address : e.source_address), code:true},
        {label:"Amount", get:e => amount(e.amount, e.token)},
        {label:"Hash", get:e => full(e.hash), code:true}
      ])}</div>
      <div class="intel-section"><h4>Top Counterparties</h4>${table(counterparties, [
        {label:"Address", get:r => full(r.address), code:true},
        {label:"TXs", get:r => r.tx_count ?? ""},
        {label:"Sent", get:r => r.sent ?? r.amount ?? ""},
        {label:"Received", get:r => r.received ?? ""},
        {label:"Tokens", get:r => (r.tokens || [r.token || ""]).join(", ")},
        {label:"First/Last", get:r => `${r.first_seen || ""} / ${r.last_seen || ""}`}
      ])}</div>
      <div class="intel-section"><h4>Token Holdings</h4>${table(tokens.slice(0, 12), [
        {label:"Symbol", get:r => r.symbol || r.token || "?"},
        {label:"Balance", get:r => r.balance ?? ""},
        {label:"USD", get:r => r.usd_value ? "$" + Number(r.usd_value).toLocaleString() : ""},
        {label:"Contract", get:r => full(r.contract), code:true}
      ])}</div>
      <div class="intel-section"><h4>All Fetched Transactions / Token Transfers (${txs.length})</h4>
        ${txs && txs.length ? `<table class="mini-table tx-evidence-table"><thead><tr><th>#</th><th>Source</th><th>Dir</th><th>Token</th><th>Value</th><th>Time</th><th>From</th><th>To</th><th>TX Hash</th><th>Status</th></tr></thead><tbody>` +
        txs.map((r, i) => `<tr>
          <td>${i + 1}</td>
          <td>${esc(r.source || "")}</td>
          <td>${esc(r.direction || "")}</td>
          <td>${esc(r.token || rawNode.balance_unit || "")}</td>
          <td>${esc(r.value ?? r.value_eth ?? r.value_trx ?? r.delta_btc ?? "")}</td>
          <td>${esc(r.time || "")}</td>
          <td><code>${esc(r.from || "")}</code></td>
          <td><code>${esc(r.to || "")}</code></td>
          <td>${txLink(r.hash || r.txid, node.chain)}</td>
          <td>${r.error ? "error" : (r.confirmed === false ? "unconfirmed" : "ok")}</td>
        </tr>`).join("") + "</tbody></table>" : '<p class="muted">No fetched TX rows.</p>'}
      </div>
      <div class="intel-section"><h4>Sanctions</h4>${table(sanctions, [
        {label:"Name", get:r => r.name || ""},
        {label:"Category", get:r => r.category || ""},
        {label:"Description", get:r => r.description || ""}
      ])}</div>
      <div class="intel-section"><h4>Mixer / Obfuscation Hits</h4>${table(mixers, [
        {label:"Name", get:r => r.mixer_name || ""},
        {label:"Type", get:r => r.mixer_type || ""},
        {label:"Counterparty", get:r => full(r.counterparty), code:true},
        {label:"TX", get:r => full(r.tx_hash), code:true}
      ])}</div>
      <div class="intel-section"><h4>Chain Hopping / Swap Signals</h4>${table(bridgeSwapRows, [
        {label:"Type", get:r => r.type || ""},
        {label:"Name", get:r => r.name || ""},
        {label:"Counterparty", get:r => full(r.counterparty), code:true},
        {label:"Dir", get:r => r.direction || ""},
        {label:"Value", get:r => `${r.value || ""} ${r.token || ""}`.trim()},
        {label:"TX", get:r => full(r.tx_hash), code:true}
      ])}</div>
      <div class="intel-section"><h4>Scam Reports</h4>${table(scamRecords, [
        {label:"Source/Type", get:r => r.source || r.type || r.category || ""},
        {label:"Preview", get:r => JSON.stringify(r).slice(0, 180)}
      ])}</div>
      ${(rawNode.error || rawNode.fallback_warning) ? `<div class="intel-section"><h4>Data Notes</h4><p>${esc(rawNode.error || "")}</p><p>${esc(rawNode.fallback_warning || "")}</p></div>` : ""}
      <details class="raw-graph-data"><summary>Raw node JSON</summary><pre>${esc(JSON.stringify(rawNode, null, 2))}</pre></details>
      <details class="raw-graph-data"><summary>Normalized TX evidence JSON</summary><pre>${esc(JSON.stringify(txs, null, 2))}</pre></details>
    `;
  }

  function selectNode(id) {
    root.querySelectorAll(".node").forEach(el => el.classList.toggle("selected", el.dataset.nodeId === id));
    renderInspector(byId[id]);
  }

  function applyFilters() {
    const q = (search.value || "").toLowerCase().trim();
    const risk = riskFilter.value;
    const hop = hopFilter.value;
    const token = (tokenFilter.value || "").toUpperCase();
    const minAmount = Number(minAmountFilter.value || 0);
    root.querySelectorAll(".node").forEach(el => {
      const node = byId[el.dataset.nodeId];
      const matchQ = !q || nodeText(node).includes(q);
      const matchRisk = !risk || node.risk_level === risk;
      const matchHop = !hop || String(node.hop) === hop;
      const txs = node.transactions || [];
      const matchToken = !token || txs.some(tx => String(tx.token || "").toUpperCase() === token);
      const matchAmount = !minAmount || txs.some(tx => Number(tx.value || 0) >= minAmount);
      el.classList.toggle("dimmed", !(matchQ && matchRisk && matchHop && matchToken && matchAmount));
    });
  }

  function renderEdgeTable() {
    const holder = root.querySelector("#edgeTable");
    if (!holder) return;
    holder.innerHTML = `<h3>Transfer Edges</h3><table><thead><tr><th>From</th><th>To</th><th>Amount</th><th>TX Hash</th></tr></thead><tbody>` +
      edges.map(e => `<tr><td><code>${esc(full(e.source_address))}</code></td><td><code>${esc(full(e.target_address))}</code></td><td>${esc(amount(e.amount, e.token))}</td><td><code>${esc(full(e.hash || ""))}</code></td></tr>`).join("") +
      "</tbody></table>";
  }

  function renderPatternTable() {
    const holder = root.querySelector("#patternTable");
    if (!holder) return;
    holder.innerHTML = `<h3>Deterministic Pattern Alerts</h3>` +
      (patterns.length ? `<table><thead><tr><th>Severity</th><th>Pattern</th><th>Scope</th><th>Wallet</th><th>Confidence</th><th>Evidence</th></tr></thead><tbody>` +
      patterns.map(p => `<tr><td>${esc(p.severity || "")}</td><td><strong>${esc(p.pattern || "")}</strong></td><td>${esc(p.scope || "")}</td><td><code>${esc(full(p.address || ""))}</code></td><td>${esc(p.confidence || "")}</td><td>${esc(p.evidence || "")}</td></tr>`).join("") +
      "</tbody></table>" : '<p class="muted">No deterministic pattern alerts fired on fetched data.</p>');
  }

  function renderTimelineTable() {
    const holder = root.querySelector("#timelineTable");
    if (!holder) return;
    const rows = timeline.slice(0, 300);
    holder.innerHTML = `<h3>Chronological Transaction Timeline (${timeline.length})</h3>` +
      (rows.length ? `<table><thead><tr><th>Time</th><th>Wallet</th><th>Hop</th><th>Risk</th><th>Dir</th><th>Token</th><th>Value</th><th>From</th><th>To</th><th>TX</th></tr></thead><tbody>` +
      rows.map(r => `<tr><td>${esc(r.time || "")}</td><td><code>${esc(full(r.wallet || ""))}</code></td><td>${esc(r.hop ?? "")}</td><td>${esc(r.risk_level || "")}</td><td>${esc(r.direction || "")}</td><td>${esc(r.token || "")}</td><td>${esc(r.value || "")}</td><td><code>${esc(full(r.from || ""))}</code></td><td><code>${esc(full(r.to || ""))}</code></td><td>${txLink(r.hash, r.chain)}</td></tr>`).join("") +
      "</tbody></table>" : '<p class="muted">No timeline events captured.</p>') +
      (timeline.length > rows.length ? `<p class="muted">Showing first ${rows.length} events. Full timeline is in graph_model.json and timeline.csv.</p>` : "");
  }

  root.querySelectorAll(".node").forEach(el => {
    el.addEventListener("click", () => selectNode(el.dataset.nodeId));
    el.addEventListener("keydown", ev => {
      if (ev.key === "Enter" || ev.key === " ") selectNode(el.dataset.nodeId);
    });
  });
  [search, riskFilter, hopFilter, tokenFilter, minAmountFilter].forEach(el => el && el.addEventListener("input", applyFilters));
  reset && reset.addEventListener("click", () => {
    search.value = "";
    riskFilter.value = "";
    hopFilter.value = "";
    tokenFilter.value = "";
    minAmountFilter.value = "";
    applyFilters();
  });
  renderEdgeTable();
  renderPatternTable();
  renderTimelineTable();
  if (nodes[0]) selectNode(nodes[0].id);
})();'''


def save_trace_graph_html(result: Dict[str, Any], output_path: Optional[Path] = None) -> Path:
    """Save the trace graph as a standalone HTML file and return its path."""
    if output_path is None:
        reports_dir = (Path(__file__).resolve().parent / "reports").resolve()
        reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        seed = _short_addr(str(result.get("seed") or "wallet"), 10).replace("...", "_")
        output_path = reports_dir / f"wallet_activity_graph_{seed}_{stamp}.html"

    output_path.write_text(format_trace_graph_html(result, standalone=True), encoding="utf-8")
    return output_path


def _case_id(result: Dict[str, Any]) -> str:
    seed = str(result.get("seed") or "wallet")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return f"case_{stamp}_{digest}"


def save_trace_evidence_bundle(result: Dict[str, Any], output_path: Optional[Path] = None) -> Path:
    """
    Save an investigator evidence bundle:
      - interactive graph HTML
      - graph model JSON
      - node risk CSV
      - transaction evidence CSV
      - trace edge CSV
      - manifest JSON
    """
    graph = build_trace_graph_model(result)
    reports_dir = (Path(__file__).resolve().parent / "reports").resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    cid = _case_id(result)
    if output_path is None:
        output_path = reports_dir / f"{cid}_crypto_evidence_bundle.zip"

    manifest = {
        "case_id": cid,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "seed": result.get("seed") or "",
        "mode": result.get("mode") or "",
        "direction": result.get("direction") or "",
        "hops_requested": result.get("hops_requested", 0),
        "total_looked_up": result.get("total_looked_up", 0),
        "stats": graph.get("stats") or {},
        "warnings": graph.get("warnings") or [],
        "files": [
            "interactive_graph.html",
            "graph_model.json",
            "nodes.csv",
            "transactions.csv",
            "counterparties.csv",
            "patterns.csv",
            "timeline.csv",
            "edges.csv",
            "manifest.json",
        ],
    }

    def _csv_text(headers: List[str], rows: List[Dict[str, Any]]) -> str:
        from io import StringIO
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buf.getvalue()

    node_rows = []
    tx_rows = []
    cp_rows = []
    for node in graph.get("nodes", []):
        raw = node.get("raw") or {}
        node_rows.append({
            "node_id": node.get("id"),
            "address": node.get("address"),
            "hop": node.get("hop"),
            "chain": node.get("chain"),
            "risk_level": node.get("risk_level"),
            "risk_score": node.get("risk_score"),
            "risk_labels": "; ".join(node.get("risk_labels") or []),
            "bridge_hits": raw.get("bridge_hits"),
            "swap_hits": raw.get("swap_hits"),
            "entity": node.get("entity"),
            "balance": node.get("balance"),
            "balance_unit": node.get("balance_unit"),
            "portfolio_usd": raw.get("portfolio_usd"),
            "tx_count": node.get("tx_count"),
            "fetched_transactions": node.get("transaction_count_fetched"),
            "source": node.get("source"),
            "explorer": node.get("explorer"),
            "error": raw.get("error"),
        })
        for tx in node.get("transactions") or []:
            tx_rows.append({
                "node_id": node.get("id"),
                "wallet": node.get("address"),
                "hop": node.get("hop"),
                "chain": node.get("chain"),
                "risk_level": node.get("risk_level"),
                "source": tx.get("source"),
                "hash": tx.get("hash"),
                "time": tx.get("time"),
                "direction": tx.get("direction"),
                "from": tx.get("from"),
                "to": tx.get("to"),
                "value": tx.get("value"),
                "token": tx.get("token"),
                "type": tx.get("type"),
                "confirmed": tx.get("confirmed"),
                "error": tx.get("error"),
            })
        for cp in node.get("counterparties") or []:
            cp_rows.append({
                "node_id": node.get("id"),
                "wallet": node.get("address"),
                "hop": node.get("hop"),
                "counterparty": cp.get("address"),
                "tx_count": cp.get("tx_count"),
                "sent": cp.get("sent"),
                "received": cp.get("received"),
                "total_volume": cp.get("total_volume"),
                "tokens": ";".join(cp.get("tokens") or []),
                "first_seen": cp.get("first_seen"),
                "last_seen": cp.get("last_seen"),
                "hashes": ";".join(cp.get("hashes") or []),
            })

    edge_rows = [
        {
            "source_node": e.get("source"),
            "target_node": e.get("target"),
            "source_address": e.get("source_address"),
            "target_address": e.get("target_address"),
            "amount": e.get("amount"),
            "token": e.get("token"),
            "hash": e.get("hash"),
        }
        for e in graph.get("edges", [])
    ]

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("interactive_graph.html", format_trace_graph_html(result, standalone=True))
        zf.writestr("graph_model.json", json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True))
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        zf.writestr("nodes.csv", _csv_text([
            "node_id", "address", "hop", "chain", "risk_level", "risk_score",
            "risk_labels", "bridge_hits", "swap_hits", "entity", "balance", "balance_unit", "portfolio_usd",
            "tx_count", "fetched_transactions", "source", "explorer", "error",
        ], node_rows))
        zf.writestr("transactions.csv", _csv_text([
            "node_id", "wallet", "hop", "chain", "risk_level", "source", "hash",
            "time", "direction", "from", "to", "value", "token", "type",
            "confirmed", "error",
        ], tx_rows))
        zf.writestr("counterparties.csv", _csv_text([
            "node_id", "wallet", "hop", "counterparty", "tx_count", "sent",
            "received", "total_volume", "tokens", "first_seen", "last_seen", "hashes",
        ], cp_rows))
        zf.writestr("patterns.csv", _csv_text([
            "scope", "node_id", "address", "pattern", "severity", "confidence", "evidence",
        ], graph.get("patterns") or []))
        zf.writestr("timeline.csv", _csv_text([
            "node_id", "wallet", "hop", "chain", "risk_level", "risk_score",
            "time", "source", "direction", "hash", "from", "to", "value", "token", "type",
        ], graph.get("timeline") or []))
        zf.writestr("edges.csv", _csv_text([
            "source_node", "target_node", "source_address", "target_address",
            "amount", "token", "hash",
        ], edge_rows))
    return output_path


_RISK_ICON = {
    "sanctioned": "🚨",
    "mixer":      "🌀",
    "scam":       "🛡️",
    "entity":     "🏴",
}

_HOP_INDENT = "  "   # indent per hop level


def format_trace_html(result: Dict[str, Any], max_chars: int = 4000) -> str:
    """
    Render a trace_funds() result as Telegram-safe HTML.

    Layout:
      Header — seed, mode, direction, total lookups
      Per-node block — hop label, address, balance, risk flags, flow amount
      Summary — totals for sanctioned, mixer, known-entity nodes
      Warnings — if any
    """
    if result.get("error"):
        return f"<b>❌ Trace failed:</b> {_e(result['error'])}"

    seed    = _e(result.get("seed", ""))
    hops    = result.get("hops_requested", "?")
    mode    = result.get("mode", "linear")
    direc   = result.get("direction", "out")
    total   = result.get("total_looked_up", 0)
    nodes   = result.get("nodes") or []
    warns   = result.get("warnings") or []

    dir_label  = "→ outflows (sends)" if direc == "out" else "← inflows (receives)"
    mode_label = "linear (top flow)" if mode == "linear" else f"wide (top {MAX_WIDE_BRANCH} per hop)"

    lines = [
        "<b>💸 Fund Flow Trace</b>",
        f"Seed: <code>{seed[:42]}</code>",
        f"Direction: <b>{_e(dir_label)}</b>  |  Mode: <b>{_e(mode_label)}</b>",
        f"Hops: <b>{hops}</b>  |  Addresses queried: <b>{total}</b>",
    ]

    # ── Per-node blocks ────────────────────────────────────────────────────
    for node in nodes:
        hop        = node.get("hop", 0)
        addr       = node.get("address", "")
        chain      = node.get("chain", "?")
        bal        = node.get("balance", 0)
        unit       = node.get("balance_unit", "")
        tx_cnt     = node.get("tx_count", 0)
        sanctioned = node.get("sanctioned", False)
        sanc_ids   = node.get("sanction_ids") or []
        arkham_e   = node.get("arkham_entity", "")
        arkham_t   = node.get("arkham_type", "")
        arkham_l   = node.get("arkham_label", "")
        mx_hits    = node.get("mixer_hits", 0)
        mx_names   = node.get("mixer_names") or []
        scam_cnt   = node.get("scam_reports", 0)
        via_amt    = node.get("via_amount", 0)
        via_token  = node.get("via_token", "") or unit
        via_hash   = node.get("via_hash", "")
        explorer   = node.get("explorer", "")
        err        = node.get("error", "")
        top_cps    = node.get("top_counterparties") or []

        indent = _HOP_INDENT * hop
        if hop == 0:
            hop_label = "🌱 <b>Seed Address</b>"
            separator = "━" * 12
        else:
            hop_label = f"⛓ <b>Hop {hop}</b>"
            separator = "─" * max(4, 10 - hop * 2)

        lines.append("")
        lines.append(f"{indent}{separator} {hop_label}")
        lines.append(
            f"{indent}📍 <code>{_e(addr[:36])}{'…' if len(addr) > 36 else ''}</code>"
            f"  <i>[{_e(chain)}]</i>"
        )

        # Flow amount from parent
        if via_amt and hop > 0:
            hash_str = (f"  <code>{_e(via_hash[:16])}…</code>" if via_hash else "")
            lines.append(
                f"{indent}↳ Flow: <code>{via_amt} {_e(via_token)}</code>{hash_str}"
            )

        # Balance & activity
        lines.append(
            f"{indent}💰 Balance: <code>{bal} {_e(unit)}</code>"
            f"  |  Txs: <code>{tx_cnt}</code>"
        )

        # Risk flags
        risk_parts = []
        if sanctioned:
            label = ", ".join(_e(s) for s in sanc_ids[:2]) or "OFAC/SDN"
            risk_parts.append(f"🚨 <b>SANCTIONED</b> ({label})")
        if mx_hits:
            names = ", ".join(_e(n) for n in mx_names[:2])
            risk_parts.append(f"🌀 <b>Mixer</b> ({names})" if names
                              else f"🌀 <b>Mixer ({mx_hits} hit{'s' if mx_hits != 1 else ''})</b>")
        if scam_cnt:
            risk_parts.append(f"🛡️ ScamSearch: <b>{scam_cnt} report(s)</b>")
        if arkham_e:
            label_part = f" [{_e(arkham_l)}]" if arkham_l else ""
            risk_parts.append(f"🏴 <b>{_e(arkham_e)}</b> <i>{_e(arkham_t)}{label_part}</i>")

        if risk_parts:
            for rp in risk_parts:
                lines.append(f"{indent}⚡ {rp}")

        # Error notice
        if err and not bal:
            lines.append(f"{indent}<i>⚠️ {_e(str(err)[:100])}</i>")

        # Explorer link
        if explorer:
            lines.append(f"{indent}🔗 {_e(explorer)}")

        # Top next-hop counterparties (shown on non-leaf nodes for context)
        if top_cps and hop < result.get("hops_requested", 0):
            cp_strs = [
                f"<code>{_e(cp['address'][:18])}…</code>"
                + (f" ({cp['amount']} {_e(cp.get('token', '') or unit)})" if cp['amount'] else "")
                for cp in top_cps
            ]
            lines.append(f"{indent}  ↪ Next: {', '.join(cp_strs)}")

    # ── Summary ────────────────────────────────────────────────────────────
    sanctioned_n = sum(1 for n in nodes if n.get("sanctioned"))
    mixer_n      = sum(1 for n in nodes if n.get("mixer_hits", 0) > 0)
    entity_n     = sum(1 for n in nodes if n.get("arkham_entity"))
    scam_n       = sum(1 for n in nodes if n.get("scam_reports", 0) > 0)

    if any([sanctioned_n, mixer_n, entity_n, scam_n]):
        lines.append("")
        lines.append("<b>📋 Trace Summary</b>")
        if sanctioned_n:
            lines.append(f"🚨 SANCTIONED addresses found: <b>{sanctioned_n}</b>")
        if mixer_n:
            lines.append(f"🌀 Mixer-linked addresses: <b>{mixer_n}</b>")
        if scam_n:
            lines.append(f"🛡️ ScamSearch-flagged addresses: <b>{scam_n}</b>")
        if entity_n:
            known = [n.get("arkham_entity", "") for n in nodes if n.get("arkham_entity")]
            lines.append(f"🏴 Known entities: <b>{entity_n}</b> — {', '.join(_e(e) for e in known[:5])}")
    else:
        lines.append("")
        lines.append("📋 <i>No high-risk flags detected across traced addresses.</i>")

    # ── Warnings ──────────────────────────────────────────────────────────
    if warns:
        lines.append("")
        lines.append("<b>⚠️ Tracer notes</b>")
        for w in warns:
            lines.append(f"• <i>{_e(w)}</i>")

    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars - 30] + "\n<i>… output truncated …</i>"
    return out


# =============================================================================
# ASCII tree formatter (for file exports / reports)
# =============================================================================

def format_trace_ascii(result: Dict[str, Any]) -> str:
    """
    Plain-text ASCII tree of the trace — suitable for report files.

    Example:
      [Seed] 0xABCD…  ETH  bal=0.5 ETH  txs=120
        ├─[Hop1] 0x1234…  ETH  flow=0.3 ETH  SANCTIONED
        │   └─[Hop2] 0xDEAD…  ETH  flow=0.3 ETH  Arkham: Binance
        └─[Hop1] 0x5678…  ETH  flow=0.2 ETH  Mixer(Tornado Cash)
    """
    if result.get("error"):
        return f"[ERROR] {result['error']}"

    nodes = result.get("nodes") or []
    # Index by address for quick parent lookup
    node_map: Dict[str, Dict] = {n["address"]: n for n in nodes}

    # Build children map
    children: Dict[str, List[str]] = {}
    for n in nodes:
        parent = n.get("parent", "")
        if parent:
            children.setdefault(parent, []).append(n["address"])

    lines_out: List[str] = [
        f"Fund Trace — seed: {result.get('seed', '?')}",
        f"Mode: {result.get('mode')}  |  Direction: {result.get('direction')}  "
        f"|  Hops: {result.get('hops_requested')}  "
        f"|  Nodes queried: {result.get('total_looked_up')}",
        "",
    ]

    def _render(addr: str, prefix: str, is_last: bool) -> None:
        n       = node_map.get(addr, {})
        hop     = n.get("hop", 0)
        chain   = n.get("chain", "?")
        bal     = n.get("balance", 0)
        unit    = n.get("balance_unit", "")
        tx_cnt  = n.get("tx_count", 0)
        via_amt = n.get("via_amount", 0)
        via_tok = n.get("via_token", "") or unit

        # Risk tags
        tags = []
        if n.get("sanctioned"):
            tags.append("⚠SANCTIONED")
        if n.get("mixer_hits", 0):
            tags.append(f"MIXER({', '.join(n.get('mixer_names', [])[:1])})")
        if n.get("arkham_entity"):
            tags.append(f"Entity:{n['arkham_entity']}")
        if n.get("scam_reports", 0):
            tags.append(f"SCAM({n['scam_reports']})")
        tags_str = "  " + " | ".join(tags) if tags else ""

        connector = "└─" if is_last else "├─"
        label = "[Seed]" if hop == 0 else f"[Hop{hop}]"
        addr_short = addr[:20] + ("…" if len(addr) > 20 else "")

        flow_str = f"  flow={via_amt} {via_tok}" if via_amt and hop > 0 else ""
        lines_out.append(
            f"{prefix}{connector}{label} {addr_short}  {chain}"
            f"  bal={bal} {unit}  txs={tx_cnt}{flow_str}{tags_str}"
        )

        child_addrs = children.get(addr, [])
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child_addr in enumerate(child_addrs):
            _render(child_addr, child_prefix, i == len(child_addrs) - 1)

    # Render from root
    seed = result.get("seed", "")
    if seed in node_map:
        _render(seed, "", True)
    else:
        lines_out.append("[no seed node found]")

    if result.get("warnings"):
        lines_out.append("")
        lines_out.append("Notes:")
        for w in result["warnings"]:
            lines_out.append(f"  * {w}")

    return "\n".join(lines_out)
