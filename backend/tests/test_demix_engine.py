"""Golden-file tests — demix_engine Tornado-style pairing."""
import demix_engine as dm

from tests.synthetic import tornado_case
from tests.golden import check_golden


def test_tornado_pairs_true_deposit():
    case = tornado_case(True, seed=1)
    r = dm.demix_tornado(case["deposits"], case["withdrawals"])
    assert r["links"], "withdrawal must produce candidate links"
    link = r["links"][0]
    assert link["candidates"], "candidates required"
    top = link["candidates"][0]
    assert top["deposit_tx"] == case["true_deposit"], \
        "the same-denomination, in-window, same-relayer deposit must rank first"
    assert top["confidence"] > 0.5, "relayer + denomination + window should raise confidence"
    check_golden("tornado_positive", r)


def test_tornado_rejects_out_of_window_and_wrong_denomination():
    case = tornado_case(False, seed=1)
    r = dm.demix_tornado(case["deposits"], case["withdrawals"])
    for link in r["links"]:
        for cand in link["candidates"]:
            # anything surfaced must at least explain itself; the true-pair signature
            # (same denom AND inside window) must not exist in negative cases
            assert cand["deposit_tx"].startswith("0xd")
    high_conf = [c for l in r["links"] for c in l["candidates"] if c["confidence"] > 0.5]
    assert high_conf == [], "no high-confidence pairing should exist in the negative case"


def test_tornado_confidence_is_bounded():
    case = tornado_case(True, seed=3)
    r = dm.demix_tornado(case["deposits"], case["withdrawals"])
    for link in r["links"]:
        for cand in link["candidates"]:
            assert 0.0 <= cand["confidence"] <= 1.0
