#!/usr/bin/env python3
"""
Arkham Scraper Utilities - Advanced Attribution Extraction
==========================================================
Advanced scraping utilities for crypto address attribution:
- Proxy rotation & pool management
- Multi-chain address support
- Transaction flow extraction
- Entity relationship mapping
- Portfolio history scraping
- Address clustering detection
- Confidence scoring for attributions
"""

import json
import random
import time
import logging
import re
from typing import Optional, Dict, List, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


# =============================================================================
# Chain Configurations
# =============================================================================

CHAIN_CONFIG = {
    "ethereum": {
        "explorer": "https://platform.arkhamintelligence.com/explorer/address/",
        "api_path": "/intelligence/address",
        "address_pattern": r"^0x[a-fA-F0-9]{40}$",
        "name": "Ethereum",
    },
    "bitcoin": {
        "explorer": "https://platform.arkhamintelligence.com/explorer/address/",
        "api_path": "/intelligence/address",
        "address_pattern": r"^(1|3|bc1)[a-zA-HJ-NP-Z0-9]{25,62}$",
        "name": "Bitcoin",
    },
    "solana": {
        "explorer": "https://platform.arkhamintelligence.com/explorer/address/",
        "api_path": "/intelligence/address",
        "address_pattern": r"^[1-9A-HJ-NP-Za-km-z]{32,44}$",
        "name": "Solana",
    },
    "arbitrum": {
        "explorer": "https://platform.arkhamintelligence.com/explorer/address/",
        "address_pattern": r"^0x[a-fA-F0-9]{40}$",
        "name": "Arbitrum",
    },
    "optimism": {
        "explorer": "https://platform.arkhamintelligence.com/explorer/address/",
        "address_pattern": r"^0x[a-fA-F0-9]{40}$",
        "name": "Optimism",
    },
    "base": {
        "explorer": "https://platform.arkhamintelligence.com/explorer/address/",
        "address_pattern": r"^0x[a-fA-F0-9]{40}$",
        "name": "Base",
    },
    "polygon": {
        "explorer": "https://platform.arkhamintelligence.com/explorer/address/",
        "address_pattern": r"^0x[a-fA-F0-9]{40}$",
        "name": "Polygon",
    },
    "avalanche": {
        "explorer": "https://platform.arkhamintelligence.com/explorer/address/",
        "address_pattern": r"^0x[a-fA-F0-9]{40}$",
        "name": "Avalanche",
    },
    "tron": {
        "explorer": "https://platform.arkhamintelligence.com/explorer/address/",
        "address_pattern": r"^T[a-zA-Z0-9]{33}$",
        "name": "Tron",
    },
}


def detect_chain(address: str) -> Optional[str]:
    """Detect blockchain from address format."""
    priority_chains = ["tron", "bitcoin", "ethereum", "solana"]
    checked = set()
    
    for chain_id in priority_chains:
        config = CHAIN_CONFIG.get(chain_id)
        if config and re.match(config["address_pattern"], address):
            return chain_id
        checked.add(chain_id)
    
    for chain_id, config in CHAIN_CONFIG.items():
        if chain_id in checked:
            continue
        if re.match(config["address_pattern"], address):
            return chain_id
    return None


# =============================================================================
# Proxy Rotation
# =============================================================================

@dataclass
class ProxyConfig:
    """Proxy configuration with rotation and health tracking."""
    url: str
    weight: float = 1.0
    failures: int = 0
    last_used: Optional[datetime] = None
    success_count: int = 0
    avg_response_time: float = 0.0


