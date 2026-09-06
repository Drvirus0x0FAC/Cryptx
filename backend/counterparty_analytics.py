"""
Counterparty & exchange-usage analytics for an address.

Powers the Arkham-style panels (Exchange Usage, Top Counterparties, Entity
Predictions) shown across Address Intel, Nexus Graph, Holistic Trace, Fund Tracer
and TX Lens. Reuses the holistic engine's per-chain transfer fetchers and
counterparty classifier, and adds best-effort USD pricing via CoinGecko (free).

Values are reported in BOTH USD (priced) and native token amounts. Data depth is
bounded by the free public explorers (recent transfers), so totals reflect the
fetched window rather than an address's entire lifetime — surfaced in `note`.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any, Optional

import holistic_trace_engine as hte
import chain_fetchers

# Normalize many chain spellings/aliases to the engine's canonical ids.
CHAIN_ALIASES = {
    "ethereum": "eth", "eth": "eth", "mainnet": "eth", "erc20": "eth",
    "matic": "polygon", "polygon": "polygon", "poly": "polygon",
    "binance": "bsc", "bnb": "bsc", "bsc": "bsc", "bnb smart chain": "bsc", "bep20": "bsc",
    "arbitrum": "arbitrum", "arb": "arbitrum",
    "optimism": "optimism", "op": "optimism",
    "base": "base", "gnosis": "gnosis", "xdai": "gnosis",
    "avalanche": "avax", "avax": "avax", "avalanche c-chain": "avax", "avalanche-c": "avax",
    "bitcoin": "btc", "btc": "btc", "xbt": "btc",
    "tron": "tron", "trx": "tron", "trc20": "tron",
    "zcash": "zcash", "zec": "zcash",
    "solana": "solana", "sol": "solana", "spl": "solana",
    "ripple": "xrp", "xrp": "xrp",
    "litecoin": "litecoin", "ltc": "litecoin",
    "dogecoin": "dogecoin", "doge": "dogecoin",
    "bitcoin cash": "bch", "bitcoin-cash": "bch", "bch": "bch",
    "cardano": "cardano", "ada": "cardano",
    "polkadot": "polkadot", "dot": "polkadot",
    "cosmos": "cosmos", "atom": "cosmos", "cosmoshub": "cosmos",
    "near": "near", "aptos": "aptos", "apt": "aptos", "sui": "sui",
    "ton": "ton", "toncoin": "ton", "the open network": "ton",
    "algorand": "algorand", "algo": "algorand",
    "stellar": "stellar", "xlm": "stellar",
}


def _supported_chains() -> set[str]:
    return (set(hte.EVM_EXPLORERS) | set(hte.EVM_BLOCKSCOUT)
            | {"btc", "tron", "zcash"} | set(chain_fetchers.SUPPORTED))


def resolve_chain(addr: str, chain: str) -> str:
    """Map any chain spelling to a canonical engine id; fall back to address detection."""
    c = (chain or "").strip().lower()
    if c in ("", "auto", "none", "all"):
        return detect_chain(addr)
    c = CHAIN_ALIASES.get(c, c)
    if c in _supported_chains():
        return c
    return detect_chain(addr)

# Stablecoins are pegged ~$1 (avoids a price call and is accurate enough).
STABLES = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "FDUSD", "PYUSD", "USDD", "GUSD", "USDE"}

# Token/native symbol → CoinGecko id for live USD pricing.
CG_IDS = {
    "ETH": "ethereum", "WETH": "weth", "BTC": "bitcoin", "WBTC": "wrapped-bitcoin",
    "BNB": "binancecoin", "MATIC": "matic-network", "POL": "matic-network", "AVAX": "avalanche-2",
    "SOL": "solana", "XRP": "ripple", "LTC": "litecoin", "DOGE": "dogecoin", "BCH": "bitcoin-cash",
    "ADA": "cardano", "DOT": "polkadot", "ATOM": "cosmos", "NEAR": "near", "APT": "aptos",
    "SUI": "sui", "TON": "the-open-network", "ALGO": "algorand", "XLM": "stellar", "ZEC": "zcash",
    "TRX": "tron", "XDAI": "xdai", "LINK": "chainlink", "UNI": "uniswap", "AAVE": "aave",
    "SHIB": "shiba-inu", "PEPE": "pepe", "ARB": "arbitrum", "OP": "optimism", "CRO": "crypto-com-chain",
    "STETH": "staked-ether", "WSTETH": "wrapped-steth",
}

_WINDOW_SECONDS = {"1h": 3600, "24h": 86400, "1w": 604800, "1m": 2592000, "all": 0}


def detect_chain(addr: str) -> str:
    """Port of the frontend detector: pick a chain from the address format."""
    a = (addr or "").strip()
    if re.match(r"^0x[0-9a-fA-F]{40}$", a):
        return "eth"
    if re.match(r"^(bc1|tb1)[0-9a-zA-Z]{6,87}$", a):
        return "btc"
    if re.match(r"^t[13][a-km-zA-HJ-NP-Z1-9]{33}$", a):
        return "zcash"
    if re.match(r"^T[1-9A-HJ-NP-Za-km-z]{33}$", a):
        return "tron"
    if re.match(r"^addr1[0-9a-z]{20,}$", a):
        return "cardano"
    if re.match(r"^cosmos1[0-9a-z]{38,}$", a):
        return "cosmos"
    if re.match(r"^G[A-Z2-7]{55}$", a):
        return "stellar"
    if re.match(r"^[A-Z2-7]{58}$", a):
        return "algorand"
    if re.match(r"^[EU]Q[A-Za-z0-9_-]{46}$", a):
        return "ton"
    if re.match(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$", a):
        return "xrp"
    if re.match(r"^(ltc1[0-9a-z]{6,}|[LM][1-9A-HJ-NP-Za-km-z]{26,33})$", a):
        return "litecoin"
    if re.match(r"^D[1-9A-HJ-NP-Za-km-z]{32,34}$", a):
        return "dogecoin"
    if re.search(r"(\.near|\.testnet)$", a):
        return "near"
    if re.match(r"^(bitcoincash:)?[qp][0-9a-z]{38,}$", a):
        return "bch"
    if re.match(r"^1[a-km-zA-HJ-NP-Z1-9]{46,47}$", a):
        return "polkadot"
    if re.match(r"^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$", a):
        return "btc"
    return "eth"


async def _prices(session, symbols: set[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    ids: set[str] = set()
    for s in symbols:
        su = (s or "").upper()
        if su in STABLES:
            out[su] = 1.0
        elif su in CG_IDS:
            ids.add(CG_IDS[su])
    if ids:
        url = "https://api.coingecko.com/api/v3/simple/price"
        try:
            async with session.get(url, params={"ids": ",".join(sorted(ids)), "vs_currencies": "usd"}, timeout=20) as r:
                data = await r.json(content_type=None)
        except Exception:  # noqa: BLE001
            data = {}
        inv = {v: k for k, v in CG_IDS.items()}
        for cgid, obj in (data or {}).items():
            sym = inv.get(cgid)
            if sym and isinstance(obj, dict):
                out[sym.upper()] = float(obj.get("usd") or 0)
    return out


def _fmt_native(by_token: dict[str, float]) -> str:
    """Compact native-amount label, e.g. '12.4 ETH + 50.0K USDT'."""
    parts = []
    for tok, amt in sorted(by_token.items(), key=lambda kv: -kv[1])[:2]:
        if amt >= 1_000_000:
            parts.append(f"{amt / 1_000_000:.2f}M {tok}")
        elif amt >= 1_000:
            parts.append(f"{amt / 1_000:.1f}K {tok}")
        elif amt >= 1:
            parts.append(f"{amt:.2f} {tok}")
        else:
            parts.append(f"{amt:.4f} {tok}")
    return " + ".join(parts)


async def analyze(address: str, chain: str = "auto", window: str = "all", limit: int = 150) -> dict[str, Any]:
    addr = (address or "").strip()
    if not addr:
        return {"error": "address is required"}
    ch = resolve_chain(addr, chain)
    cutoff = 0
    if window in _WINDOW_SECONDS and _WINDOW_SECONDS[window]:
        cutoff = int(time.time()) - _WINDOW_SECONDS[window]

    errors: list[str] = []
    try:
        import aiohttp
    except Exception as exc:  # noqa: BLE001
        return {"error": f"aiohttp unavailable: {exc}", "address": addr, "chain": ch}

    rows: list[dict[str, Any]] = []
    prices: dict[str, float] = {}
    async with aiohttp.ClientSession(headers={"User-Agent": "CrypTX-Analytics/1.0"}) as session:
        import os
        api_key = os.environ.get("ETHERSCAN_API_KEY", "") if ch in hte.EVM_EXPLORERS else ""
        fetched, err = await hte.fetch_transfers(addr, ch, api_key=api_key, limit=limit)
        if err:
            errors.append(err)
        rows = [r for r in (fetched or []) if (not cutoff or int(r.get("timestamp") or 0) >= cutoff)]
        prices = await _prices(session, {str(r.get("asset") or "") for r in rows})

    me = hte._addr(addr)
    # ── Aggregation accumulators ──────────────────────────────────────────────
    dep_by_ex: dict[str, dict[str, Any]] = defaultdict(lambda: {"usd": 0.0, "native": defaultdict(float)})
    wd_by_ex: dict[str, dict[str, Any]] = defaultdict(lambda: {"usd": 0.0, "native": defaultdict(float)})
    cp_agg: dict[str, dict[str, Any]] = {}
    dep_series: dict[str, float] = defaultdict(float)   # month → usd
    wd_series: dict[str, float] = defaultdict(float)
    total_dep_usd = total_wd_usd = 0.0
    timestamps: list[int] = []

    for r in rows:
        frm, to = hte._addr(r.get("from")), hte._addr(r.get("to"))
        if me not in (frm, to):
            continue
        direction = "out" if frm == me else "in"
        cp = to if direction == "out" else frm
        if not cp or cp == me:
            continue
        asset = (str(r.get("asset") or "") or "?").upper()
        value = float(r.get("value") or 0)
        # Bug #2 fix: lstrip("W") strips ALL leading W's (e.g. "WWAY" -> "AY").
        # Use the safe unwrap helper from constants instead (only unwraps known
        # wrapped-native tokens like WETH -> ETH).
        unwrapped = asset
        try:
            import constants
            unwrapped = constants.unwrap_native(asset).upper()
        except Exception:
            unwrapped = asset[1:] if asset.startswith("W") and len(asset) > 1 else asset
        usd = value * prices.get(asset, prices.get(unwrapped, 0.0))
        ts = int(r.get("timestamp") or 0)
        rchain = r.get("chain") or ch
        if ts:
            timestamps.append(ts)
        month = time.strftime("%Y-%m", time.gmtime(ts)) if ts else "—"

        c = hte.classify_counterparty(cp, rchain)
        is_exchange = c.get("type") == "exchange"
        ex_label = c.get("label") or "Unknown exchange"

        # Exchange usage (subject → exchange = deposit; exchange → subject = withdrawal)
        if is_exchange:
            if direction == "out":
                dep_by_ex[ex_label]["usd"] += usd
                dep_by_ex[ex_label]["native"][asset] += value
                total_dep_usd += usd
                dep_series[month] += usd
            else:
                wd_by_ex[ex_label]["usd"] += usd
                wd_by_ex[ex_label]["native"][asset] += value
                total_wd_usd += usd
                wd_series[month] += usd

        # Top counterparties (grouped by address)
        a = cp_agg.setdefault(cp, {
            "address": cp, "entity": c.get("label") or "", "type": c.get("type") or "unknown",
            "sanctioned": bool(c.get("sanctioned")), "risk": int(c.get("risk") or 0),
            "chains": set(), "tx": 0, "usd": 0.0, "in_usd": 0.0, "out_usd": 0.0,
            "native": defaultdict(float), "first_seen": ts or 0, "last_seen": ts or 0,
        })
        a["chains"].add(rchain)
        a["tx"] += 1
        a["usd"] += usd
        a["native"][asset] += value
        a["in_usd" if direction == "in" else "out_usd"] += usd
        if ts:
            a["first_seen"] = min(a["first_seen"] or ts, ts)
            a["last_seen"] = max(a["last_seen"], ts)

    # ── Build exchange-usage tables (ranked + %) ──────────────────────────────
    def _rank(table: dict[str, dict[str, Any]], total: float) -> list[dict[str, Any]]:
        items = []
        for name, v in table.items():
            items.append({
                "exchange": name, "usd": round(v["usd"], 2),
                "native_label": _fmt_native(v["native"]),
                "pct": round(100 * v["usd"] / total, 1) if total > 0 else 0.0,
            })
        return sorted(items, key=lambda x: -x["usd"])

    # ── Build counterparties list ─────────────────────────────────────────────
    counterparties = []
    for v in cp_agg.values():
        counterparties.append({
            "address": v["address"], "entity": v["entity"], "type": v["type"],
            "sanctioned": v["sanctioned"], "risk": v["risk"],
            "chains": sorted(v["chains"]), "tx": v["tx"],
            "usd": round(v["usd"], 2), "in_usd": round(v["in_usd"], 2),
            "out_usd": round(v["out_usd"], 2), "net_usd": round(v["out_usd"] - v["in_usd"], 2),
            "native_label": _fmt_native(v["native"]),
            "tokens": sorted(v["native"].keys()),
            "first_seen": v["first_seen"], "last_seen": v["last_seen"],
        })
    counterparties.sort(key=lambda x: -x["usd"])

    def _series(d: dict[str, float]) -> list[dict[str, Any]]:
        cum, out = 0.0, []
        for m in sorted(k for k in d if k != "—"):
            cum += d[m]
            out.append({"t": m, "value": round(cum, 2)})
        return out

    start = min(timestamps) if timestamps else 0
    end = max(timestamps) if timestamps else 0
    days = round((end - start) / 86400) if start and end else 0

    # ── Entity predictions: classify the SUBJECT itself first (mixer, sanctioned,
    #    exchange, bridge, dex via registries/VASP/sanctions), then layer on the
    #    behavioral signals from its counterparty mix. ─────────────────────────
    try:
        subject_class = hte.classify_counterparty(me, ch)
    except Exception:  # noqa: BLE001
        subject_class = {"type": "unknown", "label": "", "sanctioned": False}
    predictions = _entity_predictions(counterparties, total_dep_usd, total_wd_usd, subject_class)

    return {
        "address": addr, "chain": ch, "window": window,
        "date_range": {"start": start, "end": end, "days": days},
        "totals": {
            "deposit_usd": round(total_dep_usd, 2), "withdrawal_usd": round(total_wd_usd, 2),
            "tx_count": len(rows), "counterparty_count": len(counterparties),
        },
        "exchange_usage": {
            "deposits": {"total_usd": round(total_dep_usd, 2), "items": _rank(dep_by_ex, total_dep_usd)},
            "withdrawals": {"total_usd": round(total_wd_usd, 2), "items": _rank(wd_by_ex, total_wd_usd)},
            "deposit_series": _series(dep_series),
            "withdrawal_series": _series(wd_series),
        },
        "counterparties": counterparties[:30],
        "entity_predictions": predictions,
        "errors": errors,
        "note": ("Figures cover the most recent transfers available from free public explorers, "
                 "not the address's full lifetime. USD is best-effort (CoinGecko spot; stablecoins=$1; "
                 "unpriced tokens count as $0). Exchange labels come from the VASP directory."),
        "disclaimer": "Counterparty attributions are investigative leads, not proof.",
        "generated_at": int(time.time()),
    }


def _entity_predictions(counterparties, dep_usd, wd_usd, subject_class=None) -> list[dict[str, Any]]:
    """Entity-type guesses. Classifies the SUBJECT address directly first (strongest
    signal), then layers behavioral inference from its counterparty mix."""
    preds: list[dict[str, Any]] = []

    def add(label, conf, why):
        preds.append({"label": label, "confidence": round(conf, 2), "rationale": why})

    # ── 1) The subject's own identity (registries / VASP / sanctions) ──────────
    sc = subject_class or {}
    s_type = sc.get("type", "unknown")
    s_label = sc.get("label") or ""
    suffix = f" · {s_label}" if s_label else ""
    if sc.get("sanctioned"):
        add(f"Sanctioned entity{suffix}", 0.97, "Subject address matches a sanctions list (e.g. OFAC SDN).")
    if s_type == "mixer":
        add(f"Mixer / tumbler{suffix}", 0.96, "Subject is a known mixing/anonymizing contract (e.g. Tornado Cash).")
    elif s_type == "exchange":
        add(f"Exchange / VASP{suffix}", 0.9, "Subject is a known exchange or VASP wallet in the directory.")
    elif s_type == "bridge":
        add(f"Cross-chain bridge{suffix}", 0.88, "Subject is a known bridge contract.")
    elif s_type == "dex":
        add(f"DEX / AMM router{suffix}", 0.85, "Subject is a known DEX router contract.")
    elif s_type == "contract":
        add("Smart contract", 0.7, "Subject is a contract address, not an EOA wallet.")

    # ── 2) Behavioral inference from the counterparty mix ──────────────────────
    n = len(counterparties)
    if not n:
        if not preds:
            add("Unclassified wallet", 0.3, "No transfers or known attribution in the fetched window.")
        return sorted(preds, key=lambda p: -p["confidence"])
    ex = sum(1 for c in counterparties if c["type"] == "exchange")
    mix = sum(1 for c in counterparties if c["type"] == "mixer")
    dex = sum(1 for c in counterparties if c["type"] == "dex")
    sanc = sum(1 for c in counterparties if c["sanctioned"])

    if ex / n > 0.4:
        add("Exchange-adjacent / OTC desk", min(0.85, 0.4 + ex / n / 2),
            f"{ex}/{n} counterparties are known exchanges; high deposit/withdrawal concentration.")
    if mix:
        add("Obfuscation user", min(0.9, 0.5 + 0.1 * mix),
            f"Interacts with {mix} mixer(s) — funds laundering / privacy behavior.")
    if dex / max(1, n) > 0.3:
        add("DeFi trader", min(0.75, 0.3 + dex / n), f"{dex}/{n} counterparties are DEX routers.")
    if sanc:
        add("Sanctions exposure", min(0.97, 0.7 + 0.1 * sanc),
            f"{sanc} sanctioned counterparties in scope.")
    if dep_usd > 5 * (wd_usd + 1):
        add("Accumulation / cash-in wallet", 0.55, "Deposits to exchanges far exceed withdrawals.")
    elif wd_usd > 5 * (dep_usd + 1):
        add("Distribution / cash-out wallet", 0.55, "Withdrawals from exchanges far exceed deposits.")
    if not preds:
        add("Unclassified wallet", 0.3, "No dominant behavioral signal in the fetched window.")
    return sorted(preds, key=lambda p: -p["confidence"])
