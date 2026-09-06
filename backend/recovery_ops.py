"""
Recovery last-mile & operations engine (Domain D).

Where 2026 investigations actually end: not a report, but an issuer/VASP
freeze-and-seize request. Models the T3-style pipeline for smaller agencies —
generate a structured, evidence-backed freeze-request package targeting the
right party (stablecoin issuer or exchange compliance desk), and track it to
resolution.

Own SQLite table in the shared cryptoosint.db (additive — never touches
existing tables). Deterministic issuer routing by asset/chain.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH

# ── Freeze-target routing: who can actually freeze a given asset ─────────────
ISSUER_TARGETS: dict[str, dict[str, Any]] = {
    "USDT": {"issuer": "Tether", "channel": "T3 Financial Crime Unit / Tether LE portal",
             "authority": "Issuer-level freeze (freeze/blacklist) on supported chains",
             "chains": ["eth", "trx", "bsc", "sol", "avax"],
             "note": "Tether can freeze USDT at the issuer level; route via law-enforcement request."},
    "USDC": {"issuer": "Circle", "channel": "Circle law-enforcement request",
             "authority": "Issuer-level freeze (blacklist) on supported chains",
             "chains": ["eth", "sol", "base", "arb", "avax", "matic"],
             "note": "Circle can freeze USDC addresses on a valid legal request."},
    "PYUSD": {"issuer": "Paxos", "channel": "Paxos compliance / law-enforcement",
              "authority": "Issuer-level freeze", "chains": ["eth", "sol"],
              "note": "Paxos-issued stablecoin; issuer freeze available."},
    "USDP": {"issuer": "Paxos", "channel": "Paxos compliance / law-enforcement",
             "authority": "Issuer-level freeze", "chains": ["eth"], "note": "Paxos stablecoin."},
}

STATUSES = ("draft", "submitted", "acknowledged", "frozen", "seized", "rejected", "closed")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def init_tables() -> None:
    con = _conn()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS recovery_requests (
                id            TEXT PRIMARY KEY,
                case_id       TEXT,
                created_at    TEXT,
                updated_at    TEXT,
                status        TEXT,
                address       TEXT,
                chain         TEXT,
                asset         TEXT,
                amount_usd    REAL,
                target_type   TEXT,     -- 'issuer' | 'vasp'
                target_name   TEXT,
                channel       TEXT,
                reason        TEXT,
                evidence_json TEXT,
                package_json  TEXT,
                history_json  TEXT
            )
        """)
        con.commit()
    finally:
        con.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def route_target(asset: str, chain: str = "", vasp_name: str = "") -> dict[str, Any]:
    """Resolve who can freeze this asset. Stablecoins → issuer; else → VASP desk."""
    a = (asset or "").upper()
    if a in ISSUER_TARGETS:
        meta = ISSUER_TARGETS[a]
        supported = (not chain) or (chain.lower() in meta["chains"])
        return {
            "target_type": "issuer",
            "target_name": meta["issuer"],
            "channel": meta["channel"],
            "authority": meta["authority"],
            "chain_supported": supported,
            "note": meta["note"] if supported else
                    f"{meta['issuer']} freezes {a} on {', '.join(meta['chains'])}; chain '{chain}' not listed — verify.",
        }
    # Non-issuer asset → the receiving VASP's compliance desk is the lever
    return {
        "target_type": "vasp",
        "target_name": vasp_name or "Receiving VASP / exchange compliance desk",
        "channel": "Exchange law-enforcement / compliance request",
        "authority": "Account freeze at the custodial endpoint (requires the deposit to have reached a VASP)",
        "chain_supported": True,
        "note": "Non-issuer asset: freezing requires the funds to sit at a custodial VASP. "
                "Trace to the off-ramp first, then serve the receiving exchange.",
    }


def build_package(address: str, chain: str, asset: str, amount_usd: float,
                  case_id: str = "", reason: str = "", vasp_name: str = "",
                  evidence: Optional[list[dict[str, Any]]] = None,
                  requester: str = "") -> dict[str, Any]:
    """Assemble a structured freeze-request package (not yet persisted)."""
    target = route_target(asset, chain, vasp_name)
    pkg = {
        "generated_at": _now(),
        "requester": requester,
        "subject": {"address": address, "chain": chain, "asset": asset,
                    "amount_usd": round(float(amount_usd or 0), 2)},
        "target": target,
        "reason": reason or "Funds identified as proceeds of an offense; freeze requested pending legal process.",
        "evidence_bundle": evidence or [],
        "required_attachments": [
            "Chain-of-custody trail (Evidence Vault export)",
            "Daubert methodology appendix for the tracing methods relied upon",
            "Court-presentable graph exhibit(s) with SHA-256 of underlying data",
            "Legal instrument (subpoena / court order / MLAT) per the target's requirements",
        ],
        "cover_note": _cover_note(address, chain, asset, amount_usd, target, reason),
    }
    return {"target": target, "package": pkg}


