"""
CrypTX Predictive Intelligence Engine
=====================================
Hybrid predictive engine for detecting crypto crimes BEFORE they happen.

Architecture (3 layers, blended):
  1. Precursor pattern detectors  — deterministic, explainable "pre-crime"
     signatures (mixer staging, cash-out fanning, peel-chain setup, drainer
     recon, rug-pull deployer patterns). Always available.
  2. Statistical anomaly layer    — robust z-scores (median/MAD) of an
     address's behavioral features vs. the population baseline learned from
     every address CrypTX has ever analyzed.
  3. Machine-learning layer       — logistic-regression classifier trained on
     historic labeled data (sanctions, scam networks, local illicit labels vs.
     trusted entities). Pure-Python (stdlib only) so it runs anywhere; uses
     scikit-learn automatically when installed. Degrades gracefully when
     training data is sparse.

Prediction types:
  laundering   — imminent laundering / cash-out staging
  rugpull      — scam / rug-pull early warning
  trajectory   — address risk-escalation forecast (7/30/90-day horizons)
  victim       — wallet likely to be drained / targeted next

Every prediction returns probability, confidence, time horizon, ranked
evidence, feature contributions, and recommended investigator actions —
explainability is a first-class output (Daubert-friendly).
"""
from __future__ import annotations

import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import database as db

try:  # optional acceleration — engine is fully functional without it
    from sklearn.linear_model import LogisticRegression as _SkLogReg  # type: ignore
    _HAS_SKLEARN = True
except Exception:
    _HAS_SKLEARN = False

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

MIXER_LABELS = {
    "tornado", "tornado cash", "tornado.cash", "mixer", "tumbler", "blender",
    "chipmixer", "sinbad", "wasabi", "coinjoin", "samourai", "whirlpool",
    "railgun", "cryptomixer", "yomix",
}
EXCHANGE_LABELS = {
    "binance", "coinbase", "kraken", "okx", "kucoin", "bybit", "gate.io",
    "huobi", "htx", "bitfinex", "gemini", "crypto.com", "bitstamp", "mexc",
    "bitget", "upbit", "bithumb", "poloniex", "lbank", "exchange",
}
BRIDGE_LABELS = {
    "bridge", "wormhole", "stargate", "synapse", "hop", "across", "celer",
    "multichain", "anyswap", "orbiter", "layerzero", "thorchain", "renbridge",
}
DRAINER_LABELS = {
    "drainer", "phishing", "fake_phishing", "scam", "angel drainer",
    "inferno drainer", "pink drainer", "monkey drainer", "venom drainer",
    "approval farm", "ice phishing",
}
ILLICIT_LABEL_TYPES = {
    "mixer", "tumbler", "darknet", "dark_market", "illicit", "scam", "hack",
    "phishing", "fraud", "ransomware", "terror", "terrorist", "sanctions",
    "exploit", "drainer", "ponzi", "rugpull", "theft",
}
TRUSTED_LABEL_TYPES = {
    "exchange", "cex", "dex", "defi", "institution", "custodian", "government",
    "regulator", "protocol", "nft_marketplace", "fund", "miner", "validator",
}
STABLECOINS = {"usdt", "usdc", "dai", "busd", "tusd", "frax", "usdp", "gusd", "pyusd", "fdusd"}

STRUCTURING_BAND = (8_000.0, 10_000.0)   # just-under-reporting-threshold band
DORMANCY_DAYS = 30
FEATURE_NAMES: List[str] = [
    "tx_count", "active_days", "tx_per_day", "recency_days", "burst_ratio",
    "hour_entropy", "acceleration", "dormancy_awakening",
    "total_in_usd", "total_out_usd", "out_in_ratio", "avg_tx_usd", "max_tx_usd",
    "round_amount_ratio", "structuring_ratio", "value_entropy", "stablecoin_ratio",
    "unique_counterparties", "fan_in", "fan_out", "fan_out_burst",
    "peel_chain_score", "mixer_proximity", "exchange_exposure", "bridge_exposure",
    "risky_counterparty_ratio", "fresh_counterparty_ratio", "dust_in_ratio",
    "poisoning_score", "drainer_proximity",
    "is_sanctioned", "scam_reports", "risk_score",
]

_now = lambda: datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────────────────────────────────────────────────────────────
# Storage
# ──────────────────────────────────────────────────────────────────────────────

