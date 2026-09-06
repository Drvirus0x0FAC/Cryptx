#!/usr/bin/env python3
"""
scamsearch.py — ScamSearch.io integration for the Stage 08 bot.

Wraps the exact-match search endpoint at scamsearch.io and returns a
normalized result. Used by phone, username, and crypto lookups.

API docs: https://scamsearch.io/api_docs

Endpoint:
  GET https://scamsearch.io/api/search?search={value}&type={t}&api_token={key}
  type ∈ {all, email, user, address, phone}
  Rate limit: 30 req/min (1 per 2s)

Env vars:
  SCAMSEARCH_API_KEY    required — register at scamsearch.io for a free key
  SCAMSEARCH_TIMEOUT    default 15 seconds
"""

import os
import asyncio
import logging
from html import escape
from typing import Any, Dict, List, Optional

import aiohttp

log = logging.getLogger("scamsearch")

SCAMSEARCH_API_KEY = os.getenv("SCAMSEARCH_API_KEY", "").strip()
SCAMSEARCH_TIMEOUT = int(os.getenv("SCAMSEARCH_TIMEOUT", "15"))
BASE_URL           = "https://scamsearch.io/api/search"

# Global throttle: ScamSearch allows 1 req per 2 seconds
_RATE_LOCK: Optional[asyncio.Lock] = None
_LAST_CALL_TS: float = 0.0
_MIN_INTERVAL  = 2.1  # seconds between calls (slightly above 2.0 for safety)


def _get_lock() -> asyncio.Lock:
    global _RATE_LOCK
    if _RATE_LOCK is None:
        _RATE_LOCK = asyncio.Lock()
    return _RATE_LOCK


async def _rate_limited_get(params: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Single rate-limited GET to ScamSearch."""
    global _LAST_CALL_TS
    async with _get_lock():
        now = asyncio.get_event_loop().time()
        wait = _MIN_INTERVAL - (now - _LAST_CALL_TS)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            timeout = aiohttp.ClientTimeout(total=SCAMSEARCH_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(BASE_URL, params=params) as r:
                    _LAST_CALL_TS = asyncio.get_event_loop().time()
                    if r.status == 401 or r.status == 403:
                        return {"_error": "invalid_api_key"}
                    if r.status == 429:
                        return {"_error": "rate_limited"}
                    if r.status != 200:
                        body = (await r.text())[:200]
                        log.warning("ScamSearch HTTP %s: %s", r.status, body)
                        return {"_error": f"HTTP {r.status}"}
                    try:
                        return await r.json(content_type=None)
                    except Exception as e:
                        text = (await r.text())[:300]
                        log.warning("ScamSearch JSON parse error: %s body=%s", e, text)
                        return {"_error": "invalid_json"}
        except asyncio.TimeoutError:
            return {"_error": "timeout"}
        except Exception as e:
            log.warning("ScamSearch error: %s", e)
            return {"_error": str(e)[:120]}


async def search_exact(value: str, search_type: str) -> Dict[str, Any]:
    """
    Exact-match search against ScamSearch.
    search_type ∈ {'phone', 'user', 'address', 'email', 'all'}.

    Returns a normalized dict:
      {
        "found": bool,
        "count": int,
        "type": str,
        "query": str,
        "records": [ {raw record fields...}, ... ],
        "error": str (only on failure),
      }
    """
    if not SCAMSEARCH_API_KEY:
        return {"found": False, "skipped": True, "reason": "no_api_key"}
    if not value:
        return {"found": False, "error": "empty_query"}

    params = {
        "search": value,
        "type": search_type,
        "api_token": SCAMSEARCH_API_KEY,
    }
    raw = await _rate_limited_get(params)
    if raw is None:
        return {"found": False, "error": "no_response"}
    if isinstance(raw, dict) and raw.get("_error"):
        return {"found": False, "error": raw["_error"]}

    return _normalize(raw, value, search_type)


def _normalize(raw: Any, query: str, search_type: str) -> Dict[str, Any]:
    """Flatten ScamSearch responses into a stable shape."""
    records: List[Dict[str, Any]] = []

    # ScamSearch sometimes returns: a list directly, a dict with "data",
    # or a dict with the actual records nested. Handle all forms.
    if isinstance(raw, list):
        records = [r for r in raw if isinstance(r, dict)]
    elif isinstance(raw, dict):
        # API errors first
        if raw.get("error") or raw.get("message") and not raw.get("data"):
            return {
                "found": False,
                "error": str(raw.get("error") or raw.get("message"))[:200],
                "query": query, "type": search_type,
            }
        data = raw.get("data") or raw.get("results") or raw.get("result")
        if isinstance(data, list):
            records = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            records = [data]
        else:
            # Last resort: treat the whole dict as a single record if it
            # has any of the expected fields
            interesting = {"name", "email", "phone", "bitcoinaddress",
                           "user", "username", "country", "report"}
            if any(k in raw for k in interesting):
                records = [raw]

    return {
        "found": bool(records),
        "count": len(records),
        "query": query,
        "type": search_type,
        "records": records,
    }


# =========================================================================
# Telegram HTML formatter
# =========================================================================
def format_scamsearch_html(result: Optional[Dict[str, Any]]) -> str:
    """Render ScamSearch findings as a Telegram-HTML block."""
    if not result or result.get("skipped"):
        return ""  # Silent skip when no key configured
    if result.get("error"):
        return (f"<b>🛡️ ScamSearch:</b> "
                f"<i>{escape(str(result['error']))}</i>")
    if not result.get("found"):
        return "<b>🛡️ ScamSearch:</b> ✅ <i>no scam reports found</i>"

    count   = result.get("count", 0)
    records = result.get("records") or []

    lines = [f"<b>🚨 ScamSearch — {count} scam report(s)</b>"]
    for i, rec in enumerate(records[:5], 1):
        lines.append("")
        lines.append(f"<b>Report #{i}</b>")
        for key, label in (
            ("name",           "Name"),
            ("email",          "Email"),
            ("phone",          "Phone"),
            ("user",           "User"),
            ("username",       "Username"),
            ("bitcoinaddress", "BTC"),
            ("address",        "Address"),
            ("country",        "Country"),
            ("category",       "Category"),
            ("reporttype",     "Type"),
            ("source",         "Source"),
            ("date",           "Date"),
            ("dateadded",      "Added"),
        ):
            v = rec.get(key)
            if v is None or v == "" or v == "null":
                continue
            v_str = escape(str(v)[:200])
            lines.append(f"• <b>{label}:</b> <code>{v_str}</code>")
        # Report description / comment if present
        for k in ("report", "description", "comment", "details", "message"):
            v = rec.get(k)
            if v:
                lines.append(f"<i>{escape(str(v)[:300])}</i>")
                break

    if count > 5:
        lines.append("")
        lines.append(f"<i>… {count - 5} more report(s) not shown</i>")

    return "\n".join(lines)
