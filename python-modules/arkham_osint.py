"""
Arkham owner-name attribution adapter (scraper-only, no authentication).

CryptoOSINT imports this module optionally. It wraps the bundled Arkham scraper
(``arkm_scraper.py`` / ``arkm_utils.py``) that now lives inside the tool's
``backend`` folder and exposes a small async API that returns the entity
attribution needed by the app.

This adapter operates entirely without API keys or authentication -- it relies
on public-page scraping only. Arkham gates most entity data behind login walls,
so results are best-effort: when attribution is publicly visible the scraper
will surface it; otherwise it returns ``found=False`` cleanly.

Design goals:
  - Zero configuration. The scraper is located dynamically relative to this
    file and the running backend, so moving the tool to a new device or OS
    requires no environment variables and no code edits.
  - Cross-platform. All paths are resolved with ``pathlib`` from the backend
    folder itself; nothing is hardcoded to a specific user or drive.
  - Optional overrides. ``ARKHAM_SCRAPER_DIR`` is still honoured if set, but it
    is never required.
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

_SCRAPER_MODULE_NAME = "arkm_scraper"
_SCRAPER_FILENAME = "arkm_scraper.py"

_CACHE_TTL = int(os.getenv("ARKHAM_OWNER_CACHE_TTL", "3600") or "3600")
# Arkham is behind Cloudflare; only the stealth browser path reliably gets
# through. The inline lookup is kept short so it never stalls the address page;
# the on-demand deep resolve gets a real budget to wait out the CF challenge.
_LOOKUP_TIMEOUT = int(os.getenv("ARKHAM_OWNER_TIMEOUT", "22") or "22")
_DEEP_TIMEOUT = int(os.getenv("ARKHAM_OWNER_DEEP_TIMEOUT", "95") or "95")
_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

# Cached, resolved location of the folder that contains arkm_scraper.py.
_SCRAPER_DIR: Optional[Path] = None


# ---------------------------------------------------------------------------
# Dynamic, device-independent location of the bundled scraper
# ---------------------------------------------------------------------------
def _candidate_dirs() -> list[Path]:
    """Directories to probe for arkm_scraper.py, most-specific first.

    Everything is derived from this file's location, the current working
    directory, and sys.path -- so it works regardless of the OS, drive letter,
    or user account the tool was copied to.
    """
    here = Path(__file__).resolve()
    repo_root = here.parent.parent            # <repo>/python-modules -> <repo>
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

    # Optional explicit override (not required).
    env_dir = os.getenv("ARKHAM_SCRAPER_DIR", "").strip()
    if env_dir:
        add(Path(env_dir).expanduser())

    # The tool's backend folder -- the expected home of the scraper.
    add(repo_root / "backend")
    add(repo_root.parent / "backend")
    # In case the scraper is dropped next to this adapter or at the repo root.
    add(here.parent)
    add(repo_root)
    # Wherever the process was launched from (uvicorn is usually run in backend).
    add(Path.cwd())
    add(Path.cwd() / "backend")
    # Anything already importable.
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
    """Import the bundled ArkhamScraper module, wherever it lives."""
    # Fast path: already importable (backend dir on sys.path / cwd).
    try:
        return importlib.import_module(_SCRAPER_MODULE_NAME)
    except Exception:
        pass

    scraper_dir = _find_scraper_dir()
    if scraper_dir is None:
        raise FileNotFoundError(
            "arkm_scraper.py not found. Place it (and arkm_utils.py) in the "
            "tool's backend folder. Searched: "
            + ", ".join(str(d) for d in _candidate_dirs()[:8])
        )

    # Make the scraper folder importable so arkm_scraper can pull in arkm_utils.
    if str(scraper_dir) not in sys.path:
        sys.path.insert(0, str(scraper_dir))

    path = scraper_dir / _SCRAPER_FILENAME
    spec = importlib.util.spec_from_file_location(_SCRAPER_MODULE_NAME, path)
    if not spec or not spec.loader:
        raise ImportError(f"Unable to load Arkham scraper from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cookie_jar_path() -> str:
    """Keep cookies alongside the scraper, not in a transient CWD."""
    d = _find_scraper_dir() or Path.cwd()
    return str(d / "arkham_cookies.json")


# ---------------------------------------------------------------------------
# Chain normalisation + result shaping
# ---------------------------------------------------------------------------
def _chain_for_arkham(chain: str) -> str:
    c = (chain or "").strip().lower()
    return {
        "eth": "ethereum",
        "ethereum": "ethereum",
        "btc": "bitcoin",
        "bitcoin": "bitcoin",
        "sol": "solana",
        "solana": "solana",
        "trx": "tron",
        "tron": "tron",
        "matic": "polygon",
        "polygon": "polygon",
        "arb": "arbitrum",
        "arbitrum": "arbitrum",
        "op": "optimism",
        "optimism": "optimism",
        "base": "base",
    }.get(c, c or "ethereum")


def _clean(value: Any) -> str:
    return str(value or "").strip()


# Arkham brand / placeholder strings that must never be reported as an owner.
_GENERIC_NAMES = {
    "none", "unknown", "address", "intel platform", "intel platform | arkham",
    "arkham", "arkham intel", "arkham intel platform", "arkham intelligence",
    "explorer", "intel", "loading", "loading...", "not found", "404",
    "page not found",
}


def _is_generic(value: str) -> bool:
    return not value or value.strip().lower() in _GENERIC_NAMES


def _pick_name(data: dict[str, Any]) -> str:
    for key in ("entity_name", "name", "primary_entity_name", "label", "entity_id"):
        value = _clean(data.get(key))
        if value and not _is_generic(value):
            return value
    labels = data.get("labels") or []
    for label in labels:
        value = _clean(label)
        if value and not _is_generic(value):
            return value
    return ""


def _shape_result(result: Any, chain: str) -> dict[str, Any]:
    """Turn an AddressAttribution (or dict) into the app's arkham payload."""
    if result is None:
        return {"found": False, "name": "", "error": "Arkham name not found"}
    data = result.to_dict() if hasattr(result, "to_dict") else result
    if not isinstance(data, dict):
        return {"found": False, "name": "", "error": "Unexpected scraper result"}

    error = _clean(data.get("error"))
    name = _pick_name(data)
    labels = [l for l in (data.get("labels") or []) if _clean(l)]
    portfolio = data.get("portfolio_usd")

    if not name:
        return {
            "found": False,
            "name": "",
            "error": error or "Arkham name not found",
            "source_url": data.get("source_url"),
        }

    return {
        "found": True,
        "name": name,
        "entity_name": _clean(data.get("entity_name")) or name,
        "entity_id": _clean(data.get("entity_id")),
        "entity_type": _clean(data.get("entity_type")),
        "label": labels[0] if labels else "",
        "labels": labels,
        "label_type": _clean(data.get("entity_type")),
        "tags": [t for t in (data.get("tags") or []) if _clean(t)],
        "is_verified": bool(data.get("is_verified")),
        "confidence": data.get("confidence_score"),
        "portfolio_usd": portfolio,
        "balance_usd": portfolio,
        "chains_seen": [c for c in [_chain_for_arkham(chain)] if c],
        "source_url": data.get("source_url"),
        "scraped_at": data.get("scraped_at"),
    }


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------
def _lookup_sync(address: str, chain: str, deep: bool = False) -> dict[str, Any]:
    """Scrape Arkham public pages for entity attribution (no API, no auth).

    ``deep=False`` (inline): one endpoint, short Cloudflare wait — fast, so it
    can't stall the address page. ``deep=True`` (on-demand): all endpoints and a
    long CF wait so the challenge actually clears and the owner resolves.
    """
    module = _load_module()
    scraper_cls = getattr(module, "ArkhamScraper", None)
    if scraper_cls is None:
        raise AttributeError("ArkhamScraper class not found in arkm_scraper.py")

    # The stealth browser is the only reliable Cloudflare bypass, but it's heavy.
    # Use it only for the deep (on-demand) resolve so the fast inline lookup on
    # the main address page stays snappy; the Attribution Analysis panel triggers
    # the deep pass itself. Set ARKHAM_OWNER_USE_BROWSER=0 to disable it entirely.
    browser_enabled = os.getenv("ARKHAM_OWNER_USE_BROWSER", "1").strip().lower() in {"1", "true", "yes", "on"}
    use_browser = browser_enabled and deep
    scraper_kwargs = dict(
        use_browser=use_browser,
        headless=True,
        rate_limit_delay=float(os.getenv("ARKHAM_OWNER_DELAY", "0.25") or "0.25"),
        cookie_jar=_cookie_jar_path(),
    )
    # These constructor args exist on the enhanced scraper; guard for older ones.
    try:
        scraper = scraper_cls(
            **scraper_kwargs,
            cf_wait_seconds=(30.0 if deep else 8.0),
            max_endpoints=(3 if deep else 1),
        )
    except TypeError:
        scraper = scraper_cls(**scraper_kwargs)
    try:
        result = scraper.scrape_address(address, chain=_chain_for_arkham(chain))
        return _shape_result(result, chain)
    finally:
        try:
            scraper.close()
        except Exception:
            pass


