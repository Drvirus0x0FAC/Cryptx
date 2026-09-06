"""
Modern laundering & tracing engine (Domain B).

Closes the 2026 "dead-ends" that stop most tracing tools:
  B1  instant-exchanger / no-KYC swap continuation detection (FixedFloat,
      SimpleSwap, ChangeNOW, THORChain, Chainflip …) + output re-matching.
  B2  address-poisoning detection (look-alike dust that primes copy-paste theft).
  B4  peel-chain & micro-fragmentation typology scoring.

Local, deterministic, evidence-first. Functions are pure — routers may enrich
inputs with the existing chain fetchers first, but the engine needs no network.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Optional

# ── Known instant-exchange / no-KYC swap infrastructure ──────────────────────
# Deposit addresses rotate, so we match on known service contracts/hot wallets
# AND on name hints surfaced by attribution. Extend freely; additive only.
INSTANT_SWAP_SERVICES: dict[str, dict[str, Any]] = {
    "fixedfloat":  {"label": "FixedFloat", "kyc": False, "type": "instant_exchanger",
                    "note": "No-KYC instant exchanger; the 2026 obfuscation layer of choice."},
    "simpleswap":  {"label": "SimpleSwap", "kyc": False, "type": "instant_exchanger",
                    "note": "No-KYC instant exchanger."},
    "changenow":   {"label": "ChangeNOW", "kyc": False, "type": "instant_exchanger",
                    "note": "No-account instant exchanger."},
    "changehero":  {"label": "ChangeHero", "kyc": False, "type": "instant_exchanger", "note": "Instant exchanger."},
    "godex":       {"label": "Godex", "kyc": False, "type": "instant_exchanger", "note": "No-KYC exchanger."},
    "thorchain":   {"label": "THORChain", "kyc": False, "type": "cross_chain_swap",
                    "note": "Decentralized cross-chain swap; native-asset settlement, no custodial KYC."},
    "chainflip":   {"label": "Chainflip", "kyc": False, "type": "cross_chain_swap",
                    "note": "Decentralized cross-chain swap protocol."},
    "sideshift":   {"label": "SideShift", "kyc": False, "type": "instant_exchanger", "note": "No-KYC exchanger."},
    "railway":     {"label": "Railgun", "kyc": False, "type": "privacy_pool",
                    "note": "On-chain privacy system; trace boundary."},
}

# Known service contract/hot-wallet addresses → service key (seed set; extend).
INSTANT_SWAP_ADDRESSES: dict[str, str] = {
    # THORChain routers (Ethereum)
    "0xc145990e84155416144c532e31f89b840ca8c2ce": "thorchain",
    "0xd37bbe5744d730a1d98d8dc97c42f0ca46ad7146": "thorchain",
    # FixedFloat known hot wallet (illustrative seed)
    "0x14d8ada7a0ba91f59dc0cba0d0d0d0d0d0d0d0d0": "fixedfloat",
}

_DUST_USD = 1.0          # value <= this counts as "dust" for poisoning
_MIMIC_EDGE = 4          # hex chars compared at each end for look-alike match


def _norm(a: Any) -> str:
    return str(a or "").strip().lower()


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════════════════
# B2 — Address-poisoning detection
# ═══════════════════════════════════════════════════════════════════════════
def _looks_like(a: str, b: str, edge: int = _MIMIC_EDGE) -> bool:
    """True when two addresses share a prefix+suffix of `edge` hex chars (after
    the 0x) but are not identical — the visual trick behind address poisoning."""
    a, b = _norm(a), _norm(b)
    if not a or not b or a == b:
        return False
    ax = a[2:] if a.startswith("0x") else a
    bx = b[2:] if b.startswith("0x") else b
    if len(ax) < edge * 2 or len(bx) < edge * 2:
        return False
    return ax[:edge] == bx[:edge] and ax[-edge:] == bx[-edge:]


def detect_address_poisoning(subject: str, transfers: list[dict[str, Any]],
                             edge: int = _MIMIC_EDGE) -> dict[str, Any]:
    """Detect look-alike dust poisoning targeting `subject`.

    `transfers` items: {from, to, value_usd?/value?, token?, tx_hash?, timestamp?}.
    Method: (1) learn the subject's *real* counterparties (meaningful value),
    (2) flag inbound dust/zero transfers whose sender mimics a real counterparty's
    prefix+suffix. Each hit names the poisoning address and the address it spoofs.
    """
    subj = _norm(subject)
    real_counterparties: set[str] = set()
    inbound_dust: list[dict[str, Any]] = []

    for t in transfers:
        frm, to = _norm(t.get("from")), _norm(t.get("to"))
        val = _num(t.get("value_usd", t.get("value")))
        other = frm if to == subj else to if frm == subj else ""
        if other and val > _DUST_USD:
            real_counterparties.add(other)
        # inbound (to subject) with ~zero value → candidate poison
        if to == subj and frm and frm != subj and val <= _DUST_USD:
            inbound_dust.append(t)

    hits: list[dict[str, Any]] = []
    poison_addrs: set[str] = set()
    for t in inbound_dust:
        frm = _norm(t.get("from"))
        for real in real_counterparties:
            if _looks_like(frm, real, edge):
                poison_addrs.add(frm)
                hits.append({
                    "poison_address": t.get("from"),
                    "spoofs": real,
                    "tx_hash": t.get("tx_hash", ""),
                    "value_usd": _num(t.get("value_usd", t.get("value"))),
                    "token": t.get("token", ""),
                    "timestamp": t.get("timestamp"),
                    "detail": f"Dust transfer from an address mimicking {real[:10]}…{real[-6:]} "
                              f"— primed for copy-paste theft.",
                })
                break

    severity = "critical" if hits else "clean"
    return {
        "subject": subject,
        "real_counterparties": len(real_counterparties),
        "inbound_dust_transfers": len(inbound_dust),
        "poisoning_hits": hits,
        "poison_addresses": sorted(poison_addrs),
        "severity": severity,
        "verdict": (f"POISONING DETECTED — {len(hits)} look-alike dust transfer(s); "
                    f"verify every saved/pasted address before sending."
                    if hits else "No address-poisoning pattern in the supplied transfers."),
        "guidance": "Never copy a counterparty address from transaction history; use a verified address book. "
                    "Poison addresses should be added to the case blocklist.",
        "disclaimer": "Heuristic look-alike match on the supplied transfers; completeness depends on the input window.",
    }


# ═══════════════════════════════════════════════════════════════════════════
# B1 — Instant-exchanger / swap continuation detection
# ═══════════════════════════════════════════════════════════════════════════
def classify_swap_endpoint(address: str = "", label: str = "") -> Optional[dict[str, Any]]:
    """Return service metadata if the address or its attribution label maps to a
    known instant-exchange / cross-chain swap service, else None."""
    a = _norm(address)
    if a in INSTANT_SWAP_ADDRESSES:
        return {"key": INSTANT_SWAP_ADDRESSES[a], **INSTANT_SWAP_SERVICES[INSTANT_SWAP_ADDRESSES[a]]}
    hay = f"{label}".lower()
    for key, meta in INSTANT_SWAP_SERVICES.items():
        if key in hay or meta["label"].lower() in hay:
            return {"key": key, **meta}
    return None


def detect_swap_continuation(subject: str, transfers: list[dict[str, Any]],
                             candidate_outputs: Optional[list[dict[str, Any]]] = None,
                             value_tolerance: float = 0.05,
                             time_window_seconds: int = 21_600) -> dict[str, Any]:
    """Detect funds entering a no-KYC swap service ("dead-end") and, when
    candidate outputs are supplied, re-match them by value + time window.

    `transfers`: outgoing flows from the subject {to, to_label?, value_usd?,
    token?, tx_hash?, timestamp?}. `candidate_outputs`: observed deposits on
    other chains {from?, value_usd?, token?, chain?, tx_hash?, timestamp?}.
    """
    subj = _norm(subject)
    entries: list[dict[str, Any]] = []
    for t in transfers:
        frm = _norm(t.get("from"))
        to = _norm(t.get("to"))
        # outbound from subject
        if subj and frm and frm != subj:
            continue
        svc = classify_swap_endpoint(to, t.get("to_label", ""))
        if not svc:
            continue
        entries.append({
            "service": svc["label"],
            "service_type": svc["type"],
            "kyc": svc["kyc"],
            "deposit_address": t.get("to", ""),
            "value_usd": _num(t.get("value_usd", t.get("value"))),
            "token": t.get("token", ""),
            "tx_hash": t.get("tx_hash", ""),
            "timestamp": t.get("timestamp"),
            "note": svc["note"],
        })

    # Re-match candidate outputs by value/time window
    matches: list[dict[str, Any]] = []
    for e in entries:
        ev = e["value_usd"]
        ets = _int(e["timestamp"])
        for c in (candidate_outputs or []):
            cv = _num(c.get("value_usd", c.get("value")))
            cts = _int(c.get("timestamp"))
            if ev <= 0 or cv <= 0:
                continue
            within_val = abs(cv - ev) / ev <= value_tolerance
            within_time = ets and cts and 0 <= (cts - ets) <= time_window_seconds
            if within_val and within_time:
                conf = round(0.6 * (1 - abs(cv - ev) / (ev or 1)) +
                             0.4 * (1 - (cts - ets) / (time_window_seconds or 1)), 3)
                matches.append({
                    "entry_tx": e["tx_hash"], "service": e["service"],
                    "output_tx": c.get("tx_hash", ""), "output_chain": c.get("chain", ""),
                    "entry_usd": ev, "output_usd": cv,
                    "delay_seconds": cts - ets,
                    "confidence": max(0.0, min(1.0, conf)),
                    "detail": f"Probable continuation on {c.get('chain','?')}: "
                              f"${cv:,.0f} out ≈ ${ev:,.0f} in within {(cts-ets)//60} min.",
                })
    matches.sort(key=lambda m: -m["confidence"])

    return {
        "subject": subject,
        "swap_entries": entries,
        "entry_count": len(entries),
        "continuation_matches": matches,
        "dead_end": bool(entries) and not matches,
        "verdict": (f"{len(entries)} swap entr{'y' if len(entries)==1 else 'ies'} detected — "
                    + ("continuation re-matched on the output side." if matches
                       else "trace boundary at a no-KYC swap; supply candidate outputs on likely destination chains to re-match.")
                    if entries else "No instant-exchanger / cross-chain-swap entries in the supplied flows."),
        "disclaimer": "Service detection uses a seed registry of contracts/labels; deposit addresses rotate. "
                      "Value/time re-matching yields leads, not proof of the same funds.",
    }


# ═══════════════════════════════════════════════════════════════════════════
# B4 — Peel-chain & micro-fragmentation typology scoring
# ═══════════════════════════════════════════════════════════════════════════
def score_laundering_typologies(subject: str, transfers: list[dict[str, Any]]) -> dict[str, Any]:
    """Score modern laundering signatures over a transfer set:
      • peel chain — repeated large-in → small-out + remainder-forward.
      • micro-fragmentation — one source fanned into many small ~equal outflows.
    Returns named typologies with confidence and evidence.
    """
    subj = _norm(subject)
    out = [t for t in transfers if _norm(t.get("from")) == subj and _norm(t.get("to")) != subj]
    inc = [t for t in transfers if _norm(t.get("to")) == subj and _norm(t.get("from")) != subj]

    typologies: list[dict[str, Any]] = []

    # Micro-fragmentation: many small outflows of similar size to distinct addrs
    out_vals = [_num(t.get("value_usd", t.get("value"))) for t in out]
    distinct_dests = {_norm(t.get("to")) for t in out}
    if len(out) >= 8 and len(distinct_dests) >= 6:
        nonzero = [v for v in out_vals if v > 0]
        if nonzero:
            mean = sum(nonzero) / len(nonzero)
            var = sum((v - mean) ** 2 for v in nonzero) / len(nonzero)
            cv = (var ** 0.5) / mean if mean else 99
            small = sum(1 for v in nonzero if v <= 2000)
            if cv < 0.6 and small / len(nonzero) > 0.6:
                conf = round(min(0.95, 0.4 + 0.5 * (small / len(nonzero))), 3)
                typologies.append({
                    "typology": "micro_fragmentation",
                    "title": "Micro-fragmentation across many wallets",
                    "confidence": conf,
                    "evidence": f"{len(out)} outflows to {len(distinct_dests)} distinct wallets, "
                                f"low size variance (CV={cv:.2f}), {small} ≤ $2k.",
                    "detail": "Value split into many small, similar transfers to fresh wallets — "
                              "the 2026 fragmentation signature that raises tracing cost.",
                })

    # Peel chain: sequence where subject repeatedly forwards most value onward,
    # peeling a small amount to a side address each hop.
    ordered = sorted(out, key=lambda t: _int(t.get("timestamp")))
    peels = 0
    for i in range(len(ordered) - 1):
        a = _num(ordered[i].get("value_usd", ordered[i].get("value")))
        b = _num(ordered[i + 1].get("value_usd", ordered[i + 1].get("value")))
        if a > 0 and b > 0 and b < a and (a - b) / a < 0.25:  # forwards ≥75% onward
            peels += 1
    if peels >= 3:
        conf = round(min(0.9, 0.35 + 0.1 * peels), 3)
        typologies.append({
            "typology": "peel_chain",
            "title": "Peel chain",
            "confidence": conf,
            "evidence": f"{peels} consecutive hops forwarding ≥75% of value while peeling a remainder.",
            "detail": "Classic peel-chain laundering: the bulk moves hop-to-hop while small amounts peel off.",
        })

    # Layering breadth as a supporting signal
    layering = "high" if len(distinct_dests) >= 12 else "medium" if len(distinct_dests) >= 6 else "low"

    typologies.sort(key=lambda x: -x["confidence"])
    return {
        "subject": subject,
        "outflow_count": len(out),
        "inflow_count": len(inc),
        "distinct_destinations": len(distinct_dests),
        "layering": layering,
        "typologies": typologies,
        "verdict": (f"{len(typologies)} laundering typolog{'y' if len(typologies)==1 else 'ies'} scored."
                    if typologies else "No strong peel-chain / fragmentation signature in the supplied flows."),
        "disclaimer": "Behavioral scoring over the supplied transfers; provides investigative leads with explicit confidence.",
    }


def services_catalog() -> dict[str, Any]:
    """Expose the instant-swap registry for the UI."""
    return {
        "services": [{"key": k, **v} for k, v in INSTANT_SWAP_SERVICES.items()],
        "known_addresses": len(INSTANT_SWAP_ADDRESSES),
    }
