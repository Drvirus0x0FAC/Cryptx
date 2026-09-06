#!/usr/bin/env python3
"""
Reddit Crypto Address Scraper
=============================
Search Reddit for posts/comments mentioning a given crypto address.
Uses Scrapling for stealth bypass of Reddit's anti-bot protections.

Features:
- No API key required (uses Reddit's web search + JSON API)
- Scrapling stealth engine for Cloudflare/bot detection bypass
- Post + comment extraction
- Pagination support
- Full post metadata (title, author, subreddit, score, timestamp, content)
- Batch processing with multiple addresses
- Structured JSON/CSV output
- Proxy support
- Deduplication

Requirements:
    pip install scrapling requests beautifulsoup4 lxml

Usage:
    python reddit_scraper.py --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045
    python reddit_scraper.py --address 0x47666Fab8bd0Ac7003bce3f5C3585383F09486E2 --type comments
    python reddit_scraper.py --batch addresses.txt --output results.json
    python reddit_scraper.py --address 0x... --pages 3 --type posts
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
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Any, Set
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from urllib.parse import urljoin, quote, urlparse

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

# Scrapling (primary stealth engine)
try:
    from scrapling import StealthyFetcher
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False
    StealthyFetcher = None

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

REDDIT_BASE = "https://www.reddit.com"
REDDIT_OLD = "https://old.reddit.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class RedditPost:
    """Represents a Reddit post mentioning a crypto address."""
    post_id: str
    title: str
    author: str
    subreddit: str
    permalink: str
    url: str
    selftext: str = ""
    score: int = 0
    num_comments: int = 0
    created_utc: Optional[float] = None
    created_iso: Optional[str] = None
    post_type: str = "post"  # "post" or "comment"
    is_self: bool = False
    domain: str = ""
    thumbnail: str = ""
    upvote_ratio: Optional[float] = None
    distinguished: Optional[str] = None
    over_18: bool = False
    spoiler: bool = False
    locked: bool = False
    stickied: bool = False
    address_mentioned: str = ""
    scraped_at: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now(timezone.utc).isoformat()
        if self.created_utc and not self.created_iso:
            self.created_iso = datetime.fromtimestamp(self.created_utc, tz=timezone.utc).isoformat()
        if not self.domain and self.url:
            parsed = urlparse(self.url)
            self.domain = parsed.netloc

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def full_permalink(self) -> str:
        return f"{REDDIT_BASE}{self.permalink}"

    @property
    def short_summary(self) -> str:
        return f"[{self.subreddit}] {self.title[:60]}... by u/{self.author} ({self.score} pts)"


@dataclass
class RedditComment:
    """Represents a Reddit comment mentioning a crypto address."""
    comment_id: str
    body: str
    author: str
    subreddit: str
    permalink: str
    parent_id: str = ""
    link_id: str = ""
    score: int = 0
    created_utc: Optional[float] = None
    created_iso: Optional[str] = None
    is_submitter: bool = False
    depth: int = 0
    edited: bool = False
    distinguished: Optional[str] = None
    address_mentioned: str = ""
    scraped_at: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now(timezone.utc).isoformat()
        if self.created_utc and not self.created_iso:
            self.created_iso = datetime.fromtimestamp(self.created_utc, tz=timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def full_permalink(self) -> str:
        return f"{REDDIT_BASE}{self.permalink}"


# =============================================================================
# Core Scraper
# =============================================================================

class RedditScraper:
    """Scraper for finding Reddit posts/comments mentioning crypto addresses."""

    def __init__(
        self,
        proxy: Optional[str] = None,
        rate_limit_delay: float = 2.0,
        max_pages: int = 3,
        results_per_page: int = 25,
        search_type: str = "posts",  # "posts" or "comments" or "all"
        sort: str = "new",  # "new", "relevance", "top"
        time_filter: str = "all",  # "all", "year", "month", "week", "day"
        use_scrapling: bool = True,
    ):
        self.proxy = proxy
        self.rate_limit_delay = rate_limit_delay
        self.max_pages = max_pages
        self.results_per_page = results_per_page
        self.search_type = search_type
        self.sort = sort
        self.time_filter = time_filter
        self.use_scrapling = use_scrapling and SCRAPLING_AVAILABLE
        self._session = self._init_session()
        self._seen_ids: Set[str] = set()
        self._last_request_time = 0

    def _init_session(self) -> Optional[requests.Session]:
        if requests is None:
            return None
        session = requests.Session()
        session.headers.update(HEADERS)
        retry = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        if self.proxy:
            session.proxies.update({"http": self.proxy, "https": self.proxy})
        return session

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - elapsed + random.uniform(0.5, 1.5)
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _is_bot_block(self, html: str) -> bool:
        """Check if Reddit returned a bot block page."""
        if not html or len(html) < 1000:
            return True
        # Look for specific bot block patterns (not just the word "bot")
        block_patterns = [
            "blocked by reddit",
            "you have been blocked",
            "access denied",
            "robot verification",
            "please enable javascript",
            "checking your browser",
            "cf-error",
            "cloudflare-challenge",
            "reddit is experiencing a heavy load",
            "rate limit exceeded",
            "too many requests",
            "we're sorry",
            "redirecting",
        ]
        return any(p in html.lower() for p in block_patterns)

    def _is_rate_limit(self, html: str) -> bool:
        return "rate limit" in html.lower() or "too many requests" in html.lower()

    # =================================================================
    # Scrapling Engine (Primary)
    # =================================================================

    def _fetch_with_scrapling(self, url: str) -> Optional[str]:
        """Fetch page using Scrapling stealth engine."""
        if not SCRAPLING_AVAILABLE or not self.use_scrapling:
            return None

        try:
            logger.info(f"Scrapling fetching: {url}")
            opts = {
                "headless": True,
                "solve_cloudflare": True,
                "disable_resources": False,
                "block_ads": True,
                "block_webrtc": True,
                "hide_canvas": True,
                "timeout": 60000,
                "wait": 5000,
                "load_dom": True,
            }
            if self.proxy:
                opts["proxy"] = self.proxy

            response = StealthyFetcher.fetch(url, **opts)
            html = response.body.decode('utf-8') if response.body and hasattr(response.body, 'decode') else str(response)
            if response.status == 200 and html and len(html) > 1000 and not self._is_bot_block(html):
                logger.info(f"Scrapling success: {len(html)} bytes")
                return html
            else:
                logger.warning(f"Scrapling returned status {response.status}, len={len(html)}")
        except Exception as e:
            logger.debug(f"Scrapling failed: {e}")
        return None

    # =================================================================
    # HTTP Engine (Fallback)
    # =================================================================

    def _fetch_with_http(self, url: str) -> Optional[str]:
        """Fetch page using standard HTTP requests."""
        if self._session is None:
            return None
        self._rate_limit()
        try:
            resp = self._session.get(url, timeout=30)
            if resp.status_code == 200 and resp.text and len(resp.text) > 1000 and not self._is_bot_block(resp.text):
                return resp.text
            elif resp.status_code in [403, 429, 503]:
                logger.warning(f"HTTP {resp.status_code} from {url}")
            else:
                logger.warning(f"HTTP {resp.status_code} for {url}")
        except Exception as e:
            logger.debug(f"HTTP fetch failed: {e}")
        return None

    # =================================================================
    # Unified Fetch
    # =================================================================

    def _fetch_page(self, url: str) -> Optional[str]:
        """Try all fetch strategies in order of preference."""
        # 1. Scrapling (stealth)
        html = self._fetch_with_scrapling(url)
        if html:
            return html

        # 2. Standard HTTP
        html = self._fetch_with_http(url)
        if html:
            return html

        return None

    # =================================================================
    # Reddit JSON API (for detailed post data)
    # =================================================================

    def _fetch_post_json(self, permalink: str) -> Optional[Dict]:
        """Fetch detailed post data via Reddit's JSON API."""
        if self._session is None:
            return None
        json_url = f"{REDDIT_BASE}{permalink}.json"
        self._rate_limit()
        try:
            resp = self._session.get(json_url, headers={**HEADERS, "Accept": "application/json"}, timeout=20)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"Post JSON fetch failed: {e}")
        return None

    # =================================================================
    # Parsing: Search Results Page
    # =================================================================

    def _parse_search_results(self, html: str, address: str) -> List[RedditPost]:
        """Parse Reddit search results HTML to extract posts."""
        posts = []
        if not html or self._is_bot_block(html):
            return posts

        soup = BeautifulSoup(html, 'html.parser') if BeautifulSoup else None
        if not soup:
            return posts

        # Strategy 1: Extract from post links (most reliable)
        seen_links = set()
        # Reddit permalinks have format: /r/SUBREDDIT/comments/ID/SLUG/ (with trailing slash)
        for m in re.finditer(r'href="(/r/([^/]+)/comments/([^/]+)/([^"]+))"', html):
            permalink = m.group(1).rstrip('/')  # Remove trailing slash for consistency
            post_id = m.group(3)
            subreddit = m.group(2)

            if post_id in self._seen_ids or post_id in seen_links:
                continue
            seen_links.add(post_id)

            # Find the link element to get title text
            link_text = ""
            # Search nearby for the title text
            pos = m.end()
            nearby = html[pos:pos+500]
            title_match = re.search(r'>([^<]{10,200})<', nearby)
            if title_match:
                link_text = re.sub(r'\s+', ' ', title_match.group(1)).strip()

            post = RedditPost(
                post_id=post_id,
                title=link_text or f"Post in r/{subreddit}",
                author="",
                subreddit=subreddit,
                permalink=permalink,
                url=f"{REDDIT_BASE}{permalink}",
                address_mentioned=address,
            )
            posts.append(post)

        # Strategy 2: Extract from shreddit-post-title tags (if present)
        if soup:
            for title_tag in soup.find_all(re.compile(r'shreddit-post-title', re.I)):
                text = title_tag.get_text(strip=True)
                if text and len(text) > 10:
                    # Try to find associated permalink
                    parent = title_tag.find_parent()
                    if parent:
                        link = parent.find('a', href=re.compile(r'/r/[^/]+/comments/'))
                        if link:
                            href = link.get('href', '')
                            match = re.search(r'/r/([^/]+)/comments/([^/]+)/', href)
                            if match:
                                post_id = match.group(2)
                                if post_id not in self._seen_ids:
                                    posts.append(RedditPost(
                                        post_id=post_id,
                                        title=text,
                                        author="",
                                        subreddit=match.group(1),
                                        permalink=href.rstrip('/'),
                                        url=f"{REDDIT_BASE}{href.rstrip('/')}",
                                        address_mentioned=address,
                                    ))

        # Strategy 3: Extract from <article> or <faceplate-tracker> elements
        if soup:
            for article in soup.find_all(['article', 'shreddit-post', 'faceplate-tracker']):
                link = article.find('a', href=re.compile(r'/r/[^/]+/comments/'))
                if link:
                    href = link.get('href', '')
                    match = re.search(r'/r/([^/]+)/comments/([^/]+)/', href)
                    if match:
                        post_id = match.group(2)
                        if post_id not in self._seen_ids and post_id not in [p.post_id for p in posts]:
                            title = link.get_text(strip=True) or link.get('aria-label', '')
                            posts.append(RedditPost(
                                post_id=post_id,
                                title=title,
                                author="",
                                subreddit=match.group(1),
                                permalink=href.rstrip('/'),
                                url=f"{REDDIT_BASE}{href.rstrip('/')}",
                                address_mentioned=address,
                            ))

        # Deduplicate
        deduped = []
        for p in posts:
            if p.post_id not in self._seen_ids:
                self._seen_ids.add(p.post_id)
                deduped.append(p)

        return deduped

    # =================================================================
    # Parsing: Comments from Search Results
    # =================================================================

    def _parse_comment_results(self, html: str, address: str) -> List[RedditComment]:
        """Parse Reddit comment search results HTML."""
        comments = []
        if not html or self._is_bot_block(html):
            return comments

        soup = BeautifulSoup(html, 'html.parser') if BeautifulSoup else None

        # Look for comment links (same pattern as posts but in comment context)
        seen = set()
        for m in re.finditer(r'href="(/r/([^/]+)/comments/([^/]+)/[^/]+/([^/]+))"', html):
            permalink = m.group(1)
            comment_id = m.group(4)
            subreddit = m.group(2)

            if comment_id in seen or comment_id in self._seen_ids:
                continue
            seen.add(comment_id)

            # Find body text nearby
            pos = m.end()
            nearby = html[pos:pos+800]
            body_match = re.search(r'>([^<]{10,500})<', nearby)
            body = body_match.group(1).strip() if body_match else ""

            comment = RedditComment(
                comment_id=comment_id,
                body=body,
                author="",
                subreddit=subreddit,
                permalink=permalink,
                address_mentioned=address,
            )
            comments.append(comment)

        # Deduplicate
        deduped = []
        for c in comments:
            if c.comment_id not in self._seen_ids:
                self._seen_ids.add(c.comment_id)
                deduped.append(c)

        return deduped

    # =================================================================
    # Enrich Posts with Full Details
    # =================================================================

    def _enrich_posts(self, posts: List[RedditPost]) -> List[RedditPost]:
        """Fetch full post details via Reddit JSON API."""
        enriched = []
        for post in posts:
            if not post.permalink:
                enriched.append(post)
                continue

            logger.info(f"Enriching post: {post.post_id}")
            data = self._fetch_post_json(post.permalink)
            if data and isinstance(data, list) and len(data) > 0:
                post_data = data[0].get('data', {}).get('children', [{}])[0].get('data', {})
                if post_data:
                    post.title = post_data.get('title', post.title)
                    post.author = post_data.get('author', post.author)
                    post.selftext = post_data.get('selftext', post.selftext)
                    post.score = post_data.get('score', post.score)
                    post.num_comments = post_data.get('num_comments', post.num_comments)
                    post.created_utc = post_data.get('created_utc')
                    post.is_self = post_data.get('is_self', post.is_self)
                    post.url = post_data.get('url', post.url)
                    post.upvote_ratio = post_data.get('upvote_ratio')
                    post.distinguished = post_data.get('distinguished')
                    post.over_18 = post_data.get('over_18', post.over_18)
                    post.spoiler = post_data.get('spoiler', post.spoiler)
                    post.locked = post_data.get('locked', post.locked)
                    post.stickied = post_data.get('stickied', post.stickied)
                    post.domain = post_data.get('domain', post.domain)
                    post.thumbnail = post_data.get('thumbnail', post.thumbnail)

            enriched.append(post)

        return enriched

    # =================================================================
    # Public API
    # =================================================================

    def search_posts(self, address: str, pages: Optional[int] = None, enrich: bool = False) -> List[RedditPost]:
        """Search Reddit for posts mentioning a crypto address."""
        address = address.strip().lower()
        max_pages = pages or self.max_pages
        all_posts = []

        for page in range(max_pages):
            logger.info(f"Searching page {page + 1}/{max_pages} for: {address}")

            # Build search URL
            after = ""
            if page > 0 and all_posts:
                # Reddit uses "after" for pagination, but with HTML we need to track offsets
                # For simplicity, we use count parameter
                count = page * self.results_per_page
                url = f"{REDDIT_BASE}/search/?q={quote(address)}&type=posts&sort={self.sort}&t={self.time_filter}&count={count}"
            else:
                url = f"{REDDIT_BASE}/search/?q={quote(address)}&type=posts&sort={self.sort}&t={self.time_filter}"

            html = self._fetch_page(url)
            if not html:
                logger.error(f"Failed to fetch page {page + 1}")
                break

            posts = self._parse_search_results(html, address)
            if not posts:
                logger.info(f"No more results on page {page + 1}")
                break

            logger.info(f"Found {len(posts)} posts on page {page + 1}")
            all_posts.extend(posts)

            # Enrich with details (optional, adds API calls - slow and may be blocked)
            if enrich and self._session:
                posts = self._enrich_posts(posts)

            time.sleep(self.rate_limit_delay)

        return all_posts

    def search_comments(self, address: str, pages: Optional[int] = None) -> List[RedditComment]:
        """Search Reddit for comments mentioning a crypto address."""
        address = address.strip().lower()
        max_pages = pages or self.max_pages
        all_comments = []

        for page in range(max_pages):
            logger.info(f"Searching comments page {page + 1}/{max_pages} for: {address}")

            count = page * self.results_per_page if page > 0 else 0
            url = f"{REDDIT_BASE}/search/?q={quote(address)}&type=comments&sort={self.sort}&t={self.time_filter}"
            if count > 0:
                url += f"&count={count}"

            html = self._fetch_page(url)
            if not html:
                logger.error(f"Failed to fetch comment page {page + 1}")
                break

            comments = self._parse_comment_results(html, address)
            if not comments:
                logger.info(f"No more comments on page {page + 1}")
                break

            logger.info(f"Found {len(comments)} comments on page {page + 1}")
            all_comments.extend(comments)
            time.sleep(self.rate_limit_delay)

        return all_comments

    def search(self, address: str, enrich: bool = False) -> Dict[str, Any]:
        """Search both posts and comments."""
        results = {
            "address": address,
            "search_type": self.search_type,
            "posts": [],
            "comments": [],
            "total_posts": 0,
            "total_comments": 0,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

        if self.search_type in ("posts", "all"):
            posts = self.search_posts(address, enrich=enrich)
            results["posts"] = [p.to_dict() for p in posts]
            results["total_posts"] = len(posts)
            logger.info(f"Total posts found: {len(posts)}")

        if self.search_type in ("comments", "all"):
            comments = self.search_comments(address)
            results["comments"] = [c.to_dict() for c in comments]
            results["total_comments"] = len(comments)
            logger.info(f"Total comments found: {len(comments)}")

        return results

    def batch_search(self, addresses: List[str], output_file: Optional[str] = None, enrich: bool = False) -> Dict[str, Any]:
        """Search multiple addresses."""
        all_results = []
        for i, addr in enumerate(addresses, 1):
            logger.info(f"[{i}/{len(addresses)}] Searching: {addr}")
            result = self.search(addr, enrich=enrich)
            all_results.append(result)
            time.sleep(self.rate_limit_delay)

        combined = {
            "addresses_searched": len(addresses),
            "results": all_results,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

        if output_file:
            self._save_results(combined, output_file)

        return combined

    def _save_results(self, data: Any, filepath: str, format: str = "json"):
        path = Path(filepath)

        if format.lower() == "json":
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        elif format.lower() in ("csv", "tsv"):
            # Flatten posts for CSV
            flat_posts = []
            if isinstance(data, dict) and "results" in data:
                for r in data["results"]:
                    for p in r.get("posts", []):
                        flat_posts.append(p)
            elif isinstance(data, dict) and "posts" in data:
                flat_posts = data["posts"]

            if flat_posts:
                keys = sorted(flat_posts[0].keys())
                delimiter = '\t' if format.lower() == "tsv" else ','
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=keys, delimiter=delimiter)
                    writer.writeheader()
                    for item in flat_posts:
                        row = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in item.items()}
                        writer.writerow(row)

        logger.info(f"Results saved to {path}")


