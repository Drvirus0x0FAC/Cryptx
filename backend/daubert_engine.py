"""
Court-readiness / evidentiary-depth engine (Domain C).

Generalizes the attribution "court methodology document" to EVERY heuristic the
platform applies, and packages the result as a Daubert admissibility appendix —
the four factors a US federal court weighs (testability, peer review, known error
rate, general acceptance) for each technique used in a case.

Also provides tamper-evident notarization: SHA-256 content hashing plus a
local trusted-timestamp record and hash chain, so exported exhibits are
independently datable and any post-hoc edit is detectable.

Pure/local. No network. Complements (does not replace) attribution_workflow's
attribution-only report and the evidence_vault hash/audit log.
"""
from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

BENCHMARK_RESULTS = Path(__file__).parent / "benchmarks" / "benchmark_results.json"

# benchmark detector id → METHODS key it substantiates
_BENCHMARK_METHOD_MAP = {
    "address_poisoning": "address_poisoning",
    "demix_pairing": "demix_pairing",
    "contract_static_scan": "contract_static_scan",
    "approval_exposure": "contract_static_scan",
    "swap_continuation": "swap_continuation",
    "fan_out_motif": "peel_chain",
}

# ── Catalog of platform heuristics with their Daubert scaffolding ─────────────
# Each method: technique, peer-reviewed basis, error-rate class, confidence
# semantics, and the four Daubert factors. Keys match the method ids the
# engines emit so a dossier can be assembled from "which methods fired".
METHODS: dict[str, dict[str, Any]] = {
    "cospend_clustering": {
        "name": "Common-input (co-spend) clustering",
        "technique": "Groups addresses that jointly authorize a single transaction's inputs, "
                     "inferring common control from the multi-input spend heuristic.",
        "peer_review": "Meiklejohn et al., 'A Fistful of Bitcoins' (IMC 2013); Reid & Harrigan (2013). "
                       "Accepted in US v. Sterlingov (2024) under Daubert.",
        "error_rate": "Low for co-spend; elevated where CoinJoin/mixing breaks the assumption "
                      "(the engine excludes recognized CoinJoin patterns).",
        "confidence": "Reported as a common-control LEAD, never asserted ownership.",
        "testability": "Deterministic and independently reproducible from the public ledger.",
        "general_acceptance": "Standard across Chainalysis, Elliptic, TRM and academic literature.",
    },
    "demix_pairing": {
        "name": "Mixer deposit↔withdrawal pairing",
        "technique": "Links fixed-denomination pool deposits to withdrawals by denomination, "
                     "timing, and gas/relayer fingerprints; ranked candidates with explicit confidence.",
        "peer_review": "Wu et al. on Tornado Cash linkability; Béres et al. (2021) mixer analysis.",
        "error_rate": "Probabilistic — each link carries a confidence; multiple equally-ranked "
                      "candidates are surfaced rather than a single deterministic answer.",
        "confidence": "Ranked leads with numeric confidence and the evidence each rests on.",
        "testability": "Reproducible from pool events; candidate sets are enumerable.",
        "general_acceptance": "Demixing is offered by all major vendors; methodology is published.",
    },
    "taint_propagation": {
        "name": "Taint / value-flow propagation",
        "technique": "Propagates a taint fraction forward through transactions (haircut/FIFO variants) "
                     "to quantify exposure between a source and downstream addresses.",
        "peer_review": "Haircut and FIFO tainting formalized in Möser & Böhme; UK 'Clayton's Case' FIFO precedent.",
        "error_rate": "Method-dependent; the model used (haircut vs FIFO) is disclosed per run.",
        "confidence": "Exposure percentages with the propagation model named.",
        "testability": "Deterministic given the model and the transaction graph.",
        "general_acceptance": "Widely used for AML exposure scoring across the industry.",
    },
    "peel_chain": {
        "name": "Peel-chain detection",
        "technique": "Identifies sequences that forward the bulk of value hop-to-hop while peeling small "
                     "remainders — a canonical layering structure.",
        "peer_review": "Documented across FATF typology reports and vendor methodology papers.",
        "error_rate": "Behavioral; scored with confidence, corroboration recommended.",
        "confidence": "Confidence score with the hop evidence enumerated.",
        "testability": "Reproducible from the ordered transaction sequence.",
        "general_acceptance": "Established laundering typology.",
    },
    "cashout_detection": {
        "name": "Cash-out / off-ramp detection",
        "technique": "Flags fan-in-to-exchange and hot-wallet redistribution patterns indicating fiat off-ramping.",
        "peer_review": "Exchange-deposit clustering per Meiklejohn et al.; vendor off-ramp methodologies.",
        "error_rate": "Low for known-exchange endpoints; depends on VASP attribution freshness.",
        "confidence": "Endpoint attribution carries source + confidence.",
        "testability": "Reproducible against the VASP/exchange registry snapshot used.",
        "general_acceptance": "Core AML technique.",
    },
    "address_poisoning": {
        "name": "Address-poisoning (look-alike) detection",
        "technique": "Flags inbound dust from addresses sharing a real counterparty's prefix+suffix, "
                     "the visual trick behind copy-paste theft.",
        "peer_review": "Documented by Chainalysis/Coinbase security advisories (2023–2025).",
        "error_rate": "Low false-positive: requires both a dust value and a prefix+suffix collision "
                      "with a genuine counterparty.",
        "confidence": "Deterministic match; each hit names the spoofed address.",
        "testability": "Fully reproducible from the transfer set.",
        "general_acceptance": "Recognized industry-wide as a distinct scam typology.",
    },
    "bytecode_similarity": {
        "name": "Bytecode similarity / attacker-contract clustering",
        "technique": "Fingerprints deployed bytecode (opcode distribution + selector set) and matches against "
                     "known-malicious contracts to expand an attacker's deployment family.",
        "peer_review": "Contract similarity via opcode n-grams / embeddings — established program-analysis technique "
                       "(e.g., DeepBinDiff, EtherSolve); applied by AnChain to the Bybit exploiter set.",
        "error_rate": "Similarity is a graded score; matches are ranked with an explicit threshold.",
        "confidence": "Cosine/Jaccard similarity 0–1 with shared-selector evidence.",
        "testability": "Deterministic from public bytecode; recomputable by any party.",
        "general_acceptance": "Binary/bytecode similarity is standard in security research.",
    },
    "swap_continuation": {
        "name": "Instant-exchanger / cross-chain swap continuation",
        "technique": "Recognizes deposits into labeled no-KYC swap services (FixedFloat, THORChain, "
                     "Chainflip …) and re-matches probable output-side settlements by value tolerance "
                     "and time window.",
        "peer_review": "Cross-chain value/time-window matching per Elliptic and Merkle Science published "
                       "bridge-tracing methodologies; service registry disclosed per run.",
        "error_rate": "Continuation matches are probabilistic leads ranked by value/time proximity; "
                      "the tolerance and window used are disclosed.",
        "confidence": "Each match reports the value delta and time gap it rests on.",
        "testability": "Reproducible from the transfer set and the disclosed service registry snapshot.",
        "general_acceptance": "Swap/bridge re-matching is standard practice across major vendors.",
    },
    "contract_static_scan": {
        "name": "Smart-contract static risk scan",
        "technique": "Detects privileged-control and honeypot patterns from selectors, source keywords, and opcodes "
                     "(mint, blacklist, mutable fee, pausable, upgradeable proxy, selfdestruct).",
        "peer_review": "Pattern set aligns with SWC Registry, Slither/Mythril detectors, and honeypot literature.",
        "error_rate": "Static analysis: findings are evidence-cited; absence is not a safety guarantee (disclosed).",
        "confidence": "Each finding cites the exact selector/opcode/source line.",
        "testability": "Deterministic and reproducible from the artifacts.",
        "general_acceptance": "Static contract analysis is standard audit practice.",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# Methodology dossier
# ═══════════════════════════════════════════════════════════════════════════
def measured_error_rates() -> dict[str, Any]:
    """Load the latest labeled-benchmark results (benchmarks/run_benchmark.py).

    Returns {method_id: [ {detector, precision, recall, fpr, n, version, generated_at} ]}.
    Empty when the benchmark has not been run — dossiers then fall back to the
    qualitative error-rate statements.
    """
    try:
        raw = json.loads(BENCHMARK_RESULTS.read_text())
    except (OSError, ValueError):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for det, stats in (raw.get("detectors") or {}).items():
        method = _BENCHMARK_METHOD_MAP.get(det)
        if not method:
            continue
        out.setdefault(method, []).append({
            "detector": det,
            "precision": stats.get("precision"),
            "recall": stats.get("recall"),
            "false_positive_rate": stats.get("false_positive_rate"),
            "n": stats.get("n"),
            "benchmark_version": raw.get("benchmark_version"),
            "generated_at": raw.get("generated_at"),
            "corpus": raw.get("corpus"),
        })
    return out


def _measured_statement(entries: list[dict[str, Any]]) -> str:
    parts = []
    for e in entries:
        parts.append(
            f"{e['detector']}: precision {e['precision']}, recall {e['recall']}, "
            f"FPR {e['false_positive_rate']} (n={e['n']}, benchmark v{e['benchmark_version']})")
    return ("MEASURED on the reproducible labeled benchmark — " + "; ".join(parts) +
            ". Corpus: " + (entries[0].get("corpus") or "seeded synthetic labeled corpus") + ".")


def list_methods() -> dict[str, Any]:
    measured = measured_error_rates()
    methods = []
    for k, v in METHODS.items():
        entry = {"id": k, **v}
        if k in measured:
            entry["measured_performance"] = measured[k]
        methods.append(entry)
    return {"methods": methods, "count": len(methods),
            "benchmark_available": bool(measured)}


def build_dossier(case_ref: str, methods_used: Iterable[str],
                  analyst: str = "", subject: str = "",
                  findings: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Assemble a Daubert admissibility appendix for the methods applied in a case."""
    used = [m for m in dict.fromkeys(methods_used) if m in METHODS]
    unknown = [m for m in methods_used if m not in METHODS]
    measured = measured_error_rates()
    entries = []
    for m in used:
        meta = METHODS[m]
        error_rate = meta["error_rate"]
        if m in measured:  # benchmark numbers upgrade the qualitative statement
            error_rate = f"{error_rate} {_measured_statement(measured[m])}"
        entry = {
            "id": m,
            "name": meta["name"],
            "technique": meta["technique"],
            "daubert": {
                "testability": meta["testability"],
                "peer_review": meta["peer_review"],
                "known_error_rate": error_rate,
                "general_acceptance": meta["general_acceptance"],
            },
            "confidence_reporting": meta["confidence"],
        }
        if m in measured:
            entry["measured_performance"] = measured[m]
        entries.append(entry)
    manifest = {
        "case_ref": case_ref,
        "subject": subject,
        "analyst": analyst,
        "generated_at": _now_iso(),
        "methods": entries,
        "unrecognized_methods": unknown,
        "findings_summary": findings or [],
        "standard": "Daubert v. Merrell Dow Pharmaceuticals, 509 U.S. 579 (1993) — four-factor reliability test.",
        "attestation": "Each technique above is deterministic or reports explicit confidence; all outputs are "
                       "reproducible from public on-chain data and the disclosed registry snapshots.",
    }
    manifest["content_sha256"] = _sha256(json.dumps(manifest, sort_keys=True, default=str).encode())
    return manifest


def render_dossier_html(dossier: dict[str, Any]) -> str:
    """Self-contained, print-ready HTML admissibility appendix."""
    e = html.escape
    rows = []
    for m in dossier.get("methods", []):
        d = m["daubert"]
        rows.append(f"""
        <section class="method">
          <h3>{e(m['name'])}</h3>
          <p class="tech">{e(m['technique'])}</p>
          <table>
            <tr><th>Testability</th><td>{e(d['testability'])}</td></tr>
            <tr><th>Peer review &amp; publication</th><td>{e(d['peer_review'])}</td></tr>
            <tr><th>Known / potential error rate</th><td>{e(d['known_error_rate'])}</td></tr>
            <tr><th>General acceptance</th><td>{e(d['general_acceptance'])}</td></tr>
            <tr><th>Confidence reporting</th><td>{e(m['confidence_reporting'])}</td></tr>
          </table>
        </section>""")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Daubert Methodology Appendix — {e(dossier.get('case_ref',''))}</title>
<style>
  body{{font-family:Georgia,'Times New Roman',serif;color:#111;max-width:920px;margin:32px auto;line-height:1.5}}
  h1{{font-size:22px;border-bottom:2px solid #111;padding-bottom:8px}}
  h3{{font-size:16px;margin:22px 0 4px}}
  .meta{{color:#444;font-size:13px;margin-bottom:18px}}
  .tech{{font-style:italic;color:#333}}
  table{{border-collapse:collapse;width:100%;margin:8px 0 4px;font-size:13px}}
  th,td{{border:1px solid #bbb;padding:6px 8px;text-align:left;vertical-align:top}}
  th{{width:230px;background:#f3f3f3}}
  .hash{{font-family:monospace;font-size:11px;word-break:break-all;color:#555}}
  footer{{margin-top:28px;font-size:12px;color:#555;border-top:1px solid #ccc;padding-top:10px}}
</style></head><body>
<h1>Daubert Methodology Appendix</h1>
<div class="meta">
  <strong>Case:</strong> {e(dossier.get('case_ref',''))} &nbsp;·&nbsp;
  <strong>Subject:</strong> {e(dossier.get('subject','—'))} &nbsp;·&nbsp;
  <strong>Analyst:</strong> {e(dossier.get('analyst','—'))}<br>
  <strong>Generated:</strong> {e(dossier.get('generated_at',''))}<br>
  <strong>Standard:</strong> {e(dossier.get('standard',''))}
</div>
{''.join(rows) or '<p>No recognized methods supplied.</p>'}
<footer>
  <p>{e(dossier.get('attestation',''))}</p>
  <p class="hash">Content SHA-256: {e(dossier.get('content_sha256',''))}</p>
</footer>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════════
# Tamper-evident notarization (chain-of-custody hardening)
# ═══════════════════════════════════════════════════════════════════════════
def notarize(payload: Any, prev_hash: str = "", label: str = "", tsa_url: str | None = None) -> dict[str, Any]:
    """Produce a tamper-evident notarization record for an exhibit/export.

    Returns a record containing the content SHA-256, a UTC trusted-timestamp,
    and a chained hash linking to `prev_hash` (the previous record's chain hash).
    Verifiable offline; any edit to the payload changes content_hash and breaks
    the chain.

    If `tsa_url` (or config.TSA_URL) is set, the content is also submitted to an
    RFC-3161 Trusted Timestamp Authority and the verified token is attached —
    making the record externally datable and court-admissible. TSA failures never
    block the export; on failure the record carries tsa_error and falls back to
    the local timestamp.
    """
    raw = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload, sort_keys=True, default=str).encode()
    content_hash = _sha256(raw)
    ts = _now_iso()
    chain_hash = _sha256(f"{prev_hash}|{content_hash}|{ts}".encode())

    record = {
        "label": label,
        "content_sha256": content_hash,
        "timestamp_utc": ts,
        "prev_chain_hash": prev_hash,
        "chain_hash": chain_hash,
        "algorithm": "SHA-256 hash chain over (prev_chain_hash | content_hash | timestamp_utc)",
    }

    # RFC-3161 trusted timestamping (optional, court-admissibility asset).
    # Lazy import so the engine runs without rfc3161ng installed.
    effective_tsa = tsa_url if tsa_url is not None else _tsa_url()
    if effective_tsa:
        try:
            import tsa_client
            tsa_result = tsa_client.request_timestamp(raw, effective_tsa)
            record["tsa"] = tsa_result
            if tsa_result.get("tsa_verified"):
                record["court_timestamp"] = tsa_result.get("tsa_timestamp") or ts
                record["note"] = ("Local hash-chain record + RFC-3161 trusted timestamp from "
                                  f"{tsa_result.get('tsa_issuer')}. Externally datable and court-admissible.")
            else:
                record["note"] = ("Local trusted-timestamp record. RFC-3161 TSA timestamping attempted but failed: "
                                  f"{tsa_result.get('tsa_error')}. Submit content_sha256 to an accredited TSA manually.")
        except Exception as exc:
            record["tsa"] = {"tsa_verified": False, "tsa_error": str(exc)}
            record["note"] = f"Local hash-chain record. TSA integration error: {exc}"
    else:
        record["note"] = ("Local trusted-timestamp record. For statutory RFC-3161 timestamping, set the "
                          "TSA_URL env var to an accredited TSA endpoint.")
    return record


def _tsa_url() -> str:
    """Read TSA_URL from config without importing config at module load (avoids
    a circular import risk if daubert is ever imported before config)."""
    try:
        import config
        return getattr(config, "TSA_URL", "") or ""
    except Exception:
        return ""


def verify_chain(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the hash chain to confirm no record was altered or reordered."""
    prev = ""
    broken_at = -1
    for i, r in enumerate(records):
        expect = _sha256(f"{prev}|{r.get('content_sha256','')}|{r.get('timestamp_utc','')}".encode())
        if expect != r.get("chain_hash"):
            broken_at = i
            break
        prev = r.get("chain_hash", "")
    ok = broken_at == -1
    return {
        "valid": ok,
        "records": len(records),
        "broken_at_index": None if ok else broken_at,
        "verdict": "Chain intact — no record altered or reordered." if ok
                   else f"TAMPER DETECTED at record #{broken_at}: content or timestamp does not match the chain.",
    }
