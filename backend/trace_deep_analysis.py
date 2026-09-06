"""
Deep Analysis Orchestrator for the Fund Tracer.

This module turns the (already excellent but disconnected) analysis engines into
a single coherent "deep analysis" pass over a traced fund-flow graph:

  1. Run the live multi-hop trace (holistic_trace_engine.trace).
  2. Enrich every node from edge data (balance, tx_count, first/last seen,
     risk labels) — closing the placeholder-zeros gap in the graph model.
  3. Fan out to the FIVE existing engines, reusing their logic verbatim:
       - forensic_engine.analyze_forensics   (motifs, role, taint, temporal)
       - cashout_detector.detect_cashout     (off-ramp indicators)
       - crosschain_engine.trace_crosschain  (real bridge-in<->bridge-out stitch)
       - clustering_engine.analyze_clusters  (common-control wallet groups)
       - risk_engine.compute_risk_score      (composite 0-100 per node)
  4. Run THREE new algorithms that close genuine gaps no engine covers:
       - detect_peel_chain        (multi-output UTXO peel walk)
       - detect_layering_sequence (bridge->mixer->swap service-hop chains)
       - dwell_time_analysis      (rapid forward / no dwell time)
  5. Merge every finding into the already-plumbed result["patterns"] slot and
     attach a structured result["analysis"] block (clusters, crosschain paths,
     cashout destination, dwell times).

Design rules:
  - Every external engine call is wrapped so one failure never aborts the trace.
  - No reimplementation of detection logic — orchestration only.
  - Output is backward-compatible: callers that ignore ["analysis"] and
    ["patterns"] see the same shape as a plain holistic trace.

This produces investigative leads, not proof. Bridge attributions and
cross-chain links are probabilistic and must be corroborated.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any, Optional

import holistic_trace_engine as hte


# ---------------------------------------------------------------------------
# Edge / node normalization for the downstream engines
# ---------------------------------------------------------------------------
def _to_engine_nodes(holistic_nodes: list[dict]) -> list[dict]:
    """The analysis engines expect nodes keyed by `id` with a few standard
    fields. We pass the holistic TraceNode dicts through with light shaping so
    each engine's own lookup (`{n['id']: n for n in nodes}`) works unchanged."""
    out = []
    for n in holistic_nodes:
        addr = n.get("address", "")
        chain = n.get("chain", "")
        # The holistic engine's node id is "{chain}:{address}"; keep it as-is
        # so edges (which use the same id) resolve correctly.
        out.append({
            "id": n.get("id") or f"{chain}:{addr}",
            "address": addr,
            "chain": chain,
            "label": n.get("label") or n.get("vasp") or n.get("type") or "",
            "role": n.get("type", "unknown"),
            "risk_score": int(n.get("risk", 0) or 0),
            "hop": int(n.get("hop", 0) or 0),
            "type": n.get("type", "unknown"),
            "sanctioned": bool(n.get("sanctioned")),
            "vasp": n.get("vasp"),
        })
    return out


def _epoch_to_iso(ts) -> str:
    """Convert an epoch int/float/str to an ISO 8601 string for engines that
    parse time via datetime.strptime (crosschain_engine, clustering_engine,
    forensic_engine). Returns '' for falsy/invalid input."""
    try:
        n = int(ts)
        if n <= 0:
            return ""
        # Use UTC — these engines normalize to timezone-aware UTC timestamps.
        from datetime import datetime, timezone
        return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError):
        return ""


