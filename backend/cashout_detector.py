"""
Exposure and cash-out detection engine.
Detects patterns indicating a wallet is attempting to convert
crypto to fiat or off-ramp through exchanges/services.

Signals:
  - Exchange deposit patterns (fan-in from many wallets → exchange address)
  - Fan-out hot wallet behavior (service wallet redistributing funds)
  - High-volume concentration to a single destination
  - Stablecoin off-ramp detection (USDT/USDC sudden large transfer)
  - Repeated small deposits into large service wallet (structuring pattern)
  - Known service wallet behaviors
"""
from __future__ import annotations
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


# ── Known service/exchange labels ─────────────────────────────────────────────
_EXCHANGE_LABELS = {
    "binance", "coinbase", "kraken", "okx", "kucoin", "bybit", "gate.io",
    "huobi", "bitfinex", "gemini", "crypto.com", "bitstamp", "bitmex",
    "deribit", "poloniex", "bittrex", "upbit", "korbit", "bithumb",
    "mexc", "lbank", "ascendex", "phemex",
}
_STABLECOIN_TOKENS = {"usdt", "usdc", "dai", "busd", "tusd", "frax", "usdp", "gusd"}
_OFFRAMP_LABELS   = {"moonpay", "ramp", "transak", "simplex", "wyre", "onramper"}


def _parse_ts(ts) -> float:
    # Accept epoch ints/floats directly (real chain APIs return numeric timestamps).
    if isinstance(ts, (int, float)):
        return float(ts)
    if not ts:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
        try:
            from datetime import datetime, timezone
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            pass
    try:
        return float(ts)
    except (ValueError, TypeError):
        return 0.0


def _label_lower(node: dict) -> str:
    return f"{(node.get('label') or '')} {(node.get('role') or '')}".lower()


def _is_exchange(node: dict) -> bool:
    lbl = _label_lower(node)
    return any(e in lbl for e in _EXCHANGE_LABELS | {"exchange", "cex"})


def _is_stablecoin(token: str) -> bool:
    return token.lower() in _STABLECOIN_TOKENS


# ── Pattern detectors ─────────────────────────────────────────────────────────

def _detect_exchange_deposits(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
) -> list[dict]:
    """
    Subject sends funds to an exchange address.
    Returns one indicator per unique exchange destination.
    """
    indicators = []
    out_to_exchange: dict[str, list[dict]] = defaultdict(list)

    for e in edges:
        src = e.get("source") or e.get("src") or ""
        tgt = e.get("target") or e.get("tgt") or ""
        if src == subject:
            tgt_node = nodes.get(tgt, {})
            if _is_exchange(tgt_node):
                out_to_exchange[tgt].append(e)

    for dest, txs in out_to_exchange.items():
        total_val = sum(float(t.get("value") or 0) for t in txs)
        indicators.append({
            "type":          "exchange_deposit",
            "severity":      "high",
            "destination":   dest,
            "dest_label":    nodes.get(dest, {}).get("label") or dest[:10],
            "tx_count":      len(txs),
            "total_value":   total_val,
            "tokens":        list({t.get("token") or "native" for t in txs}),
            "timestamps":    sorted(t.get("time") or t.get("timestamp") or ""
                                    for t in txs),
            "description":   (
                f"Subject sent {len(txs)} tx(s) totalling {total_val:.4f} "
                f"to exchange: {nodes.get(dest,{}).get('label', dest[:8])}"
            ),
            "confidence":    min(100, 40 + len(txs) * 10),
        })
    return indicators


