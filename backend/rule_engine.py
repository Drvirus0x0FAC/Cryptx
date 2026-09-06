"""
No-code alert rule engine for CrypTX — composite conditions, dry-run, templates.

Extends the existing `alert_rules` table (5 fixed columns, fixed AND) with a
JSON `conditions` model supporting:
  * USD value thresholds (not just native units)
  * velocity rules ("more than N tx in M hours")
  * first-interaction-with-category ("first mixer interaction")
  * new-infinite-approval (from contract_forensics)
  * time-of-day windows
  * AND/OR composition

Also adds:
  * Dry-run: test a candidate rule against a wallet's stored tx history.
  * Rule templates: a library of common investigation rules (one-click create).

This is the productization layer that turns the monitor into a Caudena-CRM-shape
recurring-revenue product. The existing monitor.py endpoints stay fully
functional; this adds composite-rule power on top.
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


# ── Composite condition model ───────────────────────────────────────────────
# A condition is a dict: {"field": str, "op": str, "value": Any}
# Supported fields: usd_value, native_value, direction, counterparty_category,
#                   token, chain, time_of_day_hour, tx_velocity_count,
#                   tx_velocity_window_hours, is_first_mixer_interaction,
#                   is_new_infinite_approval
# Supported ops: eq, gt, gte, lt, lte, in, contains, between
# A rule's `conditions` is a list joined by `operator` (AND | OR).

CONDITION_FIELDS = {
    "usd_value", "native_value", "direction", "counterparty_category",
    "token", "chain", "time_of_day_hour", "tx_velocity_count",
    "tx_velocity_window_hours", "is_first_mixer_interaction",
    "is_new_infinite_approval", "kind",
}

CONDITION_OPS = {"eq", "gt", "gte", "lt", "lte", "in", "contains", "between"}


def validate_condition(cond: dict) -> Optional[str]:
    """Return an error message if the condition is invalid, else None."""
    if not isinstance(cond, dict):
        return "condition must be an object"
    field = cond.get("field")
    op = cond.get("op")
    if field not in CONDITION_FIELDS:
        return f"unknown field '{field}'; valid: {sorted(CONDITION_FIELDS)}"
    if op not in CONDITION_OPS:
        return f"unknown op '{op}'; valid: {sorted(CONDITION_OPS)}"
    if "value" not in cond:
        return "condition missing 'value'"
    return None


def validate_rule(conditions: list[dict], operator: str) -> Optional[str]:
    """Validate a composite rule. Returns error message or None."""
    if operator not in ("AND", "OR"):
        return "operator must be AND or OR"
    if not isinstance(conditions, list) or not conditions:
        return "conditions must be a non-empty list"
    for c in conditions:
        err = validate_condition(c)
        if err:
            return err
    return None


def evaluate_condition(cond: dict, tx_context: dict) -> bool:
    """Evaluate a single condition against a transaction context dict.

    `tx_context` should contain the tx's resolved fields:
        usd_value, native_value, direction, counterparty_categories (set),
        token, chain, hour (0-23), tx_velocity (count in window),
        is_first_mixer_interaction (bool), is_new_infinite_approval (bool), kind
    """
    field = cond["field"]
    op = cond["op"]
    value = cond["value"]
    actual = tx_context.get(field)

    if op == "eq":
        return actual == value
    if op == "gt":
        try:
            return float(actual or 0) > float(value)
        except (TypeError, ValueError):
            return False
    if op == "gte":
        try:
            return float(actual or 0) >= float(value)
        except (TypeError, ValueError):
            return False
    if op == "lt":
        try:
            return float(actual or 0) < float(value)
        except (TypeError, ValueError):
            return False
    if op == "lte":
        try:
            return float(actual or 0) <= float(value)
        except (TypeError, ValueError):
            return False
    if op == "in":
        return actual in (value if isinstance(value, (list, set, tuple)) else [value])
    if op == "contains":
        return str(value).lower() in str(actual or "").lower()
    if op == "between":
        try:
            lo, hi = value[0], value[1]
            return lo <= float(actual or 0) <= hi
        except (TypeError, ValueError, IndexError):
            return False
    return False


def evaluate_rule(conditions: list[dict], operator: str, tx_context: dict) -> tuple[bool, list[str]]:
    """Evaluate a composite rule. Returns (matched, reasons)."""
    results = []
    reasons = []
    for cond in conditions:
        matched = evaluate_condition(cond, tx_context)
        results.append(matched)
        reasons.append(f"{cond['field']} {cond['op']} {cond['value']}: {'✓' if matched else '✗'}")
    if operator == "AND":
        return all(results), reasons
    return any(results), reasons


# ── Rule template library ───────────────────────────────────────────────────

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "high-value-cashout",
        "name": "High-value cash-out to exchange",
        "description": "Alert when >$50K flows to an exchange in a single transaction.",
        "conditions": [
            {"field": "usd_value", "op": "gt", "value": 50000},
            {"field": "counterparty_category", "op": "eq", "value": "exchange"},
        ],
        "operator": "AND",
    },
    {
        "id": "mixer-interaction",
        "name": "First mixer interaction",
        "description": "Alert the first time a watched wallet sends to a known mixer.",
        "conditions": [
            {"field": "is_first_mixer_interaction", "op": "eq", "value": True},
        ],
        "operator": "AND",
    },
    {
        "id": "bridge-hop",
        "name": "Bridge crossing",
        "description": "Alert when funds move through a cross-chain bridge.",
        "conditions": [
            {"field": "counterparty_category", "op": "eq", "value": "bridge"},
        ],
        "operator": "AND",
    },
    {
        "id": "sanctioned-touch",
        "name": "Sanctioned entity contact",
        "description": "Alert on any interaction with a sanctioned address.",
        "conditions": [
            {"field": "counterparty_category", "op": "eq", "value": "sanctioned"},
        ],
        "operator": "AND",
    },
    {
        "id": "high-velocity",
        "name": "High-velocity fragmentation",
        "description": "Alert on >10 transactions in 1 hour (micro-fragmentation laundering signal).",
        "conditions": [
            {"field": "tx_velocity_count", "op": "gt", "value": 10},
            {"field": "tx_velocity_window_hours", "op": "eq", "value": 1},
        ],
        "operator": "AND",
    },
    {
        "id": "infinite-approval",
        "name": "New infinite approval",
        "description": "Alert when a wallet grants a new infinite token approval (drainer risk).",
        "conditions": [
            {"field": "is_new_infinite_approval", "op": "eq", "value": True},
        ],
        "operator": "AND",
    },
    {
        "id": "off-hours",
        "name": "Off-hours activity",
        "description": "Alert on transactions between 1am-5am UTC (common in automated laundering).",
        "conditions": [
            {"field": "time_of_day_hour", "op": "between", "value": [1, 5]},
        ],
        "operator": "AND",
    },
]


def list_templates() -> list[dict[str, Any]]:
    """Return the rule template library."""
    return TEMPLATES


def get_template(template_id: str) -> Optional[dict[str, Any]]:
    for t in TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


# ── Composite rule storage (additive to alert_rules) ────────────────────────

def _ensure_composite_columns() -> None:
    """Add conditions_json + operator columns to alert_rules if missing."""
    with _conn() as con:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(alert_rules)").fetchall()}
        if "conditions_json" not in cols:
            con.execute("ALTER TABLE alert_rules ADD COLUMN conditions_json TEXT DEFAULT ''")
        if "operator" not in cols:
            con.execute("ALTER TABLE alert_rules ADD COLUMN operator TEXT DEFAULT 'AND'")
        if "template_id" not in cols:
            con.execute("ALTER TABLE alert_rules ADD COLUMN template_id TEXT DEFAULT ''")
        con.commit()


def create_composite_rule(
    name: str,
    conditions: list[dict],
    operator: str = "AND",
    *,
    address: str = "",
    chain: str = "",
    enabled: bool = True,
    template_id: str = "",
) -> dict[str, Any]:
    """Create a composite alert rule. Returns the rule record."""
    err = validate_rule(conditions, operator)
    if err:
        raise ValueError(err)
    _ensure_composite_columns()
    rid = str(uuid.uuid4())
    now = _now()
    with _conn() as con:
        con.execute(
            """INSERT INTO alert_rules
               (id, name, address, chain, direction, min_value, counterparty_category,
                enabled, created_at, updated_at, conditions_json, operator, template_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, name, address, chain, "any", 0, "any",
             1 if enabled else 0, now, now, json.dumps(conditions), operator, template_id),
        )
        con.commit()
    return get_composite_rule(rid)  # type: ignore[return-value]


