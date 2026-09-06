from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any


def _addr(value: Any) -> str:
    return str(value or "").strip().lower()


def _short(address: str) -> str:
    return f"{address[:8]}...{address[-6:]}" if len(address) > 18 else address


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except Exception:
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _evidence(kind: str, title: str, detail: str, source: str, confidence: float, data: dict | None = None) -> dict:
    return {
        "kind": kind,
        "title": title,
        "detail": detail,
        "source": source,
        "confidence": round(_clamp(confidence), 3),
        "data": data or {},
    }


def _node_address(node: dict) -> str:
    return _addr(node.get("address") or node.get("id"))


def _edge_endpoint(edge: dict, key: str) -> str:
    return _addr(edge.get(key) or edge.get(f"{key}_address"))


def _tx_value(edge: dict) -> float:
    return _safe_float(edge.get("value", edge.get("amount", 0)))


def _unique(items: list[dict], key: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        value = str(item.get(key, ""))
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(item)
    return out


def _text(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip() or default
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "username", "handle", "label", "candidate", "value", "domain", "reverse_name"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return default


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _chain_portfolio(intel: dict) -> dict:
    tokens = intel.get("tokens") or []
    token_rows = []
    total_usd = _safe_float(intel.get("portfolio_usd"))
    for token in tokens:
        amount = _safe_float(token.get("balance"))
        usd = _safe_float(token.get("usd_value"))
        if usd:
            total_usd += usd if not intel.get("portfolio_usd") else 0
        token_rows.append({
            "symbol": token.get("symbol") or "TOKEN",
            "name": token.get("name") or token.get("symbol") or "Unknown token",
            "balance": amount,
            "usd_value": usd,
            "contract": token.get("contract") or "",
        })
    token_rows.sort(key=lambda x: x.get("usd_value") or x.get("balance") or 0, reverse=True)
    return {
        "chain": intel.get("chain") or intel.get("detected_chain") or "",
        "native_balance": _safe_float(intel.get("balance")),
        "native_unit": intel.get("balance_unit") or "",
        "portfolio_usd": round(total_usd, 2),
        "tokens": token_rows[:30],
        "tx_count": intel.get("tx_count") or 0,
        "first_seen": intel.get("first_seen") or "",
        "last_seen": intel.get("last_seen") or "",
    }


def _chain_portfolios(primary: dict, chain_intels: list[dict] | None = None) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for intel in [primary] + list(chain_intels or []):
        if not isinstance(intel, dict) or intel.get("error") and not intel.get("tx_count") and not intel.get("balance"):
            continue
        chain = _text(intel.get("chain") or intel.get("detected_chain") or intel.get("chainid"), "UNKNOWN").upper()
        if chain in seen:
            continue
        seen.add(chain)
        portfolio = _chain_portfolio(intel)
        txs = list(intel.get("recent_txs") or []) + list(intel.get("token_txs") or [])
        rows.append({
            "chain": chain,
            "chainid": intel.get("chainid"),
            "native_balance": portfolio["native_balance"],
            "native_unit": portfolio["native_unit"],
            "portfolio_usd": portfolio["portfolio_usd"],
            "tx_count": portfolio["tx_count"] or len(txs),
            "token_count": len(portfolio["tokens"]),
            "first_seen": portfolio["first_seen"],
            "last_seen": portfolio["last_seen"],
            "explorer": intel.get("explorer") or "",
            "source": intel.get("source") or "",
            "active": bool((portfolio["tx_count"] or len(txs)) or portfolio["native_balance"] or portfolio["tokens"]),
        })
    rows.sort(key=lambda r: (r.get("portfolio_usd") or 0, r.get("tx_count") or 0), reverse=True)
    return rows


def _aggregate_portfolio(primary: dict, chain_intels: list[dict] | None = None) -> dict:
    chains = _chain_portfolios(primary, chain_intels)
    total_usd = sum(_safe_float(c.get("portfolio_usd")) for c in chains)
    active = [c for c in chains if c.get("active")]
    return {
        "total_usd": round(total_usd, 2),
        "chain_count": len(chains),
        "active_chain_count": len(active),
        "chains": chains,
        "dominant_chain": (active or chains or [{}])[0].get("chain", ""),
    }


def _activity_profile(intel: dict) -> dict:
    txs = list(intel.get("recent_txs") or []) + list(intel.get("token_txs") or [])
    directions = Counter(str(tx.get("direction") or "").upper() for tx in txs)
    tokens = Counter(str(tx.get("token") or intel.get("balance_unit") or "native") for tx in txs)
    counterparties: Counter[str] = Counter()
    subject = _addr(intel.get("address"))
    for tx in txs:
      for side in ("from", "to"):
        cp = _addr(tx.get(side))
        if cp and cp != subject:
            counterparties[cp] += 1
    return {
        "observed_transactions": len(txs),
        "in_count": directions.get("IN", 0),
        "out_count": directions.get("OUT", 0),
        "top_tokens": [{"token": k, "count": v} for k, v in tokens.most_common(8) if k],
        "top_counterparties": [{"address": k, "short": _short(k), "count": v} for k, v in counterparties.most_common(12)],
    }


def _graph_relationships(address: str, graph: dict) -> tuple[list[dict], list[dict], dict]:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    correlations = graph.get("correlations") or []
    node_map = {_node_address(n): n for n in nodes if _node_address(n)}
    related: list[dict] = []
    relation_scores: dict[str, float] = defaultdict(float)
    relation_evidence: dict[str, list[str]] = defaultdict(list)

    for edge in edges:
        src = _edge_endpoint(edge, "source")
        dst = _edge_endpoint(edge, "target")
        if address not in (src, dst):
            continue
        other = dst if src == address else src
        if not other:
            continue
        value = _tx_value(edge)
        relation_scores[other] += 0.18 + min(math.log1p(abs(value)) / 20, 0.18)
        relation_evidence[other].append(f"Direct {edge.get('type') or 'transaction'} flow {src[:8]}... -> {dst[:8]}... {edge.get('token') or ''} {value:g}".strip())

    for corr in correlations:
        src = _addr(corr.get("source"))
        dst = _addr(corr.get("target"))
        if address not in (src, dst):
            continue
        other = dst if src == address else src
        score = _safe_float(corr.get("score"))
        relation_scores[other] += 0.25 + score * 0.45
        for ev in corr.get("evidence") or []:
            relation_evidence[other].append(str(ev))

    for other, score in sorted(relation_scores.items(), key=lambda kv: kv[1], reverse=True):
        node = node_map.get(other, {})
        related.append({
            "address": other,
            "short": _short(other),
            "relationship": node.get("role_hint") or "linked wallet",
            "confidence": round(_clamp(score), 3),
            "risk_score": node.get("risk_score", 0),
            "labels": node.get("labels") or [],
            "evidence": relation_evidence[other][:6],
        })

    graph_summary = {
        "nodes": len(nodes),
        "edges": len(edges),
        "correlations": len(correlations),
        "direct_neighbors": len(related),
    }
    return related[:30], list(node_map.values()), graph_summary


def _identity_signals(address: str, intel: dict, local_labels: list[dict], reverse_name: str | None, threat: dict | None) -> tuple[list[dict], list[dict]]:
    """Build identity signals + attribution hypotheses.

    Consolidation: threat_intel_engine already derives Arkham, local-label, and
    scam-report attribution hypotheses with identical confidence values. When a
    `threat` dict is available, we import its hypotheses directly instead of
    re-deriving them here (the previous code computed them twice). We still
    derive the ENS reverse-name hypothesis locally (threat_intel doesn't cover it)
    and emit signals (evidence records) for the UI panels.
    """
    signals: list[dict] = []
    hypotheses: list[dict] = []
    threat_hyps_available = bool(threat and threat.get("attribution_hypotheses"))

    # ── ENS reverse-name — always derived locally (threat_intel doesn't cover it) ──
    if reverse_name:
        signals.append(_evidence("name_service", "Reverse name", f"Address reverse-resolves to {reverse_name}", "ENS/domain resolver", 0.82, {"name": reverse_name}))
        hypotheses.append({
            "candidate": reverse_name,
            "type": "public-name-profile",
            "confidence": 0.78,
            "evidence": ["Reverse name service record links this wallet to the displayed name."],
            "caveat": "Name ownership is a public identity signal, not proof of real-world owner.",
        })

    # ── Evidence signals (for the UI panels) — always emitted ──
    arkham = intel.get("arkham") or {}
    if arkham.get("found"):
        name = arkham.get("name") or arkham.get("entity_name") or arkham.get("label") or arkham.get("entity_id")
        signals.append(_evidence("entity_label", "Arkham entity signal", f"Wallet appears in existing entity intelligence as {name}", "address-intel", 0.76, arkham))

    for label in local_labels:
        confidence = _safe_float(label.get("confidence"), 1.0)
        signals.append(_evidence("local_label", label.get("label") or "Local label", label.get("notes") or label.get("category") or "Investigator-owned local label matched this wallet.", label.get("source") or "local-labels", confidence, label))

    sanctions = intel.get("sanctions") or {}
    if sanctions.get("sanctioned"):
        ids = sanctions.get("identifications") or []
        name = ids[0].get("name") if ids and isinstance(ids[0], dict) else "Sanctions match"
        signals.append(_evidence("sanctions", "Sanctions exposure", f"Sanctions screening matched {name}", sanctions.get("source") or "sanctions", 0.92, sanctions))

    scam = intel.get("scam_reports") or {}
    if scam.get("found"):
        signals.append(_evidence("scam_report", "Public scam report match", f"{scam.get('count', 1)} public scam report(s) reference this wallet.", scam.get("source") or "scam reports", 0.68, {"count": scam.get("count")}))

    # ── Attribution hypotheses — import from threat_intel to avoid re-deriving ──
    if threat_hyps_available:
        # threat_intel already computed Arkham (0.72), local-label, scam, and
        # ransomware hypotheses with the same values we would have used. Import
        # them directly instead of duplicating the work.
        for hyp in threat.get("attribution_hypotheses") or []:
            hypotheses.append({
                "candidate": hyp.get("candidate"),
                "type": hyp.get("type") or hyp.get("category") or "threat-intel",
                "confidence": _safe_float(hyp.get("confidence")),
                "evidence": hyp.get("evidence") or [],
                "caveat": "Generated from local threat-intelligence heuristics; validate before reporting.",
            })
    else:
        # No threat-intel available — fall back to local derivation (standalone use)
        if arkham.get("found"):
            name = arkham.get("name") or arkham.get("entity_name") or arkham.get("label") or arkham.get("entity_id")
            hypotheses.append({
                "candidate": name,
                "type": arkham.get("entity_type") or "entity-label",
                "confidence": 0.72,
                "evidence": [arkham.get("entity_note") or arkham.get("label") or "Entity label returned by configured address intelligence."],
                "caveat": "Third-party labels require analyst review and corroboration.",
            })
        for label in local_labels:
            confidence = _safe_float(label.get("confidence"), 1.0)
            hypotheses.append({
                "candidate": label.get("label") or label.get("category") or "Local label",
                "type": label.get("category") or "investigator-label",
                "confidence": round(_clamp(confidence), 3),
                "evidence": [label.get("notes") or "Matched investigator-owned label database."],
                "caveat": "Local labels inherit the quality of analyst-maintained evidence.",
            })

    return signals, _unique([h for h in hypotheses if h.get("candidate")], "candidate")[:12]


def _public_profile_records(domain_profile: dict | None, intel: dict, local_labels: list[dict]) -> tuple[list[dict], list[str]]:
    profile = domain_profile or {}
    records = profile.get("text_records") or {}
    handles: list[dict] = []
    aliases: list[str] = []

    reverse_name = _text(profile.get("reverse_name"))
    if reverse_name:
        aliases.append(reverse_name)
        handles.append({
            "platform": "ENS",
            "handle": reverse_name,
            "source": "ens_reverse",
            "confidence": 0.86,
            "url": f"https://app.ens.domains/{reverse_name}",
        })

    record_map = {
        "com.twitter": ("X / Twitter", "https://x.com/"),
        "com.github": ("GitHub", "https://github.com/"),
        "com.discord": ("Discord", ""),
        "url": ("Website", ""),
        "email": ("Email", "mailto:"),
        "avatar": ("Avatar", ""),
        "description": ("Bio", ""),
    }
    for key, value in records.items():
        text = _text(value)
        if not text:
            continue
        platform, prefix = record_map.get(key, (key, ""))
        handle = text.lstrip("@") if key in {"com.twitter", "com.github"} else text
        aliases.append("@" + handle if key in {"com.twitter", "com.github"} else handle)
        handles.append({
            "platform": platform,
            "handle": "@" + handle if key in {"com.twitter", "com.github"} else handle,
            "source": "ens_text_record",
            "confidence": 0.78,
            "url": f"{prefix}{handle}" if prefix and not prefix.startswith("mailto:") else f"{prefix}{handle}" if prefix else "",
        })

    arkham = intel.get("arkham") or {}
    for key, platform in (("entity_twitter", "X / Twitter"), ("entity_website", "Website")):
        value = _text(arkham.get(key))
        if value:
            aliases.append(value)
            handles.append({"platform": platform, "handle": value, "source": "entity_intel", "confidence": 0.68, "url": value if value.startswith("http") else ""})

    for label in local_labels:
        label_text = _text(label.get("label"))
        if label_text:
            aliases.append(label_text)
            handles.append({"platform": "Local Label", "handle": label_text, "source": label.get("source") or "local-labels", "confidence": _safe_float(label.get("confidence"), 0.7), "url": ""})

    return _unique(handles, "platform"), list(dict.fromkeys(a for a in aliases if a))[:16]


def _protocol_and_services(intel: dict, graph: dict) -> list[dict]:
    hits: list[dict] = []
    chain_hop = intel.get("chain_hop_swap") or {}
    for item in chain_hop.get("bridge_hits") or []:
        hits.append({"type": "bridge", "name": item.get("name") or "Bridge", "confidence": 0.72, "evidence": item})
    for item in chain_hop.get("swap_hits") or []:
        hits.append({"type": "dex-swap", "name": item.get("name") or "DEX", "confidence": 0.68, "evidence": item})
    for item in intel.get("mixer_hits") or []:
        hits.append({"type": "mixer", "name": item.get("mixer_name") or "Mixer", "confidence": 0.82, "evidence": item})
    for node in graph.get("nodes") or []:
        labels = " ".join(node.get("labels") or [])
        role = str(node.get("role_hint") or "")
        if any(term in f"{labels} {role}".lower() for term in ["exchange", "mixer", "bridge", "dex", "swap"]):
            hits.append({
                "type": "counterparty-service",
                "name": role or labels or "Service counterparty",
                "confidence": min(0.78, 0.45 + _safe_float(node.get("risk_score")) / 200),
                "evidence": {"address": node.get("address") or node.get("id"), "labels": node.get("labels") or []},
            })
    return hits[:30]


def _protocol_positions(intel: dict, graph: dict, chain_intels: list[dict] | None = None) -> list[dict]:
    rows: list[dict] = []
    for chain_intel in [intel] + list(chain_intels or []):
        chain = _text(chain_intel.get("chain") or chain_intel.get("detected_chain"), "CHAIN").upper()
        native_balance = _safe_float(chain_intel.get("balance"))
        if native_balance:
            rows.append({
                "name": f"{chain} Wallet",
                "type": "wallet",
                "chain": chain,
                "usd_value": _safe_float(chain_intel.get("portfolio_usd")),
                "balance": native_balance,
                "symbol": chain_intel.get("balance_unit") or chain,
                "confidence": 0.9,
                "evidence": "Native chain balance observed.",
            })
        for token in chain_intel.get("tokens") or []:
            symbol = _text(token.get("symbol"), "TOKEN")
            rows.append({
                "name": token.get("name") or symbol,
                "type": "token",
                "chain": chain,
                "usd_value": _safe_float(token.get("usd_value")),
                "balance": _safe_float(token.get("balance")),
                "symbol": symbol,
                "confidence": 0.82,
                "evidence": f"Token balance observed on {chain}.",
            })
    for svc in _protocol_and_services(intel, graph):
        rows.append({
            "name": svc.get("name"),
            "type": svc.get("type"),
            "chain": _text(intel.get("chain"), ""),
            "usd_value": 0,
            "balance": 0,
            "symbol": "",
            "confidence": svc.get("confidence", 0),
            "evidence": "Service/protocol interaction inferred from local graph or wallet intelligence.",
        })
    rows.sort(key=lambda x: (_safe_float(x.get("usd_value")), _safe_float(x.get("confidence"))), reverse=True)
    return rows[:60]


def _activity_metrics(intel: dict, chain_intels: list[dict] | None, graph_summary: dict, related: list[dict]) -> dict:
    all_txs = []
    chains = [intel] + list(chain_intels or [])
    for item in chains:
        all_txs.extend(item.get("recent_txs") or [])
        all_txs.extend(item.get("token_txs") or [])
    first_seen = min([_text(tx.get("time")) for tx in all_txs if _text(tx.get("time"))] or [_text(intel.get("first_seen"))])
    last_seen = max([_text(tx.get("time")) for tx in all_txs if _text(tx.get("time"))] or [_text(intel.get("last_seen"))])
    return {
        "observed_transactions": len({tx.get("hash") for tx in all_txs if tx.get("hash")}) or len(all_txs),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "graph_nodes": graph_summary.get("nodes", 0),
        "graph_edges": graph_summary.get("edges", 0),
        "correlations": graph_summary.get("correlations", 0),
        "direct_neighbors": len(related),
    }


def build_identity_profile(
    address: str,
    intel: dict | None = None,
    graph: dict | None = None,
    threat: dict | None = None,
    local_labels: list[dict] | None = None,
    reverse_name: str | None = None,
    domain_profile: dict | None = None,
    chain_intels: list[dict] | None = None,
) -> dict:
    subject = _addr(address or (intel or {}).get("address"))
    intel = intel or {}
    graph = graph or {}
    threat = threat or {}
    local_labels = local_labels or []

    related, _, graph_summary = _graph_relationships(subject, graph)
    signals, hypotheses = _identity_signals(subject, intel, local_labels, reverse_name, threat)
    public_handles, public_aliases = _public_profile_records(domain_profile, intel, local_labels)
    services = _protocol_and_services(intel, graph)
    portfolio = _chain_portfolio(intel)
    aggregate_portfolio = _aggregate_portfolio(intel, chain_intels)
    protocol_positions = _protocol_positions(intel, graph, chain_intels)
    activity = _activity_profile(intel)
    activity_metrics = _activity_metrics(intel, chain_intels, graph_summary, related)

    confidence = 0.12
    confidence += min(len(signals) * 0.08, 0.34)
    confidence += min(len(related) * 0.018, 0.18)
    confidence += 0.16 if reverse_name else 0
    confidence += 0.16 if hypotheses else 0
    confidence += 0.08 if services else 0
    confidence = _clamp(confidence)

    alias_candidates = []
    if reverse_name:
        alias_candidates.append(reverse_name)
    alias_candidates.extend(public_aliases)
    for hyp in hypotheses:
        cand = hyp.get("candidate")
        if cand and cand not in alias_candidates:
            alias_candidates.append(cand)

    likely_entity = _first_nonempty(
        public_aliases[0] if public_aliases else "",
        hypotheses[0]["candidate"] if hypotheses else "",
        reverse_name,
        "Unknown public entity",
    )
    username = ""
    for handle in public_handles:
        h = _text(handle.get("handle"))
        if h.startswith("@"):
            username = h
            break
    if not username and public_aliases:
        username = public_aliases[0]
    risk_flags = []
    if (intel.get("sanctions") or {}).get("sanctioned"):
        risk_flags.append("sanctions-match")
    if (intel.get("scam_reports") or {}).get("found"):
        risk_flags.append("public-scam-report")
    if intel.get("mixer_hits"):
        risk_flags.append("mixer-exposure")
    if services:
        risk_flags.extend(sorted({s["type"] for s in services if s.get("type") in {"bridge", "dex-swap", "mixer"}}))

    return {
        "version": "identity-lens-v2",
        "address": subject,
        "short": _short(subject),
        "chain": portfolio.get("chain") or intel.get("chain") or "",
        "likely_entity": likely_entity,
        "username": username,
        "profile": {
            "display_name": likely_entity,
            "username": username,
            "avatar_seed": subject[-8:],
            "public_handles": public_handles,
            "source_count": len(public_handles) + len(signals) + len(local_labels),
        },
        "confidence": round(confidence, 3),
        "confidence_label": "HIGH" if confidence >= 0.74 else "MEDIUM" if confidence >= 0.45 else "LOW",
        "aliases": alias_candidates[:12],
        "identity_signals": signals,
        "attribution_hypotheses": hypotheses,
        "portfolio": portfolio,
        "aggregate_portfolio": aggregate_portfolio,
        "protocol_positions": protocol_positions,
        "activity": activity,
        "activity_metrics": activity_metrics,
        "services": services,
        "related_wallets": related,
        "risk_flags": sorted(set(risk_flags)),
        "graph_summary": graph_summary,
        "investigator_notes": [
            "This profile is evidence-first and generated from local investigation signals.",
            "Treat ownership as a confidence-scored hypothesis unless public identity records and transaction evidence corroborate it.",
            "Private real-world attribution should require lawful off-chain process or investigator-owned evidence.",
        ],
    }