def _detect_structuring(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
) -> list[dict]:
    """
    Repeated near-equal deposits below reporting thresholds (structuring).
    Groups transactions by destination and checks for value clustering.
    """
    indicators = []
    out_by_dest: dict[str, list[float]] = defaultdict(list)

    for e in edges:
        src = e.get("source") or ""
        tgt = e.get("target") or ""
        if src == subject:
            val = float(e.get("value") or 0)
            if val > 0:
                out_by_dest[tgt].append(val)

    for dest, vals in out_by_dest.items():
        if len(vals) < 3:
            continue
        try:
            stdev = statistics.stdev(vals)
            mean  = statistics.mean(vals)
        except statistics.StatisticsError:
            continue
        cv = stdev / mean if mean > 0 else 1.0
        # Low coefficient of variation = suspiciously similar values
        if cv < 0.15 and len(vals) >= 3:
            indicators.append({
                "type":        "structuring",
                "severity":    "medium",
                "destination": dest,
                "dest_label":  nodes.get(dest, {}).get("label") or dest[:10],
                "tx_count":    len(vals),
                "mean_value":  round(mean, 6),
                "stdev":       round(stdev, 6),
                "cv":          round(cv, 4),
                "description": (
                    f"{len(vals)} txs to {dest[:8]} with very similar values "
                    f"(mean={mean:.4f}, cv={cv:.3f}) — possible structuring"
                ),
                "confidence":  min(100, int((1 - cv) * 80 + 10)),
            })
    return indicators


def _detect_stablecoin_offramp(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
) -> list[dict]:
    """
    Large stablecoin (USDT/USDC/DAI) outflows — likely off-ramp attempt.
    """
    indicators = []
    stable_out: dict[str, dict] = defaultdict(lambda: {"tokens": defaultdict(float), "txs": []})

    for e in edges:
        src = e.get("source") or ""
        tgt = e.get("target") or ""
        token = (e.get("token") or "").lower()
        if src == subject and _is_stablecoin(token):
            val = float(e.get("value") or 0)
            stable_out[tgt]["tokens"][token] += val
            stable_out[tgt]["txs"].append(e)

    for dest, data in stable_out.items():
        total = sum(data["tokens"].values())
        if total > 1000:  # >$1k stablecoin flow is notable
            indicators.append({
                "type":          "stablecoin_offramp",
                "severity":      "medium" if total < 50000 else "high",
                "destination":   dest,
                "dest_label":    nodes.get(dest, {}).get("label") or dest[:10],
                "total_usd":     round(total, 2),
                "tokens":        dict(data["tokens"]),
                "tx_count":      len(data["txs"]),
                "description":   (
                    f"${total:,.0f} stablecoin flow to {dest[:8]} "
                    f"({', '.join(data['tokens'].keys())})"
                ),
                "confidence":    min(100, 50 + int(math.log10(total + 1) * 5)),
            })
    return indicators


def _detect_hot_wallet_fanout(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
) -> list[dict]:
    """
    Subject receives large inflow then quickly distributes to many destinations.
    Classic hot-wallet / exchange distribution behavior.
    """
    in_val  = sum(float(e.get("value") or 0) for e in edges
                  if (e.get("target") or "") == subject)
    out_dests = {(e.get("target") or "") for e in edges
                 if (e.get("source") or "") == subject}
    out_val = sum(float(e.get("value") or 0) for e in edges
                  if (e.get("source") or "") == subject)

    indicators = []
    if len(out_dests) >= 5 and out_val > 0 and in_val > 0:
        ratio = out_val / in_val if in_val > 0 else 0
        indicators.append({
            "type":        "hot_wallet_fanout",
            "severity":    "medium",
            "in_value":    round(in_val, 6),
            "out_value":   round(out_val, 6),
            "out_ratio":   round(ratio, 3),
            "dest_count":  len(out_dests),
            "description": (
                f"Hot-wallet behavior: received {in_val:.4f}, "
                f"redistributed to {len(out_dests)} destinations"
            ),
            "confidence":  min(100, 30 + len(out_dests) * 5),
        })
    return indicators


