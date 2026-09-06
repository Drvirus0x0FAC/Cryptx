#!/usr/bin/env python3
"""
crypto_footprint.py — On-chain behavioral footprinting for the Stage 08 bot.

Extracts deterministic transaction fingerprints from a crypto address intel dict
(produced by crypto_osint.lookup_crypto_address) and sends the condensed
fingerprint profile to DeepSeek for deep behavioral analysis, cross-chain
correlation, and de-anonymization leads.

No additional API keys required — uses the existing AI backend configured in
ai_analyst.py (DeepSeek / Ollama / OpenRouter) plus on-chain data already
fetched by crypto_osint.

Public API:
    extract_fingerprint(intel)         -> dict  (deterministic, instant)
    analyze_footprint(intel)           -> dict  (async, calls AI)
    format_footprint_inline_html(fp)   -> str   (Telegram HTML for chat)
    format_footprint_report_html(fp)   -> str   (full HTML section for report)
"""

from __future__ import annotations

import json
import re
import math
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("crypto_footprint")

# Import AI backend from existing module
try:
    from ai_analyst import _ollama_generate, _safe_json, AI_ENABLED, CRYPTO_SYSTEM_PROMPT
except ImportError:
    AI_ENABLED = False
    CRYPTO_SYSTEM_PROMPT = ""
    async def _ollama_generate(*a, **kw):  # type: ignore
        return None
    def _safe_json(raw):  # type: ignore
        return {}


# ── Known bridge / cross-chain infrastructure ─────────────────────────────────
KNOWN_BRIDGES: Dict[str, str] = {
    # ETH bridges
    "0x3ee18b2214aff97000d974cf647e7c347e8fa585": "Wormhole: ETH",
    "0x40ec5b33f54e0e8a33a975908c5ba1c14e5bbbdf": "Polygon: PoS Bridge",
    "0xa0c68c638235ee32657e8f720a23cec1bfc6492a": "Polygon: Plasma Bridge",
    "0x3014ca10b91cb3d0ad85fef7a3cb95bcac9c0f79": "Faust: FLR Bridge",
    "0x99c9fc46f92e8a1c0dec1b1747d010903e884be1": "Optimism: Gateway",
    "0x4dbd4fc535ac27206064b68ffcf827b0a60bab3f": "Arbitrum: Delayed Inbox",
    "0x011b6e24ffb0b5f5fcc564cf4183c5bbbc96d515": "Across: Bridge",
    "0x5427fefa711eff984124bfbb1ab6fbf5e3da1820": "Synapse: Bridge",
    "0x2796317b0ff8538f253012862c06787adfb8ceb6": "Synapse: Bridge v2",
    "0x737b7867d945e5c24ba47cfa5d68e4b0de230550": "Ronin: Bridge",
    # TRX
    "TLMViQX5bsCiDfBXgATU1Fwe7WfA1rDoWU": "Sun.io: Bridge",
}

# ── Known DEX routers ────────────────────────────────────────────────────────
KNOWN_DEXES: Dict[str, str] = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2 Router",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3 Router",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap: Universal Router",
    "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b": "Uniswap: Universal Router 2",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch V5 Router",
    "0x1111111254fb6c44bac0bed2854e76f90643097d": "1inch V4 Router",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x: Exchange Proxy",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": "SushiSwap Router",
    "0x10ed43c718714eb63d5aa57b78b54704e256024e": "PancakeSwap V2 Router",
}


# ═════════════════════════════════════════════════════════════════════════════
# DETERMINISTIC FINGERPRINT EXTRACTION
# ═════════════════════════════════════════════════════════════════════════════

