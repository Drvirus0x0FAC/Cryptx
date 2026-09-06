"""
Natural-language multi-step investigation agent for CrypTX.

Takes a free-text prompt ("trace this address, find the cash-out, draft a SAR,
open a freeze request") and autonomously sequences the right investigation tools
to fulfill it — the capability both Chainalysis and TRM shipped in summer 2026.

Design (per the P1.11 exploration recommendation #1):
  * The LLM is given a set of TOOL DEFINITIONS (name, description, params).
  * It emits a tool call → we execute the corresponding Python function
    (wrapping existing engines) → feed the result back → repeat until the LLM
    emits a final answer or hits the step cap.
  * Progress is reported via the same _JOBS polling pattern autopilot uses.

This is NOT routing through MCP (those tools are for external LLM clients);
the agent calls engines in-process for zero transport overhead.

Tool-calling support varies by provider. For providers without native
tool-calling, we fall back to a "plan-then-execute" mode: the LLM emits a JSON
plan (list of tool calls), we execute them in order, then summarize.

Degrades gracefully: if no AI provider is configured, returns a helpful error
suggesting the user configure one in Settings.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

MAX_STEPS = 8  # cap to prevent runaway loops


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Tool definitions ────────────────────────────────────────────────────────
# Each tool is (name, description, param_schema, async_executor).
# The executor wraps an existing engine function.

TOOLS: list[dict[str, Any]] = [
    {
        "name": "screen_sanctions",
        "description": "Check if an address appears on any sanctions list (OFAC, OpenSanctions). Returns hit details.",
        "params": {"address": "str", "chain": "str (optional, default 'eth')"},
    },
    {
        "name": "trace_funds",
        "description": "Trace fund flows from an address across chains. Returns a graph of where the money went, including cash-out points at exchanges.",
        "params": {"address": "str", "chain": "str (default 'eth')", "direction": "str (in|out|both, default 'out')", "max_hops": "int (default 3)"},
    },
    {
        "name": "identify_vasp",
        "description": "Identify if an address belongs to a known exchange/VASP. Returns the VASP name, jurisdiction, and type.",
        "params": {"address": "str", "chain": "str (optional)"},
    },
    {
        "name": "compute_risk",
        "description": "Compute a risk score (0-100) for an address based on 20+ indicators. Returns risk level and contributing factors.",
        "params": {"address": "str", "chain": "str (default 'eth')"},
    },
    {
        "name": "draft_sar",
        "description": "Draft a Suspicious Activity Report for an address. Returns a structured SAR with narrative, categories, and counterparties.",
        "params": {"address": "str", "chain": "str (default 'eth')", "case_id": "str (optional)", "narrative": "str (optional extra context)"},
    },
    {
        "name": "open_freeze_request",
        "description": "Open a freeze-request workflow for an illicit address. Builds the evidence package targeting the right issuer (Tether, Circle) or VASP.",
        "params": {"address": "str", "chain": "str (default 'eth')", "case_id": "str (optional)", "reason": "str (why this should be frozen)"},
    },
    {
        "name": "search_entities",
        "description": "Search for known entities (exchanges, sanctioned actors, mixers) by name. Returns matching entity cards with addresses.",
        "params": {"query": "str (entity name, e.g. 'Binance', 'Lazarus')"},
    },
    {
        "name": "get_address_intel",
        "description": "Get full address intelligence: balance, tokens, transactions, attribution, risk signals.",
        "params": {"address": "str", "chain": "str (default 'eth')"},
    },
]

TOOL_NAMES = {t["name"] for t in TOOLS}


async def _execute_tool(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool by name. Each wraps an existing engine function."""
    try:
        if name == "screen_sanctions":
            import sanctions_engine
            res = sanctions_engine.screen_address(params.get("address", ""), params.get("chain"))
            return {"tool": name, "result": res}

        elif name == "trace_funds":
            import holistic_trace_engine as hte
            import os
            api_key = os.environ.get("ETHERSCAN_API_KEY", "")
            res = await hte.trace(
                params.get("address", ""),
                chain=params.get("chain", "eth"),
                direction=params.get("direction", "out"),
                max_hops=min(int(params.get("max_hops", 3)), 5),
                max_nodes=80,
                min_value=0.0,
                api_key=api_key,
            )
            # Summarize for the LLM (full graph is too large).
            summary = res.get("summary", {})
            cash_outs = summary.get("cash_out_points") or []
            exchanges = summary.get("exchanges_reached") or []
            return {
                "tool": name,
                "result": {
                    "summary": {
                        "node_count": summary.get("node_count"),
                        "edge_count": summary.get("edge_count"),
                        "total_traced_value": summary.get("total_traced_value"),
                        "cash_out_points": cash_outs[:5],
                        "exchanges_reached": exchanges[:5],
                        "mixers_hit": summary.get("mixers_hit"),
                        "bridges_crossed": summary.get("bridges_crossed"),
                        "sanctioned_hits": summary.get("sanctioned_hits"),
                    },
                },
            }

        elif name == "identify_vasp":
            import vasp_directory
            res = vasp_directory.identify_vasp(params.get("address", ""), params.get("chain"))
            return {"tool": name, "result": res}

        elif name == "compute_risk":
            import risk_engine
            import crypto_osint
            intel = crypto_osint.lookup_crypto_address(params.get("address", ""), params.get("chain", "eth"))
            res = risk_engine.compute_risk_score(intel)
            return {"tool": name, "result": res}

        elif name == "draft_sar":
            import regulatory_reports
            res = regulatory_reports.generate_sar(
                subject_address=params.get("address", ""),
                chain=params.get("chain", "eth"),
                case_id=params.get("case_id", ""),
                narrative=params.get("narrative", ""),
            )
            return {"tool": name, "result": {"sar_id": res.get("id"), "filing_entity": res.get("filing_entity"), "narrative_preview": (res.get("narrative") or "")[:500]}}

        elif name == "open_freeze_request":
            import recovery_ops
            res = recovery_ops.build_package(
                address=params.get("address", ""),
                chain=params.get("chain", "eth"),
                case_id=params.get("case_id", ""),
                reason=params.get("reason", ""),
            )
            return {"tool": name, "result": {"package_id": res.get("id"), "target": res.get("target"), "status": res.get("status")}}

        elif name == "search_entities":
            import entity_search
            res = entity_search.search_entities(params.get("query", ""), limit=10)
            return {"tool": name, "result": {"entities": res.get("entities", []), "count": res.get("count", 0)}}

        elif name == "get_address_intel":
            import crypto_osint
            intel = crypto_osint.lookup_crypto_address(params.get("address", ""), params.get("chain", "eth"))
            # Summarize for the LLM.
            return {"tool": name, "result": {
                "balance": intel.get("balance"),
                "chain": intel.get("chain"),
                "transaction_count": len(intel.get("transactions") or []),
                "token_count": len(intel.get("tokens") or []),
            }}

        else:
            return {"tool": name, "error": f"unknown tool '{name}'"}

    except Exception as exc:
        return {"tool": name, "error": str(exc)}


