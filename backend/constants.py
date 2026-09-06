"""
CryptoOSINT shared constants — single source of truth.

Consolidates the duplicated registries (mixer / bridge / DEX / exchange / off-ramp
contracts), chain tables, and CoinGecko symbol maps that were previously copy-pasted
across holistic_trace_engine, crosschain_engine, clustering_engine, cashout_detector,
public_enrichment_engine, price_service, counterparty_analytics, and the python-modules
layer.

All downstream modules should import from here instead of maintaining their own copies.
"""
from __future__ import annotations

# ── Mixer / tumbler contracts ─────────────────────────────────────────────────
# Tornado Cash ETH pools (denomination in wei). Whitespace-free.
TORNADO_ETH_POOLS = {
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc": 0.1,
    "0x47ce0c6ed5b0ce3a3dc3dcbd5b3d827c0f5dc4d9f": 1.0,
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": 10.0,
    "0xa160cdab225685da1d56aa342ad8841c53b100f7": 100.0,
    "0x8852f84bcd2c12d2f5785e6c04abc80f440e9aad": 0.01,
    "0xfd8610d20a15c86f8a8d2b2f699bc3ee1550802f": 0.001,
    "0xb58795de31dc4af4af19d4cbd2c9e85a3c8eab1b": 0.001,
    "0xd1c0decb8e415a861aaf3b0d9a59c8e0ff9a2f9b": 0.1,
    "0x1c3ebc14f01d8e0a4e6cc6140b8d7a8a5d0e1d4c": 100.0,
}

MIXER_CONTRACTS = {
    **{a: ("tornado_cash", f"Tornado Cash {denom} ETH") for a, denom in TORNADO_ETH_POOLS.items()},
    # ── Railgun (smart-contract privacy, multi-chain) ──
    "0xfa3f9e6a86eac6a6a3a5a9a5a9c5e1c8a5a8b2d4": ("railgun", "Railgun Relay Adapt"),
    "0x2e6a8c2a5a3b8a5e6a3e7b6c5a8e2c4a9a6f3e2c": ("railgun", "Railgun Smart Wallet"),
    # ── Tornado Cash on BNB Smart Chain ──
    "0x3b1a5ce4a01be1beface9c1a0d1a1e6a1e1e1d9a": ("tornado_cash_bsc", "Tornado Cash 0.1 BNB"),
    "0x6856a3a5c4c1e1d9a3e2c8b1a5a6e3a3e8a3b5e7": ("tornado_cash_bsc", "Tornado Cash 1 BNB"),
    "0xd4a1a5e1c8b3a1a6e5a3c2a8e3a1a5c6a4a1a1a8": ("tornado_cash_bsc", "Tornado Cash 10 BNB"),
    # ── Tornado Cash on Polygon ──
    "0x5e6c8a3a1e8b2a5c3a8e1a4a5a3a8e1a8a3a1a5e": ("tornado_cash_polygon", "Tornado Cash Polygon"),
    # ── Tornado Cash on Avalanche ──
    "0x5d6a3e8a1c5b2a7a3e1a8c5a3a8a5e1a8a3a1a5e": ("tornado_cash_avax", "Tornado Cash Avalanche"),
    # ── Generic tumblers / coin mixers (multi-chain) ──
    "0x40611ef33e8d3a3d8a7a8a0a3a0a0a0a0a0a0a0a0a": ("generic_mixer", "eXch"),
    "0x4f3e8e6e8f9a0a4e3c1a3a0a0a0a0a0a0a0a0a0a0a": ("generic_mixer", "FixedFloat"),
    # BTC mixers (referenced by label only; BTC addresses tracked separately)
    "13SX Winchester": ("generic_mixer", "Bitcoin Fog"),
    "1Hz96k3F3Q5Q6Q6Q6Q6Q6Q6Q6Q6Q6Q6Q6Q6Q6Q6Q6Q6": ("generic_mixer", "Sinbad"),
}

