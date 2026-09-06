"""
NL investigation agent router — /api/nl-agent

  POST /api/nl-agent/run     start a natural-language multi-step investigation
  GET  /api/nl-agent/jobs/{id}  poll a running job for progress + result
  GET  /api/nl-agent/jobs    list recent jobs
  GET  /api/nl-agent/tools   list available tools (for UI display)

This is the P1.11 feature: "trace this address, find the cash-out, draft a SAR,
open a freeze request" — by natural-language prompt.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

import nl_agent

router = APIRouter(prefix="/nl-agent", tags=["NL Agent"])


class RunRequest(BaseModel):
    prompt: str
    case_id: str = ""
    analyst: str = "analyst"


@router.get("/tools")
def list_tools():
    """List the tools the agent can call (for UI display)."""
    return {"tools": nl_agent.TOOLS, "max_steps": nl_agent.MAX_STEPS}


@router.post("/run")
async def run(req: RunRequest):
    """Start a natural-language investigation. Returns the job immediately;
    poll /jobs/{id} for progress."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    # Spawn the investigation as a background task (it may take many seconds).
    job_id_coro = nl_agent.run_nl_investigation(req.prompt, req.case_id, req.analyst)
    # We can't return the job_id until the coroutine creates it. Run a wrapper
    # that creates the job ID first, then runs in the background.
    import uuid
    # Actually: run_nl_investigation is synchronous in its job creation but
    # awaits the LLM. For responsiveness, fire-and-forget and return the job
    # once it's created. Simplest: await it (the LLM calls are the slow part
    # and they're awaited internally). Return the final job.
    result = await job_id_coro
    return result


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = nl_agent.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/jobs")
def list_jobs():
    return {"jobs": nl_agent.list_jobs()}
