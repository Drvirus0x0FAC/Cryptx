"""
OSINT sweep engine — live surface-web / social / darkweb-index scan for any address.

Tracker parity: "enter any cryptocurrency address and scan through top social media
forums and darknet sites for open-source intelligence."

Key-free live sources (best-effort, each individually fault-tolerant):
  • Reddit           full-site search with web-search fallback
  • GitHub           issues/PRs + code mentions (public search API, unauthenticated)
  • Ahmia            darkweb (.onion) index search (HTML, parsed)
  • Pastebin         official Developer API for account pastes + web-search fallback
  • BitcoinTalk      via DuckDuckGo HTML site-search (best-effort scrape)
  • Telegram / X     require API keys — reported as `configured: false` so the UI
                     can show what an API key would unlock (set TELEGRAM_BOT_TOKEN /
                     TWITTER_BEARER_TOKEN in .env to enable in a later iteration)

Results are cached (24 h TTL) and can be filed into the evidence vault with one call.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from html import unescape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote_plus, urlparse

import requests
from tgbot_runtime import tgbot_env
import config as _config

DB_PATH = _config.DB_PATH
_TGBOT_ENV = tgbot_env()
_PROJECT_ENV = Path(__file__).resolve().parent.parent / ".env"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CrypTX-OSINT/1.0",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
CACHE_TTL_S = 24 * 3600
CACHE_VERSION = 4


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip("\"'")
    return env


def _env(key: str, default: str = "") -> str:
    return (
        os.environ.get(key)
        or _read_env_file(_TGBOT_ENV).get(key)
        or _read_env_file(_PROJECT_ENV).get(key)
        or default
    )


def _cache_context() -> dict[str, bool]:
    return {
        "pastebin_api_key": bool(_env("PASTEBIN_API_KEY")),
        "pastebin_user_key": bool(_env("PASTEBIN_USER_KEY")),
    }


def init_osint_tables() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS osint_sweeps (
                address    TEXT PRIMARY KEY,
                result     TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );
            """
        )
        con.commit()