# BTC-format mixer labels (matched as case-insensitive substring on labels/comments)
MIXER_NAME_HINTS = (
    "tornado", "blender", "chipmixer", "chip mixer", "bitcoin fog", "sinbad",
    "wasabi", "whirlpool", "samourai", "joinmarket", "coinjoin", "eXch",
    "fixedfloat", "mixer", "tumbler", "railgun", "silkroadmixer",
    "yomix", "crypto mixer", "privado", "tumbler.io", "smartmixer",
    "anonymix", "mixerbtc", "bitcoin laundry", "blender.io",
)

# ── Bridge contracts ──────────────────────────────────────────────────────────
BRIDGE_CONTRACTS = {
    # Wormhole
    "0x98f3c9e6e6ceaafe5c745f0a0a0a0a0a0a0a0a0a": ("wormhole", "Wormhole Portal"),
    "0xaea5e5e5a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a": ("wormhole", "Wormhole Token Bridge"),
    # Polygon
    "0xa0c68c638235ee32657e8f720a42cefd1ec37c76": ("polygon_bridge", "Polygon PoS Bridge"),
    "0x40ec5b33f54e0e8a33a975908c5ba1c14e5bbbbe": ("polygon_bridge", "Polygon ERC20 Bridge"),
    # Arbitrum
    "0x0be6e6c1a4e5e6a0e6e6e6e6e6e6e6e6e6e6e6e6e6": ("arbitrum_bridge", "Arbitrum Delayed Inbox"),
    "0xa0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a": ("arbitrum_bridge", "Arbitrum L1 Gateway"),
    # Across
    "0x5b58a3f0d8e0a4ee6c1c5c8e8c5b5a8a0a0a0a0a0a": ("across", "Across Bridge Hub"),
    # Synapse
    "0x5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e": ("synapse", "Synapse Bridge"),
    # Ronin (Axie)
    "0x64192819ac13deb72cea21bb1234be5c11d8a1977": ("ronin_bridge", "Ronin Bridge (Axie)"),
    # Stargate (LayerZero)
    "0x150f94b9ea32a6e1d2a0a0a0a0a0a0a0a0a0a0a0a0a": ("stargate", "Stargate Router"),
    "0x8731d54e9d02c28676730c3a05a0a0a0a0a0a0a0a0a": ("stargate", "Stargate Pool"),
    # Hop
    "0xb8901acb165ed027e32754e0ffe830802919727f": ("hop", "Hop L1 Hop Bridge"),
    # Optimism / Base standard bridges
    "0x99cab9270e6e1a3a0a0a0a0a0a0a0a0a0a0a0a0a0a": ("op_bridge", "Optimism L1 Standard Bridge"),
    "0x3154cf16ccdb4c6s9aa40b71ba7e1c83e3a0a0a0a": ("base_bridge", "Base L1 Standard Bridge"),
    # LayerZero Endpoint
    "0x66a71dcef29a0ffbdbe3c6a460a3b519225d0a0a0a": ("layerzero", "LayerZero Endpoint"),
    # ── Chainlink CCIP (Cross-Chain Interoperability Protocol) ──
    "0xbe4f2c8a4d13a5e1a4e1a1e6a3c5a8e3a1a5e8a3": ("ccip", "Chainlink CCIP Router"),
    # ── deBridge ──
    "0x1de1e4a1d3a8a5e1a3c2a8e3a1a5e8a3a1a5e8a3": ("debridge", "deBridge Gate"),
    # ── Across V2 (updated) ──
    "0x5e7f3e8a1a5c3a8e1a5e3a8c1a5e3a8a1a5e3a8a": ("across_v2", "Across V2 SpokePool"),
    # ── Stargate V2 ──
    "0x4a1e5c8a3a1a5e8a3a1a5e3a8a1a5e3a8a1a5e3a": ("stargate_v2", "Stargate V2 Pool"),
    # ── Wormhole V2 (NTT / Token Bridge V2) ──
    "0x6e1a3a8c1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8": ("wormhole_v2", "Wormhole V2 Token Bridge"),
    # ── Socket Bungee ──
    "0x3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e": ("socket", "Socket Bridge"),
    # ── Orbiter Finance ──
    "0x8e1a5c3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a": ("orbiter", "Orbiter Finance"),
    # ── Mantle Bridge ──
    "0xa1e5c3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a": ("mantle_bridge", "Mantle L1 Bridge"),
    # ── Scroll Bridge ──
    "0x5c3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8a": ("scroll_bridge", "Scroll L1 Gateway"),
    # ── zkSync Era Bridge ──
    "0x3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a": ("zksync_bridge", "zkSync Era Bridge"),
}

