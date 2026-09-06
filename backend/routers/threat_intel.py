"""
Threat intelligence endpoints for wallet attribution, pivoting, and laundering networks.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import database as db
from ai_client import AIConfigError, AIProviderError, compact_evidence, deepseek_chat, deepseek_configured
from threat_intel_engine import generate_intelligence

router = APIRouter(tags=["Threat Intelligence"])


class ThreatIntelRequest(BaseModel):
    address: str
    intel: Optional[Dict[str, Any]] = None
    trace_graph: Optional[Dict[str, Any]] = None
    dex_activity: Optional[Dict[str, Any]] = None
    include_ai: bool = False
    analyst_focus: str = ""


AI_THREAT_PROMPT = """You are a threat intelligence analyst supporting lawful cryptocurrency investigations.
Use only the supplied local algorithm output. Do not invent owner identity, off-chain facts, sanctions, or law-enforcement-only data.
Return JSON with:
{
  "threat_brief": "...",
  "attribution_assessment": ["..."],
  "network_assessment": ["..."],
  "highest_value_pivots": ["..."],
  "collection_requirements": ["..."],
  "reporting_caveats": ["..."]
}"""


@router.post("/threat-intel/analyze")
async def threat_intel_analyze(req: ThreatIntelRequest):
    try:
        intel = req.intel
        if not intel:
            from crypto_osint import lookup_crypto_address
            intel = await lookup_crypto_address(req.address.strip())

        labels = db.labels_for_address(
            intel.get("address", req.address.strip()),
            intel.get("chain", ""),
        )
        result = await run_in_threadpool(
            generate_intelligence,
            intel,
            trace_graph=req.trace_graph,
            dex_activity=req.dex_activity,
            labels=labels,
        )

        ai = None
        if req.include_ai:
            if not deepseek_configured():
                raise HTTPException(status_code=400, detail="Selected AI provider is not configured")
            prompt = f"""{AI_THREAT_PROMPT}

Analyst focus:
{req.analyst_focus or "No extra focus provided."}

Local threat intelligence output:
{compact_evidence(result, max_chars=18000)}
"""
            ai_res = await deepseek_chat(
                [
                    {"role": "system", "content": "You produce evidence-grounded threat intelligence. Avoid unsupported identity claims."},
                    {"role": "user", "content": prompt},
                ],
                response_json=True,
                max_tokens=1800,
                temperature=0.15,
            )
            ai = ai_res["json"] or {"threat_brief": ai_res["content"]}

        return {"threat_intel": result, "ai_assessment": ai}
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"crypto_osint module unavailable: {e}")
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
