"""
Alert delivery channels for the wallet monitor.

Supports multiple fan-out destinations per alert:
  - in-app notification (already in monitor_notifications)
  - webhook (generic HTTP POST with HMAC signature)
  - email (SMTP)
  - Telegram bot message
  - Server-Sent Events (SSE) live push to connected browsers

Configuration is read from DB tables (alert_destinations) and/or env vars.
All deliveries are best-effort and async; a failed channel never blocks others.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import aiohttp

import database as db

log = logging.getLogger("alert_delivery")

# Channel kind constants
CHANNEL_WEBHOOK = "webhook"
CHANNEL_EMAIL = "email"
CHANNEL_TELEGRAM = "telegram"
CHANNEL_SSE = "sse"
CHANNEL_INAPP = "inapp"
VALID_CHANNELS = (CHANNEL_WEBHOOK, CHANNEL_EMAIL, CHANNEL_TELEGRAM, CHANNEL_SSE, CHANNEL_INAPP)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_delivery_tables() -> None:
    with db.get_connection() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS alert_destinations (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            kind         TEXT NOT NULL,
            config_json  TEXT DEFAULT '{}',
            enabled      INTEGER DEFAULT 1,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alert_deliveries (
            id            TEXT PRIMARY KEY,
            notification_id TEXT DEFAULT '',
            destination_id  TEXT NOT NULL REFERENCES alert_destinations(id) ON DELETE CASCADE,
            status        TEXT DEFAULT 'pending',
            attempts      INTEGER DEFAULT 0,
            last_error    TEXT DEFAULT '',
            delivered_at  TEXT DEFAULT '',
            payload_json  TEXT DEFAULT '{}',
            created_at    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_alert_deliveries_dest ON alert_deliveries(destination_id, created_at);
        CREATE INDEX IF NOT EXISTS alert_deliveries_status ON alert_deliveries(status);
        """)


# ── SSE broadcast ──────────────────────────────────────────────────────────────
# A simple in-process pub/sub. Each connected browser client registers an asyncio.Queue;
# broadcast fans out to all queues. Non-SSE channels (webhook/email/telegram) are handled
# separately via the dispatch loop.

_SSE_CLIENTS: set[asyncio.Queue] = set()


async def sse_subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _SSE_CLIENTS.add(q)
    return q


def sse_unsubscribe(q: asyncio.Queue) -> None:
    _SSE_CLIENTS.discard(q)


async def _sse_broadcast(event: dict) -> None:
    """Push an event to every connected SSE client. Non-blocking; drops on overflow."""
    dead: list[asyncio.Queue] = []
    for q in list(_SSE_CLIENTS):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest then insert (keep latest alerts visible)
            try:
                q.get_nowait()
                q.put_nowait(event)
            except Exception:
                dead.append(q)
    for q in dead:
        _SSE_CLIENTS.discard(q)


# ── Formatting ─────────────────────────────────────────────────────────────────

def _format_message(notification: dict, rule_hit: dict | None = None) -> tuple[str, str]:
    """Return (title, body) for an alert notification."""
    tx = notification.get("tx") or {}
    addr = notification.get("address", "?")
    chain = notification.get("chain", "")
    value = tx.get("value", 0)
    tx_hash = tx.get("hash", "?")
    counterparty = tx.get("to") if tx.get("from", "").lower() == addr.lower() else tx.get("from")
    direction = "OUT" if tx.get("from", "").lower() == addr.lower() else "IN"

    title = f"[CrypTX Alert] {value} {chain.upper()} {direction} — {addr[:10]}…"
    lines = [
        f"Address: {addr} ({chain})",
        f"Direction: {direction}",
        f"Value: {value}",
        f"Counterparty: {counterparty}",
        f"TX: {tx_hash}",
    ]
    if rule_hit:
        lines.append(f"Rule: {rule_hit.get('rule_name')}")
        lines.append("Reason: " + ", ".join(rule_hit.get("reasons", [])))
    body = "\n".join(lines)
    return title, body


# ── Channel dispatchers ────────────────────────────────────────────────────────

async def _send_webhook(config: dict, title: str, body: str, event: dict) -> str:
    """POST JSON to a webhook URL with an HMAC-SHA256 signature header."""
    url = config.get("url", "").strip()
    if not url:
        return "no_url"
    secret = config.get("secret", "").encode("utf-8")
    payload = json.dumps({"title": title, "body": body, "event": event, "source": "cryptx-monitor"})
    headers = {"Content-Type": "application/json"}
    if secret:
        sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        headers["X-CrypTX-Signature"] = f"sha256={sig}"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, data=payload, headers=headers) as resp:
            if resp.status >= 400:
                return f"http_{resp.status}"
    return "ok"


async def _send_telegram(config: dict, title: str, body: str) -> str:
    """Send a message via Telegram Bot API."""
    token = config.get("bot_token", "").strip() or os.getenv("MONITOR_TELEGRAM_BOT_TOKEN", "")
    chat_id = config.get("chat_id", "").strip()
    if not token or not chat_id:
        return "not_configured"
    text = f"*{title}*\n```\n{body}\n```"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json={
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
        }) as resp:
            if resp.status >= 400:
                data = await resp.text()
                return f"http_{resp.status}:{data[:120]}"
    return "ok"


