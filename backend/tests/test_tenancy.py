"""
Smoke tests for the multi-tenancy layer.

Verifies:
  1. init_tenancy_tables() creates organizations + adds org_id to app_users.
  2. A default org is provisioned.
  3. register_user attaches the new user to the default org.
  4. scope() returns enabled=True for an org user and respects global admin.
  5. Two users in different orgs are isolated by org_id.

These tests hit the real SQLite DB (temp file) but do not require network.
Run: cd backend && python -m pytest tests/test_tenancy.py -v
"""
import os
import sys
import tempfile

# Use a temp DB so we never touch the real cryptoosint.db.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name

# backend/ must be on the path (conftest adds it; this also runs standalone).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tenancy
import auth_service


def setup_module(module):
    """Initialize schema fresh for the whole module."""
    auth_service.init_auth_db()
    import database
    database.init_db()
    tenancy.init_tenancy_tables()
    tenancy.ensure_tenant_columns()


def test_organizations_table_exists():
    import sqlite3
    con = sqlite3.connect(tenancy.DB_PATH)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    con.close()
    assert "organizations" in tables


def test_app_users_has_org_id():
    import sqlite3
    con = sqlite3.connect(tenancy.DB_PATH)
    cols = {r[1] for r in con.execute("PRAGMA table_info(app_users)").fetchall()}
    con.close()
    assert "org_id" in cols
    assert "org_role" in cols


def test_default_org_provisioned():
    oid = tenancy.get_or_create_default_org()
    assert oid, "default org id should be non-empty"
    org = tenancy.get_org(oid)
    assert org is not None
    assert org["status"] == "active"


def test_register_user_attaches_to_org():
    u = auth_service.register_user("tenancy_test@example.com", "Sup3rSecret!", "Tenancy Tester")
    assert u.get("org_id"), "registered user should have an org_id"
    assert u.get("org_role") in ("analyst", "org_admin")


def test_scope_for_org_user():
    u = auth_service.register_user("scope_test@example.com", "Sup3rSecret!", "Scope Tester")
    s = tenancy.scope(u)
    assert s["enabled"] is True
    assert s["org_id"] == u["org_id"]
    assert s["is_global_admin"] is False


def test_scope_for_global_admin_bypasses():
    # The first registered user becomes global admin (bootstrap rule).
    admin = auth_service.get_user_by_email("tenancy_test@example.com")
    # Force admin role for the test.
    import sqlite3
    con = sqlite3.connect(tenancy.DB_PATH)
    con.execute("UPDATE app_users SET role='admin' WHERE email='tenancy_test@example.com'")
    con.commit()
    con.close()
    admin = auth_service.get_user_by_email("tenancy_test@example.com")
    s = tenancy.scope(admin)
    assert s["is_global_admin"] is True
    assert s["enabled"] is False  # global admin sees across orgs


def test_scoped_param_fragment():
    u = auth_service.register_user("param_test@example.com", "Sup3rSecret!", "Param Tester")
    s = tenancy.scope(u)
    wc, wp = tenancy.scoped_param(s)
    assert wc == " AND org_id=?"
    assert wp == (u["org_id"],)
    # Disabled scope → empty fragment.
    s_off = {"enabled": False}
    wc2, wp2 = tenancy.scoped_param(s_off)
    assert wc2 == "" and wp2 == ()


def test_org_isolation():
    """Two users in different orgs have different org_ids."""
    import sqlite3
    import uuid
    # Create a second org.
    org2 = tenancy.create_org("Acme Investigations", "acme")
    u2 = auth_service.register_user("acme@example.com", "Sup3rSecret!", "Acme Analyst")
    tenancy.assign_user_to_org(u2["id"], org2["id"], "analyst")
    u2 = auth_service.get_user_by_id(u2["id"])

    u1 = auth_service.get_user_by_email("param_test@example.com")
    assert u1["org_id"] != u2["org_id"], "users in different orgs must have different org_ids"