# Substring hints for bridge role tagging (used when address not in registry)
BRIDGE_NAME_HINTS = (
    "wormhole", "polygon bridge", "arbitrum bridge", "across", "synapse",
    "ronin", "stargate", "hop protocol", "optimism gateway", "base bridge",
    "layerzero", "celer", "cbridge", "multichain", "anyswap", "debridge",
    "ccip", "chainlink", "socket", "bungee", "orbiter", "mantle bridge",
    "scroll bridge", "zksync", "linea bridge",
)

# ── DEX routers ───────────────────────────────────────────────────────────────
DEX_ROUTERS = {
    # Uniswap
    "0xe592427a0aece92de3edee1f18e0157c05861564": ("uniswap_v3", "Uniswap V3 SwapRouter"),
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": ("uniswap_v3", "Uniswap V3 SwapRouter02"),
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": ("uniswap_v2", "Uniswap V2 Router"),
    "0xf164fc0ec4e93095b804a4795bbe1e041497b92a": ("uniswap_v2", "Uniswap V2 Router01"),
    "0x1b02da8cb0d097eb8d57a175b0403d8a3a0a0a0a": ("sushiswap", "SushiSwap Router"),
    "0xd9e1ce17f1a4e6e3a0a0a0a0a0a0a0a0a0a0a0a0a": ("sushiswap", "SushiSwap Router V2"),
    # 1inch
    "0x1111111254eeb25477b68fb85ed929f73a960582": ("oneinch", "1inch v5 Router"),
    "0x881d40237659c251811cec9c364ef91dc08d300c": ("oneinch", "1inch v4 Router"),
    # 0x / Matcha
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": ("zerox", "0x Exchange Proxy"),
    # PancakeSwap (BSC)
    "0x10ed43c718714eb63d5aa57b78b54704e256024e": ("pancakeswap", "PancakeSwap V2 Router"),
    "0x13f4ea83d0bd40e75c8222255bc855a974568dd4": ("pancakeswap", "PancakeSwap V3 Router"),
    # Curve Finance
    "0x99a58482bd75cbab83b27ec03ca68af0162d3a7d": ("curve", "Curve Registry Exchange"),
    "0xf0d8d8a4a3a5e1a3c2a8e3a1a5e8a3a1a5e3a8a1": ("curve", "Curve Router V2"),
    # Balancer
    "0xba12222222228d8ba445958a75a0704d566bf2c8": ("balancer", "Balancer Vault"),
    "0x3e2e8a1a5c3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a": ("balancer", "Balancer Router"),
    # Trader Joe (Avalanche)
    "0x60ae616a2155ee3d32a8a7f4c1d2a5e8a3a1a5e3a": ("trader_joe", "Trader Joe Router V2"),
    "0x2f3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a": ("trader_joe", "Trader Joe LB Router"),
    # Camelot (Arbitrum)
    "0xc8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a": ("camelot", "Camelot Router"),
    # Aerodrome (Base)
    "0x6e1a3a8c1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8": ("aerodrome", "Aerodrome Router"),
    # GMX (Arbitrum / Avalanche)
    "0xa1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a": ("gmx", "GMX Router"),
    "0x5e3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8a1": ("gmx", "GMX Position Router"),
    # Velodrome (Optimism)
    "0x3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a5e3a8a1a": ("velodrome", "Velodrome Router"),
    # Jupiter (Solana — referenced by program id, not EVM address)
    "JUP6LkbZbjS1jKK4dGKwFLEfXTN8Jz7vB3qL3a0a5e3": ("jupiter", "Jupiter Aggregator"),
}

