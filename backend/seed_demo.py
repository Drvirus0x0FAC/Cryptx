"""
Seed the CrypTX conference demo case ("Operation Ember Forge") into the database.

Idempotent: re-running removes the previous demo case/board and re-inserts a fresh copy.
Populates case + addresses + notes + labels + board + forensic/nexus graph + evidence +
victim reports + OSINT sweep + report artifact + address-intel cache — all offline.

Usage (from the backend/ directory):
    python seed_demo.py
Then restart the backend so the Address-Intel / Nexus offline short-circuit loads.
"""
from __future__ import annotations

import json
import sys

import database as db
import boards_engine
import evidence_vault
import demo_data as D


def _cleanup(con):
    """Remove any prior copy of the demo case + board so re-seeding is clean."""
    cid = D.DEMO_CASE_ID
    con.execute("DELETE FROM case_addresses WHERE case_id=?", (cid,))
    con.execute("DELETE FROM case_notes WHERE case_id=?", (cid,))
    con.execute("DELETE FROM boards WHERE id=? OR case_id=?", (D.DEMO_BOARD_ID, cid))
    con.execute("DELETE FROM evidence_vault WHERE case_id=?", (cid,))
    con.execute("DELETE FROM victim_reports WHERE case_id=?", (cid,))
    con.execute("DELETE FROM report_artifacts WHERE case_id=?", (cid,))
    con.execute("DELETE FROM cases WHERE id=?", (cid,))
    # Address-scoped rows (labels/graph/osint/cache) for our demo addresses.
    for a in D.ALL_ADDRESSES:
        con.execute("DELETE FROM local_labels WHERE lower(address)=?", (a.lower(),))
        con.execute("DELETE FROM osint_sweeps WHERE lower(address)=?", (a.lower(),))
        con.execute("DELETE FROM address_cache_v2 WHERE lower(address)=?", (a.lower(),))
    con.commit()


def _ensure_case(con):
    now = db._now()
    con.execute(
        "INSERT INTO cases (id, name, description, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (D.DEMO_CASE_ID, D.DEMO_CASE_NAME,
         "Lazarus/TraderTraitor laundering of the Feb-2025 Bybit heist (~$1.46B). "
         "Full-feature CrypTX demonstration dataset — offline.",
         "active", now, now),
    )
    con.commit()