def _detect_fan_in(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
) -> list[dict]:
    """
    Many source wallets sending into subject — consolidation before cashout.
    """
    in_sources = {(e.get("source") or "") for e in edges
                  if (e.get("target") or "") == subject}
    in_val = sum(float(e.get("value") or 0) for e in edges
                 if (e.get("target") or "") == subject)

    indicators = []
    if len(in_sources) >= 5:
        indicators.append({
            "type":         "fan_in_consolidation",
            "severity":     "medium",
            "source_count": len(in_sources),
            "total_in":     round(in_val, 6),
            "description":  (
                f"Subject received funds from {len(in_sources)} distinct sources "
                f"(total: {in_val:.4f}) — consolidation pattern"
            ),
            "confidence":   min(100, 25 + len(in_sources) * 5),
        })
    return indicators


def _detect_offramp_services(
    nodes: dict[str, dict],
    edges: list[dict],
    subject: str,
) -> list[dict]:
    """Detect known off-ramp service usage (MoonPay, Ramp, etc.)."""
    indicators = []
    for e in edges:
        src = e.get("source") or ""
        tgt = e.get("target") or ""
        if src == subject:
            tgt_lbl = _label_lower(nodes.get(tgt, {}))
            for svc in _OFFRAMP_LABELS:
                if svc in tgt_lbl:
                    indicators.append({
                        "type":        "offramp_service",
                        "severity":    "high",
                        "destination": tgt,
                        "service":     svc,
                        "value":       float(e.get("value") or 0),
                        "description": f"Funds sent to off-ramp service: {svc}",
                        "confidence":  85,
                    })
    return indicators


# ── Scoring ───────────────────────────────────────────────────────────────────

def _overall_risk(indicators: list[dict]) -> dict:
    if not indicators:
        return {"level": "low", "score": 0, "summary": "No cashout indicators detected"}

    high   = sum(1 for i in indicators if i.get("severity") == "high")
    medium = sum(1 for i in indicators if i.get("severity") == "medium")
    score  = min(100, high * 30 + medium * 15)

    if score >= 70:
        level = "critical"
    elif score >= 45:
        level = "high"
    elif score >= 20:
        level = "medium"
    else:
        level = "low"

    type_list = list({i["type"] for i in indicators})
    return {
        "level":    level,
        "score":    score,
        "summary":  f"{len(indicators)} cashout indicator(s): {', '.join(type_list)}",
        "high_count":   high,
        "medium_count": medium,
    }


# ── Public entry point ────────────────────────────────────────────────────────

def detect_cashout(
    nodes: list[dict],
    edges: list[dict],
    subject_id: str,
) -> dict[str, Any]:
    """
    Main entry point.  Returns a cashout detection report for subject_id.
    nodes: list of {id, label, role, risk_score, ...}
    edges: list of {source, target, value, token, time/timestamp, tx_hash, ...}
    """
    node_map = {n["id"]: n for n in nodes}

    indicators: list[dict] = []
    indicators += _detect_exchange_deposits(node_map, edges, subject_id)
    indicators += _detect_structuring(node_map, edges, subject_id)
    indicators += _detect_stablecoin_offramp(node_map, edges, subject_id)
    indicators += _detect_hot_wallet_fanout(node_map, edges, subject_id)
    indicators += _detect_fan_in(node_map, edges, subject_id)
    indicators += _detect_offramp_services(node_map, edges, subject_id)

    # Sort by confidence desc
    indicators.sort(key=lambda i: i.get("confidence", 0), reverse=True)

    risk = _overall_risk(indicators)

    # Find most likely cashout destination
    best_dest = None
    best_conf = 0
    for ind in indicators:
        if "destination" in ind and ind.get("confidence", 0) > best_conf:
            best_conf = ind["confidence"]
            best_dest = ind["destination"]

    return {
        "subject":             subject_id,
        "indicators":          indicators,
        "indicator_count":     len(indicators),
        "risk":                risk,
        "primary_cashout_dest": best_dest,
        "exchange_exposure":   any(i["type"] == "exchange_deposit" for i in indicators),
        "stablecoin_exit":     any(i["type"] == "stablecoin_offramp" for i in indicators),
        "structuring_detected": any(i["type"] == "structuring" for i in indicators),
    }
