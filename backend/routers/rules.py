"""
No-code rules router — /api/rules

Composite alert rules (JSON conditions + AND/OR), rule templates, and dry-run.
This is the productization layer that turns the monitor into a Caudena-CRM-shape
recurring-revenue product.

Endpoints:
  GET    /api/rules/templates              rule template library
  POST   /api/rules/from-template          one-click create from a template
  GET    /api/rules/composite              list composite rules
  POST   /api/rules/composite              create a composite rule
  PATCH  /api/rules/composite/{id}         update
  DELETE /api/rules/composite/{id}         delete
  POST   /api/rules/dry-run                test a candidate rule against tx history
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Optional

import rule_engine
import tenancy

router = APIRouter(prefix="/rules", tags=["Alert Rules"])


def _user(request: Request) -> dict:
    return getattr(request.state, "user", None) or {}


# ── Request models ───────────────────────────────────────────────────────────

class ConditionModel(BaseModel):
    field: str
    op: str
    value: Any


class CreateCompositeRuleRequest(BaseModel):
    name: str
    conditions: list[ConditionModel]
    operator: str = "AND"
    address: str = ""
    chain: str = ""
    enabled: bool = True
    template_id: str = ""


class UpdateCompositeRuleRequest(BaseModel):
    name: Optional[str] = None
    conditions: Optional[list[ConditionModel]] = None
    operator: Optional[str] = None
    enabled: Optional[bool] = None


class DryRunRequest(BaseModel):
    conditions: list[ConditionModel]
    operator: str = "AND"
    transactions: list[dict[str, Any]] = []


class FromTemplateRequest(BaseModel):
    template_id: str
    name: Optional[str] = None
    address: str = ""
    chain: str = ""


# ── Templates ───────────────────────────────────────────────────────────────

@router.get("/templates")
def list_templates():
    """List the rule template library (one-click create)."""
    return {"templates": rule_engine.list_templates()}


@router.post("/from-template", status_code=201)
def create_from_template(req: FromTemplateRequest):
    """Create a composite rule from a template."""
    tmpl = rule_engine.get_template(req.template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"template '{req.template_id}' not found")
    try:
        conditions = [c if isinstance(c, dict) else c.model_dump() for c in tmpl["conditions"]]
        return rule_engine.create_composite_rule(
            name=req.name or tmpl["name"],
            conditions=conditions,
            operator=tmpl["operator"],
            address=req.address,
            chain=req.chain,
            template_id=tmpl["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Composite rule CRUD ─────────────────────────────────────────────────────

@router.get("/composite")
def list_composite(address: str = ""):
    return {"rules": rule_engine.list_composite_rules(address=address)}


@router.post("/composite", status_code=201)
def create_composite(req: CreateCompositeRuleRequest):
    try:
        conditions = [c.model_dump() for c in req.conditions]
        return rule_engine.create_composite_rule(
            name=req.name,
            conditions=conditions,
            operator=req.operator,
            address=req.address,
            chain=req.chain,
            enabled=req.enabled,
            template_id=req.template_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/composite/{rule_id}")
def update_composite(rule_id: str, req: UpdateCompositeRuleRequest):
    existing = rule_engine.get_composite_rule(rule_id)
    if not existing:
        raise HTTPException(status_code=404, detail="rule not found")
    # Build the updated conditions/operator.
    conditions = [c.model_dump() for c in req.conditions] if req.conditions else existing["conditions"]
    operator = req.operator or existing.get("operator") or "AND"
    err = rule_engine.validate_rule(conditions, operator)
    if err:
        raise HTTPException(status_code=400, detail=err)
    import sqlite3
    import json
    from datetime import datetime, timezone
    with sqlite3.connect(rule_engine.DB_PATH) as con:
        con.row_factory = sqlite3.Row
        if req.name is not None:
            con.execute("UPDATE alert_rules SET name=? WHERE id=?", (req.name, rule_id))
        if req.conditions is not None:
            con.execute("UPDATE alert_rules SET conditions_json=? WHERE id=?", (json.dumps(conditions), rule_id))
        if req.operator is not None:
            con.execute("UPDATE alert_rules SET operator=? WHERE id=?", (operator, rule_id))
        if req.enabled is not None:
            con.execute("UPDATE alert_rules SET enabled=? WHERE id=?", (1 if req.enabled else 0, rule_id))
        con.execute("UPDATE alert_rules SET updated_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), rule_id))
        con.commit()
    return rule_engine.get_composite_rule(rule_id)


@router.delete("/composite/{rule_id}")
def delete_composite(rule_id: str):
    import sqlite3
    with sqlite3.connect(rule_engine.DB_PATH) as con:
        cur = con.execute("DELETE FROM alert_rules WHERE id=?", (str(rule_id),))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="rule not found")
    return {"deleted": rule_id}


# ── Dry-run ─────────────────────────────────────────────────────────────────

@router.post("/dry-run")
def dry_run(req: DryRunRequest):
    """Test a candidate rule against a list of transactions. Returns match count + samples."""
    try:
        conditions = [c.model_dump() for c in req.conditions]
        return rule_engine.dry_run_rule(conditions, req.operator, req.transactions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
