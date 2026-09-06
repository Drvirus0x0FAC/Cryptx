"""
Deterministic synthetic fixtures for detector tests AND the labeled benchmark.

Every generator is seeded — identical corpora on every run, so measured
precision/recall numbers are reproducible (a Daubert requirement: testability
and known error rates presume a fixed, re-runnable benchmark).
"""
from __future__ import annotations

import random
from typing import Any

SUBJECT = "0x" + "a1" * 20
THOR_ROUTER = "0xc145990e84155416144c532e31f89b840ca8c2ce"  # labeled in laundering_trace
T0 = 1_700_000_000

HEX = "0123456789abcdef"


def _addr(rng: random.Random) -> str:
    return "0x" + "".join(rng.choice(HEX) for _ in range(40))


def _lookalike(real: str, rng: random.Random, edge: int = 6) -> str:
    """Address sharing `edge` leading and trailing hex chars with `real`."""
    body = "".join(rng.choice(HEX) for _ in range(40 - 2 * edge))
    return "0x" + real[2:2 + edge] + body + real[-edge:]


# ── Address poisoning ────────────────────────────────────────────────────────

def poisoning_case(positive: bool, seed: int) -> dict[str, Any]:
    """One labeled wallet history. Positive → contains a look-alike dust transfer."""
    rng = random.Random(seed)
    real = _addr(rng)
    transfers = [
        {"from": SUBJECT, "to": real, "value_usd": rng.uniform(500, 20_000),
         "tx_hash": f"0xreal{seed}", "timestamp": T0},
        {"from": _addr(rng), "to": SUBJECT, "value_usd": rng.uniform(50, 400),
         "tx_hash": f"0xnoise{seed}", "timestamp": T0 + 100},
    ]
    dust_sender = _lookalike(real, rng) if positive else _addr(rng)
    # HARD cases (every 5th positive): the attacker sends $1.01 — just above the
    # detector's dust ceiling. Still a real poisoning attempt (label stays True),
    # so misses here surface as honest false negatives in the benchmark.
    dust_value = 1.01 if (positive and seed % 5 == 4) else 0.0
    transfers.append({"from": dust_sender, "to": SUBJECT, "value_usd": dust_value,
                      "tx_hash": f"0xdust{seed}", "timestamp": T0 + 600})
    return {"label": positive, "subject": SUBJECT, "transfers": transfers}


# ── Instant-exchanger / swap continuation ────────────────────────────────────

def swap_case(positive: bool, seed: int) -> dict[str, Any]:
    rng = random.Random(1000 + seed)
    value = rng.uniform(5_000, 50_000)
    dest = THOR_ROUTER if positive else _addr(rng)
    transfers = [{"from": SUBJECT, "to": dest, "value_usd": value,
                  "tx_hash": f"0xin{seed}", "timestamp": T0}]
    outputs = [{"from": _addr(rng), "value_usd": value * rng.uniform(0.96, 0.99),
                "chain": "btc", "tx_hash": f"0xout{seed}", "timestamp": T0 + rng.randint(600, 7_200)}]
    # decoy output far outside the value tolerance
    outputs.append({"from": _addr(rng), "value_usd": value * 3.5, "chain": "btc",
                    "tx_hash": f"0xdecoy{seed}", "timestamp": T0 + 900})
    return {"label": positive, "subject": SUBJECT, "transfers": transfers, "outputs": outputs}


# ── Tornado-style demix pairing ──────────────────────────────────────────────

