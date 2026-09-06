"""
Perp-DEX coverage — Hyperliquid engine (Next-Horizon 3.4).

Hyperliquid processes $200B+/month (70–80% of perp-DEX volume) and HIP-3 lets
anyone launch markets permissionlessly — a fresh surface for wash trading,
manipulation, and laundering via intentional-loss trades that classic wallet
tools don't cover.

Uses only the PUBLIC, keyless Hyperliquid info API (POST https://api.hyperliquid.xyz/info).
Deterministic detectors over the account's fills/ledger, in the house
"leads, not claims" style — every verdict carries its computed basis.

Detectors:
  * wash_trading            — high volume, near-flat net position, near-zero PnL,
                              sub-minute round trips
  * intentional_loss_xfer   — laundering via trading: concentrated, repeated
                              losses transferring value to counterparties
  * pass_through_account    — deposit → trade-thin → withdraw within hours
                              (placement/layering behavior)
  * liquidation_activity    — liquidation-heavy flow (self-liquidation value
                              transfer is a documented perp-DEX technique)
  * hip3_thin_market        — activity concentrated in thin/exotic markets where
                              manipulation is cheap

Key pivot: Hyperliquid deposits/withdrawals settle in USDC on Arbitrum from the
SAME EOA — the analyzed address is directly traceable on-chain (feed to Address
Intel / Holistic Trace on chain 'arb').
"""
from __future__ import annotations

import time
from typing import Any, Optional

API_URL = "https://api.hyperliquid.xyz/info"
TIMEOUT_S = 20
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 120  # seconds

MAJOR_COINS = {"BTC", "ETH", "SOL", "HYPE", "ARB", "AVAX", "DOGE", "XRP", "LINK",
               "OP", "MATIC", "SUI", "APT", "BNB", "LTC", "ADA", "TON", "WIF", "PEPE"}


