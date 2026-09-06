"""
Stablecoin compliance suite — "CrypTX Comply" (Next-Horizon 3.1).

GENIUS-Act-shaped compliance product for stablecoin issuers, fintechs, and
banks: a monitored address book per compliance *program*, deterministic KYT
screening runs (sanctions + attribution + mixer/obfuscation exposure), Travel
Rule threshold evaluation over submitted transfers, an examiner-facing audit
log, and a board-ready compliance report.

Design rules (house style):
  * additive — own tables in the shared cryptoosint.db, never touches others
  * deterministic, evidence-cited "leads not claims" outputs
  * degrades gracefully when optional engines/feeds are unavailable
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

# GENIUS Act / BSA-aligned obligations checklist rendered into examiner reports.
OBLIGATIONS = [
    {"id": "bsa_program", "name": "BSA/AML program",
     "requirement": "Maintain a written AML program with designated compliance officer, "
                    "training, and independent testing (GENIUS Act §4; 31 CFR 1020)."},
    {"id": "ofac", "name": "OFAC / sanctions screening",
     "requirement": "Screen all monitored flows against OFAC SDN and consolidated sanctions "
                    "lists; block or freeze on match and file within 10 business days."},
    {"id": "kyt", "name": "On-chain transaction monitoring (KYT)",
     "requirement": "Blockchain-analytics-backed monitoring able to identify illicit patterns "
                    "including cross-chain transfers, DEX activity, and deliberate obfuscation."},
    {"id": "travel_rule", "name": "Travel Rule data handling",
     "requirement": "Collect, hold, and transmit originator/beneficiary data for transfers at or "
                    "above the applicable threshold (default $3,000 US)."},
    {"id": "mixer_monitoring", "name": "Mixer / obfuscation exposure monitoring",
     "requirement": "FinCEN-bound standards: monitor for flows routed through mixers, tumblers, "
                    "no-KYC instant exchangers, or other obfuscation layers."},
    {"id": "freeze_capability", "name": "Freeze / blacklist responsiveness",
     "requirement": "Issuer-side capability (or VASP escalation path) to freeze flagged addresses "
                    "on lawful request; document time-to-freeze."},
]

TRAVEL_RULE_DEFAULT_USD = 3000.0
CTR_THRESHOLD_USD = 10000.0

ADDRESS_ROLES = ("treasury", "operations", "customer", "counterparty", "monitored")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables() -> None:
    con = _conn()
    try:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS comply_programs (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                org           TEXT DEFAULT '',
                asset         TEXT DEFAULT 'USDT',
                chains        TEXT DEFAULT '[]',
                travel_rule_usd REAL DEFAULT 3000,
                notes         TEXT DEFAULT '',
                created_at    TEXT,
                updated_at    TEXT
            );
            CREATE TABLE IF NOT EXISTS comply_addresses (
                id          TEXT PRIMARY KEY,
                program_id  TEXT NOT NULL,
                address     TEXT NOT NULL,
                chain       TEXT DEFAULT 'eth',
                role        TEXT DEFAULT 'monitored',
                label       TEXT DEFAULT '',
                added_at    TEXT,
                UNIQUE(program_id, address, chain)
            );
            CREATE INDEX IF NOT EXISTS idx_comply_addr_prog ON comply_addresses(program_id);
            CREATE TABLE IF NOT EXISTS comply_screenings (
                id          TEXT PRIMARY KEY,
                program_id  TEXT NOT NULL,
                run_at      TEXT,
                stats_json  TEXT,
                results_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_comply_scr_prog ON comply_screenings(program_id);
            CREATE TABLE IF NOT EXISTS comply_audit (
                id          TEXT PRIMARY KEY,
                program_id  TEXT,
                at          TEXT,
                actor       TEXT DEFAULT '',
                action      TEXT,
                detail      TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_comply_audit_prog ON comply_audit(program_id);
        """)
        con.commit()
    finally:
        con.close()


def _audit(program_id: str, action: str, detail: str = "", actor: str = "") -> None:
    con = _conn()
    try:
        con.execute("INSERT INTO comply_audit (id, program_id, at, actor, action, detail) VALUES (?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:16], program_id, _now(), actor, action, detail))
        con.commit()
    finally:
        con.close()


# ── Programs ─────────────────────────────────────────────────────────────────

def create_program(name: str, org: str = "", asset: str = "USDT",
                   chains: Optional[list[str]] = None,
                   travel_rule_usd: float = TRAVEL_RULE_DEFAULT_USD,
                   notes: str = "", actor: str = "") -> dict[str, Any]:
    init_tables()
    pid = uuid.uuid4().hex[:16]
    now = _now()
    con = _conn()
    try:
        con.execute(
            "INSERT INTO comply_programs (id, name, org, asset, chains, travel_rule_usd, notes, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, name, org, (asset or "USDT").upper(), json.dumps(chains or ["eth"]),
             float(travel_rule_usd or TRAVEL_RULE_DEFAULT_USD), notes, now, now))
        con.commit()
    finally:
        con.close()
    _audit(pid, "program_created", f"name={name} asset={asset}", actor)
    return get_program(pid)


