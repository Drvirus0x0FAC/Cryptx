"""
CrypTX Investigator Insight Engine
==================================
Shared analytics layer that upgrades EVERY screen with investigator-grade
added value. One endpoint, context-aware: each screen sends its context
("address", "trace", "dex", "case", "monitor", "dashboard") plus whatever data
it already has, and receives back a prioritized set of insights:

  - key_findings        what matters most right now, ranked
  - anomalies           statistical outliers vs. everything CrypTX has seen
  - predictions         condensed pre-crime outlook from the predictive engine
  - percentiles         how this subject compares to the analyzed population
  - next_steps          concrete recommended investigator actions
  - watch_signals       things to monitor going forward

Insights are deduplicated, severity-ranked and evidence-backed so the panel is
useful rather than noisy.
"""
from __future__ import annotations

import json
import statistics
from typing import Any, Dict, List, Optional

import database as db
import predictive_engine as pe

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _insight(severity: str, title: str, detail: str, action: str = "",
             tag: str = "") -> Dict[str, Any]:
    return {"severity": severity, "title": title, "detail": detail,
            "action": action, "tag": tag}


def _rank(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    seen: set = set()
    out = []
    for it in sorted(items, key=lambda i: SEV_ORDER.get(i["severity"], 5)):
        key = it["title"][:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
        if len(out) >= limit:
            break
    return out


def _percentiles(feats: Dict[str, float]) -> List[Dict[str, Any]]:
    """Where does this subject sit vs. every address CrypTX has analyzed?"""
    out: List[Dict[str, Any]] = []
    interesting = [
        ("tx_per_day", "Transaction velocity"),
        ("total_in_usd", "Total inflow (USD)"),
        ("fan_out", "Outbound counterparties"),
        ("unique_counterparties", "Network size"),
        ("risky_counterparty_ratio", "Illicit-counterparty exposure"),
        ("avg_tx_usd", "Average transfer size"),
    ]
    try:
        with db.get_connection() as con:
            rows = con.execute(
                "SELECT features_json FROM predictive_features LIMIT 10000").fetchall()
        pop: Dict[str, List[float]] = {k: [] for k, _ in interesting}
        for r in rows:
            try:
                fj = json.loads(r["features_json"])
            except Exception:
                continue
            for k, _ in interesting:
                v = fj.get(k)
                if isinstance(v, (int, float)):
                    pop[k].append(float(v))
        for k, label in interesting:
            vals = pop.get(k) or []
            if len(vals) < 10:
                continue
            v = float(feats.get(k, 0.0))
            pct = 100.0 * sum(1 for x in vals if x <= v) / len(vals)
            out.append({"metric": label, "value": round(v, 2),
                        "percentile": round(pct, 1), "population": len(vals)})
    except Exception:
        pass
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Context analyzers
# ──────────────────────────────────────────────────────────────────────────────

def _address_insights(address: str, chain: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    ins: List[Dict[str, Any]] = []
    intel = data.get("intel") or {}
    feats = pe.extract_features(address, chain, intel or None)

    if feats["is_sanctioned"]:
        ins.append(_insight("critical", "Sanctioned entity",
                            "Subject appears on sanctions lists. All downstream flows are tainted.",
                            "Generate a Regulatory report and preserve full graph evidence now.", "sanctions"))
    if feats["mixer_proximity"] > 0:
        ins.append(_insight("critical", "Mixer exposure in immediate graph",
                            "Subject is directly or 1-hop connected to mixing infrastructure.",
                            "Open Demix Lab to attempt de-mixing correlation.", "laundering"))
    if feats["drainer_proximity"] > 0:
        ins.append(_insight("critical", "Drainer infrastructure contact",
                            "Subject interacted with known drainer/phishing contracts.",
                            "Check victim reports and map shared infrastructure in Scam Atlas.", "scam"))
    if feats["poisoning_score"] > 0:
        ins.append(_insight("high", "Address-poisoning lookalikes present",
                            "Counterparties with matching prefix+suffix detected — active poisoning attempt.",
                            "Flag lookalike addresses and warn stakeholders against copy-paste errors.", "victim"))
    if feats["structuring_ratio"] > 0.15:
        ins.append(_insight("high", "Structuring below reporting threshold",
                            f"{feats['structuring_ratio']*100:.0f}% of transfers fall just under $10k.",
                            "Document the pattern — strong indicator for a SAR filing.", "laundering"))
    if feats["peel_chain_score"] > 0.3:
        ins.append(_insight("high", "Peel-chain layering signature",
                            "Sequential decreasing transfers consistent with automated layering.",
                            "Trace the peel chain end-points in Fund Tracer (wide mode).", "laundering"))
    if feats["dormancy_awakening"]:
        ins.append(_insight("medium", "Dormant wallet just woke up",
                            "30+ days of silence followed by fresh activity within the last week.",
                            "Add to Wallet Monitor before funds move again.", "behavior"))
    if feats["fresh_counterparty_ratio"] > 0.6 and feats["unique_counterparties"] >= 5:
        ins.append(_insight("medium", "Disposable-wallet network",
                            f"{feats['fresh_counterparty_ratio']*100:.0f}% of counterparties have no "
                            "labels/history — likely purpose-built intermediaries.",
                            "Cluster them with the Clustering engine to find the common controller.", "network"))
    if feats["stablecoin_ratio"] > 0.4:
        ins.append(_insight("medium", "Stablecoin rotation",
                            "Heavy conversion into stablecoins — value preservation before movement.",
                            "Watch for exchange deposits; stablecoin issuers can freeze on request.", "cashout"))
    if not ins:
        ins.append(_insight("info", "No high-priority red flags in stored history",
                            "Behavioral profile within population norms on available data. "
                            "Coverage may be partial — consider a deeper trace.",
                            "Run Auto-Investigate to widen data coverage.", "baseline"))
    return ins


def _trace_insights(address: str, chain: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    ins: List[Dict[str, Any]] = []
    graph = data.get("graph") or {}
    edges = graph.get("edges") or data.get("edges") or []
    nodes = graph.get("nodes") or data.get("nodes") or []

    if edges:
        usd = [pe._f(e.get("value_usd")) for e in edges if pe._f(e.get("value_usd")) > 0]
        total = sum(usd)
        if usd:
            top = max(usd)
            if total > 0 and top / total > 0.5:
                ins.append(_insight("high", "Flow dominated by a single transfer",
                                    f"One edge carries {top/total*100:.0f}% of traced value (${top:,.0f}).",
                                    "Prioritize that corridor — resolve its endpoints first.", "flow"))
        # terminal sinks
        sources = {pe._norm(e.get("source")) for e in edges}
        sinks: Dict[str, float] = {}
        for e in edges:
            t = pe._norm(e.get("target"))
            if t not in sources:
                sinks[t] = sinks.get(t, 0.0) + pe._f(e.get("value_usd"))
        top_sinks = sorted(sinks.items(), key=lambda kv: -kv[1])[:3]
        if top_sinks:
            labels = pe.gather_labels([a for a, _ in top_sinks])
            for a, v in top_sinks:
                lbl = labels.get(a, {}).get("label") or "unlabeled"
                ltype = labels.get(a, {}).get("type") or ""
                sev = "high" if v > 10_000 else "medium"
                hint = "KYC records may exist — prepare legal process." \
                    if pe._label_match(lbl, ltype, pe.EXCHANGE_LABELS) else \
                    "Terminal wallet — candidate for monitoring and freeze coordination."
                ins.append(_insight(sev, f"Terminal sink: {lbl}",
                                    f"{a[:14]}… absorbed ${v:,.0f} and hasn't forwarded it.", hint, "sink"))
    if nodes:
        risky = [n for n in nodes if pe._f(n.get("risk_score")) >= 60]
        if risky:
            ins.append(_insight("high", f"{len(risky)} high-risk nodes in traced graph",
                                "Multiple counterparties already carry HIGH/CRITICAL risk scores.",
                                "Batch-screen all graph nodes and pin the worst into the case.", "risk"))
    if not ins:
        ins.append(_insight("info", "Trace graph shows no concentrated risk yet",
                            "Consider increasing hop depth or switching to wide mode.",
                            "Re-run with +1 hop; watch for consolidation points.", "flow"))
    return ins


def _dex_insights(address: str, chain: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    ins: List[Dict[str, Any]] = []
    swaps = data.get("swaps") or []
    if swaps:
        buys = [s for s in swaps if str(s.get("side", "")).lower() == "buy"]
        sells = [s for s in swaps if str(s.get("side", "")).lower() == "sell"]
        if buys and sells and len(swaps) >= 10:
            ratio = len(buys) / max(1, len(sells))
            if 0.8 <= ratio <= 1.25:
                ins.append(_insight("high", "Wash-trading symmetry",
                                    f"Near-1:1 buy/sell ratio across {len(swaps)} swaps — "
                                    "self-trading to fake volume is likely.",
                                    "Compare counterparty wallets across the swap pairs for common funding.", "manipulation"))
        ts = sorted(pe._parse_ts(s.get("timestamp")) for s in swaps if s.get("timestamp"))
        if len(ts) >= 5:
            gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
            if gaps and statistics.median(gaps) < 120:
                ins.append(_insight("medium", "Bot-speed trading cadence",
                                    "Median inter-swap gap under 2 minutes — automated operation.",
                                    "Fingerprint the bot: identical gas patterns often link operator wallets.", "automation"))
    feats = pe.extract_features(address, chain)
    if feats["mixer_proximity"] > 0:
        ins.append(_insight("critical", "DEX activity funded near a mixer",
                            "Trading capital is mixer-adjacent — possible laundering-via-DEX.",
                            "Trace the funding leg before the first swap.", "laundering"))
    if not ins:
        ins.append(_insight("info", "No manipulation signature detected",
                            "Swap pattern looks organic on available data.", "", "baseline"))
    return ins


def _monitor_insights(address: str, chain: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    ins: List[Dict[str, Any]] = []
    watches = data.get("watches") or []
    addrs = [w.get("address") for w in watches if w.get("address")] or ([address] if address else [])
    scored = []
    for a in addrs[:15]:
        try:
            r = pe.predict_laundering(a, chain)
            scored.append((a, r["probability"], r["horizon"]))
        except Exception:
            continue
    scored.sort(key=lambda x: -x[1])
    for a, p, hz in scored[:5]:
        if p >= 0.45:
            sev = "critical" if p >= 0.65 else "high"
            ins.append(_insight(sev, f"Cash-out risk {p*100:.0f}% — {a[:12]}…",
                                f"Predictive engine expects movement within {hz}.",
                                "Raise alert priority and pre-stage freeze contacts.", "prediction"))
    if not ins:
        ins.append(_insight("info", "Watchlist quiet",
                            "No watched address currently shows imminent-movement staging.",
                            "Predictions refresh on each scan — keep monitors running.", "baseline"))
    return ins


def _case_insights(address: str, chain: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    ins: List[Dict[str, Any]] = []
    case_id = data.get("case_id") or ""
    addrs: List[Dict[str, Any]] = data.get("addresses") or []
    if case_id and not addrs:
        try:
            with db.get_connection() as con:
                addrs = [dict(r) for r in con.execute(
                    "SELECT address, chain, risk_score FROM case_addresses WHERE case_id=? LIMIT 50",
                    (case_id,)).fetchall()]
        except Exception:
            addrs = []
    high = [a for a in addrs if pe._f(a.get("risk_score")) >= 60]
    if high:
        ins.append(_insight("high", f"{len(high)}/{len(addrs)} case addresses are HIGH+ risk",
                            "Case risk is concentrated — prioritize these subjects.",
                            "Run predict-all on the top addresses to sequence next actions by urgency.", "case"))
    stale = [a for a in addrs if pe._f(a.get("risk_score")) < 0]
    if stale:
        ins.append(_insight("medium", f"{len(stale)} case addresses never scored",
                            "Unscored addresses are blind spots in the case.",
                            "Batch-screen them to complete coverage.", "coverage"))
    # cross-address overlap
    if len(addrs) >= 2:
        cps: Dict[str, int] = {}
        for a in addrs[:10]:
            for e in pe.gather_address_edges(a.get("address", "")):
                for side in ("source", "target"):
                    v = pe._norm(e.get(side))
                    if v and v not in {pe._norm(x.get("address")) for x in addrs}:
                        cps[v] = cps.get(v, 0) + 1
        shared = [(k, c) for k, c in cps.items() if c >= 2]
        shared.sort(key=lambda kv: -kv[1])
        if shared:
            ins.append(_insight("high", "Hidden common counterparty across case subjects",
                                f"{shared[0][0][:14]}… touches {shared[0][1]} of the case addresses — "
                                "possible common controller or consolidation point.",
                                "Add it to the case and run Entity Investigation on it.", "link-analysis"))
    if not ins:
        ins.append(_insight("info", "Case coverage looks complete",
                            "All subjects scored; no cross-subject convergence found yet.",
                            "Widen each subject by 1 hop to hunt for late-stage consolidation.", "case"))
    return ins


def _dashboard_insights(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    ins: List[Dict[str, Any]] = []
    try:
        with db.get_connection() as con:
            hot = con.execute(
                """SELECT address, ptype, probability, level, horizon, MAX(created_at) ts
                   FROM predictive_predictions WHERE probability >= 0.55
                   GROUP BY address, ptype ORDER BY probability DESC LIMIT 5""").fetchall()
            for r in hot:
                ins.append(_insight(
                    "critical" if r["probability"] >= 0.75 else "high",
                    f"{str(r['ptype']).title()} threat {r['probability']*100:.0f}% — {r['address'][:12]}…",
                    f"Level {r['level']}, expected window {r['horizon']} (as of {r['ts']}).",
                    "Open Predictive AI for full evidence chain.", "prediction"))
            n_mon = con.execute("SELECT COUNT(*) c FROM wallet_monitors").fetchone()
            unread = None
            try:
                unread = con.execute(
                    "SELECT COUNT(*) c FROM monitor_notifications WHERE read_at IS NULL OR read_at=''").fetchone()
            except Exception:
                pass
            if n_mon and n_mon["c"] and unread and unread["c"] > 10:
                ins.append(_insight("medium", f"{unread['c']} unreviewed monitor alerts",
                                    "Alert backlog is growing — triage to avoid missing staging behavior.",
                                    "Sort by predictive cash-out risk in the Monitor screen.", "ops"))
    except Exception:
        pass
    if not ins:
        ins.append(_insight("info", "No elevated predictive threats on file",
                            "Run predictions on active subjects to populate the threat board.",
                            "Open Predictive AI and analyze your case addresses.", "baseline"))
    return ins


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

_CONTEXTS = {"address", "trace", "dex", "case", "monitor", "dashboard"}


def generate_insights(context: str, address: str = "", chain: str = "",
                      data: Optional[Dict[str, Any]] = None,
                      include_predictions: bool = True,
                      limit: int = 8) -> Dict[str, Any]:
    data = data or {}
    context = (context or "address").lower()
    if context not in _CONTEXTS:
        context = "address"

    if context == "address":
        items = _address_insights(address, chain, data)
    elif context == "trace":
        items = _trace_insights(address, chain, data)
    elif context == "dex":
        items = _dex_insights(address, chain, data)
    elif context == "monitor":
        items = _monitor_insights(address, chain, data)
    elif context == "case":
        items = _case_insights(address, chain, data)
    else:
        items = _dashboard_insights(data)

    out: Dict[str, Any] = {
        "context": context,
        "address": address,
        "insights": _rank(items, limit),
    }

    if address and context in {"address", "trace", "dex"}:
        feats = pe.extract_features(address, chain, (data.get("intel") or None))
        out["percentiles"] = _percentiles(feats)
        anom = pe.anomaly_report(feats)
        out["anomaly"] = {"score": anom["anomaly_score"], "outliers": anom["outliers"][:4]}
        if include_predictions:
            try:
                laun = pe.predict_laundering(address, chain)
                traj = pe.predict_trajectory(address, chain)
                out["predictions"] = {
                    "laundering": {"probability": laun["probability"], "level": laun["level"],
                                   "horizon": laun["horizon"]},
                    "trajectory": {"probability": traj["probability"], "level": traj["level"],
                                   "trend": traj.get("trend"), "horizons": traj.get("horizons")},
                }
            except Exception:
                pass
    return out
