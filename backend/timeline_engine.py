"""
Investigation Timeline Engine.
Builds a chronological event stream from address intel, transactions,
trace graphs, forensic data, and case notes.

Each event has:
  id, timestamp, type, actor, counterparty, value, token,
  description, severity, source, metadata
"""
from __future__ import annotations
import hashlib
import uuid
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any

_EVENT_TYPES = {
    "tx_in":           {"icon": "arrow-down",   "color": "green"},
    "tx_out":          {"icon": "arrow-up",     "color": "blue"},
    "tx_internal":     {"icon": "arrow-right",  "color": "gray"},
    "token_transfer":  {"icon": "coins",        "color": "purple"},
    "dex_swap":        {"icon": "repeat",       "color": "cyan"},
    "bridge_op":       {"icon": "link",         "color": "orange"},
    "mixer_use":       {"icon": "eye-off",      "color": "red"},
    "approval":        {"icon": "check-circle", "color": "yellow"},
    "contract_deploy": {"icon": "code",         "color": "gray"},
    "case_note":       {"icon": "file-text",    "color": "blue"},
    "case_address":    {"icon": "user-plus",    "color": "blue"},
    "risk_flag":       {"icon": "alert-triangle","color": "red"},
    "cluster_link":    {"icon": "users",        "color": "purple"},
    "cashout_signal":  {"icon": "trending-up",  "color": "orange"},
    "bridge_detect":   {"icon": "globe",        "color": "orange"},
    "unknown":         {"icon": "circle",       "color": "gray"},
}


def _parse_ts(ts: Any) -> float:
    if not ts:
        return 0.0
    if isinstance(ts, (int, float)):
        return float(ts)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(ts), fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    try:
        return float(ts)
    except (TypeError, ValueError):
        return 0.0


def _format_ts(ts: float) -> str:
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _evt(
    etype: str,
    timestamp: float,
    description: str,
    actor: str = "",
    counterparty: str = "",
    value: float = 0.0,
    token: str = "",
    severity: str = "info",
    source: str = "",
    tx_hash: str = "",
    metadata: dict | None = None,
) -> dict:
    meta = _EVENT_TYPES.get(etype, _EVENT_TYPES["unknown"])
    return {
        "id":          str(uuid.uuid4())[:8],
        "timestamp":   _format_ts(timestamp),
        "ts_epoch":    timestamp,
        "type":        etype,
        "icon":        meta["icon"],
        "color":       meta["color"],
        "actor":       actor,
        "actor_short": actor[:10] + "…" if len(actor) > 12 else actor,
        "counterparty": counterparty,
        "cp_short":    counterparty[:10] + "…" if len(counterparty) > 12 else counterparty,
        "value":       value,
        "token":       token,
        "description": description,
        "severity":    severity,
        "source":      source,
        "tx_hash":     tx_hash,
        "metadata":    metadata or {},
    }


# ── Event builders ────────────────────────────────────────────────────────────

def _events_from_txs(
    address: str,
    txs: list[dict],
    source_label: str = "address_intel",
) -> list[dict]:
    events = []
    for tx in txs:
        frm     = (tx.get("from") or "").lower()
        to      = (tx.get("to") or "").lower()
        val     = float(tx.get("value") or tx.get("value_eth") or tx.get("delta_btc") or 0)
        tok     = tx.get("token") or "native"
        ts_raw  = tx.get("time") or tx.get("timestamp") or ""
        ts      = _parse_ts(ts_raw)
        txhash  = tx.get("hash") or tx.get("txid") or ""
        direction = tx.get("direction") or ("OUT" if frm == address.lower() else "IN")

        if direction == "OUT":
            events.append(_evt(
                "tx_out", ts,
                f"Sent {val:.6f} {tok}" + (f" → {to[:10]}…" if to else ""),
                actor=frm, counterparty=to, value=val, token=tok,
                source=source_label, tx_hash=txhash,
            ))
        else:
            events.append(_evt(
                "tx_in", ts,
                f"Received {val:.6f} {tok}" + (f" ← {frm[:10]}…" if frm else ""),
                actor=frm, counterparty=to, value=val, token=tok,
                source=source_label, tx_hash=txhash,
            ))
    return events


