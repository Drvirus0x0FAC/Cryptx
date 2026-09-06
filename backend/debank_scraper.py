#!/usr/bin/env python3
"""
DeBank Dynamic Scraper
======================
A headless browser scraper + direct API client for DeBank profile pages.
Extracts portfolio data by intercepting DeBank's frontend API calls.

Two modes:
  1. Browser mode (default): Uses Playwright to render the page and intercept API calls
  2. Direct API mode: Calls DeBank's internal API directly (faster, no browser)

Usage:
    # Browser mode
    python debank_scraper.py 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

    # Direct API mode (faster, no browser)
    python debank_scraper.py 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 --api-only

Install dependencies:
    pip install playwright requests
    playwright install chromium

Author: AI Assistant
"""

import json
import sys
import time
import argparse
import requests
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse, parse_qs


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ChainBalance:
    chain_id: str
    chain_name: str
    logo_url: str
    native_token_id: str
    wrapped_token_id: str
    usd_value: float


@dataclass
class TokenInfo:
    id: str
    chain: str
    name: str
    symbol: str
    decimals: int
    logo_url: str
    price: float
    amount: float
    raw_amount: int
    usd_value: float
    is_verified: bool
    is_core: bool
    is_wallet: bool = False
    protocol_id: Optional[str] = None
    credit_score: float = 0.0
    price_24h_change: float = 0.0
    is_scam: bool = False
    is_suspicious: bool = False


@dataclass
class ProtocolPosition:
    protocol_id: str
    protocol_name: str
    chain: str
    logo_url: str
    site_url: str
    tvl: float
    asset_usd_value: float
    debt_usd_value: float
    net_usd_value: float
    detail_types: List[str] = field(default_factory=list)
    asset_tokens: List[TokenInfo] = field(default_factory=list)


@dataclass
class NFTItem:
    id: str
    chain: str
    name: str
    collection_id: str
    collection_name: str
    logo_url: str
    amount: float
    usd_value: float


@dataclass
class Transaction:
    tx_id: str
    chain: str
    time_at: int
    category: str
    project_id: Optional[str] = None
    token_approve: Optional[Dict] = None
    receives: List[Dict] = field(default_factory=list)
    sends: List[Dict] = field(default_factory=list)
    protocol: Optional[Dict] = None


@dataclass
class DeBankProfile:
    address: str
    total_usd_value: float = 0.0
    chain_balances: List[ChainBalance] = field(default_factory=list)
    tokens: List[TokenInfo] = field(default_factory=list)
    protocols: List[ProtocolPosition] = field(default_factory=list)
    nfts: List[NFTItem] = field(default_factory=list)
    transactions: List[Transaction] = field(default_factory=list)
    raw_api_data: Dict[str, Any] = field(default_factory=dict, repr=False)

    # Social/Identity fields
    display_name: Optional[str] = None
    bio: str = ""
    follower_count: int = 0
    following_count: int = 0
    tags: List[Dict[str, str]] = field(default_factory=list)
    is_vip: bool = False
    is_pro: bool = False
    web3_id: Optional[str] = None
    used_chains: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["owner_name"] = self.resolve_owner_name()
        return data

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def resolve_owner_name(self) -> Optional[str]:
        """Best owner/identity label DeBank knows for this address.

        Preference order: the profile display name the owner set → their DeBank
        Web3 ID (e.g. ``vitalik``) → the first descriptive tag DeBank applied
        (e.g. an exchange/whale label). Returns None when DeBank has no identity
        signal, so callers can treat the address as unattributed.
        """
        def _clean(v: Any) -> str:
            return str(v).strip() if v else ""

        name = _clean(self.display_name)
        if name and name.lower() not in ("", "unknown", "unnamed"):
            return name

        web3 = _clean(self.web3_id)
        if web3:
            return web3 if web3.endswith((".eth", ".bnb", ".lens")) else f"{web3} (DeBank ID)"

        for tag in self.tags or []:
            tag_name = _clean(tag.get("name") if isinstance(tag, dict) else tag)
            if tag_name:
                return tag_name
        return None


