"""Smoke tests for the NFT flow adapter (P1.9)."""
import nft_flow_adapter as nfa


def test_opensea_sale_event_converts_to_holistic():
    """A 'successful' (sale) OpenSea event becomes an nft_sale holistic event."""
    opensea_result = {
        "events": [
            {
                "event_type": "successful",
                "from_address": "0xTHIEF",
                "to_address": "0xBUYER",
                "price": 5.0,
                "currency": "ETH",
                "collection_slug": "bored-ape-yacht-club",
                "asset_token_id": "1234",
                "transaction_hash": "0xabc",
                "created_date": "2024-01-15T10:30:00",
            }
        ]
    }
    events = nfa.opensea_events_to_holistic(opensea_result, "0xTHIEF")
    assert len(events) == 1
    e = events[0]
    assert e["chain"] == "eth"
    assert e["from"] == "0xthief"
    assert e["to"] == "0xbuyer"
    assert e["kind"] == "nft_sale"
    assert e["value"] == 5.0
    assert "bored-ape-yacht-club" in e["asset"]
    assert e["asset"].startswith("NFT:")
    assert e["tx_hash"] == "0xabc"
    assert e["timestamp"] > 0


def test_opensea_transfer_event_converts():
    """A plain 'transfer' event (no price) becomes an nft_transfer event."""
    opensea_result = {
        "events": [
            {
                "event_type": "transfer",
                "from_address": "0xA",
                "to_address": "0xB",
                "price": 0.0,
                "collection_slug": "azuki",
                "asset_token_id": "99",
            }
        ]
    }
    events = nfa.opensea_events_to_holistic(opensea_result, "0xA")
    assert len(events) == 1
    assert events[0]["kind"] == "nft_transfer"
    assert events[0]["value"] == 0.0


def test_non_movement_events_skipped():
    """Events like 'offer' or 'cancel' don't represent NFT movement — skip them."""
    opensea_result = {
        "events": [
            {"event_type": "offer", "from_address": "0xA", "to_address": "0xB"},
            {"event_type": "cancel", "from_address": "0xA", "to_address": "0xB"},
            {"event_type": "successful", "from_address": "0xA", "to_address": "0xB", "price": 1.0},
        ]
    }
    events = nfa.opensea_events_to_holistic(opensea_result, "0xA")
    assert len(events) == 1  # only the successful sale


def test_events_without_endpoints_skipped():
    """Events missing from/to can't form an edge — skip."""
    opensea_result = {
        "events": [
            {"event_type": "transfer", "from_address": "", "to_address": "0xB"},
            {"event_type": "transfer", "from_address": "0xA", "to_address": ""},
        ]
    }
    events = nfa.opensea_events_to_holistic(opensea_result, "0xA")
    assert len(events) == 0


def test_reservoir_holdings_convert_to_holding_events():
    """Reservoir holdings become 'holding' events from contract to subject."""
    reservoir_result = {
        "tokens": [
            {"token": {"collection": {"name": "Pudgy Penguins", "id": "0xCONTRACT1"}, "tokenId": "42"}},
            {"token": {"collection": {"name": "Doodles", "id": "0xCONTRACT2"}, "tokenId": "7"}},
        ]
    }
    events = nfa.reservoir_transfers_to_holistic(reservoir_result, "0xSUBJECT")
    assert len(events) == 2
    for e in events:
        assert e["to"] == "0xsubject"
        assert e["kind"] == "nft_holding"
        assert e["asset"].startswith("NFT:")
    collections = {e["collection"] for e in events}
    assert "Pudgy Penguins" in collections
    assert "Doodles" in collections


def test_empty_opensea_returns_empty():
    events = nfa.opensea_events_to_holistic({}, "0xA")
    assert events == []


def test_empty_reservoir_returns_empty():
    events = nfa.reservoir_transfers_to_holistic({}, "0xA")
    assert events == []


def test_timestamp_parsing():
    assert nfa._parse_timestamp("2024-01-15T10:30:00") > 0
    assert nfa._parse_timestamp("2024-01-15T10:30:00Z") > 0
    assert nfa._parse_timestamp("") == 0
    assert nfa._parse_timestamp("garbage") == 0
