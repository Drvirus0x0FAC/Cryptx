"""
Label-growth loop router — /api/labels

  POST /api/labels/ingest-victim-reports   feed confirmed reports → attribution
  POST /api/labels/import                  bulk import a label set
  POST /api/labels/run-growth-loop         run all ingestion sources
  GET  /api/labels/stats                   attribution database statistics
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import label_growth

router = APIRouter(prefix="/labels", tags=["Label Growth"])


class ImportRequest(BaseModel):
    items: list[dict[str, Any]]
    source: str
    default_chain: str = "eth"
    default_category: str = "unknown"
    default_confidence: float = 0.5
    assigned_by: str = "bulk_import"


@router.post("/ingest-victim-reports")
def ingest_victim_reports(limit: int = 500):
    """Feed confirmed victim reports into the attribution engine."""
    return label_growth.ingest_confirmed_victim_reports(limit=limit)


@router.post("/import")
def import_labels(req: ImportRequest):
    """Bulk import a label set (OFAC, Etherscan tags, Dune, GitHub IOCs, etc.)."""
    if not req.items:
        raise HTTPException(status_code=400, detail="items array is required")
    if not req.source.strip():
        raise HTTPException(status_code=400, detail="source is required")
    return label_growth.import_label_set(
        req.items,
        req.source.strip(),
        default_chain=req.default_chain,
        default_category=req.default_category,
        default_confidence=req.default_confidence,
        assigned_by=req.assigned_by,
    )


@router.post("/run-growth-loop")
def run_growth_loop():
    """Run all label ingestion sources in sequence."""
    return label_growth.run_growth_loop()


@router.get("/stats")
def stats():
    """Return attribution database statistics."""
    return label_growth.label_stats()
