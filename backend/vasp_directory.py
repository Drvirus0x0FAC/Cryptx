"""
Know-Your-VASP (KYV) directory.

Maps blockchain addresses to known Virtual Asset Service Providers (exchanges,
custodians, payment processors) so investigators can tag deposit/withdrawal
endpoints, identify off-ramps, and populate Travel Rule originator/beneficiary
fields.

Ships with a seed of publicly-known exchange hot/deposit wallets and is fully
extensible at runtime (add_vasp). This is attribution intelligence: treat a
match as a strong lead, corroborate before any compliance filing.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH

# Publicly documented exchange wallets (labelled hot/cold wallets widely cited
# by block explorers). Representative seed — extend via add_vasp / import.
SEED_VASPS: list[dict[str, Any]] = [
    {"name": "Binance", "type": "exchange", "country": "KY", "jurisdiction": "Cayman Islands",
     "addresses": [
         {"chain": "eth", "address": "0x28c6c06298d514db089934071355e5743bf21d60", "label": "Binance Hot Wallet 14"},
         {"chain": "eth", "address": "0x21a31ee1afc51d94c2efccaa2092ad1028285549", "label": "Binance Hot Wallet 15"},
         {"chain": "eth", "address": "0xdfd5293d8e347dfe59e90efd55b2956a1343963d", "label": "Binance Hot Wallet 16"},
         {"chain": "btc", "address": "34xp4vrocgjym3xr7ycvpfhocnxv4twseo", "label": "Binance Cold Wallet"},
     ]},
    {"name": "Coinbase", "type": "exchange", "country": "US", "jurisdiction": "United States",
     "addresses": [
         {"chain": "eth", "address": "0x71660c4005ba85c37ccec55d0c4493e66fe775d3", "label": "Coinbase 1"},
         {"chain": "eth", "address": "0x503828976d22510aad0201ac7ec88293211d23da", "label": "Coinbase 2"},
         {"chain": "eth", "address": "0xddfabcdc4d8ffc6d5beaf154f18b778f892a0740", "label": "Coinbase 3"},
     ]},
    {"name": "Kraken", "type": "exchange", "country": "US", "jurisdiction": "United States",
     "addresses": [
         {"chain": "eth", "address": "0x2910543af39aba0cd09dbb2d50200b3e800a63d2", "label": "Kraken 1"},
         {"chain": "eth", "address": "0xe853c56864a2ebe4576a807d26fdc4a0ada51919", "label": "Kraken 4"},
     ]},
    {"name": "OKX", "type": "exchange", "country": "SC", "jurisdiction": "Seychelles",
     "addresses": [
         {"chain": "eth", "address": "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b", "label": "OKX"},
         {"chain": "eth", "address": "0x236f9f97e0e62388479bf9e5ba4889e46b0273c3", "label": "OKX 2"},
     ]},
    {"name": "Bitfinex", "type": "exchange", "country": "VG", "jurisdiction": "British Virgin Islands",
     "addresses": [
         {"chain": "eth", "address": "0x1151314c646ce4e0efd76d1af4760ae66a9fe30f", "label": "Bitfinex 2"},
         {"chain": "eth", "address": "0x876eabf441b2ee5b5b0554fd502a8e0600950cfa", "label": "Bitfinex 3"},
     ]},
    {"name": "Crypto.com", "type": "exchange", "country": "SG", "jurisdiction": "Singapore",
     "addresses": [
         {"chain": "eth", "address": "0x6262998ced04146fa42253a5c0af90ca02dfd2a3", "label": "Crypto.com 1"},
         {"chain": "eth", "address": "0x46340b20830761efd32832a74d7169b29feb9758", "label": "Crypto.com 2"},
     ]},
]


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_vasp_tables() -> None:
    with _conn() as con:
        con.executescript(
            """
        CREATE TABLE IF NOT EXISTS vasp_directory (
            address      TEXT NOT NULL,
            chain        TEXT DEFAULT '',
            vasp_name    TEXT NOT NULL,
            vasp_type    TEXT DEFAULT 'exchange',
            country      TEXT DEFAULT '',
            jurisdiction TEXT DEFAULT '',
            label        TEXT DEFAULT '',
            source       TEXT DEFAULT 'seed',
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (address)
        );
        CREATE INDEX IF NOT EXISTS idx_vasp_name ON vasp_directory(vasp_name);
            """
        )
    _seed_if_empty()


def _seed_if_empty() -> None:
    with _conn() as con:
        n = con.execute("SELECT COUNT(*) AS n FROM vasp_directory").fetchone()["n"]
        if n:
            return
        for v in SEED_VASPS:
            for a in v["addresses"]:
                con.execute(
                    """INSERT OR IGNORE INTO vasp_directory
                       (address, chain, vasp_name, vasp_type, country, jurisdiction, label, source, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        a["address"].strip().lower(), a.get("chain", ""), v["name"], v.get("type", "exchange"),
                        v.get("country", ""), v.get("jurisdiction", ""), a.get("label", ""), "seed", _now(),
                    ),
                )


def identify_vasp(address: str, chain: Optional[str] = None) -> dict[str, Any]:
    a = (address or "").strip().lower()
    if not a:
        return {"address": address, "is_vasp": False, "vasp": None}
    with _conn() as con:
        row = con.execute("SELECT * FROM vasp_directory WHERE address = ?", (a,)).fetchone()
    if not row:
        return {"address": address, "is_vasp": False, "vasp": None}
    return {
        "address": address,
        "is_vasp": True,
        "vasp": {
            "name": row["vasp_name"],
            "type": row["vasp_type"],
            "country": row["country"],
            "jurisdiction": row["jurisdiction"],
            "label": row["label"],
            "chain": row["chain"],
            "source": row["source"],
        },
    }


def add_vasp(address: str, vasp_name: str, vasp_type: str = "exchange", chain: str = "",
             country: str = "", jurisdiction: str = "", label: str = "") -> dict[str, Any]:
    a = (address or "").strip().lower()
    if not a or not vasp_name.strip():
        raise ValueError("address and vasp_name are required")
    with _conn() as con:
        con.execute(
            """INSERT INTO vasp_directory
               (address, chain, vasp_name, vasp_type, country, jurisdiction, label, source, updated_at)
               VALUES (?,?,?,?,?,?,?, 'manual', ?)
               ON CONFLICT(address) DO UPDATE SET
                 vasp_name=excluded.vasp_name, vasp_type=excluded.vasp_type, chain=excluded.chain,
                 country=excluded.country, jurisdiction=excluded.jurisdiction, label=excluded.label,
                 source='manual', updated_at=excluded.updated_at""",
            (a, chain, vasp_name.strip(), vasp_type, country, jurisdiction, label, _now()),
        )
    return identify_vasp(a, chain)


def list_vasps() -> dict[str, Any]:
    with _conn() as con:
        rows = con.execute(
            "SELECT vasp_name, vasp_type, country, jurisdiction, COUNT(*) AS addresses "
            "FROM vasp_directory GROUP BY vasp_name ORDER BY vasp_name"
        ).fetchall()
        total = con.execute("SELECT COUNT(*) AS n FROM vasp_directory").fetchone()["n"]
    return {
        "vasp_count": len(rows),
        "address_count": total,
        "vasps": [dict(r) for r in rows],
    }


if __name__ == "__main__":
    init_vasp_tables()
    print(list_vasps())
    print(identify_vasp("0x28C6c06298d514Db089934071355E5743bf21d60"))
