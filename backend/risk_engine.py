"""
CryptoOSINT Risk Scoring Engine
Inspired by Uppsala Security CARA and Caudena Prism.

Composite 0-100 risk score with 20+ indicators:
  SANCTIONED (100) → CRITICAL (80-99) → HIGH (60-79)
  → MEDIUM (40-59) → LOW (20-39) → CLEAN (0-19)
"""
from __future__ import annotations
from typing import Any, Dict, List

# Risk level thresholds
RISK_LEVELS: List[tuple[int, str]] = [
    (100, "SANCTIONED"),
    (80,  "CRITICAL"),
    (60,  "HIGH"),
    (40,  "MEDIUM"),
    (20,  "LOW"),
    (0,   "CLEAN"),
]

# Entity type → risk multiplier
_HIGH_RISK_ENTITY_TYPES = frozenset({
    "mixer", "tumbler", "obfuscation", "darknet", "dark_market", "illicit",
    "scam", "hack", "phishing", "fraud", "gambling_illegal", "sanctions",
    "ransomware", "terror", "terrorist",
})
_TRUSTED_ENTITY_TYPES = frozenset({
    "exchange", "cex", "dex", "defi", "institution", "custodian",
    "government", "regulator", "protocol", "nft_marketplace",
})


def score_to_level(score: int) -> str:
    for threshold, level in RISK_LEVELS:
        if score >= threshold:
            return level
    return "CLEAN"


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def compute_risk_score(intel: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute a deterministic composite risk score from address intelligence.

    Returns:
        {
          score: int (0-100),
          risk_level: str,
          categories: list[str],
          signals: list[dict],
          exposure: dict,
          indicators: dict,
        }
    """
    score = 0
    signals: List[Dict] = []
    categories: set[str] = set()

    # ── 1. Sanctions screening (OFAC / Chainalysis) — weight 100 ──────────
    sanctions = intel.get("sanctions") or {}
    if sanctions.get("sanctioned"):
        score = 100
        categories.add("sanctioned")
        ids = sanctions.get("identifications") or []
        detail = "; ".join(
            f"{i.get('name', '')} ({i.get('category', '')})" for i in ids[:3]
        ) or sanctions.get("source", "OFAC")
        signals.append({
            "type": "sanctioned",
            "severity": "CRITICAL",
            "weight": 100,
            "label": "OFAC / Chainalysis Sanctioned Address",
            "detail": detail,
            "source": sanctions.get("source", "ofac"),
        })

    # ── 2. Known mixer interactions (Tornado Cash, Sinbad, Helix, etc.) ───
    mixer_hits = intel.get("mixer_hits") or []
    if mixer_hits:
        names = sorted({h.get("mixer_name", "Mixer") for h in mixer_hits})
        w = min(65 + len(mixer_hits) * 4, 92)
        score = max(score, w)
        categories.add("mixer")
        signals.append({
            "type": "mixer",
            "severity": "HIGH",
            "weight": w,
            "label": f"Mixer / Obfuscation Interactions ({len(mixer_hits)})",
            "detail": ", ".join(names[:6]),
            "count": len(mixer_hits),
        })

    # ── 3. Community scam reports (ScamSearch) ─────────────────────────────
    scam = intel.get("scam_reports") or {}
    scam_count = _safe_int(scam.get("count"))
    if scam_count > 0 and not scam.get("skipped"):
        w = min(55 + scam_count * 5, 85)
        score = max(score, w)
        categories.add("scam")
        signals.append({
            "type": "scam",
            "severity": "HIGH",
            "weight": w,
            "label": f"Scam Community Reports ({scam_count})",
            "detail": "Community-reported scam/fraud activity via ScamSearch",
            "count": scam_count,
        })

    # ── 4. Arkham entity attribution ───────────────────────────────────────
    arkham = intel.get("arkham") or {}
    if arkham.get("found") and not arkham.get("error"):
        entity_type = (arkham.get("entity_type") or "").lower()
        entity_name = arkham.get("name") or arkham.get("entity_name") or ""
        label_type  = (arkham.get("label_type") or "").lower()

        if any(t in entity_type or t in label_type for t in _HIGH_RISK_ENTITY_TYPES):
            w = 82
            score = max(score, w)
            categories.add("darknet" if "dark" in entity_type else "mixer" if "mixer" in entity_type else "scam")
            signals.append({
                "type": "arkham_high_risk",
                "severity": "HIGH",
                "weight": w,
                "label": f"Arkham: High-Risk Entity — {entity_name}",
                "detail": f"Type: {entity_type or label_type}",
            })
        elif any(t in entity_type or t in label_type for t in _TRUSTED_ENTITY_TYPES):
            categories.add("exchange")
            signals.append({
                "type": "arkham_trusted",
                "severity": "INFO",
                "weight": 0,
                "label": f"Arkham: Known Entity — {entity_name}",
                "detail": f"Type: {entity_type} (reduces concern)",
            })
        else:
            signals.append({
                "type": "arkham_entity",
                "severity": "INFO",
                "weight": 0,
                "label": f"Arkham: Entity Attribution — {entity_name}",
                "detail": f"Type: {entity_type or 'unknown'}",
            })

    # ── 5. Chain hopping / bridge + swap layering ──────────────────────────
    hop = intel.get("chain_hop_swap") or {}
    bridge_ct = _safe_int(hop.get("bridge_count"))
    swap_ct   = _safe_int(hop.get("swap_count"))
    hop_risk  = hop.get("risk_level", "clean")

    if bridge_ct > 0 and swap_ct > 0:
        w = 55
        score = max(score, w)
        categories.add("bridge")
        categories.add("dex")
        signals.append({
            "type": "bridge_swap_layering",
            "severity": "MEDIUM",
            "weight": w,
            "label": f"Chain-Hopping + Swap Layering ({bridge_ct} bridge, {swap_ct} swap)",
            "detail": "Combined cross-chain bridge and DEX interaction — layering indicator (FATF red flag)",
        })
    elif bridge_ct > 0:
        w = 30
        score = max(score, w)
        categories.add("bridge")
        signals.append({
            "type": "bridge",
            "severity": "LOW",
            "weight": w,
            "label": f"Cross-Chain Bridge Interactions ({bridge_ct})",
            "detail": "Bridge usage detected — may indicate chain-hopping",
        })
    elif swap_ct > 0:
        w = 18
        score = max(score, w)
        categories.add("dex")
        signals.append({
            "type": "dex_swap",
            "severity": "INFO",
            "weight": w,
            "label": f"DEX / Swap Router Activity ({swap_ct})",
            "detail": "DEX usage — informational",
        })

    # Bridge/swap heuristic flags
    for heu in (hop.get("heuristics") or []):
        if "bridge_plus_swap" in heu.get("type", ""):
            w = 48
            score = max(score, w)
            signals.append({
                "type": "heuristic_bridge_swap",
                "severity": "MEDIUM",
                "weight": w,
                "label": "Heuristic: Bridge + Swap Layering",
                "detail": heu.get("evidence", ""),
            })
        elif "multi_token" in heu.get("type", ""):
            w = 20
            score = max(score, w)
            signals.append({
                "type": "heuristic_multi_token",
                "severity": "INFO",
                "weight": w,
                "label": "Heuristic: Multi-Token Activity",
                "detail": heu.get("evidence", ""),
            })

    # ── 6. Pass-through / mule wallet ─────────────────────────────────────
    balance = _safe_float(intel.get("balance"))
    tx_count = _safe_int(intel.get("tx_count"))
    if balance < 0.001 and tx_count >= 10:
        w = 25
        score = max(score, w)
        signals.append({
            "type": "pass_through",
            "severity": "LOW",
            "weight": w,
            "label": "Possible Pass-Through / Mule Wallet",
            "detail": f"Near-zero balance ({balance}) with {tx_count} transactions — funds not retained",
        })

    # ── 7. Local forensic algorithms ──────────────────────────────────────
    forensic = intel.get("forensic_analysis") or intel.get("forensics") or {}
    if forensic:
        for sig in forensic.get("algorithm_signals") or []:
            w = _safe_int(sig.get("weight"))
            if w > 0:
                score = max(score, w)
            sig_type = str(sig.get("type", "forensic"))
            if "motif" in sig_type or "role" in sig_type:
                categories.add("behavioral")
            if "taint" in sig_type:
                categories.add("exposure")
            signals.append({
                "type": sig_type,
                "severity": sig.get("severity", "INFO"),
                "weight": w,
                "label": sig.get("label", "Local forensic signal"),
                "detail": sig.get("detail", ""),
                "confidence": sig.get("confidence", forensic.get("confidence", 0)),
                "source": "local_forensic_engine",
            })

        role = forensic.get("role") or {}
        if role.get("role") and role.get("role") != "ordinary_wallet":
            signals.append({
                "type": "behavioral_role_summary",
                "severity": "INFO",
                "weight": 0,
                "label": f"Local role hypothesis: {role.get('role')}",
                "detail": role.get("reason", ""),
                "confidence": role.get("confidence", 0),
                "source": "local_forensic_engine",
            })

    # ── 8. High-risk ERC20 token exposure (USDT on sanctioned chain) ──────
    tokens = intel.get("tokens") or []
    token_syms = [t.get("symbol", "").upper() for t in tokens]
    if "USDT" in token_syms or "USDC" in token_syms:
        # Only flag if other risk signals are present (stablecoins alone aren't risky)
        if score >= 40:
            signals.append({
                "type": "stablecoin_exposure",
                "severity": "INFO",
                "weight": 0,
                "label": "Stablecoin Holdings (USDT/USDC)",
                "detail": "Common in money laundering flows — review transactions carefully",
            })

    # ── 9. Public/free enrichment feeds ────────────────────────────────────
    pub = intel.get("public_enrichment") or {}
    pub_summary = pub.get("summary") or {}
    ransomware_count = _safe_int(pub_summary.get("ransomware_hit_count"))
    public_abuse_count = _safe_int(pub_summary.get("abuse_report_count"))
    public_label_count = _safe_int(pub_summary.get("label_count"))

    if ransomware_count > 0:
        w = min(88 + ransomware_count * 3, 96)
        score = max(score, w)
        categories.add("ransomware")
        matches = [
            str(m.get("label", "")) for m in ((pub.get("ransomware") or {}).get("matches") or [])
            if isinstance(m, dict)
        ]
        signals.append({
            "type": "public_ransomware_dataset",
            "severity": "CRITICAL",
            "weight": w,
            "label": f"Open Ransomware Dataset Match ({ransomware_count})",
            "detail": ", ".join(matches[:4]) or "Exact address match in public ransomware intelligence.",
            "source": "public_enrichment",
        })

    if public_abuse_count > 0:
        w = min(52 + public_abuse_count * 4, 86)
        score = max(score, w)
        categories.add("scam")
        signals.append({
            "type": "public_abuse_reports",
            "severity": "HIGH" if public_abuse_count >= 3 else "MEDIUM",
            "weight": w,
            "label": f"Public Abuse/Scam Reports ({public_abuse_count})",
            "detail": "Matches from BitcoinAbuse, CryptoScamDB, or similar public feeds.",
            "count": public_abuse_count,
            "source": "public_enrichment",
        })

    high_risk_public_labels = [
        l for l in (pub.get("labels") or [])
        if str(l.get("category", "")).lower() in {
            "sanctions", "ransomware", "scam", "phishing", "darknet", "mixer", "terrorist_financing"
        }
    ]
    if high_risk_public_labels and ransomware_count == 0:
        w = 72
        score = max(score, w)
        categories.add("scam")
        signals.append({
            "type": "public_high_risk_label",
            "severity": "HIGH",
            "weight": w,
            "label": f"Public High-Risk Label ({len(high_risk_public_labels)})",
            "detail": "; ".join(str(l.get("label", "")) for l in high_risk_public_labels[:4]),
            "source": "public_enrichment",
        })

    # ── Compute exposure ──────────────────────────────────────────────────
    exposure = _compute_exposure(intel)

    # Multiple independent signals should compound. The legacy max score is
    # kept as a floor, while this probability-style score captures layering.
    score = max(score, _compound_signal_score(signals))

    # ── Build indicators summary ──────────────────────────────────────────
    indicators = {
        "sanctions_checked": True,
        "mixer_interactions": len(mixer_hits),
        "scam_reports": scam_count,
        "arkham_attribution": arkham.get("found", False),
        "bridge_interactions": bridge_ct,
        "swap_interactions": swap_ct,
        "tx_count": tx_count,
        "balance": balance,
        "token_count": len(tokens),
        "direct_exposure_pct": exposure.get("direct_pct", 0),
        "forensic_confidence": forensic.get("confidence", 0) if forensic else 0,
        "forensic_motifs": len(forensic.get("motifs") or []) if forensic else 0,
        "public_labels": public_label_count,
        "public_abuse_reports": public_abuse_count,
        "ransomware_dataset_hits": ransomware_count,
    }

    return {
        "score": score,
        "risk_level": score_to_level(score),
        "categories": sorted(categories),
        "signals": signals,
        "exposure": exposure,
        "indicators": indicators,
        "address": intel.get("address", ""),
        "chain": intel.get("chain", ""),
    }


def _compound_signal_score(signals: List[Dict[str, Any]]) -> int:
    risk_probability = 0.0
    for signal in signals:
        weight = max(0, min(_safe_int(signal.get("weight")), 100))
        if weight == 0:
            continue
        confidence = _safe_float(signal.get("confidence"))
        if confidence <= 0:
            confidence = {
                "CRITICAL": 0.96,
                "HIGH": 0.82,
                "MEDIUM": 0.62,
                "LOW": 0.38,
                "INFO": 0.18,
            }.get(str(signal.get("severity", "INFO")).upper(), 0.35)
        contribution = (weight / 100.0) * max(0.1, min(confidence, 1.0))
        risk_probability = 1 - ((1 - risk_probability) * (1 - contribution))
    return int(round(min(risk_probability * 100, 100)))


def _compute_exposure(intel: Dict[str, Any]) -> Dict[str, Any]:
    """
    Estimate direct exposure: percentage of transacted volume
    flowing through known risky counterparties.
    """
    all_txs = list(intel.get("recent_txs") or []) + list(intel.get("token_txs") or [])
    if not all_txs:
        return {"direct_pct": 0, "risky_volume": 0, "total_volume": 0, "breakdown": [], "unit": ""}

    try:
        from crypto_osint import KNOWN_MIXERS
    except ImportError:
        KNOWN_MIXERS = {}

    unit = intel.get("balance_unit", "")
    total_value = 0.0
    risky_value = 0.0
    breakdown: Dict[str, float] = {}

    for tx in all_txs:
        val = _safe_float(
            tx.get("value_eth") or tx.get("value_trx") or
            abs(_safe_float(tx.get("delta_btc"))) or tx.get("value")
        )
        total_value += val
        # Check all counterparties
        for field in ("from", "to"):
            cp = (tx.get(field) or "").lower()
            if cp and cp in KNOWN_MIXERS:
                risky_value += val
                name = KNOWN_MIXERS[cp].get("name", "Mixer")
                breakdown[name] = breakdown.get(name, 0.0) + val

    direct_pct = (risky_value / total_value * 100) if total_value > 0 else 0

    return {
        "direct_pct": round(direct_pct, 2),
        "risky_volume": round(risky_value, 8),
        "total_volume": round(total_value, 8),
        "unit": unit,
        "breakdown": sorted(
            [{"entity": k, "volume": round(v, 8)} for k, v in breakdown.items()],
            key=lambda x: x["volume"],
            reverse=True,
        ),
    }
