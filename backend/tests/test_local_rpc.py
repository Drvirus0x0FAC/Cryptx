"""Smoke tests for the local RPC fetcher (P2.4 — air-gap mode).

These test the pure helpers (topic parsing, hex conversion, config resolution)
without requiring a live Ethereum node. The actual RPC calls are integration-
tested against a real node in deployment.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_rpc_fetcher as lrf


def test_hex_to_int():
    assert lrf._hex_to_int("0x1") == 1
    assert lrf._hex_to_int("0xde0b6b3a7640000") == 10**18
    assert lrf._hex_to_int("") == 0
    assert lrf._hex_to_int(None) == 0
    assert lrf._hex_to_int("garbage") == 0


def test_topic_to_address():
    """Extract a 20-byte address from a 32-byte topic."""
    topic = "0x00000000000000000000000028c6c06298d514db089934071355e5743bf21d60"
    addr = lrf._topic_to_address(topic)
    assert addr == "0x28c6c06298d514db089934071355e5743bf21d60"


def test_topic_to_address_short():
    assert lrf._topic_to_address("") == ""
    assert lrf._topic_to_address("0x123") == ""


def test_transfer_topic_constant():
    """The Transfer event topic is the well-known keccak256 hash."""
    assert lrf.TRANSFER_TOPIC == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def test_rpc_url_resolution():
    """Config resolution returns the right URL per chain."""
    # With no config, returns empty.
    old = dict(os.environ)
    os.environ.pop("LOCAL_RPC_URLS", None)
    os.environ.pop("ETH_RPC_URL", None)
    import importlib
    import config
    importlib.reload(config)
    lrf_config = config
    assert not lrf_config.LOCAL_RPC_URLS
    assert not lrf_config.LOCAL_RPC_ENABLED
    os.environ.clear()
    os.environ.update(old)


def test_rpc_url_from_json_map():
    """JSON map config resolves per-chain URLs."""
    import json
    old = dict(os.environ)
    os.environ["LOCAL_RPC_URLS"] = json.dumps({"eth": "http://node1:8545", "base": "http://node2:8545"})
    import importlib
    import config
    importlib.reload(config)
    assert config.LOCAL_RPC_ENABLED
    assert config.LOCAL_RPC_URLS.get("eth") == "http://node1:8545"
    assert config.LOCAL_RPC_URLS.get("base") == "http://node2:8545"
    os.environ.clear()
    os.environ.update(old)


def test_rpc_url_single_string():
    """A single URL string maps to eth."""
    old = dict(os.environ)
    os.environ["LOCAL_RPC_URLS"] = "http://localhost:8545"
    import importlib
    import config
    importlib.reload(config)
    assert config.LOCAL_RPC_URLS.get("eth") == "http://localhost:8545"
    os.environ.clear()
    os.environ.update(old)


def test_eth_rpc_url_legacy():
    """ETH_RPC_URL (legacy single-chain) still works."""
    old = dict(os.environ)
    os.environ["ETH_RPC_URL"] = "http://legacy:8545"
    os.environ.pop("LOCAL_RPC_URLS", None)
    import importlib
    import config
    importlib.reload(config)
    assert config.LOCAL_RPC_URLS.get("eth") == "http://legacy:8545"
    os.environ.clear()
    os.environ.update(old)
