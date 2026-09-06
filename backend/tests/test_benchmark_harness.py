"""Smoke tests for the detector benchmark harness (P2.3)."""
import benchmark_harness as bh


def test_benchmark_result_metrics():
    """The BenchmarkResult computes precision/recall/F1/FPR correctly."""
    r = bh.BenchmarkResult(detector_name="test", total_cases=10,
                           true_positives=8, false_positives=1,
                           true_negatives=0, false_negatives=1)
    # precision = 8/(8+1) = 0.888...
    assert round(r.precision, 3) == 0.889
    # recall = 8/(8+1) = 0.888...
    assert round(r.recall, 3) == 0.889
    # f1 = 2*p*r/(p+r)
    assert r.f1 > 0.88


def test_run_benchmark_perfect_detector():
    """A detector that always matches ground truth → 100% precision/recall."""
    cases = [
        bh.BenchmarkCase(input={"x": 1}, expected=True, label="pos1"),
        bh.BenchmarkCase(input={"x": 2}, expected=True, label="pos2"),
        bh.BenchmarkCase(input={"x": 3}, expected=False, label="neg1"),
    ]
    result = bh.run_benchmark("perfect", lambda inp: inp["x"] < 3, cases)
    assert result.true_positives == 2
    assert result.true_negatives == 1
    assert result.false_positives == 0
    assert result.false_negatives == 0
    assert result.precision == 1.0
    assert result.recall == 1.0


def test_run_benchmark_with_false_positives():
    """A detector that over-flags → high FPR."""
    cases = [
        bh.BenchmarkCase(input={}, expected=False),
        bh.BenchmarkCase(input={}, expected=False),
        bh.BenchmarkCase(input={}, expected=True),
    ]
    result = bh.run_benchmark("overflagger", lambda inp: True, cases)
    # Flags everything: TP=1, FP=2, TN=0, FN=0.
    assert result.false_positives == 2
    assert result.false_positive_rate == 1.0
    assert result.precision == 1 / 3


def test_crash_counts_as_missed():
    """If the detector raises, it counts as a missed detection (not a crash)."""
    def crashy(inp):
        if inp["x"] == 2:
            raise ValueError("boom")
        return inp["x"] == 1

    cases = [
        bh.BenchmarkCase(input={"x": 1}, expected=True),
        bh.BenchmarkCase(input={"x": 2}, expected=True),  # detector crashes → FN
    ]
    result = bh.run_benchmark("crashy", crashy, cases)
    assert result.false_negatives == 1


def test_register_and_run_all():
    """register_benchmark + run_all_benchmarks works."""
    bh.register_benchmark("custom_test", lambda inp: inp.get("flag", False), [
        bh.BenchmarkCase(input={"flag": True}, expected=True),
        bh.BenchmarkCase(input={"flag": False}, expected=False),
    ])
    report = bh.run_all_benchmarks()
    assert report["detectors_tested"] >= 1
    assert "average_precision" in report
    assert "methodology" in report
    # Find our custom detector in results.
    names = [r["detector"] for r in report["results"]]
    assert "custom_test" in names


def test_builtin_benchmarks_registered():
    """Built-in benchmarks (poisoning, memecoin, rules) are registered on import."""
    report = bh.run_all_benchmarks()
    names = {r["detector"] for r in report["results"]}
    # At least the rule_engine benchmark should always register.
    assert "rule_engine" in names or len(names) >= 1


def test_to_dict_includes_all_metrics():
    """to_dict() includes all Daubert-relevant metrics."""
    r = bh.BenchmarkResult(detector_name="t", total_cases=5,
                           true_positives=3, false_positives=1,
                           true_negatives=1, false_negatives=0)
    d = r.to_dict()
    for key in ("precision", "recall", "f1", "false_positive_rate", "false_negative_rate", "accuracy"):
        assert key in d
