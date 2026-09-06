"""
Multi-chain transfer fetchers for the Holistic trace engine.

Each fetcher is best-effort and returns a tuple ``(rows, error)`` where ``rows`` is a
list of normalized transfer dicts:

    {"chain", "from", "to", "asset", "value", "value_usd", "tx_hash", "timestamp"}

All use free, public, no-key (or generous free-tier) endpoints. Any network or
shape problem is caught and surfaced as an error string so the trace degrades to
"no flow on chain" rather than crashing. Addresses are preserved verbatim
(case-sensitive Base58/Base32/Bech32) — only EVM addresses are lowercased upstream.

Supported here: solana, xrp, litecoin, dogecoin, bitcoin-cash (bch), cardano,
polkadot, cosmos (atom), near, aptos, sui, ton, algorand, stellar.
(Avalanche is handled as an EVM chain in holistic_trace_engine; btc/tron/zcash too.)
"""
from __future__ import annotations

import calendar
import time
from typing import Any, Optional


def _a(v: Any) -> str:
    return str(v or "").strip()


def _iso_epoch(s: Any) -> int:
    """Parse common timestamp shapes (ISO-8601, 'YYYY-MM-DD HH:MM:SS') to epoch seconds."""
    s = _a(s)
    if not s:
        return 0
    if s.isdigit():
        # already epoch (seconds or ms)
        n = int(s)
        return n // 1000 if n > 10_000_000_000 else n
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(calendar.timegm(time.strptime(s.split("+")[0].rstrip("Z"), fmt.rstrip("Z"))))
        except (ValueError, TypeError):
            continue
    return 0


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


async def _get_json(session, url, params=None, headers=None, timeout=25):
    """Guarded GET: per-provider bounded concurrency, rate budget, circuit breaker.

    Falls back to a raw request only if the http_cache guard layer is unavailable.
    """
    try:
        import http_cache
        return await http_cache.guarded_get_json(session, url, params=params,
                                                 headers=headers, timeout=timeout)
    except ImportError:
        pass
    try:
        async with session.get(url, params=params, headers=headers, timeout=timeout) as resp:
            return await resp.json(content_type=None), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


async def _post_json(session, url, payload, headers=None, timeout=25):
    try:
        import http_cache
        return await http_cache.guarded_post_json(session, url, payload,
                                                  headers=headers, timeout=timeout)
    except ImportError:
        pass
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    try:
        async with session.post(url, json=payload, headers=h, timeout=timeout) as resp:
            return await resp.json(content_type=None), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _row(chain, frm, to, asset, value, tx_hash, ts):
    # NOTE: value_usd is intentionally 0.0 here — USD valuation is computed
    # downstream by price_service.convert_batch (which has the CoinGecko price
    # cache). This keeps fetchers price-source-agnostic.
    return {"chain": chain, "from": _a(frm), "to": _a(to), "asset": asset,
            "value": float(value or 0), "value_usd": 0.0,
            "tx_hash": _a(tx_hash), "timestamp": int(ts or 0)}


# ---------------------------------------------------------------------------
# UTXO chains via Blockchair (Litecoin, Dogecoin, Bitcoin Cash)
# ---------------------------------------------------------------------------
async def _blockchair_utxo(session, chain, slug, asset, decimals, address, limit):
    base = f"https://api.blockchair.com/{slug}/dashboards"
    data, err = await _get_json(session, f"{base}/address/{address}", params={"limit": "20"})
    if err:
        return [], err
    try:
        tx_hashes = list(data["data"][address]["transactions"])[:min(limit, 10)]
    except (KeyError, TypeError):
        return [], f"no {asset} activity found for address"
    rows, me, div = [], _a(address), float(10 ** decimals)
    for h in tx_hashes:
        td, e2 = await _get_json(session, f"{base}/transaction/{h}")
        if e2 or not isinstance(td, dict):
            continue
        try:
            tx = td["data"][h]
        except (KeyError, TypeError):
            continue
        ts = _iso_epoch((tx.get("transaction") or {}).get("time"))
        ins = tx.get("inputs") or []
        outs = tx.get("outputs") or []
        senders = {_a(i.get("recipient")) for i in ins if i.get("recipient")}
        if me in senders:  # outgoing
            for o in outs:
                dst = _a(o.get("recipient"))
                if dst and dst != me:
                    rows.append(_row(chain, me, dst, asset, (o.get("value") or 0) / div, h, ts))
        else:  # incoming
            for i in ins:
                src = _a(i.get("recipient"))
                if src and src != me:
                    rows.append(_row(chain, src, me, asset, (i.get("value") or 0) / div, h, ts))
    return rows, (None if rows else f"no transparent {asset} flows found")


