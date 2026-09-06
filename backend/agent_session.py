"""
Case-native AI Investigator (Recommendation D3).

Turns the structured AI-Agent into a conversational, case-grounded investigator:
an analyst picks a case, "assigns" it to the agent, and then holds a natural-
language investigation over that case's addresses, evidence, risk signals, and
notes — with evidence citations and one-click structured actions.

Reuses the existing building blocks (no duplication, no changes to them):
  • database.list_cases / get_case          — case + addresses + notes
  • evidence_vault.list_evidence            — stored artifacts
  • case_qa._build_context                  — keyword+recency RAG retrieval
  • ai_agent.QUERY_CONFIGS / run_agent_query — structured investigation queries
  • ai_client.ai_chat / ai_configured       — provider-neutral multi-turn chat
"""
from __future__ import annotations

import re
from typing import Any, Optional

import database as db


AGENT_PERSONA = (
    "You are the CrypTX AI Investigator — an expert cryptocurrency-forensics analyst "
    "assigned to an active investigation case. You hold a natural-language conversation "
    "with a human investigator, grounded strictly in the supplied case context.\n\n"
    "Rules:\n"
    "1. Ground every claim in the provided case context (addresses, evidence, risk, notes). "
    "If something is not in the context, say so — never invent facts, addresses, txs, or attributions.\n"
    "2. Cite evidence inline as [evidence:ID] whenever you reference a specific stored finding.\n"
    "3. Separate confirmed on-chain facts from investigative hypotheses; label confidence "
    "Low / Medium / High / Very High.\n"
    "4. Use 'common-control lead' language for clustering — never assert real-world ownership.\n"
    "5. Be concise and operational: an investigator wants next steps, not essays. "
    "Prefer short paragraphs and tight bullet lists.\n"
    "6. Flag evidence gaps that would strengthen the case.\n"
)


# ── quick stats for the case picker ──────────────────────────────────────────
def _evidence_count(case_id: str) -> int:
    try:
        import evidence_vault
        evidence_vault.init_evidence_tables()
        return len(evidence_vault.list_evidence(case_id, limit=1000))
    except Exception:
        return 0


def list_case_briefs() -> list[dict[str, Any]]:
    """Cases with quick stats for the assignment picker."""
    briefs: list[dict[str, Any]] = []
    for c in db.list_cases():
        case = db.get_case(c["id"]) or c
        addrs = case.get("addresses") or []
        risks = [a.get("risk_score", -1) for a in addrs if isinstance(a.get("risk_score"), (int, float))]
        briefs.append({
            "id": case["id"],
            "name": case.get("name", ""),
            "status": case.get("status", ""),
            "description": case.get("description", ""),
            "created_at": case.get("created_at", ""),
            "updated_at": case.get("updated_at", ""),
            "address_count": len(addrs),
            "note_count": len(case.get("notes") or []),
            "evidence_count": _evidence_count(case["id"]),
            "max_risk": max(risks) if risks else 0,
        })
    return briefs


# ── assignment briefing ──────────────────────────────────────────────────────
def _suggest_prompts(case: dict, addrs: list[dict], evidence_n: int) -> list[str]:
    """Context-aware starter prompts for the assigned case."""
    prompts: list[str] = []
    high = [a for a in addrs if isinstance(a.get("risk_score"), (int, float)) and a["risk_score"] >= 70]
    if high:
        a = high[0]
        prompts.append(f"Why is {a['address'][:12]}… high risk, and where do its funds go?")
    if len(addrs) >= 2:
        prompts.append("Which of the case addresses are likely under common control, and on what basis?")
    prompts.append("Trace the most likely cash-out route and name the exchanges to subpoena.")
    if evidence_n:
        prompts.append("Summarize the strongest evidence in this case for a prosecutor.")
    prompts.append("What are the biggest evidence gaps, and how do I close them?")
    prompts.append("Give me the next 5 highest-value investigation steps.")
    return prompts[:6]


def case_briefing(case_id: str) -> dict[str, Any]:
    """Full briefing shown when a case is assigned to the agent."""
    case = db.get_case(case_id)
    if not case:
        raise ValueError("case not found")
    addrs = case.get("addresses") or []
    notes = case.get("notes") or []
    evidence_n = _evidence_count(case_id)

    address_rows = [{
        "address": a.get("address", ""),
        "chain": a.get("chain", ""),
        "risk_score": a.get("risk_score", None),
        "risk_level": a.get("risk_level", ""),
        "label": a.get("label", ""),
    } for a in addrs[:100]]

    import ai_client
    return {
        "case": {
            "id": case["id"], "name": case.get("name", ""),
            "status": case.get("status", ""), "description": case.get("description", ""),
        },
        "stats": {
            "addresses": len(addrs),
            "evidence": evidence_n,
            "notes": len(notes),
            "max_risk": max([a.get("risk_score", 0) or 0 for a in addrs], default=0),
        },
        "addresses": address_rows,
        "suggested_prompts": _suggest_prompts(case, addrs, evidence_n),
        "actions": list_actions(),
        "ai_configured": ai_client.ai_configured(),
        "welcome": (
            f"Case **{case.get('name','')}** assigned. I have {len(addrs)} address(es), "
            f"{evidence_n} evidence record(s), and {len(notes)} note(s) in context. "
            "Ask me anything, or run a structured action."
        ),
    }


