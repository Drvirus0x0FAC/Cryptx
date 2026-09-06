"""
Wallet monitoring endpoints and background scanner.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database as db

router = APIRouter(tags=["Wallet Monitor"])

_SCAN_LOCK = asyncio.Lock()
_MONITOR_TASK: Optional[asyncio.Task] = None
DEFAULT_INTERVAL = 90


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _tx_hash(tx: Dict[str, Any]) -> str:
    return str(tx.get("hash") or tx.get("txid") or tx.get("tx_hash") or "").strip()


def _tx_time(tx: Dict[str, Any]) -> str:
    return str(tx.get("time") or tx.get("timestamp") or "")


def _tx_value(tx: Dict[str, Any]) -> float:
    for key in ("value", "value_eth", "value_trx", "delta_btc", "amount", "usd_value"):
        try:
            if tx.get(key) is not None:
                return float(tx.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0.0


def init_monitor_tables() -> None:
    with db.get_connection() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS wallet_monitors (
            id              TEXT PRIMARY KEY,
            address         TEXT NOT NULL,
            chain           TEXT DEFAULT '',
            label           TEXT DEFAULT '',
            active          INTEGER DEFAULT 1,
            poll_interval   INTEGER DEFAULT 90,
            last_checked    TEXT DEFAULT '',
            last_seen_json  TEXT DEFAULT '[]',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            UNIQUE(address, chain)
        );
        CREATE TABLE IF NOT EXISTS monitor_notifications (
            id              TEXT PRIMARY KEY,
            monitor_id      TEXT NOT NULL,
            address         TEXT NOT NULL,
            chain           TEXT DEFAULT '',
            tx_hash         TEXT NOT NULL,
            tx_json         TEXT DEFAULT '{}',
            is_read         INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL,
            UNIQUE(monitor_id, tx_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_monitor_notifications_read ON monitor_notifications(is_read, created_at);
        CREATE INDEX IF NOT EXISTS idx_wallet_monitors_active ON wallet_monitors(active, updated_at);
        CREATE TABLE IF NOT EXISTS alert_rules (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            address         TEXT DEFAULT '',
            chain           TEXT DEFAULT '',
            direction       TEXT DEFAULT 'any',
            min_value       REAL DEFAULT 0,
            counterparty_category TEXT DEFAULT 'any',
            enabled         INTEGER DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_alert_rules_address ON alert_rules(address, enabled);
        CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled ON alert_rules(enabled);
        """)


def _row(row) -> Dict[str, Any]:
    out = dict(row)
    if "active" in out:
        out["active"] = bool(out["active"])
    if "is_read" in out:
        out["is_read"] = bool(out["is_read"])
    if "last_seen_json" in out:
        try:
            out["last_seen"] = json.loads(out.get("last_seen_json") or "[]")
        except Exception:
            out["last_seen"] = []
        out.pop("last_seen_json", None)
    if "tx_json" in out:
        try:
            out["tx"] = json.loads(out.get("tx_json") or "{}")
        except Exception:
            out["tx"] = {}
        out.pop("tx_json", None)
    return out


class MonitorCreateRequest(BaseModel):
    addresses: List[str]
    chain: str = ""
    label: str = ""
    poll_interval: int = DEFAULT_INTERVAL
    baseline_existing: bool = True


class MonitorUpdateRequest(BaseModel):
    active: Optional[bool] = None
    label: Optional[str] = None
    poll_interval: Optional[int] = None


async def _lookup_intel(address: str) -> Optional[Dict[str, Any]]:
    try:
        from crypto_osint import lookup_crypto_address
        result = await asyncio.wait_for(lookup_crypto_address(address), timeout=75)
        return result if isinstance(result, dict) else None
    except Exception:
        return None


def _recent_txs(intel: Dict[str, Any]) -> List[Dict[str, Any]]:
    txs = list(intel.get("recent_txs") or []) + list(intel.get("token_txs") or [])
    seen = set()
    out = []
    for tx in txs:
        h = _tx_hash(tx)
        if not h or h in seen:
            continue
        seen.add(h)
        out.append(tx)
    return out


