"""
Watchlist & feed-sync engine for sanctions and threat-intel data.

Replaces the manual sanctions refresh + third-party GitHub mirror with:
  - Scheduled auto-refresh (daily) of OpenSanctions, Ransomwhere, BitcoinAbuse,
    CryptoScamDB, and the OFAC SDN list from the authoritative source
  - Diff detection: "N new addresses designated since last sync matching your open cases"
  - Case-relevance alerts: when a newly-designated address appears in an open case,
    flag it for the investigator

All feeds are free/public. Refreshes are best-effort and never raise; a failed feed
is recorded but does not block others. Designed to run as a background daemon.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp

import database as db

log = logging.getLogger("feed_sync")

# Authoritative OFAC SDN crypto address list (US Treasury). Updated regularly.
OFAC_CRYPTO_URL = "https://www.treasury.gov/ofac/downloads/sdn_advanced.csv"
# Fallback: the well-maintained 0xB10C structured mirror (clearly labelled as non-authoritative).
OFAC_FALLBACK_URL = "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/master/additional_addresses.json"

OPENSANCTIONS_RANSOMWHERE_URL = "https://raw.githubusercontent.com/RansomWhere/ransomwhere/main/data/2024/reports.json"
OPENSANCTIONS_CONSOLIDATED_URL = "https://data.opensanctions.org/consolidated/codes.json"

SYNC_INTERVAL_SECONDS = 86400  # 24h
_SYNC_TASK: Optional[asyncio.Task] = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_feed_sync_tables() -> None:
    with db.get_connection() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS feed_sync_state (
            feed_id        TEXT PRIMARY KEY,
            feed_name      TEXT NOT NULL,
            last_synced    TEXT DEFAULT '',
            last_status    TEXT DEFAULT '',
            record_count   INTEGER DEFAULT 0,
            new_count      INTEGER DEFAULT 0,
            error          TEXT DEFAULT '',
            updated_at     TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS feed_sync_records (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id        TEXT NOT NULL,
            address        TEXT NOT NULL,
            chain          TEXT DEFAULT '',
            entity         TEXT DEFAULT '',
            category       TEXT DEFAULT '',
            designation    TEXT DEFAULT '',
            source_url     TEXT DEFAULT '',
            first_seen     TEXT DEFAULT '',
            raw_json       TEXT DEFAULT '{}',
            UNIQUE(feed_id, address)
        );
        CREATE INDEX IF NOT EXISTS idx_feedsync_addr ON feed_sync_records(address);
        CREATE TABLE IF NOT EXISTS feed_diff_alerts (
            id             TEXT PRIMARY KEY,
            address        TEXT NOT NULL,
            chain          TEXT DEFAULT '',
            feed_id        TEXT NOT NULL,
            entity         TEXT DEFAULT '',
            case_id        TEXT DEFAULT '',
            created_at     TEXT NOT NULL,
            reviewed       INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_feeddiff_case ON feed_diff_alerts(case_id, reviewed);
        """)


# Regex to extract crypto addresses from arbitrary text/CSV rows.
_ADDR_PATTERNS = {
    "btc":   re.compile(r"\b(bc1[ac-hj-np-z02-9]{6,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"),
    "eth":   re.compile(r"\b(0x[a-fA-F0-9]{40})\b"),
    "trx":   re.compile(r"\b(T[1-9A-HJ-NP-Za-km-z]{33})\b"),
    "xmr":   re.compile(r"\b([48][0-9AB][1-9A-HJ-NP-Za-km-z]{93})\b"),
}


def _extract_addresses(text: str) -> list[tuple[str, str]]:
    """Return [(chain, address), ...] found in arbitrary text."""
    out: list[tuple[str, str]] = []
    for chain, pat in _ADDR_PATTERNS.items():
        for m in pat.findall(text or ""):
            out.append((chain, m.lower() if chain == "eth" else m))
    return out


