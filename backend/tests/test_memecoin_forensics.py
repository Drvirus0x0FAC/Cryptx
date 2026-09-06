"""Smoke tests for memecoin insider-network forensics (P2.1)."""
import memecoin_forensics as mf

LAUNCH = 1700000000


def _transfer(frm, to, amount, ts, tx="", block=""):
    return {"from": frm, "to": to, "amount": amount, "timestamp": ts, "tx_hash": tx, "block": block}


def test_empty_transfers_returns_unknown():
    result = mf.analyze_memecoin("TOKEN123", [])
    assert result["risk_level"] == "UNKNOWN"
    assert result["risk_score"] == 0


def test_clean_token_low_risk():
    """A token with gradual organic buying over time → LOW risk."""
    transfers = []
    for i in range(20):
        buyer = f"0xbuyer{i}"
        transfers.append(_transfer(f"0xdex", buyer, 100, LAUNCH + 600 + i * 60))  # buys start 10 min after launch
    result = mf.analyze_memecoin("CLEAN", transfers, launch_timestamp=LAUNCH)
    assert result["risk_level"] == "LOW"
    assert result["risk_score"] < 20


def test_sniper_cluster_detected():
    """3+ wallets buying within 2 min of launch from the same seller → cluster."""
    seller = "0xSELLER"
    transfers = [
        _transfer(seller, "0xsnipe1", 1000, LAUNCH + 5),
        _transfer(seller, "0xsnipe2", 1000, LAUNCH + 8),
        _transfer(seller, "0xsnipe3", 1000, LAUNCH + 12),
        _transfer(seller, "0xsnipe4", 1000, LAUNCH + 20),
        # organic buys later
        _transfer("0xdex", "0xbuyer1", 50, LAUNCH + 600),
        _transfer("0xdex", "0xbuyer2", 50, LAUNCH + 1200),
    ]
    result = mf.analyze_memecoin("SNIPE", transfers, launch_timestamp=LAUNCH)
    assert result["summary"]["sniper_count"] == 4
    assert len(result["clusters"]) >= 1
    assert result["clusters"][0]["funder"] == seller
    assert result["clusters"][0]["member_count"] == 4
    assert result["risk_level"] in ("HIGH", "CRITICAL", "MODERATE")


def test_coordinated_dump_detected():
    """Sniper cluster that dumps within a 10-min window → coordinated."""
    seller = "0xSELLER"
    transfers = [
        # Buy phase (first 2 min)
        _transfer(seller, "0xsnipe1", 1000, LAUNCH + 5),
        _transfer(seller, "0xsnipe2", 1000, LAUNCH + 8),
        _transfer(seller, "0xsnipe3", 1000, LAUNCH + 10),
        # Dump phase (all within 5 minutes of each other)
        _transfer("0xsnipe1", "0xdex", 1000, LAUNCH + 3600),
        _transfer("0xsnipe2", "0xdex", 1000, LAUNCH + 3720),
        _transfer("0xsnipe3", "0xdex", 1000, LAUNCH + 3840),
    ]
    result = mf.analyze_memecoin("DUMP", transfers, launch_timestamp=LAUNCH)
    coordinated = [c for c in result["clusters"] if c.get("coordinated_dump_detected")]
    assert len(coordinated) >= 1
    assert result["risk_level"] in ("HIGH", "CRITICAL")


def test_bundled_launch_detected():
    """3+ buys in the same block within launch window → bundled."""
    transfers = [
        _transfer("0xdeploy", "0xb1", 500, LAUNCH + 2, block="blk1"),
        _transfer("0xdeploy", "0xb2", 500, LAUNCH + 2, block="blk1"),
        _transfer("0xdeploy", "0xb3", 500, LAUNCH + 2, block="blk1"),
    ]
    result = mf.analyze_memecoin("BUNDLE", transfers, launch_timestamp=LAUNCH)
    assert result["summary"]["bundled_blocks"] >= 1


def test_deployer_sells_flagged():
    """Deployer selling tokens → deployer_sold signal."""
    transfers = [
        _transfer("0xdex", "0xdeploy", 10000, LAUNCH + 10),
        _transfer("0xdeploy", "0xdex", 5000, LAUNCH + 3600, tx="sell1"),
    ]
    result = mf.analyze_memecoin("RUG", transfers, deployer="0xdeploy", launch_timestamp=LAUNCH)
    deployer_signals = [s for s in result["signals"] if s.get("signal") == "deployer_sold"]
    assert len(deployer_signals) == 1
    assert deployer_signals[0]["evidence"][0]["tx_hash"] == "sell1"


def test_deployer_funds_snipers_flagged():
    """Deployer who funds the sniper cluster → insider network signal."""
    deployer = "0xDEPLOYER"
    transfers = [
        _transfer(deployer, "0xs1", 1000, LAUNCH + 3),
        _transfer(deployer, "0xs2", 1000, LAUNCH + 5),
        _transfer(deployer, "0xs3", 1000, LAUNCH + 7),
    ]
    result = mf.analyze_memecoin("INSIDER", transfers, deployer=deployer, launch_timestamp=LAUNCH)
    insider_signals = [s for s in result["signals"] if s.get("signal") == "deployer_funds_snipers"]
    assert len(insider_signals) == 1


def test_risk_score_capped_at_100():
    """Even with every red flag, score never exceeds 100."""
    deployer = "0xDEPLOYER"
    transfers = []
    # Many snipers from deployer
    for i in range(20):
        transfers.append(_transfer(deployer, f"0xs{i}", 1000, LAUNCH + i, block="blk1" if i < 5 else ""))
    # Coordinated dump
    for i in range(20):
        transfers.append(_transfer(f"0xs{i}", "0xdex", 1000, LAUNCH + 3600 + i * 5))
    # Deployer sells
    transfers.append(_transfer(deployer, "0xdex", 99999, LAUNCH + 7200))
    result = mf.analyze_memecoin("MAXRISK", transfers, deployer=deployer, launch_timestamp=LAUNCH)
    assert result["risk_score"] <= 100
    assert result["risk_level"] == "CRITICAL"


def test_signals_have_evidence():
    """Every signal includes data/evidence for court-defensibility."""
    seller = "0xSELLER"
    transfers = [
        _transfer(seller, "0xs1", 1000, LAUNCH + 5),
        _transfer(seller, "0xs2", 1000, LAUNCH + 8),
        _transfer(seller, "0xs3", 1000, LAUNCH + 10),
    ]
    result = mf.analyze_memecoin("EVID", transfers, launch_timestamp=LAUNCH)
    for signal in result["signals"]:
        assert "data" in signal or "evidence" in signal
        assert "description" in signal