def _events_from_token_txs(
    address: str,
    token_txs: list[dict],
) -> list[dict]:
    events = []
    for tx in token_txs:
        frm    = (tx.get("from") or "").lower()
        to     = (tx.get("to")   or "").lower()
        val    = float(tx.get("value") or 0)
        tok    = tx.get("token") or "TOKEN"
        ts     = _parse_ts(tx.get("time") or tx.get("timestamp") or "")
        txhash = tx.get("hash") or tx.get("txid") or ""
        events.append(_evt(
            "token_transfer", ts,
            f"Token: {val:.4f} {tok} {'→' if frm == address.lower() else '←'} "
            f"{''+to[:10]+'…' if frm == address.lower() else frm[:10]+'…'}",
            actor=frm, counterparty=to, value=val, token=tok,
            source="token_txs", tx_hash=txhash,
        ))
    return events


def _events_from_mixer_hits(
    address: str,
    mixer_hits: list[dict],
) -> list[dict]:
    events = []
    for h in mixer_hits:
        cp  = h.get("counterparty") or ""
        mxr = h.get("mixer_name") or "Mixer"
        ts  = _parse_ts(h.get("time") or "")
        txhash = h.get("tx_hash") or ""
        events.append(_evt(
            "mixer_use", ts,
            f"Mixer interaction with {mxr} (counterparty: {cp[:10]}…)",
            actor=address, counterparty=cp,
            severity="high", source="mixer_hits", tx_hash=txhash,
            metadata={"mixer_name": mxr, "mixer_type": h.get("mixer_type", "")},
        ))
    return events


def _events_from_trace_graph(
    address: str,
    trace_graph: dict,
) -> list[dict]:
    events = []
    edges = (trace_graph.get("edges") or []) if trace_graph else []
    nodes_by_id: dict[str, dict] = {
        n["id"]: n for n in (trace_graph.get("nodes") or [])
    }

    for e in edges:
        src = e.get("source_address") or e.get("source") or ""
        tgt = e.get("target_address") or e.get("target") or ""
        amt = float(e.get("amount") or e.get("value") or 0)
        tok = e.get("token") or "native"
        txhash = e.get("hash") or e.get("tx_hash") or ""

        # Try to get timestamp from edge metadata or source node
        ts = 0.0
        src_node = nodes_by_id.get(src, {})
        raw_txs = src_node.get("transactions") or []
        for tx in raw_txs:
            if (tx.get("hash") or tx.get("txid") or "") == txhash:
                ts = _parse_ts(tx.get("time") or "")
                break

        if src.lower() == address.lower():
            events.append(_evt(
                "tx_out", ts,
                f"Traced: sent {amt:.6f} {tok} → {tgt[:10]}…",
                actor=src, counterparty=tgt, value=amt, token=tok,
                source="trace_graph", tx_hash=txhash,
            ))
        elif tgt.lower() == address.lower():
            events.append(_evt(
                "tx_in", ts,
                f"Traced: received {amt:.6f} {tok} ← {src[:10]}…",
                actor=src, counterparty=tgt, value=amt, token=tok,
                source="trace_graph", tx_hash=txhash,
            ))
    return events


def _events_from_case(
    address: str,
    case: dict,
) -> list[dict]:
    events = []
    for note in case.get("notes") or []:
        ts = _parse_ts(note.get("created_at") or "")
        events.append(_evt(
            "case_note", ts,
            f"Case note: {str(note.get('note') or '')[:120]}",
            source="case",
            severity="info",
        ))
    for addr in case.get("addresses") or []:
        ts = _parse_ts(addr.get("added_at") or "")
        events.append(_evt(
            "case_address", ts,
            f"Address added to case: {addr.get('label') or addr.get('address','')[:20]}",
            actor=addr.get("address") or "",
            source="case",
        ))
    return events