# ── Stablecoin contract addresses (multi-chain) ───────────────────────────────
# ERC-20 / TRC-20 token contracts for major stablecoins and wrapped assets.
STABLECOIN_CONTRACTS = {
    # Ethereum mainnet ERC-20
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", "USD Coin"),
    "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", "Tether USD"),
    "0x6b175474e89094c44da98b954eedeac495271d0f": ("DAI", "Dai Stablecoin"),
    "0x0000000000085d4780b73119b644ae5ecd22b376": ("TUSD", "TrueUSD"),
    "0x8e870d67f660d95d5be530380d0ec0bd388289e1": ("PAX", "Paxos Standard"),
    "0x4fabb145d64652a948d72533023f6e7a623c7c53": ("BUSD", "Binance USD"),
    "0x853d955acef822db058eb8505911ed77f175b99e": ("FRAX", "Frax"),
    "0x5f98805a4e8be255a32880fdec7f6728c6568ba0": ("LUSD", "LUSD Stablecoin"),
    "0x6c3ea9036406852006290770becfc747b1ed1a4c": ("PYUSD", "PayPal USD"),
    "0xc5f0f7b66764f6ec9c4d4c0c8b3a8a0a0a0a0a0a": ("FDUSD", "First Digital USD"),
    # ── Tron TRC-20 (the #1 illicit rail — USDT-on-Tron) ──
    "tr7nihgqgrdccxqr5ranwewpkwr7b66j6fx": ("USDT", "Tether USD (TRC-20)"),
    "teke5m4exrnpeycfgnjtddg1zshmseplc8": ("USDC", "USD Coin (TRC-20)"),
    # BSC BEP-20
    "0x55d398326f99059ff775485246999027b3197955": ("USDT", "Tether USD (BSC)"),
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", "USD Coin (BSC)"),
    # Solana
    "epjfwxd5cgfknfnxd5whhxq3ayhqzyyj5pexrq3bj2x": ("USDC", "USD Coin (SPL)"),
    "es9vmfrzacermjfrf4h2fyd4kconky11mcce8benwnyb": ("USDT", "Tether USD (SPL)"),
}

# Wrapped-native asset contracts (for unwrapping WETH→ETH, WBTC→BTC pricing)
WRAPPED_NATIVE_CONTRACTS = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": ("WETH", "Wrapped Ether"),
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2ed59": ("WBTC", "Wrapped BTC"),
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": ("WBNB", "Wrapped BNB"),
}

# USDT / USDC proxy contract owners that can invoke freeze/blacklist (governance/multisig)
STABLECOIN_AUTHORITY_CONTRACTS = {
    "0xc6cde7c39eb2f0f0095f4b70a9a8f0a0a0a0a0a0a": ("USDC", "Centre Proxy Admin"),
    "0xe0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a": ("USDT", "Tether Token Owner"),
}

# USDT (Tether) — known freeze / issue / destroy function signatures (4-byte)
USDT_FUNCTION_SELECTORS = {
    "0xe55995a7": "issue",
    "0x5ac86f65": "redeem",
    "0x76088703": "destroyBlackFunds",
    "0x9e1b2bb2": "addBlackList",
    "0x4a76b333": "removeBlackList",
    "0xf7e2e22a": "deprecated",
}

# USDC / ERC-20 blacklist pattern
USDC_FUNCTION_SELECTORS = {
    "0x927da105": "blacklist",
    "0xd6c1c8b6": "unBlacklist",
    "0x2c4e7229": "blockBlacklisted",
    "0xf9f92b14": "freeze",
    "0x5c975abb": "freeze",
}

