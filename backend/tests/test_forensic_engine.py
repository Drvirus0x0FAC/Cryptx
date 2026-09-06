"""Golden-file tests — forensic_engine motifs + taint propagation."""
import forensic_engine as fe

from tests.synthetic import fanout_case, SUBJECT
from tests.golden import check_golden


def _motifs(case):
    feats = fe.behavior_fingerprint({"address": case["subject"]}, case["edges"])
    return fe.detect_motifs(case["edges"], feats, case["subject"])


def test_fan_out_dispersal_detected():
    case = fanout_case(True, seed=1)
    patterns = {m["pattern"] for m in _motifs(case)}
    assert "fan_out_dispersal" in patterns
    check_golden("fanout_positive", sorted(patterns))


def test_low_degree_wallet_not_flagged_as_fanout():
    case = fanout_case(False, seed=1)
    patterns = {m["pattern"] for m in _motifs(case)}
    assert "fan_out_dispersal" not in patterns


def test_motif_confidence_bounded():
    case = fanout_case(True, seed=2)
    for m in _motifs(case):
        assert 0.0 <= m.get("confidence", 0) <= 1.0


def test_taint_flow_propagates_forward():
    edges = [
        {"source": SUBJECT, "target": "0xhop1" + "0" * 34, "value": 100, "token": "ETH", "timestamp": 1},
        {"source": "0xhop1" + "0" * 34, "target": "0xhop2" + "0" * 34, "value": 90, "token": "ETH", "timestamp": 2},
    ]
    t = fe.taint_flow(SUBJECT, edges, max_depth=4)
    assert isinstance(t, dict)
    tainted = str(t).lower()
    assert "0xhop2" in tainted, "taint must reach the second hop"
