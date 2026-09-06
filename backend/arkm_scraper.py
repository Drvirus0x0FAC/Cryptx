#!/usr/bin/env python3
"""
Arkham Intelligence (arkm.com) Crypto Address Attribution Scraper
===============================================================
A comprehensive, no-API-key scraper for extracting crypto address attribution
data from Arkham Intelligence's web platform.

Features:
- Cloudflare bypass via Scrapling (stealth Playwright) + undetected-chromedriver fallback
- Address-to-entity attribution extraction
- Entity profile scraping (portfolio, labels, tags)
- Batch processing with rate limiting
- Proxy support
- Structured JSON/CSV output
- Automatic retry with exponential backoff

Requirements:
    pip install scrapling requests beautifulsoup4 lxml
    pip install undetected-chromedriver selenium webdriver-manager  # fallback only

Usage:
    python arkm_scraper.py --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045
    python arkm_scraper.py --entity binance
    python arkm_scraper.py --batch addresses.txt --output results.json
"""

import argparse
import json
import csv
import time
import re
import sys
import os
import random
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from dataclasses import dataclass, asdict, field
from urllib.parse import urljoin, quote
from datetime import datetime, timezone

# Third-party imports
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# === Scrapling (Primary stealth engine) ===
try:
    from scrapling import StealthyFetcher, Fetcher
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False
    StealthyFetcher = None
    Fetcher = None

# === Playwright (Direct stealth fallback) ===
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None

# === undetected-chromedriver (Fallback) ===
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, WebDriverException, NoSuchElementException
    )
except ImportError:
    uc = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('arkm_scraper.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

BASE_URL = "https://arkm.com"
INTEL_URL = "https://intel.arkm.com"
ARKM_URL = "https://arkm.com"
PLATFORM_URL = "https://platform.arkhamintelligence.com"
API_BASE = "https://api.arkhamintelligence.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Cache-Control": "max-age=0",
}

GRAPHQL_HEADERS = {
    **HEADERS,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

KNOWN_ENTITY_SLUGS = [
    "binance", "coinbase", "kraken", "okx", "bybit", "bitfinex", "huobi",
    "kucoin", "gate-io", "mexc", "cryptocom", "blockfi", "celsius",
    "vitalik-buterin", "arthur-hayes", "sbf", "jump-trading", "wintermute",
    "alameda-research", "three-arrows-capital", "ftx", "celsius-network",
    "luna-foundation-guard", "tether", "circle", "makerdao", "aave",
    "uniswap", "compound", "lido", "stargate", "opensea", "blur",
    "looksrare", "nansen", "arkham", "chainalysis", "elliptic",
    "mt-gox", "mt-gox-trustee", "silk-road", "silk-road-hacker",
    "plus-token", "onecoin", "bitconnect", "arb-hacker", "nomad-hacker",
    "ronin-hacker", "wormhole-hacker", "poly-network-hacker",
]

# Generic / brand strings that appear in Arkham's page <title>, og:title and
# chrome regardless of which address is being viewed. These must NEVER be
# treated as an entity attribution — doing so mislabels every address as
# "Intel Platform".
GENERIC_ENTITY_NAMES = {
    "intel platform",
    "intel platform | arkham",
    "arkham",
    "arkham intel",
    "arkham intel platform",
    "arkham intelligence",
    "arkham - blockchain analytics platform",
    "explorer",
    "intel",
    "address",
    "unknown",
    "loading",
    "loading...",
    "not found",
    "404",
    "page not found",
}


def _is_generic_entity_name(text: str) -> bool:
    """True if the text is an Arkham brand/placeholder string, not a real owner."""
    if not text:
        return True
    t = re.sub(r"\s+", " ", text).strip().lower()
    if t in GENERIC_ENTITY_NAMES:
        return True
    # "... | Arkham" brand suffix with nothing meaningful in front.
    if t.endswith("| arkham") and t.split("|")[0].strip() in GENERIC_ENTITY_NAMES:
        return True
    return False


def _is_likely_entity_name(text: str) -> bool:
    """Return True if text looks like a real entity name (not generic/address/number)."""
    if not text:
        return False
    t = text.strip()
    if len(t) < 2 or len(t) > 120:
        return False
    if _is_generic_entity_name(t):
        return False
    # Reject strings that are just numbers/currency values
    cleaned = t.replace(".", "").replace(",", "").replace("$", "").replace(" ", "").replace("-", "")
    if cleaned.isdigit():
        return False
    return True

# =============================================================================
# Data Models
# =============================================================================

@dataclass
class AddressAttribution:
    """Represents the attribution data for a single crypto address."""
    address: str
    chain: str = "ethereum"
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    is_verified: bool = False
    confidence_score: Optional[float] = None
    portfolio_usd: Optional[float] = None
    related_addresses: List[str] = field(default_factory=list)
    source_url: Optional[str] = None
    scraped_at: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EntityProfile:
    """Represents an entity profile from Arkham."""
    entity_id: str
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    twitter: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    addresses: List[Dict[str, Any]] = field(default_factory=list)
    portfolio_usd: Optional[float] = None
    portfolio_by_chain: Dict[str, float] = field(default_factory=dict)
    top_tokens: List[Dict[str, Any]] = field(default_factory=list)
    top_counterparties: List[Dict[str, Any]] = field(default_factory=list)
    source_url: Optional[str] = None
    scraped_at: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# HTTP Session Manager
# =============================================================================

class ArkhamSession:
    """Manages HTTP sessions with retry logic and session persistence."""

    def __init__(self, proxy: Optional[str] = None, cookie_jar: Optional[str] = None):
        self.proxy = proxy
        self.cookie_jar = cookie_jar or "arkham_cookies.json"
        self.session = None
        self._init_session()

    def _init_session(self):
        if requests is None:
            logger.error("requests library not installed")
            return

        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        retry_strategy = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        if self.proxy:
            self.session.proxies.update({
                "http": self.proxy,
                "https": self.proxy,
            })
            logger.info(f"Using proxy: {self.proxy}")

        if os.path.exists(self.cookie_jar):
            try:
                with open(self.cookie_jar, 'r') as f:
                    cookies = json.load(f)
                self.session.cookies.update(cookies)
                logger.info(f"Loaded cookies from {self.cookie_jar}")
            except Exception as e:
                logger.warning(f"Failed to load cookies: {e}")

    def save_cookies(self):
        if self.session:
            try:
                with open(self.cookie_jar, 'w') as f:
                    json.dump(dict(self.session.cookies), f)
            except Exception as e:
                logger.warning(f"Failed to save cookies: {e}")

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        if not self.session:
            return None
        try:
            resp = self.session.get(url, timeout=30, **kwargs)
            self.save_cookies()
            return resp
        except Exception as e:
            logger.error(f"GET request failed: {url} - {e}")
            return None

    def post(self, url: str, **kwargs) -> Optional[requests.Response]:
        if not self.session:
            return None
        try:
            resp = self.session.post(url, timeout=30, **kwargs)
            self.save_cookies()
            return resp
        except Exception as e:
            logger.error(f"POST request failed: {url} - {e}")
            return None

    def close(self):
        self.save_cookies()
        if self.session:
            self.session.close()


# =============================================================================
# Browser Automation (Cloudflare Bypass)
# =============================================================================

class ArkhamBrowser:
    """Headless browser wrapper using undetected-chromedriver for Cloudflare bypass."""

    def __init__(self, headless: bool = True, proxy: Optional[str] = None):
        self.headless = headless
        self.proxy = proxy
        self.driver = None
        self._init_driver()

    def _init_driver(self):
        if uc is None:
            logger.error("undetected-chromedriver not installed. Run: pip install undetected-chromedriver")
            return

        options = uc.ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-infobars")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")

        if self.proxy:
            options.add_argument(f"--proxy-server={self.proxy}")

        try:
            self.driver = uc.Chrome(options=options, version_main=None)
            self.driver.set_page_load_timeout(60)
            logger.info("Browser initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            self.driver = None

    def get_page_source(self, url: str, wait_for: Optional[str] = None, timeout: int = 30) -> Optional[str]:
        if not self.driver:
            logger.error("Browser not initialized")
            return None

        try:
            logger.info(f"Navigating to: {url}")
            self.driver.get(url)

            time.sleep(random.uniform(4, 7))

            if "cloudflare" in self.driver.page_source.lower() or "challenge" in self.driver.page_source.lower():
                logger.warning("Cloudflare challenge detected, waiting longer...")
                time.sleep(random.uniform(8, 15))

            if wait_for:
                try:
                    WebDriverWait(self.driver, timeout).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, wait_for))
                    )
                except TimeoutException:
                    logger.warning(f"Timeout waiting for element: {wait_for}")

            return self.driver.page_source

        except Exception as e:
            logger.error(f"Browser navigation failed: {url} - {e}")
            return None

    def get_element_text(self, selector: str) -> Optional[str]:
        if not self.driver:
            return None
        try:
            elem = self.driver.find_element(By.CSS_SELECTOR, selector)
            return elem.text.strip()
        except NoSuchElementException:
            return None
        except Exception as e:
            logger.error(f"Error getting element text: {e}")
            return None

    def get_elements(self, selector: str) -> List[Any]:
        if not self.driver:
            return []
        try:
            return self.driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception as e:
            logger.error(f"Error getting elements: {e}")
            return []

    def execute_script(self, script: str, *args) -> Any:
        if not self.driver:
            return None
        try:
            return self.driver.execute_script(script, *args)
        except Exception as e:
            logger.error(f"Script execution failed: {e}")
            return None

    def get_network_logs(self) -> List[Dict[str, Any]]:
        logs = []
        if not self.driver:
            return logs
        try:
            logs_raw = self.driver.get_log("performance")
            for entry in logs_raw:
                message = json.loads(entry.get("message", "{}"))
                if "Network.response" in message.get("message", {}).get("method", ""):
                    logs.append(message)
        except Exception as e:
            logger.debug(f"Network log capture failed: {e}")
        return logs

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Browser closed")
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# =============================================================================
# Core Scraper
# =============================================================================

