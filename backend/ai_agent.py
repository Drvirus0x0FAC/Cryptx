"""
AI Investigation Agent — structured investigation queries.
Wraps the selected AI provider with investigation-specific prompts and response schemas.

Supported query types:
  find_cashout              → trace cashout routes, identify exchanges/services
  explain_cluster           → explain a wallet cluster in plain English
  generate_subpoena_targets → structured list of legal subpoena targets
  find_missing_evidence     → identify data gaps and how to fill them
  summarize_for_prosecutor  → prosecution-ready case narrative
  list_weak_assumptions     → surface uncertain/unsupported claims
  create_pivots             → next 10 investigation pivots with rationale
  compare_cases             → compare two investigations side-by-side
  open_query                → free-form question over all evidence
"""
from __future__ import annotations
import json
import re
from typing import Any, Optional

from ai_client import (
    AIConfigError,
    AIProviderError,
    compact_evidence,
    deepseek_chat,
)

AGENT_SYSTEM_PROMPT = """You are CryptoOSINT AI Investigation Agent — an expert cryptocurrency forensics analyst
assisting with lawful criminal investigation. Your outputs may form part of a legal case file.

Rules:
- Use ONLY supplied evidence. Never invent facts, addresses, transactions, or attributions.
- Separate confirmed blockchain facts from investigative hypotheses.
- Use "common-control lead" language (not "owner is X") for address clustering.
- Label confidence as Low / Medium / High / Very High — never fabricate certainty.
- Every subpoena target, pivot, or claim must cite specific supporting evidence.
- Flag if evidence is insufficient — do not fill gaps with speculation.
- Return valid JSON exactly matching the requested schema — no prose outside JSON.
"""

# ── Per-query prompts and schemas ─────────────────────────────────────────────

