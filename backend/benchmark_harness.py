"""
Detector benchmark harness — measured error rates for Daubert admissibility.

The Daubert standard (cleared by Chainalysis Reactor in *US v. Sterlingov*)
requires "known error rates" for any forensic technique. This harness runs
every detector against a labeled benchmark dataset and computes precision,
recall, F1, false-positive rate, and false-negative rate — the exact numbers
that feed `daubert_engine`'s admissibility appendix.

Design:
  * Each detector is registered with a callable + a benchmark dataset (fixtures).
  * The harness runs the detector, compares to ground-truth labels, computes metrics.
  * Results are structured for direct inclusion in the Daubert dossier.

This is engineering hygiene turned into a court admissibility asset: the test
suite that already validates correctness also produces the error-rate numbers
the court wants to see.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BenchmarkCase:
    """A single labeled test case for a detector."""
    input: dict[str, Any]       # the data the detector processes
    expected: Any               # ground-truth: True (positive) / False (negative) / a value
    label: str = ""             # human-readable description


@dataclass
class BenchmarkResult:
    """Results of running a detector against its benchmark dataset."""
    detector_name: str
    total_cases: int
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0
    case_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def precision(self) -> float:
        """Of all positives the detector flagged, how many were real? (1 - FPR-ish)"""
        predicted_pos = self.true_positives + self.false_positives
        return self.true_positives / predicted_pos if predicted_pos else 0.0

    @property
    def recall(self) -> float:
        """Of all real positives, how many did the detector catch?"""
        actual_pos = self.true_positives + self.false_negatives
        return self.true_positives / actual_pos if actual_pos else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def false_positive_rate(self) -> float:
        """Of all real negatives, how many were wrongly flagged? (Daubert key metric)"""
        actual_neg = self.true_negatives + self.false_positives
        return self.false_positives / actual_neg if actual_neg else 0.0

    @property
    def false_negative_rate(self) -> float:
        actual_pos = self.true_positives + self.false_negatives
        return self.false_negatives / actual_pos if actual_pos else 0.0

    @property
    def accuracy(self) -> float:
        correct = self.true_positives + self.true_negatives
        return correct / self.total_cases if self.total_cases else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector_name,
            "total_cases": self.total_cases,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "false_negative_rate": round(self.false_negative_rate, 4),
            "accuracy": round(self.accuracy, 4),
        }


def run_benchmark(
    detector_name: str,
    detector_fn: Callable[[dict[str, Any]], bool],
    cases: list[BenchmarkCase],
) -> BenchmarkResult:
    """Run a boolean detector against labeled cases.

    `detector_fn` takes a case's `input` dict and returns True (positive detection)
    or False (no detection). The result is compared to `case.expected` (True/False).

    Returns a BenchmarkResult with full metrics.
    """
    result = BenchmarkResult(detector_name=detector_name, total_cases=len(cases))

    for case in cases:
        try:
            predicted = bool(detector_fn(case.input))
        except Exception:
            predicted = False  # a crash counts as a missed detection

        expected = bool(case.expected)

        if predicted and expected:
            result.true_positives += 1
        elif predicted and not expected:
            result.false_positives += 1
        elif not predicted and not expected:
            result.true_negatives += 1
        else:
            result.false_negatives += 1

        result.case_results.append({
            "label": case.label,
            "expected": expected,
            "predicted": predicted,
            "correct": predicted == expected,
        })

    return result


# ── Registry of detector benchmarks ─────────────────────────────────────────
# Each entry: (detector_name, detector_fn, cases). Populated by register_benchmark().
_REGISTRY: dict[str, tuple[Callable, list[BenchmarkCase]]] = {}


def register_benchmark(
    detector_name: str,
    detector_fn: Callable[[dict[str, Any]], bool],
    cases: list[BenchmarkCase],
) -> None:
    """Register a detector + its benchmark dataset."""
    _REGISTRY[detector_name] = (detector_fn, cases)


def run_all_benchmarks() -> dict[str, Any]:
    """Run every registered detector benchmark. Returns a structured report
    suitable for inclusion in the Daubert dossier."""
    results: list[dict[str, Any]] = []
    for name, (fn, cases) in _REGISTRY.items():
        result = run_benchmark(name, fn, cases)
        results.append(result.to_dict())

    # Overall summary.
    total_cases = sum(r["total_cases"] for r in results)
    avg_precision = sum(r["precision"] for r in results) / len(results) if results else 0
    avg_recall = sum(r["recall"] for r in results) / len(results) if results else 0
    avg_fpr = sum(r["false_positive_rate"] for r in results) / len(results) if results else 0

    return {
        "detectors_tested": len(results),
        "total_cases": total_cases,
        "average_precision": round(avg_precision, 4),
        "average_recall": round(avg_recall, 4),
        "average_false_positive_rate": round(avg_fpr, 4),
        "results": results,
        "generated_at": _now(),
        "methodology": (
            "Each detector is run against a labeled benchmark dataset of known-positive and "
            "known-negative cases. Precision = TP/(TP+FP), Recall = TP/(TP+FN), "
            "FPR = FP/(FP+TN). These are the 'known error rates' the Daubert standard requires."
        ),
    }


# ── Built-in benchmarks (registered at import) ──────────────────────────────

def _register_builtin_benchmarks() -> None:
    """Register benchmarks for CrypTX's detectors using synthetic fixtures."""

    # 1. Address-poisoning detector (laundering_trace.detect_poisoning).
    try:
        import laundering_trace as lt

        def poisoning_detector(inp: dict[str, Any]) -> bool:
            hits = lt.detect_poisoning(inp.get("transfers", []), inp.get("victim_address", ""))
            return len(hits) > 0

        poisoning_cases = [
            # Positive: dust transfer from a lookalike address.
            BenchmarkCase(
                input={"transfers": [
                    {"from": "0xabc123def456", "to": "0xREAL_VICTIM", "value": 0, "token": "USDT"},
                ], "victim_address": "0xREAL_VICTIM"},
                expected=True,
                label="dust transfer from lookalike address",
            ),
            BenchmarkCase(
                input={"transfers": [
                    {"from": "0xabc123def456", "to": "0xREAL_VICTIM", "value": 0, "token": "USDT"},
                ], "victim_address": "0xREAL_VICTIM"},
                expected=True,
                label="zero-value transfer",
            ),
            # Negative: normal transfer with real value.
            BenchmarkCase(
                input={"transfers": [
                    {"from": "0xnormal", "to": "0xREAL_VICTIM", "value": 500, "token": "USDT"},
                ], "victim_address": "0xREAL_VICTIM"},
                expected=False,
                label="normal value transfer",
            ),
        ]
        register_benchmark("address_poisoning", poisoning_detector, poisoning_cases)
    except Exception:
        pass

    # 2. Memecoin sniper detection.
    try:
        import memecoin_forensics as mf

        def memecoin_sniper_detector(inp: dict[str, Any]) -> bool:
            result = mf.analyze_memecoin(
                inp.get("token", "T"),
                inp.get("transfers", []),
                launch_timestamp=inp.get("launch_ts"),
            )
            return result["summary"]["sniper_count"] > 0

        launch = 1700000000
        memecoin_cases = [
            BenchmarkCase(
                input={"token": "A", "transfers": [
                    {"from": "0xs", "to": "0xb1", "amount": 100, "timestamp": launch + 5},
                    {"from": "0xs", "to": "0xb2", "amount": 100, "timestamp": launch + 8},
                ], "launch_ts": launch},
                expected=True,
                label="sniper buys within launch window",
            ),
            BenchmarkCase(
                input={"token": "B", "transfers": [
                    {"from": "0xdex", "to": "0xb1", "amount": 100, "timestamp": launch + 600},
                ], "launch_ts": launch},
                expected=False,
                label="organic buys after launch window",
            ),
        ]
        register_benchmark("memecoin_sniper", memecoin_sniper_detector, memecoin_cases)
    except Exception:
        pass

    # 3. Rule engine condition evaluator.
    try:
        import rule_engine as re_

        def rule_evaluator(inp: dict[str, Any]) -> bool:
            matched, _ = re_.evaluate_rule(
                inp.get("conditions", []),
                inp.get("operator", "AND"),
                inp.get("context", {}),
            )
            return matched

        rule_cases = [
            BenchmarkCase(
                input={"conditions": [{"field": "usd_value", "op": "gt", "value": 50000}],
                       "operator": "AND", "context": {"usd_value": 60000}},
                expected=True,
                label="value above threshold matches",
            ),
            BenchmarkCase(
                input={"conditions": [{"field": "usd_value", "op": "gt", "value": 50000}],
                       "operator": "AND", "context": {"usd_value": 30000}},
                expected=False,
                label="value below threshold does not match",
            ),
        ]
        register_benchmark("rule_engine", rule_evaluator, rule_cases)
    except Exception:
        pass


# Register built-ins on import.
_register_builtin_benchmarks()