async def lookup_address(address: str, chain: str = "", deep: bool = False) -> dict[str, Any]:
    """Return Arkham entity attribution for an address (owner name + context).

    ``deep=False`` is the fast inline path used by the main address lookup;
    ``deep=True`` enables the full Cloudflare-solving browser path and is used by
    the on-demand "resolve owner" endpoint behind the Intelligence-tab card.
    """
    addr = (address or "").strip()
    if not addr:
        return {"found": False, "name": "", "error": "address is required"}

    ch = _chain_for_arkham(chain)
    key = (ch, addr.lower() + (":deep" if deep else ":fast"))
    cached = _CACHE.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    timeout = _DEEP_TIMEOUT if deep else _LOOKUP_TIMEOUT
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_lookup_sync, addr, chain, deep),
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        result = {"found": False, "name": "", "error": f"Arkham lookup failed: {type(exc).__name__}: {exc}"}

    # Cache hits (and clean "no attribution" results), but never cache a transient
    # error/timeout — otherwise one Cloudflare block hides the owner for an hour.
    if result.get("found") or not result.get("error"):
        _CACHE[key] = (time.time(), result)
    # A found fast result also satisfies a later deep request.
    if result.get("found"):
        _CACHE[(ch, addr.lower() + ":deep")] = (time.time(), result)
    return result


def format_arkham_section_html(arkham: Optional[dict[str, Any]]) -> str:
    if not arkham or not arkham.get("found") or not arkham.get("name"):
        return ""
    name = arkham.get("name")
    label = arkham.get("label")
    if label and label != name:
        return f"<b>Arkham owner:</b> <code>{name}</code> ({label})"
    return f"<b>Arkham owner:</b> <code>{name}</code>"


def scraper_diagnostics() -> dict[str, Any]:
    """Lightweight status probe for health checks / debugging (no network)."""
    scraper_dir = _find_scraper_dir()
    module_ok = False
    error = ""
    try:
        module = _load_module()
        module_ok = getattr(module, "ArkhamScraper", None) is not None
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    return {
        "scraper_dir": str(scraper_dir) if scraper_dir else None,
        "scraper_found": scraper_dir is not None,
        "module_loadable": module_ok,
        "cookie_jar": _cookie_jar_path(),
        "error": error,
        "mode": "anonymous_scrape",
    }
