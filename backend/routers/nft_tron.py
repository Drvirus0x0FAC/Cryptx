from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nft_tron_engine import investigate_nft_tron

router = APIRouter(tags=["NFT/TRON Sentinel"])


class NFTTronRequest(BaseModel):
    subject: str
    chain: str = "auto"
    focus: str = ""


@router.post("/nft-tron/analyze")
async def nft_tron_analyze(req: NFTTronRequest):
    subject = req.subject.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject address or transaction hash is required.")
    try:
        return await investigate_nft_tron(subject, req.chain, req.focus)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"NFT/TRON investigation failed: {exc}")


# ── P1.9: NFT flows unified on the money graph ─────────────────────────────
class NFTFlowGraphRequest(BaseModel):
    subject: str
    chain: str = "eth"
    include_native_trace: bool = True


@router.post("/nft-tron/flow-graph")
async def nft_flow_graph(req: NFTFlowGraphRequest):
    """Combined NFT (ERC-721) + native/ERC-20 money-flow graph.

    Shows an NFT's theft → sale → proceeds liquidation on the same canvas as
    ETH/token flows — QLUE's unified NFT tracing feature.
    """
    subject = req.subject.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="subject address is required")
    try:
        import nft_flow_adapter
        return await nft_flow_adapter.build_nft_enriched_graph(
            subject, include_native_trace=req.include_native_trace, chain=req.chain
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"NFT flow graph failed: {exc}")
