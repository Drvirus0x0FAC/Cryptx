"""
Freeze-network operationalization (Next-Horizon 3.2).

Extends Recovery Ops (Domain D1) from "build a freeze package" into an
operational T3/Beacon-style last mile:

  (a) a maintained routing DIRECTORY of issuer / VASP freeze-request intake
      channels with per-target evidence-format requirements and SLA notes;
  (b) a "Beacon-lite" WATCH loop — watchlisted case addresses are checked
      against incoming monitor notifications; the moment funds touch a labeled
      VASP/exchange (or an issuer-freezable asset moves), a freeze-request
      package is auto-drafted via recovery_ops and queued for review;
  (c) freeze KPI TELEMETRY — time-to-freeze, totals by target, monthly frozen
      value — computed from the recovery_requests status history.

Additive: own tables; reads (never writes) monitor_notifications.
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

# ── (a) Freeze-request routing directory ─────────────────────────────────────
# Intake channels an investigator can actually serve. Notes are operational
# guidance, not legal advice; verify current channel before service.
DIRECTORY: list[dict[str, Any]] = [
    {"name": "Tether (USDT)", "type": "issuer", "assets": ["USDT"],
     "chains": ["eth", "trx", "bsc", "sol", "avax", "ton"],
     "channel": "T3 Financial Crime Unit / Tether law-enforcement portal",
     "evidence_format": ["LE request on agency letterhead", "Address + chain + amount",
                         "Tracing summary with methodology", "Legal instrument or urgency basis"],
     "sla_note": "T3 has executed freezes within 24h of LE request; $450M+ frozen since Sept 2024."},
    {"name": "Circle (USDC)", "type": "issuer", "assets": ["USDC", "EURC"],
     "chains": ["eth", "sol", "base", "arb", "avax", "matic", "op"],
     "channel": "Circle law-enforcement request (le@circle.com intake)",
     "evidence_format": ["Valid legal process (subpoena/court order/MLAT)", "Address list per chain",
                         "Case summary"],
     "sla_note": "Issuer-level blacklist on lawful request; response typically days."},
    {"name": "Paxos (PYUSD/USDP)", "type": "issuer", "assets": ["PYUSD", "USDP", "BUSD"],
     "chains": ["eth", "sol"],
     "channel": "Paxos compliance / law-enforcement desk",
     "evidence_format": ["Legal process", "Address + amount + tracing basis"],
     "sla_note": "Regulated NY trust; documented freeze capability."},
    {"name": "TRON DAO / T3", "type": "network", "assets": ["USDT"],
     "chains": ["trx"],
     "channel": "T3 Financial Crime Unit (TRON-side escalation)",
     "evidence_format": ["Same as Tether T3 intake"],
     "sla_note": "TRON-native USDT is the highest-volume illicit stablecoin rail — route via T3."},
    {"name": "Binance", "type": "vasp", "assets": ["*"], "chains": ["*"],
     "channel": "Binance Law Enforcement Portal (binance.com/en/support/law-enforcement)",
     "evidence_format": ["Registered LE portal account", "Deposit tx hash + deposit address",
                         "Legal process for KYC disclosure; preservation request first"],
     "sla_note": "Account-level freeze at the custodial endpoint; preservation requests honored quickly."},
    {"name": "Coinbase", "type": "vasp", "assets": ["*"], "chains": ["*"],
     "channel": "Coinbase Law Enforcement Request portal (Kodex)",
     "evidence_format": ["Kodex-registered request", "Deposit evidence", "Legal process"],
     "sla_note": "US-regulated; emergency disclosure path for imminent harm."},
    {"name": "Kraken", "type": "vasp", "assets": ["*"], "chains": ["*"],
     "channel": "Kraken LE portal / compliance@kraken.com",
     "evidence_format": ["LE request", "Deposit tx evidence", "Legal process"],
     "sla_note": "Established LE-liaison team."},
    {"name": "OKX", "type": "vasp", "assets": ["*"], "chains": ["*"],
     "channel": "OKX law-enforcement request intake",
     "evidence_format": ["LE request", "Deposit evidence"],
     "sla_note": "Seychelles/global; MLAT may be required for KYC."},
    {"name": "Bybit", "type": "vasp", "assets": ["*"], "chains": ["*"],
     "channel": "Bybit LE desk (lea@bybit.com)",
     "evidence_format": ["LE request", "Deposit evidence"],
     "sla_note": "Cooperative post-2025 exploit; Dubai-based."},
    {"name": "HTX (Huobi)", "type": "vasp", "assets": ["*"], "chains": ["*"],
     "channel": "HTX compliance / LE intake",
     "evidence_format": ["LE request", "Deposit evidence"],
     "sla_note": "Response variable; escalate via T3 where USDT-on-TRON involved."},
]

WATCH_STATUSES = ("active", "paused")


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
            CREATE TABLE IF NOT EXISTS freeze_watchlist (
                id           TEXT PRIMARY KEY,
                case_id      TEXT DEFAULT '',
                address      TEXT NOT NULL,
                chain        TEXT DEFAULT 'eth',
                asset        TEXT DEFAULT 'USDT',
                min_usd      REAL DEFAULT 0,
                reason       TEXT DEFAULT '',
                auto_queue   INTEGER DEFAULT 1,
                status       TEXT DEFAULT 'active',
                created_at   TEXT,
                last_scan_at TEXT,
                last_hit_at  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_fw_addr ON freeze_watchlist(address);
            CREATE TABLE IF NOT EXISTS freeze_watch_events (
                id           TEXT PRIMARY KEY,
                watch_id     TEXT NOT NULL,
                at           TEXT,
                kind         TEXT,      -- 'vasp_touch' | 'issuer_asset_move' | 'manual'
                counterparty TEXT DEFAULT '',
                vasp_name    TEXT DEFAULT '',
                tx_hash      TEXT DEFAULT '',
                amount_usd   REAL DEFAULT 0,
                request_id   TEXT DEFAULT '',
                detail       TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_fwe_watch ON freeze_watch_events(watch_id);
        """)
        con.commit()
    finally:
        con.close()