def list_actions() -> list[dict[str, Any]]:
    """One-click structured actions (subset of ai_agent query types that make
    sense at the case level)."""
    import ai_agent
    case_level = {
        "find_cashout", "generate_subpoena_targets", "find_missing_evidence",
        "summarize_for_prosecutor", "list_weak_assumptions", "create_pivots",
    }
    return [q for q in ai_agent.list_query_types() if q["id"] in case_level]


# ── evidence auto-load for structured actions ────────────────────────────────
def _case_evidence_bundle(case: dict) -> dict[str, Any]:
    """Assemble the evidence dict that ai_agent.run_agent_query expects, from the
    case's own stored data."""
    addrs = case.get("addresses") or []
    bundle: dict[str, Any] = {
        "case": {
            "id": case["id"], "name": case.get("name", ""),
            "status": case.get("status", ""), "description": case.get("description", ""),
            "addresses": [{
                "address": a.get("address"), "chain": a.get("chain"),
                "risk_score": a.get("risk_score"), "risk_level": a.get("risk_level"),
                "label": a.get("label"),
            } for a in addrs],
            "notes": [n.get("note", "") for n in (case.get("notes") or [])][:20],
        },
    }
    if addrs:
        bundle["address"] = addrs[0].get("address", "")
        bundle["chain"] = addrs[0].get("chain", "")
    try:
        import evidence_vault
        evidence_vault.init_evidence_tables()
        ev = evidence_vault.list_evidence(case["id"], limit=60)
        bundle["case"]["evidence"] = [{
            "id": e.get("id"), "type": e.get("evidence_type"), "title": e.get("title"),
            "subject": e.get("subject"), "chain": e.get("chain"),
            "quality": e.get("quality_score"),
        } for e in ev]
    except Exception:
        pass
    return bundle


async def run_case_action(case_id: str, query_type: str, free_text: str = "") -> dict[str, Any]:
    """Run a structured ai_agent query with the case's evidence auto-loaded."""
    case = db.get_case(case_id)
    if not case:
        raise ValueError("case not found")
    import ai_agent
    evidence = _case_evidence_bundle(case)
    result = await ai_agent.run_agent_query(
        query_type=query_type, evidence=evidence, free_text=free_text,
    )
    return {"case_id": case_id, "query_type": query_type, **result}


# ── multi-turn grounded chat ─────────────────────────────────────────────────
def _extract_citations(text: str, valid_ids: set[str]) -> list[dict[str, Any]]:
    out = []
    for m in re.finditer(r"\[evidence:([A-Za-z0-9\-]+)\]", text or ""):
        eid = m.group(1)
        out.append({"evidence_id": eid, "valid": eid in valid_ids})
    return out


def _followups(answer: str) -> list[str]:
    """Cheap, deterministic follow-up suggestions to keep the investigation moving."""
    base = [
        "Trace where those funds went next.",
        "Which exchanges should I subpoena first?",
        "What evidence would strengthen this?",
        "Draft this as a prosecutor summary.",
    ]
    return base


async def chat(case_id: str, messages: list[dict[str, str]],
               max_tokens: int = 1400, temperature: float = 0.2) -> dict[str, Any]:
    """Multi-turn, case-grounded conversation.

    `messages`: prior turns [{role: 'user'|'assistant', content}], last = new user turn.
    """
    case = db.get_case(case_id)
    if not case:
        raise ValueError("case not found")

    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = m.get("content", "")
            break

    import case_qa, ai_client
    context = case_qa._build_context(case, last_user)

    if not ai_client.ai_configured():
        return {
            "answer": (
                "AI is not configured, so I can't converse yet. I retrieved "
                f"{context['summary']['evidence_retrieved']} evidence record(s), "
                f"{context['summary']['addresses']} address(es), and "
                f"{context['summary']['notes']} note(s) for this question. "
                "Add an LLM provider key in Settings to enable the investigator."
            ),
            "citations": [], "context_used": context["summary"], "ai_used": False,
            "followups": [],
        }

    system = (
        AGENT_PERSONA +
        f"\n\nCASE: {case.get('name','')}  (status: {case.get('status','')})\n"
        f"CASE CONTEXT (retrieved for the current question):\n{context['context_text']}\n"
    )
    convo: list[dict[str, str]] = [{"role": "system", "content": system}]
    # keep the last ~10 turns to bound the prompt
    for m in messages[-10:]:
        role = m.get("role")
        if role in ("user", "assistant") and m.get("content"):
            convo.append({"role": role, "content": m["content"]})

    try:
        result = await ai_client.ai_chat(
            messages=convo, response_json=False,
            max_tokens=max_tokens, temperature=temperature,
        )
    except ai_client.AIConfigError as exc:
        return {"answer": f"AI not configured: {exc}", "citations": [], "ai_used": False, "followups": []}
    except ai_client.AIProviderError as exc:
        return {"answer": f"AI provider error: {exc}", "citations": [], "ai_used": False, "followups": []}

    answer = result.get("content") or result.get("text") or str(result)
    citations = _extract_citations(answer, context["evidence_ids"])
    return {
        "answer": answer,
        "citations": citations,
        "context_used": context["summary"],
        "ai_used": True,
        "followups": _followups(answer),
        "disclaimer": "AI-generated, grounded in case evidence. Heuristic findings are leads, not proof.",
    }