def _cover_note(address: str, chain: str, asset: str, amount_usd: float,
                target: dict[str, Any], reason: str) -> str:
    return (
        f"To: {target['target_name']} — {target['channel']}\n"
        f"Re: Request to freeze {asset} at address {address} ({chain}).\n\n"
        f"Approx. value: ${float(amount_usd or 0):,.2f}. {target['authority']}.\n"
        f"Basis: {reason or 'Funds traced as proceeds of an offense.'}\n\n"
        f"A full evidence bundle (chain-of-custody, methodology appendix, and graph exhibits) is attached. "
        f"We request preservation and freezing of the above address pending service of legal process."
    )


def create_request(address: str, chain: str, asset: str, amount_usd: float,
                   case_id: str = "", reason: str = "", vasp_name: str = "",
                   evidence: Optional[list[dict[str, Any]]] = None,
                   requester: str = "") -> dict[str, Any]:
    init_tables()
    built = build_package(address, chain, asset, amount_usd, case_id, reason, vasp_name, evidence, requester)
    rid = uuid.uuid4().hex[:16]
    now = _now()
    history = [{"at": now, "status": "draft", "by": requester, "note": "Request drafted."}]
    con = _conn()
    try:
        con.execute(
            """INSERT INTO recovery_requests
               (id, case_id, created_at, updated_at, status, address, chain, asset, amount_usd,
                target_type, target_name, channel, reason, evidence_json, package_json, history_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, case_id, now, now, "draft", address, chain, (asset or "").upper(), float(amount_usd or 0),
             built["target"]["target_type"], built["target"]["target_name"], built["target"]["channel"],
             reason, json.dumps(evidence or []), json.dumps(built["package"]), json.dumps(history)),
        )
        con.commit()
    finally:
        con.close()
    return get_request(rid)


def get_request(rid: str) -> Optional[dict[str, Any]]:
    con = _conn()
    try:
        row = con.execute("SELECT * FROM recovery_requests WHERE id=?", (rid,)).fetchone()
    finally:
        con.close()
    return _row_to_dict(row) if row else None


def list_requests(case_id: str = "", status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    init_tables()
    q = "SELECT * FROM recovery_requests WHERE 1=1"
    args: list[Any] = []
    if case_id:
        q += " AND case_id=?"; args.append(case_id)
    if status:
        q += " AND status=?"; args.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"; args.append(limit)
    con = _conn()
    try:
        rows = con.execute(q, args).fetchall()
    finally:
        con.close()
    return [_row_to_dict(r) for r in rows]


def update_status(rid: str, status: str, note: str = "", by: str = "") -> Optional[dict[str, Any]]:
    if status not in STATUSES:
        raise ValueError(f"invalid status '{status}'")
    cur = get_request(rid)
    if not cur:
        return None
    history = cur.get("history", [])
    history.append({"at": _now(), "status": status, "by": by, "note": note})
    con = _conn()
    try:
        con.execute("UPDATE recovery_requests SET status=?, updated_at=?, history_json=? WHERE id=?",
                    (status, _now(), json.dumps(history), rid))
        con.commit()
    finally:
        con.close()
    return get_request(rid)


def summary() -> dict[str, Any]:
    init_tables()
    con = _conn()
    try:
        rows = con.execute("SELECT status, COUNT(*) c, COALESCE(SUM(amount_usd),0) v FROM recovery_requests GROUP BY status").fetchall()
    finally:
        con.close()
    by_status = {r["status"]: {"count": r["c"], "amount_usd": round(r["v"], 2)} for r in rows}
    frozen = by_status.get("frozen", {}).get("amount_usd", 0) + by_status.get("seized", {}).get("amount_usd", 0)
    return {
        "by_status": by_status,
        "total_requests": sum(v["count"] for v in by_status.values()),
        "value_frozen_or_seized_usd": round(frozen, 2),
    }


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in ("evidence_json", "package_json", "history_json"):
        if k in d and d[k]:
            try:
                d[k.replace("_json", "")] = json.loads(d[k])
            except (ValueError, TypeError):
                d[k.replace("_json", "")] = None
        d.pop(k, None)
    return d