def tornado_case(positive: bool, seed: int) -> dict[str, Any]:
    """Positive → the true deposit shares denomination + window (+ relayer) with
    the withdrawal, decoys don't. Negative → no valid same-denomination deposit
    inside the window."""
    rng = random.Random(2000 + seed)
    denom = rng.choice([1, 10, 100])
    relayer = _addr(rng)
    w_time = T0 + 40_000
    withdrawals = [{"tx_hash": f"0xw{seed}", "recipient": _addr(rng),
                    "denomination": denom, "timestamp": w_time, "relayer": relayer}]
    deposits = []
    if positive:
        deposits.append({"tx_hash": f"0xdT{seed}", "address": _addr(rng), "denomination": denom,
                         "timestamp": w_time - rng.randint(1_000, 20_000), "relayer": relayer})
        # decoys: wrong denomination / outside window
        deposits.append({"tx_hash": f"0xdX{seed}", "address": _addr(rng),
                         "denomination": denom * 10 if denom < 100 else 1,
                         "timestamp": w_time - 5_000, "relayer": ""})
        # HARD cases (every 4th positive): a second same-denomination deposit
        # inside the window with a different relayer — a realistic ambiguity.
        # If the engine ranks the ambiguous decoy first, that's an honest
        # top-1 pairing error counted against precision/recall.
        if seed % 4 == 3:
            deposits.append({"tx_hash": f"0xdA{seed}", "address": _addr(rng), "denomination": denom,
                             "timestamp": w_time - rng.randint(1_000, 20_000), "relayer": _addr(rng)})
    else:
        deposits.append({"tx_hash": f"0xdF{seed}", "address": _addr(rng), "denomination": denom,
                         "timestamp": w_time - 200_000, "relayer": ""})   # outside 24h window
        deposits.append({"tx_hash": f"0xdG{seed}", "address": _addr(rng),
                         "denomination": denom * 10 if denom < 100 else 1,
                         "timestamp": w_time - 3_000, "relayer": ""})     # wrong denom
    return {"label": positive, "deposits": deposits, "withdrawals": withdrawals,
            "true_deposit": f"0xdT{seed}" if positive else None}


# ── Contract static scan ─────────────────────────────────────────────────────

MALICIOUS_SELECTOR_SETS = [
    ["40c10f19", "f9f92be4", "8456cb59"],              # mint + blacklist + pause
    ["40c10f19", "f2fde38b", "8456cb59", "3659cfe6"],  # mint + owner + pause + proxy upgrade
    ["f9f92be4", "3659cfe6", "8456cb59"],              # blacklist + upgrade + pause
]
BENIGN_SELECTOR_SETS = [
    ["a9059cbb", "095ea7b3", "70a08231", "18160ddd"],  # transfer/approve/balanceOf/totalSupply
    ["a9059cbb", "70a08231", "dd62ed3e"],
    ["70a08231", "18160ddd", "313ce567", "06fdde03"],  # views only
]


def contract_case(positive: bool, seed: int) -> dict[str, Any]:
    rng = random.Random(3000 + seed)
    sels = rng.choice(MALICIOUS_SELECTOR_SETS if positive else BENIGN_SELECTOR_SETS)
    return {"label": positive, "abi_selectors": list(sels)}


# ── Approval-drain exposure ──────────────────────────────────────────────────

def approval_case(positive: bool, seed: int) -> dict[str, Any]:
    rng = random.Random(4000 + seed)
    bad_spender = _addr(rng)
    if positive:
        approvals = [{"token": _addr(rng), "token_symbol": "USDT",
                      "spender": bad_spender, "amount": "infinite"}]
        malicious = [bad_spender]
    else:
        approvals = [{"token": _addr(rng), "token_symbol": "USDC",
                      "spender": _addr(rng), "amount": 500}]
        malicious = [bad_spender]  # present in the list but not approved
    return {"label": positive, "approvals": approvals, "malicious": malicious}


# ── Forensic motifs (fan-out dispersal) ──────────────────────────────────────

def fanout_case(positive: bool, seed: int) -> dict[str, Any]:
    rng = random.Random(5000 + seed)
    n = rng.randint(6, 12) if positive else rng.randint(1, 3)
    edges = [{"source": SUBJECT, "target": _addr(rng),
              "value": rng.uniform(10, 500), "token": "ETH", "timestamp": T0 + i * 60}
             for i, _ in enumerate(range(n))]
    edges.append({"source": _addr(rng), "target": SUBJECT, "value": 1000,
                  "token": "ETH", "timestamp": T0 - 600})
    return {"label": positive, "subject": SUBJECT, "edges": edges}


# ── Corpus assembly (used by the benchmark runner) ───────────────────────────

def corpus(n_per_class: int = 25) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for name, gen in (
        ("address_poisoning", poisoning_case),
        ("swap_continuation", swap_case),
        ("demix_pairing", tornado_case),
        ("contract_static_scan", contract_case),
        ("approval_exposure", approval_case),
        ("fan_out_motif", fanout_case),
    ):
        cases = [gen(True, i) for i in range(n_per_class)] + \
                [gen(False, i) for i in range(n_per_class)]
        out[name] = cases
    return out