def _events_from_risk(
    address: str,
    risk: dict,
) -> list[dict]:
    events = []
    for sig in risk.get("signals") or []:
        if sig.get("severity") in ("CRITICAL", "HIGH"):
            events.append(_evt(
                "risk_flag", 0.0,
                f"Risk signal: {sig.get('label','')} — {sig.get('detail','')}",
                actor=address,
                severity="high" if sig.get("severity") == "HIGH" else "critical",
                source="risk_score",
                metadata={"signal": sig},
            ))
    return events


def _events_from_cashout(
    address: str,
    cashout: dict,
) -> list[dict]:
    events = []
    for ind in cashout.get("indicators") or []:
        events.append(_evt(
            "cashout_signal", 0.0,
            f"Cashout: {ind.get('description','')}",
            actor=address,
            severity=ind.get("severity") or "medium",
            source="cashout_detector",
            metadata=ind,
        ))
    return events


def _events_from_crosschain(
    address: str,
    crosschain: dict,
) -> list[dict]:
    events = []
    for hop in crosschain.get("bridge_hops") or []:
        events.append(_evt(
            "bridge_detect", hop.get("timestamp") or 0,
            hop.get("description") or "Bridge hop detected",
            actor=address,
            value=float(hop.get("value") or 0),
            token=hop.get("token") or "",
            severity="medium",
            source="crosschain_engine",
            tx_hash=hop.get("tx_hash") or "",
            metadata=hop,
        ))
    return events


# ── Deduplication ─────────────────────────────────────────────────────────────

def _dedup(events: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for e in events:
        key = hashlib.md5(
            f"{e['type']}{e['ts_epoch']:.0f}{e['actor']}{e['counterparty']}{e['value']:.8f}".encode()
        ).hexdigest()
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# ── Public entry point ────────────────────────────────────────────────────────

def build_timeline(
    address: str,
    intel:       dict | None = None,
    trace_graph: dict | None = None,
    risk:        dict | None = None,
    case:        dict | None = None,
    cashout:     dict | None = None,
    crosschain:  dict | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """
    Aggregate all data sources into a unified investigation timeline.
    Returns sorted, deduped event list with stats.
    """
    events: list[dict] = []

    if intel:
        events += _events_from_txs(address, intel.get("recent_txs") or [])
        events += _events_from_token_txs(address, intel.get("token_txs") or [])
        events += _events_from_mixer_hits(address, intel.get("mixer_hits") or [])

    if trace_graph:
        events += _events_from_trace_graph(address, trace_graph)

    if risk:
        events += _events_from_risk(address, risk)

    if case:
        events += _events_from_case(address, case)

    if cashout:
        events += _events_from_cashout(address, cashout)

    if crosschain:
        events += _events_from_crosschain(address, crosschain)

    events = _dedup(events)

    # Sort: timestamped events by ts desc, then undated at end
    timestamped   = sorted([e for e in events if e["ts_epoch"] > 0], key=lambda x: x["ts_epoch"], reverse=True)
    untimstamped  = [e for e in events if e["ts_epoch"] <= 0]
    sorted_events = (timestamped + untimstamped)[:limit]

    # Stats
    by_type: dict[str, int] = defaultdict(int)
    by_sev:  dict[str, int] = defaultdict(int)
    for e in sorted_events:
        by_type[e["type"]] += 1
        by_sev[e["severity"]] += 1

    earliest = min((e["ts_epoch"] for e in timestamped), default=0)
    latest   = max((e["ts_epoch"] for e in timestamped), default=0)

    return {
        "address":        address,
        "events":         sorted_events,
        "event_count":    len(sorted_events),
        "total_raw":      len(events),
        "date_range": {
            "earliest": _format_ts(earliest),
            "latest":   _format_ts(latest),
        },
        "stats": {
            "by_type":     dict(by_type),
            "by_severity": dict(by_sev),
        },
    }
