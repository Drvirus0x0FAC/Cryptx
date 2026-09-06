"""
Blockchain Threat Landscape router.

Serves aggregated cryptocurrency / blockchain security news from curated RSS/Atom
feeds, plus full-content detail for a single article.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import threat_feed_engine as tfe

router = APIRouter(tags=["Blockchain Threat Landscape"])


@router.get("/threat-feed/sources")
def threat_feed_sources():
    """List the curated feed sources."""
    return {"sources": tfe.list_sources()}


@router.get("/threat-feed/news")
def threat_feed_news(
    source: str | None = Query(default=None, description="Filter to a single source id"),
    limit: int = Query(default=60, ge=1, le=200),
    refresh: bool = Query(default=False, description="Force a live refresh, bypassing cache"),
):
    """Aggregated news items across all feeds (or one source), newest first."""
    try:
        return tfe.get_news(source_id=source, limit=limit, force_refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to load threat feeds: {exc}")


@router.get("/threat-feed/item/{item_id}")
def threat_feed_item(
    item_id: str,
    refresh: bool = Query(default=False, description="Force a live refresh, bypassing cache"),
):
    """Full article content for a single feed item."""
    try:
        item = tfe.get_item(item_id, force_refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to load article: {exc}")
    if not item:
        raise HTTPException(status_code=404, detail="Article not found or feed no longer lists it")
    return {"item": item}