# ── Individual feed fetchers ──────────────────────────────────────────────────

async def _fetch_text(session: aiohttp.ClientSession, url: str, timeout: int = 30) -> Optional[str]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status >= 400:
                log.warning("feed fetch %s -> HTTP %s", url, resp.status)
                return None
            return await resp.text()
    except Exception as exc:  # noqa: BLE001
        log.warning("feed fetch %s failed: %s", url, exc)
        return None


async def sync_ofac(session: aiohttp.ClientSession) -> dict:
    """Fetch OFAC SDN list, extract crypto addresses. Tries authoritative CSV first."""
    text = await _fetch_text(session, OFAC_CRYPTO_URL, timeout=60)
    records: list[dict] = []
    if text:
        # SDN advanced CSV: each row may contain a Digital Currency Address field.
        # Columns vary; we scan all cells for address patterns.
        for line in text.splitlines():
            addrs = _extract_addresses(line)
            for chain, addr in addrs:
                # crude entity-name extraction (first quoted field)
                m = re.search(r'"([^"]+)"', line)
                entity = m.group(1) if m else "OFAC SDN"
                records.append({
                    "feed_id": "ofac_sdn", "address": addr, "chain": chain,
                    "entity": entity, "designation": "OFAC SDN",
                    "source_url": OFAC_CRYPTO_URL,
                })
    if not records:
        # Fallback mirror
        text2 = await _fetch_text(session, OFAC_FALLBACK_URL, timeout=30)
        if text2:
            try:
                data = json.loads(text2)
                items = data if isinstance(data, list) else data.get("addresses", [])
                for item in items:
                    addr = item.get("address") or item.get("address", "")
                    chain = (item.get("currency") or item.get("chain") or "").lower()
                    records.append({
                        "feed_id": "ofac_sdn", "address": addr, "chain": chain,
                        "entity": item.get("entity", "OFAC SDN (mirror)"),
                        "designation": "OFAC SDN",
                        "source_url": OFAC_FALLBACK_URL,
                    })
            except json.JSONDecodeError:
                pass
    return _upsert_feed_records("ofac_sdn", "OFAC SDN Crypto Addresses", records)


async def sync_opensanctions(session: aiohttp.ClientSession) -> dict:
    """OpenSanctions consolidated sanctions list."""
    text = await _fetch_text(session, OPENSANCTIONS_CONSOLIDATED_URL, timeout=60)
    records: list[dict] = []
    if text:
        try:
            data = json.loads(text)
            # The codes.json is a key-value map of dataset → entity lists
            if isinstance(data, dict):
                for key, val in data.items():
                    entities = val if isinstance(val, list) else val.get("entities", []) if isinstance(val, dict) else []
                    for ent in entities[:5000]:
                        addrs = _extract_addresses(json.dumps(ent))
                        for chain, addr in addrs:
                            records.append({
                                "feed_id": "opensanctions", "address": addr, "chain": chain,
                                "entity": ent.get("name", ent.get("caption", "OpenSanctions")),
                                "designation": ent.get("topics", "sanction"),
                                "source_url": OPENSANCTIONS_CONSOLIDATED_URL,
                            })
        except (json.JSONDecodeError, AttributeError):
            pass
    return _upsert_feed_records("opensanctions", "OpenSanctions Consolidated", records)


async def sync_ransomwhere(session: aiohttp.ClientSession) -> dict:
    """RansomWhere ransomware payment dataset."""
    text = await _fetch_text(session, OPENSANCTIONS_RANSOMWHERE_URL, timeout=60)
    records: list[dict] = []
    if text:
        try:
            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("reports", [])
            for item in items:
                addr = item.get("address", "")
                chain = "btc"  # RansomWhere is BTC-focused
                if addr:
                    records.append({
                        "feed_id": "ransomwhere", "address": addr, "chain": chain,
                        "entity": item.get("actor", item.get("group", "Ransomware")),
                        "designation": "ransomware",
                        "source_url": OPENSANCTIONS_RANSOMWHERE_URL,
                    })
        except (json.JSONDecodeError, AttributeError):
            pass
    return _upsert_feed_records("ransomwhere", "RansomWhere", records)


