"""
Cross-Chain Trace Engine.
Detects and traces asset movements across blockchain networks.

Detection capabilities:
  - Bridge fingerprint detection (Stargate, Wormhole, Hop, Across, Celer,
    Synapse, Multichain, Portal/Wormhole, renBridge, LayerZero)
  - Value/time-window matching across chains (deposit ≈ withdrawal)
  - Wrapped asset movement (WETH, wBTC, wETH on other chains)
  - Stablecoin chain-hop detection (USDT/USDC cross-chain)
  - Cross-chain path confidence scoring
  - Cross-chain exposure summary
"""
from __future__ import annotations
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

# Consolidation: the bridge-contract registry now lives in constants.py (single
# source of truth) so holistic_trace_engine, crosschain_engine, and constants
# can never drift apart. The per-bridge chain list is derived from the registry.
import constants as _C

def _build_bridge_fingerprints() -> dict[str, dict]:
    """Derive BRIDGE_FINGERPRINTS from the canonical constants.BRIDGE_CONTRACTS."""
    out: dict[str, dict] = {}
    # Map bridge-type → common chain coverage (used for the legacy 'chains' field)
    chain_coverage = {
        "wormhole": ["ETH", "BSC", "SOL", "AVAX", "MATIC"],
        "layerzero": ["ETH", "BSC", "AVAX", "MATIC", "ARB", "OP"],
        "stargate": ["ETH", "BSC", "AVAX", "MATIC", "ARB", "OP", "FTM"],
        "hop": ["ETH", "ARB", "OP", "MATIC", "XDAI"],
        "synapse": ["ETH", "BSC", "AVAX", "MATIC", "ARB", "OP", "FTM", "MOVR"],
        "across": ["ETH", "ARB", "OP", "BASE", "MATIC"],
        "polygon_bridge": ["ETH", "MATIC"],
        "arbitrum_bridge": ["ETH", "ARB"],
        "op_bridge": ["ETH", "OP"],
        "base_bridge": ["ETH", "BASE"],
        "ronin_bridge": ["ETH", "RONIN"],
    }
    for addr, (btype, label) in _C.BRIDGE_CONTRACTS.items():
        out[addr.lower()] = {
            "name": label,
            "chains": chain_coverage.get(btype, ["ETH"]),
            "type": btype,
        }
    return out

# Build once at import; supplements with any legacy addresses not yet in constants.
BRIDGE_FINGERPRINTS: dict[str, dict] = _build_bridge_fingerprints()
# Legacy entries not yet promoted to constants.py (kept for coverage, will be merged)
_LEGACY_BRIDGES = {
    "0x9a9f2ccfde556a7e9ff0848998aa4a0cfd8863ae": {"name": "Harmony Bridge",      "chains": ["ETH", "ONE"]},
    "0xae92d5ad7583ad66e49a0c67bad18f6ba52dddc1": {"name": "Celer Network Bridge","chains": ["ETH", "BSC", "AVAX", "MATIC", "ARB", "OP"]},
    "0xf6a78083ca3e2a662d6dd1703c939c8ace2e268d": {"name": "Multichain (AnySwap)","chains": ["ETH", "BSC", "FTM", "AVAX", "MATIC", "MOVR"]},
    "0xc30141b657f4216252dc59af2e7cdb9d8792e1b0": {"name": "Socket.Tech",         "chains": ["ETH", "BSC", "AVAX", "MATIC", "ARB", "OP", "FTM"]},
}
for _addr, _info in _LEGACY_BRIDGES.items():
    BRIDGE_FINGERPRINTS.setdefault(_addr, _info)

# Role hints from edge labels — now shared from constants
_BRIDGE_ROLE_TAGS = set(_C.BRIDGE_NAME_HINTS)
# Wrapped-token + stablecoin sets — shared from constants
_WRAP_TOKENS = set(k.lower() for k in _C.WRAPPED_NATIVE_MAP) | {"eth.e", "btc.b", "usdc.e", "usdt.e"}
_STABLECOINS = set(s.lower() for s in _C.STABLE_SYMBOLS)


def _parse_ts(ts) -> float:
    # Accept epoch ints/floats directly (real chain APIs return numeric timestamps).
    if isinstance(ts, (int, float)):
        return float(ts)
    if not ts:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            pass
    try:
        return float(ts)
    except (TypeError, ValueError):
        return 0.0


def _label_lower(node: dict) -> str:
    return f"{node.get('label','')} {node.get('role','')}".lower()


def _is_bridge_node(node: dict) -> bool:
    lbl = _label_lower(node)
    addr = (node.get("address") or node.get("id") or "").lower()
    return (
        any(t in lbl for t in _BRIDGE_ROLE_TAGS) or
        addr in BRIDGE_FINGERPRINTS
    )