# ---------------------------------------------------------------------------
# Direct API Client (fast, no browser)
# ---------------------------------------------------------------------------

class DeBankAPIClient:
    """
    Direct HTTP client for DeBank's internal API endpoints.
    No browser needed - much faster than Playwright scraping.
    """

    BASE_URL = "https://api.debank.com"
    # Max times a single endpoint will be retried after a 429. Kept as a class
    # attribute so callers (e.g. the FastAPI identity router) can dial it down to
    # 0 for fast, non-blocking requests: ``client.MAX_RETRIES = 0``.
    MAX_RETRIES = 2
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://debank.com",
        "Referer": "https://debank.com/",
        "Source": "web",
        "X-Api-Ver": "v2",
    }

    def __init__(self, rate_limit: float = 0.5):
        import os
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        # DeBank increasingly gates api.debank.com behind a signed "account"
        # header tied to a logged-in session. If the user exports one from their
        # browser devtools into DEBANK_ACCOUNT_HEADER, use it — this makes the
        # direct (fast) API path actually return data. Without it we still try
        # anonymously and fall back to the browser scraper.
        account_header = os.getenv("DEBANK_ACCOUNT_HEADER", "").strip()
        if account_header:
            self.session.headers["Account"] = account_header
        self.rate_limit = rate_limit
        self._last_request = 0.0

    def _get(self, endpoint: str, params: Dict[str, Any] = None, _attempt: int = 0) -> Optional[Dict]:
        """Make a rate-limited GET request with a bounded 429 retry."""
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)

        url = f"{self.BASE_URL}{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            self._last_request = time.time()
            if resp.status_code == 200:
                json_data = resp.json()
                # Unwrap DeBank's nested data structure
                if isinstance(json_data, dict) and "data" in json_data:
                    return json_data
                return {"data": json_data}
            elif resp.status_code == 429:
                if _attempt >= self.MAX_RETRIES:
                    print(f"[WARN] Rate limited on {endpoint}, retries exhausted")
                    return None
                print(f"[WARN] Rate limited on {endpoint}, waiting 3s (retry {_attempt + 1}/{self.MAX_RETRIES})...")
                time.sleep(3)
                return self._get(endpoint, params, _attempt + 1)
            else:
                print(f"[WARN] {endpoint} returned {resp.status_code}")
                return None
        except Exception as e:
            print(f"[ERROR] Request failed: {e}")
            return None

    def fetch_user(self, address: str) -> Optional[Dict]:
        """Fetch user profile and metadata."""
        return self._get("/user", {"id": address.lower()})

    def fetch_used_chains(self, address: str) -> Optional[Dict]:
        """Fetch list of chains the user has interacted with."""
        return self._get("/user/used_chains", {"id": address.lower()})

    def fetch_token_balance(self, address: str, chain: str) -> Optional[Dict]:
        """Fetch token balances for a specific chain."""
        return self._get("/token/balance_list", {
            "user_addr": address.lower(),
            "chain": chain,
        })

    def fetch_token_cache_balance(self, address: str) -> Optional[Dict]:
        """Fetch cached token balances across all chains."""
        return self._get("/token/cache_balance_list", {"user_addr": address.lower()})

    def fetch_portfolio_projects(self, address: str) -> Optional[Dict]:
        """Fetch DeFi protocol positions."""
        return self._get("/portfolio/project_list", {"user_addr": address.lower()})

    def fetch_portfolio_apps(self, address: str) -> Optional[Dict]:
        """Fetch portfolio app data."""
        return self._get("/portfolio/app_list", {"user_id": address.lower()})

    def fetch_nft_list(self, address: str, chain: str = "eth") -> Optional[Dict]:
        """Fetch NFT list for a chain."""
        return self._get("/nft/list", {
            "user_addr": address.lower(),
            "chain": chain,
        })

    def fetch_history(self, address: str, chain: str = "eth", page_count: int = 20) -> Optional[Dict]:
        """Fetch transaction history."""
        return self._get("/history/list", {
            "user_addr": address.lower(),
            "chain": chain,
            "page_count": page_count,
        })

    def fetch_chain_list(self) -> Optional[Dict]:
        """Fetch list of supported chains."""
        return self._get("/chain/list")

    def scrape(self, address: str) -> DeBankProfile:
        """
        Full scrape using direct API calls.

        Args:
            address: Crypto wallet address

        Returns:
            DeBankProfile with all extracted data
        """
        address = address.lower().strip()
        profile = DeBankProfile(address=address)
        raw_data = {}

        print(f"[API] Fetching user info...")
        user_data = self.fetch_user(address)
        if user_data:
            raw_data["user"] = user_data
            user_inner = user_data.get("data", {}).get("user", {})
            desc = user_inner.get("desc", {})
            profile.total_usd_value = desc.get("usd_value", 0.0)
            profile.display_name = desc.get("name")
            profile.bio = user_inner.get("bio", "")
            profile.follower_count = user_inner.get("follower_count", 0)
            profile.following_count = user_inner.get("following_count", 0)
            profile.is_vip = user_inner.get("is_vip", False)
            profile.is_pro = user_inner.get("is_pro", False)
            profile.web3_id = user_inner.get("web3_id")
            profile.tags = desc.get("tags", [])
            profile.used_chains = desc.get("used_chains", [])

        print(f"[API] Fetching used chains...")
        used_chains_data = self.fetch_used_chains(address)
        if used_chains_data:
            raw_data["used_chains"] = used_chains_data
            chains = used_chains_data.get("data", {}).get("used_chains", [])
            if chains and not profile.used_chains:
                profile.used_chains = chains

        # Fetch chain list for name mapping
        print(f"[API] Fetching chain list...")
        chain_list_data = self.fetch_chain_list()
        chain_map = {}
        if chain_list_data:
            raw_data["chain_list"] = chain_list_data
            for chain in chain_list_data.get("data", {}).get("chains", []):
                chain_map[chain["id"]] = chain

        # Build chain balances from chain_map and used_chains
        # Note: DeBank's new API doesn't give per-chain usd_value directly in total_balance
        # We'll calculate it from token balances later
        for chain_id in profile.used_chains:
            chain_info = chain_map.get(chain_id, {})
            profile.chain_balances.append(ChainBalance(
                chain_id=chain_id,
                chain_name=chain_info.get("name", chain_id),
                logo_url=chain_info.get("logo_url", ""),
                native_token_id=chain_info.get("token_id", ""),
                wrapped_token_id=chain_info.get("wrapped", ""),
                usd_value=0.0,  # Will be calculated from tokens
            ))

        # Fetch tokens - use cache_balance_list for all chains in one call, fallback to per-chain
        print(f"[API] Fetching token balances...")
        all_tokens = []
        cache_data = self.fetch_token_cache_balance(address)
        if cache_data:
            raw_data["token_cache_balance"] = cache_data
            tokens = cache_data.get("data", [])
            if isinstance(tokens, list) and tokens:
                print(f"[API] Got {len(tokens)} tokens from cache_balance_list")
                for token in tokens:
                    amount = token.get("amount", 0.0)
                    price = token.get("price", 0.0)
                    usd_value = amount * price if amount and price else 0.0
                    all_tokens.append(TokenInfo(
                        id=token.get("id", ""),
                        chain=token.get("chain", ""),
                        name=token.get("name", "Unknown"),
                        symbol=token.get("symbol", "") or token.get("optimized_symbol", ""),
                        decimals=token.get("decimals", 18),
                        logo_url=token.get("logo_url", ""),
                        price=price,
                        amount=amount,
                        raw_amount=token.get("balance", 0),
                        usd_value=usd_value,
                        is_verified=token.get("is_verified", False),
                        is_core=token.get("is_core", False),
                        is_wallet=token.get("is_wallet", False),
                        protocol_id=token.get("protocol_id") or None,
                        credit_score=token.get("credit_score", 0.0),
                        price_24h_change=token.get("price_24h_change", 0.0),
                        is_scam=token.get("is_scam", False),
                        is_suspicious=token.get("is_suspicious", False),
                    ))

        # Fallback: fetch per-chain if cache is empty or failed
        if not all_tokens and profile.used_chains:
            print(f"[API] Cache empty, fetching per-chain for {len(profile.used_chains)} chains...")
            for chain_id in profile.used_chains:
                token_data = self.fetch_token_balance(address, chain_id)
                if token_data:
                    raw_data[f"token_balance_{chain_id}"] = token_data
                    tokens = token_data.get("data", [])
                    for token in tokens:
                        amount = token.get("amount", 0.0)
                        price = token.get("price", 0.0)
                        usd_value = amount * price if amount and price else 0.0
                        all_tokens.append(TokenInfo(
                            id=token.get("id", ""),
                            chain=token.get("chain", chain_id),
                            name=token.get("name", "Unknown"),
                            symbol=token.get("symbol", "") or token.get("optimized_symbol", ""),
                            decimals=token.get("decimals", 18),
                            logo_url=token.get("logo_url", ""),
                            price=price,
                            amount=amount,
                            raw_amount=token.get("balance", 0),
                            usd_value=usd_value,
                            is_verified=token.get("is_verified", False),
                            is_core=token.get("is_core", False),
                            is_wallet=token.get("is_wallet", False),
                            protocol_id=token.get("protocol_id") or None,
                            credit_score=token.get("credit_score", 0.0),
                            price_24h_change=token.get("price_24h_change", 0.0),
                            is_scam=token.get("is_scam", False),
                            is_suspicious=token.get("is_suspicious", False),
                        ))

        all_tokens.sort(key=lambda t: t.usd_value, reverse=True)
        profile.tokens = all_tokens

        # Calculate per-chain USD values from tokens
        chain_values = {}
        for token in all_tokens:
            chain_values[token.chain] = chain_values.get(token.chain, 0.0) + token.usd_value
        for cb in profile.chain_balances:
            cb.usd_value = chain_values.get(cb.chain_id, 0.0)

        # Fetch DeFi protocols
        print(f"[API] Fetching DeFi protocols...")
        portfolio_data = self.fetch_portfolio_projects(address)
        if portfolio_data:
            raw_data["portfolio_projects"] = portfolio_data
            projects = portfolio_data.get("data", [])
            for protocol in projects:
                for item in protocol.get("portfolio_item_list", []):
                    stats = item.get("stats", {})
                    asset_tokens = []
                    for token in item.get("asset_token_list", []):
                        t_amount = token.get("amount", 0.0)
                        t_price = token.get("price", 0.0)
                        asset_tokens.append(TokenInfo(
                            id=token.get("id", ""),
                            chain=token.get("chain", ""),
                            name=token.get("name", ""),
                            symbol=token.get("symbol", ""),
                            decimals=token.get("decimals", 18),
                            logo_url=token.get("logo_url", ""),
                            price=t_price,
                            amount=t_amount,
                            raw_amount=0,
                            usd_value=t_amount * t_price,
                            is_verified=token.get("is_verified", False),
                            is_core=token.get("is_core", False),
                        ))

                    profile.protocols.append(ProtocolPosition(
                        protocol_id=protocol.get("id", ""),
                        protocol_name=protocol.get("name", ""),
                        chain=protocol.get("chain", ""),
                        logo_url=protocol.get("logo_url", ""),
                        site_url=protocol.get("site_url", ""),
                        tvl=protocol.get("tvl", 0.0),
                        asset_usd_value=stats.get("asset_usd_value", 0.0),
                        debt_usd_value=stats.get("debt_usd_value", 0.0),
                        net_usd_value=stats.get("net_usd_value", 0.0),
                        detail_types=item.get("detail_types", []),
                        asset_tokens=asset_tokens,
                    ))

        # Fetch NFTs (just Ethereum for now, could expand)
        print(f"[API] Fetching NFTs...")
        nft_data = self.fetch_nft_list(address, "eth")
        if nft_data:
            raw_data["nft_list"] = nft_data
            nfts = nft_data.get("data", [])
            for nft in nfts:
                profile.nfts.append(NFTItem(
                    id=nft.get("id", ""),
                    chain=nft.get("chain", "eth"),
                    name=nft.get("name", ""),
                    collection_id=nft.get("collection_id", ""),
                    collection_name=nft.get("collection_name", ""),
                    logo_url=nft.get("logo_url", ""),
                    amount=nft.get("amount", 0.0),
                    usd_value=nft.get("usd_value", 0.0),
                ))

        # Fetch transaction history (just Ethereum, limited)
        print(f"[API] Fetching transaction history...")
        history_data = self.fetch_history(address, "eth", page_count=20)
        if history_data:
            raw_data["history"] = history_data
            history_list = history_data.get("data", [])
            if isinstance(history_list, dict):
                history_list = history_list.get("history_list", [])
            for tx in history_list:
                profile.transactions.append(Transaction(
                    tx_id=tx.get("id", ""),
                    chain=tx.get("chain", "eth"),
                    time_at=tx.get("time_at", 0),
                    category=tx.get("cate_id", ""),
                    project_id=tx.get("project_id"),
                    token_approve=tx.get("token_approve"),
                    receives=tx.get("receives", []),
                    sends=tx.get("sends", []),
                    protocol=tx.get("protocol"),
                ))

        profile.raw_api_data = raw_data
        return profile


