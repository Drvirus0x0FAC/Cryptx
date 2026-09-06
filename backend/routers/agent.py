"""
Case-native AI Investigator router (Recommendation D3).

  GET  /api/agent/status                     provider availability
  GET  /api/agent/cases                      cases + quick stats (assignment picker)
  GET  /api/agent/case/{case_id}/briefing    full briefing when a case is assigned
  POST /api/agent/case/{case_id}/chat        multi-turn grounded conversation
  POST /api/agent/case/{case_id}/action      run a structured action over case evidence

Additive; the legacy /api/ai-agent/* endpoints are untouched.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import agent_session
import tenancy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["AI Investigator"])


def _guard(request: Request, case_id: str) -> None:
    try:
        tenancy.guard_case(case_id, getattr(request.state, "user", None) or {})
    except ValueError:
        raise HTTPException(status_code=404, detail="Case not found")


@router.get("/status")
def status() -> dict[str, Any]:
    import ai_client
    return {
        "configured": ai_client.ai_configured(),
        "provider": ai_client.ai_settings() if hasattr(ai_client, "ai_settings") else {},
    }


@router.get("/cases")
def cases() -> dict[str, Any]:
    return {"cases": agent_session.list_case_briefs()}


@router.get("/case/{case_id}/briefing")
def briefing(case_id: str, request: Request) -> dict[str, Any]:
    _guard(request, case_id)
    try:
        return agent_session.case_briefing(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = []
    max_tokens: int = 1400
    temperature: float = 0.2


@router.post("/case/{case_id}/chat")
async def chat(case_id: str, req: ChatRequest, request: Request) -> dict[str, Any]:
    _guard(request, case_id)
    try:
        return await agent_session.chat(
            case_id,
            [{"role": m.role, "content": m.content} for m in req.messages],
            max_tokens=req.max_tokens, temperature=req.temperature,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("agent chat error")
        raise HTTPException(status_code=500, detail=str(e))


class ActionRequest(BaseModel):
    query_type: str
    free_text: str = ""


@router.post("/case/{case_id}/action")
async def action(case_id: str, req: ActionRequest, request: Request) -> dict[str, Any]:
    _guard(request, case_id)
    try:
        return await agent_session.run_case_action(case_id, req.query_type, req.free_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("agent action error")
        raise HTTPException(status_code=500, detail=str(e))
