"""
Labeled detector benchmark → measured error rates for the Daubert dossier.

Runs every core detector against a seeded synthetic labeled corpus (see
tests/synthetic.py) and computes precision / recall / FPR / FNR. Results are
written to benchmarks/benchmark_results.json, which daubert_engine merges into
each method's "known error rate" statement — turning engineering hygiene into
an admissibility artifact.

Run:  python -m benchmarks.run_benchmark        (from backend/)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tests.synthetic import corpus  # noqa: E402

RESULTS_PATH = Path(__file__).parent / "benchmark_results.json"
BENCHMARK_VERSION = "1.0"
N_PER_CLASS = 50


def _predict(detector: str, case: dict) -> bool:
    """Binary prediction per detector on one labeled case."""
    if detector == "address_poisoning":
        import laundering_trace as lt
        r = lt.detect_address_poisoning(case["subject"], case["transfers"])
        return bool(r["poisoning_hits"])
    if detector == "swap_continuation":
        import laundering_trace as lt
        r = lt.detect_swap_continuation(case["subject"], case["transfers"],
                                        candidate_outputs=case["outputs"])
        return r["entry_count"] > 0
    if detector == "demix_pairing":
        import demix_engine as dm
        r = dm.demix_tornado(case["deposits"], case["withdrawals"])
        top = [c for l in r["links"] for c in l["candidates"] if c["confidence"] > 0.5]
        if not top:
            return False
        # correctness matters, not just firing: top candidate must be the true pair
        if case.get("true_deposit"):
            return top[0]["deposit_tx"] == case["true_deposit"]
        return True
    if detector == "contract_static_scan":
        import contract_forensics as cf
        return cf.scan_contract(abi_selectors=case["abi_selectors"])["risk_score"] >= 50
    if detector == "approval_exposure":
        import contract_forensics as cf
        r = cf.approval_exposure(case["approvals"], malicious_spenders=case["malicious"])
        return r["flagged_malicious"] > 0
    if detector == "fan_out_motif":
        import forensic_engine as fe
        feats = fe.behavior_fingerprint({"address": case["subject"]}, case["edges"])
        return any(m["pattern"] == "fan_out_dispersal"
                   for m in fe.detect_motifs(case["edges"], feats, case["subject"]))
    raise ValueError(f"unknown detector {detector}")


def run() -> dict:
    data = corpus(N_PER_CLASS)
    results = {}
    for detector, cases in data.items():
        tp = fp = fn = tn = 0
        for case in cases:
            pred = _predict(detector, case)
            actual = case["label"]
            if pred and actual:
                tp += 1
            elif pred and not actual:
                fp += 1
            elif not pred and actual:
                fn += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        fpr = fp / (fp + tn) if (fp + tn) else None
        results[detector] = {
            "n": len(cases), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "false_positive_rate": round(fpr, 4) if fpr is not None else None,
        }
    payload = {
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": f"seeded synthetic labeled corpus, {N_PER_CLASS} positive + {N_PER_CLASS} negative per detector "
                  "(tests/synthetic.py — fully reproducible)",
        "detectors": results,
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    out = run()
    print(f"Benchmark v{out['benchmark_version']} → {RESULTS_PATH}")
    for name, r in out["detectors"].items():
        print(f"  {name:24s} precision={r['precision']} recall={r['recall']} fpr={r['false_positive_rate']} (n={r['n']})")