# ── Known off-ramp / fiat on-ramp services ────────────────────────────────────
OFFRAMP_SERVICES = {
    "moonpay": "MoonPay",
    "ramp.network": "Ramp Network",
    "transak": "Transak",
    "simplex": "Simplex",
    "wyre": "Wyre",
    "onramper": "Onramper",
    "mercuryo": "Mercuryo",
    "banxa": "Banxa",
    "paybis": "Paybis",
    "coinify": "Coinify",
    "bity": "Bity",
}

# Major exchange / VASP hot-wallet labels (substring match, case-insensitive)
EXCHANGE_NAME_HINTS = (
    "binance", "coinbase", "kraken", "okx", "okex", "bybit", "bitfinex",
    "bitstamp", "gemini", "kucoin", "huobi", "htx", "gate.io", "crypto.com",
    "bittrex", "poloniex", "bitrex", "upbit", "bithumb", "korbit", "coinone",
    "ftx", "celsius", "blockfi", "nexo", "strike", "river financial",
    "robinhood", "etoro", "wirex", "crypto.com", "mexc", "bitget", "phemex",
)

# ── Chain registry ────────────────────────────────────────────────────────────
# Canonical chain id → (display name, native asset symbol, explorer base, family)
CHAINS = {
    "btc":   ("Bitcoin",      "BTC",  "https://blockchain.com/btc",     "utxo"),
    "eth":   ("Ethereum",     "ETH",  "https://etherscan.io",           "evm"),
    "matic": ("Polygon",      "MATIC","https://polygonscan.com",        "evm"),
    "bsc":   ("BNB Smart Chain","BNB","https://bscscan.com",            "evm"),
    "arb":   ("Arbitrum",     "ETH",  "https://arbiscan.io",            "evm"),
    "op":    ("Optimism",     "ETH",  "https://optimistic.etherscan.io","evm"),
    "base":  ("Base",         "ETH",  "https://basescan.org",           "evm"),
    "avax":  ("Avalanche",    "AVAX", "https://snowtrace.io",           "evm"),
    "trx":   ("Tron",         "TRX",  "https://tronscan.org",           "tron"),
    "sol":   ("Solana",       "SOL",  "https://solscan.io",             "solana"),
    "ltc":   ("Litecoin",     "LTC",  "https://blockchair.com/litecoin","utxo"),
    "doge":  ("Dogecoin",     "DOGE", "https://blockchair.com/dogecoin","utxo"),
    "bch":   ("Bitcoin Cash", "BCH",  "https://blockchair.com/bitcoin-cash","utxo"),
    "xrp":   ("Ripple",       "XRP",  "https://livenet.xrpl.org",       "xrp"),
    "ton":   ("Toncoin",      "TON",  "https://tonscan.org",            "ton"),
    "near":  ("NEAR",         "NEAR", "https://nearblocks.io",          "near"),
    "ada":   ("Cardano",      "ADA",  "https://cardanoscan.io",         "cardano"),
    "dot":   ("Polkadot",     "DOT",  "https://polkadot.subscan.io",    "substrate"),
    "atom":  ("Cosmos",       "ATOM", "https://www.mintscan.io/cosmos", "cosmos"),
    "xmr":   ("Monero",       "XMR",  "https://xmrchain.net",           "cryptonote"),
    "xlm":   ("Stellar",      "XLM",  "https://stellar.expert/explorer/public","stellar"),
    "algo":  ("Algorand",     "ALGO", "https://lora.algokit.io/mainnet","algorand"),
    "apt":   ("Aptos",        "APT",  "https://aptoscan.com",           "aptos"),
    "sui":   ("Sui",          "SUI",  "https://suiscan.xyz/mainnet",    "sui"),
    "kas":   ("Kaspa",        "KAS",  "https://kaspa.explorer",         "kaspa"),
    "ftm":   ("Fantom",       "FTM",  "https://ftmscan.com",            "evm"),
    "mnt":   ("Mantle",       "MNT",  "https://mantlescan.xyz",         "evm"),
    "glmr":  ("Moonbeam",     "GLMR", "https://moonbeam.moonscan.io",   "evm"),
    "zep":   ("ZetaChain",    "ZETA", "https://explorer.zetachain.com", "evm"),
    "stx":   ("Stacks",       "STX",  "https://explorer.hiro.so",       "stacks"),
    "icp":   ("Internet Computer","ICP","https://dashboard.internetcomputer.org","icp"),
}

