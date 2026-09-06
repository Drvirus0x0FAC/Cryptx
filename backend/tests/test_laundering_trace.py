"""Golden-file tests — laundering_trace detectors (B1 swap continuation, B2 poisoning)."""
import laundering_trace as lt

from tests.synthetic import poisoning_case, swap_case, SUBJECT, THOR_ROUTER
from tests.golden import check_golden


def test_poisoning_detects_lookalike_dust():
    case = poisoning_case(True, seed=1)
    r = lt.detect_address_poisoning(case["subject"], case["transfers"])
    assert r["poisoning_hits"], "look-alike dust must be flagged"
    hit = r["poisoning_hits"][0]
    assert hit["poison_address"].lower().startswith(hit["spoofs"].lower()[:8])
    check_golden("poisoning_positive", r)


def test_poisoning_ignores_random_dust():
    case = poisoning_case(False, seed=1)
    r = lt.detect_address_poisoning(case["subject"], case["transfers"])
    assert r["poisoning_hits"] == [], "random dust must NOT be flagged"
    assert r["inbound_dust_transfers"] >= 1  # the dust was seen, just not look-alike


def test_poisoning_requires_dust_value():
    # A look-alike sender moving REAL value is not poisoning (it's a transfer)
    case = poisoning_case(True, seed=2)
    for t in case["transfers"]:
        if t["value_usd"] == 0.0:
            t["value_usd"] = 250.0
    r = lt.detect_address_poisoning(case["subject"], case["transfers"])
    assert r["poisoning_hits"] == []


def test_swap_continuation_matches_output():
    case = swap_case(True, seed=1)
    r = lt.detect_swap_continuation(case["subject"], case["transfers"],
                                    candidate_outputs=case["outputs"])
    assert r["entry_count"] == 1
    assert r["swap_entries"][0]["service"] == "THORChain"
    assert r["continuation_matches"], "value/time-window re-match must fire"
    m = r["continuation_matches"][0]
    assert m["output_tx"] == f"0xout{1}"          # the decoy (3.5x value) must lose
    check_golden("swap_continuation_positive", r)


def test_swap_continuation_negative():
    case = swap_case(False, seed=1)
    r = lt.detect_swap_continuation(case["subject"], case["transfers"],
                                    candidate_outputs=case["outputs"])
    assert r["entry_count"] == 0
    assert r["continuation_matches"] == []


def test_service_catalog_covers_2026_exchangers():
    cat = lt.services_catalog()
    labels = {s.get("label", "").lower() for s in cat.get("services", [])} if isinstance(cat.get("services"), list) \
        else {str(k).lower() for k in cat}
    joined = str(cat).lower()
    for svc in ("fixedfloat", "thorchain", "chainflip"):
        assert svc in joined, f"{svc} missing from service catalog"
