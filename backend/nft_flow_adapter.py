"""
NFT flow adapter — unifies NFT (ERC-721) transfers onto the money-flow graph.

QLUE's signature feature: trace an NFT from theft → marketplace sale →
proceeds liquidation on the SAME graph as ERC-20/native flows.

This module converts NFT transfer/sale events (from OpenSea + Reservoir) into
the normalized event shape that `holistic_trace_engine.trace_from_events()`
consumes:
    {chain, from, to, asset, value, value_usd, tx_hash, timestamp}

It then produces a combined graph where NFT movements render as distinct edges
(kind="nft_transfer" / "nft_sale") alongside any ERC-20/native flows, so an
investigator sees the full picture — stolen NFTs AND the ETH proceeds — on one
canvas.

Degrades gracefully: if OpenSea/Reservoir are unreachable (no key, rate-limited,
air-gapped), returns an empty NFT-event list so the caller's trace still works
on whatever data it has.
"""
from __future__ import annotations

from typing import Any
from datetime import datetime, timezone


def _parse_timestamp(date_str: str) -> int:
    """Parse an OpenSea created_date (ISO 8601) to a unix timestamp. 0 on failure."""
    if not date_str:
        return 0
    try:
        return int(datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp())
    except Exception:
        try:
            return int(float(date_str))
        except Exception:
            return 0


def opensea_events_to_holistic(opensea_result: dict[str, Any], subject: str) -> list[dict[str, Any]]:
    """Convert OpenSea events into normalized holistic-trace events.

    Each sale/transfer event becomes:
        {chain: "eth", from, to, asset: "NFT:<collection>", value, value_usd,
         tx_hash, timestamp, kind: "nft_sale"|"nft_transfer"}

    `subject` is the wallet being investigated — used to set direction relative
    to that wallet (the holistic engine computes in/out from this).
    """
    events_out: list[dict[str, Any]] = []
    subject_addr = (subject or "").lower().strip()
    norm_events = (opensea_result or {}).get("events") or []

    for e in norm_events:
        etype = str(e.get("event_type") or "").lower()
        # Only map event types that represent an actual movement of the NFT.
        if etype not in ("successful", "transfer", "primary_sale"):
            continue
        from_addr = str(e.get("from_address") or "").lower()
        to_addr = str(e.get("to_address") or "").lower()
        if not from_addr or not to_addr:
            continue  # can't build an edge without both endpoints
        price = float(e.get("price") or 0.0)
        currency = str(e.get("currency") or "ETH")
        collection = str(e.get("collection_slug") or e.get("asset_name") or "NFT")
        token_id = str(e.get("asset_token_id") or "")
        tx_hash = str(e.get("transaction_hash") or "")
        ts = _parse_timestamp(str(e.get("created_date") or ""))

        asset_label = f"NFT:{collection}" + (f"#{token_id}" if token_id else "")
        kind = "nft_sale" if etype in ("successful", "primary_sale") or price > 0 else "nft_transfer"

        events_out.append({
            "chain": "eth",
            "from": from_addr,
            "to": to_addr,
            "asset": asset_label,
            "value": price,            # sale price in native units (ETH)
            "value_usd": price * 3000,  # rough USD estimate; price_service refines downstream
            "tx_hash": tx_hash,
            "timestamp": ts,
            "kind": kind,
            "token_id": token_id,
            "collection": collection,
        })
    return events_out


def reservoir_transfers_to_holistic(reservoir_result: dict[str, Any], subject: str) -> list[dict[str, Any]]:
    """Convert Reservoir token holdings into transfer-shaped events.

    Reservoir returns current holdings (not transfers), so we synthesize
    'holding' events from the subject to each collection — enough to show NFT
    ownership on the graph even when transfer history isn't available.
    """
    events_out: list[dict[str, Any]] = []
    subject_addr = (subject or "").lower().strip()
    if not subject_addr:
        return events_out
    tokens = (reservoir_result or {}).get("tokens") or []
    for t in tokens:
        token_data = t.get("token") or t
        collection = (token_data.get("collection") or {}).get("name") or "Unknown"
        contract = (token_data.get("collection") or {}).get("id") or ""
        token_id = str(token_data.get("tokenId") or token_data.get("token_id") or "")
        if not contract:
            continue
        events_out.append({
            "chain": "eth",
            "from": contract.lower(),      # the collection contract holds the NFT
            "to": subject_addr,            # subject currently owns it
            "asset": f"NFT:{collection}" + (f"#{token_id}" if token_id else ""),
            "value": 0.0,
            "value_usd": 0.0,
            "tx_hash": "",
            "timestamp": 0,
            "kind": "nft_holding",
            "token_id": token_id,
            "collection": collection,
            "contract": contract,
        })
    return events_out