def seed() -> None:
    con = db.get_connection()
    try:
        _cleanup(con)
        _ensure_case(con)
    finally:
        con.close()

    cid = D.DEMO_CASE_ID

    # Case addresses
    for a in D.CASE_ADDRESSES:
        db.add_address_to_case(cid, a["address"], chain=a["chain"], label=a["label"],
                               notes=a["notes"], risk_score=a["risk_score"], risk_level=a["risk_level"])

    # Case notes
    for note in D.CASE_NOTES:
        db.add_note(cid, note)

    # Local labels (attribution)
    for lb in D.LABELS:
        db.upsert_local_label(lb["address"], chain=lb["chain"], label=lb["label"],
                              category=lb["category"], risk_weight=lb["risk_weight"],
                              confidence=lb["confidence"], source=lb["source"], notes=lb["notes"])

    # Address-intel cache (bonus offline path)
    for addr, intel in D.DEMO_INTEL.items():
        db.cache_set(addr, json.dumps(intel), json.dumps({}), chain=intel.get("chain", ""))

    # Investigation board (centerpiece) with a fixed id for idempotency
    state = D.build_board_state()
    state_json = json.dumps(state)
    now = db._now()
    con = db.get_connection()
    try:
        con.execute(
            "INSERT INTO boards (id, name, description, folder_id, case_id, state, state_hash,"
            " version, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,1,?,?,?)",
            (D.DEMO_BOARD_ID, "Ember Forge — Laundering Network", "Bybit heist fund-flow canvas",
             "", cid, state_json, boards_engine._sha256(state_json), "demo", now, now),
        )
        con.commit()
    finally:
        con.close()

    # Forensic run → populates forensic_runs + graph_addresses/edges/transactions + algorithm_outputs
    fp = D.build_forensic_payload()
    db.save_forensic_run(fp["subject"], fp["chain"], fp["summary"], fp["addresses"],
                         fp["transactions"], fp["edges"], fp["outputs"], fp["algorithm_version"])

    # Report artifact (AI-style narrative)
    db.save_report_artifact(D.EXPLOITER, D.REPORT_TITLE, D.REPORT_HTML,
                            chain="ETH", case_id=cid, fmt="html")

    # Evidence vault
    for ev in D.EVIDENCE:
        evidence_vault.save_evidence(cid, ev["evidence_type"], ev["title"], ev["content"],
                                     subject=ev["subject"], chain=ev["chain"], tags=ev["tags"],
                                     analyst_notes=ev["notes"], actor="demo")

    # Victim reports — inserted directly (bypasses a latent .get()-on-Row bug in
    # victim_report._update_intel_cache); the list/detail views read this table directly.
    import uuid as _uuid
    con = db.get_connection()
    try:
        for vr in D.VICTIM_REPORTS:
            now = db._now()
            con.execute(
                """INSERT INTO victim_reports
                   (id, case_id, scam_type, scammer_address, victim_address, amount_usd, token, chain,
                    incident_date, report_date, description, contact_name, contact_email, jurisdiction,
                    status, evidence_hashes, tx_hashes, tags, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(_uuid.uuid4()), cid, vr["scam_type"], vr["scammer_address"].lower(), "",
                 vr["amount_usd"], vr["token"], vr["chain"], vr["incident_date"], now[:10],
                 vr["description"], vr.get("contact_name", ""), "", vr.get("jurisdiction", ""),
                 "open", "[]", json.dumps([]), json.dumps(vr.get("tags", [])), now, now),
            )
        con.commit()
    finally:
        con.close()

    # OSINT sweep cache
    con = db.get_connection()
    try:
        con.execute("INSERT OR REPLACE INTO osint_sweeps (address, result, fetched_at) VALUES (?,?,?)",
                    (D.EXPLOITER.lower(), json.dumps(D.OSINT_SWEEP), db._now()))
        con.commit()
    finally:
        con.close()

    _report()


def _report() -> None:
    con = db.get_connection()
    try:
        def n(q, *a):
            return con.execute(q, a).fetchone()[0]
        print("✓ Demo case seeded: Operation Ember Forge")
        print(f"  case_id            {D.DEMO_CASE_ID}")
        print(f"  case_addresses     {n('SELECT COUNT(*) FROM case_addresses WHERE case_id=?', D.DEMO_CASE_ID)}")
        print(f"  case_notes         {n('SELECT COUNT(*) FROM case_notes WHERE case_id=?', D.DEMO_CASE_ID)}")
        print(f"  local_labels       {n('SELECT COUNT(*) FROM local_labels')}")
        print(f"  boards             {n('SELECT COUNT(*) FROM boards WHERE id=?', D.DEMO_BOARD_ID)}"
              f"  (nodes={len(D.build_board_state()['nodes'])}, edges={len(D.build_board_state()['edges'])})")
        print(f"  graph_addresses    {n('SELECT COUNT(*) FROM graph_addresses')}")
        print(f"  graph_edges        {n('SELECT COUNT(*) FROM graph_edges')}")
        print(f"  forensic_runs      {n('SELECT COUNT(*) FROM forensic_runs')}")
        print(f"  evidence_vault     {n('SELECT COUNT(*) FROM evidence_vault WHERE case_id=?', D.DEMO_CASE_ID)}")
        print(f"  victim_reports     {n('SELECT COUNT(*) FROM victim_reports WHERE case_id=?', D.DEMO_CASE_ID)}")
        print(f"  report_artifacts   {n('SELECT COUNT(*) FROM report_artifacts WHERE case_id=?', D.DEMO_CASE_ID)}")
        print(f"  address_cache_v2   {n('SELECT COUNT(*) FROM address_cache_v2')}")
        print(f"  osint_sweeps       {n('SELECT COUNT(*) FROM osint_sweeps')}")
    finally:
        con.close()


if __name__ == "__main__":
    try:
        seed()
    except Exception as exc:  # noqa: BLE001
        print(f"✗ Seed failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