def get_composite_rule(rule_id: str) -> Optional[dict[str, Any]]:
    _ensure_composite_columns()
    with _conn() as con:
        row = con.execute("SELECT * FROM alert_rules WHERE id=?", (str(rule_id),)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 1))
    try:
        d["conditions"] = json.loads(d.get("conditions_json") or "[]")
    except json.JSONDecodeError:
        d["conditions"] = []
    return d


def list_composite_rules(address: str = "") -> list[dict[str, Any]]:
    _ensure_composite_columns()
    with _conn() as con:
        if address:
            rows = con.execute(
                "SELECT * FROM alert_rules WHERE conditions_json != '' AND (address=? OR address='') ORDER BY created_at DESC",
                (address,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM alert_rules WHERE conditions_json != '' ORDER BY created_at DESC"
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d.get("enabled", 1))
        try:
            d["conditions"] = json.loads(d.get("conditions_json") or "[]")
        except json.JSONDecodeError:
            d["conditions"] = []
        out.append(d)
    return out


def dry_run_rule(conditions: list[dict], operator: str, transactions: list[dict]) -> dict[str, Any]:
    """Test a candidate rule against a list of transactions.

    Each transaction should be pre-resolved into a tx_context dict (see
    evaluate_condition). Returns how many would have matched + sample matches.
    """
    err = validate_rule(conditions, operator)
    if err:
        raise ValueError(err)
    matches: list[dict[str, Any]] = []
    for i, tx_ctx in enumerate(transactions):
        matched, reasons = evaluate_rule(conditions, operator, tx_ctx)
        if matched:
            matches.append({"index": i, "reasons": reasons, "tx": tx_ctx})
    return {
        "total_tested": len(transactions),
        "matched": len(matches),
        "match_rate": (len(matches) / len(transactions)) if transactions else 0.0,
        "sample_matches": matches[:10],
    }