# ---------------------------------------------------------------------------
# XRP Ledger via XRPScan
# ---------------------------------------------------------------------------
async def _xrp(session, address, limit):
    url = f"https://api.xrpscan.com/api/v1/account/{address}/transactions"
    data, err = await _get_json(session, url)
    if err:
        return [], err
    txs = data if isinstance(data, list) else (data.get("transactions") if isinstance(data, dict) else None)
    if not isinstance(txs, list):
        return [], "bad response from XRPScan"
    rows = []
    for t in txs[:limit]:
        if t.get("TransactionType") != "Payment":
            continue
        amt = t.get("Amount")
        if isinstance(amt, dict):
            asset, value = (amt.get("currency") or "IOU")[:12], _num(amt.get("value"))
        else:
            asset, value = "XRP", _num(amt) / 1e6
        rows.append(_row("xrp", t.get("Account"), t.get("Destination"), asset, value,
                         t.get("hash"), _iso_epoch(t.get("date"))))
    return rows, (None if rows else "no XRP payments found")


# ---------------------------------------------------------------------------
# Solana via public JSON-RPC (native SOL + SPL token balance deltas)
# ---------------------------------------------------------------------------
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
KNOWN_SPL = {"Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
             "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC"}


async def _solana(session, address, limit):
    sigs_req = {"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                "params": [address, {"limit": min(limit, 20)}]}
    data, err = await _post_json(session, SOLANA_RPC, sigs_req)
    if err:
        return [], err
    sigs = (data or {}).get("result") or []
    if not sigs:
        return [], "no Solana signatures found for address"
    rows = []
    for s in sigs[:min(limit, 20)]:
        sig = s.get("signature")
        if not sig:
            continue
        tx_req = {"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                  "params": [sig, {"maxSupportedTransactionVersion": 0, "encoding": "jsonParsed"}]}
        td, e2 = await _post_json(session, SOLANA_RPC, tx_req)
        res = (td or {}).get("result") if not e2 else None
        if not res:
            continue
        ts = int(res.get("blockTime") or 0)
        meta = res.get("meta") or {}
        msg = (res.get("transaction") or {}).get("message") or {}
        keys = [k.get("pubkey") if isinstance(k, dict) else k for k in (msg.get("accountKeys") or [])]
        pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
        # Native SOL: deltas across accounts → sender (neg) to receivers (pos)
        deltas = []
        for i, key in enumerate(keys):
            if i < len(pre) and i < len(post):
                d = (post[i] - pre[i]) / 1e9
                if abs(d) > 1e-9:
                    deltas.append((key, d))
        senders = [(k, -d) for k, d in deltas if d < 0]
        receivers = [(k, d) for k, d in deltas if d > 0]
        if senders and receivers:
            src = max(senders, key=lambda x: x[1])[0]
            for rk, rv in receivers:
                if rk != src:
                    rows.append(_row("solana", src, rk, "SOL", rv, sig, ts))
        # SPL tokens via pre/post token balances
        pretok = {(b.get("accountIndex"), b.get("mint")): b for b in (meta.get("preTokenBalances") or [])}
        for b in meta.get("postTokenBalances") or []:
            mint = b.get("mint")
            owner = b.get("owner")
            ui = (b.get("uiTokenAmount") or {})
            post_amt = _num(ui.get("uiAmount"))
            pb = pretok.get((b.get("accountIndex"), mint))
            pre_amt = _num((pb or {}).get("uiTokenAmount", {}).get("uiAmount")) if pb else 0.0
            d = post_amt - pre_amt
            if abs(d) > 1e-9 and owner:
                asset = KNOWN_SPL.get(mint, f"SPL:{(mint or '')[:4]}")
                if d > 0:
                    rows.append(_row("solana", f"spl:{(mint or '')[:8]}", owner, asset, d, sig, ts))
                else:
                    rows.append(_row("solana", owner, f"spl:{(mint or '')[:8]}", asset, -d, sig, ts))
    return rows, (None if rows else "no decodable Solana transfers found")


# ---------------------------------------------------------------------------
# TON via TON Center
# ---------------------------------------------------------------------------
async def _ton(session, address, limit):
    url = "https://toncenter.com/api/v2/getTransactions"
    data, err = await _get_json(session, url, params={"address": address, "limit": str(min(limit, 25))})
    if err:
        return [], err
    if not isinstance(data, dict) or not data.get("ok"):
        return [], "bad response from TON Center"
    rows, me = [], _a(address)
    for t in data.get("result") or []:
        h = (t.get("transaction_id") or {}).get("hash", "")
        ts = int(t.get("utime") or 0)
        inm = t.get("in_msg") or {}
        if inm.get("source") and _num(inm.get("value")) > 0:
            rows.append(_row("ton", inm.get("source"), me, "TON", _num(inm.get("value")) / 1e9, h, ts))
        for om in t.get("out_msgs") or []:
            if om.get("destination") and _num(om.get("value")) > 0:
                rows.append(_row("ton", me, om.get("destination"), "TON", _num(om.get("value")) / 1e9, h, ts))
    return rows, (None if rows else "no TON transfers found")


# ---------------------------------------------------------------------------
# NEAR via NearBlocks
# ---------------------------------------------------------------------------
async def _near(session, address, limit):
    url = f"https://api.nearblocks.io/v1/account/{address}/txns"
    data, err = await _get_json(session, url, params={"per_page": str(min(limit, 25)), "order": "desc"})
    if err:
        return [], err
    txns = (data or {}).get("txns")
    if not isinstance(txns, list):
        return [], "bad response from NearBlocks"
    rows = []
    for t in txns[:limit]:
        deposit = _num((t.get("actions_agg") or {}).get("deposit")) / 1e24
        if deposit <= 0:
            continue
        ts = int(_num(t.get("block_timestamp")) / 1e9)
        rows.append(_row("near", t.get("predecessor_account_id"), t.get("receiver_account_id"),
                         "NEAR", deposit, t.get("transaction_hash"), ts))
    return rows, (None if rows else "no NEAR transfers with deposits found")


# ---------------------------------------------------------------------------
# Aptos via fullnode REST
# ---------------------------------------------------------------------------
async def _aptos(session, address, limit):
    url = f"https://fullnode.mainnet.aptoslabs.com/v1/accounts/{address}/transactions"
    data, err = await _get_json(session, url, params={"limit": str(min(limit, 25))})
    if err:
        return [], err
    if not isinstance(data, list):
        return [], "bad response from Aptos fullnode"
    rows = []
    for t in data:
        payload = t.get("payload") or {}
        fn = _a(payload.get("function"))
        if not (fn.endswith("::coin::transfer") or fn.endswith("::aptos_account::transfer")
                or fn.endswith("::aptos_account::transfer_coins")):
            continue
        args = payload.get("arguments") or []
        if len(args) < 2:
            continue
        recipient, amount = args[0], args[-1]
        targs = payload.get("type_arguments") or []
        asset = "APT" if (not targs or "aptos_coin" in _a(targs[0]).lower()) else _a(targs[0]).split("::")[-1][:12]
        decimals = 1e8 if asset == "APT" else 1e6
        ts = int(_num(t.get("timestamp")) / 1e6)
        rows.append(_row("aptos", t.get("sender"), recipient, asset, _num(amount) / decimals, t.get("hash"), ts))
    return rows, (None if rows else "no Aptos coin transfers found")


# ---------------------------------------------------------------------------
# Sui via JSON-RPC (balance changes, both directions)
# ---------------------------------------------------------------------------
SUI_RPC = "https://fullnode.mainnet.sui.io"


async def _sui_dir(session, address, direction, limit):
    filt = {"FromAddress": address} if direction == "from" else {"ToAddress": address}
    req = {"jsonrpc": "2.0", "id": 1, "method": "suix_queryTransactionBlocks",
           "params": [{"filter": filt, "options": {"showBalanceChanges": True}}, None, min(limit, 20), True]}
    data, err = await _post_json(session, SUI_RPC, req)
    if err:
        return [], err
    res = (data or {}).get("result") or {}
    rows = []
    for tx in res.get("data") or []:
        digest = tx.get("digest", "")
        ts = int(_num(tx.get("timestampMs")) / 1000)
        changes = tx.get("balanceChanges") or []
        senders = [(c.get("owner"), -_num(c.get("amount")), c.get("coinType")) for c in changes if _num(c.get("amount")) < 0]
        receivers = [(c.get("owner"), _num(c.get("amount")), c.get("coinType")) for c in changes if _num(c.get("amount")) > 0]
        for so, sv, sc in senders:
            for ro, rv, rc in receivers:
                asset = "SUI" if "sui::SUI" in _a(sc) else _a(sc).split("::")[-1][:12]
                so_a = (so or {}).get("AddressOwner") if isinstance(so, dict) else so
                ro_a = (ro or {}).get("AddressOwner") if isinstance(ro, dict) else ro
                if so_a and ro_a and so_a != ro_a:
                    rows.append(_row("sui", so_a, ro_a, asset, min(sv, rv) / 1e9, digest, ts))
    return rows, None


async def _sui(session, address, limit):
    out_rows, e1 = await _sui_dir(session, address, "from", limit)
    in_rows, e2 = await _sui_dir(session, address, "to", limit)
    rows = (out_rows or []) + (in_rows or [])
    if rows:
        return rows, None
    return [], (e1 or e2 or "no Sui transfers found")


# ---------------------------------------------------------------------------
# Algorand via AlgoNode indexer
# ---------------------------------------------------------------------------
async def _algorand(session, address, limit):
    url = f"https://mainnet-idx.algonode.cloud/v2/accounts/{address}/transactions"
    data, err = await _get_json(session, url, params={"limit": str(min(limit, 25))})
    if err:
        return [], err
    txs = (data or {}).get("transactions")
    if not isinstance(txs, list):
        return [], "bad response from AlgoNode"
    rows = []
    for t in txs[:limit]:
        ts = int(t.get("round-time") or 0)
        h = t.get("id", "")
        sender = t.get("sender")
        pay = t.get("payment-transaction")
        axfer = t.get("asset-transfer-transaction")
        if pay and pay.get("receiver"):
            rows.append(_row("algorand", sender, pay.get("receiver"), "ALGO", _num(pay.get("amount")) / 1e6, h, ts))
        elif axfer and axfer.get("receiver"):
            rows.append(_row("algorand", sender, axfer.get("receiver"),
                             f"ASA:{axfer.get('asset-id')}", _num(axfer.get("amount")), h, ts))
    return rows, (None if rows else "no Algorand payments found")


# ---------------------------------------------------------------------------
# Stellar via Horizon
# ---------------------------------------------------------------------------
async def _stellar(session, address, limit):
    url = f"https://horizon.stellar.org/accounts/{address}/payments"
    data, err = await _get_json(session, url, params={"limit": str(min(limit, 50)), "order": "desc"})
    if err:
        return [], err
    recs = ((data or {}).get("_embedded") or {}).get("records")
    if not isinstance(recs, list):
        return [], "bad response from Horizon"
    rows = []
    for p in recs[:limit]:
        if p.get("type") not in ("payment", "path_payment_strict_send", "path_payment_strict_receive"):
            continue
        asset = "XLM" if p.get("asset_type") == "native" else _a(p.get("asset_code") or "ASSET")[:12]
        rows.append(_row("stellar", p.get("from"), p.get("to"), asset, _num(p.get("amount")),
                         p.get("transaction_hash"), _iso_epoch(p.get("created_at"))))
    return rows, (None if rows else "no Stellar payments found")


# ---------------------------------------------------------------------------
# Cardano via Koios (UTXO, best-effort)
# ---------------------------------------------------------------------------
async def _cardano(session, address, limit):
    base = "https://api.koios.rest/api/v1"
    data, err = await _post_json(session, f"{base}/address_txs", {"_addresses": [address]})
    if err:
        return [], err
    if not isinstance(data, list) or not data:
        return [], "no Cardano transactions found for address"
    # Bug #10 fix: capture block_time per tx_hash so timestamps aren't all 0.
    tx_times = {t.get("tx_hash"): _iso_epoch(t.get("tx_block_time") or t.get("block_time"))
                for t in data}
    hashes = [t.get("tx_hash") for t in data[:min(limit, 10)] if t.get("tx_hash")]
    utxos, e2 = await _post_json(session, f"{base}/tx_utxos", {"_tx_hashes": hashes})
    if e2 or not isinstance(utxos, list):
        return [], (e2 or "bad response from Koios tx_utxos")
    rows, me = [], _a(address)
    for tx in utxos:
        h = tx.get("tx_hash", "")
        ts = tx_times.get(h, 0)
        ins = tx.get("inputs") or []
        outs = tx.get("outputs") or []
        in_addrs = {_a((i.get("payment_addr") or {}).get("bech32")) for i in ins}
        if me in in_addrs:  # outgoing
            for o in outs:
                dst = _a((o.get("payment_addr") or {}).get("bech32"))
                if dst and dst != me:
                    rows.append(_row("cardano", me, dst, "ADA", _num(o.get("value")) / 1e6, h, ts))
        else:  # incoming
            for i in ins:
                src = _a((i.get("payment_addr") or {}).get("bech32"))
                if src and src != me:
                    rows.append(_row("cardano", src, me, "ADA", _num(i.get("value")) / 1e6, h, ts))
    return rows, (None if rows else "no Cardano flows decoded")


# ---------------------------------------------------------------------------
# Polkadot via Subscan
# ---------------------------------------------------------------------------
async def _polkadot(session, address, limit):
    url = "https://polkadot.api.subscan.io/api/v2/scan/transfers"
    data, err = await _post_json(session, url, {"address": address, "row": min(limit, 25), "page": 0})
    if err:
        return [], err
    transfers = ((data or {}).get("data") or {}).get("transfers")
    if not isinstance(transfers, list):
        return [], "bad response from Subscan"
    rows = []
    for t in transfers[:limit]:
        rows.append(_row("polkadot", t.get("from"), t.get("to"), _a(t.get("asset_symbol") or "DOT"),
                         _num(t.get("amount")), t.get("hash"), int(t.get("block_timestamp") or 0)))
    return rows, (None if rows else "no Polkadot transfers found")


# ---------------------------------------------------------------------------
# Cosmos Hub (ATOM) via PublicNode LCD
# ---------------------------------------------------------------------------
COSMOS_LCD = "https://cosmos-rest.publicnode.com"


async def _cosmos_query(session, event, limit):
    url = f"{COSMOS_LCD}/cosmos/tx/v1beta1/txs"
    params = {"events": event, "pagination.limit": str(min(limit, 20)), "order_by": "ORDER_BY_DESC"}
    data, err = await _get_json(session, url, params=params)
    if err:
        return [], err
    rows = []
    responses = (data or {}).get("tx_responses") or []
    for r in responses:
        h = r.get("txhash", "")
        ts = _iso_epoch(r.get("timestamp"))
        msgs = (((r.get("tx") or {}).get("body") or {}).get("messages")) or []
        for m in msgs:
            if "MsgSend" not in _a(m.get("@type")):
                continue
            amts = m.get("amount") or []
            total = sum(_num(a.get("amount")) for a in amts if a.get("denom") == "uatom") / 1e6
            if total > 0:
                rows.append(_row("cosmos", m.get("from_address"), m.get("to_address"), "ATOM", total, h, ts))
    return rows, None


async def _cosmos(session, address, limit):
    out_rows, e1 = await _cosmos_query(session, f"transfer.sender='{address}'", limit)
    in_rows, e2 = await _cosmos_query(session, f"transfer.recipient='{address}'", limit)
    rows = (out_rows or []) + (in_rows or [])
    if rows:
        # de-dup by (hash, from, to, value)
        seen, uniq = set(), []
        for r in rows:
            k = (r["tx_hash"], r["from"], r["to"], r["value"])
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        return uniq, None
    return [], (e1 or e2 or "no Cosmos transfers found")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
SUPPORTED = (
    "solana", "xrp", "litecoin", "dogecoin", "bch", "cardano", "polkadot",
    "cosmos", "near", "aptos", "sui", "ton", "algorand", "stellar",
)


async def fetch_chain(session, chain: str, address: str, limit: int = 40):
    """Dispatch to the right fetcher. Returns (rows, error) or (None, None) if unhandled."""
    c = (chain or "").lower()
    if c == "solana":
        return await _solana(session, address, limit)
    if c == "xrp":
        return await _xrp(session, address, limit)
    if c == "litecoin":
        return await _blockchair_utxo(session, "litecoin", "litecoin", "LTC", 8, address, limit)
    if c == "dogecoin":
        return await _blockchair_utxo(session, "dogecoin", "dogecoin", "DOGE", 8, address, limit)
    if c == "bch":
        return await _blockchair_utxo(session, "bch", "bitcoin-cash", "BCH", 8, address, limit)
    if c == "cardano":
        return await _cardano(session, address, limit)
    if c == "polkadot":
        return await _polkadot(session, address, limit)
    if c == "cosmos":
        return await _cosmos(session, address, limit)
    if c == "near":
        return await _near(session, address, limit)
    if c == "aptos":
        return await _aptos(session, address, limit)
    if c == "sui":
        return await _sui(session, address, limit)
    if c == "ton":
        return await _ton(session, address, limit)
    if c == "algorand":
        return await _algorand(session, address, limit)
    if c == "stellar":
        return await _stellar(session, address, limit)
    return None, None