# ── Directory ────────────────────────────────────────────────────────────────

def directory(asset: str = "", target_type: str = "") -> list[dict[str, Any]]:
    out = DIRECTORY
    if asset:
        a = asset.upper()
        out = [d for d in out if "*" in d["assets"] or a in d["assets"]]
    if target_type:
        out = [d for d in out if d["type"] == target_type]
    return out


# ── Watchlist CRUD ───────────────────────────────────────────────────────────

def add_watch(address: str, chain: str = "eth", asset: str = "USDT", case_id: str = "",
              min_usd: float = 0, reason: str = "", auto_queue: bool = True) -> dict[str, Any]:
    init_tables()
    wid = uuid.uuid4().hex[:16]
    con = _conn()
    try:
        con.execute(
            "INSERT INTO freeze_watchlist (id, case_id, address, chain, asset, min_usd, reason, auto_queue, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (wid, case_id, address.strip(), chain.lower(), (asset or "USDT").upper(),
             float(min_usd or 0), reason, 1 if auto_queue else 0, "active", _now()))
        con.commit()
    finally:
        con.close()
    return get_watch(wid)


def get_watch(wid: str) -> Optional[dict[str, Any]]:
    con = _conn()
    try:
        row = con.execute("SELECT * FROM freeze_watchlist WHERE id=?", (wid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        ev = con.execute("SELECT COUNT(*) c FROM freeze_watch_events WHERE watch_id=?", (wid,)).fetchone()
        d["event_count"] = ev["c"] if ev else 0
        return d
    finally:
        con.close()


def list_watches(case_id: str = "", status: str = "") -> list[dict[str, Any]]:
    init_tables()
    q, args = "SELECT id FROM freeze_watchlist WHERE 1=1", []
    if case_id:
        q += " AND case_id=?"; args.append(case_id)
    if status:
        q += " AND status=?"; args.append(status)
    q += " ORDER BY created_at DESC"
    con = _conn()
    try:
        rows = con.execute(q, args).fetchall()
    finally:
        con.close()
    return [get_watch(r["id"]) for r in rows]


def set_watch_status(wid: str, status: str) -> Optional[dict[str, Any]]:
    if status not in WATCH_STATUSES:
        raise ValueError(f"invalid status '{status}'")
    con = _conn()
    try:
        con.execute("UPDATE freeze_watchlist SET status=? WHERE id=?", (status, wid))
        con.commit()
    finally:
        con.close()
    return get_watch(wid)


def delete_watch(wid: str) -> bool:
    con = _conn()
    try:
        cur = con.execute("DELETE FROM freeze_watchlist WHERE id=?", (wid,))
        con.execute("DELETE FROM freeze_watch_events WHERE watch_id=?", (wid,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def list_events(wid: str = "", limit: int = 100) -> list[dict[str, Any]]:
    init_tables()
    con = _conn()
    try:
        if wid:
            rows = con.execute("SELECT * FROM freeze_watch_events WHERE watch_id=? ORDER BY at DESC LIMIT ?",
                               (wid, limit)).fetchall()
        else:
            rows = con.execute("SELECT * FROM freeze_watch_events ORDER BY at DESC LIMIT ?", (limit,)).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


# ── VASP / issuer-touch classification ───────────────────────────────────────

def _label_counterparty(addr: str, chain: str) -> dict[str, Any]:
    """Best-effort local label of a counterparty: VASP/exchange, mixer, or unknown."""
    if not addr:
        return {"kind": "unknown", "name": ""}
    a = addr.lower()
    try:
        import constants
        if a in {x.lower() for x in constants.MIXER_CONTRACTS}:
            return {"kind": "mixer", "name": "known mixer"}
    except Exception:
        pass
    # Attribution store (sanctions/VASP/labels with provenance)
    try:
        import attribution_engine
        att = attribution_engine.attribute(addr, chain)
        for at in att.get("attributions") or []:
            cat = (at.get("category") or "").lower()
            name = at.get("entity") or at.get("label") or ""
            if cat in ("exchange", "vasp", "cex"):
                return {"kind": "vasp", "name": name or "exchange"}
            low = (name or "").lower()
            try:
                import constants
                if any(h in low for h in constants.EXCHANGE_NAME_HINTS):
                    return {"kind": "vasp", "name": name}
            except Exception:
                pass
            if cat in ("mixer",):
                return {"kind": "mixer", "name": name}
    except Exception:
        pass
    return {"kind": "unknown", "name": ""}


def _record_event(watch: dict[str, Any], kind: str, counterparty: str, vasp_name: str,
                  tx_hash: str, amount_usd: float, detail: str) -> dict[str, Any]:
    """Record a watch event and (if auto_queue) draft the freeze package."""
    request_id = ""
    if watch.get("auto_queue"):
        try:
            import recovery_ops
            req = recovery_ops.create_request(
                address=watch["address"], chain=watch["chain"], asset=watch["asset"],
                amount_usd=amount_usd or 0, case_id=watch.get("case_id") or "",
                reason=(f"Auto-queued by Freeze Desk watch {watch['id']}: {detail} "
                        f"(tx {tx_hash[:18]}…)" if tx_hash else
                        f"Auto-queued by Freeze Desk watch {watch['id']}: {detail}"),
                vasp_name=vasp_name, requester="freeze-desk-auto")
            request_id = req["id"] if req else ""
        except Exception:
            request_id = ""
    eid = uuid.uuid4().hex[:16]
    now = _now()
    con = _conn()
    try:
        con.execute(
            "INSERT INTO freeze_watch_events (id, watch_id, at, kind, counterparty, vasp_name, tx_hash, amount_usd, request_id, detail)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (eid, watch["id"], now, kind, counterparty, vasp_name, tx_hash, float(amount_usd or 0), request_id, detail))
        con.execute("UPDATE freeze_watchlist SET last_hit_at=? WHERE id=?", (now, watch["id"]))
        con.commit()
    finally:
        con.close()
    return {"id": eid, "watch_id": watch["id"], "kind": kind, "request_id": request_id,
            "vasp_name": vasp_name, "detail": detail}


def evaluate_transfer(wid: str, counterparty: str, direction: str = "out",
                      amount_usd: float = 0, tx_hash: str = "") -> dict[str, Any]:
    """Manually (or agent-driven) evaluate one transfer against a watch."""
    watch = get_watch(wid)
    if not watch:
        raise ValueError("watch not found")
    label = _label_counterparty(counterparty, watch["chain"])
    if amount_usd and watch.get("min_usd") and amount_usd < watch["min_usd"]:
        return {"matched": False, "reason": f"below min_usd {watch['min_usd']}", "label": label}
    if direction == "out" and label["kind"] == "vasp":
        ev = _record_event(watch, "vasp_touch", counterparty, label["name"], tx_hash, amount_usd,
                           f"Watched funds moved OUT to labeled VASP '{label['name']}' — "
                           "freeze window open at the custodial endpoint.")
        return {"matched": True, "event": ev, "label": label}
    if label["kind"] == "mixer":
        ev = _record_event(watch, "issuer_asset_move", counterparty, label["name"], tx_hash, amount_usd,
                           "Watched funds touched a mixer — issuer-level freeze is the remaining lever.")
        return {"matched": True, "event": ev, "label": label}
    return {"matched": False, "reason": "counterparty not a labeled VASP/mixer", "label": label}


def scan_watches(limit_notifs: int = 500) -> dict[str, Any]:
    """Beacon-lite loop: sweep recent monitor_notifications for watched addresses
    whose counterparties are labeled VASPs; auto-draft freeze packages.

    Reads the wallet-monitor's notification table (additive, read-only). Run it
    from the UI, a cron, or after each monitor scan.
    """
    init_tables()
    watches = [w for w in list_watches(status="active")]
    if not watches:
        return {"scanned": 0, "matches": 0, "events": []}
    by_addr: dict[str, list[dict[str, Any]]] = {}
    for w in watches:
        by_addr.setdefault(w["address"].lower(), []).append(w)

    con = _conn()
    try:
        try:
            rows = con.execute(
                "SELECT * FROM monitor_notifications ORDER BY created_at DESC LIMIT ?",
                (limit_notifs,)).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        con.close()

    seen_hashes = {e["tx_hash"] for e in list_events(limit=1000) if e.get("tx_hash")}
    events, scanned = [], 0
    now = _now()
    for r in rows:
        d = dict(r)
        addr = (d.get("address") or "").lower()
        if addr not in by_addr:
            continue
        scanned += 1
        try:
            tx = json.loads(d.get("tx_json") or "{}")
        except (ValueError, TypeError):
            tx = {}
        tx_hash = tx.get("hash") or d.get("tx_hash") or ""
        if tx_hash and tx_hash in seen_hashes:
            continue
        frm = (tx.get("from") or tx.get("sender") or "").lower()
        to = (tx.get("to") or tx.get("receiver") or tx.get("recipient") or "").lower()
        counterparty = to if frm == addr else frm
        direction = "out" if frm == addr else "in"
        value_usd = float(tx.get("value_usd") or tx.get("usd") or 0)
        for w in by_addr[addr]:
            if w.get("min_usd") and value_usd and value_usd < w["min_usd"]:
                continue
            label = _label_counterparty(counterparty, w["chain"])
            if direction == "out" and label["kind"] in ("vasp", "mixer"):
                kind = "vasp_touch" if label["kind"] == "vasp" else "issuer_asset_move"
                detail = (f"Monitor notification: watched funds moved out to "
                          f"{label['kind']} '{label['name'] or counterparty[:12]}…'.")
                ev = _record_event(w, kind, counterparty, label["name"], tx_hash, value_usd, detail)
                events.append(ev)
                if tx_hash:
                    seen_hashes.add(tx_hash)

    con = _conn()
    try:
        con.execute("UPDATE freeze_watchlist SET last_scan_at=? WHERE status='active'", (now,))
        con.commit()
    finally:
        con.close()
    return {"scanned": scanned, "matches": len(events), "events": events}


# ── (c) KPI telemetry ────────────────────────────────────────────────────────

def kpis() -> dict[str, Any]:
    """Freeze KPIs from recovery_requests history: time-to-freeze, totals by
    target, monthly frozen value — the numbers agencies report upward."""
    try:
        import recovery_ops
        recovery_ops.init_tables()
        reqs = recovery_ops.list_requests(limit=1000)
    except Exception:
        reqs = []

    frozen = [r for r in reqs if r.get("status") in ("frozen", "seized")]
    ttf_hours: list[float] = []
    monthly: dict[str, float] = {}
    by_target: dict[str, dict[str, float]] = {}
    for r in frozen:
        hist = r.get("history") or []
        t0 = next((h["at"] for h in hist if h.get("status") == "draft"), None)
        t1 = next((h["at"] for h in reversed(hist) if h.get("status") in ("frozen", "seized")), None)
        if t0 and t1:
            try:
                dt = (datetime.fromisoformat(t1) - datetime.fromisoformat(t0)).total_seconds() / 3600
                if dt >= 0:
                    ttf_hours.append(dt)
            except ValueError:
                pass
        month = (r.get("updated_at") or "")[:7]
        if month:
            monthly[month] = monthly.get(month, 0) + float(r.get("amount_usd") or 0)
        tname = r.get("target_name") or "?"
        agg = by_target.setdefault(tname, {"count": 0, "amount_usd": 0.0})
        agg["count"] += 1
        agg["amount_usd"] += float(r.get("amount_usd") or 0)

    watch_events = list_events(limit=1000)
    auto_queued = sum(1 for e in watch_events if e.get("request_id"))
    return {
        "total_requests": len(reqs),
        "frozen_or_seized": len(frozen),
        "value_frozen_usd": round(sum(float(r.get("amount_usd") or 0) for r in frozen), 2),
        "median_time_to_freeze_hours": round(sorted(ttf_hours)[len(ttf_hours) // 2], 1) if ttf_hours else None,
        "avg_time_to_freeze_hours": round(sum(ttf_hours) / len(ttf_hours), 1) if ttf_hours else None,
        "monthly_frozen_usd": [{"month": m, "amount_usd": round(v, 2)} for m, v in sorted(monthly.items())],
        "by_target": [{"target": k, **{"count": int(v["count"]), "amount_usd": round(v["amount_usd"], 2)}}
                      for k, v in sorted(by_target.items(), key=lambda kv: -kv[1]["amount_usd"])],
        "watch_events": len(watch_events),
        "auto_queued_requests": auto_queued,
    }
