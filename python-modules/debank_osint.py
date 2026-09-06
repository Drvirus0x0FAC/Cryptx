"""
DeBank owner-name / profile attribution adapter.

CryptoOSINT imports this module optionally. It wraps the bundled DeBank scraper
(``debank_scraper.py``) that lives inside the tool's ``backend`` folder and
exposes a small async API that returns the display name + portfolio context.

Design goals:
  - Zero configuration. The scraper is located dynamically.
  - Cross-platform. All paths are resolved with ``pathlib``.
  - Optional overrides. ``DEBANK_SCRAPER_DIR`` is honoured if set.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

_SCRAPER_MODULE_NAME = "debank_scraper"
_SCRAPER_FILENAME = "debank_scraper.py"

_CACHE_TTL = int(os.getenv("DEBANK_OWNER_CACHE_TTL", "1800") or "1800")
# Fast (inline) budget — direct API only, must not block the main address
# lookup. Deep budget — allows the headless-browser fallback to render.
_LOOKUP_TIMEOUT = int(os.getenv("DEBANK_OWNER_TIMEOUT", "15") or "15")
_DEEP_TIMEOUT = int(os.getenv("DEBANK_OWNER_DEEP_TIMEOUT", "100") or "100")
_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

_SCRAPER_DIR: Optional[Path] = None


def _candidate_dirs() -> list[Path]:
    """Directories to probe for debank_scraper.py, most-specific first."""
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    seen: set[str] = set()
    dirs: list[Path] = []

    def add(p: Optional[Path]) -> None:
        if not p:
            return
        try:
            rp = p.resolve()
        except Exception:
            return
        key = str(rp).lower()
        if key not in seen:
            seen.add(key)
            dirs.append(rp)

    env_dir = os.getenv("DEBANK_SCRAPER_DIR", "").strip()
    if env_dir:
        add(Path(env_dir).expanduser())

    add(repo_root / "backend")
    add(repo_root.parent / "backend")
    add(here.parent)
    add(repo_root)
    add(Path.cwd())
    add(Path.cwd() / "backend")
    for entry in list(sys.path):
        if entry:
            add(Path(entry))

    return dirs


def _find_scraper_dir() -> Optional[Path]:
    global _SCRAPER_DIR
    if _SCRAPER_DIR and (_SCRAPER_DIR / _SCRAPER_FILENAME).exists():
        return _SCRAPER_DIR
    for d in _candidate_dirs():
        if (d / _SCRAPER_FILENAME).exists():
            _SCRAPER_DIR = d
            return d
    return None


def _load_module():
    """Import the bundled DeBank scraper module."""
    try:
        return importlib.import_module(_SCRAPER_MODULE_NAME)
    except Exception:
        pass

    scraper_dir = _find_scraper_dir()
    if scraper_dir is None:
        raise FileNotFoundError(
            "debank_scraper.py not found. Place it in the tool's backend folder."
        )

    if str(scraper_dir) not in sys.path:
        sys.path.insert(0, str(scraper_dir))

    path = scraper_dir / _SCRAPER_FILENAME
    spec = importlib.util.spec_from_file_location(_SCRAPER_MODULE_NAME, path)
    if not spec or not spec.loader:
        raise ImportError(f"Unable to load DeBank scraper from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _shape_result(profile: Any) -> dict[str, Any]:
    """Turn a DeBankProfile into a standard OSINT payload."""
    if profile is None:
        return {"found": False, "name": "", "error": "DeBank profile not found"}

    data = profile.to_dict() if hasattr(profile, "to_dict") else profile
    if not isinstance(data, dict):
        return {"found": False, "name": "", "error": "Unexpected DeBank result"}

    name = (data.get("display_name") or "").strip()
    web3_id = (data.get("web3_id") or "").strip()
    # Prefer the scraper's composite owner_name (display name → web3 id → first
    # descriptive tag), falling back to the raw fields for older payloads.
    effective_name = (data.get("owner_name") or "").strip() or name or web3_id

    if not effective_name:
        return {
            "found": False,
            "name": "",
            "error": "DeBank profile has no display name",
            "source_url": f"https://debank.com/profile/{data.get('address', '')}",
        }

    # Associated wallet balances / portfolio breakdown (screenshot-style).
    def _num(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    tokens = []
    for t in (data.get("tokens") or []):
        usd = _num(t.get("usd_value"))
        tokens.append({
            "symbol": (t.get("symbol") or t.get("name") or "").strip(),
            "name": (t.get("name") or "").strip(),
            "chain": (t.get("chain") or "").strip(),
            "price": _num(t.get("price")),
            "amount": _num(t.get("amount")),
            "usd_value": usd,
            "logo_url": t.get("logo_url") or "",
            "is_wallet": bool(t.get("is_wallet")),
            "protocol_id": t.get("protocol_id") or None,
            "is_scam": bool(t.get("is_scam")),
            "is_suspicious": bool(t.get("is_suspicious")),
        })
    tokens.sort(key=lambda x: x["usd_value"], reverse=True)

    chains = []
    for c in (data.get("chain_balances") or []):
        cv = _num(c.get("usd_value"))
        chains.append({
            "chain_id": c.get("chain_id") or "",
            "chain_name": c.get("chain_name") or c.get("chain_id") or "",
            "usd_value": cv,
            "logo_url": c.get("logo_url") or "",
        })
    chains.sort(key=lambda x: x["usd_value"], reverse=True)

    protocols = []
    for p in (data.get("protocols") or []):
        protocols.append({
            "name": p.get("protocol_name") or p.get("protocol_id") or "",
            "chain": p.get("chain") or "",
            "net_usd_value": _num(p.get("net_usd_value")),
            "asset_usd_value": _num(p.get("asset_usd_value")),
            "debt_usd_value": _num(p.get("debt_usd_value")),
            "logo_url": p.get("logo_url") or "",
            "site_url": p.get("site_url") or "",
            "detail_types": p.get("detail_types") or [],
        })
    protocols.sort(key=lambda x: x["net_usd_value"], reverse=True)

    total_usd = _num(data.get("total_usd_value"))

    return {
        "found": True,
        "name": effective_name,
        "display_name": name,
        "web3_id": web3_id,
        "bio": data.get("bio", ""),
        "follower_count": data.get("follower_count", 0),
        "following_count": data.get("following_count", 0),
        "is_vip": data.get("is_vip", False),
        "is_pro": data.get("is_pro", False),
        "total_usd_value": total_usd,
        "portfolio_usd": total_usd,
        "used_chains": data.get("used_chains", []),
        "chain_count": len(chains),
        "token_count": len(tokens),
        "protocol_count": len(protocols),
        "nft_count": len(data.get("nfts", [])),
        # Detailed associated balances (used by the Attribution Analysis panel).
        "tokens": tokens,
        "chains": chains,
        "protocols": protocols,
        "source_url": f"https://debank.com/profile/{data.get('address', '')}",
        "source": "debank",
    }


def _browser_subprocess(address: str) -> dict[str, Any]:
    """Render the DeBank profile in a headless browser (separate process) and
    read the intercepted ``/user`` payload. DeBank now gates api.debank.com
    behind a signed session header, so the direct API returns nothing for most
    addresses — the browser path is what actually surfaces the owner name.

    A subprocess is used (not a thread) because sync Playwright cannot start
    inside a thread that already has an asyncio loop on Windows.
    """
    import json
    import subprocess
    import tempfile

    scraper_dir = _find_scraper_dir()
    if scraper_dir is None:
        raise FileNotFoundError("debank_scraper.py not found for browser fallback")

    with tempfile.NamedTemporaryFile(prefix="debank-owner-", suffix=".json", delete=False) as tmp:
        out_path = tmp.name
    code = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1])))
from debank_scraper import DeBankScraper
prof = DeBankScraper(headless=True, timeout=30000).scrape(sys.argv[2], wait_seconds=8)
data = prof.to_dict()
data.pop("raw_api_data", None)
Path(sys.argv[3]).write_text(json.dumps(data, default=str), encoding="utf-8")
"""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, str(scraper_dir), address, out_path],
            cwd=str(scraper_dir),
            capture_output=True,
            text=True,
            timeout=int(os.getenv("DEBANK_BROWSER_TIMEOUT", "95") or "95"),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not os.path.exists(out_path):
            detail = (completed.stderr or completed.stdout or "").strip()[-600:]
            raise RuntimeError(detail or f"browser subprocess exit {completed.returncode}")
        with open(out_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def _lookup_sync(address: str, deep: bool = False) -> dict[str, Any]:
    """Resolve a DeBank owner name.

    ``deep=False`` (inline, used by the main address lookup): direct API only —
    fast, never spawns a browser, so it can't stall the page load.
    ``deep=True`` (on-demand card refresh): adds the headless-browser fallback,
    the reliable no-auth path for the owner name now that DeBank gates its API.
    """
    module = _load_module()
    client_cls = getattr(module, "DeBankAPIClient", None)
    if client_cls is None:
        raise AttributeError("DeBankAPIClient class not found in debank_scraper.py")

    errors: list[str] = []

    # 1) Fast path — direct public API (works when not session-gated).
    try:
        client = client_cls(rate_limit=0.5)
        try:
            client.MAX_RETRIES = 0
        except Exception:  # noqa: BLE001
            pass
        result = _shape_result(client.scrape(address))
        if result.get("found"):
            result["source"] = "debank_api"
            return result
        errors.append("direct API returned no display name")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"direct API failed: {type(exc).__name__}: {exc}")

    # 2) Browser fallback (deep only) — reliable no-auth path for the owner name.
    use_browser = os.getenv("DEBANK_OWNER_USE_BROWSER", "1").strip().lower() in {"1", "true", "yes", "on"}
    if deep and use_browser:
        try:
            result = _shape_result(_browser_subprocess(address))
            if result.get("found"):
                result["source"] = "debank_browser"
                return result
            errors.append("browser returned no display name")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"browser failed: {type(exc).__name__}: {exc}")

    return {
        "found": False,
        "name": "",
        "error": "; ".join(errors) or "DeBank profile not found",
        "source_url": f"https://debank.com/profile/{address}",
        "deep_available": not deep,  # hint to UI that a deeper lookup is possible
    }