# ---------------------------------------------------------------------------
# Playwright Browser Scraper
# ---------------------------------------------------------------------------

class DeBankScraper:
    """
    Playwright-based scraper for DeBank profile pages.
    Intercepts network requests to extract portfolio data.
    """

    DEBANK_BASE = "https://debank.com"
    API_BASE = "https://api.debank.com"

    def __init__(self, headless: bool = True, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout
        self._api_responses: Dict[str, Any] = {}
        self._page = None
        self._browser = None
        self._playwright = None

    def _handle_response(self, response):
        """Intercept and store API responses."""
        url = response.url
        if self.API_BASE in url:
            endpoint = url.replace(self.API_BASE, "").replace("/", "_").strip("_")
            # Add query params for uniqueness
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "id" in qs:
                endpoint += f"_{qs['id'][0][:8]}"
            if "user_addr" in qs:
                endpoint += f"_{qs['user_addr'][0][:8]}"
            if "chain" in qs:
                endpoint += f"_{qs['chain'][0]}"

            try:
                body = response.json()
                self._api_responses[endpoint] = {
                    "url": url,
                    "status": response.status,
                    "data": body,
                }
            except Exception:
                pass

    def _build_profile_url(self, address: str) -> str:
        return f"{self.DEBANK_BASE}/profile/{address.lower().strip()}"

    def _unwrap_data(self, resp_data: Dict) -> Any:
        """Unwrap DeBank's nested {data: {...}} response structure."""
        if isinstance(resp_data, dict) and "data" in resp_data:
            return resp_data["data"]
        return resp_data

    def _extract_total_value(self) -> float:
        for key, resp in self._api_responses.items():
            if key.startswith("user?") and "config" not in key and "banner" not in key and "vip" not in key and "used_chains" not in key:
                if resp["status"] == 200:
                    data = self._unwrap_data(resp["data"])
                    if isinstance(data, dict):
                        user = data.get("user", {})
                        desc = user.get("desc", {})
                        return desc.get("usd_value", 0.0)
        return 0.0

    def _extract_user_meta(self, profile: DeBankProfile):
        for key, resp in self._api_responses.items():
            if key.startswith("user?") and "config" not in key and "banner" not in key and "vip" not in key and "used_chains" not in key:
                if resp["status"] == 200:
                    data = self._unwrap_data(resp["data"])
                    if isinstance(data, dict):
                        user = data.get("user", {})
                        desc = user.get("desc", {})
                        profile.display_name = desc.get("name")
                        profile.bio = user.get("bio", "")
                        profile.follower_count = user.get("follower_count", 0)
                        profile.following_count = user.get("following_count", 0)
                        profile.is_vip = user.get("is_vip", False)
                        profile.is_pro = user.get("is_pro", False)
                        profile.web3_id = user.get("web3_id")
                        profile.tags = desc.get("tags", [])
                        profile.used_chains = desc.get("used_chains", [])
                        break

    def _extract_chain_balances(self, profile: DeBankProfile) -> List[ChainBalance]:
        balances = []
        # Get chain info from chain_list
        chain_map = {}
        for key, resp in self._api_responses.items():
            if "chain_list" in key and resp["status"] == 200:
                data = self._unwrap_data(resp["data"])
                if isinstance(data, dict):
                    for chain in data.get("chains", []):
                        chain_map[chain["id"]] = chain

        # Get used chains - try dedicated endpoint first, then fall back to profile
        used_chains = []
        for key, resp in self._api_responses.items():
            if key.startswith("user_used_chains") and resp["status"] == 200:
                data = self._unwrap_data(resp["data"])
                if isinstance(data, dict):
                    used_chains = data.get("used_chains", [])
                break

        if not used_chains and profile.used_chains:
            used_chains = profile.used_chains

        # Calculate per-chain values from tokens
        chain_values = {}
        for key, resp in self._api_responses.items():
            if ("token_balance" in key or "cache_balance" in key) and resp["status"] == 200:
                tokens = self._unwrap_data(resp["data"])
                if isinstance(tokens, list):
                    for token in tokens:
                        chain = token.get("chain", "")
                        amount = token.get("amount", 0.0)
                        price = token.get("price", 0.0)
                        chain_values[chain] = chain_values.get(chain, 0.0) + (amount * price)

        for chain_id in used_chains:
            chain_info = chain_map.get(chain_id, {})
            balances.append(ChainBalance(
                chain_id=chain_id,
                chain_name=chain_info.get("name", chain_id),
                logo_url=chain_info.get("logo_url", ""),
                native_token_id=chain_info.get("token_id", ""),
                wrapped_token_id=chain_info.get("wrapped", ""),
                usd_value=chain_values.get(chain_id, 0.0),
            ))

        return balances

    def _extract_tokens(self) -> List[TokenInfo]:
        tokens = []
        seen = set()
        for key, resp in self._api_responses.items():
            # Match both per-chain (token/balance_list) and the all-chain wallet
            # cache (token/cache_balance_list) endpoints — the profile page loads
            # wallet holdings from the cache endpoint, so missing it dropped every
            # wallet token.
            if ("token_balance" in key or "cache_balance" in key) and resp["status"] == 200:
                data = self._unwrap_data(resp["data"])
                if isinstance(data, list):
                    for token in data:
                        token_id = token.get("id", "")
                        chain = token.get("chain", "")
                        unique_key = f"{chain}_{token_id}"
                        if unique_key in seen:
                            continue
                        seen.add(unique_key)

                        amount = token.get("amount", 0.0)
                        price = token.get("price", 0.0)
                        usd_value = amount * price if amount and price else 0.0

                        tokens.append(TokenInfo(
                            id=token_id,
                            chain=chain,
                            name=token.get("name", "Unknown"),
                            symbol=token.get("symbol", "") or token.get("optimized_symbol", ""),
                            decimals=token.get("decimals", 18),
                            logo_url=token.get("logo_url", ""),
                            price=price,
                            amount=amount,
                            raw_amount=token.get("balance", 0),
                            usd_value=usd_value,
                            is_verified=token.get("is_verified", False),
                            is_core=token.get("is_core", False),
                            is_wallet=token.get("is_wallet", False),
                            protocol_id=token.get("protocol_id") or None,
                            credit_score=token.get("credit_score", 0.0),
                            price_24h_change=token.get("price_24h_change", 0.0),
                            is_scam=token.get("is_scam", False),
                            is_suspicious=token.get("is_suspicious", False),
                        ))
        tokens.sort(key=lambda t: t.usd_value, reverse=True)
        return tokens

    def _extract_protocols(self) -> List[ProtocolPosition]:
        protocols = []
        for key, resp in self._api_responses.items():
            if "portfolio_project" in key and resp["status"] == 200:
                data = self._unwrap_data(resp["data"])
                if isinstance(data, list):
                    for protocol in data:
                        for item in protocol.get("portfolio_item_list", []):
                            stats = item.get("stats", {})
                            asset_tokens = []
                            for token in item.get("asset_token_list", []):
                                t_amount = token.get("amount", 0.0)
                                t_price = token.get("price", 0.0)
                                asset_tokens.append(TokenInfo(
                                    id=token.get("id", ""),
                                    chain=token.get("chain", ""),
                                    name=token.get("name", ""),
                                    symbol=token.get("symbol", ""),
                                    decimals=token.get("decimals", 18),
                                    logo_url=token.get("logo_url", ""),
                                    price=t_price,
                                    amount=t_amount,
                                    raw_amount=0,
                                    usd_value=t_amount * t_price,
                                    is_verified=token.get("is_verified", False),
                                    is_core=token.get("is_core", False),
                                ))

                            protocols.append(ProtocolPosition(
                                protocol_id=protocol.get("id", ""),
                                protocol_name=protocol.get("name", ""),
                                chain=protocol.get("chain", ""),
                                logo_url=protocol.get("logo_url", ""),
                                site_url=protocol.get("site_url", ""),
                                tvl=protocol.get("tvl", 0.0),
                                asset_usd_value=stats.get("asset_usd_value", 0.0),
                                debt_usd_value=stats.get("debt_usd_value", 0.0),
                                net_usd_value=stats.get("net_usd_value", 0.0),
                                detail_types=item.get("detail_types", []),
                                asset_tokens=asset_tokens,
                            ))
        return protocols

    def _extract_nfts(self) -> List[NFTItem]:
        nfts = []
        for key, resp in self._api_responses.items():
            if "nft" in key and resp["status"] == 200:
                data = self._unwrap_data(resp["data"])
                if isinstance(data, list):
                    for nft in data:
                        nfts.append(NFTItem(
                            id=nft.get("id", ""),
                            chain=nft.get("chain", ""),
                            name=nft.get("name", ""),
                            collection_id=nft.get("collection_id", ""),
                            collection_name=nft.get("collection_name", ""),
                            logo_url=nft.get("logo_url", ""),
                            amount=nft.get("amount", 0.0),
                            usd_value=nft.get("usd_value", 0.0),
                        ))
        return nfts

    def _extract_transactions(self) -> List[Transaction]:
        transactions = []
        for key, resp in self._api_responses.items():
            if "history" in key and resp["status"] == 200:
                data = self._unwrap_data(resp["data"])
                if isinstance(data, dict):
                    history_list = data.get("history_list", [])
                elif isinstance(data, list):
                    history_list = data
                else:
                    history_list = []
                for tx in history_list:
                    transactions.append(Transaction(
                        tx_id=tx.get("id", ""),
                        chain=tx.get("chain", ""),
                        time_at=tx.get("time_at", 0),
                        category=tx.get("cate_id", ""),
                        project_id=tx.get("project_id"),
                        token_approve=tx.get("token_approve"),
                        receives=tx.get("receives", []),
                        sends=tx.get("sends", []),
                        protocol=tx.get("protocol"),
                    ))
        return transactions

    def _click_tabs(self, page):
        """Click through tabs to trigger API calls for tokens, NFTs, history."""
        tab_selectors = [
            "text=Tokens",
            "text=NFT",
            "text=History",
            "text=Approval",
            "text=DeFi",
        ]
        for selector in tab_selectors:
            try:
                tab = page.query_selector(selector)
                if tab:
                    tab.click()
                    time.sleep(2.0)
            except Exception:
                pass

    def scrape(self, address: str, wait_seconds: float = 8.0) -> DeBankProfile:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "Playwright is required. Install it with:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )

        url = self._build_profile_url(address)
        self._api_responses = {}

        with sync_playwright() as p:
            self._playwright = p
            self._browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )

            context = self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()
            self._page = page
            page.on("response", self._handle_response)

            print(f"[INFO] Navigating to {url}")
            page.goto(url, wait_until="networkidle", timeout=60000)

            print(f"[INFO] Scrolling page to trigger data loading...")
            for _ in range(3):
                page.evaluate("window.scrollBy(0, document.body.scrollHeight / 3)")
                time.sleep(1.5)

            print(f"[INFO] Waiting {wait_seconds}s for API calls...")
            time.sleep(wait_seconds)

            self._click_tabs(page)

            profile = DeBankProfile(address=address.lower().strip())
            profile.total_usd_value = self._extract_total_value()
            self._extract_user_meta(profile)
            profile.chain_balances = self._extract_chain_balances(profile)
            profile.tokens = self._extract_tokens()
            profile.protocols = self._extract_protocols()
            profile.nfts = self._extract_nfts()
            profile.transactions = self._extract_transactions()
            profile.raw_api_data = self._api_responses

            page.close()
            context.close()
            self._browser.close()

            return profile

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()