def _insert_notification(con, monitor: Dict[str, Any], tx: Dict[str, Any]) -> bool:
    tx_hash = _tx_hash(tx)
    if not tx_hash:
        return False
    nid = str(uuid.uuid4())
    try:
        con.execute(
            """INSERT INTO monitor_notifications
               (id, monitor_id, address, chain, tx_hash, tx_json, is_read, created_at)
               VALUES (?,?,?,?,?,?,0,?)""",
            (
                nid,
                monitor["id"],
                monitor["address"],
                monitor.get("chain", ""),
                tx_hash,
                json.dumps({
                    **tx,
                    "hash": tx_hash,
                    "time": _tx_time(tx),
                    "value": _tx_value(tx),
                }),
                _now(),
            ),
        )
        return True
    except Exception:
        return False


# ── Criteria-based alert rules ────────────────────────────────────────────────

RULE_CATEGORIES = ("any", "mixer", "exchange", "bridge", "sanctioned", "scam", "darknet", "ransomware")
RULE_DIRECTIONS = ("any", "in", "out")


def _tx_direction(tx: Dict[str, Any], subject: str) -> str:
    frm = str(tx.get("from") or "").lower()
    to = str(tx.get("to") or "").lower()
    s = subject.lower()
    if frm == s:
        return "out"
    if to == s:
        return "in"
    return "any"


def _counterparty(tx: Dict[str, Any], subject: str) -> str:
    frm = str(tx.get("from") or "").lower()
    to = str(tx.get("to") or "").lower()
    s = subject.lower()
    return to if frm == s else frm


def _counterparty_categories(address: str, chain: str) -> set:
    """Local, cheap category lookup via the attribution engine (sanctions + KYV + labels)."""
    if not address:
        return set()
    try:
        import attribution_engine as ae
        result = ae.attribute(address, chain or None)
        return {a.get("category") for a in result.get("attributions", []) if a.get("category")}
    except Exception:
        return set()