class ArkhamScraper:
    """Main scraper for Arkham Intelligence crypto address attribution."""

    def __init__(
        self,
        use_browser: bool = True,
        headless: bool = True,
        proxy: Optional[str] = None,
        rate_limit_delay: float = 2.0,
        cookie_jar: Optional[str] = None,
        cf_wait_seconds: float = 30.0,
        max_endpoints: int = 3,
    ):
        self.use_browser = use_browser
        self.headless = headless
        self.proxy = proxy
        self.rate_limit_delay = rate_limit_delay
        self.cookie_jar = cookie_jar or "arkham_cookies.json"
        # How long a single Playwright fetch will wait for Cloudflare's JS
        # challenge to clear, and how many Arkham endpoints to try. Kept small for
        # the fast inline lookup and large for the on-demand deep resolve.
        self.cf_wait_seconds = cf_wait_seconds
        self.max_endpoints = max(1, int(max_endpoints))
        self.session = ArkhamSession(proxy=proxy, cookie_jar=cookie_jar)
        self.browser = None
        self._last_request_time = 0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - elapsed + random.uniform(0.5, 1.5)
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _ensure_browser(self):
        if self.use_browser and self.browser is None:
            self.browser = ArkhamBrowser(headless=self.headless, proxy=self.proxy)
            if self.browser.driver is None:
                logger.warning("Browser initialization failed, falling back to HTTP only")
                self.use_browser = False

    def _is_cloudflare_block(self, html: str) -> bool:
        """Detect a genuine Cloudflare interstitial/challenge page.

        Deliberately strict: legit Arkham pages ship Cloudflare scripts and a
        ``<noscript>please enable JavaScript</noscript>`` shell, so matching on
        generic words like "cloudflare", "ray id" or "please enable javascript"
        produced false positives that made every fetch look blocked. We only flag
        the real challenge markers here.
        """
        if not html:
            return True
        h = html.lower()
        strong = [
            "just a moment...",
            "cf-chl-",              # challenge asset URLs
            "challenge-platform",
            "cf-captcha-container",
            "cf-turnstile",
            "_cf_chl_opt",
            "checking your browser before accessing",
            "attention required! | cloudflare",
            "cf-error-details",
            "cf-mitigated",
        ]
        return any(ind in h for ind in strong)

    def _extract_json_from_page(self, html: str) -> List[Dict[str, Any]]:
        data = []
        next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if next_data_match:
            try:
                next_data = json.loads(next_data_match.group(1))
                data.append({"source": "__NEXT_DATA__", "data": next_data})
            except json.JSONDecodeError:
                pass

        for pattern in [
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r'window\.__DATA__\s*=\s*({.*?});',
            r'"props":\s*({.*?"pageProps":.*?})\s*,\s*"page"',
        ]:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                    data.append({"source": "script_data", "data": parsed})
                except (json.JSONDecodeError, IndexError):
                    continue
        return data

    def _clean_text(self, text: str) -> str:
        return re.sub(r'\s+', ' ', text).strip() if text else ""

    def _deep_extract_entity(self, obj: Any, depth: int = 0) -> Dict[str, Any]:
        """Recursively walk any embedded JSON blob and pull the owner/entity
        attribution out of it, wherever Arkham nested it. Arkham keeps changing
        the exact path (``addressIntel.arkhamEntity``, ``data.entity``,
        ``arkhamLabel``…), so instead of hard-coding paths we look for any dict
        that carries an entity-shaped ``name``/``id`` pair.

        Returns a dict with any of: entity_id, entity_name, entity_type,
        is_verified, portfolio_usd, confidence — only keys we actually found.
        """
        found: Dict[str, Any] = {}
        if depth > 12 or obj is None:
            return found

        if isinstance(obj, dict):
            # An "entity-shaped" node: has a human name plus an id/slug/type.
            keys = set(obj.keys())
            name_val = obj.get("name") or obj.get("label") or obj.get("displayName")
            looks_like_entity = bool(name_val) and bool(
                keys & {"id", "slug", "type", "entityType", "isVerified", "twitter", "website"}
            )
            # Explicit Arkham entity containers always win.
            container = None
            for k in ("arkhamEntity", "entity", "arkhamLabel", "owner", "populatedTags"):
                if isinstance(obj.get(k), dict):
                    container = obj[k]
                    break

            target = container or (obj if looks_like_entity else None)
            if target and isinstance(target, dict):
                cand_name = (
                    target.get("name") or target.get("label") or target.get("displayName")
                )
                if _is_likely_entity_name(cand_name):
                    found["entity_name"] = self._clean_text(cand_name)
                    found["entity_id"] = target.get("id") or target.get("slug") or found.get("entity_id")
                    found["entity_type"] = target.get("type") or target.get("entityType") or found.get("entity_type")
                    if target.get("isVerified") is not None:
                        found["is_verified"] = bool(target.get("isVerified"))

            # Portfolio / confidence live alongside the entity, grab opportunistically.
            for pk in ("portfolioUsd", "netWorth", "balanceUsd", "usdValue"):
                if isinstance(obj.get(pk), (int, float)) and "portfolio_usd" not in found:
                    found["portfolio_usd"] = float(obj[pk])
            if isinstance(obj.get("confidence"), (int, float)) and "confidence" not in found:
                found["confidence"] = float(obj["confidence"])

            # Recurse; a better-corroborated name deeper in the tree can fill gaps
            # but never overwrites a name we already trust.
            for v in obj.values():
                child = self._deep_extract_entity(v, depth + 1)
                for ck, cv in child.items():
                    found.setdefault(ck, cv)
            return found

        if isinstance(obj, list):
            for item in obj:
                child = self._deep_extract_entity(item, depth + 1)
                for ck, cv in child.items():
                    found.setdefault(ck, cv)
        return found

    def _extract_meta_tags(self, soup) -> dict:
        """Extract og:title, twitter:title, description, og:description from soup."""
        meta = {}
        if not soup:
            return meta
        for prop, key in [
            ("og:title", "og_title"),
            ("twitter:title", "twitter_title"),
            ("og:description", "og_description"),
            ("description", "description"),
        ]:
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag:
                meta[key] = tag.get("content", "").strip()
        return meta

    def _parse_address_page(self, html: str, address: str, chain: str, url: str) -> AddressAttribution:
        result = AddressAttribution(address=address, chain=chain, source_url=url)

        if not html or self._is_cloudflare_block(html):
            result.error = "Cloudflare block or empty response"
            return result

        soup = BeautifulSoup(html, 'lxml') if BeautifulSoup else None
        if not soup:
            result.error = "BeautifulSoup not available"
            return result

        meta = self._extract_meta_tags(soup)

        # Priority 1: __NEXT_DATA__ embedded JSON with arkhamEntity.name
        embedded_data = self._extract_json_from_page(html)
        for item in embedded_data:
            data = item.get("data", {})
            props = data.get("props", {}).get("pageProps", {}) if isinstance(data, dict) else {}
            if not props and isinstance(data, dict):
                props = data

            intel = props.get("addressIntel") or props.get("addressData") or props.get("data", {})
            if intel:
                entity = intel.get("arkhamEntity") or intel.get("entity")
                if entity:
                    result.entity_id = entity.get("id") or entity.get("slug")
                    result.entity_name = entity.get("name") or entity.get("label")
                    result.entity_type = entity.get("type")
                    result.is_verified = entity.get("isVerified", False)

                labels = intel.get("labels") or intel.get("tags", [])
                if labels:
                    result.labels = [l.get("name", l) if isinstance(l, dict) else l for l in labels]

                result.confidence_score = intel.get("confidence")
                result.portfolio_usd = intel.get("portfolioUsd") or intel.get("netWorth")

        # Priority 1.5: Deep recursive walk of every embedded JSON blob. This is
        # the most reliable path because it doesn't depend on Arkham keeping the
        # entity at a fixed key path.
        if not result.entity_name:
            for item in embedded_data:
                deep = self._deep_extract_entity(item.get("data"))
                if deep.get("entity_name"):
                    result.entity_name = deep["entity_name"]
                    result.entity_id = result.entity_id or deep.get("entity_id")
                    result.entity_type = result.entity_type or deep.get("entity_type")
                    if deep.get("is_verified") is not None:
                        result.is_verified = deep["is_verified"]
                    if result.portfolio_usd is None and deep.get("portfolio_usd") is not None:
                        result.portfolio_usd = deep["portfolio_usd"]
                    if result.confidence_score is None and deep.get("confidence") is not None:
                        result.confidence_score = deep["confidence"]
                    break

        # Reject any brand/placeholder name that slipped in from embedded JSON.
        if result.entity_name and not _is_likely_entity_name(result.entity_name):
            result.entity_name = None

        # Priority 2: Meta tags (og:title, twitter:title) with non-generic text
        if not result.entity_name:
            for meta_key in ("og_title", "twitter_title"):
                val = meta.get(meta_key, "")
                if val:
                    # Strip "Arkham" suffix if present
                    val = re.sub(r'\s*\|\s*Arkham.*$', '', val, flags=re.IGNORECASE).strip()
                    if _is_likely_entity_name(val):
                        result.entity_name = val
                        break

        # Priority 3: Entity links /explorer/entity/<slug> with actual display text
        if not result.entity_name:
            for selector in [
                'a[href*="/explorer/entity/"]',
                'a[href^="/explorer/entity/"]',
            ]:
                for elem in soup.select(selector):
                    href = elem.get("href", "")
                    match = re.search(r'/explorer/entity/([^/"\'?#]+)', href)
                    if not match:
                        continue
                    slug = match.group(1)
                    if slug and not result.entity_id:
                        result.entity_id = slug
                    name_text = self._clean_text(elem.get_text())
                    if _is_likely_entity_name(name_text) and name_text.lower() != address.lower():
                        result.entity_name = name_text
                        break
                if result.entity_name:
                    break

        # Priority 4: Page title (split on | and :)
        if not result.entity_name:
            title_tag = soup.find("title")
            if title_tag:
                match = re.search(r'^(.*?)(?:\s*\|\s*Arkham|$)', title_tag.get_text())
                if match:
                    title_part = match.group(1).strip()
                    if ':' in title_part:
                        title_part = title_part.split(':')[0].strip()
                    if _is_likely_entity_name(title_part):
                        result.entity_name = title_part

        # Priority 5: JSON-LD / structured data
        if not result.entity_name:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    ld = json.loads(script.string or "")
                    if isinstance(ld, dict):
                        name = ld.get("name") or ld.get("alternateName")
                        if _is_likely_entity_name(name):
                            result.entity_name = name
                            break
                except Exception:
                    pass
            # Also search raw HTML for entity name patterns near arkhamEntity
            if not result.entity_name:
                m = re.search(r'"name"\s*:\s*"([^"]{2,80})"', html)
                if m:
                    candidate = m.group(1)
                    if _is_likely_entity_name(candidate):
                        result.entity_name = candidate

        # Priority 6: Any <h1> that contains a known entity pattern
        if not result.entity_name:
            h1 = soup.find("h1")
            if h1:
                text = self._clean_text(h1.get_text())
                if ':' in text:
                    text = text.split(':')[0].strip()
                if _is_likely_entity_name(text) and text.lower() != address.lower():
                    result.entity_name = text

        # Guarded slug-derived name: only use if slug appears corroborated in page text
        if not result.entity_name and result.entity_id:
            pretty = result.entity_id.replace("-", " ").replace("_", " ").strip()
            # Corroboration check: slug text must appear in title, meta, or h1
            corroborated = False
            page_text = " ".join([
                soup.find("title").get_text() if soup.find("title") else "",
                meta.get("og_title", ""),
                meta.get("twitter_title", ""),
                meta.get("description", ""),
                meta.get("og_description", ""),
                soup.find("h1").get_text() if soup.find("h1") else "",
            ]).lower()
            if pretty.lower() in page_text or result.entity_id.lower() in page_text:
                corroborated = True
            if corroborated and pretty and _is_likely_entity_name(pretty):
                result.entity_name = pretty.title()

        # Extract labels/tags from badges (always, independent of entity name).
        for selector in [
            '[class*="tag"]',
            '[class*="badge"]',
            '[class*="Tag"]',
            '[class*="Badge"]',
            '[class*="label"]',
        ]:
            elems = soup.select(selector)
            for elem in elems:
                text = self._clean_text(elem.get_text())
                if text and len(text) < 50 and text not in result.labels and text != address:
                    # Filter out currency/number-only labels
                    if not text.replace('.', '').replace(',', '').replace('$', '').replace(' ', '').replace('-', '').isdigit():
                        result.labels.append(text)

        result.labels = list(dict.fromkeys(result.labels))
        return result

    def _parse_entity_page(self, html: str, entity_id: str, url: str) -> EntityProfile:
        result = EntityProfile(entity_id=entity_id, source_url=url)

        if not html or self._is_cloudflare_block(html):
            result.error = "Cloudflare block or empty response"
            return result

        soup = BeautifulSoup(html, 'lxml') if BeautifulSoup else None
        if not soup:
            result.error = "BeautifulSoup not available"
            return result

        embedded_data = self._extract_json_from_page(html)
        for item in embedded_data:
            data = item.get("data", {})
            props = data.get("props", {}).get("pageProps", {}) if isinstance(data, dict) else {}
            if not props and isinstance(data, dict):
                props = data

            entity_data = props.get("entityData") or props.get("entity") or props.get("data", {})
            if entity_data:
                result.entity_name = entity_data.get("name") or entity_data.get("label")
                result.entity_type = entity_data.get("type") or entity_data.get("category")
                result.description = entity_data.get("description") or entity_data.get("bio")
                result.website = entity_data.get("website")
                result.twitter = entity_data.get("twitter") or (entity_data.get("socials", {}) or {}).get("twitter")

                addresses = entity_data.get("addresses", [])
                for addr in addresses:
                    result.addresses.append({
                        "address": addr.get("address"),
                        "chain": addr.get("chain") or addr.get("network"),
                        "label": addr.get("label"),
                    })

                result.portfolio_usd = entity_data.get("portfolioUsd") or entity_data.get("netWorth")
                portfolio_by_chain = entity_data.get("portfolioByChain") or entity_data.get("chainBalances", {})
                if portfolio_by_chain:
                    result.portfolio_by_chain = portfolio_by_chain

                top_tokens = entity_data.get("topTokens") or entity_data.get("holdings", [])
                for token in top_tokens:
                    result.top_tokens.append({
                        "symbol": token.get("symbol") or token.get("token"),
                        "balance": token.get("balance"),
                        "usd_value": token.get("usdValue") or token.get("value"),
                    })

        if not result.entity_name:
            title_tag = soup.find("title")
            if title_tag:
                title = self._clean_text(title_tag.get_text())
                match = re.search(r'^(.*?)\s*\|', title)
                if match:
                    result.entity_name = match.group(1).strip()

            for selector in ['h1', 'h2', '[class*="EntityName"]', '[class*="entity-name"]']:
                elem = soup.select_one(selector)
                if elem:
                    text = self._clean_text(elem.get_text())
                    if text and len(text) < 100:
                        result.entity_name = text
                        break

        return result

    # =================================================================
    # HTTP Fetch Strategies
    # =================================================================

    def _try_scrapling(self, url: str) -> Optional[str]:
        """Scrapling stealth fetch — primary Cloudflare bypass."""
        if not SCRAPLING_AVAILABLE:
            return None

        # Attempt 1: Standard stealth fetch with Cloudflare solver
        try:
            logger.info("Trying Scrapling stealth engine (attempt 1)...")
            scrapling_opts = {
                "headless": self.headless,
                "solve_cloudflare": True,
                "disable_resources": True,
                "block_ads": True,
                "block_webrtc": True,
                "hide_canvas": True,
                "timeout": 60000,
                "wait": 3000,
                "load_dom": True,
            }
            if self.proxy:
                scrapling_opts["proxy"] = self.proxy
            response = StealthyFetcher.fetch(url, **scrapling_opts)
            html_text = response.body.decode('utf-8') if response.body and hasattr(response.body, 'decode') else str(response)
            if response.status == 200 and html_text and len(html_text) > 1000 and not self._is_cloudflare_block(html_text):
                logger.info("Scrapling attempt 1 succeeded")
                return html_text
            else:
                logger.warning(f"Scrapling attempt 1: status={response.status}, len={len(html_text)}, cf_block={self._is_cloudflare_block(html_text)}")
        except Exception as e:
            logger.debug(f"Scrapling attempt 1 failed: {e}")

        # Attempt 2: Use real Chrome browser with longer wait
        try:
            logger.info("Trying Scrapling with real Chrome (attempt 2)...")
            scrapling_opts = {
                "headless": self.headless,
                "solve_cloudflare": True,
                "real_chrome": True,
                "disable_resources": False,
                "block_ads": True,
                "block_webrtc": True,
                "hide_canvas": True,
                "timeout": 90000,
                "wait": 5000,
                "load_dom": True,
            }
            if self.proxy:
                scrapling_opts["proxy"] = self.proxy
            response = StealthyFetcher.fetch(url, **scrapling_opts)
            html_text = response.body.decode('utf-8') if response.body and hasattr(response.body, 'decode') else str(response)
            if response.status == 200 and html_text and len(html_text) > 1000 and not self._is_cloudflare_block(html_text):
                logger.info("Scrapling attempt 2 (real Chrome) succeeded")
                return html_text
            else:
                logger.warning(f"Scrapling attempt 2: status={response.status}, len={len(html_text)}, cf_block={self._is_cloudflare_block(html_text)}")
        except Exception as e:
            logger.debug(f"Scrapling attempt 2 failed: {e}")

        return None

    def _try_playwright(self, url: str) -> Optional[str]:
        """Direct Playwright fetch that waits out Cloudflare's non-interactive
        JS challenge and lets the Arkham SPA hydrate before reading the DOM.

        Cloudflare's "Just a moment…" interstitial clears itself in a few seconds
        in a real browser, so instead of grabbing the page after a fixed delay we
        poll until the challenge is gone (or a timeout), then wait for the app's
        embedded ``__NEXT_DATA__`` / entity content to appear."""
        if not PLAYWRIGHT_AVAILABLE:
            return None
        try:
            logger.info("Trying Playwright stealth fetch...")
            with sync_playwright() as p:
                launch_opts = {
                    "headless": self.headless,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                }
                if self.proxy:
                    launch_opts["proxy"] = {"server": self.proxy}
                browser = p.chromium.launch(**launch_opts)
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="America/New_York",
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": HEADERS["Accept"],
                        "DNT": "1",
                        "Upgrade-Insecure-Requests": "1",
                    },
                )
                # Reduce the most obvious automation fingerprints.
                context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                    "window.chrome={runtime:{}};"
                    "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
                    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Poll until the Cloudflare interstitial clears.
                html = page.content()
                deadline = time.time() + max(2.0, self.cf_wait_seconds)
                while self._is_cloudflare_block(html) and time.time() < deadline:
                    page.wait_for_timeout(2000)
                    try:
                        html = page.content()
                    except Exception:  # noqa: BLE001
                        break

                # Give the SPA a moment to hydrate the entity/attribution data.
                if not self._is_cloudflare_block(html):
                    try:
                        page.wait_for_selector(
                            "script#__NEXT_DATA__, [class*='entity'], [data-testid*='entity'], h1",
                            timeout=12000,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(1500)
                    html = page.content()

                browser.close()
                if html and len(html) > 1000 and not self._is_cloudflare_block(html):
                    logger.info("Playwright stealth fetch succeeded")
                    return html
                logger.warning(
                    f"Playwright: len={len(html) if html else 0}, "
                    f"cf_block={self._is_cloudflare_block(html) if html else True}"
                )
        except Exception as e:
            logger.debug(f"Playwright fetch failed: {e}")
        return None

    def _try_http_plain(self, url: str) -> Optional[str]:
        """Plain HTTP request — likely to hit 403 on Arkham, used as last resort."""
        try:
            resp = self.session.get(url)
            if resp is not None and resp.status_code == 200:
                html = resp.text
                if not self._is_cloudflare_block(html):
                    return html
        except Exception as e:
            logger.debug(f"Plain HTTP failed: {e}")
        return None

    def _try_http_first(self, url: str, use_alternatives: bool = True) -> Optional[str]:
        """Fetch a page from Arkham with Scrapling/Playwright as PRIMARY,
        plain HTTP only as a last resort."""
        self._rate_limit()

        # ------------------------------------------------------------------
        # Strategy 1: Scrapling (stealth Playwright) — PRIMARY
        # ------------------------------------------------------------------
        html = self._try_scrapling(url)
        if html:
            return html

        # ------------------------------------------------------------------
        # Strategy 2: Direct Playwright fallback
        # ------------------------------------------------------------------
        html = self._try_playwright(url)
        if html:
            return html

        if not use_alternatives:
            return None

        # ------------------------------------------------------------------
        # Strategy 3: cloudscraper (lightweight TLS fingerprint evasion)
        # ------------------------------------------------------------------
        try:
            import cloudscraper
            logger.info("Trying cloudscraper fallback...")
            scraper = cloudscraper.create_scraper()
            if self.proxy:
                scraper.proxies.update({"http": self.proxy, "https": self.proxy})
            scraper.headers.update(HEADERS)
            r = scraper.get(url, timeout=30)
            if r.status_code == 200 and not self._is_cloudflare_block(r.text):
                logger.info("cloudscraper succeeded")
                return r.text
        except ImportError:
            logger.debug("cloudscraper not installed")
        except Exception as e:
            logger.debug(f"cloudscraper failed: {e}")

        # ------------------------------------------------------------------
        # Strategy 4: curl subprocess (different TLS fingerprint)
        # ------------------------------------------------------------------
        try:
            logger.info("Trying curl subprocess fallback...")
            cmd = [
                "curl", "-s", "-L", "-A", HEADERS["User-Agent"],
                "--connect-timeout", "15", "--max-time", "30",
                url
            ]
            if self.proxy:
                cmd.extend(["-x", self.proxy])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            if result.returncode == 0 and result.stdout and not self._is_cloudflare_block(result.stdout):
                if len(result.stdout) > 1000:
                    logger.info("curl fallback succeeded")
                    return result.stdout
        except Exception as e:
            logger.debug(f"curl fallback failed: {e}")

        # ------------------------------------------------------------------
        # Strategy 5: fake useragent rotation
        # ------------------------------------------------------------------
        try:
            from fake_useragent import UserAgent
            logger.info("Trying fake useragent rotation...")
            ua = UserAgent()
            alt_headers = {**HEADERS, "User-Agent": ua.random}
            r = requests.get(url, headers=alt_headers, timeout=20, allow_redirects=True,
                             proxies=self.session.session.proxies if self.proxy else None)
            if r.status_code == 200 and not self._is_cloudflare_block(r.text):
                logger.info("fake_useragent succeeded")
                return r.text
        except ImportError:
            logger.debug("fake_useragent not installed")
        except Exception as e:
            logger.debug(f"fake_useragent failed: {e}")

        # ------------------------------------------------------------------
        # Strategy 6: Plain HTTP session (almost certainly 403 on Arkham)
        # ------------------------------------------------------------------
        logger.info("Trying plain HTTP session as last resort...")
        html = self._try_http_plain(url)
        if html:
            return html

        return None

    def _try_intel_url(self, address: str) -> Optional[str]:
        """Try the intel.arkm.com endpoint via stealth fetchers."""
        url = f"{INTEL_URL}/explorer/address/{address.lower()}"
        logger.info(f"Trying intel.arkm.com endpoint: {url}")
        return self._try_http_first(url, use_alternatives=True)

    def _try_platform_url(self, address: str) -> Optional[str]:
        """Try the platform.arkhamintelligence.com endpoint via stealth fetchers."""
        url = f"{PLATFORM_URL}/explorer/address/{address.lower()}"
        logger.info(f"Trying platform endpoint: {url}")
        return self._try_http_first(url, use_alternatives=True)

    def _try_arkm_url(self, address: str) -> Optional[str]:
        """Try the arkm.com root endpoint via stealth fetchers."""
        url = f"{ARKM_URL}/explorer/address/{address.lower()}"
        logger.info(f"Trying arkm.com endpoint: {url}")
        return self._try_http_first(url, use_alternatives=True)

    # =================================================================
    # Public Scraping Methods
    # =================================================================

    def _try_intel_api_json(self, address: str, chain: str) -> Optional[AddressAttribution]:
        """Best-effort hit against Arkham's JSON intelligence API. When reachable
        it returns the entity owner directly as structured JSON — far cleaner than
        scraping rendered HTML. Requires no API key when the CDN serves it; if it
        is auth-walled the call simply returns None and we fall back to HTML."""
        endpoints = [
            f"{API_BASE}/intelligence/address/{address}?chain={chain}",
            f"{INTEL_URL}/api/intelligence/address/{address}?chain={chain}",
        ]
        for url in endpoints:
            # Cheap plain-HTTP probe only — never the heavy stealth chain here, so
            # an auth-walled API can't burn the whole time budget before we fall
            # back to the (working) HTML scrape path.
            raw = self._try_http_plain(url)
            if not raw:
                continue
            raw = raw.strip()
            if not raw.startswith("{"):
                # Stealth fetchers sometimes wrap JSON in a <pre>/<body>; dig it out.
                m = re.search(r'(\{.*\})', raw, re.DOTALL)
                if not m:
                    continue
                raw = m.group(1)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            deep = self._deep_extract_entity(data)
            if deep.get("entity_name"):
                res = AddressAttribution(address=address, chain=chain, source_url=url)
                res.entity_name = deep["entity_name"]
                res.entity_id = deep.get("entity_id")
                res.entity_type = deep.get("entity_type")
                res.is_verified = bool(deep.get("is_verified", False))
                res.portfolio_usd = deep.get("portfolio_usd")
                res.confidence_score = deep.get("confidence")
                return res
        return None

    def scrape_address(self, address: str, chain: str = "ethereum") -> AddressAttribution:
        address = address.lower().strip()
        url = f"{BASE_URL}/explorer/address/{address}"

        logger.info(f"Scraping address: {address}")

        # Fast path: structured JSON API (no HTML parsing needed when reachable).
        api_result = self._try_intel_api_json(address, chain)
        if api_result and api_result.entity_name:
            logger.info(f"Arkham JSON API returned owner: {api_result.entity_name}")
            return api_result

        # Try each endpoint, but only up to self.max_endpoints so the fast inline
        # lookup doesn't spend a full Cloudflare-wait budget on every host.
        html = None
        endpoints = [
            (f"{BASE_URL}/explorer/address/{address}", None),
            (f"{INTEL_URL}/explorer/address/{address}", lambda: self._try_intel_url(address)),
            (f"{PLATFORM_URL}/explorer/address/{address}", lambda: self._try_platform_url(address)),
        ]
        for candidate_url, fetch in endpoints[: self.max_endpoints]:
            html = self._try_http_first(candidate_url) if fetch is None else fetch()
            if html:
                url = candidate_url
                break

        # Try browser as last resort against the best URL we have
        if html is None and self.use_browser:
            self._ensure_browser()
            if self.browser and self.browser.driver:
                html = self.browser.get_page_source(
                    url,
                    wait_for="[data-testid='entity-name'], h1, [class*='entity']",
                    timeout=30
                )

        if html is None:
            return AddressAttribution(
                address=address,
                chain=chain,
                error="Cloudflare blocked all requests. Install Scrapling (pip install scrapling) for stealth bypass, or use a proxy.",
                source_url=url
            )

        return self._parse_address_page(html, address, chain, url)

    def scrape_entity(self, entity_id: str) -> EntityProfile:
        entity_id = entity_id.lower().strip().replace(" ", "-")
        url = f"{BASE_URL}/explorer/entity/{entity_id}"

        logger.info(f"Scraping entity: {entity_id}")

        html = self._try_http_first(url)

        if html is None and self.use_browser:
            self._ensure_browser()
            if self.browser and self.browser.driver:
                html = self.browser.get_page_source(
                    url,
                    wait_for="h1, [class*='entity'], [data-testid='portfolio']",
                    timeout=30
                )

        if html is None:
            return EntityProfile(
                entity_id=entity_id,
                error="Cloudflare blocked all requests. Install Scrapling (pip install scrapling) for stealth bypass, or use a proxy.",
                source_url=url
            )

        return self._parse_entity_page(html, entity_id, url)

    def scrape_intel_address(self, address: str) -> Optional[AddressAttribution]:
        """Scrape address attribution via intel.arkm.com endpoint."""
        address = address.lower().strip()
        html = self._try_intel_url(address)
        if html:
            return self._parse_address_page(html, address, "ethereum", f"{INTEL_URL}/explorer/address/{address}")
        return None

    def batch_scrape_addresses(
        self,
        addresses: List[str],
        output_file: Optional[str] = None,
        format: str = "json"
    ) -> List[AddressAttribution]:
        results = []
        total = len(addresses)

        for i, addr in enumerate(addresses, 1):
            logger.info(f"[{i}/{total}] Processing {addr}")
            try:
                result = self.scrape_address(addr)
                results.append(result)

                if output_file and i % 10 == 0:
                    self._save_results(results, output_file, format)
                    logger.info(f"Checkpoint saved after {i} addresses")

            except Exception as e:
                logger.error(f"Failed to scrape {addr}: {e}")
                results.append(AddressAttribution(
                    address=addr,
                    error=str(e)
                ))

        if output_file:
            self._save_results(results, output_file, format)

        return results

    def discover_entities(self, max_pages: int = 5) -> List[str]:
        discovered = []

        for page in range(1, max_pages + 1):
            url = f"{BASE_URL}/explorer/entities?page={page}"
            logger.info(f"Discovering entities from page {page}")

            html = self._try_http_first(url)
            if html is None and self.use_browser:
                self._ensure_browser()
                if self.browser and self.browser.driver:
                    html = self.browser.get_page_source(url, wait_for="a[href*='/entity/']", timeout=20)

            if not html:
                continue

            soup = BeautifulSoup(html, 'lxml') if BeautifulSoup else None
            if soup:
                links = soup.find_all("a", href=re.compile(r'/entity/([^/]+)'))
                for link in links:
                    href = link.get("href", "")
                    match = re.search(r'/entity/([^/?#]+)', href)
                    if match:
                        slug = match.group(1)
                        if slug not in discovered and slug not in KNOWN_ENTITY_SLUGS:
                            discovered.append(slug)

            time.sleep(self.rate_limit_delay)

        logger.info(f"Discovered {len(discovered)} new entities")
        return discovered

    def _save_results(self, results: List[Any], filepath: str, format: str = "json"):
        data = [r.to_dict() for r in results]
        path = Path(filepath)

        if format.lower() == "json":
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        elif format.lower() in ("csv", "tsv"):
            if not data:
                return
            keys = set()
            for item in data:
                keys.update(item.keys())
            keys = sorted(keys)
            delimiter = '\t' if format.lower() == "tsv" else ','
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys, delimiter=delimiter)
                writer.writeheader()
                for item in data:
                    row = {}
                    for k in keys:
                        val = item.get(k)
                        if isinstance(val, (list, dict)):
                            val = json.dumps(val)
                        row[k] = val
                    writer.writerow(row)

        logger.info(f"Results saved to {path}")

    def close(self):
        self.session.close()
        if self.browser:
            self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# =============================================================================
