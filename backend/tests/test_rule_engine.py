"""Smoke tests for the no-code rule engine (P1.10)."""
import os
import sys
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rule_engine
import config


def setup_module(module):
    import importlib
    importlib.reload(config)
    rule_engine.DB_PATH = config.DB_PATH
    # Create the alert_rules table so composite columns can be added.
    import sqlite3
    with sqlite3.connect(config.DB_PATH) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS alert_rules (
            id TEXT PRIMARY KEY, name TEXT, address TEXT DEFAULT '', chain TEXT DEFAULT '',
            direction TEXT DEFAULT 'any', min_value REAL DEFAULT 0,
            counterparty_category TEXT DEFAULT 'any', enabled INTEGER DEFAULT 1,
            created_at TEXT, updated_at TEXT)""")
        con.commit()


def test_validate_condition_rejects_unknown_field():
    err = rule_engine.validate_condition({"field": "bogus", "op": "eq", "value": 1})
    assert err is not None
    assert "bogus" in err


def test_validate_condition_accepts_valid():
    err = rule_engine.validate_condition({"field": "usd_value", "op": "gt", "value": 1000})
    assert err is None


def test_evaluate_usd_value_gt():
    cond = {"field": "usd_value", "op": "gt", "value": 50000}
    assert rule_engine.evaluate_condition(cond, {"usd_value": 60000}) is True
    assert rule_engine.evaluate_condition(cond, {"usd_value": 40000}) is False


def test_evaluate_between():
    cond = {"field": "time_of_day_hour", "op": "between", "value": [1, 5]}
    assert rule_engine.evaluate_condition(cond, {"time_of_day_hour": 3}) is True
    assert rule_engine.evaluate_condition(cond, {"time_of_day_hour": 10}) is False


def test_evaluate_rule_AND():
    conditions = [
        {"field": "usd_value", "op": "gt", "value": 50000},
        {"field": "counterparty_category", "op": "eq", "value": "exchange"},
    ]
    ctx = {"usd_value": 60000, "counterparty_category": "exchange"}
    matched, reasons = rule_engine.evaluate_rule(conditions, "AND", ctx)
    assert matched is True
    assert len(reasons) == 2

    ctx2 = {"usd_value": 60000, "counterparty_category": "mixer"}
    matched2, _ = rule_engine.evaluate_rule(conditions, "AND", ctx2)
    assert matched2 is False


def test_evaluate_rule_OR():
    conditions = [
        {"field": "counterparty_category", "op": "eq", "value": "mixer"},
        {"field": "counterparty_category", "op": "eq", "value": "bridge"},
    ]
    ctx = {"counterparty_category": "bridge"}
    matched, _ = rule_engine.evaluate_rule(conditions, "OR", ctx)
    assert matched is True


def test_create_and_get_composite_rule():
    rec = rule_engine.create_composite_rule(
        name="test rule",
        conditions=[{"field": "usd_value", "op": "gt", "value": 10000}],
        operator="AND",
    )
    assert rec["id"]
    assert rec["conditions"] == [{"field": "usd_value", "op": "gt", "value": 10000}]
    fetched = rule_engine.get_composite_rule(rec["id"])
    assert fetched is not None
    assert fetched["name"] == "test rule"


def test_list_composite_rules():
    rule_engine.create_composite_rule(
        name="list test",
        conditions=[{"field": "chain", "op": "eq", "value": "eth"}],
    )
    rules = rule_engine.list_composite_rules()
    assert len(rules) >= 1


def test_dry_run_counts_matches():
    conditions = [{"field": "usd_value", "op": "gt", "value": 50000}]
    transactions = [
        {"usd_value": 60000, "counterparty_category": "exchange"},
        {"usd_value": 30000, "counterparty_category": "exchange"},
        {"usd_value": 100000, "counterparty_category": "mixer"},
    ]
    result = rule_engine.dry_run_rule(conditions, "AND", transactions)
    assert result["total_tested"] == 3
    assert result["matched"] == 2
    assert 0 < result["match_rate"] < 1


def test_templates_exist():
    templates = rule_engine.list_templates()
    assert len(templates) >= 5
    ids = {t["id"] for t in templates}
    assert "high-value-cashout" in ids
    assert "mixer-interaction" in ids


def test_create_from_template():
    tmpl = rule_engine.get_template("sanctioned-touch")
    assert tmpl is not None
    rec = rule_engine.create_composite_rule(
        name=tmpl["name"],
        conditions=[c if isinstance(c, dict) else c for c in tmpl["conditions"]],
        operator=tmpl["operator"],
        template_id=tmpl["id"],
    )
    assert rec["template_id"] == "sanctioned-touch"
    assert len(rec["conditions"]) == 1


def test_validate_rule_rejects_bad_operator():
    err = rule_engine.validate_rule([{"field": "usd_value", "op": "gt", "value": 1}], "XOR")
    assert err is not None
    assert "operator" in err