class ProxyRotator:
    """Manages a pool of proxies with rotation, health checking, and weighted selection."""

    def __init__(self, proxies: Optional[List[str]] = None):
        self.proxies: List[ProxyConfig] = []
        self.current_index = 0
        self.max_failures = 3
        self.cooldown_minutes = 5

        if proxies:
            for p in proxies:
                self.add_proxy(p)

    def add_proxy(self, proxy_url: str, weight: float = 1.0):
        self.proxies.append(ProxyConfig(url=proxy_url, weight=weight))
        logger.info(f"Added proxy: {proxy_url}")

    def load_from_file(self, filepath: str):
        """Load proxies from file (one per line, format: protocol://host:port or protocol://user:pass@host:port)."""
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        self.add_proxy(line)
        except Exception as e:
            logger.error(f"Failed to load proxies from {filepath}: {e}")

    def get_next(self) -> Optional[str]:
        """Get next healthy proxy using weighted round-robin."""
        if not self.proxies:
            return None

        healthy = [p for p in self.proxies if self._is_healthy(p)]
        if not healthy:
            # Reset all if none healthy
            for p in self.proxies:
                p.failures = 0
            healthy = self.proxies

        # Weighted random selection
        total_weight = sum(p.weight for p in healthy)
        r = random.uniform(0, total_weight)
        cumulative = 0
        for p in healthy:
            cumulative += p.weight
            if r <= cumulative:
                p.last_used = datetime.now()
                return p.url

        return healthy[0].url if healthy else None

    def _is_healthy(self, proxy: ProxyConfig) -> bool:
        if proxy.failures >= self.max_failures:
            if proxy.last_used and (datetime.now() - proxy.last_used) < timedelta(minutes=self.cooldown_minutes):
                return False
            proxy.failures = 0
        return True

    def report_success(self, proxy_url: str, response_time: float):
        for p in self.proxies:
            if p.url == proxy_url:
                p.success_count += 1
                p.failures = max(0, p.failures - 1)
                # Update average response time
                if p.avg_response_time == 0:
                    p.avg_response_time = response_time
                else:
                    p.avg_response_time = (p.avg_response_time * 0.9) + (response_time * 0.1)
                break

    def report_failure(self, proxy_url: str):
        for p in self.proxies:
            if p.url == proxy_url:
                p.failures += 1
                break

    def get_stats(self) -> List[Dict[str, Any]]:
        return [
            {
                "url": p.url,
                "weight": p.weight,
                "failures": p.failures,
                "success_count": p.success_count,
                "avg_response_time": round(p.avg_response_time, 3),
                "healthy": self._is_healthy(p),
            }
            for p in self.proxies
        ]


# =============================================================================
# Advanced Attribution Parser
# =============================================================================

@dataclass
class AttributionSignal:
    """A single piece of evidence for address attribution."""
    signal_type: str  # "label", "tag", "transaction_pattern", "cluster", "heuristic"
    value: str
    confidence: float = 0.0  # 0.0 to 1.0
    source: str = "arkham"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnrichedAttribution:
    """Enriched attribution with multiple signals and confidence analysis."""
    address: str
    chain: str = "ethereum"
    primary_entity: Optional[str] = None
    primary_entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    signals: List[AttributionSignal] = field(default_factory=list)
    overall_confidence: float = 0.0
    is_verified: bool = False
    tags: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    related_entities: List[str] = field(default_factory=list)
    counterparty_analysis: Dict[str, Any] = field(default_factory=dict)
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def add_signal(self, signal: AttributionSignal):
        self.signals.append(signal)
        self._recalculate_confidence()

    def _recalculate_confidence(self):
        if not self.signals:
            self.overall_confidence = 0.0
            return

        # Weight by signal type and confidence
        weights = {
            "label": 1.0,
            "tag": 0.8,
            "transaction_pattern": 0.6,
            "cluster": 0.7,
            "heuristic": 0.3,
        }

        total_weight = 0
        weighted_sum = 0
        for sig in self.signals:
            w = weights.get(sig.signal_type, 0.5)
            weighted_sum += sig.confidence * w
            total_weight += w

        self.overall_confidence = weighted_sum / total_weight if total_weight > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "chain": self.chain,
            "primary_entity": self.primary_entity,
            "primary_entity_name": self.primary_entity_name,
            "entity_type": self.entity_type,
            "overall_confidence": round(self.overall_confidence, 4),
            "is_verified": self.is_verified,
            "tags": self.tags,
            "labels": self.labels,
            "related_entities": self.related_entities,
            "counterparty_analysis": self.counterparty_analysis,
            "signals": [
                {
                    "type": s.signal_type,
                    "value": s.value,
                    "confidence": s.confidence,
                    "source": s.source,
                    "metadata": s.metadata,
                }
                for s in self.signals
            ],
            "scraped_at": self.scraped_at,
        }