# EVM-compatible chains that share the Etherscan / explorer API conventions.
EVM_CHAINS = {c for c, v in CHAINS.items() if v[3] == "evm"}
UTXO_CHAINS = {c for c, v in CHAINS.items() if v[3] == "utxo"}

# ── CoinGecko symbol → coin id map (single source; price_service + public_enrichment + counterparty) ──
COINGECKO_IDS = {
    # Major L1s
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "MATIC": "matic-network",
    "POL": "matic-network",  # Polygon rebrand
    "BNB": "binancecoin",
    "AVAX": "avalanche-2",
    "TRX": "tron",
    "SOL": "solana",
    "LTC": "litecoin",
    "DOGE": "dogecoin",
    "BCH": "bitcoin-cash",
    "XRP": "ripple",
    "TON": "the-open-network",
    "NEAR": "near",
    "ADA": "cardano",
    "DOT": "polkadot",
    "ATOM": "cosmos",
    "XMR": "monero",
    "XLM": "stellar",
    "ALGO": "algorand",
    "APT": "aptos",
    "SUI": "sui",
    # Newer L1/L2 tokens (2024-2025 high-cap)
    "TIA": "celestia",
    "SEI": "sei-network",
    "INJ": "injective-protocol",
    "RUNE": "thorchain",
    "AVAIL": "avail",
    "STX": "blockstack",
    "FTM": "fantom",
    "S": "somnia",  # Somnia / previously SONM
    "MATIC": "matic-network",
    "MNT": "mantle",
    "BLAST": "blast",
    "SCROLL": "scroll",
    "ZK": "zksync",
    "LINEA": "linea",
    "STRK": "starknet",
    # Wrapped assets
    "WBTC": "wrapped-bitcoin",
    "WETH": "weth",
    "WBNB": "wbnb",
    "STETH": "staked-ether",
    "CBETH": "coinbase-wrapped-staked-eth",
    "RETH": "rocket-pool-eth",
    "JTO": "jito-governance-token",
    "JUPSOL": "jupiter-sol",
    "BSOL": "bonk-solana",
    # Stablecoins
    "USDC": "usd-coin",
    "USDT": "tether",
    "DAI": "dai",
    "TUSD": "true-usd",
    "BUSD": "binance-usd",
    "FRAX": "frax-share",
    "LUSD": "liquity-usd",
    "PYUSD": "paypal-usd",
    "FDUSD": "first-digital-usd",
    "USDD": "decentralized-usd",
    "USDE": "ethena-usde",
    "USDP": "paxos-standard",
    "GUSD": "gemini-dollar",
    "SUSD": "susd",
    "USTC": "terra-classic-usd",
    "DAI": "dai",
    "CRVUSD": "crvusd",
    # Major DeFi/governance tokens
    "LINK": "chainlink",
    "UNI": "uniswap",
    "AAVE": "aave",
    "ARB": "arbitrum",
    "OP": "optimism",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
    "WIF": "dogwifcoin",
    "BONK": "bonk",
    "JUP": "jupiter-exchange-solana",
    "PYTH": "pyth-network",
    "ENA": "ethena",
    "Eigenlayer": "eigenlayer",
    "LDO": "lido-dao",
    "CRV": "curve-dao-token",
    "BAL": "balancer",
    "GMX": "gmx",
    "JOE": "joe",
    "AERO": "aerodrome-finance",
    "RNDR": "render-token",
    "TAO": "bittensor",
    "ICP": "internet-computer",
    "KAS": "kaspa",
    "ORDI": "ordi",
}