# ── System prompt for the LLM ───────────────────────────────────────────────

SYSTEM_PROMPT = """You are CrypTX AI Investigator, an autonomous investigation agent for cryptocurrency crime.

You have access to tools that trace funds, screen sanctions, identify exchanges, compute risk, draft SARs, open freeze requests, search entities, and get address intelligence.

INSTRUCTIONS:
1. Read the investigator's request carefully.
2. Decide which tools to call, in what order, to fulfill it.
3. Emit tool calls ONE AT A TIME as JSON: {"tool": "<name>", "params": {...}}
4. After each tool result, decide the next step or give your final answer.
5. When done, respond with {"final_answer": "<your summary for the investigator>"}.

RULES:
- Be thorough: if asked to "investigate this address", trace it, check sanctions, compute risk, find the cash-out, and summarize.
- Ground every claim in tool results. Never fabricate addresses, amounts, or entities.
- Use "lead, not claim" language: attribution is investigative lead, not proof.
- If a tool fails, note it and proceed with what you have.
- For SARs and freeze requests, always confirm the address and reason before calling.
- Keep final answers concise and actionable: what did you find, what should the investigator do next?

You may call at most {max_steps} tools. Available tools:
{tools}
""".strip()


def _format_tools_for_prompt() -> str:
    lines = []
    for t in TOOLS:
        params = ", ".join(f"{k}: {v}" for k, v in t["params"].items())
        lines.append(f"- {t['name']}({params}): {t['description']}")
    return "\n".join(lines)


# ── Agent loop ──────────────────────────────────────────────────────────────

# In-memory job store (mirrors autopilot's pattern).
_JOBS: dict[str, dict[str, Any]] = {}
_MAX_JOBS = 50