def _bridge_info(node: dict) -> dict:
    addr = (node.get("address") or node.get("id") or "").lower()
    if addr in BRIDGE_FINGERPRINTS:
        return BRIDGE_FINGERPRINTS[addr]
    lbl = _label_lower(node)
    for tag in _BRIDGE_ROLE_TAGS:
        if tag in lbl:
            return {"name": tag.title(), "chains": []}
    return {"name": "Unknown bridge", "chains": []}


# ── Detection functions ───────────────────────────────────────────────────────

def _detect_bridge_hops(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
) -> list[dict]:
    """Direct interactions with known bridge contracts."""
    hops = []
    for e in edges:
        src = e.get("source") or ""
        tgt = e.get("target") or ""
        val = float(e.get("value") or 0)
        tok = (e.get("token") or "native").lower()
        ts  = _parse_ts(e.get("time") or e.get("timestamp") or "")

        pivot = None
        if src == subject:
            pivot = tgt
        elif tgt == subject:
            pivot = src

        if pivot and _is_bridge_node(nodes.get(pivot, {})):
            binfo = _bridge_info(nodes.get(pivot, {}))
            hops.append({
                "type":          "bridge_hop",
                "bridge_name":   binfo["name"],
                "bridge_address": pivot,
                "dest_chains":   binfo.get("chains", []),
                "direction":     "outbound" if src == subject else "inbound",
                "value":         val,
                "token":         tok,
                "timestamp":     ts,
                "tx_hash":       e.get("tx_hash") or e.get("hash") or "",
                "confidence":    85,
                "description":   (
                    f"{'Outbound' if src == subject else 'Inbound'} bridge: "
                    f"{val:.4f} {tok} via {binfo['name']}"
                ),
            })
    return hops


def _detect_value_time_match(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
    time_window: float = 3600.0,
    value_tolerance: float = 0.02,
) -> list[dict]:
    """
    Match outbound transactions from subject with inbound transactions to
    other wallets within a time window and value tolerance.
    Classic bridge/mixer value-matching heuristic.
    """
    out_txs = []
    in_txs  = []

    for e in edges:
        src = e.get("source") or ""
        tgt = e.get("target") or ""
        val = float(e.get("value") or 0)
        ts  = _parse_ts(e.get("time") or e.get("timestamp") or "")
        if val <= 0 or ts <= 0:
            continue

        if src == subject:
            out_txs.append({"val": val, "ts": ts, "to": tgt, "edge": e})
        elif tgt != subject:
            in_txs.append({"val": val, "ts": ts, "from": src, "to": tgt, "edge": e})

    matches = []
    for out in out_txs:
        for inp in in_txs:
            time_diff = abs(inp["ts"] - out["ts"])
            if time_diff > time_window:
                continue
            val_diff = abs(inp["val"] - out["val"]) / max(out["val"], 0.0001)
            if val_diff > value_tolerance:
                continue
            # Only flag if the inbound destination is not the same as our subject
            if inp["to"] == subject:
                continue
            matches.append({
                "type":          "value_time_match",
                "out_address":   subject,
                "in_address":    inp["to"],
                "value":         out["val"],
                "value_diff_pct": round(val_diff * 100, 2),
                "time_diff_sec": round(time_diff, 1),
                "out_tx":        out["edge"].get("tx_hash") or out["edge"].get("hash") or "",
                "in_tx":         inp["edge"].get("tx_hash") or inp["edge"].get("hash") or "",
                "confidence":    min(95, int(90 - val_diff * 200 - time_diff / 3600 * 5)),
                "description":   (
                    f"Value-time match: {out['val']:.4f} out → {inp['val']:.4f} in "
                    f"({time_diff:.0f}s apart, {val_diff*100:.1f}% diff)"
                ),
            })
    return matches


def _detect_wrapped_assets(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
) -> list[dict]:
    """Detect wrapped asset movements (WETH, wBTC, bridged tokens)."""
    findings = []
    wrap_out: dict[str, list] = defaultdict(list)
    wrap_in:  dict[str, list] = defaultdict(list)

    for e in edges:
        src = e.get("source") or ""
        tgt = e.get("target") or ""
        tok = (e.get("token") or "").lower()
        val = float(e.get("value") or 0)
        if tok not in _WRAP_TOKENS or val <= 0:
            continue
        if src == subject:
            wrap_out[tok].append({"val": val, "to": tgt, "edge": e})
        elif tgt == subject:
            wrap_in[tok].append({"val": val, "from": src, "edge": e})

    for tok in set(wrap_out.keys()) | set(wrap_in.keys()):
        out_total = sum(x["val"] for x in wrap_out.get(tok, []))
        in_total  = sum(x["val"] for x in wrap_in.get(tok, []))
        if out_total > 0 or in_total > 0:
            findings.append({
                "type":        "wrapped_asset_movement",
                "token":       tok.upper(),
                "out_total":   round(out_total, 6),
                "in_total":    round(in_total, 6),
                "out_count":   len(wrap_out.get(tok, [])),
                "in_count":    len(wrap_in.get(tok, [])),
                "confidence":  75,
                "description": (
                    f"Wrapped asset {tok.upper()}: "
                    f"{out_total:.4f} out / {in_total:.4f} in"
                ),
            })
    return findings