# GraphQL Direct Query Attempts (No API Key)
# =============================================================================

class ArkhamGraphQL:
    """Attempts to query Arkham's GraphQL endpoint without API keys."""

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy
        self.session = ArkhamSession(proxy=proxy)
        self.endpoint = f"{BASE_URL}/graphql"

    def _query(self, query: str, variables: Optional[Dict] = None) -> Optional[Dict]:
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        self.session.headers = GRAPHQL_HEADERS
        resp = self.session.post(self.endpoint, json=payload)
        if resp and resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                pass
        return None

    def get_address_intel(self, address: str, chain: str = "ethereum") -> Optional[Dict]:
        query = """
        query AddressIntel($address: String!, $chain: String!) {
            addressIntel(address: $address, chain: $chain) {
                address
                chain
                arkhamEntity {
                    id
                    name
                    type
                    isVerified
                }
                labels {
                    name
                    category
                }
                tags
                portfolioUsd
                confidence
            }
        }
        """
        return self._query(query, {"address": address.lower(), "chain": chain})

    def get_entity(self, entity_id: str) -> Optional[Dict]:
        query = """
        query Entity($id: String!) {
            entity(id: $id) {
                id
                name
                type
                description
                website
                twitter
                addresses {
                    address
                    chain
                }
                portfolioUsd
                labels
                tags
            }
        }
        """
        return self._query(query, {"id": entity_id})

    def close(self):
        self.session.close()