def get_program(pid: str) -> Optional[dict[str, Any]]:
    con = _conn()
    try:
        row = con.execute("SELECT * FROM comply_programs WHERE id=?", (pid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["chains"] = json.loads(d.get("chains") or "[]")
        n = con.execute("SELECT COUNT(*) c FROM comply_addresses WHERE program_id=?", (pid,)).fetchone()
        d["address_count"] = n["c"] if n else 0
        last = con.execute("SELECT run_at, stats_json FROM comply_screenings WHERE program_id=? "
                           "ORDER BY run_at DESC LIMIT 1", (pid,)).fetchone()
        d["last_run_at"] = last["run_at"] if last else None
        d["last_stats"] = json.loads(last["stats_json"]) if last and last["stats_json"] else None
        return d
    finally:
        con.close()


def list_programs() -> list[dict[str, Any]]:
    init_tables()
    con = _conn()
    try:
        rows = con.execute("SELECT id FROM comply_programs ORDER BY created_at DESC").fetchall()
    finally:
        con.close()
    return [get_program(r["id"]) for r in rows]


def delete_program(pid: str, actor: str = "") -> bool:
    con = _conn()
    try:
        cur = con.execute("DELETE FROM comply_programs WHERE id=?", (pid,))
        con.execute("DELETE FROM comply_addresses WHERE program_id=?", (pid,))
        con.commit()
        deleted = cur.rowcount > 0
    finally:
        con.close()
    if deleted:
        _audit(pid, "program_deleted", "", actor)
    return deleted


# ── Address book ─────────────────────────────────────────────────────────────

def add_addresses(pid: str, entries: list[dict[str, Any]], actor: str = "") -> dict[str, Any]:
    """entries: [{address, chain?, role?, label?}]"""
    init_tables()
    added, skipped = 0, 0
    con = _conn()
    try:
        for e in entries:
            addr = (e.get("address") or "").strip()
            if not addr:
                skipped += 1
                continue
            role = e.get("role") or "monitored"
            if role not in ADDRESS_ROLES:
                role = "monitored"
            try:
                con.execute(
                    "INSERT OR IGNORE INTO comply_addresses (id, program_id, address, chain, role, label, added_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:16], pid, addr, (e.get("chain") or "eth").lower(),
                     role, e.get("label") or "", _now()))
                added += 1
            except sqlite3.Error:
                skipped += 1
        con.commit()
    finally:
        con.close()
    _audit(pid, "addresses_added", f"added={added} skipped={skipped}", actor)
    return {"added": added, "skipped": skipped, "addresses": list_addresses(pid)}


def list_addresses(pid: str) -> list[dict[str, Any]]:
    con = _conn()
    try:
        rows = con.execute("SELECT * FROM comply_addresses WHERE program_id=? ORDER BY added_at DESC", (pid,)).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def remove_address(pid: str, addr_id: str, actor: str = "") -> bool:
    con = _conn()
    try:
        cur = con.execute("DELETE FROM comply_addresses WHERE program_id=? AND id=?", (pid, addr_id))
        con.commit()
        ok = cur.rowcount > 0
    finally:
        con.close()
    if ok:
        _audit(pid, "address_removed", addr_id, actor)
    return ok


# ── Screening ────────────────────────────────────────────────────────────────

def _screen_one(address: str, chain: str) -> dict[str, Any]:
    """Deterministic per-address screen: sanctions + attribution + obfuscation labels.

    Every finding carries a source so the output is examiner-citable.
    """
    findings: list[dict[str, Any]] = []
    level = "clear"

    # 1. Sanctions (local OFAC/OpenSanctions tables — highest severity)
    try:
        import sanctions_engine
        s = sanctions_engine.screen_address(address, chain)
        if s.get("matched") or s.get("matches"):
            level = "blocked"
            for m in (s.get("matches") or [])[:5]:
                findings.append({"type": "sanctions", "severity": "critical",
                                 "detail": m.get("name") or m.get("entity") or "Sanctions list match",
                                 "source": m.get("source") or "sanctions_engine"})
            if not s.get("matches"):
                findings.append({"type": "sanctions", "severity": "critical",
                                 "detail": "Sanctions screen matched", "source": "sanctions_engine"})
    except Exception as e:  # engine unavailable — report, don't fail the run
        findings.append({"type": "engine_unavailable", "severity": "info",
                         "detail": f"sanctions engine unavailable: {e}", "source": "comply"})

    # 2. Attribution / labels (provenance-tracked)
    try:
        import attribution_engine
        att = attribution_engine.attribute(address, chain)
        for a in (att.get("attributions") or [])[:8]:
            cat = (a.get("category") or "").lower()
            sev = "high" if cat in ("mixer", "darknet", "ransomware", "scam", "sanctioned") else "info"
            if sev == "high" and level != "blocked":
                level = "review"
            findings.append({"type": "attribution", "severity": sev,
                             "detail": f"{a.get('entity') or a.get('label') or '?'} ({cat or 'label'})",
                             "source": a.get("source") or "attribution_engine",
                             "confidence": a.get("confidence")})
    except Exception:
        pass

    # 3. Known obfuscation infrastructure (mixers, no-KYC instant exchangers)
    try:
        import constants
        a = address.lower()
        if a in {x.lower() for x in constants.MIXER_CONTRACTS}:
            level = "blocked" if level != "blocked" else level
            findings.append({"type": "mixer", "severity": "critical",
                             "detail": f"Known mixer contract: {constants.MIXER_CONTRACTS.get(address, ('mixer', a))[1] if address in constants.MIXER_CONTRACTS else 'mixer'}",
                             "source": "constants.MIXER_CONTRACTS"})
    except Exception:
        pass
    try:
        import laundering_trace as lt
        seed = getattr(lt, "_SERVICE_ADDRESSES", {})
        key = seed.get(address.lower())
        if key:
            svc = getattr(lt, "_SERVICES", {}).get(key, {})
            if level == "clear":
                level = "review"
            findings.append({"type": "no_kyc_service", "severity": "high",
                             "detail": f"{svc.get('label', key)} — no-KYC {svc.get('type', 'service')}",
                             "source": "laundering_trace service registry"})
    except Exception:
        pass

    return {"address": address, "chain": chain, "level": level, "findings": findings}


def run_screening(pid: str, actor: str = "") -> dict[str, Any]:
    """Screen every address in the program book. Deterministic + local; no live chain calls."""
    prog = get_program(pid)
    if not prog:
        raise ValueError("program not found")
    addrs = list_addresses(pid)
    results = []
    for a in addrs:
        r = _screen_one(a["address"], a.get("chain") or "eth")
        r["role"] = a.get("role")
        r["label"] = a.get("label")
        results.append(r)

    stats = {
        "total": len(results),
        "blocked": sum(1 for r in results if r["level"] == "blocked"),
        "review": sum(1 for r in results if r["level"] == "review"),
        "clear": sum(1 for r in results if r["level"] == "clear"),
        "finding_counts": {},
    }
    for r in results:
        for f in r["findings"]:
            t = f["type"]
            stats["finding_counts"][t] = stats["finding_counts"].get(t, 0) + 1

    sid = uuid.uuid4().hex[:16]
    con = _conn()
    try:
        con.execute("INSERT INTO comply_screenings (id, program_id, run_at, stats_json, results_json) VALUES (?,?,?,?,?)",
                    (sid, pid, _now(), json.dumps(stats), json.dumps(results)))
        con.commit()
    finally:
        con.close()
    _audit(pid, "screening_run", f"screened={stats['total']} blocked={stats['blocked']} review={stats['review']}", actor)
    return {"id": sid, "program_id": pid, "run_at": _now(), "stats": stats, "results": results}


def list_screenings(pid: str, limit: int = 20) -> list[dict[str, Any]]:
    con = _conn()
    try:
        rows = con.execute("SELECT id, run_at, stats_json FROM comply_screenings WHERE program_id=? "
                           "ORDER BY run_at DESC LIMIT ?", (pid, limit)).fetchall()
    finally:
        con.close()
    return [{"id": r["id"], "run_at": r["run_at"], "stats": json.loads(r["stats_json"] or "{}")} for r in rows]


def get_screening(sid: str) -> Optional[dict[str, Any]]:
    con = _conn()
    try:
        row = con.execute("SELECT * FROM comply_screenings WHERE id=?", (sid,)).fetchone()
    finally:
        con.close()
    if not row:
        return None
    return {"id": row["id"], "program_id": row["program_id"], "run_at": row["run_at"],
            "stats": json.loads(row["stats_json"] or "{}"),
            "results": json.loads(row["results_json"] or "[]")}


# ── Travel Rule evaluation ───────────────────────────────────────────────────

def evaluate_transfers(pid: str, transfers: list[dict[str, Any]], actor: str = "") -> dict[str, Any]:
    """Evaluate a batch of transfers against Travel Rule / CTR thresholds and the
    screened address book. transfers: [{from, to, amount_usd, chain?, tx_hash?}]"""
    prog = get_program(pid)
    if not prog:
        raise ValueError("program not found")
    threshold = float(prog.get("travel_rule_usd") or TRAVEL_RULE_DEFAULT_USD)
    flagged: list[dict[str, Any]] = []
    for t in transfers:
        amt = float(t.get("amount_usd") or 0)
        flags = []
        if amt >= threshold:
            flags.append({"rule": "travel_rule",
                          "detail": f"Transfer ${amt:,.2f} ≥ Travel Rule threshold ${threshold:,.2f} — "
                                    "originator/beneficiary data must be collected and transmitted."})
        if amt >= CTR_THRESHOLD_USD:
            flags.append({"rule": "ctr", "detail": f"Transfer ${amt:,.2f} ≥ ${CTR_THRESHOLD_USD:,.0f} CTR threshold."})
        for side in ("from", "to"):
            addr = (t.get(side) or "").strip()
            if not addr:
                continue
            screen = _screen_one(addr, (t.get("chain") or "eth").lower())
            if screen["level"] != "clear":
                flags.append({"rule": f"counterparty_{screen['level']}",
                              "detail": f"{side} address {addr[:14]}… screened '{screen['level']}': "
                                        + "; ".join(f["detail"] for f in screen["findings"][:3])})
        if flags:
            flagged.append({**t, "flags": flags})
    result = {"evaluated": len(transfers), "flagged": len(flagged),
              "travel_rule_usd": threshold, "transfers": flagged}
    _audit(pid, "transfers_evaluated", f"evaluated={len(transfers)} flagged={len(flagged)}", actor)
    return result


# ── Examiner report & audit ──────────────────────────────────────────────────

def audit_log(pid: str, limit: int = 200) -> list[dict[str, Any]]:
    con = _conn()
    try:
        rows = con.execute("SELECT * FROM comply_audit WHERE program_id=? ORDER BY at DESC LIMIT ?",
                           (pid, limit)).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def compliance_report(pid: str) -> dict[str, Any]:
    """Board/examiner-ready snapshot: program, obligations checklist with status,
    latest screening stats, audit-trail summary."""
    prog = get_program(pid)
    if not prog:
        raise ValueError("program not found")
    runs = list_screenings(pid, limit=5)
    latest = get_screening(runs[0]["id"]) if runs else None
    log = audit_log(pid, limit=50)

    obligations = []
    for ob in OBLIGATIONS:
        status, evidence = "attention", "No evidence recorded in CrypTX yet."
        if ob["id"] == "ofac":
            if latest:
                status = "met" if latest["stats"].get("blocked", 0) == 0 else "action_required"
                evidence = (f"Latest screen ({latest['run_at'][:19]}): {latest['stats']['total']} addresses, "
                            f"{latest['stats'].get('blocked', 0)} blocked, {latest['stats'].get('review', 0)} for review.")
        elif ob["id"] == "kyt":
            if runs:
                status = "met"
                evidence = f"{len(runs)} screening run(s) recorded; deterministic evidence-cited findings per address."
        elif ob["id"] == "travel_rule":
            evals = [l for l in log if l["action"] == "transfers_evaluated"]
            if evals:
                status = "met"
                evidence = f"{len(evals)} Travel-Rule evaluation batch(es); threshold ${prog['travel_rule_usd']:,.0f}."
        elif ob["id"] == "mixer_monitoring":
            if latest:
                mixers = latest["stats"].get("finding_counts", {}).get("mixer", 0) + \
                         latest["stats"].get("finding_counts", {}).get("no_kyc_service", 0)
                status = "met" if mixers == 0 else "action_required"
                evidence = f"Obfuscation-infrastructure findings in latest screen: {mixers}."
        elif ob["id"] == "freeze_capability":
            try:
                import recovery_ops
                s = recovery_ops.summary()
                if s.get("total_requests"):
                    status = "met"
                    evidence = (f"{s['total_requests']} freeze request(s) tracked; "
                                f"${s['value_frozen_or_seized_usd']:,.2f} frozen/seized via Recovery Ops.")
                else:
                    evidence = "Freeze Desk configured (Recovery Ops); no requests filed yet."
                    status = "attention"
            except Exception:
                pass
        elif ob["id"] == "bsa_program":
            status = "attention"
            evidence = "Attach the written AML program externally; CrypTX records the monitoring evidence."
        obligations.append({**ob, "status": status, "evidence": evidence})

    return {
        "generated_at": _now(),
        "program": prog,
        "obligations": obligations,
        "latest_screening": {"run_at": latest["run_at"], "stats": latest["stats"]} if latest else None,
        "screening_history": runs,
        "audit_entries": len(log),
        "disclaimer": "CrypTX Comply findings are deterministic leads with cited sources — not legal advice. "
                      "Regulatory obligations summarized from the GENIUS Act / BSA; verify with counsel.",
    }
