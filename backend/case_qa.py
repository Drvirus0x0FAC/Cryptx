"""
AI RAG Q&A over case evidence.

Lets an investigator ask natural-language questions about a case and get answers
grounded in the stored evidence + graph, with citations to specific evidence IDs.

Approach (keyword + recency retrieval, no vector DB required):
  1. Retrieve relevant evidence records by keyword match on the question
  2. Retrieve the case's addresses, risk signals, and graph summary
  3. Build a grounded prompt with the retrieved context
  4. The LLM answers with inline [evidence:ID] citations
  5. We post-process to extract and validate the cited evidence IDs

This is where the LLM adds the most value: synthesis over heterogeneous case data.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import database as db

log = logging.getLogger("case_qa")


async def answer_case_question(case_id: str, question: str, user: str = "analyst") -> dict:
    """Answer a natural-language question about a case, grounded in its evidence.

    Returns: {answer, citations, context_used, ai_used}
    """
    import ai_client

    case = db.get_case(case_id)
    if not case:
        raise ValueError("case not found")

    # 1. Retrieve relevant evidence
    context = _build_context(case, question)

    # 2. Check AI availability
    if not ai_client.ai_configured():
        return {
            "answer": _fallback_answer(question, context),
            "citations": [],
            "context_used": context["summary"],
            "ai_used": False,
            "disclaimer": "AI not configured. Showing retrieved evidence context only.",
        }

    # 3. Build the RAG prompt
    system_prompt = (
        "You are a cryptocurrency investigation assistant embedded in the CrypTX platform. "
        "You answer questions about an active investigation case using ONLY the provided case "
        "context (evidence records, addresses, risk signals, graph). "
        "\n\nRules:\n"
        "1. Ground every claim in the provided context. If the answer is not in the context, "
        "say so explicitly — do not speculate.\n"
        "2. Cite evidence by ID in square brackets, e.g. [evidence:abc-123], whenever you "
        "reference a specific finding.\n"
        "3. Distinguish deterministic findings (sanctions matches, contract-registry labels) "
        "from heuristic/AI-derived hypotheses.\n"
        "4. Use 'common-control lead' language for clusters — never assert real-world ownership.\n"
        "5. If asked about identity, state that on-chain attribution is hypothesis-based unless "
        "corroborated by off-chain evidence.\n"
        "6. Flag any gaps in the evidence that would strengthen the conclusion.\n"
    )
    user_prompt = (
        f"CASE: {case['name']}\n"
        f"STATUS: {case.get('status', '')}\n\n"
        f"CASE CONTEXT:\n{context['context_text']}\n\n"
        f"INVESTIGATOR QUESTION: {question}\n\n"
        "Answer grounded in the context above, with evidence citations where applicable."
    )

    try:
        evidence_compact = ai_client.compact_evidence({"context": context["context_text"]}, max_chars=14000)
        result = await ai_client.ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_json=False,
            max_tokens=1500,
            temperature=0.2,
        )
    except ai_client.AIConfigError as exc:
        return {"answer": f"AI not configured: {exc}", "citations": [], "ai_used": False}
    except ai_client.AIProviderError as exc:
        return {"answer": f"AI provider error: {exc}", "citations": [], "ai_used": False}

    answer_text = result.get("content") or result.get("text") or str(result)
    citations = _extract_citations(answer_text, context["evidence_ids"])

    return {
        "answer": answer_text,
        "citations": citations,
        "context_used": context["summary"],
        "ai_used": True,
        "disclaimer": "AI-generated answer grounded in case evidence. Heuristic findings are "
                      "investigative leads, not proof. Verify cited evidence before action.",
    }


def _build_context(case: dict, question: str) -> dict:
    """Retrieve and format relevant case context for the LLM."""
    import evidence_vault
    evidence_vault.init_evidence_tables()

    # 1. Addresses + risk
    addr_lines = []
    for a in (case.get("addresses") or [])[:50]:
        addr_lines.append(
            f"- {a['address']} ({a.get('chain', '?')}): risk={a.get('risk_score', -1)} "
            f"({a.get('risk_level', '')}), label={a.get('label', '')}"
        )

    # 2. Evidence retrieval by keyword
    question_keywords = set(re.findall(r"\b\w{4,}\b", question.lower()))
    stop_words = {"what", "where", "which", "when", "this", "that", "with", "from", "have", "been", "were"}
    question_keywords -= stop_words
    all_evidence = evidence_vault.list_evidence(case["id"], limit=200)
    scored: list[tuple[int, dict]] = []
    for ev in all_evidence:
        text = (str(ev.get("title", "")) + " " + str(ev.get("subject", "")) + " " +
                str(ev.get("analyst_notes", ""))).lower()
        score = sum(1 for kw in question_keywords if kw in text)
        # recency boost
        score += 1
        scored.append((score, ev))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_evidence = [ev for _, ev in scored[:15]]

    evidence_ids = {ev["id"] for ev in top_evidence}
    evidence_lines = []
    for ev in top_evidence:
        evidence_lines.append(
            f"[evidence:{ev['id']}] {ev.get('evidence_type', '')}: {ev.get('title', '')} "
            f"(subject={ev.get('subject', '')[:20]}, quality={ev.get('quality_score', 0)}, "
            f"chain={ev.get('chain', '')})"
        )

    # 3. Case notes
    note_lines = [f"- {n.get('note', '')[:200]}" for n in (case.get("notes") or [])[:10]]

    context_text = (
        "ADDRESSES UNDER INVESTIGATION:\n" + "\n".join(addr_lines) + "\n\n"
        "EVIDENCE RECORDS:\n" + "\n".join(evidence_lines) + "\n\n"
        "INVESTIGATOR NOTES:\n" + "\n".join(note_lines)
    )

    return {
        "context_text": context_text[:14000],
        "evidence_ids": evidence_ids,
        "summary": {
            "addresses": len(addr_lines),
            "evidence_retrieved": len(top_evidence),
            "notes": len(note_lines),
        },
    }


def _extract_citations(answer: str, valid_ids: set[str]) -> list[dict]:
    """Extract [evidence:ID] citations from the answer and validate them."""
    citations = []
    for m in re.finditer(r"\[evidence:([a-f0-9\-]+)\]", answer, re.I):
        eid = m.group(1)
        citations.append({
            "evidence_id": eid,
            "valid": eid in valid_ids,
        })
    return citations


def _fallback_answer(question: str, context: dict) -> str:
    """When AI is unavailable, return the retrieved context as a structured summary."""
    return (
        "AI is not configured, so I can't synthesize an answer. However, I retrieved "
        f"{context['summary']['evidence_retrieved']} evidence records, "
        f"{context['summary']['addresses']} addresses, and "
        f"{context['summary']['notes']} notes that may be relevant to your question. "
        "Configure an LLM provider in Settings to enable grounded Q&A."
    )
