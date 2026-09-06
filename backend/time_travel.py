"""
Time-travel / historical state reconstruction.

"Show me this wallet's balance and graph as of 2023-06-15."

Replays the transaction history forward from genesis (or the wallet's first tx) to
a target timestamp, computing:
  - Historical balances per asset at that point in time
  - The graph state (counterparties known) as of that date
  - Cumulative volume in/out up to that date

Requires the full transaction history (fetched upstream); this module is pure CPU.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_ts(ts: Any) -> float:
    try:
        if isinstance(ts, (int, float)):
            # treat large numbers as milliseconds
            f = float(ts)
            return f / 1000 if f > 1e12 else f
        s = str(ts).strip()
        if not s:
            return 0.0
        if s.isdigit():
            f = float(s)
            return f / 1000 if f > 1e12 else f
        # ISO format
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp()
    except (TypeError, ValueError):
        return 0.0


def reconstruct_at_timestamp(
    tx_list: list[dict],
    target_ts: float,
    address: str,
    chain: str = "",
) -> dict:
    """Reconstruct balance + graph state at a target unix timestamp.

    Only transactions with timestamp <= target_ts are counted.
    """
    addr_lc = address.lower() if address.startswith("0x") else address
    balances: dict[str, float] = {}
    counterparties: dict[str, dict] = {}
    cumulative_in = 0.0
    cumulative_out = 0.0
    active_edges: list[dict] = []

    for tx in tx_list:
        ts = _parse_ts(tx.get("time") or tx.get("timestamp"))
        if ts == 0 or ts > target_ts:
            continue
        src = str(tx.get("from") or "").lower() if str(tx.get("from") or "").startswith("0x") else tx.get("from")
        tgt = str(tx.get("to") or "").lower() if str(tx.get("to") or "").startswith("0x") else tx.get("to")
        token = tx.get("token") or tx.get("asset") or chain or "native"
        value = float(tx.get("value") or 0)

        if src == addr_lc:
            balances[token] = balances.get(token, 0) - value
            cumulative_out += value
            cp = tgt
        elif tgt == addr_lc:
            balances[token] = balances.get(token, 0) + value
            cumulative_in += value
            cp = src
        else:
            continue
        if cp:
            cp_stats = counterparties.setdefault(cp, {"in": 0.0, "out": 0.0, "txs": 0})
            if src == addr_lc:
                cp_stats["out"] += value
            else:
                cp_stats["in"] += value
            cp_stats["txs"] += 1
        active_edges.append({
            "source": src, "target": tgt, "value": value, "token": token,
            "tx_hash": tx.get("hash") or tx.get("tx_hash") or "", "timestamp": ts,
        })

    return {
        "address": address,
        "chain": chain,
        "target_timestamp": target_ts,
        "target_iso": datetime.fromtimestamp(target_ts, tz=timezone.utc).isoformat(),
        "balances": {k: v for k, v in balances.items()},
        "cumulative_in": cumulative_in,
        "cumulative_out": cumulative_out,
        "net": cumulative_in - cumulative_out,
        "counterparty_count": len(counterparties),
        "top_counterparties": sorted(
            [{"address": k, **v} for k, v in counterparties.items()],
            key=lambda x: x["in"] + x["out"], reverse=True,
        )[:20],
        "active_edges": len(active_edges),
        "disclaimer": "Historical state reconstructed by forward-replay of tx history. "
                      "Accuracy depends on the completeness of the fetched tx list.",
    }


def timeline_evolution(tx_list: list[dict], address: str, chain: str = "",
                       intervals: int = 12) -> dict:
    """Show how balance + counterparty count evolved over time (sparkline data)."""
    if not tx_list:
        return {"points": [], "address": address}
    timestamps = sorted([_parse_ts(tx.get("time") or tx.get("timestamp")) for tx in tx_list if _parse_ts(tx.get("time") or tx.get("timestamp")) > 0])
    if not timestamps:
        return {"points": [], "address": address}
    t_min, t_max = timestamps[0], timestamps[-1]
    if t_max <= t_min:
        return {"points": [], "address": address}
    step = (t_max - t_min) / intervals
    points = []
    for i in range(intervals + 1):
        target = t_min + step * i
        state = reconstruct_at_timestamp(tx_list, target, address, chain)
        points.append({
            "timestamp": target,
            "iso": datetime.fromtimestamp(target, tz=timezone.utc).isoformat()[:10],
            "net_balance": sum(state["balances"].values()),
            "counterparties": state["counterparty_count"],
            "cumulative_in": state["cumulative_in"],
        })
    return {
        "address": address,
        "chain": chain,
        "points": points,
        "first_tx": datetime.fromtimestamp(t_min, tz=timezone.utc).isoformat(),
        "last_tx": datetime.fromtimestamp(t_max, tz=timezone.utc).isoformat(),
    }