QUERY_CONFIGS: dict[str, dict] = {
    "find_cashout": {
        "label":       "Find Cashout Route",
        "description": "Trace every path to an exchange, mixer, bridge, or off-ramp service",
        "icon":        "trending-up",
        "schema": """{
  "cashout_routes": [
    {
      "route_id": "A",
      "path_description": "...",
      "destination_type": "exchange|mixer|bridge|offramp|unknown",
      "destination_label": "...",
      "estimated_value": "...",
      "token": "...",
      "hops": ["address1", "address2", "..."],
      "supporting_txs": ["0x..."],
      "confidence": "High|Medium|Low",
      "urgency": "time-sensitive|standard",
      "rationale": "..."
    }
  ],
  "primary_route": "A",
  "total_estimated_exposure": "...",
  "exchange_targets": ["exchange name 1", "..."],
  "recommended_action": "...",
  "evidence_gaps": ["..."]
}""",
        "prompt_addendum": "Identify every route the subject wallet uses or could use to convert or obscure funds. Prioritize exchange deposits and stablecoin off-ramps.",
    },

    "explain_cluster": {
        "label":       "Explain Cluster",
        "description": "Plain-English explanation of a wallet cluster and its significance",
        "icon":        "users",
        "schema": """{
  "cluster_summary": "...",
  "common_control_assessment": "...",
  "cluster_role": "exchange|mixer|victim|suspect|unknown",
  "member_roles": [
    {"address": "...", "inferred_role": "...", "evidence": "..."}
  ],
  "behavioral_pattern": "...",
  "risk_assessment": "High|Medium|Low",
  "laundering_typology": "...",
  "confidence": "High|Medium|Low",
  "disclaimer": "These are investigative leads requiring independent verification",
  "recommended_follow_up": ["..."],
  "legal_notes": "..."
}""",
        "prompt_addendum": "Explain what this cluster represents in plain English. Always use 'common-control lead' language — never assert ownership without verified attribution.",
    },

    "generate_subpoena_targets": {
        "label":       "Subpoena Targets",
        "description": "Generate a ranked list of exchanges and services to subpoena",
        "icon":        "file-text",
        "schema": """{
  "subpoena_targets": [
    {
      "rank": 1,
      "entity_name": "...",
      "entity_type": "exchange|otc|mixer|defi|unknown",
      "jurisdiction_guess": "...",
      "legal_basis": "...",
      "specific_wallets": ["..."],
      "specific_txs": ["0x..."],
      "data_to_request": ["KYC records", "IP logs", "withdrawal records", "..."],
      "estimated_value_at_entity": "...",
      "priority": "Urgent|High|Standard",
      "confidence": "High|Medium|Low",
      "caveats": "..."
    }
  ],
  "total_targets": 0,
  "jurisdiction_summary": "...",
  "preservation_notice_recommended": true,
  "mlat_required": ["..."],
  "disclaimer": "Legal review required before serving subpoenas. Jurisdictional rules vary."
}""",
        "prompt_addendum": "Generate a legally actionable subpoena target list. Every target must be supported by specific transaction evidence. Flag uncertain jurisdictions and MLATs required.",
    },

    "find_missing_evidence": {
        "label":       "Find Missing Evidence",
        "description": "Identify what evidence is absent and how to obtain it",
        "icon":        "search",
        "schema": """{
  "evidence_gaps": [
    {
      "gap_id": "G1",
      "description": "...",
      "impact_if_missing": "Critical|High|Medium|Low",
      "how_to_obtain": "...",
      "blockchain_pivot": "...",
      "estimated_effort": "...",
      "priority": "P1|P2|P3"
    }
  ],
  "strongest_existing_evidence": ["..."],
  "weakest_links": ["..."],
  "chain_of_custody_risks": ["..."],
  "recommended_preservation_steps": ["..."],
  "overall_evidence_quality": "Strong|Adequate|Weak|Insufficient",
  "can_prosecute_now": false,
  "prosecution_blocker": "..."
}""",
        "prompt_addendum": "Audit the supplied evidence for gaps. What is missing that would be needed to prosecute? What can be obtained from blockchain, exchanges, or other sources?",
    },

    "summarize_for_prosecutor": {
        "label":       "Prosecutor Summary",
        "description": "Draft a prosecution-ready case narrative from blockchain evidence",
        "icon":        "shield",
        "schema": """{
  "executive_summary": "...",
  "chronological_narrative": "...",
  "subject_wallet": "...",
  "scheme_description": "...",
  "financial_harm": {
    "estimated_amount": "...",
    "currency": "...",
    "victims": "...",
    "confidence": "High|Medium|Low"
  },
  "key_evidence": [
    {"fact": "...", "source": "blockchain|exchange|label|cluster", "tx_hash": "...", "confidence": "High|Medium|Low"}
  ],
  "defendant_actions": ["..."],
  "legal_theories": ["money laundering", "wire fraud", "..."],
  "charges_to_consider": ["..."],
  "evidence_admissibility_notes": ["..."],
  "limitations": ["..."],
  "disclaimer": "This is an AI-generated summary for investigator review only. Legal review required before submission."
}""",
        "prompt_addendum": "Write a prosecution summary as if briefing a prosecutor. Be factual and precise. Clearly separate what the blockchain proves from investigative inferences. Include all caveats.",
    },

    "list_weak_assumptions": {
        "label":       "Weak Assumptions",
        "description": "Surface the most uncertain claims in the investigation",
        "icon":        "alert-triangle",
        "schema": """{
  "weak_assumptions": [
    {
      "assumption": "...",
      "why_uncertain": "...",
      "current_support": "...",
      "how_to_strengthen": "...",
      "risk_if_wrong": "High|Medium|Low",
      "confidence": "Low|Very Low|Unverified"
    }
  ],
  "untested_hypotheses": ["..."],
  "attribution_risks": ["..."],
  "confirmation_bias_warnings": ["..."],
  "recommended_devil_advocate_checks": ["..."],
  "overall_investigation_confidence": "High|Medium|Low|Insufficient"
}""",
        "prompt_addendum": "Act as devil's advocate. Identify every assumption, inference, or claim in the investigation that lacks strong evidence. What could go wrong if these assumptions are incorrect?",
    },

    "create_pivots": {
        "label":       "Next 10 Pivots",
        "description": "Generate the 10 most valuable next investigation steps",
        "icon":        "zap",
        "schema": """{
  "pivots": [
    {
      "pivot_number": 1,
      "priority": "P1|P2|P3",
      "pivot_type": "address|transaction|exchange|legal|blockchain_query",
      "target": "...",
      "rationale": "...",
      "expected_yield": "...",
      "method": "...",
      "estimated_effort": "minutes|hours|days",
      "confidence_this_helps": "High|Medium|Low",
      "tools": ["blockchain_explorer", "exchange_subpoena", "clustering", "..."]
    }
  ],
  "highest_value_pivot": 1,
  "quick_wins": [1, 2],
  "long_term_pivots": [8, 9, 10],
  "strategy_note": "..."
}""",
        "prompt_addendum": "Generate exactly 10 specific, actionable investigation pivots ordered by priority. Each pivot must name a specific address, transaction, exchange, or query — no vague suggestions.",
    },

    "compare_cases": {
        "label":       "Compare Cases",
        "description": "Compare two investigations to find links or shared patterns",
        "icon":        "git-merge",
        "schema": """{
  "comparison_summary": "...",
  "shared_addresses": ["..."],
  "shared_transactions": ["..."],
  "shared_counterparties": ["..."],
  "behavioral_similarities": ["..."],
  "typology_match": "...",
  "linked": true,
  "link_confidence": "High|Medium|Low",
  "link_evidence": ["..."],
  "differences": ["..."],
  "attribution_overlap": "...",
  "recommended_merge_action": "Merge cases|Keep separate|Investigate further",
  "rationale": "..."
}""",
        "prompt_addendum": "Compare Case A and Case B. Look for shared wallets, counterparties, behavioral patterns, timing, and typology matches. The 'case_b' field in evidence contains the second case.",
    },

    "open_query": {
        "label":       "Open Query",
        "description": "Ask anything about the investigation evidence",
        "icon":        "message-circle",
        "schema": """{
  "answer": "...",
  "evidence_used": ["..."],
  "confidence": "High|Medium|Low",
  "caveats": ["..."],
  "follow_up_questions": ["..."]
}""",
        "prompt_addendum": "",
    },
}


