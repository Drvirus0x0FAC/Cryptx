"""
Multi-jurisdiction sanctions screening engine.

Screens blockchain addresses and entity names against:
  - OFAC SDN (US Treasury) — including designated digital-currency addresses
  - OpenSanctions consolidated lists (EU, UK, UN, CA, CH, AU, and more)

Design goals:
  - Works fully OFFLINE from a bundled seed of publicly-known sanctioned
    crypto addresses, so screening is always available.
  - Enriches from free public sources on demand via refresh() (best-effort;
    network failures degrade gracefully and never break screening).
  - Fuzzy name search implemented in pure Python (no extra dependencies).

This is investigative tooling: a match is a strong lead that must be confirmed
against the official primary source before any compliance action.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Optional

import config as _config
DB_PATH = _config.DB_PATH

# Free, public, no-key sources. Parsed best-effort; format autodetected.
# OpenSanctions "simple CSV" schema:
#   id,schema,name,aliases,birth_date,countries,addresses,identifiers,
#   sanctions,phones,emails,dataset,first_seen,last_seen,last_change
DEFAULT_SOURCES: list[dict[str, str]] = [
    {
        "name": "OpenSanctions Consolidated",
        "url": "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv",
        "format": "opensanctions_simple",
    },
    {
        "name": "OpenSanctions Crypto Wallets",
        "url": "https://data.opensanctions.org/datasets/latest/crypto/targets.simple.csv",
        "format": "opensanctions_simple",
    },
]

# ---------------------------------------------------------------------------
# Bundled seed — publicly disclosed OFAC-designated crypto addresses & entities.
# Source: US Treasury OFAC SDN press releases (public record). Representative,
# not exhaustive; refresh() augments this from live feeds.
# ---------------------------------------------------------------------------
SEED_ENTITIES: list[dict[str, Any]] = [
    {
        "uid": "ofac-tornado-cash",
        "name": "TORNADO CASH",
        "type": "entity",
        "programs": ["CYBER2"],
        "country": "",
        "source": "OFAC SDN",
        "listed_on": "2022-08-08",
        "aliases": ["Tornado.Cash", "Tornado Cash Classic"],
        "addresses": [
            {"chain": "eth", "address": "0x8589427373d6d84e98730d7795d8f6f8731fda16"},
            {"chain": "eth", "address": "0x722122df12d4e14e13ac3b6895a86e84145b6967"},
            {"chain": "eth", "address": "0xdd4c48c0b24039969fc16d1cdf626eab821d3384"},
            {"chain": "eth", "address": "0xd90e2f925da726b50c4 ed8d0fb90ad053324f31b".replace(" ", "")},
            {"chain": "eth", "address": "0xa160cdab225685da1d56aa342ad8841c3b53f291"},
            {"chain": "eth", "address": "0xfac583c0cf07ec513e2faab7f4cc40decabddc1c"},
        ],
    },
    {
        "uid": "ofac-lazarus-group",
        "name": "LAZARUS GROUP",
        "type": "entity",
        "programs": ["DPRK", "CYBER2"],
        "country": "KP",
        "source": "OFAC SDN",
        "listed_on": "2019-09-13",
        "aliases": ["APT38", "Hidden Cobra", "Guardians of Peace"],
        "addresses": [
            {"chain": "eth", "address": "0x098b716b8aaf21512996dc57eb0615e2383e2f96"},
            {"chain": "btc", "address": "1jbenet7zhwj8j5vqzkvgk2zywsysmnwha".upper().lower()},
        ],
    },
    {
        "uid": "ofac-blender-io",
        "name": "BLENDER.IO",
        "type": "entity",
        "programs": ["DPRK", "CYBER2"],
        "country": "",
        "source": "OFAC SDN",
        "listed_on": "2022-05-06",
        "aliases": ["Blender"],
        "addresses": [
            {"chain": "btc", "address": "bc1qxmtttmw7lr4d2gw0n7e0qkjxr5lcsxytar6mra"},
        ],
    },
    {
        "uid": "ofac-garantex",
        "name": "GARANTEX EUROPE OU",
        "type": "entity",
        "programs": ["RUSSIA-EO14024", "CYBER2"],
        "country": "RU",
        "source": "OFAC SDN",
        "listed_on": "2022-04-05",
        "aliases": ["Garantex"],
        "addresses": [
            {"chain": "eth", "address": "0x32be343b94f860124dc4fee278fdcbd38c102d88"},
        ],
    },
    {
        "uid": "ofac-suex",
        "name": "SUEX OTC, S.R.O.",
        "type": "entity",
        "programs": ["CYBER2"],
        "country": "CZ",
        "source": "OFAC SDN",
        "listed_on": "2021-09-21",
        "aliases": ["Suex"],
        "addresses": [
            {"chain": "btc", "address": "12qtcdndtpyqku9swfej9h4hdcgz7tjydw".lower()},
        ],
    },
    {
        "uid": "ofac-hydra-market",
        "name": "HYDRA MARKET",
        "type": "entity",
        "programs": ["CYBER2", "RUSSIA-EO14024"],
        "country": "RU",
        "source": "OFAC SDN",
        "listed_on": "2022-04-05",
        "aliases": ["Hydra"],
        "addresses": [
            {"chain": "btc", "address": "bc1q4c8n5t00jmj8temxdgcc3t32nkg2wjwz24lywv"},
        ],
    },
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_sanctions_tables() -> None:
    with _conn() as con:
        con.executescript(
            """
        CREATE TABLE IF NOT EXISTS sanctions_entities (
            uid        TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            type       TEXT DEFAULT 'entity',
            programs   TEXT DEFAULT '',
            country    TEXT DEFAULT '',
            source     TEXT DEFAULT '',
            listed_on  TEXT DEFAULT '',
            aliases    TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sanctions_addresses (
            address    TEXT NOT NULL,
            chain      TEXT DEFAULT '',
            uid        TEXT NOT NULL REFERENCES sanctions_entities(uid) ON DELETE CASCADE,
            PRIMARY KEY (address, uid)
        );
        CREATE INDEX IF NOT EXISTS idx_sanctions_addr ON sanctions_addresses(address);
        CREATE TABLE IF NOT EXISTS sanctions_meta (
            key        TEXT PRIMARY KEY,
            value      TEXT
        );
            """
        )
    _seed_if_empty()


def _norm_addr(value: str) -> str:
    return (value or "").strip().lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upsert_entity(con: sqlite3.Connection, ent: dict[str, Any]) -> None:
    con.execute(
        """INSERT INTO sanctions_entities (uid, name, type, programs, country, source, listed_on, aliases, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(uid) DO UPDATE SET
             name=excluded.name, type=excluded.type, programs=excluded.programs,
             country=excluded.country, source=excluded.source, listed_on=excluded.listed_on,
             aliases=excluded.aliases, updated_at=excluded.updated_at""",
        (
            ent["uid"],
            ent["name"],
            ent.get("type", "entity"),
            "; ".join(ent.get("programs", []) or []),
            ent.get("country", ""),
            ent.get("source", ""),
            ent.get("listed_on", ""),
            "; ".join(ent.get("aliases", []) or []),
            _now(),
        ),
    )
    for addr in ent.get("addresses", []) or []:
        a = _norm_addr(addr.get("address", ""))
        if not a:
            continue
        con.execute(
            "INSERT OR IGNORE INTO sanctions_addresses (address, chain, uid) VALUES (?,?,?)",
            (a, addr.get("chain", ""), ent["uid"]),
        )


def _seed_if_empty() -> None:
    with _conn() as con:
        count = con.execute("SELECT COUNT(*) AS n FROM sanctions_entities").fetchone()["n"]
        if count:
            return
        for ent in SEED_ENTITIES:
            _upsert_entity(con, ent)
        con.execute(
            "INSERT OR REPLACE INTO sanctions_meta (key, value) VALUES ('seeded_at', ?)",
            (_now(),),
        )


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------
def screen_address(address: str, chain: Optional[str] = None) -> dict[str, Any]:
    a = _norm_addr(address)
    if not a:
        return {"address": address, "sanctioned": False, "matches": [], "checked_at": _now()}
    with _conn() as con:
        rows = con.execute(
            """SELECT e.uid, e.name, e.type, e.programs, e.country, e.source, e.listed_on, e.aliases, sa.chain
               FROM sanctions_addresses sa JOIN sanctions_entities e ON e.uid = sa.uid
               WHERE sa.address = ?""",
            (a,),
        ).fetchall()
    matches = [
        {
            "uid": r["uid"],
            "name": r["name"],
            "type": r["type"],
            "programs": [p for p in (r["programs"] or "").split("; ") if p],
            "country": r["country"],
            "source": r["source"],
            "listed_on": r["listed_on"],
            "aliases": [x for x in (r["aliases"] or "").split("; ") if x],
            "matched_chain": r["chain"],
        }
        for r in rows
        if not chain or not r["chain"] or r["chain"].lower() == chain.lower()
    ]
    return {
        "address": address,
        "chain": chain or "",
        "sanctioned": bool(matches),
        "match_count": len(matches),
        "matches": matches,
        "checked_at": _now(),
    }


def get_entity(uid: str) -> Optional[dict[str, Any]]:
    """Return full details for a single sanctioned entity, including every
    associated blockchain address. Returns None if the uid is unknown."""
    uid = (uid or "").strip()
    if not uid:
        return None
    with _conn() as con:
        row = con.execute(
            """SELECT uid, name, type, programs, country, source, listed_on, aliases, updated_at
               FROM sanctions_entities WHERE uid = ?""",
            (uid,),
        ).fetchone()
        if not row:
            return None
        addr_rows = con.execute(
            "SELECT address, chain FROM sanctions_addresses WHERE uid = ? ORDER BY chain, address",
            (uid,),
        ).fetchall()
    return {
        "uid": row["uid"],
        "name": row["name"],
        "type": row["type"],
        "programs": [p for p in (row["programs"] or "").split("; ") if p],
        "country": row["country"],
        "source": row["source"],
        "listed_on": row["listed_on"],
        "aliases": [a for a in (row["aliases"] or "").split("; ") if a],
        "updated_at": row["updated_at"],
        "addresses": [{"address": r["address"], "chain": r["chain"] or ""} for r in addr_rows],
        "address_count": len(addr_rows),
    }


def screen_addresses(addresses: Iterable[str], chain: Optional[str] = None) -> dict[str, Any]:
    results = [screen_address(a, chain) for a in addresses]
    return {
        "total": len(results),
        "sanctioned_count": sum(1 for r in results if r["sanctioned"]),
        "results": results,
        "checked_at": _now(),
    }


# ---------------------------------------------------------------------------
# Fuzzy name search (pure Python)
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(value: str) -> set[str]:
    return set(_WORD_RE.findall((value or "").lower()))


def _name_score(query: str, candidate: str) -> float:
    q, c = (query or "").lower().strip(), (candidate or "").lower().strip()
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.93
    ratio = SequenceMatcher(None, q, c).ratio()
    qt, ct = _tokens(q), _tokens(c)
    jacc = len(qt & ct) / len(qt | ct) if (qt | ct) else 0.0
    return round(max(ratio, 0.5 * ratio + 0.5 * jacc), 4)


def search_name(query: str, limit: int = 25, min_score: float = 0.55) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"query": query, "matches": [], "checked_at": _now()}
    with _conn() as con:
        rows = con.execute(
            "SELECT uid, name, type, programs, country, source, listed_on, aliases FROM sanctions_entities"
        ).fetchall()
    scored = []
    for r in rows:
        names = [r["name"]] + [a for a in (r["aliases"] or "").split("; ") if a]
        best = max((_name_score(q, n) for n in names), default=0.0)
        if best >= min_score:
            scored.append(
                {
                    "uid": r["uid"],
                    "name": r["name"],
                    "type": r["type"],
                    "programs": [p for p in (r["programs"] or "").split("; ") if p],
                    "country": r["country"],
                    "source": r["source"],
                    "listed_on": r["listed_on"],
                    "aliases": [a for a in (r["aliases"] or "").split("; ") if a],
                    "score": best,
                }
            )
    scored.sort(key=lambda m: m["score"], reverse=True)
    return {"query": q, "match_count": len(scored), "matches": scored[:limit], "checked_at": _now()}


# ---------------------------------------------------------------------------
# Refresh from live public feeds (best-effort)
# ---------------------------------------------------------------------------
def _parse_opensanctions_simple(text: str, source_name: str) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        addr_field = row.get("addresses") or ""
        ident_field = row.get("identifiers") or ""
        # crypto wallets usually surface in identifiers/addresses as 0x.. / bc1.. / etc.
        raw = f"{addr_field};{ident_field}"
        wallets = re.findall(r"(0x[a-fA-F0-9]{40}|bc1[a-z0-9]{20,}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|T[1-9A-HJ-NP-Za-km-z]{33})", raw)
        if not wallets:
            continue
        uid = f"os-{row.get('id') or row.get('name')}"
        entities.append(
            {
                "uid": uid,
                "name": row.get("name") or "(unnamed)",
                "type": (row.get("schema") or "entity").lower(),
                "programs": [p for p in (row.get("sanctions") or "").split(";") if p][:6],
                "country": (row.get("countries") or "").split(";")[0],
                "source": source_name,
                "listed_on": (row.get("first_seen") or "")[:10],
                "aliases": [a for a in (row.get("aliases") or "").split(";") if a][:8],
                "addresses": [{"chain": "", "address": w} for w in set(wallets)],
            }
        )
    return entities


def refresh(sources: Optional[list[dict[str, str]]] = None, timeout: int = 30) -> dict[str, Any]:
    """Best-effort pull from public feeds. Never raises; returns a per-source report."""
    import requests  # local import; requests is already a dependency

    sources = sources or DEFAULT_SOURCES
    report: list[dict[str, Any]] = []
    total_added = 0
    for src in sources:
        entry: dict[str, Any] = {"name": src["name"], "url": src["url"], "ok": False, "entities": 0, "error": None}
        try:
            resp = requests.get(src["url"], timeout=timeout, headers={"User-Agent": "CryptoOSINT/1.0"})
            if resp.status_code != 200:
                entry["error"] = f"HTTP {resp.status_code}"
                report.append(entry)
                continue
            if src["format"] == "opensanctions_simple":
                ents = _parse_opensanctions_simple(resp.text, src["name"])
            else:
                ents = []
            with _conn() as con:
                for ent in ents:
                    _upsert_entity(con, ent)
            entry["ok"] = True
            entry["entities"] = len(ents)
            total_added += len(ents)
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
        report.append(entry)

    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO sanctions_meta (key, value) VALUES ('refreshed_at', ?)",
            (_now(),),
        )
    return {"refreshed_at": _now(), "entities_added": total_added, "sources": report}


def status() -> dict[str, Any]:
    with _conn() as con:
        ents = con.execute("SELECT COUNT(*) AS n FROM sanctions_entities").fetchone()["n"]
        addrs = con.execute("SELECT COUNT(*) AS n FROM sanctions_addresses").fetchone()["n"]
        meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM sanctions_meta").fetchall()}
        by_source = con.execute(
            "SELECT source, COUNT(*) AS n FROM sanctions_entities GROUP BY source ORDER BY n DESC"
        ).fetchall()
    return {
        "entity_count": ents,
        "address_count": addrs,
        "seeded_at": meta.get("seeded_at"),
        "refreshed_at": meta.get("refreshed_at"),
        "sources": [{"source": r["source"] or "(seed)", "entities": r["n"]} for r in by_source],
        "available_feeds": [{"name": s["name"], "url": s["url"]} for s in DEFAULT_SOURCES],
    }


if __name__ == "__main__":
    init_sanctions_tables()
    print("status:", status())
    print("screen TC:", screen_address("0x8589427373D6D84E98730D7795D8f6f8731FDA16"))
    print("search:", search_name("tornado"))
