"""
Smart-contract crime forensics engine (Domain A).

Local, deterministic, evidence-first analysis of smart contracts — no paid
vendor intelligence. Mirrors the app's "leads, not claims" language: every
finding carries a rule id, a human explanation, a severity, and the concrete
evidence (selector, opcode, source line, or hardcoded address) it fired on, so
the output is court-defensible rather than a black-box score.

Capabilities
------------
A1  scan_contract(bytecode?, source?, abi?)     — malicious-pattern risk scan
A2  fingerprint_bytecode(bytecode)              — opcode + selector fingerprint
    compare_fingerprints(a, b)                  — similarity 0..1 (Jaccard/cosine)
    match_library(bytecode, library?)           — nearest known-malicious contracts
A3  reconstruct_incident(txs, contract?)         — exploit post-mortem assembly
A4  approval_exposure(approvals)                 — wallet-level live-approval scan

All functions are pure (no I/O). Routers may optionally enrich inputs with the
existing chain fetchers before calling in; the engine never requires network.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable, Optional

# ── EVM opcode table (subset that matters for security heuristics) ────────────
# name -> byte value
_OPCODES = {
    "STOP": 0x00, "ADD": 0x01, "MUL": 0x02, "SUB": 0x03, "DIV": 0x04,
    "SDIV": 0x05, "MOD": 0x06, "EXP": 0x0A, "LT": 0x10, "GT": 0x11,
    "EQ": 0x14, "ISZERO": 0x15, "AND": 0x16, "OR": 0x17, "NOT": 0x19,
    "SHL": 0x1B, "SHR": 0x1C, "SHA3": 0x20, "ADDRESS": 0x30,
    "BALANCE": 0x31, "ORIGIN": 0x32, "CALLER": 0x33, "CALLVALUE": 0x34,
    "CALLDATALOAD": 0x35, "CODECOPY": 0x39, "EXTCODESIZE": 0x3B,
    "EXTCODECOPY": 0x3C, "TIMESTAMP": 0x42, "NUMBER": 0x43, "MLOAD": 0x51,
    "MSTORE": 0x52, "SLOAD": 0x54, "SSTORE": 0x55, "JUMP": 0x56,
    "JUMPI": 0x57, "JUMPDEST": 0x5B, "PUSH1": 0x60, "PUSH4": 0x63,
    "PUSH20": 0x73, "PUSH32": 0x7F, "DUP1": 0x80, "SWAP1": 0x90,
    "LOG0": 0xA0, "LOG3": 0xA3, "CREATE": 0xF0, "CALL": 0xF1,
    "CALLCODE": 0xF2, "RETURN": 0xF3, "DELEGATECALL": 0xF4,
    "CREATE2": 0xF5, "STATICCALL": 0xFA, "REVERT": 0xFD,
    "INVALID": 0xFE, "SELFDESTRUCT": 0xFF,
}
_OPNAME = {v: k for k, v in _OPCODES.items()}

# ── Function selectors of interest (4-byte) — the on-chain fingerprints of
#    the powers a malicious/administrable contract exposes. ─────────────────────
# selector -> (signature, rule_id, severity, explanation)
_SELECTOR_RULES: dict[str, tuple[str, str, str, str]] = {
    "a22cb465": ("setApprovalForAll(address,bool)", "blanket_nft_approval", "medium",
                 "Blanket NFT operator approval — a malicious operator can move every token in an approving wallet."),
    "095ea7b3": ("approve(address,uint256)", "erc20_approval", "info",
                 "Standard ERC-20 approval; drain risk only if the spender is malicious or the amount is infinite."),
    "42966c68": ("burn(uint256)", "burn", "info",
                 "Token burn present."),
    "40c10f19": ("mint(address,uint256)", "privileged_mint", "high",
                 "Owner-callable mint — supply can be inflated after launch (rug/dilution vector)."),
    "449a52f8": ("mintTo(address,uint256)", "privileged_mint", "high",
                 "Owner-callable mint-to — arbitrary supply issuance."),
    "8456cb59": ("pause()", "pausable", "medium",
                 "Pausable transfers — issuer can freeze all movement (honeypot / soft-rug vector)."),
    "3f4ba83a": ("unpause()", "pausable", "info", "Unpause counterpart to pause()."),
    "f2fde38b": ("transferOwnership(address)", "ownable", "info",
                 "Ownable — a single owner key holds privileged powers."),
    "715018a6": ("renounceOwnership()", "renounce", "info",
                 "Ownership can be renounced (mitigates owner-key risk if actually called)."),
    "f9f92be4": ("blacklist(address)", "blacklist", "high",
                 "Address blacklist — issuer can block selected holders from selling (honeypot vector)."),
    "0ecb93c0": ("addBlackList(address)", "blacklist", "high",
                 "Blacklist control (Tether-style) — selected addresses can be blocked."),
    "e4997dc5": ("removeBlackList(address)", "blacklist", "info", "Blacklist removal counterpart."),
    "f3bdc228": ("removeBlackList(address)", "blacklist", "info", "Blacklist removal counterpart."),
    "89b8d3b6": ("setMaxTxAmount(uint256)", "max_tx_limit", "medium",
                 "Adjustable max-transaction limit — can be set to near-zero to trap sellers."),
    "751039fc": ("setFee(uint256)", "mutable_fee", "high",
                 "Mutable transfer fee/tax — can be raised to ~100% to block sells (honeypot)."),
    "8f70ccf7": ("setTaxFeePercent(uint256)", "mutable_fee", "high",
                 "Mutable tax percentage — sell tax can be raised arbitrarily."),
    "3659cfe6": ("upgradeTo(address)", "upgradeable_proxy", "high",
                 "Upgradeable proxy — contract logic can be swapped for a malicious implementation."),
    "4f1ef286": ("upgradeToAndCall(address,bytes)", "upgradeable_proxy", "high",
                 "Upgradeable proxy with call — logic swap plus arbitrary post-upgrade call."),
    "5c60da1b": ("implementation()", "proxy", "info", "Proxy implementation pointer present."),
    "24d7806c": ("setAuthority(address)", "authority", "medium", "Mutable authority controller."),
    "01ffc9a7": ("supportsInterface(bytes4)", "erc165", "info", "ERC-165 interface detection."),
}

# Source-code keyword patterns → same rule vocabulary (used when verified
# Solidity is available; complements the selector scan).
_SOURCE_PATTERNS: list[tuple[str, str, str, str]] = [
    (r"\bselfdestruct\s*\(", "selfdestruct", "high",
     "selfdestruct present — contract (and any held funds) can be destroyed by the privileged caller."),
    (r"\bdelegatecall\s*\(", "delegatecall", "high",
     "delegatecall present — executes external code in this contract's storage context (upgrade/backdoor vector)."),
    (r"function\s+_?mint\b", "privileged_mint", "high",
     "Internal/again-callable mint path — verify it is not reachable by an owner-only function post-launch."),
    (r"onlyOwner", "ownable", "info", "Owner-gated functions present."),
    (r"blacklist|_isBlacklisted|isBlackListed", "blacklist", "high",
     "Blacklist logic in source — holders can be blocked from transferring (honeypot vector)."),
    (r"_maxTxAmount|maxTransactionAmount", "max_tx_limit", "medium",
     "Max-transaction cap in source — can be tuned to trap sellers."),
    (r"tradingEnabled|canTrade|_tradingOpen", "trading_gate", "medium",
     "Trading on/off gate — sells can be disabled by the owner (classic honeypot)."),
    (r"require\s*\(\s*(from|sender)\s*==\s*owner", "sell_restriction", "high",
     "Transfer restricted to owner — non-owners may be unable to sell (honeypot)."),
    (r"\b(sellFee|sellTax)\b.{0,40}=", "mutable_fee", "high",
     "Mutable sell fee/tax in source — can be raised to block sells."),
    (r"assembly\s*\{", "inline_assembly", "info",
     "Inline assembly present — increases audit surface; review for hidden logic."),
]

# Hidden-value knock-outs for severity → numeric weight
_SEV_WEIGHT = {"critical": 100, "high": 60, "medium": 30, "low": 12, "info": 3}
_INFINITE = int("f" * 60, 16)  # ~uint256 max threshold for "infinite" approvals


# ═══════════════════════════════════════════════════════════════════════════
# A1 — Contract risk scan
# ═══════════════════════════════════════════════════════════════════════════
def _clean_hex(s: str) -> str:
    s = (s or "").strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    return re.sub(r"[^0-9a-fA-F]", "", s)


def extract_selectors_from_bytecode(bytecode: str) -> list[str]:
    """Extract 4-byte function selectors from a contract's dispatcher.

    The Solidity dispatcher compares calldata's selector against constants
    loaded with PUSH4. Scanning for the PUSH4 (0x63) immediates recovers the
    contract's public function selectors without an ABI. Best-effort; skips
    push payloads correctly so we don't misread PUSH data as opcodes.
    """
    code = _clean_hex(bytecode)
    if not code:
        return []
    try:
        b = bytes.fromhex(code)
    except ValueError:
        return []
    out: list[str] = []
    i = 0
    n = len(b)
    while i < n:
        op = b[i]
        if op == 0x63 and i + 4 < n:  # PUSH4
            out.append(b[i + 1:i + 5].hex())
            i += 5
            continue
        if 0x60 <= op <= 0x7F:  # PUSH1..PUSH32 — skip immediate
            i += 1 + (op - 0x5F)
            continue
        i += 1
    # de-dup, preserve order
    seen: set[str] = set()
    uniq = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _opcode_histogram(bytecode: str) -> Counter:
    code = _clean_hex(bytecode)
    hist: Counter = Counter()
    if not code:
        return hist
    try:
        b = bytes.fromhex(code)
    except ValueError:
        return hist
    i = 0
    n = len(b)
    while i < n:
        op = b[i]
        hist[_OPNAME.get(op, f"0x{op:02x}")] += 1
        if 0x60 <= op <= 0x7F:
            i += 1 + (op - 0x5F)
        else:
            i += 1
    return hist


def scan_contract(
    address: str = "",
    chain: str = "eth",
    bytecode: str = "",
    source: str = "",
    abi_selectors: Optional[Iterable[str]] = None,
    verified: Optional[bool] = None,
) -> dict[str, Any]:
    """Deterministic malicious-pattern scan of a smart contract.

    Any of bytecode / source / abi_selectors may be supplied. Returns a
    verdict, a 0-100 risk score, and evidence-cited findings.
    """
    findings: list[dict[str, Any]] = []
    fired: set[str] = set()

    def _add(rule_id: str, severity: str, title: str, detail: str, evidence: str, source_hint: str):
        key = f"{rule_id}:{evidence}"
        if key in fired:
            return
        fired.add(key)
        findings.append({
            "rule_id": rule_id,
            "severity": severity,
            "title": title,
            "detail": detail,
            "evidence": evidence,
            "method": source_hint,  # 'selector' | 'source' | 'opcode' | 'address'
        })

    # Selectors — from ABI if given, else recovered from bytecode
    selectors = [s.lower().lstrip("0x") for s in (abi_selectors or [])]
    if not selectors and bytecode:
        selectors = extract_selectors_from_bytecode(bytecode)
    for sel in selectors:
        rule = _SELECTOR_RULES.get(sel)
        if rule:
            sig, rule_id, sev, expl = rule
            _add(rule_id, sev, sig, expl, f"selector 0x{sel} ({sig})", "selector")

    # Source keyword scan
    if source:
        for pattern, rule_id, sev, expl in _SOURCE_PATTERNS:
            m = re.search(pattern, source, re.IGNORECASE)
            if m:
                _add(rule_id, sev, rule_id.replace("_", " ").title(), expl,
                     f"source match: “{m.group(0)[:60]}”", "source")

    # Bytecode opcode heuristics
    hist = _opcode_histogram(bytecode) if bytecode else Counter()
    if hist.get("DELEGATECALL"):
        _add("delegatecall", "high", "delegatecall opcode",
             "delegatecall in bytecode — proxy/upgrade or code-injection surface; verify the implementation target.",
             f"DELEGATECALL ×{hist['DELEGATECALL']}", "opcode")
    if hist.get("SELFDESTRUCT"):
        _add("selfdestruct", "high", "selfdestruct opcode",
             "selfdestruct in bytecode — contract can be destroyed; escrowed value at risk.",
             f"SELFDESTRUCT ×{hist['SELFDESTRUCT']}", "opcode")
    if hist.get("CREATE2"):
        _add("create2", "medium", "CREATE2 factory",
             "CREATE2 present — deterministic deployment; used by drainer factories to pre-compute attack addresses.",
             f"CREATE2 ×{hist['CREATE2']}", "opcode")

    # Score = capped sum of severity weights, with diminishing returns
    raw = sum(_SEV_WEIGHT.get(f["severity"], 0) for f in findings)
    score = min(100, round(100 * (1 - math.exp(-raw / 90.0))))
    # Verdict language stays investigative
    if score >= 80:
        verdict = "CRITICAL — multiple owner-abuse / honeypot indicators"
    elif score >= 55:
        verdict = "HIGH — significant privileged-control surface"
    elif score >= 30:
        verdict = "ELEVATED — administrable contract; review before trusting"
    elif findings:
        verdict = "LOW — standard patterns only"
    else:
        verdict = "CLEAN — no flagged patterns in supplied artifacts"

    honeypot_rules = {"blacklist", "mutable_fee", "trading_gate", "sell_restriction", "max_tx_limit", "pausable"}
    is_honeypot_suspect = len({f["rule_id"] for f in findings} & honeypot_rules) >= 2

    return {
        "address": address,
        "chain": chain,
        "verified_source": bool(source) if verified is None else verified,
        "analyzed": {
            "bytecode": bool(bytecode),
            "source": bool(source),
            "selectors": len(selectors),
        },
        "risk_score": score,
        "verdict": verdict,
        "honeypot_suspect": is_honeypot_suspect,
        "findings": sorted(findings, key=lambda f: -_SEV_WEIGHT.get(f["severity"], 0)),
        "selectors_found": selectors[:64],
        "disclaimer": "Investigative leads from static analysis of the supplied artifacts. "
                      "Absence of a finding is not a safety guarantee; confirm on-chain behavior before relying on this.",
    }


# ═══════════════════════════════════════════════════════════════════════════
# A2 — Bytecode fingerprint & similarity (attacker-contract clustering)
# ═══════════════════════════════════════════════════════════════════════════
def fingerprint_bytecode(bytecode: str) -> dict[str, Any]:
    """Compute an order-independent fingerprint: opcode histogram (normalized)
    + the set of public function selectors. Basis for similarity matching."""
    hist = _opcode_histogram(bytecode)
    total = sum(hist.values()) or 1
    vector = {k: v / total for k, v in hist.items()}
    selectors = extract_selectors_from_bytecode(bytecode)
    code = _clean_hex(bytecode)
    return {
        "size_bytes": len(code) // 2,
        "opcode_vector": vector,
        "selectors": sorted(selectors),
        "selector_count": len(selectors),
    }


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def compare_fingerprints(fa: dict[str, Any], fb: dict[str, Any]) -> dict[str, Any]:
    """Similarity 0..1 blending opcode-cosine (structure) and selector-Jaccard
    (interface). Weighted 60/40 toward structure."""
    cos = _cosine(fa.get("opcode_vector", {}), fb.get("opcode_vector", {}))
    jac = _jaccard(set(fa.get("selectors", [])), set(fb.get("selectors", [])))
    score = round(0.6 * cos + 0.4 * jac, 4)
    shared = sorted(set(fa.get("selectors", [])) & set(fb.get("selectors", [])))
    return {
        "similarity": score,
        "opcode_cosine": round(cos, 4),
        "selector_jaccard": round(jac, 4),
        "shared_selectors": shared,
        "verdict": ("near-identical (likely same author/template)" if score >= 0.9
                    else "strongly similar" if score >= 0.75
                    else "partially similar" if score >= 0.5
                    else "dissimilar"),
    }


def match_library(bytecode: str, library: Optional[list[dict[str, Any]]] = None,
                  threshold: float = 0.5, top_k: int = 10) -> dict[str, Any]:
    """Match a target contract against a library of known contracts.

    `library` items: {"label": str, "bytecode"?: str, "fingerprint"?: {...},
    "tag"?: str}. Returns nearest matches above threshold — the AnChain-style
    "one attacker contract → the attacker's whole deployment family" pivot.
    """
    target = fingerprint_bytecode(bytecode)
    matches: list[dict[str, Any]] = []
    for item in (library or []):
        fp = item.get("fingerprint") or (fingerprint_bytecode(item["bytecode"]) if item.get("bytecode") else None)
        if not fp:
            continue
        cmp = compare_fingerprints(target, fp)
        if cmp["similarity"] >= threshold:
            matches.append({
                "label": item.get("label", "unnamed"),
                "tag": item.get("tag", ""),
                **cmp,
            })
    matches.sort(key=lambda m: -m["similarity"])
    return {
        "target_fingerprint": {"size_bytes": target["size_bytes"],
                               "selector_count": target["selector_count"]},
        "matches": matches[:top_k],
        "match_count": len(matches),
    }


# ═══════════════════════════════════════════════════════════════════════════
# A3 — Exploit incident reconstruction (post-mortem)
# ═══════════════════════════════════════════════════════════════════════════
_EXPLOIT_SIGNS: list[tuple[str, str, str]] = [
    ("flashLoan", "flash_loan", "Flash-loan invocation — capital-efficient exploit primitive."),
    ("0x490e6cbc", "flash_loan", "Aave flashLoan selector observed."),
    ("reentr", "reentrancy", "Reentrancy keyword/trace — repeated callback into the victim before state settles."),
    ("delegatecall", "delegatecall_takeover", "delegatecall into attacker code — logic/storage takeover."),
    ("selfdestruct", "selfdestruct", "selfdestruct used to sweep/clean up."),
]


def reconstruct_incident(txs: list[dict[str, Any]], contract: str = "",
                         attacker: str = "") -> dict[str, Any]:
    """Assemble an exploit post-mortem from a set of transactions.

    Best-effort chronology: attacker EOA → deployed contracts → exploit calls →
    value drained → first laundering hop (hand-off point for the holistic trace).
    Each `tx`: {hash, from, to, timestamp, value_usd?, method?, input_data?,
    created_contract?, is_error?}.
    """
    events: list[dict[str, Any]] = []
    deployed: list[str] = []
    drained_usd = 0.0
    victim = (contract or "").lower()
    signatures: set[str] = set()

    ordered = sorted(txs, key=lambda t: _int(t.get("timestamp")))
    for t in ordered:
        frm = (t.get("from") or "").lower()
        to = (t.get("to") or "").lower()
        method = (t.get("method") or "")
        inp = (t.get("input_data") or "")
        blob = f"{method} {inp}".lower()
        created = t.get("created_contract")
        if created:
            deployed.append(created)
            events.append({"phase": "deploy", "hash": t.get("hash"), "actor": frm,
                           "detail": f"Deployed contract {created[:12]}…", "ts": t.get("timestamp")})
        for needle, sig_id, expl in _EXPLOIT_SIGNS:
            if needle.lower() in blob:
                signatures.add(sig_id)
                events.append({"phase": "exploit", "hash": t.get("hash"), "actor": frm,
                               "detail": expl, "signature": sig_id, "ts": t.get("timestamp")})
        val = _num(t.get("value_usd"))
        if victim and (frm == victim or to == victim) and val > 0:
            drained_usd += val
            events.append({"phase": "value_move", "hash": t.get("hash"), "actor": frm or to,
                           "detail": f"Value movement ${val:,.0f} involving victim contract", "ts": t.get("timestamp")})

    # laundering hand-off: last distinct counterparty the attacker sent to
    handoff = ""
    if attacker:
        atk = attacker.lower()
        outs = [t for t in ordered if (t.get("from") or "").lower() == atk and t.get("to")]
        if outs:
            handoff = outs[-1].get("to", "")

    typ = "unknown"
    if "flash_loan" in signatures:
        typ = "flash-loan-assisted exploit"
    elif "reentrancy" in signatures:
        typ = "reentrancy"
    elif "delegatecall_takeover" in signatures:
        typ = "delegatecall / logic takeover"

    return {
        "victim_contract": contract,
        "attacker": attacker,
        "incident_type": typ,
        "signatures": sorted(signatures),
        "deployed_contracts": deployed,
        "estimated_drained_usd": round(drained_usd, 2),
        "timeline": events,
        "laundering_handoff": handoff,
        "next_step": ("Hand the laundering hand-off address to Holistic Trace to follow the funds cross-chain."
                      if handoff else "No outbound laundering hop identified in the supplied transactions."),
        "disclaimer": "Reconstructed from the supplied transactions only; completeness depends on the input set.",
    }


# ═══════════════════════════════════════════════════════════════════════════
# A4 — Wallet approval-drain exposure
# ═══════════════════════════════════════════════════════════════════════════
def approval_exposure(approvals: list[dict[str, Any]],
                      malicious_spenders: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """Aggregate a wallet's *live* token approvals into an exposure report.

    `approvals` items: {token, token_symbol?, spender, spender_label?, amount?
    (int/str/'infinite'), is_nft? (setApprovalForAll), revoked? (bool),
    chain?}. Only non-revoked approvals count as live exposure.
    """
    bad = {s.lower() for s in (malicious_spenders or [])}
    live: list[dict[str, Any]] = []
    infinite_count = 0
    flagged_count = 0

    for a in approvals:
        if a.get("revoked"):
            continue
        spender = (a.get("spender") or "").lower()
        raw = a.get("amount")
        is_infinite = False
        if isinstance(raw, str) and raw.lower() in ("infinite", "unlimited", "max"):
            is_infinite = True
        else:
            try:
                is_infinite = int(raw) >= _INFINITE if raw not in (None, "") else bool(a.get("is_nft"))
            except (TypeError, ValueError):
                is_infinite = bool(a.get("is_nft"))
        if a.get("is_nft"):
            is_infinite = True
        flagged = spender in bad
        if is_infinite:
            infinite_count += 1
        if flagged:
            flagged_count += 1
        sev = "critical" if (flagged and is_infinite) else "high" if flagged else "medium" if is_infinite else "low"
        live.append({
            "token": a.get("token", ""),
            "token_symbol": a.get("token_symbol") or a.get("symbol") or "",
            "spender": a.get("spender", ""),
            "spender_label": a.get("spender_label", ""),
            "chain": a.get("chain", ""),
            "infinite": is_infinite,
            "nft_operator": bool(a.get("is_nft")),
            "flagged_malicious": flagged,
            "severity": sev,
            "recommendation": ("REVOKE NOW — infinite approval to a flagged-malicious spender."
                               if (flagged and is_infinite) else
                               "Revoke — spender flagged malicious." if flagged else
                               "Consider revoking — infinite allowance is an unbounded drain risk." if is_infinite else
                               "Bounded allowance; monitor."),
        })

    live.sort(key=lambda x: -_SEV_WEIGHT.get(x["severity"], 0))
    score = min(100, flagged_count * 40 + infinite_count * 12)
    return {
        "live_approvals": len(live),
        "infinite_approvals": infinite_count,
        "flagged_malicious": flagged_count,
        "exposure_score": score,
        "verdict": ("CRITICAL — live approvals to flagged-malicious spenders" if flagged_count else
                    "HIGH — multiple infinite approvals outstanding" if infinite_count >= 3 else
                    "ELEVATED — infinite approvals present" if infinite_count else
                    "LOW — no unbounded/flagged approvals"),
        "approvals": live,
        "disclaimer": "Exposure reflects the supplied approval set; enumerate all Approval/ApprovalForAll logs for completeness.",
    }


# ── small numeric helpers ────────────────────────────────────────────────────
def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default