async def _post(payload: dict[str, Any]) -> Any:
    import aiohttp  # lazy — engine's pure detectors work without it
    key = str(sorted(payload.items()))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_S)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(API_URL, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    _CACHE[key] = (time.time(), data)
    return data


async def fetch_account(address: str) -> dict[str, Any]:
    """Pull state + fills + ledger for one account. Partial failures degrade gracefully."""
    out: dict[str, Any] = {"address": address, "errors": []}
    for name, payload in (
        ("state", {"type": "clearinghouseState", "user": address}),
        ("fills", {"type": "userFills", "user": address}),
        ("ledger", {"type": "userNonFundingLedgerUpdates", "user": address}),
    ):
        try:
            out[name] = await _post(payload)
        except Exception as e:
            out[name] = None
            out["errors"].append(f"{name}: {e}")
    return out


# ── Fill statistics ──────────────────────────────────────────────────────────

def _fill_stats(fills: list[dict[str, Any]]) -> dict[str, Any]:
    if not fills:
        return {"fill_count": 0}
    vol = 0.0
    pnl = 0.0
    fees = 0.0
    by_coin: dict[str, dict[str, float]] = {}
    times: list[int] = []
    liq_fills = 0
    round_trips = 0
    last_side_by_coin: dict[str, tuple[str, int]] = {}
    holding_secs: list[float] = []

    for f in sorted(fills, key=lambda x: x.get("time") or 0):
        coin = f.get("coin") or "?"
        px = float(f.get("px") or 0)
        sz = float(f.get("sz") or 0)
        notional = px * sz
        vol += notional
        pnl += float(f.get("closedPnl") or 0)
        fees += float(f.get("fee") or 0)
        t = int(f.get("time") or 0)
        times.append(t)
        c = by_coin.setdefault(coin, {"volume": 0.0, "pnl": 0.0, "fills": 0})
        c["volume"] += notional
        c["pnl"] += float(f.get("closedPnl") or 0)
        c["fills"] += 1
        if "liquidat" in (f.get("dir") or "").lower():
            liq_fills += 1
        side = f.get("side") or ""
        prev = last_side_by_coin.get(coin)
        if prev and prev[0] != side:
            round_trips += 1
            if t and prev[1]:
                holding_secs.append((t - prev[1]) / 1000.0)
        last_side_by_coin[coin] = (side, t)

    span_h = (max(times) - min(times)) / 3600000.0 if len(times) > 1 else 0
    fast_flips = sum(1 for s in holding_secs if s <= 60)
    return {
        "fill_count": len(fills),
        "volume_usd": round(vol, 2),
        "net_closed_pnl_usd": round(pnl, 2),
        "fees_usd": round(fees, 2),
        "coins": sorted(by_coin.keys()),
        "by_coin": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in
                    sorted(by_coin.items(), key=lambda kv: -kv[1]["volume"])[:15]},
        "active_span_hours": round(span_h, 1),
        "round_trips": round_trips,
        "fast_flips_under_60s": fast_flips,
        "median_holding_seconds": round(sorted(holding_secs)[len(holding_secs) // 2], 1) if holding_secs else None,
        "liquidation_fills": liq_fills,
        "first_fill_at": min(times) if times else None,
        "last_fill_at": max(times) if times else None,
    }


def _ledger_stats(ledger: list[dict[str, Any]]) -> dict[str, Any]:
    deposits, withdrawals = [], []
    for u in ledger or []:
        delta = u.get("delta") or {}
        kind = (delta.get("type") or "").lower()
        usdc = abs(float(delta.get("usdc") or 0))
        t = int(u.get("time") or 0)
        if kind == "deposit":
            deposits.append({"usd": usdc, "time": t})
        elif kind == "withdraw":
            withdrawals.append({"usd": usdc, "time": t})
    return {
        "deposit_count": len(deposits), "deposit_usd": round(sum(d["usd"] for d in deposits), 2),
        "withdrawal_count": len(withdrawals), "withdrawal_usd": round(sum(w["usd"] for w in withdrawals), 2),
        "deposits": deposits[-25:], "withdrawals": withdrawals[-25:],
    }


# ── Detectors ────────────────────────────────────────────────────────────────

def run_detectors(fills_stats: dict[str, Any], ledger_stats: dict[str, Any],
                  state: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    fc = fills_stats.get("fill_count") or 0
    vol = fills_stats.get("volume_usd") or 0.0
    pnl = fills_stats.get("net_closed_pnl_usd") or 0.0
    fees = fills_stats.get("fees_usd") or 0.0

    # Wash trading: serious volume, near-zero economic outcome, fast flipping
    if fc >= 20 and vol >= 50_000:
        pnl_ratio = abs(pnl) / vol if vol else 0
        fast = fills_stats.get("fast_flips_under_60s") or 0
        if pnl_ratio < 0.002 and fast >= max(5, fc * 0.2):
            out.append({
                "detector": "wash_trading", "severity": "high",
                "verdict": "Volume pattern consistent with wash trading / volume farming.",
                "basis": f"${vol:,.0f} traded across {fc} fills with |PnL|/volume = {pnl_ratio:.4%} "
                         f"and {fast} sub-60s side flips — economically empty turnover.",
            })

    # Intentional-loss value transfer (laundering via trading)
    if fc >= 6 and pnl < 0 and vol > 0:
        loss_ratio = -pnl / vol
        top_loss_coins = [c for c, v in (fills_stats.get("by_coin") or {}).items() if v.get("pnl", 0) < 0]
        if loss_ratio >= 0.05 and -pnl >= 10_000:
            out.append({
                "detector": "intentional_loss_xfer", "severity": "high",
                "verdict": "Loss profile consistent with value transfer to trading counterparties "
                           "(documented perp-DEX laundering technique).",
                "basis": f"Net closed PnL {pnl:,.0f} USD = {loss_ratio:.1%} of ${vol:,.0f} volume, "
                         f"concentrated in {', '.join(top_loss_coins[:4]) or 'few markets'}; fees only ${fees:,.0f}. "
                         "LEAD: identify the profit side of these fills via time/market matching.",
            })

    # Pass-through account: deposit → thin trading → withdraw quickly
    dep, wdr = ledger_stats.get("deposit_usd") or 0, ledger_stats.get("withdrawal_usd") or 0
    if dep >= 10_000 and wdr >= dep * 0.8:
        deps, wds = ledger_stats.get("deposits") or [], ledger_stats.get("withdrawals") or []
        fast_pairs = 0
        for d in deps:
            for w in wds:
                dth = (w["time"] - d["time"]) / 3600000.0
                if 0 <= dth <= 24 and w["usd"] >= d["usd"] * 0.7:
                    fast_pairs += 1
                    break
        if fast_pairs or (vol < dep * 2):
            out.append({
                "detector": "pass_through_account", "severity": "medium" if vol else "high",
                "verdict": "Deposit/withdrawal profile consistent with a pass-through (placement) account.",
                "basis": f"${dep:,.0f} in / ${wdr:,.0f} out ({wdr / dep:.0%}), trading volume only ${vol:,.0f}; "
                         f"{fast_pairs} deposit→withdrawal pair(s) within 24h. "
                         "PIVOT: same EOA settles USDC on Arbitrum — trace it there.",
            })

    # Liquidation-heavy activity
    liq = fills_stats.get("liquidation_fills") or 0
    if liq >= 3 and fc and liq / fc >= 0.15:
        out.append({
            "detector": "liquidation_activity", "severity": "medium",
            "verdict": "Liquidation-heavy account — check for engineered self-liquidation value transfer.",
            "basis": f"{liq}/{fc} fills are liquidations. LEAD: compare opposite-side accounts funded "
                     "from a common Arbitrum ancestor.",
        })

    # HIP-3 thin/exotic market concentration
    by_coin = fills_stats.get("by_coin") or {}
    exotic = {c: v for c, v in by_coin.items() if c.upper().split("-")[0] not in MAJOR_COINS}
    exotic_vol = sum(v.get("volume", 0) for v in exotic.values())
    if vol >= 25_000 and exotic_vol / vol >= 0.7 and exotic:
        out.append({
            "detector": "hip3_thin_market", "severity": "medium",
            "verdict": "Activity concentrated in thin/permissionless (HIP-3-style) markets where "
                       "price manipulation and collusive transfer are cheap.",
            "basis": f"{exotic_vol / vol:.0%} of ${vol:,.0f} volume in non-major markets: "
                     f"{', '.join(list(exotic)[:5])}.",
        })

    if not out and fc:
        out.append({"detector": "none", "severity": "info",
                    "verdict": "No abuse pattern met detector thresholds.",
                    "basis": f"{fc} fills, ${vol:,.0f} volume, PnL {pnl:,.0f} USD analysed."})
    return out


# ── Public API ───────────────────────────────────────────────────────────────

async def analyze(address: str) -> dict[str, Any]:
    acct = await fetch_account(address)
    fills = acct.get("fills") or []
    ledger = acct.get("ledger") or []
    state = acct.get("state") or {}

    fills_stats = _fill_stats(fills if isinstance(fills, list) else [])
    ledger_stats = _ledger_stats(ledger if isinstance(ledger, list) else [])
    detectors = run_detectors(fills_stats, ledger_stats, state)

    margin = (state or {}).get("marginSummary") or {}
    positions = []
    for p in (state or {}).get("assetPositions") or []:
        pos = p.get("position") or {}
        positions.append({
            "coin": pos.get("coin"), "size": pos.get("szi"),
            "entry_px": pos.get("entryPx"), "position_value": pos.get("positionValue"),
            "unrealized_pnl": pos.get("unrealizedPnl"), "leverage": (pos.get("leverage") or {}).get("value"),
        })

    max_sev = "info"
    for d in detectors:
        if d["severity"] == "high":
            max_sev = "high"
            break
        if d["severity"] == "medium":
            max_sev = "medium"

    return {
        "address": address,
        "venue": "Hyperliquid (perp DEX)",
        "fetched_at": int(time.time() * 1000),
        "errors": acct.get("errors") or [],
        "account": {
            "account_value_usd": margin.get("accountValue"),
            "total_margin_used": margin.get("totalMarginUsed"),
            "total_ntl_pos": margin.get("totalNtlPos"),
            "withdrawable": (state or {}).get("withdrawable"),
            "positions": positions,
        },
        "fills_stats": fills_stats,
        "ledger_stats": ledger_stats,
        "detectors": detectors,
        "risk_level": max_sev,
        "pivots": [
            {"label": "Trace funding on Arbitrum (same EOA settles USDC there)",
             "route": f"/intel/{address}", "chain": "arb"},
            {"label": "Holistic cross-chain trace", "route": f"/trace/{address}", "chain": "arb"},
            {"label": "Nexus graph", "route": f"/nexus/{address}", "chain": "arb"},
        ],
        "method_note": "Deterministic detectors over public Hyperliquid fills/ledger data. "
                       "Verdicts are leads with computed bases — not conclusions.",
    }