def _detect_stablecoin_hops(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
) -> list[dict]:
    """Large stablecoin flows that may indicate cross-chain conversion."""
    findings = []
    stable_flows: dict[str, dict] = defaultdict(lambda: {"out": 0.0, "in": 0.0, "txs": []})

    for e in edges:
        src = e.get("source") or ""
        tgt = e.get("target") or ""
        tok = (e.get("token") or "").lower()
        val = float(e.get("value") or 0)
        if tok not in _STABLECOINS or val < 100:
            continue
        if src == subject:
            stable_flows[tok]["out"] += val
            stable_flows[tok]["txs"].append(e)
        elif tgt == subject:
            stable_flows[tok]["in"] += val
            stable_flows[tok]["txs"].append(e)

    for tok, data in stable_flows.items():
        if data["out"] + data["in"] > 0:
            findings.append({
                "type":        "stablecoin_hop",
                "token":       tok.upper(),
                "out_usd":     round(data["out"], 2),
                "in_usd":      round(data["in"], 2),
                "net_usd":     round(data["out"] - data["in"], 2),
                "tx_count":    len(data["txs"]),
                "confidence":  70,
                "description": (
                    f"Stablecoin {tok.upper()}: "
                    f"${data['out']:,.0f} out / ${data['in']:,.0f} in — "
                    f"possible cross-chain conversion"
                ),
            })
    return findings


def _build_crosschain_path(
    bridge_hops: list[dict],
    value_matches: list[dict],
) -> list[dict]:
    """Assemble a cross-chain path from bridge hops + value matches."""
    paths = []
    for hop in bridge_hops:
        path_entry = {
            "type":        "bridge_path",
            "bridge":      hop["bridge_name"],
            "direction":   hop["direction"],
            "token":       hop["token"],
            "value":       hop["value"],
            "dest_chains": hop["dest_chains"],
            "confidence":  hop["confidence"],
            "hops":        [hop],
        }
        # Try to find a matching value-time match for the same value
        for vm in value_matches:
            if abs(vm["value"] - hop["value"]) / max(hop["value"], 0.0001) < 0.05:
                path_entry["hops"].append(vm)
                path_entry["confidence"] = min(99, path_entry["confidence"] + 5)
                break
        paths.append(path_entry)
    return paths


def _overall_crosschain_risk(
    bridge_hops: list, value_matches: list, wrapped: list, stable_hops: list
) -> dict:
    score = 0
    score += min(60, len(bridge_hops) * 20)
    score += min(30, len(value_matches) * 15)
    score += min(15, len(stable_hops) * 8)
    score = min(100, score)

    if score >= 75:
        level = "critical"
    elif score >= 50:
        level = "high"
    elif score >= 25:
        level = "medium"
    else:
        level = "low"

    return {
        "level": level,
        "score": score,
        "bridge_hops":    len(bridge_hops),
        "value_matches":  len(value_matches),
        "wrapped_assets": len(wrapped),
        "stablecoin_hops": len(stable_hops),
    }


# ── Public entry point ────────────────────────────────────────────────────────

def trace_crosschain(
    nodes: list[dict],
    edges: list[dict],
    subject_id: str,
    time_window: float = 3600.0,
    value_tolerance: float = 0.02,
) -> dict[str, Any]:
    """
    Main entry point.
    Returns full cross-chain trace report for subject_id.
    """
    node_map = {n["id"]: n for n in nodes}

    bridge_hops   = _detect_bridge_hops(node_map, edges, subject_id)
    value_matches = _detect_value_time_match(node_map, edges, subject_id, time_window, value_tolerance)
    wrapped       = _detect_wrapped_assets(node_map, edges, subject_id)
    stable_hops   = _detect_stablecoin_hops(node_map, edges, subject_id)
    paths         = _build_crosschain_path(bridge_hops, value_matches)
    risk          = _overall_crosschain_risk(bridge_hops, value_matches, wrapped, stable_hops)

    bridges_seen = list({h["bridge_name"] for h in bridge_hops})
    chains_involved = list({c for h in bridge_hops for c in h.get("dest_chains", [])})

    return {
        "subject":          subject_id,
        "bridge_hops":      bridge_hops,
        "value_matches":    value_matches,
        "wrapped_movements": wrapped,
        "stablecoin_hops":  stable_hops,
        "crosschain_paths": paths,
        "risk":             risk,
        "bridges_seen":     bridges_seen,
        "chains_involved":  chains_involved,
        "total_findings":   len(bridge_hops) + len(value_matches) + len(wrapped) + len(stable_hops),
        "summary": (
            f"{len(bridge_hops)} bridge hop(s) via {', '.join(bridges_seen) or 'none'}, "
            f"{len(value_matches)} value match(es), "
            f"{len(chains_involved)} chain(s) involved"
        ),
    }