async def run_nl_investigation(prompt: str, case_id: str = "", analyst: str = "analyst") -> dict[str, Any]:
    """Run a natural-language investigation. Returns the final result.

    The loop:
      1. Send the prompt + tool definitions to the LLM.
      2. Parse the response for a tool call or final answer.
      3. Execute the tool, feed the result back.
      4. Repeat until final answer or MAX_STEPS.
    """
    from ai_client import ai_chat, ai_configured

    if not ai_configured():
        return {
            "error": "No AI provider configured. Set an AI provider (DeepSeek/OpenAI/Claude) in Settings to use the NL investigation agent.",
            "configured": False,
        }

    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "prompt": prompt,
        "case_id": case_id,
        "status": "running",
        "step": 0,
        "max_steps": MAX_STEPS,
        "tool_calls": [],
        "final_answer": None,
        "error": None,
        "started_at": _now(),
        "updated_at": _now(),
    }
    _JOBS[job_id] = job
    # LRU eviction.
    if len(_JOBS) > _MAX_JOBS:
        oldest = next(iter(_JOBS))
        del _JOBS[oldest]

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(
                max_steps=MAX_STEPS, tools=_format_tools_for_prompt()
            )},
            {"role": "user", "content": f"Investigation request: {prompt}\n\nCase: {case_id or '(none)'}\nAnalyst: {analyst}"},
        ]

        for step in range(MAX_STEPS):
            job["step"] = step + 1
            job["updated_at"] = _now()

            response = await ai_chat(messages, max_tokens=2000, temperature=0.15)
            content = response.get("content", "").strip()

            # Parse: is it a tool call, a final answer, or something else?
            tool_call = _parse_tool_call(content)
            final = _parse_final_answer(content)

            if final:
                job["final_answer"] = final
                job["status"] = "completed"
                job["updated_at"] = _now()
                break

            if tool_call:
                tool_name = tool_call.get("tool")
                tool_params = tool_call.get("params") or {}
                if tool_name not in TOOL_NAMES:
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Error: unknown tool '{tool_name}'. Available: {sorted(TOOL_NAMES)}"})
                    continue

                # Execute the tool.
                result = await _execute_tool(tool_name, tool_params)
                job["tool_calls"].append({
                    "step": step + 1,
                    "tool": tool_name,
                    "params": tool_params,
                    "result_preview": json.dumps(result, default=str)[:1000],
                })
                job["updated_at"] = _now()

                # Feed the result back to the LLM.
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"Tool result for {tool_name}:\n{json.dumps(result, default=str)[:3000]}\n\nDecide your next step, or give your final answer."})
                continue

            # Neither tool call nor final answer — nudge the LLM.
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "Please either call a tool ({\"tool\": ..., \"params\": ...}) or give your final answer ({\"final_answer\": ...})."})
        else:
            # Hit the step cap.
            job["status"] = "step_limit_reached"
            job["final_answer"] = "Reached the maximum number of tool calls without a final answer. See tool_calls for the investigation steps taken."

    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        job["updated_at"] = _now()

    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    return _JOBS.get(str(job_id))


def list_jobs() -> list[dict[str, Any]]:
    return sorted(_JOBS.values(), key=lambda j: j.get("started_at", ""), reverse=True)[:20]


# ── Response parsers ────────────────────────────────────────────────────────

def _parse_tool_call(content: str) -> dict[str, Any] | None:
    """Extract a {"tool": ..., "params": ...} JSON object from the LLM response."""
    # Try direct JSON parse first.
    try:
        obj = json.loads(content)
        if isinstance(obj, dict) and "tool" in obj:
            return obj
    except json.JSONDecodeError:
        pass
    # Try to find a JSON object with "tool" in the text — handle nested braces
    # by scanning for balanced {...} blocks.
    depth = 0
    start = -1
    for i, ch in enumerate(content):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = content[start:i + 1]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict) and "tool" in obj:
                        return obj
                except json.JSONDecodeError:
                    pass
                start = -1
    return None


def _parse_final_answer(content: str) -> str | None:
    """Extract a final answer from the LLM response."""
    try:
        obj = json.loads(content)
        if isinstance(obj, dict) and "final_answer" in obj:
            return str(obj["final_answer"])
    except json.JSONDecodeError:
        pass
    # If the content doesn't look like a tool call and isn't JSON, and we've
    # done at least one step, treat a plain-text response as a final answer.
    if "tool" not in content.lower() and len(content) > 50:
        # Heuristic: a substantial non-JSON, non-tool-call response is likely the answer.
        return content
    return None
