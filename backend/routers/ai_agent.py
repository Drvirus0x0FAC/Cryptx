"""
AI Investigation Agent router.
  GET  /ai-agent/queries        → list available query types
  POST /ai-agent/run            → run any structured query
"""
from __future__ import annotations
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_agent import run_agent_query, list_query_types
from ai_client import AIConfigError, AIProviderError

logger = logging.getLogger(__name__)
router = APIRouter()


class AgentRunRequest(BaseModel):
    query_type:  str
    free_text:   str = ""
    # Evidence context — pass whatever you have, agent handles missing fields
    address:     str = ""
    chain:       str = ""
    intel:       Optional[dict] = None
    risk:        Optional[dict] = None
    forensic:    Optional[dict] = None
    case:        Optional[dict] = None
    case_b:      Optional[dict] = None     # for compare_cases
    cluster:     Optional[dict] = None
    cashout:     Optional[dict] = None
    paths:       Optional[dict] = None
    crosschain:  Optional[dict] = None
    timeline:    Optional[dict] = None
    nodes:       Optional[list] = None
    edges:       Optional[list] = None
    max_tokens:  int = 2800
    temperature: float = 0.15


@router.get("/ai-agent/queries")
def get_query_types():
    return {"queries": list_query_types()}


@router.post("/ai-agent/run")
async def agent_run(req: AgentRunRequest) -> dict[str, Any]:
    evidence = {k: v for k, v in {
        "address":   req.address,
        "chain":     req.chain,
        "intel":     req.intel,
        "risk":      req.risk,
        "forensic":  req.forensic,
        "case":      req.case,
        "case_b":    req.case_b,
        "cluster":   req.cluster,
        "cashout":   req.cashout,
        "paths":     req.paths,
        "crosschain": req.crosschain,
        "timeline":  req.timeline,
        "nodes":     req.nodes,
        "edges":     req.edges,
    }.items() if v is not None and v != "" and v != []}

    try:
        result = await run_agent_query(
            query_type=req.query_type,
            evidence=evidence,
            free_text=req.free_text,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        return {"status": "ok", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("ai agent error")
        raise HTTPException(status_code=500, detail=str(e))
