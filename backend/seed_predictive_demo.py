"""
Seed a synthetic 'staging' wallet so the Predictive AI features can be tested
end-to-end without waiting for real on-chain data.

Creates address 0xdemo...bad1 with: dormancy awakening, peel-chain fan-out,
mixer counterparty, structuring-band transfers, and inbound dust.

Run:    python seed_predictive_demo.py
Undo:   python seed_predictive_demo.py --clean
"""
import sys
from datetime import datetime, timedelta, timezone

import database as db

ADDR = "0xdemo00000000000000000000000000000000bad1"
INV_ID = "predictive-demo"


def clean():
    with db.get_connection() as con:
        con.execute("DELETE FROM investigation_edges WHERE investigation_id=?", (INV_ID,))
        con.execute("DELETE FROM investigations WHERE id=?", (INV_ID,))
        con.execute("DELETE FROM local_labels WHERE address='0xdemomixer0000000000000000000000000000001'")
        con.execute("DELETE FROM predictive_features WHERE address=?", (ADDR,))
        con.execute("DELETE FROM predictive_predictions WHERE address=?", (ADDR,))
    print("demo data removed")


def seed():
    now = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    edges = []
    # old activity, then 60+ day dormancy gap
    edges.append((ADDR, "0xoldcp0000000000000000000000000000000001", 9500, (now - timedelta(days=90)).strftime(fmt)))
    # awakening burst: peel-chain fan-out to fresh wallets in one day
    val = 50_000.0
    for i in range(8):
        ts = (now - timedelta(days=2, hours=8 - i)).strftime(fmt)
        edges.append((ADDR, f"0xfresh{i:037d}", val, ts))
        val *= 0.8
    # mixer approach + structuring-band transfer
    edges.append((ADDR, "0xdemomixer0000000000000000000000000000001", 9200, (now - timedelta(days=1)).strftime(fmt)))
    # inbound dust (victim-targeting signal)
    edges.append(("0xdust00000000000000000000000000000000000a", ADDR, 0.5, (now - timedelta(days=3)).strftime(fmt)))

    with db.get_connection() as con:
        con.execute(
            """INSERT OR REPLACE INTO investigations(id, subject, chain, name, created_at, updated_at)
               VALUES(?, ?, 'eth', 'Predictive demo', ?, ?)""",
            (INV_ID, ADDR, now.strftime(fmt), now.strftime(fmt)))
        con.execute("DELETE FROM investigation_edges WHERE investigation_id=?", (INV_ID,))
        for i, (s, t, v, ts) in enumerate(edges):
            con.execute(
                """INSERT INTO investigation_edges(investigation_id, source, target, chain,
                     tx_hash, token, value, value_usd, timestamp, edge_type)
                   VALUES(?,?,?,'eth',?,'usdt',?,?,?,'transfer')""",
                (INV_ID, s, t, f"0xdemohash{i}", v, v, ts))
        con.execute(
            """INSERT INTO local_labels(chain, address, label, category, created_at, updated_at)
               VALUES('eth','0xdemomixer0000000000000000000000000000001','Tornado Cash','mixer',?,?)""",
            (now.strftime(fmt), now.strftime(fmt)))
    print(f"seeded. Test subject:\n  {ADDR}")
    print("Expected: laundering ~70% HIGH, horizon 24-72h, mixer/peel-chain/dormancy evidence")


if __name__ == "__main__":
    clean() if "--clean" in sys.argv else seed()
