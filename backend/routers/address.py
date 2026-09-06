import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

LOOKUP_TIMEOUT = 60  # seconds


class AddressRequest(BaseModel):
    address: str


class EnsRequest(BaseModel):
    name: str


@router.post("/address")
async def lookup_address(req: AddressRequest):
    """Full OSINT lookup for a crypto address across all supported chains."""
    try:
        from crypto_osint import lookup_crypto_address
        try:
            result = await asyncio.wait_for(
                lookup_crypto_address(req.address.strip()),
                timeout=LOOKUP_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail=f"Address lookup timed out after {LOOKUP_TIMEOUT}s",
            )
        try:
            import public_enrichment_engine
            # sync requests-based engine — run off the event loop (I/O discipline)
            result["public_enrichment"] = await asyncio.to_thread(
                public_enrichment_engine.enrich_address,
                result.get("address") or req.address.strip(),
                chain=result.get("chain", ""),
                intel=result,
            )
            prices = (result["public_enrichment"].get("prices") or {})
            if prices.get("portfolio_usd") is not None and result.get("portfolio_usd") is None:
                result["portfolio_usd"] = prices["portfolio_usd"]
        except Exception as exc:  # noqa: BLE001
            result["public_enrichment"] = {
                "address": req.address.strip(),
                "error": f"public enrichment failed: {type(exc).__name__}: {exc}",
            }
        return result
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"crypto_osint module unavailable: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sanctions")
async def check_sanctions(req: AddressRequest):
    """OFAC / Chainalysis sanctions screening for a crypto address."""
    try:
        from crypto_osint import check_sanctions
        result = await check_sanctions(req.address.strip())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/arkham/status")
async def arkham_status():
    """Report whether the bundled Arkham scraper is discoverable and loadable.
    Use this to confirm the attribution parser is wired up (no network call)."""
    try:
        import arkham_osint
        return arkham_osint.scraper_diagnostics()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"arkham adapter unavailable: {e}")


@router.post("/arkham/lookup")
async def arkham_lookup_route(req: AddressRequest):
    """Deep Arkham owner resolution (full stealth browser, waits out Cloudflare).
    Used by the Intelligence-tab card to enrich when the fast inline lookup was
    blocked."""
    try:
        import arkham_osint
        return await arkham_osint.lookup_address(req.address.strip(), deep=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debank/status")
async def debank_owner_status():
    """Report whether the bundled DeBank owner adapter is loadable (no network)."""
    try:
        import debank_osint
        return debank_osint.scraper_diagnostics()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"debank adapter unavailable: {e}")


@router.post("/debank/owner")
async def debank_owner_route(req: AddressRequest):
    """Deep DeBank owner-name resolution (direct API, then headless-browser
    fallback). Used by the Intelligence-tab card to enrich when the fast inline
    lookup found no display name."""
    try:
        import debank_osint
        return await debank_osint.lookup_address(req.address.strip(), deep=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/attribution-analysis")
async def attribution_analysis(req: AddressRequest):
    """Unified owner attribution + associated wallet balances for one address.

    Runs the entity-attribution and wallet-profile providers together and merges
    them into a single, provider-agnostic result: a best owner name/labels plus
    the address's token balances, per-chain breakdown and protocol positions.
    """
    addr = req.address.strip()
    if not addr:
        raise HTTPException(status_code=400, detail="address is required")

    from datetime import datetime, timezone
    errors: list[str] = []
    arkham: dict = {}
    debank: dict = {}

    try:
        import arkham_osint
    except Exception as e:  # noqa: BLE001
        arkham_osint = None  # type: ignore
        errors.append(f"attribution provider unavailable: {e}")
    try:
        import debank_osint
    except Exception as e:  # noqa: BLE001
        debank_osint = None  # type: ignore
        errors.append(f"wallet-profile provider unavailable: {e}")

    async def _ark():
        if not arkham_osint:
            return {}
        try:
            return await arkham_osint.lookup_address(addr, deep=True) or {}
        except Exception as e:  # noqa: BLE001
            errors.append(f"attribution lookup failed: {type(e).__name__}: {e}")
            return {}

    async def _deb():
        if not debank_osint:
            return {}
        try:
            return await debank_osint.lookup_address(addr, deep=True) or {}
        except Exception as e:  # noqa: BLE001
            errors.append(f"wallet-profile lookup failed: {type(e).__name__}: {e}")
            return {}

    arkham, debank = await asyncio.gather(_ark(), _deb())

    # ── Merge owner attribution (provider-agnostic) ──────────────────────────
    owner = None
    ark_name = (arkham.get("name") or arkham.get("entity_name") or "").strip() if arkham.get("found") else ""
    deb_name = (debank.get("name") or debank.get("display_name") or debank.get("web3_id") or "").strip() if debank.get("found") else ""
    primary = ark_name or deb_name
    if primary:
        aliases = [n for n in {ark_name, deb_name} if n and n != primary]
        owner = {
            "name": primary,
            "type": arkham.get("entity_type") or ("wallet profile" if deb_name else None),
            "verified": bool(arkham.get("is_verified")),
            "labels": [l for l in (arkham.get("labels") or []) if l],
            "confidence": arkham.get("confidence"),
            "aliases": aliases,
            "bio": debank.get("bio") or "",
        }

    # ── Associated wallet balances / portfolio (from the wallet-profile source)
    portfolio = None
    if debank.get("found") and (
        debank.get("tokens") or debank.get("chains") or debank.get("protocols") or debank.get("total_usd_value")
    ):
        portfolio = {
            "total_usd": debank.get("total_usd_value") or debank.get("portfolio_usd") or 0.0,
            "chains": debank.get("chains") or [],
            "tokens": debank.get("tokens") or [],
            "protocols": debank.get("protocols") or [],
            "token_count": debank.get("token_count") or 0,
            "chain_count": debank.get("chain_count") or 0,
            "protocol_count": debank.get("protocol_count") or 0,
        }

    return {
        "address": addr,
        "found": bool(owner or portfolio),
        "owner": owner,
        "portfolio": portfolio,
        "errors": errors,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/ens/resolve")
async def ens_resolve(req: EnsRequest):
    """Resolve ENS / Unstoppable Domain name to an address."""
    try:
        from ens_resolver import resolve_domain_async
        result = await resolve_domain_async(req.name.strip())
        return result or {"error": "not_found", "name": req.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ens/reverse")
async def ens_reverse(req: AddressRequest):
    """Reverse-resolve an address to its ENS / Unstoppable Domain name."""
    try:
        from ens_resolver import resolve_ens_name
        result = await resolve_ens_name(req.address.strip())
        return {"name": result} if result else {"error": "not_found", "address": req.address}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