async def _send_email(config: dict, title: str, body: str) -> str:
    """Send an email via SMTP. Runs blocking SMTP in a thread to avoid blocking the loop."""
    import smtplib
    from email.mime.text import MIMEText
    host = config.get("smtp_host", "") or os.getenv("MONITOR_SMTP_HOST", "")
    port = int(config.get("smtp_port", 587) or 587)
    user = config.get("smtp_user", "") or os.getenv("MONITOR_SMTP_USER", "")
    pw = config.get("smtp_pass", "") or os.getenv("MONITOR_SMTP_PASS", "")
    from_addr = config.get("from_addr", user) or "cryptx-alerts@localhost"
    to_addr = config.get("to_addr", "")
    use_tls = bool(config.get("use_tls", True))
    if not host or not to_addr:
        return "not_configured"

    msg = MIMEText(body)
    msg["Subject"] = title
    msg["From"] = from_addr
    msg["To"] = to_addr

    def _smtp_send() -> str:
        try:
            with smtplib.SMTP(host, port, timeout=20) as server:
                if use_tls:
                    server.starttls()
                if user and pw:
                    server.login(user, pw)
                server.sendmail(from_addr, [to_addr], msg.as_string())
            return "ok"
        except Exception as exc:  # noqa: BLE001
            return f"smtp_error:{type(exc).__name__}"

    return await asyncio.to_thread(_smtp_send)


# ── Public dispatch API ────────────────────────────────────────────────────────

async def dispatch_alert(
    notification: dict,
    rule_hit: dict | None = None,
    actor: str = "monitor",
) -> dict:
    """Fan an alert out to all enabled destinations.

    Always pushes to SSE (live browser clients). Then iterates configured
    destinations (webhook / email / telegram). Each result is recorded in
    alert_deliveries for audit. A failing channel never blocks others.
    """
    init_delivery_tables()
    title, body = _format_message(notification, rule_hit)
    event = {
        "title": title,
        "notification": notification,
        "rule_hit": rule_hit,
        "timestamp": _now(),
    }

    # 1. Always broadcast to SSE clients (live browser push)
    await _sse_broadcast(event)

    # 2. Fan out to configured destinations
    results: list[dict] = []
    with db.get_connection() as con:
        dests = [dict(r) for r in con.execute(
            "SELECT * FROM alert_destinations WHERE enabled=1"
        ).fetchall()]

    for dest in dests:
        kind = dest["kind"]
        try:
            config = json.loads(dest.get("config_json") or "{}")
        except json.JSONDecodeError:
            config = {}
        delivery_id = ""
        status = "skipped"

        try:
            if kind == CHANNEL_WEBHOOK:
                status = await _send_webhook(config, title, body, event)
            elif kind == CHANNEL_TELEGRAM:
                status = await _send_telegram(config, title, body)
            elif kind == CHANNEL_EMAIL:
                status = await _send_email(config, title, body)
            elif kind == CHANNEL_SSE:
                status = "ok"  # already broadcast above
            elif kind == CHANNEL_INAPP:
                status = "ok"  # in-app notification already stored by monitor
        except Exception as exc:  # noqa: BLE001
            status = f"error:{type(exc).__name__}"
            log.warning("Alert delivery to %s (%s) failed: %s", dest.get("name"), kind, exc)

        delivery_id = _record_delivery(dest["id"], notification.get("id", ""), status, event)
        results.append({"destination": dest["name"], "kind": kind, "status": status, "delivery_id": delivery_id})

    return {"dispatched_to": len(results), "results": results, "title": title}


def _record_delivery(dest_id: str, notif_id: str, status: str, payload: dict) -> str:
    import uuid
    did = str(uuid.uuid4())
    now = _now()
    attempts = 0 if status in ("ok", "skipped", "not_configured") else 1
    delivered = now if status == "ok" else ""
    err = "" if status == "ok" else status
    with db.get_connection() as con:
        con.execute(
            """INSERT INTO alert_deliveries
               (id, notification_id, destination_id, status, attempts, last_error,
                delivered_at, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (did, notif_id, dest_id, status, attempts, err, delivered,
             json.dumps(payload, default=str), now),
        )
    return did


# ── Destination management ─────────────────────────────────────────────────────

def add_destination(name: str, kind: str, config: dict, enabled: bool = True) -> dict:
    import uuid
    if kind not in VALID_CHANNELS:
        raise ValueError(f"kind must be one of {VALID_CHANNELS}")
    did = str(uuid.uuid4())
    now = _now()
    with db.get_connection() as con:
        con.execute(
            """INSERT INTO alert_destinations (id, name, kind, config_json, enabled, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (did, name.strip(), kind, json.dumps(config), int(enabled), now, now),
        )
        row = con.execute("SELECT * FROM alert_destinations WHERE id=?", (did,)).fetchone()
    out = dict(row)
    out["enabled"] = bool(out["enabled"])
    out["config"] = json.loads(out.pop("config_json", "{}") or "{}")
    return out


def list_destinations() -> list[dict]:
    init_delivery_tables()
    with db.get_connection() as con:
        rows = con.execute("SELECT * FROM alert_destinations ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        try:
            d["config"] = json.loads(d.pop("config_json", "{}") or "{}")
        except json.JSONDecodeError:
            d["config"] = {}
        out.append(d)
    return out


def delete_destination(dest_id: str) -> bool:
    with db.get_connection() as con:
        cur = con.execute("DELETE FROM alert_destinations WHERE id=?", (dest_id,))
    return cur.rowcount > 0


def toggle_destination(dest_id: str, enabled: bool) -> bool:
    with db.get_connection() as con:
        cur = con.execute(
            "UPDATE alert_destinations SET enabled=?, updated_at=? WHERE id=?",
            (int(enabled), _now(), dest_id),
        )
    return cur.rowcount > 0


def delivery_history(limit: int = 50) -> list[dict]:
    with db.get_connection() as con:
        rows = con.execute(
            """SELECT ad.*, d.name AS destination_name, d.kind AS destination_kind
               FROM alert_deliveries ad
               JOIN alert_destinations d ON d.id = ad.destination_id
               ORDER BY ad.created_at DESC LIMIT ?""",
            (min(limit, 500),),
        ).fetchall()
    return [dict(r) for r in rows]