# ── Response normalizers ──────────────────────────────────────────────────────

def _try_parse(content: str) -> Any:
    """Extract JSON from AI response, handling markdown fences."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end   = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_text": content, "_parse_error": "Could not parse JSON response"}


# ── Core agent dispatcher ─────────────────────────────────────────────────────

async def run_agent_query(
    query_type:   str,
    evidence:     dict,
    free_text:    str = "",
    max_tokens:   int = 2800,
    temperature:  float = 0.15,
) -> dict[str, Any]:
    """
    Run a structured investigation query.

    evidence can include any of:
      address, chain, intel, risk, forensic, case, case_b (for compare),
      cluster, cashout, paths, crosschain, timeline, nodes, edges
    """
    config = QUERY_CONFIGS.get(query_type)
    if not config:
        valid = list(QUERY_CONFIGS.keys())
        raise ValueError(f"Unknown query type '{query_type}'. Valid: {valid}")

    schema_block = config["schema"]
    addendum     = config.get("prompt_addendum") or ""
    analyst_q    = free_text.strip() or f"Run {config['label']} on the supplied evidence."

    user_prompt = f"""Investigation query type: {config['label']}
{addendum}

Analyst instruction: {analyst_q}

Return ONLY this JSON schema (no explanation outside JSON):
{schema_block}

Evidence:
{compact_evidence(evidence, max_chars=20000)}
"""

    result = await deepseek_chat(
        [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_json=False,   # parse ourselves to handle fences
        max_tokens=max_tokens,
        temperature=temperature,
    )

    parsed = _try_parse(result["content"])

    return {
        "query_type":   query_type,
        "query_label":  config["label"],
        "result":       parsed,
        "raw_content":  result["content"],
        "model":        result["model"],
        "usage":        result.get("usage", {}),
        "analyst_note": analyst_q,
        "has_error":    "_parse_error" in (parsed if isinstance(parsed, dict) else {}),
    }


def list_query_types() -> list[dict]:
    return [
        {
            "id":          qid,
            "label":       cfg["label"],
            "description": cfg["description"],
            "icon":        cfg["icon"],
        }
        for qid, cfg in QUERY_CONFIGS.items()
    ]
