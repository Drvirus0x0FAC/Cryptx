"""Smoke tests for RFC-3161 TSA integration in daubert notarize + evidence vault."""
import os
import sys
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name
# Ensure TSA_URL is unset so we test the graceful-degradation path.
os.environ.pop("TSA_URL", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reload config so TSA_URL='' takes effect even if imported earlier.
import importlib
import config
importlib.reload(config)

import daubert_engine as de


def test_notarize_without_tsa_returns_local_record():
    """When TSA_URL is unset, notarize returns the local hash-chain record with a
    note explaining how to enable TSA — no tsa field with verified=True."""
    rec = de.notarize({"exhibit": "test"}, label="exhibit-1")
    assert rec["content_sha256"]
    assert rec["chain_hash"]
    assert rec["timestamp_utc"]
    assert "note" in rec
    # No TSA verification when unconfigured.
    assert not (rec.get("tsa") or {}).get("tsa_verified")


def test_notarize_with_disabled_tsa_url_empty_string():
    """Passing tsa_url='' explicitly disables TSA even if config had one."""
    rec = de.notarize({"x": 1}, tsa_url="")
    assert rec["content_sha256"]
    assert "note" in rec
    assert not (rec.get("tsa") or {}).get("tsa_verified")


def test_notarize_chain_links_correctly():
    """Two consecutive notarizations: the second's prev_chain_hash = first's chain_hash."""
    r1 = de.notarize({"a": 1})
    r2 = de.notarize({"b": 2}, prev_hash=r1["chain_hash"])
    assert r2["prev_chain_hash"] == r1["chain_hash"]
    # Verify the chain.
    result = de.verify_chain([r1, r2])
    assert result["valid"] is True


def test_notarize_tamper_detection():
    """Modifying a record's content_hash breaks verify_chain."""
    r1 = de.notarize({"a": 1})
    r2 = de.notarize({"b": 2}, prev_hash=r1["chain_hash"])
    r2_tampered = dict(r2)
    r2_tampered["content_sha256"] = "0000000000000000"
    result = de.verify_chain([r1, r2_tampered])
    assert result["valid"] is False
    assert result["broken_at_index"] == 1


def test_tsa_client_graceful_when_url_unset():
    """tsa_client.request_timestamp returns tsa_verified=False (not an exception)
    when TSA_URL is unset."""
    import tsa_client
    result = tsa_client.request_timestamp(b"some content")
    assert result["tsa_verified"] is False
    assert result["tsa_error"]


def test_evidence_vault_saves_with_tsa_column():
    """save_evidence works with the new tsa_token column (empty when TSA unset)."""
    import database
    database.init_db()
    import evidence_vault as ev
    ev.init_evidence_tables()
    # Create a case to attach evidence to.
    case = database.create_case("TSA test case")
    rec = ev.save_evidence(
        case_id=case["id"],
        evidence_type="report_export",
        title="Test exhibit",
        content={"finding": "test"},
    )
    assert rec["id"]
    assert rec["content_hash"]
    assert rec["chain_hash"]
    # tsa_token column exists and is empty (TSA unconfigured).
    assert rec.get("tsa_token") in ("", None)
