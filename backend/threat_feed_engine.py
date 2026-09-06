"""
Blockchain Threat Landscape - RSS/Atom threat-feed aggregation engine.

Fetches a curated set of cryptocurrency / blockchain security feeds, parses them
(supporting both RSS 2.0 and Atom), caches the results in-memory with a TTL, and
exposes normalized news items (list + full-content detail) to the API layer.

No external feed-parser dependency: parsing uses the stdlib xml parser, with
BeautifulSoup (already a project dependency) for light HTML sanitization and
plain-text/summary/image extraction.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests

try:  # BeautifulSoup ships with the backend (beautifulsoup4)
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except Exception:  # pragma: no cover - fallback if bs4 missing
    _HAS_BS4 = False

logger = logging.getLogger(__name__)

# ── Curated feed sources ────────────────────────────────────────────────────────
FEED_SOURCES: List[Dict[str, str]] = [
    {
        "id": "qualys",
        "name": "Qualys - Cryptocurrency",
        "url": "https://blog.qualys.com/tag/cryptocurrency/feed",
        "category": "Vulnerability Research",
        "publisher": "Qualys Threat Research",
    },
    {
        "id": "vault12",
        "name": "Vault12 Blog",
        "url": "https://vault12.com/feeds/blog.rss",
        "category": "Wallet & Key Security",
        "publisher": "Vault12",
    },
    {
        "id": "schneier",
        "name": "Schneier on Security - Cryptocurrency",
        "url": "https://www.schneier.com/tag/cryptocurrency/feed/",
        "category": "Security Commentary",
        "publisher": "Bruce Schneier",
    },
    {
        "id": "ackee",
        "name": "Ackee Blockchain",
        "url": "https://ackee.xyz/blog/feed/",
        "category": "Smart Contract Audits",
        "publisher": "Ackee Blockchain",
    },
    {
        "id": "buzzsprout",
        "name": "Blockchain Threat Intelligence (Podcast)",
        "url": "https://feeds.buzzsprout.com/1148225.rss",
        "category": "Podcast / Threat Intel",
        "publisher": "Blockchain Threat Intelligence",
    },
    # ── Ransomware & Crypto Crime Intelligence ──────────────────────────────
    {
        "id": "bleepingcomputer",
        "name": "BleepingComputer",
        "url": "https://www.bleepingcomputer.com/feed/",
        "category": "Ransomware & Cybercrime",
        "publisher": "BleepingComputer",
    },
    {
        "id": "therecord",
        "name": "The Record by Recorded Future",
        "url": "https://therecord.media/feed/",
        "category": "Cybercrime & Threat Intel",
        "publisher": "The Record",
    },
    {
        "id": "darkreading",
        "name": "Dark Reading",
        "url": "https://www.darkreading.com/rss.xml",
        "category": "Enterprise Security",
        "publisher": "Dark Reading",
    },
    {
        "id": "krebsonsecurity",
        "name": "Krebs on Security",
        "url": "https://krebsonsecurity.com/feed/",
        "category": "Investigative Cybercrime",
        "publisher": "Brian Krebs",
    },
    {
        "id": "thehackernews",
        "name": "The Hacker News",
        "url": "https://feeds.feedburner.com/TheHackersNews",
        "category": "Threat Intelligence",
        "publisher": "The Hacker News",
    },
    {
        "id": "cisa_alerts",
        "name": "CISA Alerts",
        "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
        "category": "Government Advisories",
        "publisher": "CISA",
    },
    {
        "id": "chainalysis",
        "name": "Chainalysis Blog",
        "url": "https://blog.chainalysis.com/feed/",
        "category": "Crypto Crime & Compliance",
        "publisher": "Chainalysis",
    },
    {
        "id": "elliptic",
        "name": "Elliptic Blog",
        "url": "https://www.elliptic.co/blog/rss.xml",
        "category": "Crypto Compliance & Crime",
        "publisher": "Elliptic",
    },
    {
        "id": "trmlabs",
        "name": "TRM Labs Blog",
        "url": "https://trmlabs.com/blog/rss.xml",
        "category": "Blockchain Intelligence",
        "publisher": "TRM Labs",
    },
]

_SOURCE_BY_ID = {s["id"]: s for s in FEED_SOURCES}

# XML namespaces we care about.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CrypTX-ThreatFeed/1.0; +https://cryptx.local)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}

CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
REQUEST_TIMEOUT = 25

# ── In-memory cache ─────────────────────────────────────────────────────────────
_lock = threading.Lock()
# per-source cache: {source_id: {"fetched_at": ts, "items": [...], "error": str|None}}
_feed_cache: Dict[str, Dict[str, Any]] = {}
# flat lookup of every known item by id -> item dict (for detail view)
_item_index: Dict[str, Dict[str, Any]] = {}


# ── Helpers ─────────────────────────────────────────────────────────────────────
def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _txt(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _make_id(source_id: str, guid: str) -> str:
    return hashlib.sha1(f"{source_id}|{guid}".encode("utf-8", "ignore")).hexdigest()[:16]


def _parse_date(value: str) -> Optional[str]:
    """Return an ISO-8601 UTC string, or None."""
    value = (value or "").strip()
    if not value:
        return None
    # RFC 822 (RSS pubDate)
    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    # ISO-8601 (Atom updated/published)
    try:
        iso = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _sanitize_html(html: str, base_url: str = "") -> str:
    """Remove scripts/styles/iframes/event handlers; keep readable content HTML.

    If ``base_url`` is supplied, relative href/src links are resolved to absolute
    URLs so images and links from a fetched article page render correctly.
    """
    if not html:
        return ""
    if not _HAS_BS4:
        # Minimal fallback: strip script/style blocks.
        html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
        return html
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "iframe", "object", "embed", "form", "link", "meta", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            low = attr.lower()
            if low.startswith("on"):
                del tag.attrs[attr]
            elif low in ("href", "src") and str(tag.attrs[attr]).strip().lower().startswith("javascript:"):
                del tag.attrs[attr]
        # Absolutize relative image/link URLs against the article page.
        if base_url:
            if tag.name == "a" and tag.get("href"):
                tag["href"] = urljoin(base_url, tag["href"])
            if tag.name in ("img", "source") and tag.get("src"):
                tag["src"] = urljoin(base_url, tag["src"])
            if tag.name == "img" and tag.get("data-src") and not tag.get("src"):
                tag["src"] = urljoin(base_url, tag["data-src"])
    # Make links open safely in a new tab.
    for a in soup.find_all("a"):
        a["target"] = "_blank"
        a["rel"] = "noopener noreferrer"
    return str(soup)


# Containers most likely to hold the main article body, best first.
_ARTICLE_SELECTORS = [
    "article",
    "main",
    "[role=main]",
    ".post-content", ".entry-content", ".article-content", ".article-body",
    ".post-body", ".blog-post", ".single-post", ".content-body", ".rich-text",
    "#content", ".content", ".post", ".entry",
]


def _extract_readable(page_html: str, base_url: str) -> str:
    """Best-effort readability extraction of the main article body from a page."""
    if not _HAS_BS4 or not page_html:
        return ""
    soup = BeautifulSoup(page_html, "html.parser")
    # Strip chrome that never belongs in the article body.
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form",
                     "noscript", "iframe", "svg", "button"]):
        tag.decompose()

    def text_len(node) -> int:
        return len(node.get_text(" ", strip=True)) if node else 0

    candidate = None
    for sel in _ARTICLE_SELECTORS:
        try:
            found = soup.select(sel)
        except Exception:
            found = []
        for node in found:
            if text_len(node) > text_len(candidate):
                candidate = node
        if candidate is not None and text_len(candidate) > 800:
            break

    # Fallback: the block with the greatest concentration of <p> text.
    if candidate is None or text_len(candidate) < 400:
        best, best_score = None, 0
        for node in soup.find_all(["div", "section", "article"]):
            paras = node.find_all("p", recursive=False) or node.find_all("p")
            score = sum(len(p.get_text(" ", strip=True)) for p in paras)
            if score > best_score:
                best, best_score = node, score
        if best is not None and best_score > text_len(candidate):
            candidate = best

    if candidate is None:
        return ""
    return _sanitize_html(str(candidate), base_url=base_url)


def _needs_full_fetch(item: Dict[str, Any]) -> bool:
    """A feed entry that only shipped a short teaser is worth expanding."""
    if item.get("full_content"):
        return False
    if not item.get("link"):
        return False
    text = _plain_text(item.get("content_html") or "", limit=10**9)
    return len(text) < 900


def _enrich_full_content(item: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch the source article and replace the teaser with the full body."""
    try:
        resp = requests.get(item["link"], headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        full = _extract_readable(resp.text, base_url=item["link"])
    except Exception as exc:
        logger.info("threat-feed full-fetch failed for %s: %s", item.get("link"), exc)
        item["full_content"] = False
        return item
    # Only swap in the fetched body if it is clearly richer than the teaser.
    if full and len(_plain_text(full, limit=10**9)) > len(_plain_text(item.get("content_html") or "", limit=10**9)) + 200:
        item["content_html"] = full
        if not item.get("image"):
            item["image"] = _first_image(full)
        item["reading_minutes"] = _reading_minutes(full)
    item["full_content"] = True
    return item


def _plain_text(html: str, limit: int = 320) -> str:
    if not html:
        return ""
    if _HAS_BS4:
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    else:
        text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _first_image(html: str, media_url: str = "") -> str:
    if media_url:
        return media_url
    if not html:
        return ""
    if _HAS_BS4:
        img = BeautifulSoup(html, "html.parser").find("img")
        if img and img.get("src"):
            return str(img["src"])
        return ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
    return m.group(1) if m else ""


def _reading_minutes(html: str) -> int:
    words = len(_plain_text(html, limit=10**9).split())
    return max(1, round(words / 200)) if words else 0


# ── Parsing ─────────────────────────────────────────────────────────────────────
def _parse_rss_item(item: ET.Element, source: Dict[str, str]) -> Optional[Dict[str, Any]]:
    fields: Dict[str, str] = {}
    media_url = ""
    for child in item:
        tag = _strip_ns(child.tag)
        if tag == "encoded":  # content:encoded
            fields["content"] = child.text or ""
        elif tag == "content":
            fields["content"] = child.text or ""
        elif tag == "enclosure":
            typ = child.get("type", "")
            if typ.startswith("image"):
                media_url = child.get("url", "") or media_url
        elif tag in ("title", "link", "description", "pubDate", "creator", "guid", "date"):
            fields[tag] = child.text or ""
    # media:thumbnail / media:content
    for m in item.findall("media:thumbnail", _NS) + item.findall("media:content", _NS):
        if m.get("url"):
            media_url = m.get("url")
            break

    link = fields.get("link", "").strip()
    guid = fields.get("guid", "").strip() or link
    title = (fields.get("title", "") or "Untitled").strip()
    if not link and not guid:
        return None

    content_html = _sanitize_html(fields.get("content") or fields.get("description") or "")
    summary_src = fields.get("description") or fields.get("content") or ""
    published = _parse_date(fields.get("pubDate") or fields.get("date") or "")

    return {
        "id": _make_id(source["id"], guid),
        "source_id": source["id"],
        "source_name": source["name"],
        "publisher": source["publisher"],
        "category": source["category"],
        "title": title,
        "link": link,
        "author": (fields.get("creator") or source["publisher"]).strip(),
        "published": published,
        "summary": _plain_text(summary_src),
        "content_html": content_html,
        "image": _first_image(content_html, media_url),
        "reading_minutes": _reading_minutes(content_html),
    }


def _parse_atom_entry(entry: ET.Element, source: Dict[str, str]) -> Optional[Dict[str, Any]]:
    title = _txt(entry.find("atom:title", _NS)) or "Untitled"
    link = ""
    for l in entry.findall("atom:link", _NS):
        rel = l.get("rel", "alternate")
        if rel == "alternate" or not link:
            link = l.get("href", "") or link
    guid = _txt(entry.find("atom:id", _NS)) or link
    content_el = entry.find("atom:content", _NS)
    summary_el = entry.find("atom:summary", _NS)
    raw = (content_el.text if content_el is not None else "") or (summary_el.text if summary_el is not None else "")
    content_html = _sanitize_html(raw)
    author = _txt(entry.find("atom:author/atom:name", _NS)) or source["publisher"]
    published = _parse_date(
        _txt(entry.find("atom:published", _NS)) or _txt(entry.find("atom:updated", _NS))
    )
    if not link and not guid:
        return None
    return {
        "id": _make_id(source["id"], guid),
        "source_id": source["id"],
        "source_name": source["name"],
        "publisher": source["publisher"],
        "category": source["category"],
        "title": title.strip(),
        "link": link.strip(),
        "author": author.strip(),
        "published": published,
        "summary": _plain_text(raw),
        "content_html": content_html,
        "image": _first_image(content_html),
        "reading_minutes": _reading_minutes(content_html),
    }


def parse_feed(xml_bytes: bytes, source: Dict[str, str]) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    items: List[Dict[str, Any]] = []
    rss_items = root.findall(".//item")
    if rss_items:
        for it in rss_items:
            parsed = _parse_rss_item(it, source)
            if parsed:
                items.append(parsed)
    else:
        for entry in root.findall(".//atom:entry", _NS):
            parsed = _parse_atom_entry(entry, source)
            if parsed:
                items.append(parsed)
    return items


# ── Fetch + cache ────────────────────────────────────────────────────────────────
def _fetch_source(source: Dict[str, str]) -> Dict[str, Any]:
    try:
        resp = requests.get(source["url"], headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        items = parse_feed(resp.content, source)
        return {"fetched_at": time.time(), "items": items, "error": None}
    except Exception as exc:  # network / parse errors are non-fatal per-source
        logger.warning("threat-feed fetch failed for %s: %s", source["id"], exc)
        return {"fetched_at": time.time(), "items": [], "error": str(exc)}


def _refresh_source(source_id: str, force: bool = False) -> Dict[str, Any]:
    source = _SOURCE_BY_ID[source_id]
    with _lock:
        cached = _feed_cache.get(source_id)
        fresh = cached and (time.time() - cached["fetched_at"] < CACHE_TTL_SECONDS)
        if fresh and not force:
            return cached
    result = _fetch_source(source)  # network outside the lock
    with _lock:
        # On error, keep previously good items if we have them.
        prev = _feed_cache.get(source_id)
        if result["error"] and prev and prev.get("items"):
            result["items"] = prev["items"]
        _feed_cache[source_id] = result
        for item in result["items"]:
            _item_index[item["id"]] = item
    return result


def get_news(
    source_id: Optional[str] = None,
    limit: int = 60,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Aggregate items across sources (or a single source), newest first."""
    sources = [source_id] if source_id else [s["id"] for s in FEED_SOURCES]
    all_items: List[Dict[str, Any]] = []
    source_status: List[Dict[str, Any]] = []
    for sid in sources:
        if sid not in _SOURCE_BY_ID:
            continue
        result = _refresh_source(sid, force=force_refresh)
        src = _SOURCE_BY_ID[sid]
        source_status.append({
            "id": sid,
            "name": src["name"],
            "category": src["category"],
            "url": src["url"],
            "count": len(result["items"]),
            "error": result["error"],
            "fetched_at": datetime.fromtimestamp(result["fetched_at"], tz=timezone.utc).isoformat(),
        })
        all_items.extend(result["items"])

    def sort_key(it: Dict[str, Any]):
        return it.get("published") or ""

    all_items.sort(key=sort_key, reverse=True)
    limited = all_items[: max(1, limit)]
    # Return list items without the heavy content_html payload.
    list_items = [{k: v for k, v in it.items() if k != "content_html"} for it in limited]
    return {
        "items": list_items,
        "sources": source_status,
        "total": len(all_items),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_item(item_id: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    if force_refresh or item_id not in _item_index:
        for s in FEED_SOURCES:
            _refresh_source(s["id"], force=force_refresh)
    item = _item_index.get(item_id)
    if item is None:
        return None
    # Fully parse the article: expand teaser-only feed entries by fetching the
    # source page and extracting the complete readable body (cached in-place).
    if _needs_full_fetch(item):
        item = _enrich_full_content(item)  # network happens outside the lock
        with _lock:
            _item_index[item_id] = item
    return item


def list_sources() -> List[Dict[str, str]]:
    return [dict(s) for s in FEED_SOURCES]


def warm_cache() -> None:
    """Populate the cache in the background at startup."""
    for s in FEED_SOURCES:
        try:
            _refresh_source(s["id"], force=False)
        except Exception as exc:  # pragma: no cover
            logger.warning("threat-feed warm failed for %s: %s", s["id"], exc)


def start_warm_cache() -> None:
    threading.Thread(target=warm_cache, name="threat-feed-warm", daemon=True).start()