# ---------------------------------------------------------------------------
# CLI & Entry Point
# ---------------------------------------------------------------------------

def print_summary(profile: DeBankProfile):
    print(f"\n{'='*60}")
    print(f"  SCRAPE SUMMARY")
    print(f"{'='*60}")
    print(f"Address: {profile.address}")
    print(f"Display Name: {profile.display_name or 'N/A'}")
    print(f"Web3 ID: {profile.web3_id or 'N/A'}")
    print(f"Total Value: ${profile.total_usd_value:,.2f}")
    print(f"Chains: {len(profile.chain_balances)}")
    print(f"Tokens: {len(profile.tokens)}")
    print(f"Protocols: {len(profile.protocols)}")
    print(f"NFTs: {len(profile.nfts)}")
    print(f"Transactions: {len(profile.transactions)}")
    print(f"Followers: {profile.follower_count}")
    print(f"Following: {profile.following_count}")
    if profile.tags:
        print(f"Tags: {', '.join(t['name'] for t in profile.tags)}")
    print(f"{'='*60}")

    if profile.tokens:
        print(f"\nTop 10 Tokens:")
        for i, t in enumerate(profile.tokens[:10], 1):
            symbol = t.symbol or t.name
            print(f"  {i}. {symbol} ({t.chain}): ${t.usd_value:,.2f} ({t.amount:,.4f} @ ${t.price:,.4f})")

    if profile.chain_balances:
        print(f"\nChain Breakdown:")
        for chain in sorted(profile.chain_balances, key=lambda c: c.usd_value, reverse=True):
            if chain.usd_value > 0:
                print(f"  {chain.chain_name}: ${chain.usd_value:,.2f}")

    if profile.protocols:
        print(f"\nTop 5 DeFi Positions:")
        for i, p in enumerate(sorted(profile.protocols, key=lambda x: x.net_usd_value, reverse=True)[:5], 1):
            print(f"  {i}. {p.protocol_name} ({p.chain}): ${p.net_usd_value:,.2f}")


