"""Smoke tests for the API key service + rate limiting + metering."""
import os
import sys
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_key_service


def setup_module(module):
    api_key_service.init_api_key_tables()


def test_create_and_lookup_key():
    rec, plain = api_key_service.create_key(org_id="org-a", name="test key")
    assert rec["id"]
    assert rec["key_prefix"].startswith("ctxk_")
    assert plain.startswith("ctxk_")
    # Lookup by plaintext works.
    resolved = api_key_service.lookup_by_plaintext(plain)
    assert resolved is not None
    assert resolved["org_id"] == "org-a"


def test_lookup_rejects_garbage():
    assert api_key_service.lookup_by_plaintext("not-a-key") is None
    assert api_key_service.lookup_by_plaintext("ctxk_nope") is None


def test_hash_not_stored_in_listing():
    api_key_service.create_key(org_id="org-a", name="list test")
    keys = api_key_service.list_keys("org-a")
    assert len(keys) >= 1
    for k in keys:
        assert "key_hash" not in k, "hash must never be exposed in listings"


def test_rate_limit_allows_then_blocks():
    rec, _ = api_key_service.create_key(
        org_id="org-b", name="ratelimit", rate_limit_per_min=3
    )
    allowed1, _, _ = api_key_service.check_rate_limit(rec)
    allowed2, _, _ = api_key_service.check_rate_limit(rec)
    allowed3, _, _ = api_key_service.check_rate_limit(rec)
    blocked, retry, headers = api_key_service.check_rate_limit(rec)
    assert allowed1 and allowed2 and allowed3
    assert not blocked
    assert retry >= 1
    assert "X-RateLimit-Limit" in headers


def test_metering_increments():
    rec, _ = api_key_service.create_key(org_id="org-c", name="metering")
    api_key_service.record_usage(rec["id"])
    api_key_service.record_usage(rec["id"])
    api_key_service.record_usage(rec["id"], error=True)
    usage = api_key_service.get_usage(rec["id"])
    assert usage["total_requests"] == 3
    assert usage["total_errors"] == 1


def test_resolve_user_from_key_carries_org():
    rec, _ = api_key_service.create_key(org_id="org-d", name="resolve", scopes=["read:cases"])
    user = api_key_service.resolve_user_from_key(rec)
    assert user["role"] == "api"
    assert user["org_id"] == "org-d"
    assert "read:cases" in user["_scopes"]
    # Scope check.
    assert api_key_service.has_scope(user, "read:cases")
    assert not api_key_service.has_scope(user, "write:evidence")


def test_org_isolation_in_listing():
    """Keys from org-a must not appear in org-b's listing."""
    api_key_service.create_key(org_id="org-iso-a", name="a1")
    api_key_service.create_key(org_id="org-iso-b", name="b1")
    a_keys = api_key_service.list_keys("org-iso-a")
    b_keys = api_key_service.list_keys("org-iso-b")
    a_names = {k["name"] for k in a_keys}
    b_names = {k["name"] for k in b_keys}
    assert "a1" in a_names and "a1" not in b_names
    assert "b1" in b_names and "b1" not in a_names
