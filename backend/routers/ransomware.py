"""
Ransomware intelligence router.

Provides endpoints for:
  - Ransomware group profiles (with TTPs, leak sites, crypto addresses, wallets)
  - Extortion incidents (with victim info, crypto addresses)
  - Aggregate statistics
  - Search across groups and incidents
  - Address lookup across all ransomware data sources
  - Unified threat intelligence feed
  - Threat actor profiles (comprehensive, correlated)
  - Address intelligence (all tracked addresses with actor attribution)
  - Crypto wallet data from RansomLook CryptoAPI
  - Baseline snapshot (all tab data in one call)
  - Background refresh (incremental data update)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import ransomware_engine as rengine

router = APIRouter(tags=["Ransomware Intelligence"])


# ── Baseline & Refresh ──────────────────────────────────────────────────────────

@router.get("/ransomware/baseline")
def ransomware_baseline():
    """Return ALL threat data from cache in a single response.
    Returns instantly from cached/persisted data — never blocks on external APIs."""
    return rengine.get_baseline()


@router.post("/ransomware/refresh")
def ransomware_refresh():
    """Trigger a background refresh of all threat data sources.
    Returns immediately with refresh status. Data updates asynchronously."""
    status = rengine.get_refresh_status()
    if status.get("running"):
        return {"status": "already_running", "started_at": status.get("started_at")}
    rengine.start_background_refresh()
    return {"status": "started", "message": "Background refresh initiated"}


@router.get("/ransomware/refresh-status")
def ransomware_refresh_status():
    """Check the status of the current/last background refresh."""
    return rengine.get_refresh_status()


# ── Group endpoints ─────────────────────────────────────────────────────────────

@router.get("/ransomware/groups")
def ransomware_groups(
    refresh: bool = Query(default=False, description="Force refresh from upstream API"),
):
    """List all known ransomware group profiles (unified from all sources)."""
    groups = rengine.fetch_all_groups(force=refresh)
    return {
        "groups": groups,
        "total": len(groups),
        "active": len([g for g in groups if g.get("active_sites")]),
        "with_wallets": len([g for g in groups if g.get("wallets")]),
    }


@router.get("/ransomware/groups/{group_name}")
def ransomware_group_detail(
    group_name: str,
    refresh: bool = Query(default=False),
):
    """Detailed profile for a specific ransomware group."""
    group = rengine.fetch_group_detail(group_name, force=refresh)
    if not group:
        raise HTTPException(status_code=404, detail=f"Group '{group_name}' not found")
    posts = rengine.fetch_group_posts(group_name, force=refresh)

    # Also try to get RansomLook CryptoAPI data for this group
    slug = group_name.lower().replace(" ", "-")
    crypto_data = rengine.fetch_crypto_group_rlk(slug, force=refresh)

    result = {
        "group": group,
        "incidents": posts,
        "incident_count": len(posts),
    }
    if crypto_data:
        result["crypto_wallets"] = crypto_data
    return result


# ── Incident endpoints ──────────────────────────────────────────────────────────

@router.get("/ransomware/incidents")
def ransomware_incidents(
    group: str | None = Query(default=None, description="Filter by group name"),
    limit: int = Query(default=100, ge=1, le=500),
    refresh: bool = Query(default=False),
):
    """List recent ransomware extortion incidents."""
    posts = rengine.fetch_all_posts(force=refresh)
    if group:
        posts = [p for p in posts if group.lower() in p.get("group", "").lower()]
    posts = sorted(posts, key=lambda p: p.get("discovered", ""), reverse=True)[:limit]
    return {
        "incidents": posts,
        "total": len(posts),
        "with_crypto_addresses": len([
            p for p in posts
            if any(p.get("crypto_addresses", {}).get(c) for c in rengine.CHAIN_REGEXES)
        ]),
    }


# ── Stats ───────────────────────────────────────────────────────────────────────

@router.get("/ransomware/stats")
def ransomware_stats(refresh: bool = Query(default=False)):
    """Aggregate ransomware statistics."""
    return rengine.fetch_stats(force=refresh)


# ── Search ──────────────────────────────────────────────────────────────────────

@router.get("/ransomware/search")
def ransomware_search(
    q: str = Query(..., min_length=1, description="Search query"),
):
    """Search across ransomware groups and incidents."""
    return rengine.search_ransomware(q)


# ── Address lookup ──────────────────────────────────────────────────────────────

@router.get("/ransomware/address/{address}")
def ransomware_address_lookup(
    address: str,
):
    """Look up a crypto address across all ransomware data sources."""
    return rengine.search_by_address(address)


# ── Feed ────────────────────────────────────────────────────────────────────────

@router.get("/ransomware/feed")
def ransomware_feed(
    limit: int = Query(default=100, ge=1, le=500),
    refresh: bool = Query(default=False),
):
    """Unified threat intelligence feed combining all ransomware sources."""
    return rengine.get_threat_intelligence_feed(limit=limit)


# ── NEW: Threat Actor Profiles ──────────────────────────────────────────────────

@router.get("/ransomware/threat-actors")
def threat_actors(
    refresh: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    sort_by: str = Query(default="victim_count", description="Sort: victim_count, incident_count, total_addresses, name"),
    active_only: bool = Query(default=False, description="Only show active groups"),
    with_crypto_only: bool = Query(default=False, description="Only show groups with crypto addresses"),
):
    """
    Comprehensive threat actor profiles correlated from all sources.
    Includes crypto wallets, TTPs, victim data, infrastructure, and more.
    """
    profiles = rengine.build_threat_actor_profiles(force=refresh)

    if active_only:
        profiles = [p for p in profiles if p.get("active")]
    if with_crypto_only:
        profiles = [p for p in profiles if p.get("total_addresses", 0) > 0]

    sort_keys = {
        "victim_count": lambda p: p.get("victim_count", 0),
        "incident_count": lambda p: p.get("incident_count", 0),
        "total_addresses": lambda p: p.get("total_addresses", 0),
        "name": lambda p: p.get("name", "").lower(),
    }
    sort_fn = sort_keys.get(sort_by, sort_keys["victim_count"])
    profiles.sort(key=sort_fn, reverse=(sort_by != "name"))

    return {
        "profiles": profiles[:limit],
        "total": len(profiles),
        "with_wallets": len([p for p in profiles if p.get("wallets")]),
        "with_crypto": len([p for p in profiles if p.get("total_addresses", 0) > 0]),
        "total_wallet_balance_usd": sum(
            p.get("wallet_stats", {}).get("total_balance_usd", 0) for p in profiles
        ),
    }


@router.get("/ransomware/threat-actors/{name}")
def threat_actor_detail(
    name: str,
    refresh: bool = Query(default=False),
):
    """Detailed threat actor profile by name."""
    profile = rengine.get_threat_actor(name, force=refresh)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Threat actor '{name}' not found")

    # Include their incidents
    posts = rengine.fetch_all_posts(force=False)
    actor_posts = [
        p for p in posts
        if p.get("group", "").lower() == name.lower()
    ]
    actor_posts.sort(key=lambda p: p.get("discovered", ""), reverse=True)

    return {
        "profile": profile,
        "incidents": actor_posts[:100],
        "incident_count": len(actor_posts),
    }


# ── NEW: Address Intelligence ───────────────────────────────────────────────────

@router.get("/ransomware/address-intel")
def address_intelligence(
    refresh: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
    chain: str | None = Query(default=None, description="Filter by chain: btc, eth, xmr, ltc, doge, zec, dash, bch"),
    actor: str | None = Query(default=None, description="Filter by actor name"),
    with_balance_only: bool = Query(default=False, description="Only show addresses with wallet balance data"),
):
    """
    Comprehensive crypto address intelligence index.
    All tracked addresses with actor attribution, incident links, wallet data.
    """
    all_addrs = rengine.build_address_intelligence(force=refresh)

    if chain:
        all_addrs = [a for a in all_addrs if a.get("chain") == chain.lower()]
    if actor:
        actor_lower = actor.lower()
        all_addrs = [a for a in all_addrs if any(actor_lower in act.lower() for act in a.get("actors", []))]
    if with_balance_only:
        all_addrs = [a for a in all_addrs if a.get("wallet_data")]

    return {
        "addresses": all_addrs[:limit],
        "total": len(all_addrs),
        "by_chain": _count_by_chain(all_addrs),
        "total_balance_usd": sum(
            (a.get("wallet_data") or {}).get("balance_usd", 0) for a in all_addrs
        ),
    }


@router.get("/ransomware/address-intel/{address}")
def address_intel_detail(
    address: str,
):
    """Full intelligence for a single crypto address."""
    return rengine.lookup_address_intel(address)


# ── NEW: Crypto Wallets ─────────────────────────────────────────────────────────

@router.get("/ransomware/crypto-wallets")
def crypto_wallets(
    refresh: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=2000),
    chain: str | None = Query(default=None),
    group: str | None = Query(default=None),
):
    """
    All tracked crypto wallets from RansomLook CryptoAPI.
    Includes balances, tx counts, USD values.
    """
    all_crypto = rengine.fetch_all_crypto_rlk(force=refresh)

    wallets = []
    for slug, data in all_crypto.items():
        if group and group.lower() not in slug.lower():
            continue
        for w in data.get("wallets", []):
            if chain and w.get("chain") != chain.lower():
                continue
            wallets.append(w)

    wallets.sort(key=lambda w: w.get("balance_usd", 0), reverse=True)

    return {
        "wallets": wallets[:limit],
        "total": len(wallets),
        "total_balance_usd": sum(w.get("balance_usd", 0) for w in wallets),
        "total_tx_count": sum(w.get("tx_count", 0) for w in wallets),
        "by_chain": _count_by_chain_field(wallets),
        "groups_count": len(set(w.get("group", "") for w in wallets)),
    }


@router.get("/ransomware/crypto-groups")
def crypto_groups(
    refresh: bool = Query(default=False),
):
    """List all groups with crypto wallet data on RansomLook."""
    slugs = rengine.fetch_crypto_groups_rlk(force=refresh)
    return {
        "groups": slugs,
        "total": len(slugs),
    }


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _count_by_chain(addresses: list) -> dict:
    counts = {}
    for a in addresses:
        chain = a.get("chain", "unknown")
        counts[chain] = counts.get(chain, 0) + 1
    return counts


def _count_by_chain_field(wallets: list) -> dict:
    counts = {}
    for w in wallets:
        chain = w.get("chain", "unknown")
        counts[chain] = counts.get(chain, 0) + 1
    return counts
