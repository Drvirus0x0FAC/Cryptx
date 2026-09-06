"""Smoke tests for the label-growth loop (P2.2)."""
import os
import sys
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import label_growth
import config


def setup_module(module):
    import importlib
    importlib.reload(config)
    label_growth.DB_PATH = config.DB_PATH
    import attribution_engine as ae
    ae.DB_PATH = config.DB_PATH
    ae.init_attribution_tables()
    # Create victim_reports table for testing.
    import sqlite3
    with sqlite3.connect(config.DB_PATH) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS victim_reports (
            id TEXT PRIMARY KEY, address TEXT, chain TEXT DEFAULT 'eth',
            scam_type TEXT, description TEXT, status TEXT DEFAULT 'pending')""")
        con.commit()


def test_import_label_set_basic():
    """Bulk import creates attributions for each item."""
    items = [
        {"address": "0xAAA", "category": "scam", "label": "Test Scammer"},
        {"address": "0xBBB", "category": "exchange", "label": "Test Exchange"},
    ]
    result = label_growth.import_label_set(items, source="test_import")
    assert result["imported"] == 2
    assert result["skipped"] == 0


def test_import_is_idempotent():
    """Re-importing the same addresses with the same source skips them."""
    items = [{"address": "0xCCC", "category": "sanctioned"}]
    r1 = label_growth.import_label_set(items, source="test_idem")
    assert r1["imported"] == 1
    r2 = label_growth.import_label_set(items, source="test_idem")
    assert r2["imported"] == 0
    assert r2["skipped"] == 1


def test_import_different_source_adds():
    """Same address, different source → adds a new attribution."""
    addr = "0xDDD"
    label_growth.import_label_set([{"address": addr}], source="source_a")
    r = label_growth.import_label_set([{"address": addr}], source="source_b")
    assert r["imported"] == 1


def test_import_empty_address_skipped():
    items = [{"address": "", "category": "scam"}, {"address": "0xEEE", "category": "scam"}]
    result = label_growth.import_label_set(items, source="test_empty")
    assert result["imported"] == 1
    assert result["skipped"] == 1


def test_label_stats_returns_counts():
    stats = label_growth.label_stats()
    assert "total_attributions" in stats
    assert "unique_addresses" in stats
    assert "by_source" in stats
    assert "by_category" in stats
    assert stats["total_attributions"] > 0


def test_ingest_victim_reports():
    """Confirmed victim reports get attributed."""
    import sqlite3
    with sqlite3.connect(config.DB_PATH) as con:
        con.execute(
            "INSERT INTO victim_reports (id, address, chain, scam_type, status) VALUES (?,?,?,?,?)",
            ("vr-1", "0xVR1", "eth", "pig_butchering", "confirmed"),
        )
        con.commit()
    result = label_growth.ingest_confirmed_victim_reports()
    assert result["source"] == "victim_reports"
    # At least one imported (or skipped if already exists).
    assert result["imported"] + result["skipped"] >= 1


def test_ingest_skips_pending_reports():
    """Reports with status='pending' are NOT ingested."""
    import sqlite3
    with sqlite3.connect(config.DB_PATH) as con:
        con.execute(
            "INSERT INTO victim_reports (id, address, chain, scam_type, status) VALUES (?,?,?,?,?)",
            ("vr-pending", "0xVPEND", "eth", "phishing", "pending"),
        )
        con.commit()
    # Import and check that 0xvpend was NOT attributed.
    label_growth.ingest_confirmed_victim_reports()
    with sqlite3.connect(config.DB_PATH) as con:
        row = con.execute(
            "SELECT 1 FROM attributions WHERE address=? AND source='victim_report'",
            ("0xvpend",),
        ).fetchone()
    assert row is None


def test_run_growth_loop_returns_summary():
    result = label_growth.run_growth_loop()
    assert "sources_processed" in result
    assert "total_imported" in result
    assert "run_at" in result
