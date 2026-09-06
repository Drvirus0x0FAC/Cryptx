#!/usr/bin/env python3
"""
OpenSea NFT Scraper
====================
A hybrid scraper for OpenSea profile pages using GraphQL API + Playwright DOM extraction.
Extracts NFT portfolio data for OSINT and digital-identity investigation.

Data extracted:
  - Profile: display name, bio, follower count, portfolio value
  - Collections owned: name, slug, count, floor price, total volume
  - NFTs: name, image, token ID, collection, traits, last sale price
  - Activity: sales, transfers, listings, offers

Usage:
    python opensea_scraper.py <address>
    python opensea_scraper.py 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

Install:
    pip install playwright requests
    playwright install chromium

Author: AI Assistant
"""

import json
import sys
import time
import argparse
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class OpenSeaProfile:
    address: str
    display_name: Optional[str] = None
    username: Optional[str] = None
    bio: str = ""
    profile_image_url: Optional[str] = None
    banner_image_url: Optional[str] = None
    follower_count: int = 0
    following_count: int = 0
    is_verified: bool = False
    is_staff: bool = False
    portfolio_value_usd: float = 0.0
    nft_percentage: float = 0.0
    token_percentage: float = 0.0

    collections: List["NFTCollection"] = field(default_factory=list)
    nfts: List["NFTAsset"] = field(default_factory=list)
    events: List["Event"] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


@dataclass
class NFTCollection:
    name: str
    slug: str
    description: str = ""
    image_url: Optional[str] = None
    banner_url: Optional[str] = None
    category: str = ""
    item_count: int = 0
    owner_count: int = 0
    floor_price: float = 0.0
    floor_price_currency: str = "ETH"
    total_volume: float = 0.0
    total_volume_currency: str = "ETH"
    traits: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NFTAsset:
    token_id: str
    name: str
    collection_name: str = ""
    collection_slug: str = ""
    image_url: Optional[str] = None
    animation_url: Optional[str] = None
    external_url: Optional[str] = None
    permalink: Optional[str] = None
    contract_address: str = ""
    schema_name: str = "ERC721"  # or ERC1155
    owner_address: str = ""
    traits: List[Dict[str, Any]] = field(default_factory=list)
    last_sale_price: float = 0.0
    last_sale_currency: str = ""
    last_sale_date: Optional[str] = None
    current_price: float = 0.0
    current_price_currency: str = ""
    rarity_score: Optional[float] = None
    rarity_rank: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Event:
    event_type: str  # sale, transfer, listing, offer, mint
    created_date: str
    asset_name: str = ""
    asset_token_id: str = ""
    collection_slug: str = ""
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    price: float = 0.0
    currency: str = "ETH"
    transaction_hash: Optional[str] = None
    quantity: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# GraphQL API Client (for profile stats)
# ---------------------------------------------------------------------------