# =============================================================================
# CLI
# =============================================================================

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reddit Crypto Address Scraper - Search Reddit for posts/comments mentioning crypto addresses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search posts mentioning an address
  python reddit_scraper.py --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

  # Search comments
  python reddit_scraper.py --address 0x47666Fab8bd0Ac7003bce3f5C3585383F09486E2 --type comments

  # Search both posts and comments
  python reddit_scraper.py --address 0x... --type all

  # Multiple pages
  python reddit_scraper.py --address 0x... --pages 3

  # Batch search from file
  python reddit_scraper.py --batch addresses.txt --output results.json

  # Use proxy
  python reddit_scraper.py --address 0x... --proxy http://127.0.0.1:8080
        """
    )

    parser.add_argument("--address", type=str, help="Single crypto address to search for")
    parser.add_argument("--batch", type=str, help="File containing addresses (one per line)")
    parser.add_argument("--output", type=str, default="reddit_results.json", help="Output file path")
    parser.add_argument("--format", type=str, choices=["json", "csv", "tsv"], default="json", help="Output format")
    parser.add_argument("--type", type=str, choices=["posts", "comments", "all"], default="posts", help="Search type")
    parser.add_argument("--pages", type=int, default=3, help="Max pages to search (default: 3)")
    parser.add_argument("--per-page", type=int, default=25, help="Results per page (default: 25)")
    parser.add_argument("--sort", type=str, choices=["new", "relevance", "top"], default="new", help="Sort order")
    parser.add_argument("--time", type=str, choices=["all", "year", "month", "week", "day"], default="all", help="Time filter")
    parser.add_argument("--proxy", type=str, help="Proxy URL (e.g., http://127.0.0.1:8080)")
    parser.add_argument("--delay", type=float, default=2.0, help="Rate limit delay between requests")
    parser.add_argument("--enrich", action="store_true", default=False, help="Fetch full post details via Reddit API (slow, may be blocked)")
    parser.add_argument("--no-scrapling", dest="use_scrapling", action="store_false", default=True, help="Disable Scrapling (use HTTP only)")
    parser.add_argument("--setup-check", action="store_true", help="Check dependencies")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    return parser


def run_setup_check():
    print("\n" + "=" * 60)
    print("Reddit Scraper - Setup Check")
    print("=" * 60)

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

    print("\n[Stealth Engine]")
    try:
        import scrapling
        print(f"  scrapling: {scrapling.__version__} OK (PRIMARY)")
    except ImportError:
        print("  scrapling: MISSING - pip install scrapling")
        print("    -> REQUIRED for Reddit Cloudflare bypass")

    print("\n" + "=" * 60)
    print("\nInstall command:")
    print("  pip install scrapling requests beautifulsoup4 lxml")
    print("=" * 60 + "\n")


def main():
    parser = create_parser()
    args = parser.parse_args()

    if args.setup_check:
        run_setup_check()
        sys.exit(0)

    if not any([args.address, args.batch]):
        parser.print_help()
        sys.exit(1)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    scraper = RedditScraper(
        proxy=args.proxy,
        rate_limit_delay=args.delay,
        max_pages=args.pages,
        results_per_page=args.per_page,
        search_type=args.type,
        sort=args.sort,
        time_filter=args.time,
        use_scrapling=args.use_scrapling,
    )

    if args.address:
        results = scraper.search(args.address, enrich=args.enrich)
        print(json.dumps(results, indent=2, ensure_ascii=False))

    if args.batch:
        if not os.path.exists(args.batch):
            logger.error(f"Batch file not found: {args.batch}")
            sys.exit(1)

        with open(args.batch, 'r') as f:
            addresses = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        logger.info(f"Loaded {len(addresses)} addresses from {args.batch}")
        results = scraper.batch_search(addresses, output_file=args.output, enrich=args.enrich)
        print(json.dumps(results, indent=2, ensure_ascii=False))

    if args.address and not args.batch:
        scraper._save_results(results, args.output, args.format)
        logger.info(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