def _to_engine_edges(holistic_edges: list[dict]) -> list[dict]:
    """Map holistic TraceEdge dicts to the {source,target,value,token,time,
    tx_hash,chain} shape every analysis engine reads.

    Note: `time` is provided as an ISO 8601 STRING (the format the downstream
    engines' strptime-based parsers expect), while `timestamp` keeps the raw
    epoch int for engines that prefer it. Providing an int in `time` caused
    TypeError in crosschain_engine._parse_ts / clustering_engine._parse_ts."""
    out = []
    for e in holistic_edges:
        ts_raw = e.get("timestamp") or 0
        out.append({
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "value": float(e.get("value") or 0),
            "token": e.get("asset") or e.get("token") or "",
            "time": _epoch_to_iso(ts_raw) or (str(ts_raw) if ts_raw else ""),
            "timestamp": ts_raw,
            "tx_hash": e.get("tx_hash") or "",
            "hash": e.get("tx_hash") or "",
            "chain": e.get("chain", ""),
            "kind": e.get("kind", "transfer"),
        })
    return out


# ---------------------------------------------------------------------------
# Node enrichment (closes the placeholder-zeros gap in the graph model)
# ---------------------------------------------------------------------------
def _enrich_nodes(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Derive balance / tx_count / first_seen / last_seen / risk_labels for
    every node from the incident edges. Mutates and returns the node list.

    The holistic TraceNode only carries inflow_value/outflow_value/type — the
    frontend's GraphNode needs balance, tx_count, and temporal bounds, which
    were previously hardcoded to 0/empty in _holistic_to_graph_model."""
    inflow: dict[str, float] = defaultdict(float)
    outflow: dict[str, float] = defaultdict(float)
    tx_count: dict[str, int] = defaultdict(int)
    times: dict[str, list[int]] = defaultdict(list)
    for e in edges:
        s, t = e.get("source", ""), e.get("target", "")
        val = float(e.get("value") or 0)
        ts = int(e.get("timestamp") or 0)
        if s:
            outflow[s] += val
            tx_count[s] += 1
            if ts:
                times[s].append(ts)
        if t:
            inflow[t] += val
            tx_count[t] += 1
            if ts:
                times[t].append(ts)

    for n in nodes:
        nid = n.get("id", "")
        n["balance"] = round(inflow.get(nid, 0) - outflow.get(nid, 0), 6)
        n["inflow_value"] = round(inflow.get(nid, 0), 6)
        n["outflow_value"] = round(outflow.get(nid, 0), 6)
        n["tx_count"] = tx_count.get(nid, 0)
        node_times = times.get(nid, [])
        if node_times:
            n["first_seen"] = min(node_times)
            n["last_seen"] = max(node_times)
        else:
            n.setdefault("first_seen", 0)
            n.setdefault("last_seen", 0)
        # Multi-label risk flags (was a single [entity] label at most)
        labels = []
        ntype = n.get("type", "")
        if n.get("sanctioned") or ntype == "sanctioned":
            labels.append("sanctioned")
        if ntype == "mixer":
            labels.append("mixer")
        if ntype == "bridge":
            labels.append("bridge")
        if ntype == "dex":
            labels.append("dex")
        if ntype == "exchange":
            labels.append("exchange")
        if n.get("vasp"):
            labels.append(f"vasp:{n['vasp']}")
        if not labels and ntype and ntype != "unknown":
            labels.append(ntype)
        n["risk_labels"] = labels
    return nodes


# ---------------------------------------------------------------------------
# NEW algorithm 1: peel-chain detection
# ---------------------------------------------------------------------------
def detect_peel_chain(edges: list[dict], subject: str, min_length: int = 3) -> list[dict]:
    """Detect UTXO-style peel chains: a sequence where each wallet forwards
    (close to) its entire received balance to a single next wallet, leaving
    only a small change output. Classic Bitcoin laundering structure.

    A peel chain:  A -> B -> C -> D  where each hop forwards >=80% of inflow
    to exactly one successor. Length >= min_length (default 3) to qualify.

    Returns one finding per detected chain, with the full address path and a
    confidence derived from how consistently value is forwarded.
    """
    subject = subject.lower()
    # Build successor / inflow maps
    out_edges: dict[str, list[dict]] = defaultdict(list)
    in_total: dict[str, float] = defaultdict(float)
    for e in edges:
        s, t = e.get("source", "").lower(), e.get("target", "").lower()
        val = float(e.get("value") or 0)
        if s and t and val > 0:
            out_edges[s].append({"target": t, "value": val})
            in_total[t] += val

    def _forward_ratio(addr: str) -> tuple[float, Optional[str]]:
        """Return (max single-forward ratio, that successor) for addr."""
        outs = out_edges.get(addr, [])
        if not outs or in_total.get(addr, 0) <= 0:
            return 0.0, None
        top = max(outs, key=lambda o: o["value"])
        return top["value"] / in_total[addr], top["target"]

    chains: list[dict] = []
    visited_starts: set[str] = set()

    # Seed peel walks from every funded wallet (not just subject — peel chains
    # can start mid-graph after a fan-out).
    starts = {e.get("source", "").lower() for e in edges if float(e.get("value") or 0) > 0}
    for start in starts:
        if start in visited_starts:
            continue
        path = [start]
        ratios = []
        cur = start
        seen_in_chain = {start}
        while True:
            ratio, nxt = _forward_ratio(cur)
            if ratio < 0.8 or not nxt or nxt in seen_in_chain:
                break
            path.append(nxt)
            ratios.append(ratio)
            seen_in_chain.add(nxt)
            cur = nxt
            # cap walk length to avoid pathological loops
            if len(path) > 12:
                break
        visited_starts.add(start)
        if len(path) >= min_length + 1 and ratios:
            confidence = round(sum(ratios) / len(ratios), 3)
            chains.append({
                "pattern": "peel_chain",
                "scope": "path",
                "node_id": path[-1],
                "address": path[-1],
                "severity": "HIGH" if confidence >= 0.9 else "MEDIUM",
                "confidence": confidence,
                "evidence": (f"{len(path) - 1}-hop peel chain forwarding "
                             f"avg {confidence * 100:.0f}% of inflow per hop: "
                             f"{' -> '.join(a[:10] for a in path[:6])}"
                             f"{'…' if len(path) > 6 else ''}"),
                "path": path,
            })
    # Dedup by terminal node, keep highest-confidence chain per endpoint
    best: dict[str, dict] = {}
    for c in chains:
        key = c["node_id"]
        if key not in best or c["confidence"] > best[key]["confidence"]:
            best[key] = c
    return list(best.values())


# ---------------------------------------------------------------------------
# NEW algorithm 2: layering-sequence detection
# ---------------------------------------------------------------------------
# Service categories — a "service hop" is a transfer through a known obfuscation
# or conversion primitive. Consecutive different-category service hops = layering.
def _service_category(node_type: str) -> str:
    if node_type in ("mixer",):
        return "mixer"
    if node_type in ("bridge",):
        return "bridge"
    if node_type in ("dex",):
        return "swap"
    if node_type in ("exchange",):
        return "exchange"
    return ""


def detect_layering_sequence(nodes: list[dict], edges: list[dict], subject: str) -> list[dict]:
    """Detect layering: a path through 2+ DIFFERENT service categories in
    sequence (e.g. bridge -> mixer -> swap, or mixer -> bridge -> exchange).
    This is the canonical three-stage money-laundering 'layering' signature.

    Walks forward from the subject along value edges, tracking the sequence of
    service categories touched. A sequence of >=2 distinct categories flags it.

    Robust to id shape: the subject may be referenced by bare address OR by
    "{chain}:{address}" — we resolve both to the canonical node id before walking.
    """
    subject = subject.lower()
    node_by_id = {n["id"].lower(): n for n in nodes}
    # Resolve subject (bare address or {chain}:{addr}) to its canonical node id.
    subject_node = node_by_id.get(subject)
    if not subject_node:
        for n in nodes:
            if n.get("address", "").lower() == subject:
                subject_node = n
                node_by_id[subject] = n
                break
    subject_id = subject_node["id"].lower() if subject_node else subject

    out_edges: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        s, t = e.get("source", "").lower(), e.get("target", "").lower()
        if s and t:
            out_edges[s].append(t)

    findings: list[dict] = []
    start_cat = _service_category(subject_node.get("type", "")) if subject_node else ""
    init_seq = (start_cat,) if start_cat else ()
    queue: deque[tuple[str, tuple, list[str]]] = deque([(subject_id, init_seq, [subject_id])])
    seen_states: set[tuple[str, tuple]] = set()
    best_layering: dict[str, dict] = {}  # keyed by end node

    while queue:
        nid, seq, path = queue.popleft()
        if (nid, seq) in seen_states:
            continue
        seen_states.add((nid, seq))
        # Distinct categories (ignore empties from unknown intermediate wallets)
        distinct = tuple(c for c in seq if c)
        if len(set(distinct)) >= 2:
            # This is a layering path. Record it (keep longest per endpoint).
            end = nid
            if (end not in best_layering
                    or len(set(distinct)) > len(set(c for c in best_layering[end]["categories"] if c))):
                best_layering[end] = {
                    "pattern": "layering_sequence",
                    "scope": "path",
                    "node_id": end,
                    "address": end.split(":")[-1] if ":" in end else end,
                    "severity": "CRITICAL" if len(set(distinct)) >= 3 else "HIGH",
                    "confidence": round(min(0.95, 0.55 + 0.15 * len(set(distinct))), 2),
                    "evidence": (f"Layering via {' -> '.join(distinct)} "
                                 f"({len(set(distinct))} obfuscation stages)"),
                    "categories": list(distinct),
                    "path": path,
                }
        for nxt in out_edges.get(nid, []):
            nn = node_by_id.get(nxt, {})
            ncat = _service_category(nn.get("type", ""))
            nseq = seq + (ncat,) if ncat else seq
            if len(path) < 10:
                queue.append((nxt, nseq, path + [nxt]))

    return list(best_layering.values())


# ---------------------------------------------------------------------------
# NEW algorithm 3: dwell-time analysis
# ---------------------------------------------------------------------------
def dwell_time_analysis(edges: list[dict], subject: str, rapid_threshold_sec: int = 600) -> dict:
    """Per-wallet dwell time: how long funds sit before being forwarded.

    For every wallet that both receives and sends, compute the gap between its
    earliest inflow and earliest outflow. Gaps below `rapid_threshold_sec`
    (default 10 min) flag as rapid-movement / no-dwell — a strong structuring
    and automated-dispersal signal.

    Returns {dwell_times: [...], rapid_wallets: [...], avg_dwell_sec, summary}.
    """
    inflows: dict[str, list[int]] = defaultdict(list)
    outflows: dict[str, list[int]] = defaultdict(list)
    for e in edges:
        ts = int(e.get("timestamp") or 0)
        if ts <= 0:
            continue
        s, t = e.get("source", ""), e.get("target", "")
        if t:
            inflows[t].append(ts)
        if s:
            outflows[s].append(ts)

    dwell_times = []
    rapid_wallets = []
    for addr, in_ts in inflows.items():
        out_ts = outflows.get(addr, [])
        if not out_ts:
            continue  # never forwarded — no dwell to measure
        first_in = min(in_ts)
        first_out = min(out_ts)
        if first_out < first_in:
            # out before in — data ordering quirk; use absolute gap
            gap = first_in - first_out
        else:
            gap = first_out - first_in
        entry = {
            "address": addr,
            "dwell_sec": gap,
            "first_in": first_in,
            "first_out": first_out,
            "rapid": gap <= rapid_threshold_sec,
        }
        dwell_times.append(entry)
        if entry["rapid"]:
            rapid_wallets.append(addr)

    dwell_times.sort(key=lambda d: d["dwell_sec"])
    valid_gaps = [d["dwell_sec"] for d in dwell_times if d["dwell_sec"] >= 0]
    avg = round(sum(valid_gaps) / len(valid_gaps)) if valid_gaps else 0
    return {
        "dwell_times": dwell_times[:50],  # cap for payload size
        "rapid_wallet_count": len(rapid_wallets),
        "rapid_wallets": rapid_wallets[:30],
        "rapid_threshold_sec": rapid_threshold_sec,
        "avg_dwell_sec": avg,
        "summary": (f"{len(rapid_wallets)} wallet(s) forwarded funds within "
                    f"{rapid_threshold_sec}s of receipt (rapid movement)"),
    }


# ---------------------------------------------------------------------------
# Pattern normalization + merge
# ---------------------------------------------------------------------------
def _to_pattern(finding: dict, default_node: str = "") -> dict:
    """Normalize any engine finding into the TracePattern contract the frontend
    already consumes: {scope, node_id, address, pattern, severity, confidence, evidence}."""
    return {
        "scope": finding.get("scope", "node"),
        "node_id": finding.get("node_id") or finding.get("address") or default_node,
        "address": finding.get("address", ""),
        "pattern": finding.get("pattern") or finding.get("name") or finding.get("type", "unknown"),
        "severity": finding.get("severity", "MEDIUM"),
        "confidence": finding.get("confidence", "medium"),
        "evidence": finding.get("evidence", finding.get("detail", "")),
    }


def _safe_call(fn, *args, **kwargs):
    """Run an analysis engine; return (result_or_None, error_or_None)."""
    try:
        return fn(*args, **kwargs), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{fn.__name__}: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------
async def deep_analyze(
    subject: str,
    chain: str = "eth",
    direction: str = "both",
    max_hops: int = 3,
    max_nodes: int = 120,
    api_key: str = "",
    per_address_limit: int = 40,
    time_budget: float = 0.0,
    progress=None,
) -> dict[str, Any]:
    """Run a deep analysis pass: trace + enrich + 5 engines + 3 new algorithms,
    merged into a single result with populated `patterns` and an `analysis` block.

    The returned dict is a superset of holistic_trace_engine.trace()'s output:
      - All original keys preserved (subject, graph, summary, errors, ...)
      - graph.nodes are enriched (balance, tx_count, first_seen, last_seen, risk_labels)
      - patterns[] populated (was always empty before)
      - analysis{} new block: clusters, crosschain, cashout, forensics, dwell
    """
    subject = hte._addr(subject)

    # ── progress helper (summarized, user-friendly; never technical) ──
    def _emit(pct: int, label: str, detail: str = ""):
        if progress is not None:
            try:
                progress({"pct": max(0, min(100, pct)), "label": label, "detail": detail})
            except Exception:  # noqa: BLE001
                pass

    _emit(3, "Starting deep analysis", "Preparing the investigation")

    # ── 1. Live trace ──
    # Reserve ~12s of the overall budget for the in-memory engines + serialization
    # so the fetch phase never consumes the whole window.
    trace_budget = max(20.0, time_budget - 12.0) if time_budget and time_budget > 0 else 0.0

    def _trace_progress(fetched: int, cap: int, hop: int):
        # Map fetch progress onto 5–62% of the overall bar.
        frac = (fetched / cap) if cap else 0.0
        _emit(5 + int(frac * 57),
              "Following the money",
              f"Traced {fetched} of up to {cap} wallets across {hop + 1} hop(s)")

    result = await hte.trace(
        subject=subject, chain=chain, direction=direction,
        max_hops=max_hops, max_nodes=max_nodes,
        api_key=api_key, per_address_limit=per_address_limit,
        time_budget=trace_budget, progress=_trace_progress,
    )
    _emit(64, "Building the flow graph", "Organizing wallets and transfers")

    g = result.get("graph") or {}
    raw_nodes = g.get("nodes") or []
    raw_edges = g.get("edges") or []

    if not raw_edges:
        # Nothing to analyze — return the trace as-is with empty analysis.
        result["patterns"] = []
        result["analysis"] = {"note": "No transfers to analyze."}
        return result

    # ── 2. Enrich nodes ──
    raw_nodes = _enrich_nodes(raw_nodes, raw_edges)
    g["nodes"] = raw_nodes
    result["graph"] = g

    # ── 3. Normalize for engines ──
    eng_nodes = _to_engine_nodes(raw_nodes)
    eng_edges = _to_engine_edges(raw_edges)
    subject_id = eng_nodes[0]["id"] if eng_nodes else subject

    analysis: dict[str, Any] = {"engines": {}}
    all_findings: list[dict] = []
    engine_errors: list[str] = []

    # ── 4a. Forensic motifs (fan_out, fan_in, pass_through, round_amounts, ...) ──
    _emit(67, "Detecting laundering patterns", "Fan-out, pass-through, round-amount motifs")
    intel = {"address": subject, "chain": chain}
    trace_graph_for_fe = {
        "nodes": [{"id": n["id"], "address": n["address"], "chain": n["chain"]} for n in eng_nodes],
        "edges": eng_edges,
    }
    forensics, err = _safe_call(
        _import_and_run_forensics, intel, trace_graph_for_fe
    )
    if err:
        engine_errors.append(err)
    else:
        motifs = (forensics or {}).get("summary", {}).get("motifs", []) or (forensics or {}).get("motifs", [])
        for m in motifs:
            all_findings.append(_to_pattern({**m, "scope": "node", "node_id": subject_id}))
        analysis["engines"]["forensics"] = {
            "role": (forensics or {}).get("summary", {}).get("role"),
            "motif_count": len(motifs),
        }

    # ── 4b. Cashout detection ──
    _emit(75, "Finding cash-out routes", "Exchanges, off-ramps and service deposits")
    cashout, err = _safe_call(_import_cashout().detect_cashout, eng_nodes, eng_edges, subject_id)
    if err:
        engine_errors.append(err)
    else:
        for ind in (cashout or {}).get("indicators", []):
            all_findings.append(_to_pattern({
                "pattern": f"cashout_{ind.get('type', 'unknown')}",
                "scope": "node",
                "node_id": ind.get("destination") or subject_id,
                "address": ind.get("destination", ""),
                "severity": ind.get("severity", "MEDIUM"),
                "confidence": ind.get("confidence", 0.5),
                "evidence": ind.get("evidence") or ind.get("detail", ""),
            }))
        analysis["engines"]["cashout"] = {
            "indicator_count": (cashout or {}).get("indicator_count", 0),
            "primary_dest": (cashout or {}).get("primary_cashout_dest"),
            "risk": (cashout or {}).get("risk"),
        }

    # ── 4c. Cross-chain bridge stitching (value-time match) ──
    _emit(81, "Checking cross-chain hops", "Bridges and swaps to other blockchains")
    crosschain, err = _safe_call(_import_crosschain().trace_crosschain, eng_nodes, eng_edges, subject_id)
    if err:
        engine_errors.append(err)
    else:
        cc = crosschain or {}
        for vm in cc.get("value_matches", []):
            all_findings.append(_to_pattern({
                "pattern": "crosschain_value_match",
                "scope": "path",
                "node_id": vm.get("dest_id") or subject_id,
                "address": vm.get("dest_address", ""),
                "severity": "HIGH",
                "confidence": vm.get("confidence", 0.7),
                "evidence": vm.get("evidence", "Cross-chain value+time match"),
            }))
        analysis["engines"]["crosschain"] = {
            "bridge_hops": len(cc.get("bridge_hops", [])),
            "value_matches": len(cc.get("value_matches", [])),
            "paths": cc.get("crosschain_paths", []),
            "bridges_seen": cc.get("bridges_seen", []),
        }

    # ── 4d. Clustering (common-control wallet groups) ──
    _emit(87, "Grouping related wallets", "Common-control clustering leads")
    clusters, err = _safe_call(_import_clustering().analyze_clusters, eng_nodes, eng_edges)
    if err:
        engine_errors.append(err)
    else:
        cluster_list = (clusters or {}).get("clusters", [])
        analysis["engines"]["clusters"] = {
            "count": len(cluster_list),
            "clusters": cluster_list,
        }

    # ── 4e. Per-node composite risk scoring ──
    _emit(92, "Scoring risk", "Sanctions, mixer and service exposure")
    risk_module = _import_risk()
    if risk_module:
        for n in eng_nodes:
            if n.get("sanctioned") or n.get("type") in ("mixer", "bridge", "dex", "exchange"):
                node_intel = {
                    "address": n["address"],
                    "chain": n["chain"],
                    "sanctions": {"sanctioned": n.get("sanctioned")} if n.get("sanctioned") else {},
                    "mixer_hits": [{"mixer_name": n.get("label", "Mixer")}] if n.get("type") == "mixer" else [],
                }
                scored, err = _safe_call(risk_module.compute_risk_score, node_intel)
                if not err and scored:
                    n["risk_score_composite"] = scored.get("score", n.get("risk_score", 0))
                    n["risk_signals"] = scored.get("signals", [])
        analysis["engines"]["risk"] = {"scored_nodes": sum(1 for n in eng_nodes if "risk_score_composite" in n)}

    # ── 5. New algorithms ──
    _emit(96, "Spotting peel-chains & timing", "Peel-chain, layering and dwell-time")
    peel_findings = detect_peel_chain(eng_edges, subject)
    all_findings.extend(peel_findings)
    layer_findings = detect_layering_sequence(eng_nodes, eng_edges, subject)
    all_findings.extend(layer_findings)
    dwell = dwell_time_analysis(eng_edges, subject)
    analysis["dwell"] = dwell
    if dwell["rapid_wallet_count"] > 0:
        all_findings.append({
            "pattern": "rapid_movement",
            "scope": "graph",
            "node_id": subject_id,
            "address": subject,
            "severity": "HIGH" if dwell["rapid_wallet_count"] >= 3 else "MEDIUM",
            "confidence": 0.8,
            "evidence": dwell["summary"],
        })

    # ── 6. Merge + dedup patterns ──
    # Dedup by (pattern, node_id); keep highest-severity / highest-confidence.
    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    best_pattern: dict[tuple, dict] = {}
    for p in all_findings:
        key = (p.get("pattern", ""), p.get("node_id", ""))
        existing = best_pattern.get(key)
        if (not existing
                or severity_rank.get(str(p.get("severity")).upper(), 0)
                    > severity_rank.get(str(existing.get("severity")).upper(), 0)):
            best_pattern[key] = p
    # Sort: highest severity first, then confidence desc.
    patterns = sorted(
        best_pattern.values(),
        key=lambda p: (-severity_rank.get(str(p.get("severity")).upper(), 0),
                       -(p["confidence"] if isinstance(p.get("confidence"), (int, float)) else 0.5)),
    )

    result["patterns"] = patterns
    analysis["pattern_count"] = len(patterns)
    analysis["engine_errors"] = engine_errors
    analysis["peel_chains"] = [p for p in peel_findings]
    analysis["layering"] = [p for p in layer_findings]
    result["analysis"] = analysis
    _emit(100, "Done", f"{len(patterns)} pattern(s) · {len(raw_nodes)} wallet(s) analyzed")
    return result


# ---------------------------------------------------------------------------
# Lazy imports (engines are heavy; only load when deep analysis runs)
# ---------------------------------------------------------------------------
def _import_and_run_forensics(intel: dict, trace_graph: dict) -> dict:
    import forensic_engine
    return forensic_engine.analyze_forensics(intel, trace_graph=trace_graph)


def _import_cashout():
    import cashout_detector
    return cashout_detector


def _import_crosschain():
    import crosschain_engine
    return crosschain_engine


def _import_clustering():
    import clustering_engine
    return clustering_engine


def _import_risk():
    try:
        import risk_engine
        return risk_engine
    except Exception:  # noqa: BLE001
        return None