class OpenSeaGraphQLClient:
    """Direct GraphQL client for OpenSea's public API."""

    GQL_URL = "https://gql.opensea.io/graphql"
    HEADERS = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://opensea.io",
        "Referer": "https://opensea.io/",
    }

    def __init__(self):
        import requests
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _query(self, query: str, variables: Dict[str, Any]) -> Optional[Dict]:
        try:
            resp = self.session.post(self.GQL_URL, json={"query": query, "variables": variables}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if "errors" in data:
                    return None
                return data.get("data")
            return None
        except Exception as e:
            print(f"[WARN] GraphQL error: {e}")
            return None

    def fetch_profile(self, address: str) -> Optional[Dict]:
        """Fetch profile stats via GraphQL."""
        query = """
        query ProfileQuery($address: Address!) {
            profileByAddress(address: $address) {
                __typename
                ... on Profile {
                    address
                    username
                    displayName
                    bio
                    followerCount
                    followingCount
                    isVerified
                    isStaff
                    portfolioSummary {
                        estimatedValue { usd }
                        nftPercentageOfPortfolio
                        tokenPercentageOfPortfolio
                    }
                }
            }
        }
        """
        data = self._query(query, {"address": address.lower()})
        if data:
            profile = data.get("profileByAddress", {})
            if profile and profile.get("__typename") == "Profile":
                summary = profile.get("portfolioSummary", {})
                return {
                    "address": profile.get("address"),
                    "username": profile.get("username"),
                    "display_name": profile.get("displayName"),
                    "bio": profile.get("bio", ""),
                    "follower_count": profile.get("followerCount", 0),
                    "following_count": profile.get("followingCount", 0),
                    "is_verified": profile.get("isVerified", False),
                    "is_staff": profile.get("isStaff", False),
                    "portfolio_value_usd": summary.get("estimatedValue", {}).get("usd", 0.0),
                    "nft_percentage": summary.get("nftPercentageOfPortfolio", 0.0),
                    "token_percentage": summary.get("tokenPercentageOfPortfolio", 0.0),
                }
        return None


# ---------------------------------------------------------------------------
# Playwright Network Interception Scraper (for NFTs, collections, activity)
# ---------------------------------------------------------------------------

class OpenSeaScraper:
    """Playwright-based scraper that intercepts GraphQL API calls."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._api_responses: Dict[str, Any] = {}

    def _build_profile_url(self, address: str) -> str:
        return f"https://opensea.io/{address.lower().strip()}"

    def _handle_response(self, response):
        """Intercept GraphQL responses."""
        url = response.url
        if "gql.opensea.io" in url or "api.opensea.io" in url:
            try:
                body = response.json()
                # Use operationName or query snippet as key
                key = url.replace("https://", "").replace("/", "_")
                if isinstance(body, dict):
                    if "operationName" in body:
                        key = f"{body['operationName']}_{int(time.time()*1000)}"
                    elif "data" in body and body.get("data"):
                        # Try to infer from data keys
                        data_keys = list(body["data"].keys()) if isinstance(body["data"], dict) else []
                        if data_keys:
                            key = f"{'_'.join(data_keys)}_{int(time.time()*1000)}"
                self._api_responses[key] = {
                    "url": url,
                    "status": response.status,
                    "data": body,
                }
            except Exception:
                pass

    def _extract_collections_from_graphql(self) -> List[NFTCollection]:
        """Extract collections from intercepted GraphQL responses."""
        collections = []
        seen = set()

        for key, resp in self._api_responses.items():
            data = resp.get("data", {})
            if not isinstance(data, dict):
                continue
            data = data.get("data", {})  # Unwrap GraphQL response wrapper
            if not isinstance(data, dict):
                continue

            for root_key, root_val in data.items():
                if not isinstance(root_val, dict):
                    continue

                # OpenSea v2 uses "items" array directly
                items = root_val.get("items", [])
                if not isinstance(items, list):
                    continue

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    # userCollections: item has "collection" and "ownership"
                    coll = item.get("collection", {}) if isinstance(item.get("collection"), dict) else item
                    if not isinstance(coll, dict):
                        continue

                    name = coll.get("name", "") or coll.get("displayName", "")
                    slug = coll.get("slug", "") or coll.get("collectionSlug", "")
                    if not name and not slug:
                        continue

                    unique = f"{slug}_{name}"
                    if unique in seen:
                        continue
                    seen.add(unique)

                    # Ownership stats
                    ownership = item.get("ownership", {}) if isinstance(item.get("ownership"), dict) else {}
                    item_count = 0
                    owner_count = 0
                    floor_price = 0.0
                    total_volume = 0.0

                    if isinstance(ownership, dict):
                        item_count = ownership.get("itemCount", 0) or ownership.get("totalQuantity", 0)
                        value_data = ownership.get("value", {}) if isinstance(ownership.get("value"), dict) else {}
                        if value_data:
                            native = value_data.get("native", {}) if isinstance(value_data.get("native"), dict) else {}
                            total_volume = native.get("unit", 0) or 0

                    # Floor price from collection
                    floor_data = coll.get("floorPrice", {}) if isinstance(coll.get("floorPrice"), dict) else {}
                    if floor_data:
                        price_per = floor_data.get("pricePerItem", {}) if isinstance(floor_data.get("pricePerItem"), dict) else {}
                        if price_per:
                            floor_price = price_per.get("usd", 0) or 0

                    collections.append(NFTCollection(
                        name=name,
                        slug=slug,
                        description=coll.get("description", ""),
                        image_url=coll.get("imageUrl") or coll.get("logoUrl") or coll.get("image_url"),
                        banner_url=coll.get("bannerUrl") or coll.get("banner_url"),
                        category=coll.get("category", ""),
                        item_count=item_count,
                        owner_count=owner_count,
                        floor_price=floor_price,
                        total_volume=total_volume,
                    ))

                # Also check for edges/node pattern (older Relay style)
                edges = root_val.get("edges", [])
                if isinstance(edges, list):
                    for edge in edges:
                        node = edge.get("node", {}) if isinstance(edge, dict) else edge
                        if not isinstance(node, dict):
                            continue
                        name = node.get("name", "") or node.get("displayName", "")
                        slug = node.get("slug", "") or node.get("collectionSlug", "")
                        if not name and not slug:
                            continue
                        unique = f"{slug}_{name}"
                        if unique in seen:
                            continue
                        seen.add(unique)
                        collections.append(NFTCollection(
                            name=name,
                            slug=slug,
                            description=node.get("description", ""),
                            image_url=node.get("imageUrl") or node.get("logoUrl"),
                            banner_url=node.get("bannerUrl"),
                            category=node.get("category", ""),
                            item_count=0,
                            owner_count=0,
                            floor_price=0.0,
                            total_volume=0.0,
                        ))

        return collections

    def _extract_nfts_from_graphql(self) -> List[NFTAsset]:
        """Extract NFTs from intercepted GraphQL responses."""
        nfts = []
        seen = set()

        for key, resp in self._api_responses.items():
            data = resp.get("data", {})
            if not isinstance(data, dict):
                continue
            data = data.get("data", {})  # Unwrap GraphQL response wrapper
            if not isinstance(data, dict):
                continue

            for root_key, root_val in data.items():
                if not isinstance(root_val, dict):
                    continue

                # OpenSea v2 uses "items" array directly
                items = root_val.get("items", [])
                if not isinstance(items, list):
                    continue

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    token_id = str(item.get("tokenId", "")) or str(item.get("token_id", "")) or str(item.get("identifier", ""))
                    name = item.get("name", "") or item.get("displayName", "") or item.get("title", "")
                    if not name and not token_id:
                        continue

                    unique = f"{token_id}_{name}"
                    if unique in seen:
                        continue
                    seen.add(unique)

                    # Collection info
                    collection = item.get("collection", {}) if isinstance(item.get("collection"), dict) else {}
                    coll_name = collection.get("name", "") if isinstance(collection, dict) else ""
                    coll_slug = collection.get("slug", "") if isinstance(collection, dict) else ""

                    # Floor price / top offer
                    current_price = 0.0
                    current_currency = "ETH"
                    top_offer = collection.get("topOffer", {}) if isinstance(collection, dict) else {}
                    if isinstance(top_offer, dict):
                        ppi = top_offer.get("pricePerItem", {}) if isinstance(top_offer.get("pricePerItem"), dict) else {}
                        if ppi:
                            current_price = ppi.get("usd", 0) or 0
                            token = ppi.get("token", {}) if isinstance(ppi.get("token"), dict) else {}
                            current_currency = token.get("symbol", "ETH") if isinstance(token, dict) else "ETH"

                    # Last sale
                    last_sale = item.get("lastSale", {}) if isinstance(item.get("lastSale"), dict) else {}
                    last_price = 0.0
                    last_currency = "ETH"
                    last_date = ""
                    if isinstance(last_sale, dict):
                        last_price = last_sale.get("price", 0) or 0
                        last_currency = last_sale.get("paymentToken", {}).get("symbol", "ETH") if isinstance(last_sale.get("paymentToken"), dict) else "ETH"
                        last_date = last_sale.get("eventTimestamp", "")

                    # Contract
                    contract_address = item.get("contractAddress", "") or ""
                    schema_name = item.get("standard", "ERC721") or "ERC721"

                    nfts.append(NFTAsset(
                        token_id=token_id,
                        name=name,
                        collection_name=coll_name,
                        collection_slug=coll_slug,
                        image_url=item.get("imageUrl") or item.get("image_url") or item.get("image"),
                        animation_url=item.get("animationUrl") or item.get("animation_url"),
                        external_url=item.get("externalUrl") or item.get("external_url"),
                        permalink=item.get("permalink") or item.get("openseaUrl"),
                        contract_address=contract_address,
                        schema_name=schema_name,
                        owner_address=item.get("owner", {}).get("address", "") if isinstance(item.get("owner"), dict) else "",
                        traits=item.get("traits", []) if isinstance(item.get("traits"), list) else [],
                        last_sale_price=float(last_price) if last_price else 0.0,
                        last_sale_currency=last_currency,
                        last_sale_date=last_date,
                        current_price=float(current_price) if current_price else 0.0,
                        current_price_currency=current_currency,
                        rarity_score=item.get("rarity") if isinstance(item.get("rarity"), (int, float)) else None,
                        rarity_rank=item.get("rarityRank") if isinstance(item.get("rarityRank"), int) else None,
                    ))

                # Also handle edges/node pattern
                edges = root_val.get("edges", [])
                if isinstance(edges, list):
                    for edge in edges:
                        node = edge.get("node", {}) if isinstance(edge, dict) else edge
                        if not isinstance(node, dict):
                            continue
                        name = node.get("name", "") or node.get("displayName", "") or node.get("title", "")
                        token_id = str(node.get("tokenId", "")) or str(node.get("token_id", "")) or str(node.get("identifier", ""))
                        if not name and not token_id:
                            continue
                        unique = f"{token_id}_{name}"
                        if unique in seen:
                            continue
                        seen.add(unique)

                        collection = node.get("collection", {}) if isinstance(node.get("collection"), dict) else {}
                        coll_name = collection.get("name", "") if isinstance(collection, dict) else ""
                        coll_slug = collection.get("slug", "") if isinstance(collection, dict) else ""

                        nfts.append(NFTAsset(
                            token_id=token_id,
                            name=name,
                            collection_name=coll_name,
                            collection_slug=coll_slug,
                            image_url=node.get("imageUrl") or node.get("image_url"),
                            animation_url=node.get("animationUrl") or node.get("animation_url"),
                            external_url=node.get("externalUrl") or node.get("external_url"),
                            permalink=node.get("permalink") or node.get("openseaUrl"),
                            contract_address=node.get("assetContract", {}).get("address", "") if isinstance(node.get("assetContract"), dict) else "",
                            schema_name=node.get("assetContract", {}).get("tokenStandard", "ERC721") if isinstance(node.get("assetContract"), dict) else "ERC721",
                            owner_address=node.get("owner", {}).get("address", "") if isinstance(node.get("owner"), dict) else "",
                            traits=node.get("traits", []) if isinstance(node.get("traits"), list) else [],
                            last_sale_price=0.0,
                            last_sale_currency="ETH",
                            current_price=0.0,
                            current_price_currency="ETH",
                        ))

        return nfts

    def _extract_events_from_graphql(self) -> List[Event]:
        """Extract events from intercepted GraphQL responses."""
        events = []
        seen = set()
        for key, resp in self._api_responses.items():
            data = resp.get("data", {})
            if not isinstance(data, dict):
                continue
            data = data.get("data", {})  # Unwrap GraphQL response wrapper
            if not isinstance(data, dict):
                continue
            for root_key, root_val in data.items():
                if not isinstance(root_val, dict):
                    continue
                edges = root_val.get("edges", [])
                if isinstance(edges, list):
                    for edge in edges:
                        node = edge.get("node", {}) if isinstance(edge, dict) else edge
                        if not isinstance(node, dict):
                            continue
                        event_id = node.get("id", "") or str(node.get("eventId", ""))
                        if not event_id:
                            event_id = f"{node.get('eventType', '')}_{node.get('createdDate', '')}"
                        if event_id in seen:
                            continue
                        seen.add(event_id)

                        price = 0.0
                        currency = "ETH"
                        price_data = node.get("price", {}) or {}
                        if isinstance(price_data, dict):
                            price = price_data.get("quantity", 0) or price_data.get("eth", 0) or 0
                            currency = price_data.get("asset", {}).get("symbol", "ETH") if isinstance(price_data.get("asset"), dict) else "ETH"

                        asset = node.get("asset", {}) or {}
                        asset_name = asset.get("name", "") if isinstance(asset, dict) else ""
                        asset_token_id = str(asset.get("tokenId", "")) if isinstance(asset, dict) else ""
                        collection = asset.get("collection", {}) if isinstance(asset, dict) else {}
                        collection_slug = collection.get("slug", "") if isinstance(collection, dict) else ""

                        from_addr = node.get("fromAccount", {}).get("address", "") if isinstance(node.get("fromAccount"), dict) else ""
                        to_addr = node.get("toAccount", {}).get("address", "") if isinstance(node.get("toAccount"), dict) else ""

                        events.append(Event(
                            event_type=node.get("eventType", "").lower() or "unknown",
                            created_date=node.get("createdDate", ""),
                            asset_name=asset_name,
                            asset_token_id=asset_token_id,
                            collection_slug=collection_slug,
                            from_address=from_addr or None,
                            to_address=to_addr or None,
                            price=float(price) if price else 0.0,
                            currency=currency,
                            transaction_hash=node.get("transaction", {}).get("transactionHash") if isinstance(node.get("transaction"), dict) else None,
                            quantity=node.get("quantity", 1),
                        ))
        return events

    def _extract_profile_from_graphql(self) -> Dict[str, Any]:
        """Extract additional profile data from intercepted responses."""
        for key, resp in self._api_responses.items():
            data = resp.get("data", {})
            if isinstance(data, dict) and "profileByAddress" in data.get("data", {}):
                profile = data["data"]["profileByAddress"]
                if isinstance(profile, dict) and profile.get("__typename") == "Profile":
                    summary = profile.get("portfolioSummary", {})
                    return {
                        "address": profile.get("address"),
                        "username": profile.get("username"),
                        "display_name": profile.get("displayName"),
                        "bio": profile.get("bio", ""),
                        "follower_count": profile.get("followerCount", 0),
                        "following_count": profile.get("followingCount", 0),
                        "is_verified": profile.get("isVerified", False),
                        "is_staff": profile.get("isStaff", False),
                        "portfolio_value_usd": summary.get("estimatedValue", {}).get("usd", 0.0),
                        "nft_percentage": summary.get("nftPercentageOfPortfolio", 0.0),
                        "token_percentage": summary.get("tokenPercentageOfPortfolio", 0.0),
                    }
        return {}

    def scrape(self, address: str, wait_seconds: float = 10.0) -> OpenSeaProfile:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError("Playwright required. Install: pip install playwright && playwright install chromium")

        url = self._build_profile_url(address)
        self._api_responses = {}

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )

            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()
            page.on("response", self._handle_response)

            print(f"[INFO] Navigating to {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            print(f"[INFO] Waiting {wait_seconds}s for page to load...")
            time.sleep(wait_seconds)

            # Scroll to load more content
            print("[INFO] Scrolling to trigger lazy loading...")
            for i in range(5):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(1.5)

            # Click through tabs to trigger more API calls
            tab_selectors = [
                "button:has-text('Collected')",
                "button:has-text('Created')",
                "button:has-text('Favorited')",
                "button:has-text('Activity')",
                "button:has-text('Offers')",
                "button:has-text('Listings')",
            ]
            for selector in tab_selectors:
                try:
                    tabs = page.query_selector_all(selector)
                    for tab in tabs:
                        try:
                            tab.click()
                            time.sleep(2.0)
                            page.evaluate("window.scrollBy(0, window.innerHeight)")
                            time.sleep(1.0)
                        except Exception:
                            pass
                except Exception:
                    pass

            # Also try to find and click any tab-like elements
            try:
                all_buttons = page.query_selector_all("button, [role='tab']")
                for btn in all_buttons:
                    text = btn.inner_text().strip().lower()
                    if any(t in text for t in ["collected", "created", "activity", "offers", "listing"]):
                        try:
                            btn.click()
                            time.sleep(2.0)
                        except Exception:
                            pass
            except Exception:
                pass

            print("[INFO] Extracting data from intercepted API calls...")
            time.sleep(3.0)  # Wait for any final API calls

            # Build profile from intercepted data
            profile = OpenSeaProfile(address=address.lower().strip())
            profile.raw_data = self._api_responses

            # Extract from GraphQL intercepts
            gql_profile = self._extract_profile_from_graphql()
            if gql_profile:
                profile.display_name = gql_profile.get("display_name") or profile.display_name
                profile.username = gql_profile.get("username") or profile.username
                profile.bio = gql_profile.get("bio", "")
                profile.follower_count = gql_profile.get("follower_count", 0)
                profile.following_count = gql_profile.get("following_count", 0)
                profile.is_verified = gql_profile.get("is_verified", False)
                profile.is_staff = gql_profile.get("is_staff", False)
                profile.portfolio_value_usd = gql_profile.get("portfolio_value_usd", 0.0)
                profile.nft_percentage = gql_profile.get("nft_percentage", 0.0)
                profile.token_percentage = gql_profile.get("token_percentage", 0.0)

            profile.collections = self._extract_collections_from_graphql()
            profile.nfts = self._extract_nfts_from_graphql()
            profile.events = self._extract_events_from_graphql()

            page.close()
            context.close()
            browser.close()

            return profile


# ---------------------------------------------------------------------------
# Hybrid Scraper (GraphQL + Playwright)
# ---------------------------------------------------------------------------

class OpenSeaHybridScraper:
    """Combines GraphQL API for stats + Playwright network interception for NFT data."""

    def __init__(self, headless: bool = True):
        self.gql = OpenSeaGraphQLClient()
        self.scraper = OpenSeaScraper(headless=headless)

    def scrape(self, address: str, wait_seconds: float = 10.0) -> OpenSeaProfile:
        address = address.lower().strip()

        # Step 1: Get profile stats via GraphQL (fast, reliable)
        print(f"[GQL] Fetching profile stats for {address}...")
        profile_data = self.gql.fetch_profile(address)

        # Step 2: Get NFT data via Playwright network interception
        print(f"[Browser] Scraping NFT data from OpenSea...")
        dom_profile = self.scraper.scrape(address, wait_seconds=wait_seconds)

        # Merge data: use GraphQL stats if browser didn't capture them
        if profile_data:
            dom_profile.display_name = profile_data.get("display_name") or dom_profile.display_name
            dom_profile.username = profile_data.get("username") or dom_profile.username
            dom_profile.bio = profile_data.get("bio", "")
            dom_profile.follower_count = profile_data.get("follower_count", 0)
            dom_profile.following_count = profile_data.get("following_count", 0)
            dom_profile.is_verified = profile_data.get("is_verified", False)
            dom_profile.is_staff = profile_data.get("is_staff", False)
            dom_profile.portfolio_value_usd = profile_data.get("portfolio_value_usd", 0.0)
            dom_profile.nft_percentage = profile_data.get("nft_percentage", 0.0)
            dom_profile.token_percentage = profile_data.get("token_percentage", 0.0)

        return dom_profile


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_summary(profile: OpenSeaProfile):
    print(f"\n{'='*60}")
    print(f"  OPENSEA SCRAPE SUMMARY")
    print(f"{'='*60}")
    print(f"Address: {profile.address}")
    print(f"Display Name: {profile.display_name or 'N/A'}")
    print(f"Username: {profile.username or 'N/A'}")
    print(f"Bio: {profile.bio or 'N/A'}")
    print(f"Verified: {profile.is_verified}")
    print(f"Staff: {profile.is_staff}")
    print(f"Followers: {profile.follower_count}")
    print(f"Following: {profile.following_count}")
    print(f"Portfolio Value (NFT): ${profile.portfolio_value_usd:,.2f}")
    print(f"NFT % of Portfolio: {profile.nft_percentage:.0%}")
    print(f"Token % of Portfolio: {profile.token_percentage:.0%}")
    print(f"Collections Found: {len(profile.collections)}")
    print(f"NFTs Found: {len(profile.nfts)}")
    print(f"Events Found: {len(profile.events)}")
    print(f"{'='*60}")

    if profile.collections:
        print(f"\nTop Collections:")
        for i, c in enumerate(profile.collections[:10], 1):
            print(f"  {i}. {c.name} (slug: {c.slug})")

    if profile.nfts:
        print(f"\nTop NFTs:")
        for i, n in enumerate(profile.nfts[:10], 1):
            print(f"  {i}. {n.name}")


def main():
    parser = argparse.ArgumentParser(description="OpenSea NFT Scraper - Extract NFT portfolio data")
    parser.add_argument("address", help="Crypto wallet address")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser headless")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--wait", type=float, default=10.0, help="Seconds to wait for page load")
    parser.add_argument("--output", "-o", default="opensea_profile.json", help="Output JSON file")
    parser.add_argument("--pretty", action="store_true", default=True, help="Pretty-print JSON")

    args = parser.parse_args()
    headless = False if args.no_headless else args.headless

    print(f"{'='*60}")
    print(f"  OpenSea NFT Scraper")
    print(f"{'='*60}")
    print(f"Address: {args.address}")
    print(f"Headless: {headless}")
    print(f"Wait time: {args.wait}s")
    print(f"Output: {args.output}")
    print(f"{'='*60}\n")

    try:
        scraper = OpenSeaHybridScraper(headless=headless)
        profile = scraper.scrape(args.address, wait_seconds=args.wait)

        print_summary(profile)

        indent = 2 if args.pretty else None
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(profile.to_json(indent=indent))
        print(f"\n[OK] Data saved to {args.output}")

    except ImportError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