def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Best-effort parse of a timestamp string."""
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(ts_str[:19], fmt[:min(len(fmt), 19)]).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    # Unix timestamp fallback
    try:
        n = float(ts_str)
        if n > 1e12:
            n /= 1000
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except (ValueError, TypeError):
        return None


def _is_round(amount: float) -> bool:
    """Check if an amount looks like a round number (1, 5, 10, 100, 0.5, 0.1 etc)."""
    if amount <= 0:
        return False
    # Check if it's a clean multiple of common denominations
    for denom in (1, 5, 10, 25, 50, 100, 500, 1000, 0.1, 0.5, 0.01, 0.05):
        ratio = amount / denom
        if abs(ratio - round(ratio)) < 0.0001 and ratio >= 1:
            return True
    return False


def extract_fingerprint(intel: dict) -> dict:
    """
    Extract deterministic behavioral fingerprints from on-chain data.
    Pure computation — no API calls, instant execution.
    """
    txs = intel.get("recent_txs") or []
    address = (intel.get("address") or "").lower()
    chain = intel.get("chain") or "?"
    tokens = intel.get("tokens") or []

    fp: Dict[str, Any] = {
        "chain": chain,
        "address": intel.get("address") or "",
        "balance": intel.get("balance"),
        "balance_unit": intel.get("balance_unit") or "",
        "tx_count": intel.get("tx_count") or len(txs),
        "first_seen": intel.get("first_seen") or "",
        "last_seen": intel.get("last_seen") or "",
        "tokens_held": [t.get("token") for t in tokens if t.get("balance", 0) > 0],
        "arkham_entity": None,
        "sanctions": intel.get("sanctions") or {},
    }

    # Arkham attribution
    arkham = intel.get("arkham") or {}
    if arkham.get("found"):
        fp["arkham_entity"] = {
            "name": arkham.get("name") or arkham.get("entity_name"),
            "type": arkham.get("entity_type"),
            "label": arkham.get("label"),
        }

    if not txs:
        fp["timing"] = {}
        fp["amounts"] = {}
        fp["counterparties"] = {}
        fp["flow"] = {}
        fp["cross_chain"] = {}
        fp["velocity"] = {}
        return fp

    # ── Timing fingerprint ────────────────────────────────────────────────────
    hours = []
    days_of_week = []
    timestamps = []
    for tx in txs:
        dt = _parse_ts(tx.get("time") or "")
        if dt:
            hours.append(dt.hour)
            days_of_week.append(dt.strftime("%A"))
            timestamps.append(dt)

    hour_dist = dict(Counter(hours).most_common())
    dow_dist = dict(Counter(days_of_week).most_common())

    # Estimate timezone from peak activity hours
    peak_hours = [h for h, _ in Counter(hours).most_common(3)] if hours else []
    tz_estimate = None
    if peak_hours:
        avg_peak = sum(peak_hours) / len(peak_hours)
        # If peak is 9-17 UTC, likely UTC+0. If 17-1, likely UTC-8. Etc.
        if 9 <= avg_peak <= 17:
            tz_estimate = "UTC+0 to UTC+2 (Europe/Africa)"
        elif 1 <= avg_peak <= 9:
            tz_estimate = "UTC+5 to UTC+9 (Asia/Middle East)"
        elif 17 <= avg_peak <= 23:
            tz_estimate = "UTC-8 to UTC-5 (Americas)"
        else:
            tz_estimate = "UTC-5 to UTC+0 (Americas/Europe)"

    fp["timing"] = {
        "hour_distribution": hour_dist,
        "day_of_week_distribution": dow_dist,
        "peak_hours_utc": peak_hours,
        "estimated_timezone": tz_estimate,
        "total_timestamps_parsed": len(timestamps),
    }

    # ── Amount fingerprint ────────────────────────────────────────────────────
    amounts_out = []
    amounts_in = []
    all_amounts = []
    gas_prices = []

    for tx in txs:
        val = tx.get("value") or tx.get("amount") or 0
        try:
            val = abs(float(val))
        except (TypeError, ValueError):
            val = 0
        if val <= 0:
            continue
        all_amounts.append(val)
        direction = (tx.get("direction") or "").upper()
        if direction == "OUT":
            amounts_out.append(val)
        elif direction == "IN":
            amounts_in.append(val)

        # Gas price (ETH-like chains)
        gp = tx.get("gas_price") or tx.get("gasPrice")
        if gp:
            try:
                gas_prices.append(float(gp))
            except (TypeError, ValueError):
                pass

    round_count = sum(1 for a in all_amounts if _is_round(a))
    round_ratio = round_count / len(all_amounts) if all_amounts else 0

    # Amount clustering — find the most common amount ranges
    amount_ranges = Counter()
    for a in all_amounts:
        if a < 0.01:
            amount_ranges["dust (<0.01)"] += 1
        elif a < 1:
            amount_ranges["small (0.01-1)"] += 1
        elif a < 10:
            amount_ranges["medium (1-10)"] += 1
        elif a < 100:
            amount_ranges["large (10-100)"] += 1
        elif a < 1000:
            amount_ranges["very large (100-1K)"] += 1
        else:
            amount_ranges["whale (1K+)"] += 1

    fp["amounts"] = {
        "total_txs_with_value": len(all_amounts),
        "total_out": len(amounts_out),
        "total_in": len(amounts_in),
        "avg_amount": round(sum(all_amounts) / len(all_amounts), 6) if all_amounts else 0,
        "median_amount": round(sorted(all_amounts)[len(all_amounts) // 2], 6) if all_amounts else 0,
        "max_amount": round(max(all_amounts), 6) if all_amounts else 0,
        "min_amount": round(min(all_amounts), 6) if all_amounts else 0,
        "round_number_ratio": round(round_ratio, 2),
        "amount_distribution": dict(amount_ranges),
        "avg_gas_price_gwei": round(sum(gas_prices) / len(gas_prices) / 1e9, 2) if gas_prices else None,
    }

    # ── Counterparty fingerprint ──────────────────────────────────────────────
    counterparty_out = Counter()  # addresses we send TO
    counterparty_in = Counter()   # addresses that send TO us
    bridge_interactions = []
    dex_interactions = []

    for tx in txs:
        tx_from = (tx.get("from") or "").lower()
        tx_to = (tx.get("to") or "").lower()

        if tx_from == address and tx_to:
            counterparty_out[tx_to] += 1
            # Check bridges/DEXes
            for known, name in {**KNOWN_BRIDGES, **KNOWN_DEXES}.items():
                if tx_to == known.lower():
                    if known.lower() in [k.lower() for k in KNOWN_BRIDGES]:
                        bridge_interactions.append({"bridge": name, "direction": "OUT", "tx": tx.get("hash", "")[:16]})
                    else:
                        dex_interactions.append({"dex": name, "direction": "OUT", "tx": tx.get("hash", "")[:16]})
        elif tx_to == address and tx_from:
            counterparty_in[tx_from] += 1
            for known, name in {**KNOWN_BRIDGES, **KNOWN_DEXES}.items():
                if tx_from == known.lower():
                    if known.lower() in [k.lower() for k in KNOWN_BRIDGES]:
                        bridge_interactions.append({"bridge": name, "direction": "IN", "tx": tx.get("hash", "")[:16]})
                    else:
                        dex_interactions.append({"dex": name, "direction": "IN", "tx": tx.get("hash", "")[:16]})

    # Repeat counterparties (interacted >1 time)
    repeat_out = {addr: cnt for addr, cnt in counterparty_out.items() if cnt > 1}
    repeat_in = {addr: cnt for addr, cnt in counterparty_in.items() if cnt > 1}

    fp["counterparties"] = {
        "unique_outgoing": len(counterparty_out),
        "unique_incoming": len(counterparty_in),
        "top_outgoing": [{"address": a[:20] + "…", "count": c} for a, c in counterparty_out.most_common(5)],
        "top_incoming": [{"address": a[:20] + "…", "count": c} for a, c in counterparty_in.most_common(5)],
        "repeat_counterparties": len(repeat_out) + len(repeat_in),
        "one_time_counterparties": len(counterparty_out) + len(counterparty_in) - len(repeat_out) - len(repeat_in),
    }

    # ── Flow fingerprint ──────────────────────────────────────────────────────
    total_out_val = sum(amounts_out) if amounts_out else 0
    total_in_val = sum(amounts_in) if amounts_in else 0
    in_out_ratio = round(total_in_val / total_out_val, 3) if total_out_val > 0 else None

    fp["flow"] = {
        "total_outflow": round(total_out_val, 6),
        "total_inflow": round(total_in_val, 6),
        "net_flow": round(total_in_val - total_out_val, 6),
        "in_out_ratio": in_out_ratio,
        "flow_pattern": (
            "accumulator" if (in_out_ratio and in_out_ratio > 2) else
            "distributor" if (in_out_ratio and in_out_ratio < 0.5) else
            "pass-through" if (in_out_ratio and 0.8 <= in_out_ratio <= 1.2) else
            "mixed"
        ),
    }

    # ── Cross-chain indicators ────────────────────────────────────────────────
    fp["cross_chain"] = {
        "bridge_interactions": bridge_interactions[:10],
        "dex_interactions": dex_interactions[:10],
        "bridge_count": len(bridge_interactions),
        "dex_count": len(dex_interactions),
        "cross_chain_active": len(bridge_interactions) > 0,
    }

    # ── Activity velocity ─────────────────────────────────────────────────────
    if len(timestamps) >= 2:
        timestamps.sort()
        total_span_hours = (timestamps[-1] - timestamps[0]).total_seconds() / 3600
        intervals = [(timestamps[i+1] - timestamps[i]).total_seconds() / 3600
                      for i in range(len(timestamps) - 1)]
        avg_interval = sum(intervals) / len(intervals) if intervals else 0
        min_interval = min(intervals) if intervals else 0
        max_interval = max(intervals) if intervals else 0

        # Detect burst patterns (cluster of txs within 1 hour)
        burst_count = sum(1 for iv in intervals if iv < 1)

        fp["velocity"] = {
            "observation_window_hours": round(total_span_hours, 1),
            "txs_per_day": round(len(timestamps) / max(total_span_hours / 24, 0.01), 2),
            "avg_interval_hours": round(avg_interval, 2),
            "min_interval_hours": round(min_interval, 2),
            "max_interval_hours": round(max_interval, 2),
            "burst_transactions": burst_count,
            "activity_pattern": (
                "burst" if burst_count > len(intervals) * 0.5 else
                "regular" if max_interval < avg_interval * 3 else
                "sporadic"
            ),
        }
    else:
        fp["velocity"] = {"observation_window_hours": 0, "txs_per_day": 0}

    # ── Mixer interaction summary (from crypto_osint) ─────────────────────────
    mixer_hits = intel.get("mixer_hits") or []
    fp["mixer_interactions"] = len(mixer_hits)

    return fp


# ═════════════════════════════════════════════════════════════════════════════
# AI ANALYSIS — DeepSeek footprint profiling
# ═════════════════════════════════════════════════════════════════════════════

_FOOTPRINT_SYSTEM = (
    "You are an elite blockchain forensics analyst specializing in wallet "
    "behavioral fingerprinting and de-anonymization. You receive a structured "
    "behavioral fingerprint extracted from on-chain transaction data for a "
    "cryptocurrency address.\n\n"
    "Your mission:\n"
    "1. Build a BEHAVIORAL SIGNATURE for this wallet — a unique profile that "
    "   could identify the same operator across different addresses or chains.\n"
    "2. Analyze TIMING PATTERNS to estimate the operator's timezone, work "
    "   schedule, and whether this is automated (bot) or human-operated.\n"
    "3. Analyze AMOUNT PATTERNS to determine if the operator uses round "
    "   numbers (manual), precise amounts (automated/contract), or structured "
    "   amounts (layering/smurfing below thresholds).\n"
    "4. Analyze COUNTERPARTY RELATIONSHIPS to identify exchange deposits, "
    "   OTC dealings, business relationships, or criminal infrastructure.\n"
    "5. Analyze FLOW PATTERNS to classify the wallet role: accumulator, "
    "   distributor, pass-through, mixer, exchange hot wallet, personal, "
    "   or operational (ransomware C2, scam collection, etc).\n"
    "6. Identify CROSS-CHAIN FOOTPRINT — bridge and DEX usage that reveals "
    "   multi-chain activity and potential chain-hopping evasion.\n"
    "7. Flag OPSEC WEAKNESSES that could aid attribution: address reuse, "
    "   timing regularity, gas price habits, distinctive amount patterns.\n"
    "8. Generate OWNERSHIP HYPOTHESES — who might operate this wallet, "
    "   based on behavioral evidence.\n"
    "9. Suggest CROSS-CHAIN PIVOT ADDRESSES to investigate — addresses on "
    "   other chains that might belong to the same operator.\n\n"
    "CRITICAL: Base EVERY claim on evidence from the fingerprint data. "
    "NEVER fabricate addresses, hashes, or amounts not present in the input. "
    "If Arkham entity attribution is present, treat it as authoritative.\n\n"
    "When asked for JSON, output STRICT JSON only — no prose, no markdown "
    "fences, no explanation before or after the JSON object."
)


async def analyze_footprint(intel: dict) -> dict:
    """
    Extract fingerprints and send to DeepSeek for deep behavioral analysis.
    Returns a structured dict with the AI's footprint assessment.
    """
    if not AI_ENABLED:
        return {"skipped": True, "reason": "AI disabled"}

    fp = extract_fingerprint(intel)

    # Build compact payload for the AI (strip raw addresses for token limit)
    compact_fp = {k: v for k, v in fp.items() if k != "address"}
    compact_fp["address_prefix"] = fp["address"][:20] + "…" if len(fp.get("address", "")) > 20 else fp.get("address", "")

    prompt = (
        "Analyze this wallet's behavioral fingerprint and produce a comprehensive "
        "footprint assessment. Output STRICT JSON:\n"
        "{\n"
        '  "behavioral_signature": {\n'
        '    "operator_type": "human|bot|hybrid|unknown",\n'
        '    "operator_type_evidence": [],\n'
        '    "estimated_timezone": "",\n'
        '    "timezone_confidence": "high|medium|low",\n'
        '    "timezone_evidence": "",\n'
        '    "activity_schedule": "business_hours|24_7|night_owl|irregular",\n'
        '    "sophistication": "novice|intermediate|advanced|professional",\n'
        '    "sophistication_evidence": ""\n'
        "  },\n"
        '  "wallet_classification": {\n'
        '    "primary_role": "personal|exchange|mixer|service|contract|scam|ransomware|darknet|otc|unknown",\n'
        '    "confidence": "high|medium|low",\n'
        '    "evidence": [],\n'
        '    "secondary_roles": []\n'
        "  },\n"
        '  "amount_behavior": {\n'
        '    "pattern": "round_numbers|precise|structured|mixed",\n'
        '    "structuring_detected": false,\n'
        '    "structuring_evidence": "",\n'
        '    "notable_amounts": []\n'
        "  },\n"
        '  "counterparty_profile": {\n'
        '    "relationship_type": "exchange_user|p2p_trader|service_operator|mixer_user|unknown",\n'
        '    "key_relationships": [{"counterparty": "", "relationship": "", "evidence": ""}],\n'
        '    "exchange_deposits_likely": false,\n'
        '    "otc_activity_likely": false\n'
        "  },\n"
        '  "cross_chain_assessment": {\n'
        '    "multi_chain_operator": false,\n'
        '    "chains_likely_active": [],\n'
        '    "evasion_technique": "",\n'
        '    "pivot_addresses": [{"chain": "", "address_hint": "", "reason": ""}]\n'
        "  },\n"
        '  "opsec_weaknesses": [\n'
        '    {"weakness": "", "severity": "low|medium|high|critical", "exploitation": ""}\n'
        "  ],\n"
        '  "ownership_hypotheses": [\n'
        '    {"hypothesis": "", "confidence": "high|medium|low", "evidence": []}\n'
        "  ],\n"
        '  "risk_assessment": {\n'
        '    "overall_risk": "low|medium|high|critical",\n'
        '    "risk_factors": [],\n'
        '    "law_enforcement_relevance": "low|medium|high"\n'
        "  },\n"
        '  "investigation_pivots": [\n'
        '    {"action": "", "target": "", "reason": "", "priority": "high|medium|low"}\n'
        "  ]\n"
        "}\n\n"
        f"FINGERPRINT DATA:\n{json.dumps(compact_fp, ensure_ascii=False, default=str)}"
    )

    raw = await _ollama_generate(prompt, json_mode=True, system_prompt=_FOOTPRINT_SYSTEM)
    ai_result = _safe_json(raw)

    return {
        "fingerprint": fp,
        "ai_analysis": ai_result,
    }


# ═════════════════════════════════════════════════════════════════════════════
# FORMATTERS
# ═════════════════════════════════════════════════════════════════════════════

def _esc(x: Any) -> str:
    return escape("" if x is None else str(x))


def format_footprint_inline_html(result: dict) -> str:
    """Compact Telegram HTML for chat inline display."""
    if result.get("skipped"):
        return ""

    fp = result.get("fingerprint") or {}
    ai = result.get("ai_analysis") or {}

    lines = ["<b>🔬 Wallet Footprint Analysis</b>"]

    # Behavioral signature
    sig = ai.get("behavioral_signature") or {}
    if sig:
        lines.append("")
        lines.append("<b>🧬 Behavioral Signature</b>")
        if sig.get("operator_type"):
            lines.append(f"• Operator: <b>{_esc(sig['operator_type'])}</b>")
        if sig.get("estimated_timezone"):
            lines.append(f"• Timezone: {_esc(sig['estimated_timezone'])} ({_esc(sig.get('timezone_confidence',''))})")
        if sig.get("activity_schedule"):
            lines.append(f"• Schedule: {_esc(sig['activity_schedule'])}")
        if sig.get("sophistication"):
            lines.append(f"• Sophistication: <b>{_esc(sig['sophistication'])}</b>")

    # Wallet classification
    wc = ai.get("wallet_classification") or {}
    if wc:
        lines.append("")
        lines.append("<b>🏷️ Wallet Classification</b>")
        if wc.get("primary_role"):
            lines.append(f"• Role: <b>{_esc(wc['primary_role'])}</b> ({_esc(wc.get('confidence',''))})")
        for ev in (wc.get("evidence") or [])[:3]:
            lines.append(f"  ◦ <i>{_esc(str(ev)[:120])}</i>")

    # Amount behavior
    ab = ai.get("amount_behavior") or {}
    if ab and ab.get("pattern"):
        lines.append("")
        lines.append(f"<b>💰 Amount Pattern:</b> {_esc(ab['pattern'])}")
        if ab.get("structuring_detected"):
            lines.append(f"  ⚠️ <b>Structuring detected:</b> {_esc(ab.get('structuring_evidence','')[:150])}")

    # Cross-chain
    cc = ai.get("cross_chain_assessment") or {}
    if cc.get("multi_chain_operator"):
        lines.append("")
        lines.append("<b>🌐 Cross-Chain Activity</b>")
        chains = cc.get("chains_likely_active") or []
        if chains:
            lines.append(f"• Active chains: {_esc(', '.join(str(c) for c in chains))}")
        if cc.get("evasion_technique"):
            lines.append(f"• Evasion: <i>{_esc(str(cc['evasion_technique'])[:150])}</i>")

    # OPSEC weaknesses
    opsec = ai.get("opsec_weaknesses") or []
    if opsec:
        lines.append("")
        lines.append("<b>🎯 OPSEC Weaknesses</b>")
        for w in opsec[:4]:
            sev = w.get("severity", "")
            icon = "🔴" if sev == "critical" else "🟠" if sev == "high" else "🟡" if sev == "medium" else "🔵"
            lines.append(f"• {icon} {_esc(str(w.get('weakness',''))[:120])}")

    # Ownership hypotheses
    hyps = ai.get("ownership_hypotheses") or []
    if hyps:
        lines.append("")
        lines.append("<b>👤 Ownership Hypotheses</b>")
        for h in hyps[:3]:
            lines.append(f"• <b>{_esc(str(h.get('hypothesis',''))[:120])}</b> ({_esc(h.get('confidence',''))})")

    # Risk
    risk = ai.get("risk_assessment") or {}
    if risk.get("overall_risk"):
        lines.append("")
        lines.append(f"<b>⚡ Risk:</b> <b>{_esc(risk['overall_risk']).upper()}</b>")

    # Investigation pivots
    pivots = ai.get("investigation_pivots") or []
    if pivots:
        lines.append("")
        lines.append("<b>🔍 Next Steps</b>")
        for p in pivots[:4]:
            lines.append(f"• [{_esc(p.get('priority',''))}] {_esc(str(p.get('action',''))[:120])}")

    return "\n".join(lines)


def format_footprint_report_html(result: dict) -> str:
    """Full HTML section for embedding in the crypto threat report."""
    if result.get("skipped"):
        return ""

    fp = result.get("fingerprint") or {}
    ai = result.get("ai_analysis") or {}

    def _kv_row(label: str, value: Any) -> str:
        if value is None or value == "":
            return ""
        return f'<div class="kv"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'

    parts = ['<section class="section ai-section"><h2>🔬 Wallet Footprint Analysis</h2>']

    # ── Deterministic fingerprint summary ─────────────────────────────────────
    parts.append('<h3>📊 Extracted Fingerprint</h3><div class="detail-grid">')
    timing = fp.get("timing") or {}
    amounts = fp.get("amounts") or {}
    cps = fp.get("counterparties") or {}
    flow = fp.get("flow") or {}
    vel = fp.get("velocity") or {}
    xc = fp.get("cross_chain") or {}

    parts.append(_kv_row("Peak Hours (UTC)", ", ".join(str(h) for h in (timing.get("peak_hours_utc") or []))))
    parts.append(_kv_row("Estimated Timezone", timing.get("estimated_timezone")))
    parts.append(_kv_row("Round Number Ratio", f"{amounts.get('round_number_ratio', 0):.0%}"))
    parts.append(_kv_row("Avg Amount", amounts.get("avg_amount")))
    parts.append(_kv_row("Unique Outgoing", cps.get("unique_outgoing")))
    parts.append(_kv_row("Unique Incoming", cps.get("unique_incoming")))
    parts.append(_kv_row("Repeat Counterparties", cps.get("repeat_counterparties")))
    parts.append(_kv_row("Flow Pattern", flow.get("flow_pattern")))
    parts.append(_kv_row("In/Out Ratio", flow.get("in_out_ratio")))
    parts.append(_kv_row("Txs/Day", vel.get("txs_per_day")))
    parts.append(_kv_row("Activity Pattern", vel.get("activity_pattern")))
    parts.append(_kv_row("Bridge Interactions", xc.get("bridge_count")))
    parts.append(_kv_row("DEX Interactions", xc.get("dex_count")))
    parts.append(_kv_row("Mixer Interactions", fp.get("mixer_interactions", 0)))
    parts.append("</div>")

    # ── AI analysis sections ──────────────────────────────────────────────────
    sig = ai.get("behavioral_signature") or {}
    if sig:
        parts.append("<h3>🧬 Behavioral Signature</h3><div class='detail-grid'>")
        parts.append(_kv_row("Operator Type", sig.get("operator_type")))
        parts.append(_kv_row("Timezone", sig.get("estimated_timezone")))
        parts.append(_kv_row("TZ Confidence", sig.get("timezone_confidence")))
        parts.append(_kv_row("Schedule", sig.get("activity_schedule")))
        parts.append(_kv_row("Sophistication", sig.get("sophistication")))
        parts.append("</div>")
        for ev in (sig.get("operator_type_evidence") or [])[:5]:
            parts.append(f"<p class='muted'>• {escape(str(ev)[:200])}</p>")

    wc = ai.get("wallet_classification") or {}
    if wc:
        parts.append("<h3>🏷️ Wallet Classification</h3><div class='detail-grid'>")
        parts.append(_kv_row("Primary Role", wc.get("primary_role")))
        parts.append(_kv_row("Confidence", wc.get("confidence")))
        parts.append("</div>")
        for ev in (wc.get("evidence") or [])[:5]:
            parts.append(f"<p class='muted'>• {escape(str(ev)[:200])}</p>")

    opsec = ai.get("opsec_weaknesses") or []
    if opsec:
        parts.append("<h3>🎯 OPSEC Weaknesses</h3>")
        parts.append('<div class="table-wrap"><table><thead><tr><th>Weakness</th><th>Severity</th><th>How to Exploit</th></tr></thead><tbody>')
        for w in opsec[:8]:
            parts.append(
                f'<tr><td>{escape(str(w.get("weakness",""))[:200])}</td>'
                f'<td>{escape(str(w.get("severity","")))}</td>'
                f'<td>{escape(str(w.get("exploitation",""))[:200])}</td></tr>'
            )
        parts.append("</tbody></table></div>")

    hyps = ai.get("ownership_hypotheses") or []
    if hyps:
        parts.append("<h3>👤 Ownership Hypotheses</h3>")
        for h in hyps[:5]:
            parts.append(
                f"<p><strong>{escape(str(h.get('hypothesis',''))[:200])}</strong> "
                f"<em>({escape(str(h.get('confidence','')))})</em></p>"
            )
            for ev in (h.get("evidence") or [])[:3]:
                parts.append(f"<p class='muted'>• {escape(str(ev)[:200])}</p>")

    pivots = ai.get("investigation_pivots") or []
    if pivots:
        parts.append("<h3>🔍 Investigation Pivots</h3>")
        parts.append('<div class="table-wrap"><table><thead><tr><th>Priority</th><th>Action</th><th>Target</th><th>Reason</th></tr></thead><tbody>')
        for p in pivots[:8]:
            parts.append(
                f'<tr><td>{escape(str(p.get("priority","")))}</td>'
                f'<td>{escape(str(p.get("action",""))[:150])}</td>'
                f'<td><code>{escape(str(p.get("target",""))[:60])}</code></td>'
                f'<td>{escape(str(p.get("reason",""))[:150])}</td></tr>'
            )
        parts.append("</tbody></table></div>")

    risk = ai.get("risk_assessment") or {}
    if risk.get("overall_risk"):
        parts.append(f"<h3>⚡ Risk Assessment: {escape(str(risk['overall_risk']).upper())}</h3>")
        for rf in (risk.get("risk_factors") or [])[:5]:
            parts.append(f"<p class='muted'>• {escape(str(rf)[:200])}</p>")

    parts.append("</section>")
    return "\n".join(parts)
