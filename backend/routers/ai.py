"""
AI-powered investigation endpoints using the selected AI provider.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json
import re

from ai_client import (
    AIConfigError,
    AIProviderError,
    compact_evidence,
    deepseek_chat,
    deepseek_configured,
    deepseek_probe,
    deepseek_settings,
)

router = APIRouter(tags=["AI Copilot"])


SYSTEM_PROMPT = """You are CryptoOSINT AI Copilot for lawful cryptocurrency cybercrime investigation.
Use only the evidence provided. Do not invent labels, identities, facts, sanctions, or external intelligence.
Separate confirmed evidence from hypotheses. Give concise, analyst-grade output.
When recommending actions, prefer reproducible blockchain checks, local graph analysis, and evidence preservation.
Do not provide instructions for committing crime, laundering money, evading tracing, or abusing systems."""


class AiInvestigationRequest(BaseModel):
    address: str = ""
    chain: str = ""
    intel: Optional[Dict[str, Any]] = None
    risk: Optional[Dict[str, Any]] = None
    forensic: Optional[Dict[str, Any]] = None
    case: Optional[Dict[str, Any]] = None
    question: str = ""


class AiNotesRequest(BaseModel):
    text: str


AI_REPORT_CONTRACT = """Return one complete JSON object with exactly these top-level keys:
{
  "brief": {
    "executive_summary": "...",
    "risk_level_interpretation": "...",
    "top_concerns": ["..."],
    "confidence_statement": "..."
  },
  "evidence": {
    "confirmed_facts": ["..."],
    "risk_signals": ["..."],
    "graph_observations": ["..."],
    "temporal_observations": ["..."],
    "local_label_observations": ["..."]
  },
  "hypotheses": [
    {
      "title": "...",
      "confidence": 0.0,
      "supporting_evidence": ["..."],
      "contradicting_evidence": ["..."],
      "next_checks": ["..."]
    }
  ],
  "next_steps": {
    "priority_actions": [
      {"priority": "P1", "action": "...", "why": "...", "expected_evidence": "..."}
    ],
    "data_gaps": ["..."],
    "preservation_plan": ["..."]
  },
  "report_narrative": {
    "case_summary": "...",
    "risk_rationale": ["..."],
    "timeline_narrative": "...",
    "limitations": ["..."],
    "recommended_next_steps": ["..."]
  },
  "quality_control": {
    "do_not_claim": ["..."],
    "needs_human_review": ["..."],
    "source_limitations": ["..."]
  }
}