class AttributionExtractor:
    """Advanced extraction of attribution signals from various page elements."""

    def __init__(self):
        self.known_exchange_patterns = {
            r'binance': 'binance',
            r'coinbase': 'coinbase',
            r'kraken': 'kraken',
            r'okx': 'okx',
            r'bybit': 'bybit',
            r'bitfinex': 'bitfinex',
            r'huobi': 'huobi',
            r'kucoin': 'kucoin',
            r'gate\.io': 'gate-io',
            r'crypto\.com': 'cryptocom',
            r'ftx': 'ftx',
            r'blockfi': 'blockfi',
        }

        self.known_entity_types = [
            "exchange", "dex", "protocol", "individual", "fund",
            "market_maker", "vc", "miner", "hacker", "scammer",
            "defi", "nft", "bridge", "custodian", "government",
        ]

    def extract_from_html(self, html: str, address: str, chain: str) -> EnrichedAttribution:
        """Extract all attribution signals from page HTML."""
        result = EnrichedAttribution(address=address, chain=chain)

        if not html:
            return result

        # Entity name extraction
        entity_name = self._extract_entity_name(html)
        if entity_name:
            result.primary_entity_name = entity_name
            result.add_signal(AttributionSignal(
                signal_type="label",
                value=entity_name,
                confidence=0.9,
                source="arkham_page",
            ))

        # Label extraction from various HTML patterns
        labels = self._extract_labels(html)
        for label in labels:
            result.labels.append(label)
            result.add_signal(AttributionSignal(
                signal_type="label",
                value=label,
                confidence=0.85,
                source="arkham_labels",
            ))

        # Tag extraction
        tags = self._extract_tags(html)
        for tag in tags:
            result.tags.append(tag)
            result.add_signal(AttributionSignal(
                signal_type="tag",
                value=tag,
                confidence=0.7,
                source="arkham_tags",
            ))

        # Entity type detection
        entity_type = self._detect_entity_type(html, labels + tags)
        if entity_type:
            result.entity_type = entity_type

        # Exchange detection from patterns
        for pattern, exchange_id in self.known_exchange_patterns.items():
            if re.search(pattern, html, re.IGNORECASE):
                result.add_signal(AttributionSignal(
                    signal_type="heuristic",
                    value=exchange_id,
                    confidence=0.5,
                    source="pattern_match",
                    metadata={"pattern": pattern},
                ))

        # Portfolio value extraction
        portfolio = self._extract_portfolio_value(html)
        if portfolio:
            result.counterparty_analysis["portfolio_usd"] = portfolio

        # Related addresses from links
        related = self._extract_related_addresses(html, address)
        result.related_entities = related[:10]  # Limit to top 10

        return result

    def _extract_entity_name(self, html: str) -> Optional[str]:
        """Extract entity name from various page patterns."""
        patterns = [
            r'"entityName"[:\s]*"([^"]+)"',
            r'"entity"[:\s]*\{[^}]*"name"[:\s]*"([^"]+)"',
            r'"arkhamEntity"[:\s]*\{[^}]*"name"[:\s]*"([^"]+)"',
            r'class="[^"]*entity-name[^"]*"[^>]*>([^<]+)',
            r'class="[^"]*EntityName[^"]*"[^>]*>([^<]+)',
            r'<title>[^|]*\|\s*([^|]+?)\s*\|',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                name = match.group(1).strip()
                if name and len(name) < 100 and name.lower() not in ('address', 'arkham', 'explorer'):
                    return name
        return None

    def _extract_labels(self, html: str) -> List[str]:
        """Extract labels from HTML."""
        labels = set()
        patterns = [
            r'"labels"[:\s]*\[([^\]]*)\]',
            r'"label"[:\s]*"([^"]+)"',
            r'class="[^"]*label[^"]*"[^>]*>([^<]+)',
            r'class="[^"]*badge[^"]*"[^>]*>([^<]+)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
            for match in matches:
                if isinstance(match, str) and match.strip():
                    text = match.strip()
                    if len(text) < 50:
                        labels.add(text)
        return list(labels)

    def _extract_tags(self, html: str) -> List[str]:
        """Extract tags from HTML."""
        tags = set()
        patterns = [
            r'"tags"[:\s]*\[([^\]]*)\]',
            r'"tag"[:\s]*"([^"]+)"',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
            for match in matches:
                if isinstance(match, str) and match.strip():
                    # Parse JSON array if needed
                    try:
                        parsed = json.loads(f'[{match}]')
                        if isinstance(parsed, list):
                            for item in parsed:
                                if isinstance(item, str) and item.strip():
                                    tags.add(item.strip())
                    except json.JSONDecodeError:
                        text = match.strip().strip('"')
                        if text and len(text) < 50:
                            tags.add(text)
        return list(tags)

    def _detect_entity_type(self, html: str, labels: List[str]) -> Optional[str]:
        """Detect entity type from page content and labels."""
        html_lower = html.lower()

        for etype in self.known_entity_types:
            if etype.replace('_', ' ') in html_lower or etype in html_lower:
                return etype

        # Detect from labels
        for label in labels:
            label_lower = label.lower()
            if any(ex in label_lower for ex in ['exchange', 'cex', 'dex']):
                return "exchange"
            if 'protocol' in label_lower or 'defi' in label_lower:
                return "protocol"
            if 'fund' in label_lower or 'vc' in label_lower:
                return "fund"
            if 'miner' in label_lower or 'mining' in label_lower:
                return "miner"
            if 'hacker' in label_lower or 'exploit' in label_lower:
                return "hacker"

        return None

    def _extract_portfolio_value(self, html: str) -> Optional[float]:
        """Extract portfolio USD value from HTML."""
        patterns = [
            r'"portfolioUsd"[:\s]*([0-9.]+)',
            r'"netWorth"[:\s]*([0-9.]+)',
            r'portfolio[^>]*>\$?([0-9,.]+)',
            r'net worth[^>]*>\$?([0-9,.]+)',
            r'balances?[^>]*>\$?([0-9,.]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                try:
                    value_str = match.group(1).replace(',', '')
                    return float(value_str)
                except ValueError:
                    continue
        return None

    def _extract_related_addresses(self, html: str, base_address: str) -> List[str]:
        """Extract related addresses from page links."""
        related = set()
        # Find all 0x addresses
        eth_addresses = re.findall(r'0x[a-fA-F0-9]{40}', html)
        for addr in eth_addresses:
            if addr.lower() != base_address.lower():
                related.add(addr.lower())

        # Find Bitcoin addresses
        btc_addresses = re.findall(r'(1|3|bc1)[a-zA-HJ-NP-Z0-9]{25,62}', html)
        for addr in btc_addresses:
            if addr != base_address:
                related.add(addr)

        return list(related)[:50]  # Limit results


# =============================================================================
# Transaction Flow Analyzer
# =============================================================================

@dataclass
class TransactionFlow:
    """Represents a transaction flow between entities."""
    tx_hash: str
    from_address: str
    to_address: str
    from_entity: Optional[str] = None
    to_entity: Optional[str] = None
    value_usd: Optional[float] = None
    token: Optional[str] = None
    timestamp: Optional[str] = None
    chain: str = "ethereum"


class TransactionFlowExtractor:
    """Extracts transaction flows from entity/address pages."""

    def extract_from_html(self, html: str) -> List[TransactionFlow]:
        """Extract transaction flows from page HTML."""
        flows = []
        if not html:
            return flows

        # Try to find embedded JSON data with transactions
        next_data = self._extract_next_data(html)
        if next_data:
            transactions = self._parse_transactions_from_json(next_data)
            flows.extend(transactions)

        # Fallback: parse from HTML tables
        html_flows = self._parse_transactions_from_html(html)
        flows.extend(html_flows)

        return flows

    def _extract_next_data(self, html: str) -> Optional[Dict]:
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
        return None

    def _parse_transactions_from_json(self, data: Dict) -> List[TransactionFlow]:
        flows = []
        props = data.get("props", {}).get("pageProps", {})
        if not props:
            return flows

        # Look for transfers/transaction data in various structures
        transfers = (
            props.get("transfers") or
            props.get("transactions") or
            props.get("data", {}).get("transfers") or
            []
        )

        for tx in transfers:
            flow = TransactionFlow(
                tx_hash=tx.get("hash", tx.get("txHash", "")),
                from_address=tx.get("from", {}).get("address", tx.get("fromAddress", "")),
                to_address=tx.get("to", {}).get("address", tx.get("toAddress", "")),
                from_entity=tx.get("from", {}).get("entity", {}).get("name"),
                to_entity=tx.get("to", {}).get("entity", {}).get("name"),
                value_usd=tx.get("valueUsd") or tx.get("usdValue"),
                token=tx.get("token", {}).get("symbol") if isinstance(tx.get("token"), dict) else tx.get("token"),
                timestamp=tx.get("timestamp") or tx.get("time"),
                chain=tx.get("chain", "ethereum"),
            )
            flows.append(flow)

        return flows

    def _parse_transactions_from_html(self, html: str) -> List[TransactionFlow]:
        """Parse transaction rows from HTML tables."""
        flows = []
        # Look for transaction row patterns
        row_patterns = re.findall(
            r'<tr[^>]*>.*?0x[a-fA-F0-9]{40}.*?0x[a-fA-F0-9]{40}.*?</tr>',
            html, re.IGNORECASE | re.DOTALL
        )
        for row in row_patterns[:20]:  # Limit
            addresses = re.findall(r'0x[a-fA-F0-9]{40}', row)
            if len(addresses) >= 2:
                flow = TransactionFlow(
                    tx_hash="",
                    from_address=addresses[0].lower(),
                    to_address=addresses[1].lower(),
                )
                flows.append(flow)
        return flows


# =============================================================================
# Address Clustering
# =============================================================================

class AddressClusterer:
    """Groups addresses that likely belong to the same entity."""

    def __init__(self):
        self.clusters: Dict[str, Set[str]] = {}
        self.entity_map: Dict[str, str] = {}  # address -> entity_id

    def add_attribution(self, address: str, entity_id: Optional[str], related: List[str] = None):
        """Add an address and its attribution to the cluster map."""
        if entity_id:
            self.entity_map[address.lower()] = entity_id
            if entity_id not in self.clusters:
                self.clusters[entity_id] = set()
            self.clusters[entity_id].add(address.lower())

        if related:
            for rel_addr in related:
                if entity_id:
                    self.clusters[entity_id].add(rel_addr.lower())
                # Also link related addresses
                if rel_addr.lower() in self.entity_map:
                    self.clusters[self.entity_map[rel_addr.lower()]].add(address.lower())

    def get_cluster(self, entity_id: str) -> List[str]:
        return list(self.clusters.get(entity_id, set()))

    def get_entity(self, address: str) -> Optional[str]:
        return self.entity_map.get(address.lower())

    def export_clusters(self) -> Dict[str, List[str]]:
        return {eid: list(addrs) for eid, addrs in self.clusters.items()}


# =============================================================================
# Utility Functions
# =============================================================================

def format_address(address: str, chain: str = "ethereum") -> str:
    """Format and validate address for given chain."""
    if chain in ("ethereum", "arbitrum", "optimism", "base", "polygon", "avalanche"):
        return address.lower()
    if chain == "bitcoin":
        return address  # Keep case for bech32
    return address.lower()


def sanitize_filename(name: str) -> str:
    """Sanitize string for use as filename."""
    return re.sub(r'[^\w\-_.]', '_', name).strip('_')


def chunk_list(items: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks."""
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def jitter_delay(base: float, jitter: float = 0.5) -> float:
    """Calculate jittered delay."""
    return base + random.uniform(-jitter, jitter)


def is_valid_address(address: str, chain: Optional[str] = None) -> bool:
    """Validate address format for a given chain."""
    if not address or not isinstance(address, str):
        return False

    if chain:
        config = CHAIN_CONFIG.get(chain)
        if config:
            return bool(re.match(config["address_pattern"], address))
        return False

    # Auto-detect
    return detect_chain(address) is not None


# =============================================================================
# Example / Test
# =============================================================================

if __name__ == "__main__":
    # Test chain detection
    test_addresses = [
        ("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "ethereum"),
        ("bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", "bitcoin"),
        ("TNXoiKa3rP2s8PiiEfcReH8XvQjJ7Qz7E8", "tron"),
    ]

    for addr, expected in test_addresses:
        detected = detect_chain(addr)
        print(f"Address: {addr[:20]}... -> Detected: {detected}, Expected: {expected}, Match: {detected == expected}")

    # Test proxy rotator
    rotator = ProxyRotator()
    rotator.add_proxy("http://127.0.0.1:8080")
    print(f"\nProxy stats: {rotator.get_stats()}")

    # Test attribution extractor
    extractor = AttributionExtractor()
    sample_html = '''
    <html><title>0x1234 | Binance Hot Wallet | Arkham</title>
    <div class="entity-name">Binance Hot Wallet</div>
    <span class="label">Exchange</span>
    <span class="badge">CEX</span>
    <div class="portfolio">$1,234,567.89</div>
    <script id="__NEXT_DATA__">
    {"props":{"pageProps":{"addressIntel":{"arkhamEntity":{"id":"binance","name":"Binance","type":"exchange","isVerified":true},"labels":[{"name":"Exchange"},{"name":"Hot Wallet"}],"tags":["hot-wallet","cex","verified"],"portfolioUsd":1234567.89,"confidence":0.95}}}}
    </script>
    </html>
    '''
    result = extractor.extract_from_html(sample_html, "0x1234", "ethereum")
    print(f"\nAttribution result:")
    print(json.dumps(result.to_dict(), indent=2))
