"""
CrypTX conference demo dataset - "Operation Ember Forge".

A fully offline, self-contained Lazarus / TraderTraitor style investigation
(modeled on the Feb 2025 Bybit heist) used to showcase every CrypTX capability
without any live API calls. Seeded into the database by ``seed_demo.py`` and
served to the compute-heavy endpoints via a demo short-circuit in
``crypto_osint.lookup_crypto_address``.

Nothing here performs network I/O - every value is baked.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

# Deterministic case id so the seed is idempotent (re-running replaces cleanly).
DEMO_CASE_ID = "demo0000-0000-4000-a000-embe4f0463e0"
DEMO_CASE_NAME = "Operation Ember Forge - Bybit $1.46B Heist"
DEMO_BOARD_ID = "brd_demo_emberforge01"

CHAIN = "ETH"
ETHERSCAN = "https://etherscan.io/address/"

# ── Cast of addresses (the laundering chain) ────────────────────────────────────
# role drives colour/shape on the board and the narrative.
EXPLOITER      = "0x47666fab8bd0ac7003bce3f5c3585383f09486e2"  # real reported Bybit exploiter
STAGING_1      = "0xa4b2e6f5c1d9083b7e4f0a2c6d8e1f3a5b7c9d0e"
STAGING_2      = "0xf1c3a5e7092b4d6f8a0c2e4b6d8f0a1c3e5b7d90"
MIXER_TORNADO  = "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b"  # Tornado Cash Router (OFAC)
SWAP_EXCH      = "0x0000000000a84d1a9b0063a910315c7ffa9cd248"  # eXch (no-KYC swap)
BRIDGE_THOR    = "0xb2a1c3d5e7f90a2b4c6d8e0f1a3b5c7d9e0f1a2b"  # THORChain router (demo)
MULE_1         = "0xc3d5e7f90a1b2c4d6e8f0a2b4c6d8e0f1a3b5c7d"
MULE_2         = "0xa1b3c5d7e9f0a2b4c6d8e0f1a3b5c7d9e0f1a2b3"
CONSOLIDATION  = "0xd4e6f8a0b2c4d6e8f0a1b3c5d7e9f0a2b4c6d8e0"
EXCH_DEPOSIT   = "0xe5f7a9b1c3d5e7f90a2b4c6d8e0f1a3b5c7d9e0f"

# BTC leg (post-bridge cash-out through a BTC mixer)
CASHOUT_BTC    = "bc1q5shngj24323nsrmxv99652zqqvcpxszqp86wm4"  # ChipMixer-style (demo)

ALL_ADDRESSES = [
    EXPLOITER, STAGING_1, STAGING_2, MIXER_TORNADO, SWAP_EXCH, BRIDGE_THOR,
    MULE_1, MULE_2, CONSOLIDATION, EXCH_DEPOSIT, CASHOUT_BTC,
]

# case_addresses rows: (address, chain, label, risk_score, risk_level, notes)
CASE_ADDRESSES: List[Dict[str, Any]] = [
    {"address": EXPLOITER, "chain": "ETH", "label": "Bybit Exploiter - Lazarus/TraderTraitor",
     "risk_score": 98, "risk_level": "CRITICAL",
     "notes": "Primary attacker wallet. Received ~401,347 ETH drained from Bybit cold wallet on 2025-02-21."},
    {"address": STAGING_1, "chain": "ETH", "label": "Lazarus Staging Wallet 1",
     "risk_score": 94, "risk_level": "CRITICAL",
     "notes": "First-hop distribution wallet. Split proceeds into 40+ peel chains within 48h."},
    {"address": STAGING_2, "chain": "ETH", "label": "Lazarus Staging Wallet 2",
     "risk_score": 92, "risk_level": "CRITICAL",
     "notes": "Parallel staging wallet; funneled to Tornado Cash and eXch."},
    {"address": MIXER_TORNADO, "chain": "ETH", "label": "Tornado Cash Router (OFAC SDN)",
     "risk_score": 99, "risk_level": "CRITICAL",
     "notes": "OFAC-sanctioned mixer. Received layered 100 ETH deposits from staging wallets."},
    {"address": SWAP_EXCH, "chain": "ETH", "label": "eXch - no-KYC Swap",
     "risk_score": 88, "risk_level": "HIGH",
     "notes": "No-KYC instant exchange used to swap ETH→BTC/XMR mid-laundering."},
    {"address": BRIDGE_THOR, "chain": "ETH", "label": "THORChain Router (cross-chain)",
     "risk_score": 76, "risk_level": "HIGH",
     "notes": "Cross-chain bridge hop ETH→BTC. ~$150M routed in <72h."},
    {"address": MULE_1, "chain": "ETH", "label": "Layering Mule A",
     "risk_score": 79, "risk_level": "HIGH",
     "notes": "Pass-through mule, 12 hops, held funds <30 min each."},
    {"address": MULE_2, "chain": "ETH", "label": "Layering Mule B",
     "risk_score": 74, "risk_level": "HIGH",
     "notes": "Pass-through mule paralleling Mule A."},
    {"address": CONSOLIDATION, "chain": "ETH", "label": "Consolidation Wallet",
     "risk_score": 66, "risk_level": "MEDIUM",
     "notes": "Re-aggregated peeled outputs before exchange placement."},
    {"address": EXCH_DEPOSIT, "chain": "ETH", "label": "Exchange Deposit (Tier-2 CEX)",
     "risk_score": 61, "risk_level": "MEDIUM",
     "notes": "Deposit address at a Tier-2 exchange flagged for weak KYC. Cash-out endpoint."},
    {"address": CASHOUT_BTC, "chain": "BTC", "label": "BTC Cash-out via Mixer",
     "risk_score": 84, "risk_level": "HIGH",
     "notes": "Post-bridge BTC consolidated through a CoinJoin/mixer before OTC placement."},
]

# ── Case notes (investigation narrative) ────────────────────────────────────────
CASE_NOTES: List[str] = [
    "2025-02-21 - Bybit reports unauthorized transfer of ~401,347 ETH (~$1.46B) from an "
    "ETH cold wallet during a routine multisig transfer. Signing UI was spoofed (Safe{Wallet} "
    "supply-chain compromise). Attribution: DPRK Lazarus Group / TraderTraitor (FBI PIN, 2025-02-26).",
    "Phase 1 (Distribution): exploiter wallet fanned funds into 2 staging wallets, then 40+ "
    "peel chains. Median hold time per hop < 30 minutes - automated layering.",
    "Phase 2 (Obfuscation): staging wallets deposited into Tornado Cash (OFAC SDN) in 100 ETH "
    "tranches and swapped ETH via eXch (no-KYC). Cross-chain hops to BTC via THORChain.",
    "Phase 3 (Placement): consolidated outputs routed to a Tier-2 CEX deposit address (weak KYC) "
    "and a BTC mixer feeding OTC desks. ~$150M traced to placement; remainder dormant.",
    "Compliance: exploiter + Tornado router match OFAC SDN. Two victim referrals filed. "
    "Evidence bundle hashed into the tamper-evident vault (chain-of-custody intact).",
]

# ── Local labels (attribution) ──────────────────────────────────────────────────
# (address, chain, label, category, risk_weight, confidence, source, notes)
LABELS: List[Dict[str, Any]] = [
    {"address": EXPLOITER, "chain": "ETH", "label": "Lazarus Group (TraderTraitor)", "category": "threat_actor",
     "risk_weight": 100, "confidence": 0.98, "source": "FBI PIN + internal", "notes": "DPRK state-sponsored."},
    {"address": STAGING_1, "chain": "ETH", "label": "Lazarus Staging", "category": "threat_actor",
     "risk_weight": 95, "confidence": 0.9, "source": "cluster analysis", "notes": "Co-spend with exploiter."},
    {"address": STAGING_2, "chain": "ETH", "label": "Lazarus Staging", "category": "threat_actor",
     "risk_weight": 92, "confidence": 0.88, "source": "cluster analysis", "notes": ""},
    {"address": MIXER_TORNADO, "chain": "ETH", "label": "Tornado Cash", "category": "mixer",
     "risk_weight": 100, "confidence": 1.0, "source": "OFAC SDN", "notes": "Sanctioned 2022-08-08."},
    {"address": SWAP_EXCH, "chain": "ETH", "label": "eXch", "category": "no_kyc_swap",
     "risk_weight": 85, "confidence": 0.95, "source": "internal", "notes": "No-KYC instant swap."},
    {"address": BRIDGE_THOR, "chain": "ETH", "label": "THORChain", "category": "bridge",
     "risk_weight": 60, "confidence": 0.8, "source": "internal", "notes": "Cross-chain router."},
    {"address": EXCH_DEPOSIT, "chain": "ETH", "label": "Tier-2 CEX deposit", "category": "exchange",
     "risk_weight": 40, "confidence": 0.7, "source": "internal", "notes": "Weak-KYC venue."},
    {"address": CASHOUT_BTC, "chain": "BTC", "label": "BTC Mixer / OTC", "category": "mixer",
     "risk_weight": 80, "confidence": 0.85, "source": "internal", "notes": "CoinJoin placement."},
]


# ── Baked Address-Intel (offline short-circuit for /address, /nexus) ─────────────
def _tx(h: str, frm: str, to: str, value: float, token: str, ts: str, direction: str) -> Dict[str, Any]:
    return {"hash": h, "time": ts, "from": frm, "to": to, "direction": direction,
            "value": value, "value_eth": value if token == "ETH" else None, "token": token,
            "confirmed": True, "is_error": False}


def _sanctioned(name: str, category: str, desc: str) -> Dict[str, Any]:
    return {"sanctioned": True, "source": "ofac_local",
            "identifications": [{"name": name, "category": category, "description": desc}]}


def _clean() -> Dict[str, Any]:
    return {"sanctioned": False, "source": "ofac_local", "identifications": []}


def _intel(address: str, *, balance: float, unit: str, portfolio: float, received: float,
           tx_count: int, first: str, last: str, sanctions: Dict[str, Any],
           bridges: int, swaps: int, risk_level: str, recent: List[Dict[str, Any]],
           tokens: List[Dict[str, Any]] | None = None, arkham: Dict[str, Any] | None = None,
           scam: Dict[str, Any] | None = None, chain: str = "ETH") -> Dict[str, Any]:
    return {
        "address": address, "chain": chain, "detected_chain": chain,
        "balance": balance, "balance_unit": unit, "portfolio_usd": portfolio,
        "total_received": received, "tx_count": tx_count,
        "native_tx_count": tx_count, "token_tx_count": len(tokens or []),
        "first_seen": first, "last_seen": last,
        "recent_txs": recent, "token_txs": [], "tokens": tokens or [],
        "chain_hop_swap": {
            "bridge_hits": [
                {"counterparty": BRIDGE_THOR, "name": "THORChain", "type": "bridge", "chain": chain,
                 "tx_hash": "0xbridge" + "a" * 58, "direction": "OUT", "value": 4200, "token": "ETH"}
            ] if bridges else [],
            "swap_hits": [
                {"counterparty": SWAP_EXCH, "name": "eXch", "type": "no_kyc_swap", "chain": chain,
                 "tx_hash": "0xswap" + "b" * 60, "direction": "OUT", "value": 900, "token": "ETH"}
            ] if swaps else [],
            "bridge_count": bridges, "swap_count": swaps,
            "heuristics": ([{"type": "chain_hop", "severity": "high",
                             "evidence": "ETH→BTC via THORChain within 6h of mixer deposit"}] if bridges else []),
            "possible_chain_hopping": bool(bridges), "possible_chain_swapping": bool(swaps),
            "risk_level": risk_level,
        },
        "sanctions": sanctions,
        "arkham": arkham or {"found": False},
        "scam_reports": scam or {"found": False},
        "explorer": (ETHERSCAN + address) if chain == "ETH" else "",
        "source": "CrypTX demo dataset (Operation Ember Forge) - offline",
    }


def build_demo_intel() -> Dict[str, Dict[str, Any]]:
    """Registry: normalized address -> baked intel dict."""
    reg: Dict[str, Dict[str, Any]] = {}

    reg[EXPLOITER] = _intel(
        EXPLOITER, balance=12403.5, unit="ETH", portfolio=41_900_000, received=401_347.0,
        tx_count=1287, first="2025-02-21 06:14 UTC", last="2025-03-14 22:41 UTC",
        sanctions=_sanctioned("Lazarus Group / TraderTraitor (DPRK)", "Cyber",
                              "OFAC SDN - DPRK state-sponsored threat actor; Bybit exploiter wallet."),
        bridges=6, swaps=9, risk_level="high",
        arkham={"found": True, "name": "Bybit Exploiter", "entity_name": "Lazarus Group",
                "entity_type": "threat_actor", "label": "Bybit Hack 2025",
                "label_type": "hack", "chains_seen": ["ETH", "BTC"], "balance_usd": 41_900_000},
        tokens=[{"symbol": "ETH", "name": "Ether", "balance": 12403.5, "usd_value": 41_900_000},
                {"symbol": "mETH", "name": "Mantle Staked ETH", "balance": 15000, "usd_value": 52_500_000}],
        recent=[
            _tx("0x" + "1" * 64, "0x1542f7...bybitcold", EXPLOITER, 401347.0, "ETH", "2025-02-21 06:14 UTC", "IN"),
            _tx("0x" + "2" * 64, EXPLOITER, STAGING_1, 120000.0, "ETH", "2025-02-21 09:02 UTC", "OUT"),
            _tx("0x" + "3" * 64, EXPLOITER, STAGING_2, 118500.0, "ETH", "2025-02-21 09:47 UTC", "OUT"),
            _tx("0x" + "4" * 64, EXPLOITER, MIXER_TORNADO, 100.0, "ETH", "2025-02-22 03:10 UTC", "OUT"),
            _tx("0x" + "5" * 64, EXPLOITER, BRIDGE_THOR, 4200.0, "ETH", "2025-02-23 14:22 UTC", "OUT"),
        ],
    )

    reg[STAGING_1] = _intel(
        STAGING_1, balance=210.2, unit="ETH", portfolio=710_000, received=120_000.0,
        tx_count=642, first="2025-02-21 09:02 UTC", last="2025-03-09 11:03 UTC",
        sanctions=_clean(), bridges=3, swaps=7, risk_level="high",
        arkham={"found": True, "name": "Lazarus Staging", "entity_type": "threat_actor",
                "label": "Bybit Hack 2025", "chains_seen": ["ETH"]},
        recent=[
            _tx("0x" + "6" * 64, EXPLOITER, STAGING_1, 120000.0, "ETH", "2025-02-21 09:02 UTC", "IN"),
            _tx("0x" + "7" * 64, STAGING_1, MIXER_TORNADO, 100.0, "ETH", "2025-02-22 01:20 UTC", "OUT"),
            _tx("0x" + "8" * 64, STAGING_1, SWAP_EXCH, 900.0, "ETH", "2025-02-22 05:44 UTC", "OUT"),
            _tx("0x" + "9" * 64, STAGING_1, MULE_1, 5400.0, "ETH", "2025-02-22 07:31 UTC", "OUT"),
        ],
    )

    reg[MIXER_TORNADO] = _intel(
        MIXER_TORNADO, balance=88123.9, unit="ETH", portfolio=298_000_000, received=1_240_000.0,
        tx_count=98421, first="2019-12-16 00:00 UTC", last="2025-03-14 22:00 UTC",
        sanctions=_sanctioned("Tornado Cash", "Cyber", "OFAC SDN - sanctioned mixer (2022-08-08)."),
        bridges=0, swaps=0, risk_level="high",
        recent=[
            _tx("0x" + "a" * 64, STAGING_1, MIXER_TORNADO, 100.0, "ETH", "2025-02-22 01:20 UTC", "IN"),
            _tx("0x" + "b" * 64, STAGING_2, MIXER_TORNADO, 100.0, "ETH", "2025-02-22 02:05 UTC", "IN"),
        ],
    )
    return reg


DEMO_INTEL: Dict[str, Dict[str, Any]] = build_demo_intel()

# Metadata for every demo address (for the fallback intel below).
_CASE_META = {a["address"].lower(): a for a in CASE_ADDRESSES}


def _fallback_intel(address: str) -> Dict[str, Any]:
    """Minimal-but-plausible intel for demo addresses without a hand-authored record,
    so every demo address opens cleanly in Address Intel while fully offline."""
    meta = _CASE_META[address.lower()]
    chain = meta.get("chain", "ETH")
    unit = "BTC" if chain == "BTC" else "ETH"
    risky = meta.get("risk_score", 0) >= 80
    sanctioned = "Tornado" in meta["label"] or "Exploiter" in meta["label"]
    return _intel(
        address, balance=round(50 + meta.get("risk_score", 0) * 1.7, 2), unit=unit,
        portfolio=meta.get("risk_score", 0) * 42000, received=meta.get("risk_score", 0) * 3100.0,
        tx_count=120 + meta.get("risk_score", 0) * 4,
        first="2025-02-21 10:00 UTC", last="2025-03-10 18:00 UTC",
        sanctions=_sanctioned(meta["label"], "Cyber", "OFAC SDN (demo).") if sanctioned else _clean(),
        bridges=2 if risky else 0, swaps=3 if risky else 0,
        risk_level="high" if risky else "medium",
        chain=chain,
        recent=[
            _tx("0x" + "c" * 64, EXPLOITER, address, 5400.0, unit, "2025-02-22 07:31 UTC", "IN"),
            _tx("0x" + "d" * 64, address, CONSOLIDATION, 5100.0, unit, "2025-02-24 09:00 UTC", "OUT"),
        ],
    )


def lookup_demo_intel(address: str) -> Dict[str, Any] | None:
    """Return a deep copy of baked intel if this is a demo address, else None."""
    if not address:
        return None
    key = address.strip().lower()
    if key in DEMO_INTEL:
        return copy.deepcopy(DEMO_INTEL[key])
    if key in _CASE_META:
        return _fallback_intel(key)
    return None


# ── Investigation board (the visual centerpiece) ────────────────────────────────
_ROLE_STYLE = {
    "source":   {"color": "#ff2d55", "shape": "diamond"},
    "staging":  {"color": "#ff5a30", "shape": "circle"},
    "mixer":    {"color": "#ff2d55", "shape": "diamond"},
    "swap":     {"color": "#ff9f0a", "shape": "circle"},
    "bridge":   {"color": "#ffd60a", "shape": "circle"},
    "mule":     {"color": "#8e9db5", "shape": "circle"},
    "consol":   {"color": "#4aa3ff", "shape": "circle"},
    "exchange": {"color": "#22c578", "shape": "circle"},
    "btc":      {"color": "#f7931a", "shape": "circle"},
}


def _short(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}" if len(a) > 14 else a


def build_board_state() -> Dict[str, Any]:
    # (id, address, chain, role, label, x, y)
    layout = [
        ("n_src",   EXPLOITER,     "eth", "source",   "Bybit Exploiter", 80, 340),
        ("n_st1",   STAGING_1,     "eth", "staging",  "Staging 1",       320, 200),
        ("n_st2",   STAGING_2,     "eth", "staging",  "Staging 2",       320, 480),
        ("n_tc",    MIXER_TORNADO, "eth", "mixer",    "Tornado Cash",    600, 120),
        ("n_exch",  SWAP_EXCH,     "eth", "swap",     "eXch (no-KYC)",   600, 300),
        ("n_thor",  BRIDGE_THOR,   "eth", "bridge",   "THORChain",       600, 480),
        ("n_m1",    MULE_1,        "eth", "mule",     "Mule A",          860, 240),
        ("n_m2",    MULE_2,        "eth", "mule",     "Mule B",          860, 420),
        ("n_con",   CONSOLIDATION, "eth", "consol",   "Consolidation",   1120, 320),
        ("n_cex",   EXCH_DEPOSIT,  "eth", "exchange", "Tier-2 CEX",      1380, 220),
        ("n_btc",   CASHOUT_BTC,   "btc", "btc",      "BTC Cash-out",    1380, 460),
    ]
    nodes: List[Dict[str, Any]] = []
    for nid, addr, chain, role, label, x, y in layout:
        style = _ROLE_STYLE[role]
        nodes.append({
            "id": nid, "kind": "address", "ref": addr, "chain": chain,
            "label": f"{label}\n{_short(addr)}", "caption": label, "note": "",
            "x": x, "y": y, "color": style["color"], "shape": style["shape"],
        })

    # Cluster + note annotations
    nodes.append({"id": "n_cluster_laz", "kind": "cluster", "ref": "", "chain": "",
                  "label": "Lazarus cluster (co-spend)", "caption": "", "note": "",
                  "x": 200, "y": 60, "color": "#ff2d55", "shape": "square"})
    nodes.append({"id": "n_note_heist", "kind": "note", "ref": "", "chain": "",
                  "label": "Bybit cold-wallet drain\n401,347 ETH (~$1.46B)\n2025-02-21",
                  "caption": "", "note": "", "x": 60, "y": 150, "color": "#ffd60a", "shape": "square"})
    nodes.append({"id": "n_note_ofac", "kind": "note", "ref": "", "chain": "",
                  "label": "OFAC SDN match\nExploiter + Tornado router",
                  "caption": "", "note": "", "x": 600, "y": 20, "color": "#bf5af2", "shape": "square"})

    def edge(eid, src, tgt, asset, value, ts, cross=False, label=""):
        return {"id": eid, "source": src, "target": tgt, "asset": asset, "value": value,
                "valueUsd": None, "txHash": "0x" + eid.replace("e_", "") + "f" * 40,
                "ts": ts, "kind": "transfer", "label": label, "crossChain": cross}

    edges = [
        edge("e_1", "n_src", "n_st1", "ETH", 120000, 1740121320),
        edge("e_2", "n_src", "n_st2", "ETH", 118500, 1740124020),
        edge("e_3", "n_st1", "n_tc", "ETH", 100, 1740187200, label="100 ETH tranche"),
        edge("e_4", "n_st2", "n_tc", "ETH", 100, 1740189900, label="100 ETH tranche"),
        edge("e_5", "n_st1", "n_exch", "ETH", 900, 1740201840),
        edge("e_6", "n_st2", "n_thor", "ETH", 4200, 1740321720, cross=True, label="ETH→BTC"),
        edge("e_7", "n_st1", "n_m1", "ETH", 5400, 1740209460),
        edge("e_8", "n_st2", "n_m2", "ETH", 4900, 1740211200),
        edge("e_9", "n_m1", "n_con", "ETH", 5100, 1740308400),
        edge("e_10", "n_m2", "n_con", "ETH", 4600, 1740312000),
        edge("e_11", "n_exch", "n_con", "ETH", 850, 1740315600),
        edge("e_12", "n_con", "n_cex", "ETH", 8200, 1740402000),
        edge("e_13", "n_thor", "n_btc", "BTC", 61.4, 1740405600, cross=True, label="bridge out"),
        edge("e_14", "n_con", "n_btc", "ETH", 2100, 1740409200, cross=True, label="ETH→BTC"),
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "clusters": [{"id": "cl_laz", "name": "Lazarus Group", "members": ["n_src", "n_st1", "n_st2"],
                      "collapsed": False, "color": "#ff2d55"}],
        "viewport": {"x": 40, "y": 40, "z": 0.82},
        "preferences": {"fiat": False, "showGlyphs": True, "labelDensity": "normal"},
    }


# ── Evidence vault records ──────────────────────────────────────────────────────
EVIDENCE: List[Dict[str, Any]] = [
    {"evidence_type": "attribution", "title": "OFAC SDN match - Exploiter wallet", "subject": EXPLOITER,
     "chain": "ETH", "tags": ["ofac", "lazarus", "sanctions"],
     "content": {"list": "OFAC SDN", "entity": "Lazarus Group / TraderTraitor",
                 "match_type": "exact_address", "confidence": 0.98},
     "notes": "Address enumerated on OFAC SDN list; DPRK nexus."},
    {"evidence_type": "trace", "title": "Peel-chain trace - Exploiter → Tornado Cash", "subject": EXPLOITER,
     "chain": "ETH", "tags": ["trace", "mixer", "layering"],
     "content": {"hops": 5, "terminal": "Tornado Cash (OFAC)", "value_eth": 100,
                 "path": [EXPLOITER, STAGING_1, MIXER_TORNADO]},
     "notes": "Automated layering, <30 min hold per hop."},
    {"evidence_type": "screenshot", "title": "THORChain cross-chain swap receipt", "subject": BRIDGE_THOR,
     "chain": "ETH", "tags": ["bridge", "cross-chain"],
     "content": {"from_chain": "ETH", "to_chain": "BTC", "value_eth": 4200, "usd": 14_700_000},
     "notes": "ETH→BTC hop within 6h of mixer deposit."},
]

# ── Victim reports ──────────────────────────────────────────────────────────────
VICTIM_REPORTS: List[Dict[str, Any]] = [
    {"scam_type": "exchange_hack", "scammer_address": EXPLOITER, "chain": "ETH",
     "amount_usd": 1_460_000_000, "token": "ETH", "incident_date": "2025-02-21",
     "description": "Bybit cold-wallet compromise via spoofed Safe{Wallet} signing UI. "
                    "401,347 ETH drained. Attributed to Lazarus/TraderTraitor.",
     "contact_name": "Bybit Security (demo)", "jurisdiction": "UAE / global",
     "tags": ["lazarus", "exchange", "dprk"]},
    {"scam_type": "phishing", "scammer_address": STAGING_2, "chain": "ETH",
     "amount_usd": 240_000, "token": "USDT", "incident_date": "2025-02-24",
     "description": "Retail victim funds swept into Lazarus staging wallet via address-poisoning "
                    "during the laundering window.",
     "contact_name": "Individual complainant (demo)", "jurisdiction": "US",
     "tags": ["address-poisoning", "retail"]},
]

# ── OSINT sweep (cached result for the exploiter) ───────────────────────────────
OSINT_SWEEP = {
    "address": EXPLOITER,
    "risk_signal": "critical",
    "sources": [
        {"source": "chainabuse", "ok": True, "status": "hit", "category": "abuse",
         "count": 37, "note": "Multiple Bybit-hack reports"},
        {"source": "x_twitter", "ok": True, "status": "hit", "category": "social",
         "count": 210, "note": "ZachXBT + community tagging"},
        {"source": "github", "ok": True, "status": "hit", "category": "code",
         "count": 4, "note": "Address in public IOC lists"},
        {"source": "ahmia_darkweb", "ok": True, "status": "clear", "category": "darkweb", "count": 0},
    ],
    "signals": [
        {"severity": "critical", "label": "OFAC SDN", "detail": "Exploiter wallet on OFAC SDN list"},
        {"severity": "high", "label": "Community-flagged", "detail": "247 public abuse/social reports"},
    ],
    "summary": "Exploiter wallet is heavily community-flagged and OFAC-sanctioned; strong DPRK attribution.",
}

# ── AI-style narrative report (report artifact, HTML) ───────────────────────────
REPORT_TITLE = "Operation Ember Forge - Investigation Report"
REPORT_HTML = """
<h1>Operation Ember Forge - Bybit $1.46B Heist</h1>
<p><strong>Subject:</strong> 0x4766…86e2 (Bybit Exploiter) · <strong>Attribution:</strong> DPRK Lazarus Group / TraderTraitor · <strong>Confidence:</strong> High</p>
<h2>Executive summary</h2>
<p>On 2025-02-21 an attacker drained ~401,347 ETH (~$1.46B) from a Bybit ETH cold wallet by spoofing
the Safe{Wallet} multisig signing interface. Proceeds were layered through staging wallets, Tornado Cash
(OFAC-sanctioned), the no-KYC swap eXch, and cross-chained to Bitcoin via THORChain before placement at a
Tier-2 exchange and a BTC mixer.</p>
<h2>Laundering typology</h2>
<ul>
<li><strong>Distribution</strong> - fan-out to 2 staging wallets and 40+ peel chains, &lt;30 min hold per hop.</li>
<li><strong>Obfuscation</strong> - 100 ETH Tornado Cash tranches; ETH→BTC via THORChain; ETH swaps via eXch.</li>
<li><strong>Placement</strong> - consolidation wallet → Tier-2 CEX deposit + BTC CoinJoin/OTC.</li>
</ul>
<h2>Compliance flags</h2>
<p>Exploiter wallet and Tornado Cash router match the OFAC SDN list. Two victim referrals filed. Evidence
bundle hashed into the tamper-evident vault (chain-of-custody intact).</p>
<h2>Recommended actions</h2>
<ol>
<li>File SAR/STR referencing OFAC SDN exposure.</li>
<li>Notify Tier-2 CEX of tainted deposit address for freeze.</li>
<li>Continue monitoring dormant peel outputs for reactivation.</li>
</ol>
<p><em>Generated by CrypTX - demo dataset. Not financial or legal advice.</em></p>
"""

# ── Forensic run (populates nexus/forensic graph tables) ────────────────────────
def build_forensic_payload() -> Dict[str, Any]:
    addresses = [
        {"address": EXPLOITER, "chain": "ETH", "role": "hack_source", "risk_score": 98,
         "first_seen": "2025-02-21", "last_seen": "2025-03-14", "label": "Bybit Exploiter",
         "features": {"tx_count": 1287, "in_degree": 3, "out_degree": 44, "total_in": 401347.0,
                      "total_out": 388900.0, "mixer_exposure": 0.72}},
        {"address": STAGING_1, "chain": "ETH", "role": "pass_through_mule", "risk_score": 94,
         "first_seen": "2025-02-21", "last_seen": "2025-03-09", "label": "Staging 1",
         "features": {"tx_count": 642, "in_degree": 1, "out_degree": 41, "total_in": 120000.0,
                      "total_out": 119800.0, "mixer_exposure": 0.61}},
        {"address": STAGING_2, "chain": "ETH", "role": "pass_through_mule", "risk_score": 92,
         "first_seen": "2025-02-21", "last_seen": "2025-03-08", "label": "Staging 2",
         "features": {"tx_count": 588, "in_degree": 1, "out_degree": 38, "total_in": 118500.0,
                      "total_out": 118300.0, "mixer_exposure": 0.58}},
        {"address": MIXER_TORNADO, "chain": "ETH", "role": "mixer", "risk_score": 99,
         "first_seen": "2019-12-16", "last_seen": "2025-03-14", "label": "Tornado Cash",
         "features": {"tx_count": 98421, "in_degree": 5100, "out_degree": 5030, "mixer_exposure": 1.0}},
    ]
    transactions = [
        {"tx_hash": "0x" + "1" * 64, "chain": "ETH", "timestamp": "2025-02-21 06:14 UTC", "token": "ETH", "value": 401347.0},
        {"tx_hash": "0x" + "2" * 64, "chain": "ETH", "timestamp": "2025-02-21 09:02 UTC", "token": "ETH", "value": 120000.0},
        {"tx_hash": "0x" + "3" * 64, "chain": "ETH", "timestamp": "2025-02-21 09:47 UTC", "token": "ETH", "value": 118500.0},
        {"tx_hash": "0x" + "a" * 64, "chain": "ETH", "timestamp": "2025-02-22 01:20 UTC", "token": "ETH", "value": 100.0},
    ]
    edges = [
        {"chain": "ETH", "tx_hash": "0x" + "2" * 64, "source": EXPLOITER, "target": STAGING_1, "token": "ETH", "value": 120000.0, "timestamp": "2025-02-21 09:02 UTC"},
        {"chain": "ETH", "tx_hash": "0x" + "3" * 64, "source": EXPLOITER, "target": STAGING_2, "token": "ETH", "value": 118500.0, "timestamp": "2025-02-21 09:47 UTC"},
        {"chain": "ETH", "tx_hash": "0x" + "a" * 64, "source": STAGING_1, "target": MIXER_TORNADO, "token": "ETH", "value": 100.0, "timestamp": "2025-02-22 01:20 UTC"},
        {"chain": "ETH", "tx_hash": "0x" + "b" * 64, "source": STAGING_2, "target": MIXER_TORNADO, "token": "ETH", "value": 100.0, "timestamp": "2025-02-22 02:05 UTC"},
    ]
    outputs = [
        {"address": EXPLOITER, "chain": "ETH", "algorithm": "role_classifier",
         "output": {"role": "hack_source", "confidence": 0.97}, "confidence": 0.97},
        {"address": EXPLOITER, "chain": "ETH", "algorithm": "taint_flow",
         "output": {"mixer_exposure": 0.72, "sanctioned_exposure": 0.81}, "confidence": 0.9},
        {"address": STAGING_1, "chain": "ETH", "algorithm": "motif_detection",
         "output": {"motif": "peel_chain", "hops": 41}, "confidence": 0.88},
    ]
    summary = {
        "subject": EXPLOITER, "chain": "ETH", "risk_score": 98, "risk_level": "CRITICAL",
        "headline": "Lazarus/TraderTraitor peel-chain laundering of Bybit heist proceeds",
        "node_count": len(addresses), "edge_count": len(edges),
        "typologies": ["peel_chain", "mixer_layering", "cross_chain_hop", "sanctioned_exposure"],
        "mixer_exposure": 0.72, "sanctioned_exposure": 0.81,
    }
    return {"subject": EXPLOITER, "chain": "ETH", "summary": summary, "addresses": addresses,
            "transactions": transactions, "edges": edges, "outputs": outputs,
            "algorithm_version": "demo-1.0"}