Important:
- next_steps must be JSON, not prose.
- Do not omit sections. Use empty arrays when evidence is unavailable.
- Every claim must be grounded in the supplied evidence."""


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [str(value)]


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _try_parse_json_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _unwrap_report(raw: Any) -> Any:
    raw = _try_parse_json_text(raw)
    data = _as_dict(raw)
    for key in ("summary", "content", "executive_summary"):
        parsed = _try_parse_json_text(data.get(key))
        if isinstance(parsed, dict) and ("brief" in parsed or "evidence" in parsed or "next_steps" in parsed):
            return parsed
    brief = _as_dict(data.get("brief"))
    parsed_brief_summary = _try_parse_json_text(brief.get("executive_summary"))
    if isinstance(parsed_brief_summary, dict) and ("brief" in parsed_brief_summary or "evidence" in parsed_brief_summary):
        return parsed_brief_summary
    return data


def _local_fallbacks(evidence_payload: Dict[str, Any]) -> Dict[str, list]:
    intel = _as_dict(evidence_payload.get("intel"))
    risk = _as_dict(evidence_payload.get("risk"))
    forensic = _as_dict(evidence_payload.get("forensic"))
    facts = []
    if intel.get("address"):
        facts.append(f"Subject address: {intel.get('address')}")
    if intel.get("chain"):
        facts.append(f"Detected chain: {intel.get('chain')}")
    if intel.get("tx_count") is not None:
        facts.append(f"Observed transaction count: {intel.get('tx_count')}")
    if intel.get("balance") is not None:
        facts.append(f"Current balance: {intel.get('balance')} {intel.get('balance_unit', '')}".strip())
    if intel.get("first_seen"):
        facts.append(f"First seen: {intel.get('first_seen')}")
    if intel.get("last_seen"):
        facts.append(f"Last active: {intel.get('last_seen')}")

    risk_signals = []
    for sig in risk.get("signals") or []:
        if isinstance(sig, dict):
            label = sig.get("label") or sig.get("type")
            detail = sig.get("detail", "")
            if label:
                risk_signals.append(f"{label}: {detail}".strip(": "))
    if risk.get("risk_level"):
        risk_signals.insert(0, f"Computed risk level: {risk.get('risk_level')} ({risk.get('score', '-')}/100)")

    graph_observations = []
    metrics = _as_dict(forensic.get("graph_metrics"))
    features = _as_dict(forensic.get("features"))
    role = _as_dict(forensic.get("role"))
    cluster = _as_dict(forensic.get("cluster_analysis"))
    if role.get("role"):
        graph_observations.append(f"Local role classifier: {role.get('role')} ({role.get('confidence', 0)})")
    if metrics:
        graph_observations.append(f"Evidence graph: {metrics.get('nodes', 0)} nodes and {metrics.get('edges', 0)} edges")
    if features.get("flow_through_ratio") is not None:
        graph_observations.append(f"Flow-through ratio: {features.get('flow_through_ratio')}")
    if cluster.get("anomaly_level"):
        graph_observations.append(f"Unsupervised anomaly level: {cluster.get('anomaly_level')} ({cluster.get('anomaly_score', 0)})")
    for motif in forensic.get("motifs") or []:
        if isinstance(motif, dict):
            graph_observations.append(f"Motif {motif.get('pattern')}: {motif.get('evidence', '')}".strip())

    temporal = []
    for item in forensic.get("temporal_correlations") or []:
        if isinstance(item, dict):
            temporal.append(f"{item.get('type')} at {item.get('time_bucket')} involving {item.get('address_count')} addresses")

    labels = []
    for label in forensic.get("local_labels") or []:
        if isinstance(label, dict):
            labels.append(f"{label.get('label')} ({label.get('category', 'local label')}), risk weight {label.get('risk_weight', 0)}")

    return {
        "confirmed_facts": facts,
        "risk_signals": risk_signals,
        "graph_observations": graph_observations,
        "temporal_observations": temporal,
        "local_label_observations": labels,
    }


def _normalize_ai_report(raw: Any, focus: str = "", evidence_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = _unwrap_report(raw)
    data = _as_dict(raw)
    fallback = _local_fallbacks(evidence_payload or {})

    brief = _as_dict(data.get("brief"))
    evidence = _as_dict(data.get("evidence"))
    next_steps = _as_dict(data.get("next_steps"))
    narrative = _as_dict(data.get("report_narrative") or data.get("narrative"))
    quality = _as_dict(data.get("quality_control") or data.get("quality"))

    # Accept common provider deviations and fold them into the canonical schema.
    summary = data.get("summary") or data.get("executive_summary") or brief.get("executive_summary") or ""
    hypotheses = data.get("hypotheses") or data.get("ai_hypotheses") or []
    if hypotheses and all(isinstance(h, str) for h in hypotheses):
        hypotheses = [{"title": h, "confidence": 0.5, "supporting_evidence": [], "contradicting_evidence": [], "next_checks": []} for h in hypotheses]

    priority_actions = (
        next_steps.get("priority_actions")
        or data.get("priority_actions")
        or data.get("next_actions")
        or data.get("recommended_next_steps")
        or []
    )
    if priority_actions and all(isinstance(a, str) for a in priority_actions):
        priority_actions = [{"priority": "P2", "action": a, "why": "AI recommended action", "expected_evidence": ""} for a in priority_actions]

    canonical = {
        "brief": {
            "executive_summary": summary,
            "risk_level_interpretation": brief.get("risk_level_interpretation") or data.get("risk_interpretation") or "",
            "top_concerns": _as_list(brief.get("top_concerns") or data.get("top_concerns") or data.get("key_findings")),
            "confidence_statement": brief.get("confidence_statement") or "",
        },
        "evidence": {
            "confirmed_facts": _as_list(evidence.get("confirmed_facts") or data.get("key_evidence") or fallback["confirmed_facts"]),
            "risk_signals": _as_list(evidence.get("risk_signals") or data.get("risk_rationale") or fallback["risk_signals"]),
            "graph_observations": _as_list(evidence.get("graph_observations") or fallback["graph_observations"]),
            "temporal_observations": _as_list(evidence.get("temporal_observations") or fallback["temporal_observations"]),
            "local_label_observations": _as_list(evidence.get("local_label_observations") or fallback["local_label_observations"]),
        },
        "hypotheses": hypotheses if isinstance(hypotheses, list) else [],
        "next_steps": {
            "priority_actions": priority_actions if isinstance(priority_actions, list) else [],
            "data_gaps": _as_list(next_steps.get("data_gaps")),
            "preservation_plan": _as_list(next_steps.get("preservation_plan")),
        },
        "report_narrative": {
            "case_summary": narrative.get("case_summary") or summary,
            "risk_rationale": _as_list(narrative.get("risk_rationale") or data.get("risk_rationale")),
            "timeline_narrative": narrative.get("timeline_narrative") or data.get("timeline_narrative") or "",
            "limitations": _as_list(narrative.get("limitations") or data.get("limitations")),
            "recommended_next_steps": _as_list(narrative.get("recommended_next_steps") or data.get("recommended_next_steps")),
        },
        "quality_control": {
            "do_not_claim": _as_list(quality.get("do_not_claim")),
            "needs_human_review": _as_list(quality.get("needs_human_review")),
            "source_limitations": _as_list(quality.get("source_limitations") or data.get("limitations")),
        },
        "analyst_focus": focus,
        "raw_response": data,
    }
    if not canonical["brief"]["executive_summary"]:
        facts = canonical["evidence"]["confirmed_facts"][:3]
        canonical["brief"]["executive_summary"] = " ".join(facts) if facts else "No executive summary was returned by the AI."
    if not canonical["brief"]["top_concerns"]:
        canonical["brief"]["top_concerns"] = canonical["evidence"]["risk_signals"][:5]
    return canonical


@router.get("/ai/status")
def ai_status():
    return deepseek_settings()


@router.post("/ai/test")
async def ai_test():
    try:
        return await deepseek_probe()
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/investigate")
async def ai_investigate(req: AiInvestigationRequest):
    evidence = {
        "address": req.address,
        "chain": req.chain,
        "intel": req.intel,
        "risk": req.risk,
        "forensic": req.forensic,
        "case": req.case,
        "question": req.question,
    }
    user_prompt = f"""Produce a full cryptocurrency investigation report in one structured JSON response.