# =============================================================================
# Setup Check
# =============================================================================

def run_setup_check():
    """Check what's available and what the user needs to install."""
    print("\n" + "=" * 60)
    print("Arkham Scraper - Setup Check")
    print("=" * 60)

    # Check core libraries
    print("\n[Core Dependencies]")
    try:
        import requests
        print(f"  requests: {requests.__version__} OK")
    except ImportError:
        print("  requests: MISSING - pip install requests")

    try:
        from bs4 import BeautifulSoup
        print("  beautifulsoup4: OK")
    except ImportError:
        print("  beautifulsoup4: MISSING - pip install beautifulsoup4")

    try:
        import lxml
        print("  lxml: OK")
    except ImportError:
        print("  lxml: MISSING - pip install lxml")

    # Check Scrapling (primary stealth engine)
    print("\n[Stealth Engine]")
    try:
        import scrapling
        print(f"  scrapling: {scrapling.__version__} OK (PRIMARY - Cloudflare bypass)")
    except ImportError:
        print("  scrapling: MISSING - pip install scrapling")
        print("    -> This is the RECOMMENDED way to bypass Cloudflare")

    # Check browser automation (fallback)
    print("\n[Browser Automation - fallback only]")
    try:
        import undetected_chromedriver
        print("  undetected_chromedriver: OK")
    except ImportError:
        print("  undetected_chromedriver: NOT INSTALLED - pip install undetected-chromedriver")

    try:
        import selenium
        print(f"  selenium: {selenium.__version__} OK")
    except ImportError:
        print("  selenium: NOT INSTALLED - pip install selenium")

    # Check optional
    print("\n[Optional Fallbacks]")
    try:
        import cloudscraper
        print("  cloudscraper: OK")
    except ImportError:
        print("  cloudscraper: NOT INSTALLED - pip install cloudscraper")

    try:
        from fake_useragent import UserAgent
        print("  fake_useragent: OK")
    except ImportError:
        print("  fake_useragent: NOT INSTALLED - pip install fake-useragent")

    # Check curl
    print("\n[System Tools]")
    try:
        result = subprocess.run(["curl", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version_line = result.stdout.splitlines()[0] if result.stdout else "curl OK"
            print(f"  curl: {version_line}")
        else:
            print("  curl: NOT FOUND in PATH")
    except Exception:
        print("  curl: NOT FOUND in PATH")

    # Test connectivity
    print("\n[Connectivity Test]")
    test_url = "https://platform.arkhamintelligence.com"
    try:
        import requests
        r = requests.get(test_url, headers=HEADERS, timeout=10)
        if r.status_code == 200 and "cloudflare" not in r.text.lower():
            print(f"  {test_url}: OK (HTTP 200)")
        elif r.status_code == 403:
            print(f"  {test_url}: BLOCKED (HTTP 403 - Cloudflare)")
            if 'scrapling' not in sys.modules:
                print(f"    -> Install scrapling:  pip install scrapling")
            print(f"    -> Or use a proxy:       --proxy http://host:port")
        else:
            print(f"  {test_url}: HTTP {r.status_code}")
    except Exception as e:
        print(f"  {test_url}: FAILED ({e})")

    print("\n" + "=" * 60)
    print("\nRecommended install (one command):")
    print("  pip install scrapling requests beautifulsoup4 lxml")
    print("\nFor legacy fallback (not recommended):")
    print("  pip install undetected-chromedriver selenium webdriver-manager")
    print("\nFor alternative fallbacks:")
    print("  pip install cloudscraper fake-useragent")
    print("=" * 60 + "\n")


# =============================================================================
# CLI Interface
# =============================================================================

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Arkham Intelligence (arkm.com) Crypto Address Attribution Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check your setup
  python arkm_scraper.py --setup-check

  # Scrape a single address
  python arkm_scraper.py --address 0x47666fab8bd0ac7003bce3f5c3585383f09486e2

  # Scrape an entity profile
  python arkm_scraper.py --entity binance

  # Batch scrape from file
  python arkm_scraper.py --batch addresses.txt --output results.json

  # Use browser automation for Cloudflare bypass
  python arkm_scraper.py --address 0x... --no-headless

  # Use proxy
  python arkm_scraper.py --batch addresses.txt --proxy http://127.0.0.1:8080

  # HTTP only (no browser)
  python arkm_scraper.py --address 0x... --http-only
        """
    )

    parser.add_argument("--address", type=str, help="Single crypto address to scrape")
    parser.add_argument("--entity", type=str, help="Entity slug to scrape (e.g., 'binance')")
    parser.add_argument("--batch", type=str, help="File containing addresses (one per line)")
    parser.add_argument("--output", type=str, default="arkham_results.json", help="Output file path")
    parser.add_argument("--format", type=str, choices=["json", "csv", "tsv"], default="json", help="Output format")
    parser.add_argument("--chain", type=str, default="ethereum", help="Blockchain (default: ethereum)")

    parser.add_argument("--browser", action="store_true", default=True, help="Use browser automation (default: True)")
    parser.add_argument("--no-browser", dest="browser", action="store_false", help="Disable browser automation")
    parser.add_argument("--http-only", dest="browser", action="store_false", help="Only use HTTP requests (alias for --no-browser)")
    parser.add_argument("--no-headless", dest="headless", action="store_false", default=True, help="Show browser window")
    parser.add_argument("--proxy", type=str, help="Proxy URL (e.g., http://127.0.0.1:8080)")
    parser.add_argument("--delay", type=float, default=2.0, help="Rate limit delay between requests (seconds)")
    parser.add_argument("--discover", action="store_true", help="Discover entity slugs from platform")
    parser.add_argument("--graphql", action="store_true", help="Try GraphQL direct queries (experimental)")
    parser.add_argument("--setup-check", action="store_true", help="Check dependencies and connectivity")
    parser.add_argument("--install-deps", action="store_true", help="Show pip install command for dependencies")

    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    if args.setup_check:
        run_setup_check()
        sys.exit(0)

    if args.install_deps:
        print("\n" + "=" * 60)
        print("Arkham Scraper - Required Dependencies")
        print("=" * 60)
        print("\nPRIMARY (recommended for Cloudflare bypass):")
        print("  pip install scrapling")
        print("\nCore (always needed):")
        print("  pip install requests beautifulsoup4 lxml")
        print("\nFallback browser (if Scrapling fails):")
        print("  pip install undetected-chromedriver selenium webdriver-manager")
        print("\nOptional fallbacks:")
        print("  pip install cloudscraper fake-useragent")
        print("\n" + "=" * 60)
        sys.exit(0)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not any([args.address, args.entity, args.batch, args.discover]):
        parser.print_help()
        sys.exit(1)

    with ArkhamScraper(
        use_browser=args.browser,
        headless=args.headless,
        proxy=args.proxy,
        rate_limit_delay=args.delay,
    ) as scraper:

        results = []

        if args.address:
            result = scraper.scrape_address(args.address, chain=args.chain)
            results.append(result)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

        if args.entity:
            result = scraper.scrape_entity(args.entity)
            results.append(result)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

        if args.batch:
            if not os.path.exists(args.batch):
                logger.error(f"Batch file not found: {args.batch}")
                sys.exit(1)

            with open(args.batch, 'r') as f:
                addresses = [line.strip() for line in f if line.strip() and not line.startswith('#')]

            logger.info(f"Loaded {len(addresses)} addresses from {args.batch}")
            results = scraper.batch_scrape_addresses(addresses, output_file=args.output, format=args.format)

            successful = sum(1 for r in results if not r.error)
            logger.info(f"Batch complete: {successful}/{len(results)} successful")

        if args.discover:
            discovered = scraper.discover_entities(max_pages=5)
            print(json.dumps(discovered, indent=2))
            if discovered:
                with open("discovered_entities.json", 'w') as f:
                    json.dump(discovered, f, indent=2)
                logger.info(f"Saved {len(discovered)} discovered entities to discovered_entities.json")

        if args.graphql and (args.address or args.entity):
            gql = ArkhamGraphQL(proxy=args.proxy)
            if args.address:
                data = gql.get_address_intel(args.address, chain=args.chain)
                print("\n--- GraphQL Result ---")
                print(json.dumps(data, indent=2) if data else "No data / Auth required")
            if args.entity:
                data = gql.get_entity(args.entity)
                print("\n--- GraphQL Result ---")
                print(json.dumps(data, indent=2) if data else "No data / Auth required")
            gql.close()

        if results and not args.batch:
            scraper._save_results(results, args.output, args.format)
            logger.info(f"Final results saved to {args.output}")


if __name__ == "__main__":
    main()
