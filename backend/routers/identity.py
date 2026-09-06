from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database as db
from identity_profile_engine import build_identity_profile

router = APIRouter(tags=["identity"])

# Locate the bundled debank_scraper.py dynamically so the tool runs on any
# device/OS with no environment variables. Prefer the tool's backend folder,
# then fall back to the repo root, the current working dir, and anything
# already importable. ``DEBANK_SCRAPER_DIR`` is honoured if set but not required.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../backend
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)


def _find_debank_dir() -> str:
    """Return the first directory that contains debank_scraper.py."""
    candidates = [
        os.environ.get("DEBANK_SCRAPER_DIR", "").strip(),
        _BACKEND_DIR,
        _REPO_ROOT,
        os.getcwd(),
        os.path.join(os.getcwd(), "backend"),
        *sys.path,
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        resolved = os.path.abspath(os.path.expanduser(candidate))
        if resolved in seen:
            continue
        seen.add(resolved)
        if os.path.isfile(os.path.join(resolved, "debank_scraper.py")):
            return resolved
    # Fall back to the backend folder so any import error stays readable.
    return _BACKEND_DIR


_DEBANK_DIR = _find_debank_dir()
if _DEBANK_DIR not in sys.path:
    sys.path.insert(0, _DEBANK_DIR)

# Backwards-compatible alias (used by the subprocess scraper below).
_PROJECT_ROOT = _DEBANK_DIR


class IdentityProfileRequest(BaseModel):
    address: str
    intel: Optional[dict[str, Any]] = None
    graph: Optional[dict[str, Any]] = None
    threat: Optional[dict[str, Any]] = None
    include_lookup: bool = True


async def _reverse_name(address: str) -> str | None:
    profile = await _domain_profile(address)
    return profile.get("reverse_name") or None


async def _domain_profile(address: str) -> dict[str, Any]:
    try:
        from ens_resolver import resolve_all_domains
        result = await asyncio.wait_for(resolve_all_domains(address), timeout=18)
        ens = result.get("ens") or {}
        return {
            "reverse_name": ens.get("reverse_name") or "",
            "text_records": ens.get("text_records") or {},
            "resolver_address": ens.get("resolver_address") or "",
            "source": "ens",
            "raw": result,
        }
    except Exception:
        return {}


async def _lookup(address: str) -> dict[str, Any]:
    try:
        from crypto_osint import lookup_crypto_address
        return await asyncio.wait_for(lookup_crypto_address(address), timeout=60)
    except Exception:
        return {}


async def _evm_chain_scan(address: str) -> list[dict[str, Any]]:
    if not address.lower().startswith("0x"):
        return []
    try:
        from crypto_osint import ETHERSCAN_API_KEY, ETHERSCAN_CHAINS, _lookup_eth_etherscan
        if not ETHERSCAN_API_KEY:
            return []

        async def _one(chainid: int) -> dict[str, Any]:
            try:
                return await asyncio.wait_for(_lookup_eth_etherscan(address, chainid), timeout=35)
            except Exception as exc:
                info = ETHERSCAN_CHAINS.get(chainid, {})
                return {
                    "chain": info.get("label", str(chainid)),
                    "chainid": chainid,
                    "address": address,
                    "error": str(exc)[:180],
                }

        rows = await asyncio.gather(*[_one(cid) for cid in ETHERSCAN_CHAINS])
        return [
            row for row in rows
            if row and not (
                row.get("error")
                and not row.get("tx_count")
                and not row.get("balance")
                and not row.get("tokens")
            )
        ]
    except Exception:
        return []


def _debank_scrape_sync(addr: str) -> dict[str, Any]:
    """Run live wallet telemetry collection in a thread using fastest mode first."""
    from debank_scraper import DeBankAPIClient
    errors: list[str] = []

    try:
        client = DeBankAPIClient(rate_limit=0.05)
        client.MAX_RETRIES = 0
        profile = client.scrape(addr)
        data = profile.to_dict()
        data.pop("raw_api_data", None)
        if _debank_has_data(data):
            data["source_status"] = {
                "source": "prism_direct",
                "ok": True,
                "degraded": False,
                "message": "Fetched with direct public wallet telemetry endpoints.",
                "errors": [],
            }
            return data
        errors.append("direct client returned no usable portfolio data")
    except Exception as exc:
        errors.append(f"direct client failed: {type(exc).__name__}: {exc!r}")

    try:
        data = _debank_browser_subprocess_sync(addr)
        if _debank_has_data(data):
            data["source_status"] = {
                "source": "prism_browser",
                "ok": True,
                "degraded": False,
                "message": "Fetched by rendering public wallet telemetry and collecting profile responses.",
                "errors": errors,
            }
            return data
        errors.append("browser scraper returned no usable portfolio data")
    except Exception as exc:
        errors.append(f"browser scraper failed: {type(exc).__name__}: {exc!r}")

    fallback = _debank_fallback_sync(addr)
    fallback["source_status"] = {
        "source": "identity_lens_fallback",
        "ok": False,
        "degraded": True,
        "message": "Live portfolio telemetry was unavailable; rendered local Identity Lens portfolio instead.",
        "errors": errors,
    }
    return fallback


def _debank_browser_subprocess_sync(addr: str) -> dict[str, Any]:
    """Run Playwright scrape in a clean Python process to avoid Windows thread event-loop failures."""
    with tempfile.NamedTemporaryFile(prefix="debank-profile-", suffix=".json", delete=False) as tmp:
        output_path = tmp.name
    code = r"""
import json
import sys
from pathlib import Path

project_root = Path(sys.argv[1])
address = sys.argv[2]
output_path = Path(sys.argv[3])
sys.path.insert(0, str(project_root))

from debank_scraper import DeBankScraper

scraper = DeBankScraper(headless=True, timeout=30000)
profile = scraper.scrape(address, wait_seconds=8)
data = profile.to_dict()
data.pop("raw_api_data", None)
output_path.write_text(json.dumps(data, default=str), encoding="utf-8")
"""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, _PROJECT_ROOT, addr, output_path],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=105,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-1200:]
            raise RuntimeError(detail or f"subprocess exited with code {completed.returncode}")
        if not os.path.exists(output_path):
            raise RuntimeError("subprocess did not create output file")
        with open(output_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


def _debank_has_data(data: dict[str, Any]) -> bool:
    return bool(
        data.get("total_usd_value")
        or data.get("tokens")
        or data.get("protocols")
        or data.get("chain_balances")
        or data.get("display_name")
        or data.get("web3_id")
    )


def _debank_fallback_sync(addr: str) -> dict[str, Any]:
    """Build a live-portfolio-shaped response from local Identity Lens data."""
    import asyncio as _asyncio

    async def _build() -> dict[str, Any]:
        intel = await _lookup(addr)
        domain_profile, chain_intels = await _asyncio.gather(
            _domain_profile(addr),
            _evm_chain_scan(addr),
        )
        chain = str(intel.get("chain") or intel.get("detected_chain") or "").upper()
        labels = db.labels_for_address((intel.get("address") or addr).strip(), chain)
        profile = build_identity_profile(
            address=addr,
            intel=intel,
            graph={},
            threat={},
            local_labels=labels,
            reverse_name=domain_profile.get("reverse_name") or None,
            domain_profile=domain_profile,
            chain_intels=chain_intels,
        )
        aggregate = profile.get("aggregate_portfolio") or {}
        positions = profile.get("protocol_positions") or []
        chain_rows = aggregate.get("chains") or []
        return {
            "address": addr.lower().strip(),
            "total_usd_value": aggregate.get("total_usd") or (profile.get("portfolio") or {}).get("portfolio_usd") or 0,
            "chain_balances": [
                {
                    "chain_id": str(c.get("chain", "")).lower(),
                    "chain_name": c.get("chain") or "",
                    "logo_url": "",
                    "native_token_id": c.get("native_unit") or "",
                    "wrapped_token_id": "",
                    "usd_value": c.get("portfolio_usd") or 0,
                }
                for c in chain_rows
            ],
            "tokens": [
                {
                    "id": p.get("symbol") or p.get("name") or "",
                    "chain": str(p.get("chain") or "").lower(),
                    "name": p.get("name") or "",
                    "symbol": p.get("symbol") or "",
                    "decimals": 18,
                    "logo_url": "",
                    "price": 0,
                    "amount": p.get("balance") or 0,
                    "raw_amount": 0,
                    "usd_value": p.get("usd_value") or 0,
                    "is_verified": True,
                    "is_core": False,
                    "is_wallet": p.get("type") == "wallet",
                    "protocol_id": None,
                    "credit_score": 0,
                    "price_24h_change": 0,
                    "is_scam": False,
                    "is_suspicious": False,
                }
                for p in positions if p.get("type") in {"token", "wallet"}
            ],
            "protocols": [
                {
                    "protocol_id": p.get("name") or "",
                    "protocol_name": p.get("name") or "",
                    "chain": str(p.get("chain") or "").lower(),
                    "logo_url": "",
                    "site_url": "",
                    "tvl": 0,
                    "asset_usd_value": p.get("usd_value") or 0,
                    "debt_usd_value": 0,
                    "net_usd_value": p.get("usd_value") or 0,
                    "detail_types": [p.get("type") or "position"],
                    "asset_tokens": [],
                }
                for p in positions if p.get("type") not in {"token", "wallet"}
            ],
            "nfts": [],
            "transactions": [],
            "display_name": (profile.get("profile") or {}).get("display_name") or profile.get("likely_entity"),
            "bio": "Fallback profile generated from local Identity Lens evidence because live portfolio telemetry was unavailable.",
            "follower_count": 0,
            "following_count": 0,
            "tags": [{"name": "Identity Lens fallback"}],
            "is_vip": False,
            "is_pro": False,
            "web3_id": (profile.get("profile") or {}).get("username") or profile.get("username"),
            "used_chains": [str(c.get("chain", "")).lower() for c in chain_rows if c.get("active")],
        }

    return _asyncio.run(_build())


@router.get("/identity/debank-status")
async def identity_debank_status() -> dict[str, Any]:
    """Report whether the bundled DeBank scraper is discoverable and importable.
    Use this to confirm the portfolio scraper is wired up (no network call)."""
    scraper_file = os.path.join(_DEBANK_DIR, "debank_scraper.py")
    result: dict[str, Any] = {
        "scraper_dir": _DEBANK_DIR,
        "scraper_found": os.path.isfile(scraper_file),
        "backend_dir": _BACKEND_DIR,
        "module_loadable": False,
        "classes": [],
        "error": "",
    }
    try:
        import debank_scraper
        result["classes"] = [
            name for name in ("DeBankAPIClient", "DeBankScraper", "DeBankProfile")
            if hasattr(debank_scraper, name)
        ]
        result["module_loadable"] = bool(result["classes"])
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


@router.get("/identity/debank/{address}")
async def identity_debank(address: str) -> dict[str, Any]:
    """Fetch live portfolio telemetry, with local fallback if live collection fails."""
    loop = asyncio.get_running_loop()
    try:
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _debank_scrape_sync, address.lower().strip()),
            timeout=120,
        )
    except asyncio.TimeoutError:
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _debank_fallback_sync, address.lower().strip()),
            timeout=80,
        )
        data["source_status"] = {
            "source": "identity_lens_fallback",
            "ok": False,
            "degraded": True,
            "message": "Live portfolio telemetry timed out after 120s; rendered local Identity Lens fallback.",
            "errors": ["live scrape timeout"],
        }
    except Exception as exc:
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _debank_fallback_sync, address.lower().strip()),
            timeout=80,
        )
        data["source_status"] = {
            "source": "identity_lens_fallback",
            "ok": False,
            "degraded": True,
            "message": "Live portfolio telemetry failed; rendered local Identity Lens fallback.",
            "errors": [f"{type(exc).__name__}: {exc!r}"],
        }
    return data


@router.post("/identity/profile")
async def identity_profile(req: IdentityProfileRequest) -> dict[str, Any]:
    address = req.address.strip()
    if not address:
        raise HTTPException(status_code=400, detail="address is required")

    intel = req.intel or {}
    if req.include_lookup and not intel:
        intel = await _lookup(address)

    chain = str(intel.get("chain") or intel.get("detected_chain") or "").upper()
    labels = db.labels_for_address((intel.get("address") or address).strip(), chain)
    domain_profile, chain_intels = await asyncio.gather(
        _domain_profile(address),
        _evm_chain_scan(address),
    )
    reverse = domain_profile.get("reverse_name") or None

    profile = build_identity_profile(
        address=address,
        intel=intel,
        graph=req.graph or {},
        threat=req.threat or {},
        local_labels=labels,
        reverse_name=reverse,
        domain_profile=domain_profile,
        chain_intels=chain_intels,
    )
    return {"identity_profile": profile}