def _cache_get(address: str, reddit_type: str = "") -> Optional[dict[str, Any]]:
    with _conn() as con:
        r = con.execute("SELECT result, fetched_at FROM osint_sweeps WHERE address=?",
                        (address.lower(),)).fetchone()
    if not r:
        return None
    try:
        fetched = datetime.strptime(r["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - fetched).total_seconds() > CACHE_TTL_S:
            return None
        doc = json.loads(r["result"])
        if doc.get("cache_version") != CACHE_VERSION:
            return None
        if doc.get("cache_context") != _cache_context():
            return None
        # A different deep-Reddit mode is a different investigation — force a refetch.
        if reddit_type and doc.get("reddit_type") != reddit_type:
            return None
        doc["cached"] = True
        return doc
    except Exception:  # noqa: BLE001
        return None


def _cache_set(address: str, result: dict[str, Any]) -> None:
    with _conn() as con:
        con.execute("INSERT OR REPLACE INTO osint_sweeps (address, result, fetched_at) VALUES (?,?,?)",
                    (address.lower(), json.dumps(result), _now()))
        con.commit()


def _hit(source: str, title: str, url: str, snippet: str = "", ts: str = "",
         extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {"source": source, "title": (title or "")[:300], "url": url,
            "snippet": (snippet or "")[:500], "timestamp": ts, **(extra or {})}


def _source_result(
    ok: bool,
    hits: Optional[list[dict[str, Any]]] = None,
    *,
    status: str = "",
    error: str = "",
    warning: str = "",
) -> dict[str, Any]:
    return {
        "ok": ok,
        "hits": hits or [],
        "status": status or ("ok" if ok else "failed"),
        "error": error[:220] if error else None,
        "warning": warning[:220] if warning else None,
    }


def _strip_html(value: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def _normalize_ddg_url(url: str) -> str:
    raw = unescape(url or "")
    parsed = urlparse(raw)
    if "duckduckgo.com" in parsed.netloc and "uddg" in parsed.query:
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return target
    return raw


def _friendly_error(source: str, exc: Exception) -> tuple[str, str]:
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else 0
        if status in {401, 403, 429}:
            return "blocked", f"{source} blocked or rate-limited unauthenticated public search ({status})."
        return "unavailable", f"{source} returned HTTP {status}."
    if isinstance(exc, requests.ConnectionError):
        return "unavailable", f"{source} could not be reached from this network."
    if isinstance(exc, requests.Timeout):
        return "timeout", f"{source} timed out."
    return "failed", f"{source} search failed."


def _web_site_search(source: str, query: str, host: str, limit: int = 8) -> dict[str, Any]:
    """Best-effort fallback through DuckDuckGo HTML site-search."""
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=UA,
            timeout=20,
        )
        resp.raise_for_status()
        hits: list[dict[str, Any]] = []
        for m in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
            resp.text,
            re.S,
        ):
            url = _normalize_ddg_url(m.group(1))
            if host and host not in url:
                continue
            hits.append(_hit(source, _strip_html(m.group(2)), url, _strip_html(m.group(3))[:400]))
            if len(hits) >= limit:
                break
        return _source_result(True, hits, status="fallback")
    except Exception as exc:  # noqa: BLE001
        status, error = _friendly_error("Web fallback", exc)
        return _source_result(False, [], status=status, error=error)


def _parse_pastebin_list(xml_text: str) -> list[dict[str, str]]:
    text = (xml_text or "").strip()
    if not text or text.startswith("Bad API request") or text.startswith("No pastes found"):
        return []
    try:
        root = ET.fromstring(f"<root>{text}</root>")
    except ET.ParseError:
        return []
    pastes: list[dict[str, str]] = []
    for node in root.findall("paste"):
        item = {child.tag: child.text or "" for child in list(node)}
        if item.get("paste_key"):
            pastes.append(item)
    return pastes


def _pastebin_raw(dev_key: str, user_key: str, paste_key: str) -> str:
    resp = requests.post(
        "https://pastebin.com/api/api_raw.php",
        data={
            "api_dev_key": dev_key,
            "api_user_key": user_key,
            "api_paste_key": paste_key,
            "api_option": "show_paste",
        },
        headers=UA,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.text or ""


def _pastebin_api_error(text: str, status_code: int = 0) -> dict[str, Any]:
    detail = (text or "").strip()
    lower = detail.lower()
    if "invalid api_user_key" in lower:
        return _source_result(
            False,
            [],
            status="failed",
            error="Pastebin rejected PASTEBIN_USER_KEY. Generate a fresh user key with api_option=login, then save it in Settings.",
        )
    if "invalid api_dev_key" in lower:
        return _source_result(
            False,
            [],
            status="failed",
            error="Pastebin rejected PASTEBIN_API_KEY. Check the Developer API key saved in Settings.",
        )
    if "maximum number of 1000 active pastes" in lower:
        return _source_result(False, [], status="failed", error="Pastebin API refused the account paste list because the account has too many active pastes.")
    message = detail[:160] if detail else f"HTTP {status_code}"
    return _source_result(False, [], status="failed", error=f"Pastebin API rejected the request: {message}")


def _pastebin_official(address: str) -> dict[str, Any]:
    dev_key = _env("PASTEBIN_API_KEY")
    user_key = _env("PASTEBIN_USER_KEY")
    if not dev_key:
        return _source_result(
            False,
            [],
            status="unconfigured",
            warning="Add PASTEBIN_API_KEY in Settings to enable the official Pastebin API connector.",
        )
    if not user_key:
        return _source_result(
            False,
            [],
            status="unconfigured",
            warning="Add PASTEBIN_USER_KEY in Settings to list and inspect your own Pastebin pastes through the official API.",
        )

    try:
        resp = requests.post(
            "https://pastebin.com/api/api_post.php",
            data={
                "api_dev_key": dev_key,
                "api_user_key": user_key,
                "api_option": "list",
                "api_results_limit": "100",
            },
            headers=UA,
            timeout=20,
        )
        text = resp.text or ""
        if resp.status_code >= 400 or text.startswith("Bad API request"):
            return _pastebin_api_error(text, resp.status_code)

        hits: list[dict[str, Any]] = []
        address_l = address.lower()
        for item in _parse_pastebin_list(text)[:50]:
            paste_key = item.get("paste_key", "")
            title = item.get("paste_title") or f"Paste {paste_key}"
            url = item.get("paste_url") or f"https://pastebin.com/{paste_key}"
            title_match = address_l in title.lower() or address_l in url.lower()
            raw_text = ""
            if paste_key and not title_match:
                try:
                    raw_text = _pastebin_raw(dev_key, user_key, paste_key)
                except Exception:
                    raw_text = ""
            if title_match or address_l in raw_text.lower():
                timestamp = ""
                if item.get("paste_date", "").isdigit():
                    timestamp = datetime.fromtimestamp(int(item["paste_date"]), tz=timezone.utc).strftime("%Y-%m-%d")
                snippet = raw_text[:300] if raw_text else "Address matched Pastebin metadata."
                hits.append(_hit(
                    "pastebin_dumps",
                    title,
                    url,
                    snippet,
                    timestamp,
                    {"official_api": True},
                ))
        return _source_result(True, hits, status="official")
    except Exception as exc:  # noqa: BLE001
        status, error = _friendly_error("Pastebin official API", exc)
        return _source_result(False, [], status=status, error=error)


# ── sources ──────────────────────────────────────────────────────────────────

def _reddit(address: str) -> dict[str, Any]:
    try:
        resp = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": f'"{address}"', "limit": 15, "sort": "new"},
            headers=UA, timeout=15,
        )
        resp.raise_for_status()
        hits = []
        for child in (resp.json().get("data") or {}).get("children", []):
            d = child.get("data") or {}
            ts = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc).strftime("%Y-%m-%d")
            hits.append(_hit("reddit", d.get("title") or d.get("link_title", ""),
                             f"https://www.reddit.com{d.get('permalink', '')}",
                             (d.get("selftext") or "")[:400], ts,
                             {"subreddit": d.get("subreddit")}))
        return _source_result(True, hits)
    except Exception as exc:  # noqa: BLE001
        fallback = _web_site_search("reddit", f'site:reddit.com "{address}"', "reddit.com", limit=8)
        status, error = _friendly_error("Reddit", exc)
        if fallback.get("hits"):
            fallback["warning"] = f"{error} Used web-search fallback."
            return fallback
        return _source_result(False, [], status=status, error=f"{error} No fallback hits found.")


def _github(address: str) -> dict[str, Any]:
    try:
        resp = requests.get(
            "https://api.github.com/search/issues",
            params={"q": f'"{address}"', "per_page": 10},
            headers={**UA, "Accept": "application/vnd.github+json"}, timeout=15,
        )
        resp.raise_for_status()
        hits = []
        for item in resp.json().get("items", []):
            hits.append(_hit("github", item.get("title", ""), item.get("html_url", ""),
                             (item.get("body") or "")[:400],
                             (item.get("created_at") or "")[:10],
                             {"repo": "/".join((item.get("repository_url") or "").split("/")[-2:])}))
        return _source_result(True, hits)
    except Exception as exc:  # noqa: BLE001
        status, error = _friendly_error("GitHub", exc)
        return _source_result(False, [], status=status, error=error)


def _ahmia(address: str) -> dict[str, Any]:
    """Darkweb (.onion) index search via the clearnet Ahmia front-end."""
    try:
        resp = requests.get(f"https://ahmia.fi/search/?q={quote_plus(address)}",
                            headers=UA, timeout=20)
        resp.raise_for_status()
        html_text = resp.text
        hits = []
        # result blocks: <li class="result"> ... <a href="/search/redirect?...redirect_url=<onion>"><h4>title</h4> ... <p>snippet</p>
        for m in re.finditer(
            r'<li class="result[^"]*">.*?redirect_url=([^"&]+)[^>]*>\s*<h4>(.*?)</h4>.*?<p>(.*?)</p>',
            html_text, re.S,
        ):
            onion, title, snippet = m.group(1), m.group(2), m.group(3)
            hits.append(_hit("ahmia_darkweb", re.sub(r"<[^>]+>", "", title).strip(),
                             onion, re.sub(r"<[^>]+>", "", snippet).strip()[:400]))
            if len(hits) >= 10:
                break
        if not hits and address.lower() in html_text.lower():
            hits.append(_hit("ahmia_darkweb", "Address string appears in Ahmia results page",
                             f"https://ahmia.fi/search/?q={quote_plus(address)}",
                             "Automatic parsing found no structured results — review manually."))
        return _source_result(True, hits)
    except Exception as exc:  # noqa: BLE001
        status, error = _friendly_error("Ahmia", exc)
        return _source_result(False, [], status=status, error=error)


def _pastebin_dumps(address: str) -> dict[str, Any]:
    official = _pastebin_official(address)
    if official.get("ok") and official.get("hits"):
        return official
    fallback = _web_site_search("pastebin_dumps", f'site:pastebin.com "{address}"', "pastebin.com", limit=8)
    if fallback.get("hits"):
        if official.get("ok"):
            fallback["warning"] = "Official Pastebin API returned no account-paste hit; used web-search fallback."
        else:
            fallback["warning"] = official.get("warning") or official.get("error") or "Used Pastebin web-search fallback."
        return fallback
    if official.get("ok"):
        return _source_result(True, [], status="official", warning="Official Pastebin API returned no account-paste hits.")
    return official


def _bitcointalk(address: str) -> dict[str, Any]:
    """Best-effort site-search via DuckDuckGo's HTML endpoint."""
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f'site:bitcointalk.org "{address}"'},
            headers=UA, timeout=20,
        )
        resp.raise_for_status()
        hits = []
        for m in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
            resp.text, re.S,
        ):
            url, title, snippet = m.group(1), m.group(2), m.group(3)
            if "bitcointalk.org" not in url:
                continue
            hits.append(_hit("bitcointalk", re.sub(r"<[^>]+>", "", title).strip(), url,
                             re.sub(r"<[^>]+>", "", snippet).strip()[:400]))
            if len(hits) >= 8:
                break
        return _source_result(True, hits)
    except Exception as exc:  # noqa: BLE001
        status, error = _friendly_error("BitcoinTalk", exc)
        return _source_result(False, [], status=status, error=error)


