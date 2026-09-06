#!/usr/bin/env python3
"""
CryptoOSINT MCP Server.

Exposes the CryptoOSINT investigation engines as Model Context Protocol (MCP)
tools so AI agents (Claude Desktop, Cursor, Zed, custom MCP clients) can drive
investigations directly: sanctions screening, Know-Your-VASP, regulatory report
drafting, Tornado Cash / bridge demixing, and NFT/TRON analysis.

Run (stdio, for Claude Desktop / Cursor):
    uv run mcp_server.py            # or: python mcp_server.py
Run (HTTP, for remote clients):
    python mcp_server.py --remote --port 8002

Requires: pip install fastmcp
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import os
import sys
from typing import Any, Optional

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover
    print("fastmcp is required. Install with: pip install fastmcp", file=sys.stderr)
    raise

# Local engines (run this file from the backend/ directory).
import sanctions_engine
import vasp_directory
import regulatory_reports
import demix_engine
import nft_tron_engine

mcp = FastMCP("CryptoOSINT")


# ============================================================================
# SANCTIONS
# ============================================================================
@mcp.tool()
def screen_sanctions_address(address: str, chain: Optional[str] = None) -> dict:
    """Screen a blockchain address against OFAC + multi-jurisdiction sanctions lists.

    Args:
        address: Blockchain address to screen.
        chain: Optional chain hint (eth, btc, trx, ...).
    Returns: match details including sanctioning entity, programs, and source list.
    """
    return sanctions_engine.screen_address(address, chain)


@mcp.tool()
def search_sanctions_name(query: str, limit: int = 25, min_score: float = 0.55) -> dict:
    """Fuzzy-search the sanctions database by entity or individual name (catches misspellings/aliases).

    Args:
        query: Name to search (e.g. 'tornado cash', 'garentex').
        limit: Max results.
        min_score: Minimum fuzzy match score (0-1).
    """
    return sanctions_engine.search_name(query, limit, min_score)


# ============================================================================
# KNOW-YOUR-VASP
# ============================================================================
@mcp.tool()
def identify_vasp(address: str, chain: Optional[str] = None) -> dict:
    """Identify whether an address belongs to a known VASP/exchange (off-ramp attribution).

    Args:
        address: Blockchain address.
        chain: Optional chain hint.
    """
    return vasp_directory.identify_vasp(address, chain)


# ============================================================================
# REGULATORY REPORTING
# ============================================================================
@mcp.tool()
def generate_sar(
    subject_address: str,
    narrative: str = "",
    activity_categories: Optional[list[str]] = None,
    counterparties: Optional[list[str]] = None,
    total_amount_usd: float = 0.0,
    chain: str = "",
    case_id: str = "",
) -> dict:
    """Generate a draft Suspicious Activity Report (SAR), auto-enriched with sanctions + VASP context.

    Args:
        subject_address: The address the SAR is about.
        narrative: Free-text description of the suspicious activity.
        activity_categories: e.g. ['Mixer / tumbler use', 'Sanctions evasion'].
        counterparties: List of related addresses.
        total_amount_usd: Aggregate USD amount involved.
        chain: Chain hint.
        case_id: Optional case reference.
    """
    return regulatory_reports.generate_sar({
        "subject_address": subject_address,
        "narrative": narrative,
        "activity_categories": activity_categories or [],
        "counterparties": counterparties or [],
        "total_amount_usd": total_amount_usd,
        "chain": chain,
        "case_id": case_id,
    })


@mcp.tool()
def generate_travel_rule(
    chain: str,
    asset: str,
    amount: str,
    originator_address: str,
    beneficiary_address: str,
    originator_name: str = "",
    beneficiary_name: str = "",
    tx_hash: str = "",
) -> dict:
    """Generate a draft FATF Travel Rule (IVMS101-style) message with VASP + sanctions checks.

    Args:
        chain: Blockchain (eth, btc, ...).
        asset: Asset symbol.
        amount: Transfer amount.
        originator_address: Sender address.
        beneficiary_address: Recipient address.
        originator_name / beneficiary_name: Optional party names.
        tx_hash: Optional transaction hash.
    """
    return regulatory_reports.generate_travel_rule({
        "chain": chain, "asset": asset, "amount": amount, "tx_hash": tx_hash,
        "originator": {"name": originator_name, "address": originator_address},
        "beneficiary": {"name": beneficiary_name, "address": beneficiary_address},
    })


# ============================================================================
# DEMIXING
# ============================================================================
@mcp.tool()
def demix_tornado_cash(deposits: list[dict], withdrawals: list[dict]) -> dict:
    """Pair Tornado Cash pool deposits to withdrawals (probabilistic leads).

    Args:
        deposits: [{tx_hash, address, funder, denomination, timestamp, relayer}, ...]
        withdrawals: [{tx_hash, recipient, denomination, timestamp, relayer}, ...]
    """
    return demix_engine.demix_tornado(deposits, withdrawals)


@mcp.tool()
def demix_bridge(source_events: list[dict], dest_events: list[dict]) -> dict:
    """Reconcile cross-chain bridge lock/burn to mint/unlock by amount + timing.

    Args:
        source_events: [{tx_hash, chain, token, amount, timestamp, sender, recipient}, ...]
        dest_events: [{tx_hash, chain, token, amount, timestamp, recipient}, ...]
    """
    return demix_engine.demix_bridge(source_events, dest_events)


# ============================================================================
# NFT / TRON
# ============================================================================
@mcp.tool()
async def investigate_nft_tron(subject: str, chain: str = "auto", focus: str = "") -> dict:
    """Run an NFT/TRON cybercrime investigation (risk, signals, OSINT pivots, OpenSea lookup).

    Args:
        subject: NFT wallet, TRON address, or transaction hash.
        chain: auto | evm | tron.
        focus: Optional analyst focus note.
    """
    return await nft_tron_engine.investigate_nft_tron(subject, chain, focus)


def _init_engines() -> None:
    try:
        sanctions_engine.init_sanctions_tables()
        vasp_directory.init_vasp_tables()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] engine init: {exc}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoOSINT MCP Server")
    parser.add_argument("--remote", "--rm", action="store_true", help="Run as HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8002, help="HTTP port (default 8002)")
    parser.add_argument("--auth-token", default=os.getenv("MCP_AUTH_TOKEN", ""),
                        help="Bearer token required for HTTP/remote mode (or set MCP_AUTH_TOKEN env). "
                             "Required when --remote is used with a non-loopback host.")
    args = parser.parse_args()

    _init_engines()

    if args.remote:
        # SECURITY: require an auth token when binding to a non-loopback address,
        # otherwise the server would expose sanctions screening, SAR drafting, and
        # demixing to anyone who can reach the port. Refuse to start otherwise.
        is_loopback = args.host in ("127.0.0.1", "localhost", "::1")
        if not is_loopback and not args.auth_token:
            print(
                "[SECURITY] Refusing to start MCP HTTP server on a public interface "
                f"({args.host}) without --auth-token. Either bind to 127.0.0.1 or set "
                "MCP_AUTH_TOKEN / --auth-token.",
                file=sys.stderr,
            )
            sys.exit(1)
        if args.auth_token:
            # Register a lightweight auth middleware on the FastMCP http transport.
            # fastmcp exposes the underlying Starlette/ASGI app via .http_app() or
            # we add middleware before .run().
            try:
                from starlette.middleware.base import BaseHTTPMiddleware
                from starlette.requests import Request
                from starlette.responses import JSONResponse

                class _TokenAuth(BaseHTTPMiddleware):
                    async def dispatch(self, request: Request, call_next):
                        # allow the MCP handshake / SSE endpoints after token check
                        auth = request.headers.get("authorization", "")
                        token = auth.removeprefix("Bearer ").strip() if auth else ""
                        if not hmac.compare_digest(token, args.auth_token):
                            return JSONResponse(
                                {"detail": "Invalid or missing MCP auth token"},
                                status_code=401,
                            )
                        return await call_next(request)

                # fastmcp's server exposes the ASGI app; attach middleware if available
                if hasattr(mcp, "_http_app"):
                    mcp._http_app.add_middleware(_TokenAuth)
                elif hasattr(mcp, "http_app"):
                    mcp.http_app().add_middleware(_TokenAuth)
                else:
                    print("[WARN] Could not attach auth middleware to this fastmcp version; "
                          "running unauthenticated. Ensure the port is not exposed.",
                          file=sys.stderr)
            except ImportError:
                print("[WARN] starlette not available; cannot enforce MCP auth token. "
                      "Ensure the port is firewalled.", file=sys.stderr)
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