def main():
    parser = argparse.ArgumentParser(
        description="DeBank Profile Scraper - Extract portfolio data from DeBank"
    )
    parser.add_argument("address", help="Crypto wallet address to scrape")
    parser.add_argument("--api-only", action="store_true", help="Use direct API calls (no browser)")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser headless")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--wait", type=float, default=8.0, help="Seconds to wait for page load")
    parser.add_argument("--output", "-o", default="debank_profile.json", help="Output JSON file")
    parser.add_argument("--pretty", action="store_true", default=True, help="Pretty-print JSON")
    parser.add_argument("--rate-limit", type=float, default=0.5, help="API rate limit (seconds)")

    args = parser.parse_args()

    headless = False if args.no_headless else args.headless

    print(f"{'='*60}")
    print(f"  DeBank Dynamic Scraper")
    print(f"{'='*60}")
    print(f"Address: {args.address}")
    print(f"Mode: {'Direct API' if args.api_only else 'Browser (Playwright)'}")
    if not args.api_only:
        print(f"Headless: {headless}")
        print(f"Wait time: {args.wait}s")
    print(f"Output: {args.output}")
    print(f"{'='*60}\n")

    try:
        if args.api_only:
            client = DeBankAPIClient(rate_limit=args.rate_limit)
            profile = client.scrape(args.address)
        else:
            scraper = DeBankScraper(headless=headless)
            profile = scraper.scrape(args.address, wait_seconds=args.wait)

        print_summary(profile)

        # Save to file
        indent = 2 if args.pretty else None
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(profile.to_json(indent=indent))
        print(f"\n[OK] Data saved to {args.output}")

    except ImportError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Scraping failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