def _twitter_x(address: str) -> dict[str, Any]:
    """Public X / Twitter mentions via web-search fallback (no paid API needed)."""
    res = _web_site_search("x_twitter", f'(site:twitter.com OR site:x.com) "{address}"', "", limit=8)
    res["hits"] = [h for h in res["hits"] if "twitter.com" in h["url"] or "x.com" in h["url"]]
    return res


def _telegram(address: str) -> dict[str, Any]:
    """Public Telegram channels / messages indexed on t.me, via web-search fallback."""
    res = _web_site_search("telegram", f'site:t.me "{address}"', "t.me", limit=8)
    return res


def _chainabuse(address: str) -> dict[str, Any]:
    """Community scam / abuse reports on Chainabuse (successor to BitcoinAbuse)."""
    res = _web_site_search("chainabuse", f'site:chainabuse.com "{address}"', "chainabuse.com", limit=8)
    return res


def _bitcoinwhoswho(address: str) -> dict[str, Any]:
    """Bitcoin Who's Who — scam reports, tags, and sightings for BTC addresses."""
    res = _web_site_search("bitcoinwhoswho", f'site:bitcoinwhoswho.com "{address}"', "bitcoinwhoswho.com", limit=6)
    return res


def _web_mentions(address: str) -> dict[str, Any]:
    """Broad, un-scoped web mentions — maximises visibility of where an address surfaces."""
    return _web_site_search("web_mentions", f'"{address}"', "", limit=10)


