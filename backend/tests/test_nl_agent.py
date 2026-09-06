"""Smoke tests for the NL investigation agent (P1.11).

These test the parsers + tool execution without requiring a live LLM call.
"""
import json
import os
import sys
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nl_agent


def test_tool_definitions_complete():
    """Every tool has name, description, params."""
    for t in nl_agent.TOOLS:
        assert "name" in t
        assert "description" in t
        assert "params" in t
        assert isinstance(t["params"], dict)
    # Critical tools for the demo workflow exist.
    names = {t["name"] for t in nl_agent.TOOLS}
    assert "trace_funds" in names
    assert "draft_sar" in names
    assert "open_freeze_request" in names
    assert "screen_sanctions" in names
    assert "identify_vasp" in names


def test_parse_tool_call_json():
    """A clean JSON tool call is parsed."""
    content = '{"tool": "trace_funds", "params": {"address": "0xabc", "chain": "eth"}}'
    result = nl_agent._parse_tool_call(content)
    assert result is not None
    assert result["tool"] == "trace_funds"
    assert result["params"]["address"] == "0xabc"


def test_parse_tool_call_embedded():
    """A tool call embedded in prose is extracted."""
    content = 'Let me trace the funds.\n{"tool": "screen_sanctions", "params": {"address": "0xdef"}}\nThat should work.'
    result = nl_agent._parse_tool_call(content)
    assert result is not None
    assert result["tool"] == "screen_sanctions"


def test_parse_tool_call_rejects_non_tool_json():
    """JSON without a 'tool' key returns None."""
    content = '{"final_answer": "done"}'
    assert nl_agent._parse_tool_call(content) is None


def test_parse_final_answer_json():
    content = '{"final_answer": "The funds were traced to Binance. Recommend subpoena."}'
    result = nl_agent._parse_final_answer(content)
    assert result is not None
    assert "Binance" in result


def test_parse_final_answer_plaintext():
    """A substantial plain-text response is treated as a final answer."""
    content = "Based on the investigation, the funds were traced through a mixer and cashed out at Binance. I recommend serving legal process on Binance for KYC records."
    result = nl_agent._parse_final_answer(content)
    assert result is not None
    assert "Binance" in result


def test_parse_final_answer_rejects_tool_call():
    """A tool-call response is not treated as a final answer."""
    content = '{"tool": "trace_funds", "params": {"address": "0xabc"}}'
    # It's JSON with "tool" → not a final answer, and too short/structured for the heuristic.
    result = nl_agent._parse_final_answer(content)
    assert result is None


def test_screen_sanctions_tool_executes():
    """The screen_sanctions tool wraps sanctions_engine and returns a result."""
    import config
    import sanctions_engine
    sanctions_engine.DB_PATH = config.DB_PATH
    sanctions_engine.init_sanctions_tables()

    import asyncio
    result = asyncio.run(nl_agent._execute_tool("screen_sanctions", {"address": "0x8589427373d6d84e98730d7795d8f6f8731fda16"}))
    assert result["tool"] == "screen_sanctions"
    assert "result" in result or "error" in result


def test_search_entities_tool_executes():
    """The search_entities tool wraps entity_search and returns results."""
    import config, vasp_directory, sanctions_engine, database, entity_search
    for mod in (vasp_directory, sanctions_engine, database, entity_search):
        mod.DB_PATH = config.DB_PATH
    vasp_directory.init_vasp_tables()
    sanctions_engine.init_sanctions_tables()
    database.init_db()

    import asyncio
    result = asyncio.run(nl_agent._execute_tool("search_entities", {"query": "Binance"}))
    assert result["tool"] == "search_entities"
    assert "result" in result


def test_unknown_tool_returns_error():
    import asyncio
    result = asyncio.run(nl_agent._execute_tool("bogus_tool", {}))
    assert "error" in result


def test_format_tools_for_prompt_includes_all_tools():
    """The system prompt lists every tool."""
    text = nl_agent._format_tools_for_prompt()
    for t in nl_agent.TOOLS:
        assert t["name"] in text


def test_run_without_ai_returns_config_error():
    """When no AI provider is configured, run_nl_investigation returns a helpful error."""
    # Ensure no provider is configured.
    os.environ.pop("AI_PROVIDER", None)
    os.environ.pop("DEEPSEEK_API_KEY", None)
    import asyncio
    result = asyncio.run(nl_agent.run_nl_investigation("trace 0xabc"))
    assert result.get("configured") is False or result.get("error")