The frontend will filter this single report locally into Brief, Evidence, Hypotheses, Next Steps, Narrative, and QC views.
Do not tailor the response to only one tab.

Analyst focus / instruction:
{req.question.strip() or "No extra analyst focus was provided."}

You must explicitly address the analyst focus in:
- brief.executive_summary
- hypotheses.next_checks
- next_steps.priority_actions
- report_narrative.recommended_next_steps

{AI_REPORT_CONTRACT}

Evidence:
{compact_evidence(evidence)}
"""
    try:
        result = await deepseek_chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_json=True,
            max_tokens=2200,
            temperature=0.15,
        )
        return {
            "provider": result.get("provider", "ai"),
            "model": result["model"],
            "analysis": _normalize_ai_report(result["json"] or {"summary": result["content"]}, req.question, evidence),
            "usage": result.get("usage", {}),
        }
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai/extract-notes")
async def ai_extract_notes(req: AiNotesRequest):
    prompt = f"""Extract investigation entities and action items from these analyst notes.
Return JSON with keys:
{{
  "addresses": [{{"value": "...", "chain_guess": "...", "context": "..."}}],
  "tx_hashes": [{{"value": "...", "chain_guess": "...", "context": "..."}}],
  "entities": [{{"name": "...", "type": "...", "context": "..."}}],
  "claims": [{{"claim": "...", "needs_verification": true}}],
  "action_items": ["..."]
}}

Notes:
{req.text[:12000]}"""
    try:
        result = await deepseek_chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_json=True,
            max_tokens=1800,
            temperature=0,
        )
        return {"provider": result.get("provider", "ai"), "model": result["model"], "extraction": result["json"] or {}}
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AiChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    evidence: Optional[Dict[str, Any]] = None


@router.post("/ai/chat")
async def ai_chat(req: AiChatRequest):
    evidence_msg = ""
    if req.evidence:
        evidence_msg = f"\nAvailable evidence:\n{compact_evidence(req.evidence, max_chars=12000)}"
    messages = [{"role": "system", "content": SYSTEM_PROMPT + evidence_msg}] + req.messages[-12:]
    try:
        result = await deepseek_chat(messages, response_json=False, max_tokens=1800, temperature=0.25)
        return {
            "provider": result.get("provider", "ai"),
            "model": result["model"],
            "content": result["content"],
            "usage": result.get("usage", {}),
        }
    except AIConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