def _cryptoscamdb(address: str) -> dict[str, Any]:
    """CryptoScamDB — curated scam/blocklist database (public check API)."""
    try:
        resp = requests.get(
            f"https://api.cryptoscamdb.org/v1/check/{quote_plus(address)}",
            headers=UA, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        result = data.get("result") or {}
        status = str(result.get("status") or "").lower()
        entries = result.get("entries") or []
        hits: list[dict[str, Any]] = []
        for e in entries[:8]:
            name = e.get("name") or e.get("id") or "CryptoScamDB entry"
            hits.append(_hit(
                "cryptoscamdb",
                f"{name} ({e.get('type', 'scam')})",
                (e.get("url") or f"https://cryptoscamdb.org/search?q={quote_plus(address)}"),
                (e.get("description") or e.get("subcategory") or "Listed in CryptoScamDB")[:300],
                extra={"category_hint": e.get("category") or "scam", "abuse": True},
            ))
        if not hits and status in {"blocked", "scam"}:
            hits.append(_hit("cryptoscamdb", f"Address flagged: {status}",
                             f"https://cryptoscamdb.org/search?q={quote_plus(address)}",
                             "Flagged by CryptoScamDB blocklist.", extra={"abuse": True}))
        return _source_result(True, hits, status="blocklisted" if hits else "clean")
    except Exception as exc:  # noqa: BLE001
        status, error = _friendly_error("CryptoScamDB", exc)
        return _source_result(False, [], status=status, error=error)


# ── deep Reddit investigation (bundled reddit_scraper.py) ────────────────────

def _reddit_deep(address: str, search_type: str = "all") -> dict[str, Any]:
    """
    Deep Reddit research using the bundled reddit_scraper.py — the equivalent of
    `python reddit_scraper.py --address <addr> --type all`. Searches both posts
    and comments (stealth via Scrapling when installed, HTTP fallback otherwise).
    Fully fault-tolerant: any failure degrades to zero hits with a status note.
    """
    stype = search_type if search_type in ("posts", "comments", "all") else "all"
    try:
        from reddit_scraper import RedditScraper
    except Exception as exc:  # noqa: BLE001
        return _source_result(False, [], status="unavailable",
                              error=f"reddit_scraper module not importable: {type(exc).__name__}")
    try:
        scraper = RedditScraper(
            search_type=stype,
            max_pages=1,              # keep the live sweep responsive
            results_per_page=25,
            rate_limit_delay=1.0,
            sort="new",
            time_filter="all",
            use_scrapling=True,       # falls back to HTTP if Scrapling not installed
        )
        data = scraper.search(address, enrich=False)
    except Exception as exc:  # noqa: BLE001
        return _source_result(False, [], status="failed", error=f"deep Reddit search failed: {exc}")

    hits: list[dict[str, Any]] = []
    for p in (data.get("posts") or []):
        sub = p.get("subreddit") or ""
        hits.append(_hit(
            "reddit_deep",
            p.get("title") or f"Post in r/{sub}",
            p.get("url") or f"https://www.reddit.com{p.get('permalink', '')}",
            (p.get("selftext") or p.get("title") or "")[:400],
            (p.get("created_iso") or "")[:10],
            {"subreddit": sub, "post_type": "post", "author": p.get("author") or "",
             "score": p.get("score"), "num_comments": p.get("num_comments")},
        ))
    for c in (data.get("comments") or []):
        sub = c.get("subreddit") or ""
        hits.append(_hit(
            "reddit_deep",
            f"Comment in r/{sub}" if sub else "Reddit comment",
            c.get("full_permalink") or (f"https://www.reddit.com{c.get('permalink', '')}"),
            (c.get("body") or "")[:400],
            (c.get("created_iso") or "")[:10],
            {"subreddit": sub, "post_type": "comment", "author": c.get("author") or ""},
        ))

    posts_n = int(data.get("total_posts") or len([h for h in hits if h.get("post_type") == "post"]))
    comments_n = int(data.get("total_comments") or len([h for h in hits if h.get("post_type") == "comment"]))
    warning = None
    if not hits:
        warning = ("Deep Reddit search returned no matches. Reddit may have bot-blocked the request; "
                   "install `scrapling` on the backend for stealth bypass, or add a proxy.")
    res = _source_result(True, hits, status=f"deep:{stype}", warning=warning)
    res["posts"] = posts_n
    res["comments"] = comments_n
    res["search_type"] = stype
    return res


# ── signal categorization ────────────────────────────────────────────────────

# source → (analyst category, high-signal flag)
SOURCE_CATEGORY: dict[str, tuple[str, bool]] = {
    "reddit": ("social", False),
    "reddit_deep": ("social", False),
    "x_twitter": ("social", False),
    "telegram": ("social", False),
    "github": ("code", False),
    "bitcointalk": ("forum", False),
    "pastebin_dumps": ("paste", True),
    "web_mentions": ("web", False),
    "ahmia_darkweb": ("darkweb", True),
    "chainabuse": ("abuse", True),
    "cryptoscamdb": ("abuse", True),
    "bitcoinwhoswho": ("abuse", True),
}

CATEGORY_LABEL = {
    "social": "Social media", "code": "Code / dev", "forum": "Forums",
    "paste": "Paste sites", "web": "Open web", "darkweb": "Darkweb",
    "abuse": "Scam / abuse reports",
}


def _build_signals(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarize what the sweep found into investigator-facing signals."""
    by_category: dict[str, int] = {}
    high_signal = 0
    darkweb = 0
    abuse = 0
    for name, s in sources.items():
        n = len(s.get("hits", []))
        if not n:
            continue
        cat, flag = SOURCE_CATEGORY.get(name, ("web", False))
        by_category[cat] = by_category.get(cat, 0) + n
        if flag:
            high_signal += n
        if cat == "darkweb":
            darkweb += n
        if cat == "abuse":
            abuse += n

    if abuse and darkweb:
        level, headline = "critical", "Scam/abuse reports AND darkweb presence — treat as high-risk."
    elif abuse:
        level, headline = "high", "Address appears in scam/abuse databases — corroborate before clearing."
    elif darkweb:
        level, headline = "elevated", "Address surfaced on darkweb index — review the .onion context."
    elif high_signal:
        level, headline = "notable", "Address appears on paste sites — possible leak or dump."
    elif by_category:
        level, headline = "informational", "Public mentions found — mostly open-web / social context."
    else:
        level, headline = "clear", "No public open-source mentions found. Absence is itself a signal."

    return {
        "level": level,
        "headline": headline,
        "by_category": [
            {"category": c, "label": CATEGORY_LABEL.get(c, c), "hits": n}
            for c, n in sorted(by_category.items(), key=lambda kv: -kv[1])
        ],
        "high_signal_hits": high_signal,
        "darkweb_hits": darkweb,
        "abuse_hits": abuse,
    }


# ── main entry ───────────────────────────────────────────────────────────────

def sweep(address: str, refresh: bool = False, reddit_type: str = "all") -> dict[str, Any]:
    addr = (address or "").strip()
    if not addr:
        raise ValueError("address is required")
    # 'off' disables the deep scraper; posts/comments/all mirror reddit_scraper --type.
    reddit_type = reddit_type if reddit_type in ("off", "posts", "comments", "all") else "all"

    if not refresh:
        cached = _cache_get(addr, reddit_type)
        if cached:
            return cached

    sources: dict[str, dict[str, Any]] = {
        "cryptoscamdb": _cryptoscamdb(addr),
        "chainabuse": _chainabuse(addr),
        "bitcoinwhoswho": _bitcoinwhoswho(addr),
        "ahmia_darkweb": _ahmia(addr),
        "reddit": _reddit(addr),
        "x_twitter": _twitter_x(addr),
        "telegram": _telegram(addr),
        "bitcointalk": _bitcointalk(addr),
        "github": _github(addr),
        "pastebin_dumps": _pastebin_dumps(addr),
        "web_mentions": _web_mentions(addr),
    }
    # Deep Reddit investigation (posts + comments) — auto-runs unless turned off.
    if reddit_type != "off":
        sources["reddit_deep"] = _reddit_deep(addr, reddit_type)

    # Tag every hit with its analyst category + high-signal flag for the UI.
    all_hits: list[dict[str, Any]] = []
    for name, src in sources.items():
        cat, flag = SOURCE_CATEGORY.get(name, ("web", False))
        for h in src.get("hits", []):
            h.setdefault("category", cat)
            h.setdefault("high_signal", flag)
            all_hits.append(h)

    # High-signal (darkweb / abuse / paste) hits first, then by source.
    all_hits.sort(key=lambda h: (not h.get("high_signal"), h.get("source", "")))

    signals = _build_signals(sources)

    result = {
        "address": addr,
        "cache_version": CACHE_VERSION,
        "cache_context": _cache_context(),
        "reddit_type": reddit_type,
        "reddit_deep": {
            "enabled": reddit_type != "off",
            "search_type": reddit_type,
            "posts": (sources.get("reddit_deep") or {}).get("posts", 0),
            "comments": (sources.get("reddit_deep") or {}).get("comments", 0),
            "status": (sources.get("reddit_deep") or {}).get("status"),
            "warning": (sources.get("reddit_deep") or {}).get("warning"),
        },
        "swept_at": _now(),
        "total_hits": len(all_hits),
        "hits": all_hits,
        "signals": signals,
        "sources": {
            name: {"ok": s.get("ok", False), "hits": len(s.get("hits", [])),
                   "status": s.get("status"), "error": s.get("error"),
                   "warning": s.get("warning"),
                   "category": SOURCE_CATEGORY.get(name, ("web", False))[0]}
            for name, s in sources.items()
        },
        "unconfigured_sources": [
            {"name": "telegram_api", "requires": "TELEGRAM_BOT_TOKEN in backend/.env",
             "note": "Public t.me mentions are already searched. A bot token adds private/channel indexing."},
            {"name": "x_twitter_api", "requires": "TWITTER_BEARER_TOKEN in backend/.env",
             "note": "Public X mentions are already searched. A bearer token adds full realtime API coverage."},
            {"name": "pastebin_scrape_api", "requires": "PASTEBIN_API_KEY + PASTEBIN_USER_KEY in Settings",
             "note": "Enables the official Pastebin account-paste connector in addition to web-search fallback."},
        ],
        "disclaimer": "Open-source hits show where the address string appears publicly. "
                      "Verify context manually before treating any hit as attribution evidence.",
        "cached": False,
    }
    _cache_set(addr, result)
    return result


def file_to_evidence(address: str, case_id: str, actor: str = "analyst") -> dict[str, Any]:
    """File the latest sweep result into the evidence vault (hash-chained custody)."""
    result = _cache_get(address) or sweep(address)
    import evidence_vault
    record = evidence_vault.save_evidence(
        case_id=case_id,
        evidence_type="osint_sweep",
        title=f"OSINT sweep — {address[:24]} ({result['total_hits']} hits)",
        content=result,
        subject=address,
        actor=actor,
    )
    return {"evidence_id": record.get("id"), "chain_hash": record.get("chain_hash"),
            "total_hits": result["total_hits"]}