def evaluate_rules_for_tx(rules: List[Dict[str, Any]], monitor: Dict[str, Any], tx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the rules this transaction triggers (with reasons)."""
    subject = monitor["address"]
    triggered = []
    direction = _tx_direction(tx, subject)
    value = _tx_value(tx)
    cp = _counterparty(tx, subject)
    cp_cats: Optional[set] = None  # lazy — attribution lookup only when a rule needs it

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        r_addr = str(rule.get("address") or "").lower()
        if r_addr and r_addr != subject.lower():
            continue
        r_chain = str(rule.get("chain") or "")
        if r_chain and r_chain.upper() != str(monitor.get("chain", "")).upper():
            continue
        r_dir = rule.get("direction", "any")
        if r_dir != "any" and direction != r_dir:
            continue
        if value < float(rule.get("min_value") or 0):
            continue
        r_cat = rule.get("counterparty_category", "any")
        reasons = [f"direction={direction}", f"value={value}"]
        if r_cat != "any":
            if cp_cats is None:
                cp_cats = _counterparty_categories(cp, monitor.get("chain", ""))
            if r_cat not in cp_cats:
                continue
            reasons.append(f"counterparty {cp[:16]}… is labelled '{r_cat}'")
        triggered.append({"rule_id": rule["id"], "rule_name": rule["name"], "reasons": reasons})
    return triggered


def _load_rules(con) -> List[Dict[str, Any]]:
    return [dict(r) for r in con.execute("SELECT * FROM alert_rules WHERE enabled=1").fetchall()]


def _insert_rule_alert(con, monitor: Dict[str, Any], tx: Dict[str, Any], hit: Dict[str, Any]) -> bool:
    """Rule hits are stored as monitor notifications tagged with the rule."""
    tx_hash = _tx_hash(tx)
    if not tx_hash:
        return False
    try:
        con.execute(
            """INSERT INTO monitor_notifications
               (id, monitor_id, address, chain, tx_hash, tx_json, is_read, created_at)
               VALUES (?,?,?,?,?,?,0,?)""",
            (
                str(uuid.uuid4()),
                monitor["id"],
                monitor["address"],
                monitor.get("chain", ""),
                f"{tx_hash}:rule:{hit['rule_id']}",
                json.dumps({
                    **tx,
                    "hash": tx_hash,
                    "time": _tx_time(tx),
                    "value": _tx_value(tx),
                    "alert_rule": hit["rule_name"],
                    "alert_reasons": hit["reasons"],
                }),
                _now(),
            ),
        )
        return True
    except Exception:
        return False


async def _maybe_dispatch_alerts(
    monitor: Dict[str, Any],
    new_txs: List[Dict[str, Any]],
    rule_hits_by_tx: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Fan out new txs / rule hits to all delivery channels (webhook/email/telegram/SSE).

    Best-effort; never raises. Imported lazily so a missing module cannot break the monitor.
    """
    try:
        import alert_delivery
        alert_delivery.init_delivery_tables()
    except Exception:
        return
    for tx in new_txs:
        notif = {
            "id": _tx_hash(tx),
            "monitor_id": monitor.get("id", ""),
            "address": monitor.get("address", ""),
            "chain": monitor.get("chain", ""),
            "tx": tx,
        }
        hits = rule_hits_by_tx.get(_tx_hash(tx), [])
        for hit in hits:
            try:
                await alert_delivery.dispatch_alert(notif, rule_hit=hit, actor="monitor")
            except Exception:
                pass
        # If no rule hit but tx is new, still broadcast to SSE for live feed
        if not hits:
            try:
                event = {
                    "title": f"New tx on {monitor.get('address', '')[:10]}…",
                    "notification": notif,
                    "rule_hit": None,
                    "timestamp": _now(),
                }
                await alert_delivery._sse_broadcast(event)
            except Exception:
                pass


async def scan_monitor(monitor: Dict[str, Any]) -> Dict[str, Any]:
    intel = await _lookup_intel(monitor["address"])
    now = _now()
    if not intel:
        with db.get_connection() as con:
            con.execute("UPDATE wallet_monitors SET last_checked=?, updated_at=? WHERE id=?", (now, now, monitor["id"]))
        return {"monitor_id": monitor["id"], "new_count": 0, "error": "lookup_failed"}

    txs = _recent_txs(intel)
    current_hashes = [_tx_hash(tx) for tx in txs if _tx_hash(tx)]
    known = set(json.loads(monitor.get("last_seen_json") or "[]"))
    new_txs = [tx for tx in txs if _tx_hash(tx) and _tx_hash(tx) not in known]
    chain = intel.get("chain") or monitor.get("chain", "")

    inserted = 0
    rule_hits = 0
    rule_hits_by_tx: Dict[str, List[Dict[str, Any]]] = {}
    with db.get_connection() as con:
        mon = {**monitor, "chain": chain}
        rules = _load_rules(con)
        for tx in new_txs:
            inserted += 1 if _insert_notification(con, mon, tx) else 0
            tx_hits = evaluate_rules_for_tx(rules, mon, tx)
            for hit in tx_hits:
                rule_hits += 1 if _insert_rule_alert(con, mon, tx, hit) else 0
            if tx_hits:
                rule_hits_by_tx[_tx_hash(tx)] = tx_hits
        merged = list(dict.fromkeys(current_hashes + list(known)))[:250]
        con.execute(
            """UPDATE wallet_monitors
               SET chain=?, last_checked=?, last_seen_json=?, updated_at=?
               WHERE id=?""",
            (chain, now, json.dumps(merged), now, monitor["id"]),
        )
    # Fan out to delivery channels (webhook / email / telegram / SSE). Best-effort.
    if new_txs:
        await _maybe_dispatch_alerts(mon, new_txs, rule_hits_by_tx)
    return {"monitor_id": monitor["id"], "new_count": inserted, "rule_alerts": rule_hits}


async def scan_due_monitors() -> Dict[str, Any]:
    async with _SCAN_LOCK:
        init_monitor_tables()
        with db.get_connection() as con:
            rows = con.execute("SELECT * FROM wallet_monitors WHERE active=1 ORDER BY updated_at ASC").fetchall()
        results = []
        for row in rows:
            monitor = dict(row)
            results.append(await scan_monitor(monitor))
        return {"scanned": len(results), "results": results}


async def monitor_loop() -> None:
    while True:
        try:
            await scan_due_monitors()
        except Exception:
            pass
        await asyncio.sleep(DEFAULT_INTERVAL)


def start_monitor_loop() -> None:
    global _MONITOR_TASK
    init_monitor_tables()
    if _MONITOR_TASK is None or _MONITOR_TASK.done():
        _MONITOR_TASK = asyncio.create_task(monitor_loop())


@router.get("/monitor/watches")
async def list_watches():
    init_monitor_tables()
    with db.get_connection() as con:
        rows = con.execute("SELECT * FROM wallet_monitors ORDER BY updated_at DESC").fetchall()
    return {"watches": [_row(r) for r in rows]}


@router.post("/monitor/watches")
async def create_watches(req: MonitorCreateRequest):
    init_monitor_tables()
    created = []
    now = _now()
    for raw in req.addresses:
        address = raw.strip()
        if not address:
            continue
        intel = await _lookup_intel(address)
        chain = req.chain or (intel or {}).get("chain", "")
        baseline = [_tx_hash(tx) for tx in _recent_txs(intel or {}) if _tx_hash(tx)] if req.baseline_existing else []
        mid = str(uuid.uuid4())
        with db.get_connection() as con:
            con.execute(
                """INSERT INTO wallet_monitors
                   (id, address, chain, label, active, poll_interval, last_checked, last_seen_json, created_at, updated_at)
                   VALUES (?,?,?,?,1,?,?,?,?,?)
                   ON CONFLICT(address, chain) DO UPDATE SET
                     label=excluded.label,
                     active=1,
                     poll_interval=excluded.poll_interval,
                     updated_at=excluded.updated_at""",
                (
                    mid,
                    address,
                    chain,
                    req.label,
                    max(30, min(req.poll_interval, 3600)),
                    now,
                    json.dumps(baseline[:250]),
                    now,
                    now,
                ),
            )
            row = con.execute("SELECT * FROM wallet_monitors WHERE address=? AND chain=?", (address, chain)).fetchone()
            created.append(_row(row))
    if not created:
        raise HTTPException(status_code=400, detail="No valid addresses supplied")
    return {"watches": created}


@router.patch("/monitor/watches/{monitor_id}")
async def update_watch(monitor_id: str, req: MonitorUpdateRequest):
    init_monitor_tables()
    updates = []
    params: List[Any] = []
    if req.active is not None:
        updates.append("active=?")
        params.append(1 if req.active else 0)
    if req.label is not None:
        updates.append("label=?")
        params.append(req.label)
    if req.poll_interval is not None:
        updates.append("poll_interval=?")
        params.append(max(30, min(req.poll_interval, 3600)))
    if not updates:
        raise HTTPException(status_code=400, detail="No updates supplied")
    updates.append("updated_at=?")
    params.append(_now())
    params.append(monitor_id)
    with db.get_connection() as con:
        con.execute(f"UPDATE wallet_monitors SET {', '.join(updates)} WHERE id=?", params)
        row = con.execute("SELECT * FROM wallet_monitors WHERE id=?", (monitor_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return _row(row)


@router.delete("/monitor/watches/{monitor_id}")
async def delete_watch(monitor_id: str):
    init_monitor_tables()
    with db.get_connection() as con:
        con.execute("DELETE FROM monitor_notifications WHERE monitor_id=?", (monitor_id,))
        cur = con.execute("DELETE FROM wallet_monitors WHERE id=?", (monitor_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return {"deleted": True}


@router.post("/monitor/scan")
async def scan_now():
    return await scan_due_monitors()


@router.get("/monitor/notifications")
async def list_notifications(unread_only: bool = False, limit: int = 50):
    init_monitor_tables()
    where = "WHERE is_read=0" if unread_only else ""
    with db.get_connection() as con:
        rows = con.execute(
            f"""SELECT * FROM monitor_notifications
                {where}
                ORDER BY created_at DESC
                LIMIT ?""",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return {"notifications": [_row(r) for r in rows]}


@router.post("/monitor/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str):
    init_monitor_tables()
    with db.get_connection() as con:
        cur = con.execute("UPDATE monitor_notifications SET is_read=1 WHERE id=?", (notification_id,))
        row = con.execute("SELECT * FROM monitor_notifications WHERE id=?", (notification_id,)).fetchone()
    if cur.rowcount == 0 or not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    return _row(row)


# ── Alert rule endpoints ──────────────────────────────────────────────────────

class AlertRuleRequest(BaseModel):
    name: str
    address: str = ""              # empty = applies to every watched address
    chain: str = ""
    direction: str = "any"         # any | in | out
    min_value: float = 0           # native units (matches monitor tx values)
    counterparty_category: str = "any"  # any | mixer | exchange | bridge | sanctioned | scam | darknet | ransomware
    enabled: bool = True


@router.get("/monitor/rules")
async def list_rules():
    init_monitor_tables()
    with db.get_connection() as con:
        rows = con.execute("SELECT * FROM alert_rules ORDER BY created_at DESC").fetchall()
    return {"rules": [{**dict(r), "enabled": bool(dict(r)["enabled"])} for r in rows],
            "categories": RULE_CATEGORIES, "directions": RULE_DIRECTIONS}


@router.post("/monitor/rules")
async def create_rule(req: AlertRuleRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="rule name is required")
    if req.direction not in RULE_DIRECTIONS:
        raise HTTPException(status_code=400, detail=f"direction must be one of {RULE_DIRECTIONS}")
    if req.counterparty_category not in RULE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"counterparty_category must be one of {RULE_CATEGORIES}")
    init_monitor_tables()
    rid = str(uuid.uuid4())
    now = _now()
    with db.get_connection() as con:
        con.execute(
            """INSERT INTO alert_rules
               (id, name, address, chain, direction, min_value, counterparty_category, enabled, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (rid, req.name.strip(), req.address.strip().lower(), req.chain.strip(),
             req.direction, req.min_value, req.counterparty_category, int(req.enabled), now, now),
        )
        row = con.execute("SELECT * FROM alert_rules WHERE id=?", (rid,)).fetchone()
    return {**dict(row), "enabled": bool(dict(row)["enabled"])}


@router.patch("/monitor/rules/{rule_id}")
async def update_rule(rule_id: str, req: AlertRuleRequest):
    init_monitor_tables()
    with db.get_connection() as con:
        cur = con.execute(
            """UPDATE alert_rules SET name=?, address=?, chain=?, direction=?, min_value=?,
               counterparty_category=?, enabled=?, updated_at=? WHERE id=?""",
            (req.name.strip(), req.address.strip().lower(), req.chain.strip(), req.direction,
             req.min_value, req.counterparty_category, int(req.enabled), _now(), rule_id),
        )
        row = con.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
    if cur.rowcount == 0 or not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {**dict(row), "enabled": bool(dict(row)["enabled"])}


@router.delete("/monitor/rules/{rule_id}")
async def delete_rule(rule_id: str):
    init_monitor_tables()
    with db.get_connection() as con:
        cur = con.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"deleted": True}


# ── Real-time SSE live alert stream ────────────────────────────────────────────

from fastapi.responses import StreamingResponse


@router.get("/monitor/stream")
async def alert_stream():
    """Server-Sent Events endpoint for live monitor alerts.

    A browser connects with `new EventSource('/api/monitor/stream')` and receives
    `alert` events in real time as new transactions / rule hits are detected by the
    background monitor loop. Connection auto-reconnects on the client side.
    """
    import alert_delivery
    queue = await alert_delivery.sse_subscribe()

    async def event_generator():
        try:
            # Initial hello so the client knows the stream is alive
            yield f": connected {len(alert_delivery._SSE_CLIENTS)} clients\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"event: alert\ndata: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    # heartbeat keeps the connection alive through proxies
                    yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            alert_delivery.sse_unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Alert delivery destinations (webhook / email / telegram) ───────────────────

from pydantic import BaseModel as PydBaseModel


class DestinationRequest(PydBaseModel):
    name: str
    kind: str                   # webhook | email | telegram | sse | inapp
    config: dict = {}
    enabled: bool = True


@router.get("/monitor/destinations")
async def list_destinations():
    import alert_delivery
    return {
        "destinations": alert_delivery.list_destinations(),
        "kinds": alert_delivery.VALID_CHANNELS,
    }


@router.post("/monitor/destinations")
async def create_destination(req: DestinationRequest):
    import alert_delivery
    try:
        return alert_delivery.add_destination(req.name, req.kind, req.config, req.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/monitor/destinations/{dest_id}")
async def update_destination(dest_id: str, enabled: bool = True):
    import alert_delivery
    if not alert_delivery.toggle_destination(dest_id, enabled):
        raise HTTPException(status_code=404, detail="Destination not found")
    return {"updated": True, "enabled": enabled}


@router.delete("/monitor/destinations/{dest_id}")
async def delete_destination(dest_id: str):
    import alert_delivery
    if not alert_delivery.delete_destination(dest_id):
        raise HTTPException(status_code=404, detail="Destination not found")
    return {"deleted": True}


@router.get("/monitor/deliveries")
async def list_deliveries(limit: int = 50):
    import alert_delivery
    return {"deliveries": alert_delivery.delivery_history(limit)}
