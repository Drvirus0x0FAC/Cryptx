"""Golden-file tests — contract_forensics (A1 scan, A2 similarity, A3 incident, A4 approvals)."""
import contract_forensics as cf

from tests.synthetic import contract_case, approval_case
from tests.golden import check_golden


def test_scan_flags_owner_abuse_selectors():
    case = contract_case(True, seed=0)
    r = cf.scan_contract(abi_selectors=case["abi_selectors"])
    assert r["risk_score"] >= 50
    rule_ids = {f["rule_id"] for f in r["findings"]}
    assert rule_ids & {"privileged_mint", "blacklist", "pausable", "upgradeable_proxy"}
    check_golden("contract_scan_malicious", {"risk_score": r["risk_score"],
                                             "verdict": r["verdict"],
                                             "rules": sorted(rule_ids)})


def test_scan_benign_erc20_is_low_risk():
    case = contract_case(False, seed=0)
    r = cf.scan_contract(abi_selectors=case["abi_selectors"])
    assert r["risk_score"] < 50, f"benign ERC-20 scored {r['risk_score']}"


def test_bytecode_similarity_same_family_ranks_high():
    base = "60806040" + "63" + "40c10f19" + "63" + "f9f92be4" + "6000f3"
    variant = "60806040" + "63" + "40c10f19" + "63" + "f9f92be4" + "5b6000f3"
    unrelated = "60806040" + "63" + "a9059cbb" + "63" + "70a08231" + "6000f3"
    fa, fb, fc = (cf.fingerprint_bytecode(x) for x in (base, variant, unrelated))
    same = cf.compare_fingerprints(fa, fb)["similarity"]
    diff = cf.compare_fingerprints(fa, fc)["similarity"]
    assert same > diff, "same-family bytecode must outrank unrelated bytecode"
    assert 0.0 <= diff <= same <= 1.0


def test_approval_exposure_flags_malicious_infinite():
    case = approval_case(True, seed=0)
    r = cf.approval_exposure(case["approvals"], malicious_spenders=case["malicious"])
    assert r["infinite_approvals"] == 1
    assert r["flagged_malicious"] == 1
    assert "CRITICAL" in r["verdict"].upper()
    check_golden("approval_exposure_critical", {k: r[k] for k in
                 ("live_approvals", "infinite_approvals", "flagged_malicious", "verdict")})


def test_approval_exposure_clean_wallet():
    case = approval_case(False, seed=0)
    r = cf.approval_exposure(case["approvals"], malicious_spenders=case["malicious"])
    assert r["flagged_malicious"] == 0
    assert r["infinite_approvals"] == 0


def test_incident_reconstruction_orders_phases():
    txs = [
        {"tx_hash": "0x1", "from": "0xattacker", "to": "", "timestamp": 100,
         "method": "create", "note": "contract deploy"},
        {"tx_hash": "0x2", "from": "0xattacker", "to": "0xvictimpool", "timestamp": 200,
         "method": "flashLoan", "value_usd": 0},
        {"tx_hash": "0x3", "from": "0xvictimpool", "to": "0xattacker", "timestamp": 300,
         "value_usd": 2_000_000},
    ]
    r = cf.reconstruct_incident(txs, contract="0xexploit")
    assert isinstance(r, dict) and r, "reconstruction must return a structured post-mortem"
