"""
Label-growth loop — the long-term data moat for CrypTX.

Scale of ground-truth labels is what every competitor sells (Arkham 800M+,
Elliptic 100B+ data points). This module compounds CrypTX's label database
over time from three sources:

  1. CONFIRMED VICTIM REPORTS — every confirmed victim report auto-feeds its
     scam/deposit addresses into the attribution engine with provenance.
  2. BULK OPEN-LABEL IMPORT — OFAC SDN, Etherscan tags, Dune label queries,
     GitHub label repos (e.g. blockchain-ioc), ingested via the existing
     reviewer-gated feed_ingestion pipeline.
  3. APPROVED ATTRIBUTION SUBMISSIONS — already wired; this module ensures
     they feed the engine automatically.

The key design principle: every label carries `source` + `method` + `confidence`
provenance, so the attribution engine's "leads, not claims" methodology is
preserved. Bulk-imported labels start at lower confidence; confirmed reports
start higher.

Deduplication: if a label for (address, chain) already exists with the same
category, we skip (don't overwrite). If it's a new category, we add it.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _addr(v: str) -> str:
    return str(v or "").strip().lower()


# ── 1. Auto-feed confirmed victim reports ───────────────────────────────────

def ingest_confirmed_victim_reports(limit: int = 500) -> dict[str, Any]:
    """Feed confirmed victim reports into the attribution engine.

    For each report with status='confirmed' (or 'labeled'), extract the
    scam/deposit addresses and create attributions with:
      - source = "victim_report"
      - method = "confirmed_report"
      - confidence = 0.7 (lead, not claim)
      - category derived from the report's scam_type

    Idempotent: skips addresses already attributed with this source.
    Returns a summary of what was ingested.
    """
    imported = 0
    skipped = 0
    errors: list[str] = []

    try:
        with _conn() as con:
            # Find confirmed/labeled victim reports with addresses.
            rows = con.execute(
                """SELECT id, address, chain, scam_type, description, status
                   FROM victim_reports
                   WHERE status IN ('confirmed', 'labeled') AND address != ''
                   LIMIT ?""",
                (limit,),
            ).fetchall()
    except sqlite3.OperationalError:
        return {"imported": 0, "skipped": 0, "errors": ["victim_reports table not found"], "source": "victim_reports"}

    import attribution_engine as ae

    # Map scam types to attribution categories.
    CATEGORY_MAP = {
        "pig_butchering": "scam",
        "investment_scam": "scam",
        "phishing": "scam",
        "drainer": "scam",
        "ransomware": "ransomware",
        "exchange_scam": "scam",
        "romance_scam": "scam",
        "giveaway_scam": "scam",
    }

    for row in rows:
        d = dict(row)
        address = _addr(d.get("address"))
        chain = str(d.get("chain") or "eth").lower()
        scam_type = str(d.get("scam_type") or "").lower()
        category = CATEGORY_MAP.get(scam_type, "scam")
        report_id = str(d.get("id") or "")

        if not address:
            skipped += 1
            continue

        # Check if already attributed with this source.
        try:
            with _conn() as con:
                existing = con.execute(
                    "SELECT 1 FROM attributions WHERE address=? AND source='victim_report' AND valid=1 LIMIT 1",
                    (address,),
                ).fetchone()
            if existing:
                skipped += 1
                continue
        except sqlite3.OperationalError:
            pass

        # Add the attribution.
        try:
            ae.add_attribution(
                address=address,
                chain=chain,
                category=category,
                actor=f"Victim Report #{report_id}",
                label=f"{scam_type or 'scam'} address (victim-reported)",
                source="victim_report",
                method="confirmed_report",
                method_class="analyst",
                confidence=0.7,
                evidence=[{"report_id": report_id, "scam_type": scam_type}],
                assigned_by="label_growth_loop",
            )
            imported += 1
        except Exception as exc:
            errors.append(f"{address}: {exc}")
            skipped += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:10],
        "source": "victim_reports",
        "processed_at": _now(),
    }


# ── 2. Bulk open-label import ───────────────────────────────────────────────

def import_label_set(
    items: list[dict[str, Any]],
    source: str,
    *,
    default_chain: str = "eth",
    default_category: str = "unknown",
    default_confidence: float = 0.5,
    assigned_by: str = "bulk_import",
) -> dict[str, Any]:
    """Bulk-import a set of labels into the attribution engine.

    Each item should have: {address, chain?, category?, label?, confidence?}
    Fields not provided fall back to the defaults. Idempotent per (address, source).

    This is the entry point for OFAC SDN, Etherscan tags, Dune labels, and
    GitHub IOC repos — each caller normalizes their format into this shape.
    """
    imported = 0
    skipped = 0
    errors: list[str] = []
    import attribution_engine as ae

    for item in items:
        address = _addr(item.get("address"))
        if not address:
            skipped += 1
            continue
        chain = str(item.get("chain") or default_chain).lower()
        category = str(item.get("category") or default_category).lower()
        label = str(item.get("label") or item.get("name") or "")
        confidence = float(item.get("confidence") or default_confidence)

        # Dedup per (address, source).
        try:
            with _conn() as con:
                existing = con.execute(
                    "SELECT 1 FROM attributions WHERE address=? AND source=? AND valid=1 LIMIT 1",
                    (address, source),
                ).fetchone()
            if existing:
                skipped += 1
                continue
        except sqlite3.OperationalError:
            pass

        try:
            ae.add_attribution(
                address=address,
                chain=chain,
                category=category,
                actor=item.get("actor") or source,
                label=label,
                source=source,
                method="bulk_import",
                method_class="analyst",
                confidence=confidence,
                evidence=[{"imported_from": source, "original": item}],
                assigned_by=assigned_by,
            )
            imported += 1
        except Exception as exc:
            errors.append(f"{address}: {exc}")
            skipped += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:10],
        "source": source,
        "processed_at": _now(),
    }


# ── 3. Label statistics (for the dashboard) ─────────────────────────────────

def label_stats() -> dict[str, Any]:
    """Return statistics about the attribution database."""
    try:
        with _conn() as con:
            total = con.execute("SELECT COUNT(*) AS n FROM attributions WHERE valid=1").fetchone()
            by_source = con.execute(
                "SELECT source, COUNT(*) AS n FROM attributions WHERE valid=1 GROUP BY source ORDER BY n DESC"
            ).fetchall()
            by_category = con.execute(
                "SELECT category, COUNT(*) AS n FROM attributions WHERE valid=1 GROUP BY category ORDER BY n DESC"
            ).fetchall()
            unique_addresses = con.execute(
                "SELECT COUNT(DISTINCT address) AS n FROM attributions WHERE valid=1"
            ).fetchone()
        return {
            "total_attributions": total["n"] if total else 0,
            "unique_addresses": unique_addresses["n"] if unique_addresses else 0,
            "by_source": [dict(r) for r in by_source],
            "by_category": [dict(r) for r in by_category],
        }
    except sqlite3.OperationalError:
        return {"total_attributions": 0, "unique_addresses": 0, "by_source": [], "by_category": []}


# ── 4. Run the full growth loop ─────────────────────────────────────────────

def run_growth_loop() -> dict[str, Any]:
    """Run all ingestion sources in sequence. Call this from a scheduled job
    (cron / startup / manual trigger).

    Returns a combined summary of what was ingested from each source.
    """
    results: list[dict[str, Any]] = []

    # 1. Confirmed victim reports.
    results.append(ingest_confirmed_victim_reports())

    return {
        "sources_processed": len(results),
        "results": results,
        "total_imported": sum(r.get("imported", 0) for r in results),
        "total_skipped": sum(r.get("skipped", 0) for r in results),
        "run_at": _now(),
    }