def init_predictive_tables() -> None:
    with db.get_connection() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS predictive_models (
            name        TEXT PRIMARY KEY,
            weights_json TEXT NOT NULL,
            samples     INTEGER DEFAULT 0,
            positives   INTEGER DEFAULT 0,
            accuracy    REAL DEFAULT 0,
            engine      TEXT DEFAULT 'pure-python',
            trained_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS predictive_baselines (
            feature     TEXT PRIMARY KEY,
            median      REAL DEFAULT 0,
            mad         REAL DEFAULT 0,
            n           INTEGER DEFAULT 0,
            updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS predictive_predictions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            address     TEXT NOT NULL,
            chain       TEXT DEFAULT '',
            ptype       TEXT NOT NULL,
            probability REAL DEFAULT 0,
            level       TEXT DEFAULT '',
            horizon     TEXT DEFAULT '',
            result_json TEXT DEFAULT '{}',
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pred_addr ON predictive_predictions(address);
        CREATE TABLE IF NOT EXISTS predictive_features (
            address     TEXT NOT NULL,
            chain       TEXT DEFAULT '',
            features_json TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (address, chain)
        );
        """)


# ──────────────────────────────────────────────────────────────────────────────
# Data gathering
# ──────────────────────────────────────────────────────────────────────────────

def _norm(v: Any) -> str:
    s = str(v or "").strip()
    return s.lower() if s.startswith("0x") else s


def _parse_ts(ts: Any) -> float:
    if ts in (None, ""):
        return 0.0
    if isinstance(ts, (int, float)):
        v = float(ts)
        return v / 1000.0 if v > 4e12 else v
    s = str(ts).strip().replace("T", " ").replace("Z", "").split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    try:
        return float(str(ts))
    except (TypeError, ValueError):
        return 0.0


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def gather_address_edges(address: str, chain: str = "") -> List[Dict[str, Any]]:
    """Collect every edge CrypTX has ever stored touching this address
    (graph store investigations + graph evidence tables)."""
    addr = _norm(address)
    edges: List[Dict[str, Any]] = []
    seen: set = set()
    with db.get_connection() as con:
        try:
            rows = con.execute(
                """SELECT source, target, token, value, value_usd, timestamp, tx_hash, edge_type
                   FROM investigation_edges
                   WHERE lower(source)=? OR lower(target)=? LIMIT 4000""",
                (addr, addr),
            ).fetchall()
        except Exception:
            rows = []
        for r in rows:
            key = (r["tx_hash"], _norm(r["source"]), _norm(r["target"]), r["value"])
            if key in seen:
                continue
            seen.add(key)
            edges.append(dict(r))
        try:
            rows2 = con.execute(
                """SELECT source, target, token, value,
                          value AS value_usd, timestamp, tx_hash, '' AS edge_type
                   FROM graph_edges
                   WHERE lower(source)=? OR lower(target)=? LIMIT 4000""",
                (addr, addr),
            ).fetchall()
        except Exception:
            rows2 = []
        for r in rows2:
            key = (r["tx_hash"], _norm(r["source"]), _norm(r["target"]), r["value"])
            if key in seen:
                continue
            seen.add(key)
            edges.append(dict(r))
    return edges


def gather_labels(addresses: List[str]) -> Dict[str, Dict[str, Any]]:
    """label + type for a set of addresses from local labels, sanctions,
    graph node metadata and attributions."""
    out: Dict[str, Dict[str, Any]] = {}
    if not addresses:
        return out
    normed = [_norm(a) for a in addresses]
    with db.get_connection() as con:
        for batch_start in range(0, len(normed), 400):
            batch = normed[batch_start:batch_start + 400]
            ph = ",".join("?" * len(batch))
            for sql, kind in (
                (f"SELECT lower(address) a, label, category t FROM local_labels WHERE lower(address) IN ({ph})", "local"),
                (f"SELECT lower(address) a, 'sanctioned' label, 'sanctions' t FROM sanctions_addresses WHERE lower(address) IN ({ph})", "sanctions"),
                (f"SELECT lower(address) a, label, node_type t FROM investigation_nodes WHERE lower(address) IN ({ph})", "graph"),
            ):
                try:
                    for r in con.execute(sql, batch).fetchall():
                        a = r["a"]
                        rec = out.setdefault(a, {"label": "", "type": "", "sanctioned": False})
                        if r["label"] and not rec["label"]:
                            rec["label"] = str(r["label"])
                        if r["t"] and not rec["type"]:
                            rec["type"] = str(r["t"]).lower()
                        if kind == "sanctions":
                            rec["sanctioned"] = True
                except Exception:
                    continue
    return out


def _cached_intel(address: str) -> Dict[str, Any]:
    addr = _norm(address)
    with db.get_connection() as con:
        for table in ("address_cache_v2", "address_cache"):
            try:
                row = con.execute(
                    f"SELECT intel_json, risk_json FROM {table} WHERE lower(address)=?",
                    (addr,),
                ).fetchone()
            except Exception:
                row = None
            if row:
                try:
                    intel = json.loads(row["intel_json"] or "{}")
                    risk = json.loads(row["risk_json"] or "{}")
                    if isinstance(intel, dict):
                        intel.setdefault("_risk", risk)
                        return intel
                except Exception:
                    pass
    return {}


# ──────────────────────────────────────────────────────────────────────────────
# Feature extraction
# ──────────────────────────────────────────────────────────────────────────────

def _entropy(counts: List[int]) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    ent = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            ent -= p * math.log2(p)
    return ent


def _label_match(label: str, ltype: str, vocab: set) -> bool:
    text = f"{label} {ltype}".lower()
    return any(k in text for k in vocab)


def extract_features(
    address: str,
    chain: str = "",
    intel: Optional[Dict[str, Any]] = None,
    edges: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, float]:
    """Compute the full behavioral feature vector for an address."""
    addr = _norm(address)
    intel = intel or _cached_intel(addr)
    edges = edges if edges is not None else gather_address_edges(addr, chain)

    now_ts = _now().timestamp()
    f: Dict[str, float] = {k: 0.0 for k in FEATURE_NAMES}

    # ── edge-derived behavior ────────────────────────────────────────────────
    timestamps: List[float] = []
    in_usd = out_usd = 0.0
    in_counts: Dict[str, int] = defaultdict(int)
    out_counts: Dict[str, int] = defaultdict(int)
    out_events: List[Tuple[float, float]] = []     # (ts, usd)
    in_events: List[Tuple[float, float, str]] = [] # (ts, usd, source)
    values: List[float] = []
    hour_hist = [0] * 24
    round_hits = structuring_hits = stable_hits = dust_in = 0

    for e in edges:
        src, tgt = _norm(e.get("source")), _norm(e.get("target"))
        usd = _f(e.get("value_usd")) or _f(e.get("value"))
        ts = _parse_ts(e.get("timestamp"))
        token = str(e.get("token") or "").lower()
        if ts > 0:
            timestamps.append(ts)
            hour_hist[datetime.fromtimestamp(ts, tz=timezone.utc).hour] += 1
        if usd > 0:
            values.append(usd)
            if usd >= 100 and abs(usd - round(usd, -2)) < usd * 0.001:
                round_hits += 1
            if STRUCTURING_BAND[0] <= usd < STRUCTURING_BAND[1]:
                structuring_hits += 1
        if token in STABLECOINS:
            stable_hits += 1
        if tgt == addr:
            in_usd += usd
            in_counts[src] += 1
            in_events.append((ts, usd, src))
            if 0 < usd < 1.0:
                dust_in += 1
        elif src == addr:
            out_usd += usd
            out_counts[tgt] += 1
            out_events.append((ts, usd))

    n_tx = len(edges)
    f["tx_count"] = float(n_tx)
    f["total_in_usd"] = in_usd
    f["total_out_usd"] = out_usd
    f["out_in_ratio"] = out_usd / in_usd if in_usd > 0 else (1.0 if out_usd > 0 else 0.0)
    f["avg_tx_usd"] = statistics.fmean(values) if values else 0.0
    f["max_tx_usd"] = max(values) if values else 0.0
    f["round_amount_ratio"] = round_hits / n_tx if n_tx else 0.0
    f["structuring_ratio"] = structuring_hits / n_tx if n_tx else 0.0
    f["stablecoin_ratio"] = stable_hits / n_tx if n_tx else 0.0
    f["dust_in_ratio"] = dust_in / max(1, len(in_events))
    f["hour_entropy"] = _entropy(hour_hist)

    if values:
        buckets: Dict[int, int] = defaultdict(int)
        for v in values:
            buckets[int(math.log10(max(v, 1e-9)))] += 1
        f["value_entropy"] = _entropy(list(buckets.values()))

    if timestamps:
        timestamps.sort()
        span_days = max((timestamps[-1] - timestamps[0]) / 86400.0, 1 / 24)
        f["active_days"] = span_days
        f["tx_per_day"] = n_tx / span_days
        f["recency_days"] = max(0.0, (now_ts - timestamps[-1]) / 86400.0)
        # burst: max txs inside any rolling 1h window
        best = j = 0
        for i in range(len(timestamps)):
            while timestamps[i] - timestamps[j] > 3600:
                j += 1
            best = max(best, i - j + 1)
        f["burst_ratio"] = best / n_tx if n_tx else 0.0
        # acceleration: last-7d rate vs lifetime rate
        recent = sum(1 for t in timestamps if now_ts - t <= 7 * 86400)
        lifetime_rate = n_tx / span_days
        f["acceleration"] = (recent / 7.0) / lifetime_rate if lifetime_rate > 0 else 0.0
        # dormancy awakening: >30d silence then recent activity
        gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
        if gaps and max(gaps) > DORMANCY_DAYS * 86400 and f["recency_days"] < 7:
            f["dormancy_awakening"] = 1.0

    counterparties = set(in_counts) | set(out_counts)
    counterparties.discard(addr)
    f["unique_counterparties"] = float(len(counterparties))
    f["fan_in"] = float(len(in_counts))
    f["fan_out"] = float(len(out_counts))

    # fan-out burst: many distinct destinations within any 24h window
    if out_events:
        out_sorted = sorted(out_events)
        j = 0
        best_fo = 0
        for i in range(len(out_sorted)):
            while out_sorted[i][0] - out_sorted[j][0] > 86400:
                j += 1
            best_fo = max(best_fo, i - j + 1)
        f["fan_out_burst"] = best_fo / max(1, len(out_events))

    # peel-chain: consecutive outgoing values decreasing ~5-30% steps
    if len(out_events) >= 3:
        seq = [v for _, v in sorted(out_events) if v > 0]
        peels = sum(
            1 for a, b in zip(seq, seq[1:])
            if a > 0 and 0.55 <= b / a <= 0.98
        )
        f["peel_chain_score"] = peels / (len(seq) - 1) if len(seq) > 1 else 0.0

    # ── label-derived exposure ───────────────────────────────────────────────
    labels = gather_labels(list(counterparties)[:800])
    risky = fresh = mixer_touch = exch_touch = bridge_touch = drainer_touch = 0
    poisoning = 0
    for cp in counterparties:
        rec = labels.get(cp, {})
        lbl, lt = rec.get("label", ""), rec.get("type", "")
        if rec.get("sanctioned") or (lt in ILLICIT_LABEL_TYPES) or _label_match(lbl, lt, DRAINER_LABELS):
            risky += 1
        if _label_match(lbl, lt, MIXER_LABELS):
            mixer_touch += 1
        if _label_match(lbl, lt, EXCHANGE_LABELS):
            exch_touch += 1
        if _label_match(lbl, lt, BRIDGE_LABELS):
            bridge_touch += 1
        if _label_match(lbl, lt, DRAINER_LABELS):
            drainer_touch += 1
        if not lbl and not lt:
            fresh += 1
        # address-poisoning lookalike: same 4-char prefix AND suffix as subject
        if len(cp) > 12 and len(addr) > 12 and cp != addr:
            if cp[:6] == addr[:6] and cp[-4:] == addr[-4:]:
                poisoning += 1

    ncp = max(1, len(counterparties))
    f["risky_counterparty_ratio"] = risky / ncp
    f["fresh_counterparty_ratio"] = fresh / ncp
    f["mixer_proximity"] = min(1.0, mixer_touch / 2.0)
    f["exchange_exposure"] = exch_touch / ncp
    f["bridge_exposure"] = bridge_touch / ncp
    f["drainer_proximity"] = min(1.0, drainer_touch / 2.0)
    f["poisoning_score"] = min(1.0, poisoning / 2.0)

    # ── intel-derived ────────────────────────────────────────────────────────
    risk = intel.get("_risk") or intel.get("risk") or {}
    f["risk_score"] = _f(risk.get("score") or risk.get("risk_score"))
    sanc = intel.get("sanctions") or {}
    if (isinstance(sanc, dict) and (sanc.get("sanctioned") or sanc.get("is_sanctioned"))) or intel.get("is_sanctioned"):
        f["is_sanctioned"] = 1.0
    scam = intel.get("scamsearch") or intel.get("scam_reports") or {}
    if isinstance(scam, dict):
        f["scam_reports"] = _f(scam.get("total") or scam.get("count") or len(scam.get("reports", []) or []))
    elif isinstance(scam, list):
        f["scam_reports"] = float(len(scam))

    # persist for baseline building
    try:
        init_predictive_tables()
        with db.get_connection() as con:
            con.execute(
                """INSERT INTO predictive_features(address, chain, features_json, updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(address, chain) DO UPDATE SET
                     features_json=excluded.features_json, updated_at=excluded.updated_at""",
                (addr, chain or "", json.dumps(f), _utcnow_iso()),
            )
    except Exception:
        pass
    return f


# ──────────────────────────────────────────────────────────────────────────────
# Layer 2 — statistical anomaly detection (population baseline)
# ──────────────────────────────────────────────────────────────────────────────

_ANOMALY_FEATURES = [
    "tx_per_day", "burst_ratio", "acceleration", "fan_out", "fan_in",
    "out_in_ratio", "round_amount_ratio", "structuring_ratio",
    "fresh_counterparty_ratio", "peel_chain_score", "fan_out_burst",
    "stablecoin_ratio", "avg_tx_usd",
]


def rebuild_baselines() -> Dict[str, Any]:
    """Recompute population median/MAD for anomaly scoring from every stored
    feature vector."""
    init_predictive_tables()
    cols: Dict[str, List[float]] = defaultdict(list)
    with db.get_connection() as con:
        rows = con.execute("SELECT features_json FROM predictive_features LIMIT 20000").fetchall()
        for r in rows:
            try:
                feats = json.loads(r["features_json"])
            except Exception:
                continue
            for k in _ANOMALY_FEATURES:
                v = _f(feats.get(k))
                if math.isfinite(v):
                    cols[k].append(v)
        now = _utcnow_iso()
        n_rows = len(rows)
        for k, vals in cols.items():
            if len(vals) < 5:
                continue
            med = statistics.median(vals)
            mad = statistics.median([abs(v - med) for v in vals]) or 1e-9
            con.execute(
                """INSERT INTO predictive_baselines(feature, median, mad, n, updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(feature) DO UPDATE SET median=excluded.median,
                     mad=excluded.mad, n=excluded.n, updated_at=excluded.updated_at""",
                (k, med, mad, len(vals), now),
            )
    return {"population": n_rows, "features": len(cols)}


def _load_baselines() -> Dict[str, Tuple[float, float, int]]:
    out: Dict[str, Tuple[float, float, int]] = {}
    try:
        with db.get_connection() as con:
            for r in con.execute("SELECT feature, median, mad, n FROM predictive_baselines").fetchall():
                out[r["feature"]] = (r["median"], r["mad"], r["n"])
    except Exception:
        pass
    return out


def anomaly_report(features: Dict[str, float]) -> Dict[str, Any]:
    """Robust z-scores vs. population. Returns overall anomaly 0-1 + outliers."""
    base = _load_baselines()
    if not base:
        rebuild_baselines()
        base = _load_baselines()
    zscores: Dict[str, float] = {}
    for k in _ANOMALY_FEATURES:
        if k in base:
            med, mad, _ = base[k]
            z = 0.6745 * (features.get(k, 0.0) - med) / mad  # robust z
            zscores[k] = round(z, 2)
    outliers = sorted(
        [(k, z) for k, z in zscores.items() if z > 2.5],
        key=lambda kv: -kv[1],
    )
    top = sorted((abs(z) for z in zscores.values()), reverse=True)[:5]
    score = min(1.0, (statistics.fmean(top) / 6.0)) if top else 0.0
    return {
        "anomaly_score": round(score, 3),
        "population_n": max((n for _, _, n in base.values()), default=0),
        "z_scores": zscores,
        "outliers": [
            {"feature": k, "z": z, "note": f"{k} is {z:.1f} robust-σ above the population median"}
            for k, z in outliers[:6]
        ],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Layer 3 — machine learning (pure-Python logistic regression, sklearn optional)
# ──────────────────────────────────────────────────────────────────────────────

_ML_FEATURES = FEATURE_NAMES  # full vector


def _standardize(X: List[List[float]]) -> Tuple[List[List[float]], List[float], List[float]]:
    ncol = len(X[0])
    means = [statistics.fmean([row[j] for row in X]) for j in range(ncol)]
    stds = []
    for j in range(ncol):
        col = [row[j] for row in X]
        s = statistics.pstdev(col)
        stds.append(s if s > 1e-9 else 1.0)
    Xs = [[(row[j] - means[j]) / stds[j] for j in range(ncol)] for row in X]
    return Xs, means, stds


def _train_pure_logreg(X: List[List[float]], y: List[int],
                       epochs: int = 300, lr: float = 0.1, l2: float = 0.01
                       ) -> Tuple[List[float], float]:
    """Mini-batch SGD logistic regression. Returns (weights incl. bias, acc)."""
    n, m = len(X), len(X[0])
    w = [0.0] * (m + 1)  # last = bias
    idx = list(range(n))
    rng = random.Random(42)
    for _ in range(epochs):
        rng.shuffle(idx)
        for i in idx:
            z = w[m] + sum(w[j] * X[i][j] for j in range(m))
            z = max(-30.0, min(30.0, z))
            p = 1.0 / (1.0 + math.exp(-z))
            g = p - y[i]
            for j in range(m):
                w[j] -= lr * (g * X[i][j] + l2 * w[j] / n)
            w[m] -= lr * g
    correct = 0
    for i in range(n):
        z = w[m] + sum(w[j] * X[i][j] for j in range(m))
        correct += int((z > 0) == bool(y[i]))
    return w, correct / n if n else 0.0


def _collect_training_set() -> Tuple[List[List[float]], List[int], int]:
    """Build labeled training data from historic artifacts:
    positives = sanctioned / illicit-labeled / scam-network addresses that have
    stored feature vectors; negatives = trusted-entity labels."""
    pos_addrs: set = set()
    neg_addrs: set = set()
    with db.get_connection() as con:
        try:
            for r in con.execute("SELECT lower(address) a FROM sanctions_addresses LIMIT 5000"):
                pos_addrs.add(r["a"])
        except Exception:
            pass
        try:
            for r in con.execute("SELECT lower(address) a, category t FROM local_labels LIMIT 20000"):
                t = str(r["t"] or "").lower()
                if t in ILLICIT_LABEL_TYPES:
                    pos_addrs.add(r["a"])
                elif t in TRUSTED_LABEL_TYPES:
                    neg_addrs.add(r["a"])
        except Exception:
            pass
        try:
            for r in con.execute("SELECT lower(address) a, node_type t FROM investigation_nodes LIMIT 40000"):
                t = str(r["t"] or "").lower()
                if t in ILLICIT_LABEL_TYPES:
                    pos_addrs.add(r["a"])
                elif t in TRUSTED_LABEL_TYPES:
                    neg_addrs.add(r["a"])
        except Exception:
            pass
        X: List[List[float]] = []
        y: List[int] = []
        rows = con.execute("SELECT address, features_json FROM predictive_features LIMIT 20000").fetchall()
        for r in rows:
            a = _norm(r["address"])
            label = 1 if a in pos_addrs else (0 if a in neg_addrs else -1)
            if label < 0:
                continue
            try:
                feats = json.loads(r["features_json"])
            except Exception:
                continue
            X.append([_f(feats.get(k)) for k in _ML_FEATURES])
            y.append(label)
    return X, y, sum(y)


def train_models(force: bool = False) -> Dict[str, Any]:
    """Train (or retrain) the illicit-behavior classifier from historic data."""
    init_predictive_tables()
    X, y, positives = _collect_training_set()
    n = len(X)
    if n < 20 or positives < 5 or positives == n:
        return {
            "trained": False,
            "samples": n,
            "positives": positives,
            "reason": "insufficient labeled history — engine will run in "
                      "heuristic+anomaly mode (add labels / run investigations to unlock ML)",
        }
    engine = "pure-python"
    if _HAS_SKLEARN:
        try:
            clf = _SkLogReg(max_iter=2000, class_weight="balanced")
            clf.fit(X, y)
            acc = float(clf.score(X, y))
            weights = list(map(float, clf.coef_[0])) + [float(clf.intercept_[0])]
            means = [0.0] * len(_ML_FEATURES)
            stds = [1.0] * len(_ML_FEATURES)
            engine = "sklearn"
        except Exception:
            Xs, means, stds = _standardize(X)
            weights, acc = _train_pure_logreg(Xs, y)
    else:
        Xs, means, stds = _standardize(X)
        weights, acc = _train_pure_logreg(Xs, y)
    payload = {"weights": weights, "means": means, "stds": stds, "features": _ML_FEATURES}
    with db.get_connection() as con:
        con.execute(
            """INSERT INTO predictive_models(name, weights_json, samples, positives, accuracy, engine, trained_at)
               VALUES('illicit_behavior',?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET weights_json=excluded.weights_json,
                 samples=excluded.samples, positives=excluded.positives,
                 accuracy=excluded.accuracy, engine=excluded.engine, trained_at=excluded.trained_at""",
            (json.dumps(payload), n, positives, acc, engine, _utcnow_iso()),
        )
    rebuild_baselines()
    return {"trained": True, "samples": n, "positives": positives,
            "accuracy": round(acc, 3), "engine": engine}


def _ml_probability(features: Dict[str, float]) -> Optional[float]:
    try:
        with db.get_connection() as con:
            row = con.execute(
                "SELECT weights_json FROM predictive_models WHERE name='illicit_behavior'"
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["weights_json"])
        w = payload["weights"]
        means, stds = payload["means"], payload["stds"]
        names = payload["features"]
        z = w[-1]
        for j, k in enumerate(names):
            z += w[j] * ((_f(features.get(k)) - means[j]) / (stds[j] or 1.0))
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))
    except Exception:
        return None


def model_status() -> Dict[str, Any]:
    init_predictive_tables()
    out: Dict[str, Any] = {"sklearn_available": _HAS_SKLEARN, "models": [],
                           "baseline_features": 0, "feature_vectors": 0}
    try:
        with db.get_connection() as con:
            for r in con.execute("SELECT name, samples, positives, accuracy, engine, trained_at FROM predictive_models"):
                out["models"].append(dict(r))
            out["baseline_features"] = con.execute("SELECT COUNT(*) c FROM predictive_baselines").fetchone()["c"]
            out["feature_vectors"] = con.execute("SELECT COUNT(*) c FROM predictive_features").fetchone()["c"]
            out["recent_predictions"] = con.execute("SELECT COUNT(*) c FROM predictive_predictions").fetchone()["c"]
    except Exception:
        pass
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Blending & explainability helpers
# ──────────────────────────────────────────────────────────────────────────────

def _level(p: float) -> str:
    if p >= 0.85: return "CRITICAL"
    if p >= 0.65: return "HIGH"
    if p >= 0.45: return "ELEVATED"
    if p >= 0.25: return "GUARDED"
    return "LOW"


def _blend(heuristic: float, anomaly: float, ml: Optional[float]) -> Tuple[float, float, Dict[str, float]]:
    """Blend the three layers. Returns (probability, confidence, weights used)."""
    if ml is not None:
        wts = {"precursor_patterns": 0.45, "anomaly": 0.2, "ml_model": 0.35}
        p = wts["precursor_patterns"] * heuristic + wts["anomaly"] * anomaly + wts["ml_model"] * ml
        conf = 0.85
    else:
        wts = {"precursor_patterns": 0.7, "anomaly": 0.3, "ml_model": 0.0}
        p = wts["precursor_patterns"] * heuristic + wts["anomaly"] * anomaly
        conf = 0.6
    return min(1.0, max(0.0, p)), conf, wts


def _log_prediction(address: str, chain: str, ptype: str, result: Dict[str, Any]) -> None:
    try:
        with db.get_connection() as con:
            con.execute(
                """INSERT INTO predictive_predictions(address, chain, ptype, probability, level, horizon, result_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (_norm(address), chain, ptype, result.get("probability", 0),
                 result.get("level", ""), result.get("horizon", ""),
                 json.dumps({k: v for k, v in result.items() if k != "features"}),
                 _utcnow_iso()),
            )
    except Exception:
        pass


def _ev(signals: List[Tuple[float, str, str]]) -> List[Dict[str, Any]]:
    """signals: (weight_contribution, severity, text) → sorted evidence list."""
    return [
        {"weight": round(w, 3), "severity": sev, "finding": txt}
        for w, sev, txt in sorted(signals, key=lambda s: -s[0]) if w > 0
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Predictor 1 — imminent laundering / cash-out staging
# ──────────────────────────────────────────────────────────────────────────────

def predict_laundering(address: str, chain: str = "",
                       intel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    feats = extract_features(address, chain, intel)
    sig: List[Tuple[float, str, str]] = []
    h = 0.0

    def add(w: float, sev: str, txt: str, cond: bool = True):
        nonlocal h
        if cond and w > 0:
            h += w
            sig.append((w, sev, txt))

    add(min(0.25, feats["mixer_proximity"] * 0.25), "critical",
        "Direct or 1-hop exposure to mixing services — classic pre-laundering staging",
        feats["mixer_proximity"] > 0)
    add(min(0.2, feats["fan_out_burst"] * 0.2), "high",
        f"Rapid fan-out burst: funds split across many destinations within 24h "
        f"({int(feats['fan_out'])} outbound counterparties)",
        feats["fan_out_burst"] > 0.4 and feats["fan_out"] >= 5)
    add(min(0.18, feats["peel_chain_score"] * 0.18), "high",
        "Peel-chain signature: successive decreasing transfers consistent with layering",
        feats["peel_chain_score"] > 0.3)
    add(0.12, "high",
        f"Structuring pattern: {feats['structuring_ratio']*100:.0f}% of transfers sit "
        "just below the $10k reporting threshold",
        feats["structuring_ratio"] > 0.15)
    add(min(0.12, feats["stablecoin_ratio"] * 0.15), "medium",
        "Heavy rotation into stablecoins — typical value-preservation step before off-ramp",
        feats["stablecoin_ratio"] > 0.4)
    add(0.1, "medium",
        "Exchange deposit exposure detected — potential cash-out endpoints already in graph",
        feats["exchange_exposure"] > 0.1)
    add(0.08, "medium",
        f"Bridge exposure ({feats['bridge_exposure']*100:.0f}% of counterparties) — "
        "cross-chain hop preparation",
        feats["bridge_exposure"] > 0.05)
    add(0.1, "high",
        "Dormant wallet awakened in the last 7 days after 30+ days of silence — "
        "frequent precursor to fund movement",
        feats["dormancy_awakening"] > 0)
    add(min(0.1, (feats["acceleration"] - 1.5) * 0.05), "medium",
        f"Activity acceleration: recent 7-day tx rate is {feats['acceleration']:.1f}× lifetime average",
        feats["acceleration"] > 1.5)
    add(0.08, "medium",
        f"{feats['fresh_counterparty_ratio']*100:.0f}% of counterparties are fresh/unlabeled "
        "wallets — consistent with disposable intermediary layer",
        feats["fresh_counterparty_ratio"] > 0.6 and feats["unique_counterparties"] >= 5)
    add(0.07, "low",
        f"High round-amount ratio ({feats['round_amount_ratio']*100:.0f}%) — manual layering indicator",
        feats["round_amount_ratio"] > 0.3)

    heur = min(1.0, h)
    anom = anomaly_report(feats)
    ml = _ml_probability(feats)
    p, conf, wts = _blend(heur, anom["anomaly_score"], ml)

    # time-horizon: velocity-driven
    if feats["acceleration"] > 2 or feats["fan_out_burst"] > 0.5:
        horizon = "24-72 hours"
    elif feats["dormancy_awakening"] or feats["tx_per_day"] > 5:
        horizon = "3-7 days"
    else:
        horizon = "7-30 days"

    result = {
        "type": "laundering",
        "address": address, "chain": chain,
        "probability": round(p, 3), "level": _level(p), "confidence": conf,
        "horizon": horizon,
        "layer_scores": {"precursor_patterns": round(heur, 3),
                         "anomaly": anom["anomaly_score"],
                         "ml_model": round(ml, 3) if ml is not None else None},
        "blend_weights": wts,
        "evidence": _ev(sig),
        "anomaly": anom,
        "recommended_actions": _laundering_actions(p, feats),
        "features": feats,
    }
    _log_prediction(address, chain, "laundering", result)
    return result


def _laundering_actions(p: float, f: Dict[str, float]) -> List[str]:
    acts: List[str] = []
    if p >= 0.65:
        acts.append("Place address under real-time Wallet Monitor with high-priority alerting")
        acts.append("Pre-draft exchange freeze requests for the identified deposit endpoints (Freeze Desk)")
    if f["mixer_proximity"] > 0:
        acts.append("Run Demix Lab on the mixer-adjacent path to prepare de-mixing evidence")
    if f["exchange_exposure"] > 0.1:
        acts.append("Identify KYC'd exchange deposit addresses in the path and prepare legal process")
    if f["bridge_exposure"] > 0.05:
        acts.append("Set cross-chain watch: monitor destination chains for arrival of bridged funds")
    acts.append("Snapshot the current graph as evidence before funds move (Evidence Vault)")
    return acts


# ──────────────────────────────────────────────────────────────────────────────
# Predictor 2 — scam / rug-pull early warning
# ──────────────────────────────────────────────────────────────────────────────

def predict_rugpull(address: str, chain: str = "",
                    intel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    intel = intel or _cached_intel(address)
    feats = extract_features(address, chain, intel)
    sig: List[Tuple[float, str, str]] = []
    h = 0.0

    def add(w: float, sev: str, txt: str, cond: bool = True):
        nonlocal h
        if cond and w > 0:
            h += w
            sig.append((w, sev, txt))

    # deployer/operator funding hygiene
    add(min(0.3, feats["mixer_proximity"] * 0.3), "critical",
        "Wallet funded via / adjacent to mixing services — anonymised operator funding is the "
        "#1 rug-pull deployer signature",
        feats["mixer_proximity"] > 0)
    add(0.15, "high",
        f"Very young operational history ({feats['active_days']:.0f} active days) with "
        "significant value flow — burner-deployer profile",
        0 < feats["active_days"] < 14 and feats["total_in_usd"] > 5_000)
    add(0.15, "high",
        "Prior scam reports already filed against this address",
        feats["scam_reports"] > 0)
    add(min(0.15, feats["drainer_proximity"] * 0.15), "critical",
        "Interaction with known drainer/phishing infrastructure",
        feats["drainer_proximity"] > 0)
    add(0.12, "medium",
        f"Inflow heavily concentrated then out-ratio {feats['out_in_ratio']:.1f} — "
        "collect-then-extract cash pattern",
        feats["out_in_ratio"] > 0.8 and feats["fan_in"] >= 10)
    add(0.1, "medium",
        f"Fan-in from {int(feats['fan_in'])} wallets (victim-deposit funnel shape)",
        feats["fan_in"] >= 20)
    add(0.08, "medium",
        "Mostly fresh, unlabeled counterparties — no organic ecosystem footprint",
        feats["fresh_counterparty_ratio"] > 0.7 and feats["unique_counterparties"] >= 10)

    # contract-level flags if present in intel
    contract = intel.get("contract") or intel.get("contract_forensics") or {}
    if isinstance(contract, dict):
        flags = [str(x).lower() for x in (contract.get("flags") or contract.get("risks") or [])]
        joined = " ".join(flags)
        add(0.2, "critical", "Contract has owner-only liquidity/withdraw or hidden-mint capability",
            any(k in joined for k in ("mint", "owner", "withdraw", "honeypot", "blacklist", "pause")))
        add(0.12, "high", "Contract unverified — source code hidden from investors",
            bool(contract.get("unverified") or "unverified" in joined))

    heur = min(1.0, h)
    anom = anomaly_report(feats)
    ml = _ml_probability(feats)
    p, conf, wts = _blend(heur, anom["anomaly_score"], ml)

    horizon = "48 hours - 14 days" if feats["out_in_ratio"] < 0.5 and feats["fan_in"] >= 10 \
        else ("imminent / may be underway" if feats["out_in_ratio"] >= 0.8 else "14-45 days")

    result = {
        "type": "rugpull",
        "address": address, "chain": chain,
        "probability": round(p, 3), "level": _level(p), "confidence": conf,
        "horizon": horizon,
        "layer_scores": {"precursor_patterns": round(heur, 3),
                         "anomaly": anom["anomaly_score"],
                         "ml_model": round(ml, 3) if ml is not None else None},
        "blend_weights": wts,
        "evidence": _ev(sig),
        "anomaly": anom,
        "recommended_actions": [
            "Run Contract Forensics on associated token/contract for honeypot & hidden-mint checks",
            "Map the victim-deposit funnel in Nexus Graph and preserve as evidence",
            "Check liquidity-pool lock status and deployer's other contracts (Scam Atlas)",
            "If probability HIGH+: file proactive alert to exchange compliance via Freeze Desk",
        ],
        "features": feats,
    }
    _log_prediction(address, chain, "rugpull", result)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Predictor 3 — risk trajectory forecast
# ──────────────────────────────────────────────────────────────────────────────

def predict_trajectory(address: str, chain: str = "",
                       intel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    feats = extract_features(address, chain, intel)
    anom = anomaly_report(feats)
    ml = _ml_probability(feats)

    # escalation drivers
    sig: List[Tuple[float, str, str]] = []
    h = 0.0

    def add(w: float, sev: str, txt: str, cond: bool = True):
        nonlocal h
        if cond and w > 0:
            h += w
            sig.append((w, sev, txt))

    base_risk = feats["risk_score"] / 100.0
    add(base_risk * 0.3, "high" if base_risk > 0.6 else "medium",
        f"Current composite risk score {feats['risk_score']:.0f}/100 forms the trajectory baseline",
        base_risk > 0)
    add(min(0.2, feats["risky_counterparty_ratio"] * 0.5), "high",
        f"{feats['risky_counterparty_ratio']*100:.0f}% of counterparties are known-illicit — "
        "risk contagion pressure",
        feats["risky_counterparty_ratio"] > 0.05)
    add(min(0.15, (feats["acceleration"] - 1.0) * 0.075), "medium",
        f"Behavioral acceleration {feats['acceleration']:.1f}× — activity trending up",
        feats["acceleration"] > 1.0)
    add(0.1, "medium", "Recent dormancy awakening — regime change in wallet behavior",
        feats["dormancy_awakening"] > 0)
    add(min(0.15, feats["mixer_proximity"] * 0.15 + feats["drainer_proximity"] * 0.15), "critical",
        "Proximity to mixer/drainer infrastructure",
        feats["mixer_proximity"] > 0 or feats["drainer_proximity"] > 0)
    add(0.1, "medium", "Anomalous behavior vs. population baseline",
        anom["anomaly_score"] > 0.4)

    heur = min(1.0, h)
    p, conf, wts = _blend(heur, anom["anomaly_score"], ml)

    # horizon-specific probabilities: escalation decays toward baseline
    p7 = round(min(1.0, p * (0.55 + 0.45 * min(1.0, feats["acceleration"] / 3.0))), 3)
    p30 = round(p, 3)
    p90 = round(min(1.0, p * 1.15), 3)

    trend = "escalating" if feats["acceleration"] > 1.3 or feats["dormancy_awakening"] else \
            ("cooling" if feats["recency_days"] > 30 else "stable")

    result = {
        "type": "trajectory",
        "address": address, "chain": chain,
        "probability": p30, "level": _level(p30), "confidence": conf,
        "horizon": "30 days (see horizons for 7/90)",
        "trend": trend,
        "horizons": {"7d": p7, "30d": p30, "90d": p90},
        "layer_scores": {"precursor_patterns": round(heur, 3),
                         "anomaly": anom["anomaly_score"],
                         "ml_model": round(ml, 3) if ml is not None else None},
        "blend_weights": wts,
        "evidence": _ev(sig),
        "anomaly": anom,
        "recommended_actions": [
            "Add to Wallet Monitor with alert rules tuned to the escalation drivers above",
            "Re-run trajectory weekly — trend direction matters more than the point estimate",
            "If 7d probability exceeds 0.65, escalate to active investigation and snapshot evidence",
        ],
        "features": feats,
    }
    _log_prediction(address, chain, "trajectory", result)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Predictor 4 — victim / target prediction
# ──────────────────────────────────────────────────────────────────────────────

def predict_victim(address: str, chain: str = "",
                   intel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    intel = intel or _cached_intel(address)
    feats = extract_features(address, chain, intel)
    sig: List[Tuple[float, str, str]] = []
    h = 0.0

    def add(w: float, sev: str, txt: str, cond: bool = True):
        nonlocal h
        if cond and w > 0:
            h += w
            sig.append((w, sev, txt))

    add(min(0.3, feats["poisoning_score"] * 0.3), "critical",
        "Address-poisoning attack detected: lookalike addresses (matching prefix+suffix) are "
        "inserting themselves into this wallet's history to hijack a future copy-paste",
        feats["poisoning_score"] > 0)
    add(min(0.25, feats["dust_in_ratio"] * 0.5), "high",
        f"Dusting campaign: {feats['dust_in_ratio']*100:.0f}% of inbound transfers are sub-$1 dust — "
        "tracking/bait transactions commonly precede targeted attacks",
        feats["dust_in_ratio"] > 0.15)
    add(min(0.25, feats["drainer_proximity"] * 0.25), "critical",
        "Direct interaction with known drainer/phishing infrastructure — token approvals may "
        "already be compromised",
        feats["drainer_proximity"] > 0)

    # approval risk from intel
    tokens = intel.get("tokens") or intel.get("token_holdings") or []
    approvals = intel.get("approvals") or []
    if isinstance(approvals, list) and approvals:
        risky_apps = [a for a in approvals
                      if isinstance(a, dict) and _label_match(str(a.get("spender_label", "")),
                                                              str(a.get("risk", "")), DRAINER_LABELS)]
        add(0.25, "critical",
            f"{len(risky_apps)} active token approval(s) granted to flagged contracts",
            bool(risky_apps))
    hold_usd = 0.0
    if isinstance(tokens, list):
        hold_usd = sum(_f(t.get("usd_value") or t.get("value_usd")) for t in tokens if isinstance(t, dict))
    add(0.12, "medium",
        f"High-value holdings (${hold_usd:,.0f}) make this wallet an attractive target",
        hold_usd > 50_000)
    add(0.1, "medium",
        "Wallet is publicly labeled/attributed — visibility raises targeting likelihood",
        bool(intel.get("arkham") or intel.get("labels")))
    add(0.08, "low",
        "Inbound from many fresh wallets — possible recon/bait probing",
        feats["fresh_counterparty_ratio"] > 0.6 and feats["fan_in"] >= 10)

    heur = min(1.0, h)
    anom = anomaly_report(feats)
    ml = _ml_probability(feats)
    # victim prediction leans on precursors; ML models illicit behavior, so downweight it
    p = min(1.0, 0.8 * heur + 0.2 * anom["anomaly_score"])
    conf = 0.65 if ml is None else 0.7
    wts = {"precursor_patterns": 0.8, "anomaly": 0.2, "ml_model": 0.0}

    horizon = "24-72 hours" if feats["poisoning_score"] > 0 or feats["drainer_proximity"] > 0 \
        else "7-30 days"

    result = {
        "type": "victim",
        "address": address, "chain": chain,
        "probability": round(p, 3), "level": _level(p), "confidence": conf,
        "horizon": horizon,
        "layer_scores": {"precursor_patterns": round(heur, 3),
                         "anomaly": anom["anomaly_score"],
                         "ml_model": round(ml, 3) if ml is not None else None},
        "blend_weights": wts,
        "evidence": _ev(sig),
        "anomaly": anom,
        "recommended_actions": [
            "Advise owner to revoke risky token approvals immediately (revoke.cash / Etherscan)",
            "Warn against copy-pasting addresses from transaction history (poisoning defense)",
            "Move high-value holdings to a fresh cold wallet if drainer interaction is confirmed",
            "Add to Wallet Monitor to catch the drain attempt in real time",
        ],
        "features": feats,
    }
    _log_prediction(address, chain, "victim", result)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────────────

_PREDICTORS = {
    "laundering": predict_laundering,
    "rugpull": predict_rugpull,
    "trajectory": predict_trajectory,
    "victim": predict_victim,
}


def predict(ptype: str, address: str, chain: str = "",
            intel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fn = _PREDICTORS.get(ptype)
    if not fn:
        raise ValueError(f"unknown prediction type '{ptype}' — expected one of {sorted(_PREDICTORS)}")
    return fn(address, chain, intel)


def predict_all(address: str, chain: str = "",
                intel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run every predictor and produce a unified threat outlook."""
    intel = intel or _cached_intel(address)
    results = {k: fn(address, chain, intel) for k, fn in _PREDICTORS.items()}
    top = max(results.values(), key=lambda r: r["probability"])
    composite = round(
        max(r["probability"] for r in results.values()) * 0.6
        + statistics.fmean(r["probability"] for r in results.values()) * 0.4, 3)
    return {
        "address": address, "chain": chain,
        "composite_threat": composite,
        "composite_level": _level(composite),
        "primary_threat": top["type"],
        "primary_horizon": top["horizon"],
        "predictions": results,
        "model": model_status(),
        "generated_at": _utcnow_iso(),
        "methodology": "Hybrid 3-layer engine: deterministic precursor patterns + "
                       "population anomaly statistics + logistic ML (when trained). "
                       "All evidence items are independently verifiable on-chain.",
    }


def prediction_history(address: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    init_predictive_tables()
    with db.get_connection() as con:
        if address:
            rows = con.execute(
                """SELECT address, chain, ptype, probability, level, horizon, created_at
                   FROM predictive_predictions WHERE lower(address)=? ORDER BY id DESC LIMIT ?""",
                (_norm(address), limit)).fetchall()
        else:
            rows = con.execute(
                """SELECT address, chain, ptype, probability, level, horizon, created_at
                   FROM predictive_predictions ORDER BY id DESC LIMIT ?""",
                (limit,)).fetchall()
    return [dict(r) for r in rows]