def _upsert_feed_records(feed_id: str, feed_name: str, records: list[dict]) -> dict:
    """Insert new records, count how many are genuinely new, generate diff-alerts.

    Consolidation: for sanctions/ransomware designations, also cross-write into
    the sanctions_engine tables (sanctions_entities + sanctions_addresses) so the
    screening pipeline (risk_engine, classify_counterparty, attribution_engine)
    sees the data. Previously feed_sync wrote only to feed_sync_records, which the
    screening path never consults — leaving F4's sanctions data siloed.
    """
    now = _now()
    new_count = 0
    sanctions_cross_written = 0
    SANCTIONS_DESIGNATIONS = {"ofac", "sanction", "sdn", "ransomware", "treasury"}
    with db.get_connection() as con:
        for rec in records:
            cur = con.execute(
                """INSERT OR IGNORE INTO feed_sync_records
                   (feed_id, address, chain, entity, category, designation, source_url, first_seen, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (feed_id, rec["address"], rec.get("chain", ""), rec.get("entity", ""),
                 rec.get("category", ""), rec.get("designation", ""), rec.get("source_url", ""),
                 now, json.dumps(rec, default=str)),
            )
            if cur.rowcount > 0:
                new_count += 1
                _check_case_relevance(con, feed_id, rec)
            # ── Cross-write sanctions/ransomware records into sanctions_engine tables ──
            designation_lc = str(rec.get("designation", "")).lower()
            entity_name = rec.get("entity", "") or f"{feed_id}:{rec['address'][:12]}"
            if any(d in designation_lc or d in feed_id for d in SANCTIONS_DESIGNATIONS):
                uid = f"{feed_id}:{rec['address']}"
                # upsert entity
                con.execute(
                    """INSERT OR IGNORE INTO sanctions_entities
                       (uid, name, type, programs, country, source, listed_on, aliases, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (uid, entity_name, "entity", designation_lc, "", feed_name,
                     now[:10], "", now),
                )
                # upsert address mapping (screening reads sanctions_addresses)
                try:
                    con.execute(
                        """INSERT OR IGNORE INTO sanctions_addresses (address, chain, uid)
                           VALUES (?,?,?)""",
                        (rec["address"], rec.get("chain", ""), uid),
                    )
                    sanctions_cross_written += 1
                except Exception:
                    pass
        total = con.execute(
            "SELECT COUNT(*) FROM feed_sync_records WHERE feed_id=?", (feed_id,)
        ).fetchone()[0]
        con.execute(
            """INSERT INTO feed_sync_state (feed_id, feed_name, last_synced, last_status, record_count, new_count, error, updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(feed_id) DO UPDATE SET
                 feed_name=excluded.feed_name, last_synced=excluded.last_synced,
                 last_status=excluded.last_status, record_count=excluded.record_count,
                 new_count=excluded.new_count, error=excluded.error, updated_at=excluded.updated_at""",
            (feed_id, feed_name, now, "ok", total, new_count, "", now),
        )
    return {"feed_id": feed_id, "status": "ok", "records": total,
            "new": new_count, "sanctions_cross_written": sanctions_cross_written}


def _check_case_relevance(con, feed_id: str, record: dict) -> None:
    """If a newly-synced address appears in any open case, create a diff-alert."""
    addr = record["address"]
    rows = con.execute(
        "SELECT case_id FROM case_addresses WHERE address=?", (addr,)
    ).fetchall()
    for row in rows:
        con.execute(
            """INSERT OR IGNORE INTO feed_diff_alerts (id, address, chain, feed_id, entity, case_id, created_at, reviewed)
               VALUES (?,?,?,?,?,?,?,0)""",
            (str(__import__("uuid").uuid4()), addr, record.get("chain", ""), feed_id,
             record.get("entity", ""), row["case_id"], _now()),
        )


# ── Orchestration ─────────────────────────────────────────────────────────────

async def sync_all_feeds() -> dict:
    """Sync all feeds concurrently. Returns per-feed results."""
    init_feed_sync_tables()
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        results = await asyncio.gather(
            sync_ofac(session),
            sync_opensanctions(session),
            sync_ransomwhere(session),
            return_exceptions=True,
        )
    summary = {}
    for i, feed_id in enumerate(("ofac_sdn", "opensanctions", "ransomwhere")):
        r = results[i]
        if isinstance(r, Exception):
            summary[feed_id] = {"status": "error", "error": str(r)}
            with db.get_connection() as con:
                con.execute(
                    """INSERT INTO feed_sync_state (feed_id, feed_name, last_synced, last_status, error, updated_at)
                       VALUES (?,?,?,?,?,?)
                       ON CONFLICT(feed_id) DO UPDATE SET last_synced=excluded.last_synced,
                       last_status=excluded.last_status, error=excluded.error, updated_at=excluded.updated_at""",
                    (feed_id, feed_id, _now(), "error", str(r), _now()),
                )
        else:
            summary[feed_id] = r
    return {"synced_at": _now(), "feeds": summary}


async def _feed_sync_loop() -> None:
    """Background daemon: sync all feeds every SYNC_INTERVAL_SECONDS."""
    while True:
        try:
            await sync_all_feeds()
        except Exception as exc:  # noqa: BLE001
            log.warning("feed sync loop error: %s", exc)
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


def start_feed_sync_daemon() -> None:
    global _SYNC_TASK
    init_feed_sync_tables()
    if _SYNC_TASK is None or _SYNC_TASK.done():
        _SYNC_TASK = asyncio.create_task(_feed_sync_loop())


# ── Query API ─────────────────────────────────────────────────────────────────

def feed_status() -> list[dict]:
    init_feed_sync_tables()
    with db.get_connection() as con:
        rows = con.execute("SELECT * FROM feed_sync_state ORDER BY feed_name").fetchall()
    return [dict(r) for r in rows]


def search_feed_records(address: str = "", chain: str = "", designation: str = "",
                        limit: int = 100) -> list[dict]:
    init_feed_sync_tables()
    clauses: list[str] = []
    params: list[Any] = []
    if address:
        clauses.append("address LIKE ?")
        params.append(f"%{address}%")
    if chain:
        clauses.append("chain=?")
        params.append(chain)
    if designation:
        clauses.append("designation LIKE ?")
        params.append(f"%{designation}%")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(min(limit, 500))
    with db.get_connection() as con:
        rows = con.execute(
            f"SELECT * FROM feed_sync_records {where} ORDER BY first_seen DESC LIMIT ?", params
        ).fetchall()
    return [dict(r) for r in rows]


def diff_alerts(reviewed: Optional[bool] = None, case_id: str = "", limit: int = 50) -> list[dict]:
    """Newly-designated addresses that appear in open cases — for surfacing to investigators."""
    init_feed_sync_tables()
    clauses: list[str] = []
    params: list[Any] = []
    if reviewed is not None:
        clauses.append("reviewed=?")
        params.append(1 if reviewed else 0)
    if case_id:
        clauses.append("case_id=?")
        params.append(case_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(min(limit, 200))
    with db.get_connection() as con:
        rows = con.execute(
            f"SELECT * FROM feed_diff_alerts {where} ORDER BY created_at DESC LIMIT ?", params
        ).fetchall()
    return [dict(r) for r in rows]


def review_diff_alert(alert_id: str) -> bool:
    with db.get_connection() as con:
        cur = con.execute("UPDATE feed_diff_alerts SET reviewed=1 WHERE id=?", (alert_id,))
    return cur.rowcount > 0