async def build_nft_enriched_graph(
    subject: str,
    *,
    include_native_trace: bool = True,
    chain: str = "eth",
) -> dict[str, Any]:
    """Build a combined graph showing NFT flows + native/ERC-20 flows for a wallet.

    This is the P1.9 endpoint: one graph, NFT (ERC-721) + ERC-20 + native,
    with distinct edge kinds so the investigator sees theft→sale→liquidation
    on a single canvas.

    Returns a holistic-shaped graph:
        {subject, graph: {nodes, edges}, nft_summary, sources, disclaimer}
    """
    subject = (subject or "").strip()
    if not subject:
        return {"error": "subject address is required"}

    all_events: list[dict[str, Any]] = []
    nft_summary: dict[str, Any] = {"collections": 0, "nft_events": 0, "sources": []}

    # 1. Gather NFT events from OpenSea (sales/transfers) + Reservoir (holdings).
    opensea_events: list[dict[str, Any]] = []
    reservoir_events: list[dict[str, Any]] = []
    try:
        import nft_tron_engine as nte
        opensea_data = await nte.fetch_opensea(subject)
        opensea_events = opensea_events_to_holistic(opensea_data, subject)
        if opensea_events:
            nft_summary["sources"].append("opensea")
    except Exception:
        pass
    try:
        import nft_tron_engine as nte
        reservoir_data = await nte.fetch_reservoir_nfts(subject)
        reservoir_events = reservoir_transfers_to_holistic(reservoir_data, subject)
        if reservoir_events:
            nft_summary["sources"].append("reservoir")
    except Exception:
        pass

    all_events.extend(opensea_events)
    all_events.extend(reservoir_events)
    nft_summary["nft_events"] = len(all_events)
    collections = {e.get("collection") for e in all_events if e.get("collection")}
    nft_summary["collections"] = len(collections)

    # 2. Optionally gather native/ERC-20 events (the "money" side).
    native_events: list[dict[str, Any]] = []
    if include_native_trace:
        try:
            import holistic_trace_engine as hte
            native_result = await hte.trace(subject, chain=chain, direction="both", max_hops=2, max_nodes=80)
            native_events = [
                {
                    "chain": e.get("chain", chain),
                    "from": e.get("source") or e.get("from", ""),
                    "to": e.get("target") or e.get("to", ""),
                    "asset": e.get("asset") or e.get("token", ""),
                    "value": float(e.get("value") or 0),
                    "value_usd": float(e.get("value_usd") or 0),
                    "tx_hash": e.get("tx_hash") or e.get("hash", ""),
                    "timestamp": int(e.get("timestamp") or 0),
                    "kind": e.get("kind") or "transfer",
                }
                for e in (native_result.get("graph") or {}).get("edges") or []
            ]
            if native_events:
                nft_summary["sources"].append("native_trace")
        except Exception:
            pass

    all_events.extend(native_events)

    # 3. Build a unified graph from all events.
    try:
        import holistic_trace_engine as hte
        graph = hte.trace_from_events(
            subject, all_events, chain=chain, direction="both", max_hops=3, min_value=0.0
        )
    except Exception as exc:
        # Fallback: build a minimal graph manually if the engine fails.
        graph = {
            "subject": subject,
            "graph": {"nodes": [{"id": subject, "address": subject, "chain": chain}], "edges": []},
            "error": f"trace_from_events failed: {exc}",
        }

    # Stamp the NFT edge kinds so the frontend can style them distinctly.
    for edge in (graph.get("graph") or {}).get("edges") or []:
        if not edge.get("kind") or edge.get("kind") == "transfer":
            asset = str(edge.get("asset") or "").upper()
            if asset.startswith("NFT:"):
                edge["kind"] = "nft_transfer"

    graph["nft_summary"] = nft_summary
    graph["disclaimer"] = (
        "NFT flow graph combines OpenSea sales/transfer events, Reservoir holdings, and native chain "
        "traces. NFT edges are leads, not proof of illicit movement — corroborate with on-chain data."
    )
    return graph