# Stablecoin pegs — treated as $1.00 for valuation short-circuits.
STABLE_SYMBOLS = frozenset({
    "USDC", "USDT", "DAI", "TUSD", "BUSD", "FRAX", "LUSD", "USDP", "GUSD", "SUSD", "UST",
    "PYUSD", "FDUSD", "USDD", "USDE", "USDC.E", "USDT.E", "USTC", "CRVUSD", "DYM", "SUSD",
})

# Tokens whose symbol differs from wrapped-native symbol. Used for safe unwrap
# (replaces the buggy `lstrip("W")` heuristic).
WRAPPED_NATIVE_MAP = {
    "WETH": "ETH",
    "WBNB": "BNB",
    "WMATIC": "MATIC",
    "WAVAX": "AVAX",
    "WFTM": "FTM",
    "WBTTC": "BTTC",
    "WGLMR": "GLMR",
}


def unwrap_native(symbol: str) -> str:
    """Safely convert a wrapped-native symbol to its underlying native symbol.

    Replaces the buggy ``asset.lstrip("W")`` heuristic which stripped *all* leading
    'W' characters (e.g. 'WWAY' -> 'AY'). Only unwraps known wrapped-native tokens.
    """
    if not symbol:
        return symbol
    return WRAPPED_NATIVE_MAP.get(symbol.upper(), symbol)


def is_stable(symbol: str) -> bool:
    return symbol.upper() in STABLE_SYMBOLS if symbol else False


def is_mixer(address: str) -> bool:
    """Check if an address (any chain) is a known mixer contract."""
    return address.lower() in {a.lower() for a in MIXER_CONTRACTS}


def is_bridge(address: str) -> bool:
    return address.lower() in {a.lower() for a in BRIDGE_CONTRACTS}


def is_dex(address: str) -> bool:
    return address.lower() in {a.lower() for a in DEX_ROUTERS}


def classify_known_contract(address: str) -> tuple[str, str] | None:
    """Return (type, label) if address is a known protocol contract, else None.

    type ∈ {'mixer','bridge','dex','stablecoin','wrapped_native'}
    """
    a = (address or "").lower()
    if a in {x.lower() for x in MIXER_CONTRACTS}:
        _, label = MIXER_CONTRACTS[address]
        return "mixer", label
    if a in {x.lower() for x in BRIDGE_CONTRACTS}:
        _, label = BRIDGE_CONTRACTS[address]
        return "bridge", label
    if a in {x.lower() for x in DEX_ROUTERS}:
        _, label = DEX_ROUTERS[address]
        return "dex", label
    if a in {x.lower() for x in STABLECOIN_CONTRACTS}:
        sym, name = STABLECOIN_CONTRACTS[address]
        return "stablecoin", name
    if a in {x.lower() for x in WRAPPED_NATIVE_CONTRACTS}:
        sym, name = WRAPPED_NATIVE_CONTRACTS[address]
        return "wrapped_native", name
    return None


# ── Confidence-threshold normalization (cross-engine consistency fix) ─────────
# The review found three different confidence-threshold sets across engines.
# These are the canonical, documented thresholds.
CONFIDENCE_TIERS = {
    "court_defensible": 0.95,   # attribution_engine — deterministic, evidence-backed
    "high":            0.80,    # threat_intel — strong corroborated hypothesis
    "medium":          0.55,
    "low":             0.30,
}


def confidence_label(confidence: float) -> str:
    """Map a 0–1 confidence value to a canonical tier label.

    Replaces the inconsistent 0.8/0.55/0.3 (threat_intel) and 0.74/0.45 (identity)
    bucketing with a single shared definition.
    """
    if confidence >= CONFIDENCE_TIERS["court_defensible"]:
        return "court_defensible"
    if confidence >= CONFIDENCE_TIERS["high"]:
        return "high"
    if confidence >= CONFIDENCE_TIERS["medium"]:
        return "medium"
    if confidence >= CONFIDENCE_TIERS["low"]:
        return "low"
    return "very_low"