async def lookup_address(address: str, chain: str = "", deep: bool = False) -> dict[str, Any]:
    """Return DeBank profile attribution for an address (owner name + portfolio).

    ``deep=False`` is the fast inline path used by the main address lookup;
    ``deep=True`` enables the browser fallback and is used by the on-demand
    "resolve owner" endpoint behind the Intelligence-tab card.
    """
    addr = (address or "").strip()
    if not addr:
        return {"found": False, "name": "", "error": "address is required"}

    key = (addr.lower(), "deep" if deep else "fast")
    cached = _CACHE.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    timeout = _DEEP_TIMEOUT if deep else _LOOKUP_TIMEOUT
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_lookup_sync, addr, deep),
            timeout=timeout,
        )
    except Exception as exc:
        result = {"found": False, "name": "", "error": f"DeBank lookup failed: {type(exc).__name__}: {exc}"}

    # Cache successes and clean "no profile" results; skip transient errors so a
    # deep retry can still succeed.
    if result.get("found") or not result.get("error"):
        _CACHE[key] = (time.time(), result)
    # A found fast result also satisfies a deep request.
    if result.get("found"):
        _CACHE[(addr.lower(), "deep")] = (time.time(), result)
    return result


def format_debank_section_html(debank: Optional[dict[str, Any]]) -> str:
    if not debank or not debank.get("found") or not debank.get("name"):
        return ""
    name = debank.get("name")
    bio = debank.get("bio", "")
    portfolio = debank.get("portfolio_usd", 0)
    parts = [f"<b>DeBank owner:</b> <code>{name}</code>"]
    if bio:
        parts.append(f"<i>{bio[:100]}</i>")
    if portfolio:
        parts.append(f"Portfolio: <code>${float(portfolio):,.2f}</code>")
    return "\n".join(parts)


def scraper_diagnostics() -> dict[str, Any]:
    """Lightweight status probe for health checks / debugging (no network)."""
    scraper_dir = _find_scraper_dir()
    module_ok = False
    error = ""
    try:
        module = _load_module()
        module_ok = getattr(module, "DeBankAPIClient", None) is not None
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "scraper_dir": str(scraper_dir) if scraper_dir else None,
        "scraper_found": scraper_dir is not None,
        "module_loadable": module_ok,
        "error": error,
        "mode": "debank_api",
    }
