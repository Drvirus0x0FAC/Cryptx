"""
Demixing engine — probabilistic linking across obfuscation layers.

Two capabilities:
  1. Tornado Cash deposit <-> withdrawal pairing (fixed-denomination pools).
  2. Cross-chain bridge lock/burn <-> mint/unlock reconciliation.

Both are HEURISTIC and produce ranked investigative leads with explicit
confidence and reasoning. A link is a hypothesis to corroborate with further
evidence (funding sources, timing, relayer reuse) — never proof on its own.

Inputs are plain event lists so the engine is data-source agnostic: feed it
events pulled from an explorer/indexer, or our own tracing output.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

# Publicly documented Tornado Cash ETH pool contracts (OFAC-designated, Aug 2022).
TORNADO_ETH_POOLS: dict[float, str] = {
    0.1: "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc",
    1.0: "0x47 ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936".replace(" ", ""),
    10.0: "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf",
    100.0: "0xa160cdab225685da1d56aa342ad8841c3b53f291",
}
TORNADO_DENOMINATIONS = sorted(TORNADO_ETH_POOLS.keys())

_STABLECOINS = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "FRAX", "USDP", "FDUSD", "PYUSD", "USDD"}
_WRAPPED_ASSETS = {"WETH", "WBTC", "WMATIC", "WBNB", "WAVAX", "ETH.E", "BTC.B", "USDC.E", "USDT.E"}
_BRIDGE_WORDS = {"bridge", "stargate", "wormhole", "hop", "across", "synapse", "celer", "multichain", "layerzero", "socket", "portal"}
_MIXER_WORDS = {"mixer", "tornado", "tumbler", "coinjoin", "wasabi", "samourai", "whirlpool", "sinbad", "blender", "railgun"}
_SWAP_WORDS = {"swap", "router", "dex", "uniswap", "1inch", "pancake", "curve", "sushiswap", "aggregator", "paraswap"}


def _addr(v: Any) -> str:
    return (str(v or "")).strip().lower()


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _token(v: Any) -> str:
    return str(v or "").strip().upper()


def _chain(v: Any) -> str:
    return str(v or "").strip().upper()


def _text(*vals: Any) -> str:
    return " ".join(str(v or "") for v in vals).lower()


def _amount_diff(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1e-9)


def _event_type(e: dict[str, Any]) -> str:
    explicit = _text(e.get("event_type"), e.get("type"), e.get("category"))
    protocol = _text(e.get("protocol"), e.get("service"), e.get("label"), e.get("counterparty_label"))
    blob = f"{explicit} {protocol}"
    if any(w in blob for w in _MIXER_WORDS):
        if "withdraw" in blob or "out" in blob:
            return "mixer_withdrawal"
        if "deposit" in blob or "in" in blob:
            return "mixer_deposit"
        return "mixer"
    if any(w in blob for w in _BRIDGE_WORDS):
        return "bridge"
    if any(w in blob for w in _SWAP_WORDS):
        return "swap"
    return str(e.get("event_type") or e.get("type") or "transfer").lower()


def _normalise_event(e: dict[str, Any]) -> dict[str, Any]:
    amount = _f(e.get("amount") or e.get("value") or e.get("amount_in") or e.get("amount_out"))
    return {
        "tx_hash": e.get("tx_hash") or e.get("hash") or "",
        "chain": _chain(e.get("chain") or e.get("source_chain")),
        "dest_chain": _chain(e.get("dest_chain") or e.get("destination_chain") or e.get("to_chain")),
        "token": _token(e.get("token") or e.get("asset") or e.get("token_in")),
        "token_out": _token(e.get("token_out") or e.get("asset_out")),
        "amount": amount,
        "amount_out": _f(e.get("amount_out"), amount),
        "timestamp": _i(e.get("timestamp") or e.get("time") or e.get("block_timestamp")),
        "sender": _addr(e.get("sender") or e.get("from") or e.get("from_address")),
        "recipient": _addr(e.get("recipient") or e.get("to") or e.get("to_address")),
        "protocol": str(e.get("protocol") or e.get("service") or e.get("label") or ""),
        "event_type": _event_type(e),
        "raw": e,
    }


def _risk_level(score: int) -> str:
    if score >= 85:
        return "critical"
    if score >= 65:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _score_links(links: list[dict[str, Any]]) -> int:
    if not links:
        return 0
    best = max(_f(l.get("best_confidence")) for l in links)
    high = sum(1 for l in links if _f(l.get("best_confidence")) >= 0.7)
    return min(100, int(best * 70) + min(30, high * 8))


def _typology(code: str, title: str, severity: str, detail: str, confidence: int, evidence: list[str]) -> dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "severity": severity,
        "detail": detail,
        "confidence": confidence,
        "evidence": [x for x in evidence if x],
    }


# ---------------------------------------------------------------------------
# Tornado Cash demixing
# ---------------------------------------------------------------------------
def demix_tornado(
    deposits: list[dict[str, Any]],
    withdrawals: list[dict[str, Any]],
    max_candidates: int = 5,
    time_window_seconds: int = 86_400,
) -> dict[str, Any]:
    """Pair pool deposits to withdrawals by denomination, timing, and address links.

    Each deposit/withdrawal dict may include:
      deposit:    {tx_hash, address(depositor), funder, denomination, timestamp, relayer}
      withdrawal: {tx_hash, recipient, denomination, timestamp, relayer}
    """
    dep = [
        {
            "tx_hash": d.get("tx_hash", ""),
            "depositor": _addr(d.get("address") or d.get("depositor")),
            "funder": _addr(d.get("funder")),
            "denomination": _f(d.get("denomination")),
            "timestamp": _i(d.get("timestamp")),
            "relayer": _addr(d.get("relayer")),
        }
        for d in deposits
    ]

    links = []
    for w in withdrawals:
        w_denom = _f(w.get("denomination"))
        w_time = _i(w.get("timestamp"))
        w_recipient = _addr(w.get("recipient"))
        w_relayer = _addr(w.get("relayer"))

        # anonymity set: deposits of the same denomination that preceded this withdrawal
        prior = [d for d in dep if d["denomination"] == w_denom and 0 < (w_time - d["timestamp"])]
        anon_set = len(prior) or 1

        candidates = []
        for d in prior:
            dt = w_time - d["timestamp"]
            reasons = [f"Same {w_denom} ETH denomination", f"Deposit precedes withdrawal by {dt}s"]
            score = 0.15  # base for a valid same-denomination, time-ordered pair

            if w_recipient and (w_recipient == d["depositor"] or w_recipient == d["funder"]):
                score += 0.45
                reasons.append("Withdrawal recipient matches depositor/funder address (strong link)")
            if w_relayer and d["relayer"] and w_relayer == d["relayer"]:
                score += 0.18
                reasons.append("Same relayer used for deposit and withdrawal")
            if dt <= time_window_seconds:
                score += 0.15
                reasons.append(f"Within {time_window_seconds}s timing window")
            # smaller anonymity set -> higher confidence
            anon_bonus = max(0.0, 0.2 * (1.0 / anon_set))
            score += anon_bonus
            if anon_set <= 3:
                reasons.append(f"Small anonymity set ({anon_set} candidate deposits)")

            candidates.append({
                "deposit_tx": d["tx_hash"],
                "depositor": d["depositor"],
                "deposit_time": d["timestamp"],
                "time_gap_seconds": dt,
                "confidence": round(min(score, 0.97), 4),
                "reasons": reasons,
            })

        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        links.append({
            "withdrawal_tx": w.get("tx_hash", ""),
            "recipient": w_recipient,
            "denomination": w_denom,
            "anonymity_set": anon_set,
            "candidate_count": len(candidates),
            "candidates": candidates[:max_candidates],
            "best_confidence": candidates[0]["confidence"] if candidates else 0.0,
        })

    links.sort(key=lambda l: l["best_confidence"], reverse=True)
    high = [l for l in links if l["best_confidence"] >= 0.6]
    return {
        "method": "tornado_cash_demix",
        "pool": "ethereum",
        "deposits_analyzed": len(dep),
        "withdrawals_analyzed": len(withdrawals),
        "high_confidence_links": len(high),
        "links": links,
        "disclaimer": "Probabilistic leads only. Confirm with funding-source and timing evidence before attribution.",
    }


# ---------------------------------------------------------------------------
# Cross-chain bridge demixing
# ---------------------------------------------------------------------------
def demix_bridge(
    source_events: list[dict[str, Any]],
    dest_events: list[dict[str, Any]],
    value_tolerance: float = 0.01,
    time_window_seconds: int = 21_600,
    max_candidates: int = 5,
) -> dict[str, Any]:
    """Reconcile bridge lock/burn (source) to mint/unlock (destination).

    Events: {tx_hash, chain, token, amount, timestamp, sender, recipient}
    Matches by token + amount within tolerance + destination after source in window.
    """
    src = [
        {
            "tx_hash": s.get("tx_hash", ""),
            "chain": s.get("chain", ""),
            "token": (s.get("token") or "").upper(),
            "amount": _f(s.get("amount")),
            "timestamp": _i(s.get("timestamp")),
            "sender": _addr(s.get("sender")),
            "recipient": _addr(s.get("recipient")),
        }
        for s in source_events
    ]

    links = []
    for s in src:
        cands = []
        for d in dest_events:
            d_token = (d.get("token") or "").upper()
            d_amount = _f(d.get("amount"))
            d_time = _i(d.get("timestamp"))
            d_recipient = _addr(d.get("recipient"))
            dt = d_time - s["timestamp"]
            if dt < 0 or dt > time_window_seconds:
                continue
            if s["token"] and d_token and s["token"] != d_token:
                continue
            denom = max(s["amount"], 1e-9)
            amount_diff = abs(d_amount - s["amount"]) / denom
            if amount_diff > value_tolerance:
                continue

            reasons = [
                f"Amount match within {value_tolerance*100:.2f}% ({s['amount']} vs {d_amount})",
                f"Destination {dt}s after source (within window)",
            ]
            score = 0.4 + 0.3 * (1 - amount_diff / max(value_tolerance, 1e-9))
            score += 0.2 * (1 - dt / max(time_window_seconds, 1))
            if s["token"] and d_token and s["token"] == d_token:
                reasons.append(f"Same asset ({s['token']})")
                score += 0.05
            if s["recipient"] and d_recipient and s["recipient"] == d_recipient:
                reasons.append("Destination recipient matches intended recipient (strong link)")
                score += 0.1

            cands.append({
                "dest_tx": d.get("tx_hash", ""),
                "dest_chain": d.get("chain", ""),
                "dest_recipient": d_recipient,
                "amount": d_amount,
                "time_gap_seconds": dt,
                "amount_diff_pct": round(amount_diff * 100, 4),
                "confidence": round(min(score, 0.97), 4),
                "reasons": reasons,
            })

        cands.sort(key=lambda c: c["confidence"], reverse=True)
        links.append({
            "source_tx": s["tx_hash"],
            "source_chain": s["chain"],
            "token": s["token"],
            "amount": s["amount"],
            "candidate_count": len(cands),
            "candidates": cands[:max_candidates],
            "best_confidence": cands[0]["confidence"] if cands else 0.0,
        })

    links.sort(key=lambda l: l["best_confidence"], reverse=True)
    high = [l for l in links if l["best_confidence"] >= 0.6]
    return {
        "method": "cross_chain_bridge_demix",
        "source_events": len(src),
        "dest_events": len(dest_events),
        "high_confidence_links": len(high),
        "links": links,
        "risk": {
            "score": _score_links(links),
            "level": _risk_level(_score_links(links)),
            "indicator_count": len(high),
        },
        "typologies": [
            _typology(
                "BRIDGE_VALUE_TIME_MATCH",
                "Cross-chain value/time reconciliation",
                "high" if len(high) else "medium",
                "Bridge lock/burn events correlate with destination mint/unlock events by amount, token, and time.",
                min(95, 55 + len(high) * 10),
                [l.get("source_tx", "") for l in high[:5]],
            )
        ] if high else [],
        "disclaimer": "Probabilistic leads only. Bridge batching and identical amounts can produce false pairs; corroborate.",
    }


# ---------------------------------------------------------------------------
# Generic mixer demixing and AML chain-swap detection
# ---------------------------------------------------------------------------
def demix_mixer(
    deposits: list[dict[str, Any]],
    withdrawals: list[dict[str, Any]],
    max_candidates: int = 8,
    time_window_seconds: int = 604_800,
    value_tolerance: float = 0.015,
) -> dict[str, Any]:
    """Generic mixer pool demixing for fixed or near-fixed denomination mixers.

    Supports Tornado-style EVM pools, CoinJoin-like batches, and generic tumbler
    event exports. Input events may include tx_hash, chain, mixer_name, pool,
    token, amount, timestamp, sender/depositor/funder, recipient, relayer.
    """
    dep = []
    for d in deposits:
        ev = _normalise_event(d)
        dep.append({
            **ev,
            "depositor": _addr(d.get("depositor") or d.get("address") or ev["sender"]),
            "funder": _addr(d.get("funder")),
            "mixer_name": str(d.get("mixer_name") or d.get("protocol") or d.get("service") or "Mixer"),
            "pool": str(d.get("pool") or d.get("denomination") or d.get("pool_id") or ""),
        })

    links = []
    for raw_w in withdrawals:
        w = _normalise_event(raw_w)
        w_amount = _f(raw_w.get("denomination"), w["amount"])
        w_token = _token(raw_w.get("token") or raw_w.get("asset") or w["token"])
        w_chain = _chain(raw_w.get("chain") or w["chain"])
        w_pool = str(raw_w.get("pool") or raw_w.get("denomination") or raw_w.get("pool_id") or "")
        w_time = w["timestamp"]
        w_recipient = _addr(raw_w.get("recipient") or w["recipient"])
        w_relayer = _addr(raw_w.get("relayer"))

        prior = []
        for d in dep:
            dt = w_time - d["timestamp"]
            if dt <= 0 or dt > time_window_seconds:
                continue
            if w_chain and d["chain"] and w_chain != d["chain"]:
                continue
            if w_token and d["token"] and w_token != d["token"]:
                continue
            if w_pool and d["pool"] and w_pool != d["pool"]:
                continue
            d_amount = _f(d.get("amount"))
            if w_amount > 0 and d_amount > 0 and _amount_diff(w_amount, d_amount) > value_tolerance:
                continue
            prior.append(d)

        anonymity_set = len(prior) or 1
        candidates = []
        for d in prior:
            dt = w_time - d["timestamp"]
            amount_diff = _amount_diff(w_amount, _f(d.get("amount"))) if w_amount and d.get("amount") else 0.0
            reasons = [
                f"Same mixer pool context ({d['mixer_name']}, {w_token or d['token'] or 'asset unknown'})",
                f"Withdrawal follows deposit by {dt}s",
            ]
            score = 0.22
            score += 0.22 * (1 - min(1, amount_diff / max(value_tolerance, 1e-9)))
            score += 0.16 * (1 - min(1, dt / max(time_window_seconds, 1)))
            if w_pool and d["pool"] and w_pool == d["pool"]:
                score += 0.12
                reasons.append("Same explicit mixer pool/denomination")
            if w_recipient and (w_recipient == d["depositor"] or w_recipient == d["funder"]):
                score += 0.3
                reasons.append("Recipient matches depositor/funder address")
            if w_relayer and _addr(d["raw"].get("relayer")) and w_relayer == _addr(d["raw"].get("relayer")):
                score += 0.1
                reasons.append("Relayer reuse across deposit and withdrawal")
            if anonymity_set <= 5:
                score += 0.12
                reasons.append(f"Small anonymity set ({anonymity_set})")
            elif anonymity_set <= 20:
                score += 0.05
                reasons.append(f"Moderate anonymity set ({anonymity_set})")

            candidates.append({
                "deposit_tx": d["tx_hash"],
                "depositor": d["depositor"],
                "funder": d["funder"],
                "chain": d["chain"],
                "token": d["token"],
                "amount": d["amount"],
                "deposit_time": d["timestamp"],
                "time_gap_seconds": dt,
                "amount_diff_pct": round(amount_diff * 100, 4),
                "confidence": round(min(score, 0.98), 4),
                "reasons": reasons,
            })

        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        links.append({
            "withdrawal_tx": raw_w.get("tx_hash") or raw_w.get("hash") or "",
            "recipient": w_recipient,
            "chain": w_chain,
            "token": w_token,
            "amount": w_amount,
            "pool": w_pool,
            "anonymity_set": anonymity_set,
            "candidate_count": len(candidates),
            "candidates": candidates[:max_candidates],
            "best_confidence": candidates[0]["confidence"] if candidates else 0.0,
        })

    links.sort(key=lambda l: l["best_confidence"], reverse=True)
    high = [l for l in links if l["best_confidence"] >= 0.65]
    risk_score = min(100, _score_links(links) + min(15, len(withdrawals) * 2))
    return {
        "method": "generic_mixer_demix",
        "deposits_analyzed": len(dep),
        "withdrawals_analyzed": len(withdrawals),
        "high_confidence_links": len(high),
        "links": links,
        "risk": {"score": risk_score, "level": _risk_level(risk_score), "indicator_count": len(high)},
        "typologies": [
            _typology(
                "MIXER_LAYERING",
                "Mixer/tumbler layering",
                "critical" if risk_score >= 85 else "high",
                "Deposits and withdrawals correlate across mixer pools by value, timing, pool, and address reuse signals.",
                min(98, 60 + len(high) * 8),
                [l.get("withdrawal_tx", "") for l in high[:5]],
            )
        ] if high else [],
        "disclaimer": "Probabilistic leads only. Mixer anonymity sets and batching can produce false positives; corroborate before attribution.",
    }


def detect_chain_swaps(
    events: list[dict[str, Any]],
    value_tolerance: float = 0.035,
    time_window_seconds: int = 43_200,
    max_candidates: int = 25,
) -> dict[str, Any]:
    """Detect chain hopping plus asset swapping used for laundering layering."""
    evs = sorted([_normalise_event(e) for e in events], key=lambda e: e["timestamp"] or 0)
    bridge_like = [e for e in evs if e["event_type"] in {"bridge", "mixer_withdrawal", "mixer"}]
    swap_like = [e for e in evs if e["event_type"] == "swap" or (e["token_out"] and e["token_out"] != e["token"])]
    transfer_like = [e for e in evs if e not in bridge_like and e not in swap_like]

    findings: list[dict[str, Any]] = []
    for src in bridge_like + transfer_like:
        if src["timestamp"] <= 0 or src["amount"] <= 0:
            continue
        candidates = []
        for dst in swap_like + bridge_like + transfer_like:
            if dst is src or dst["timestamp"] <= src["timestamp"]:
                continue
            dt = dst["timestamp"] - src["timestamp"]
            if dt > time_window_seconds:
                continue
            chain_changed = bool(src["chain"] and dst["chain"] and src["chain"] != dst["chain"])
            declared_dest = bool(src["dest_chain"] and dst["chain"] and src["dest_chain"] == dst["chain"])
            if not chain_changed and not declared_dest:
                continue
            amount_diff = _amount_diff(src["amount"], dst["amount"])
            if amount_diff > value_tolerance:
                continue
            token_changed = bool(dst["token_out"] and dst["token_out"] != (src["token"] or dst["token"]))
            stable_shuffle = (src["token"] in _STABLECOINS and (dst["token"] in _STABLECOINS or dst["token_out"] in _STABLECOINS))
            wrapped = src["token"] in _WRAPPED_ASSETS or dst["token"] in _WRAPPED_ASSETS or dst["token_out"] in _WRAPPED_ASSETS
            same_party = bool(src["recipient"] and (src["recipient"] == dst["sender"] or src["recipient"] == dst["recipient"]))

            reasons = [
                f"Cross-chain value match {src['chain'] or '?'} to {dst['chain'] or src['dest_chain'] or '?'}",
                f"Time gap {dt}s, value delta {amount_diff * 100:.2f}%",
            ]
            score = 0.38
            score += 0.22 * (1 - amount_diff / max(value_tolerance, 1e-9))
            score += 0.16 * (1 - dt / max(time_window_seconds, 1))
            if token_changed:
                score += 0.1
                reasons.append(f"Asset converted {src['token'] or '?'} to {dst['token_out']}")
            if stable_shuffle:
                score += 0.08
                reasons.append("Stablecoin chain-swap pattern")
            if wrapped:
                score += 0.06
                reasons.append("Wrapped/bridged asset indicator")
            if same_party:
                score += 0.1
                reasons.append("Recipient/sender continuity across legs")
            if src["event_type"] in {"mixer", "mixer_withdrawal"}:
                score += 0.12
                reasons.append("Mixer withdrawal precedes chain movement")

            candidates.append({
                "dest_tx": dst["tx_hash"],
                "dest_chain": dst["chain"],
                "dest_token": dst["token"],
                "dest_token_out": dst["token_out"],
                "dest_protocol": dst["protocol"],
                "time_gap_seconds": dt,
                "amount_diff_pct": round(amount_diff * 100, 4),
                "confidence": round(min(score, 0.98), 4),
                "reasons": reasons,
            })

        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        if candidates:
            best = candidates[0]
            findings.append({
                "source_tx": src["tx_hash"],
                "source_chain": src["chain"],
                "source_token": src["token"],
                "source_amount": src["amount"],
                "source_protocol": src["protocol"],
                "source_event_type": src["event_type"],
                "candidate_count": len(candidates),
                "best_confidence": best["confidence"],
                "candidates": candidates[:max_candidates],
            })

    findings.sort(key=lambda f: f["best_confidence"], reverse=True)
    high = [f for f in findings if f["best_confidence"] >= 0.68]
    chains = sorted({e["chain"] for e in evs if e["chain"]} | {e["dest_chain"] for e in evs if e["dest_chain"]})
    protocols = sorted({e["protocol"] for e in evs if e["protocol"]})
    hop_score = min(100, int((max([f["best_confidence"] for f in findings], default=0) * 72)) + min(28, len(high) * 7))
    typologies = []
    if high:
        typologies.append(_typology(
            "CHAIN_SWAP_LAYERING",
            "Chain-swap layering",
            "critical" if hop_score >= 85 else "high",
            "Funds appear to move across chains and convert assets within value/time tolerances.",
            min(98, 62 + len(high) * 7),
            [f.get("source_tx", "") for f in high[:5]],
        ))
    if len(chains) >= 3:
        typologies.append(_typology(
            "MULTI_CHAIN_HOPPING",
            "Multi-chain hopping",
            "high",
            f"Activity spans {len(chains)} chains: {', '.join(chains[:8])}.",
            min(95, 55 + len(chains) * 8),
            chains[:8],
        ))

    return {
        "method": "chain_swap_laundering_detection",
        "events_analyzed": len(evs),
        "chain_swap_count": len(findings),
        "high_confidence_links": len(high),
        "links": findings,
        "chains_involved": chains,
        "protocols_seen": protocols,
        "risk": {
            "score": hop_score,
            "level": _risk_level(hop_score),
            "indicator_count": len(high),
            "chain_count": len(chains),
        },
        "typologies": typologies,
        "disclaimer": "Chain-swap findings are laundering indicators, not identity attribution. Validate against raw transactions and bridge receipts.",
    }


def analyze_laundering(
    deposits: list[dict[str, Any]] | None = None,
    withdrawals: list[dict[str, Any]] | None = None,
    source_events: list[dict[str, Any]] | None = None,
    dest_events: list[dict[str, Any]] | None = None,
    chain_events: list[dict[str, Any]] | None = None,
    value_tolerance: float = 0.025,
    time_window_seconds: int = 86_400,
    max_candidates: int = 8,
) -> dict[str, Any]:
    deposits = deposits or []
    withdrawals = withdrawals or []
    source_events = source_events or []
    dest_events = dest_events or []
    chain_events = chain_events or []

    mixer = demix_mixer(deposits, withdrawals, max_candidates, time_window_seconds, value_tolerance) if withdrawals else None
    bridge = demix_bridge(source_events, dest_events, value_tolerance, time_window_seconds, max_candidates) if source_events and dest_events else None
    chain_swaps = detect_chain_swaps(chain_events + source_events + dest_events, value_tolerance * 1.4, time_window_seconds, max_candidates)

    components = [x for x in (mixer, bridge, chain_swaps) if x]
    component_scores = [_i((c.get("risk") or {}).get("score")) for c in components]
    score = min(100, max(component_scores or [0]) + min(28, sum(1 for s in component_scores if s >= 50) * 9))
    typologies = []
    for c in components:
        typologies.extend(c.get("typologies") or [])

    if mixer and chain_swaps.get("high_confidence_links", 0):
        score = min(100, score + 12)
        typologies.append(_typology(
            "MIXER_TO_CHAIN_SWAP",
            "Mixer exit followed by chain-swap",
            "critical",
            "Mixer-linked funds are followed by cross-chain movement or asset conversion, a high-value layering pattern.",
            min(99, score),
            [l.get("withdrawal_tx", "") for l in (mixer.get("links") or [])[:3]],
        ))

    return {
        "method": "aml_laundering_detection",
        "risk": {
            "score": score,
            "level": _risk_level(score),
            "component_count": len(components),
            "typology_count": len(typologies),
        },
        "summary": (
            f"AML score {score}/100 ({_risk_level(score)}): "
            f"{len(typologies)} typology indicator(s), "
            f"{chain_swaps.get('chain_swap_count', 0)} chain-swap candidate(s)."
        ),
        "components": {
            "mixer": mixer,
            "bridge": bridge,
            "chain_swaps": chain_swaps,
        },
        "typologies": typologies,
        "recommended_actions": [
            "Validate top candidate transaction pairs in the source explorer or indexer.",
            "Compare gas funders, relayers, wallet creation times, and destination cash-out services.",
            "Preserve raw transaction receipts and bridge/mixer event logs as evidence.",
            "Treat high-confidence links as investigative leads until corroborated by independent signals.",
        ],
        "disclaimer": "This engine detects laundering typologies and correlation leads. It does not prove beneficial ownership or intent by itself.",
    }


if __name__ == "__main__":
    out = demix_tornado(
        deposits=[
            {"tx_hash": "0xd1", "address": "0xaaa", "denomination": 1.0, "timestamp": 1000, "relayer": "0xr"},
            {"tx_hash": "0xd2", "address": "0xbbb", "denomination": 1.0, "timestamp": 1100},
        ],
        withdrawals=[{"tx_hash": "0xw1", "recipient": "0xaaa", "denomination": 1.0, "timestamp": 2000, "relayer": "0xr"}],
    )
    print("TC best:", out["links"][0]["candidates"][0]["confidence"], out["links"][0]["candidates"][0]["reasons"])
    b = demix_bridge(
        source_events=[{"tx_hash": "0xs", "chain": "eth", "token": "USDC", "amount": 100000, "timestamp": 1000, "recipient": "0xz"}],
        dest_events=[{"tx_hash": "0xd", "chain": "bsc", "token": "USDC", "amount": 100000, "timestamp": 1300, "recipient": "0xz"}],
    )
    print("Bridge best:", b["links"][0]["candidates"][0]["confidence"])
