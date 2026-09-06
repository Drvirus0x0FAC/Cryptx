/**
 * CrypTX coverage data — the single source of truth for supported chains + tokens.
 *
 * Used by:
 *   - Dashboard (the "N chains supported" badge + coverage matrix)
 *   - CoverageModal (the expandable in-app sub-screen)
 *
 * Keep this in sync with backend/constants.py CHAINS + COINGECKO_IDS.
 * Colors match the chain-brand palette used in NexusGraph CHAIN_BADGES.
 */

export interface ChainInfo {
  id: string
  name: string
  symbol: string
  family: 'EVM' | 'UTXO' | 'Solana' | 'Tron' | 'Cosmos' | 'others'
  color: string
  textColor: string
  explorer: string
  liveTrace: boolean   // does the holistic/deep tracer support live tracing?
}

export const SUPPORTED_CHAINS: ChainInfo[] = [
  { id: 'btc',   name: 'Bitcoin',        symbol: 'BTC',   family: 'UTXO',   color: '#f7931a', textColor: '#1f1300', explorer: 'blockchain.com', liveTrace: true },
  { id: 'eth',   name: 'Ethereum',       symbol: 'ETH',   family: 'EVM',    color: '#627eea', textColor: '#ffffff', explorer: 'etherscan.io',   liveTrace: true },
  { id: 'bsc',   name: 'BNB Smart Chain',symbol: 'BNB',   family: 'EVM',    color: '#f3ba2f', textColor: '#1d1600', explorer: 'bscscan.com',    liveTrace: true },
  { id: 'matic', name: 'Polygon',        symbol: 'POL',   family: 'EVM',    color: '#8247e5', textColor: '#ffffff', explorer: 'polygonscan.com',liveTrace: true },
  { id: 'arb',   name: 'Arbitrum',       symbol: 'ARB',   family: 'EVM',    color: '#28a0f0', textColor: '#06131d', explorer: 'arbiscan.io',    liveTrace: true },
  { id: 'op',    name: 'Optimism',       symbol: 'OP',    family: 'EVM',    color: '#ff0420', textColor: '#ffffff', explorer: 'optimistic.etherscan.io', liveTrace: true },
  { id: 'base',  name: 'Base',           symbol: 'ETH',   family: 'EVM',    color: '#0052ff', textColor: '#ffffff', explorer: 'basescan.org',   liveTrace: true },
  { id: 'avax',  name: 'Avalanche',      symbol: 'AVAX',  family: 'EVM',    color: '#e84142', textColor: '#ffffff', explorer: 'snowtrace.io',   liveTrace: true },
  { id: 'trx',   name: 'Tron',           symbol: 'TRX',   family: 'Tron',   color: '#eb0029', textColor: '#ffffff', explorer: 'tronscan.org',   liveTrace: true },
  { id: 'sol',   name: 'Solana',         symbol: 'SOL',   family: 'Solana', color: '#14f195', textColor: '#05140e', explorer: 'solscan.io',     liveTrace: true },
  { id: 'ltc',   name: 'Litecoin',       symbol: 'LTC',   family: 'UTXO',   color: '#345d9d', textColor: '#ffffff', explorer: 'blockchair.com', liveTrace: true },
  { id: 'doge',  name: 'Dogecoin',       symbol: 'DOGE',  family: 'UTXO',   color: '#c2a633', textColor: '#161203', explorer: 'blockchair.com', liveTrace: true },
  { id: 'bch',   name: 'Bitcoin Cash',   symbol: 'BCH',   family: 'UTXO',   color: '#8dc351', textColor: '#091100', explorer: 'blockchair.com', liveTrace: true },
  { id: 'xrp',   name: 'Ripple',         symbol: 'XRP',   family: 'others', color: '#23292f', textColor: '#ffffff', explorer: 'livenet.xrpl.org', liveTrace: true },
  { id: 'ton',   name: 'Toncoin',        symbol: 'TON',   family: 'others', color: '#0098ea', textColor: '#ffffff', explorer: 'tonscan.org',    liveTrace: true },
  { id: 'near',  name: 'NEAR',           symbol: 'NEAR',  family: 'others', color: '#000000', textColor: '#ffffff', explorer: 'nearblocks.io',  liveTrace: true },
  { id: 'ada',   name: 'Cardano',        symbol: 'ADA',   family: 'others', color: '#0033ad', textColor: '#ffffff', explorer: 'cardanoscan.io', liveTrace: true },
  { id: 'dot',   name: 'Polkadot',       symbol: 'DOT',   family: 'others', color: '#e6007a', textColor: '#ffffff', explorer: 'polkadot.subscan.io', liveTrace: true },
  { id: 'atom',  name: 'Cosmos',         symbol: 'ATOM',  family: 'Cosmos', color: '#2e3148', textColor: '#ffffff', explorer: 'mintscan.io/cosmos', liveTrace: true },
  { id: 'xmr',   name: 'Monero',         symbol: 'XMR',   family: 'others', color: '#ff6600', textColor: '#ffffff', explorer: 'xmrchain.net',   liveTrace: false },
  { id: 'xlm',   name: 'Stellar',        symbol: 'XLM',   family: 'others', color: '#14b8a6', textColor: '#ffffff', explorer: 'stellar.expert', liveTrace: true },
  { id: 'algo',  name: 'Algorand',       symbol: 'ALGO',  family: 'others', color: '#111111', textColor: '#ffffff', explorer: 'lora.algokit.io',liveTrace: true },
  { id: 'apt',   name: 'Aptos',          symbol: 'APT',   family: 'others', color: '#06f7b7', textColor: '#05140e', explorer: 'aptoscan.com',   liveTrace: true },
  { id: 'sui',   name: 'Sui',            symbol: 'SUI',   family: 'others', color: '#6fbcf0', textColor: '#05111a', explorer: 'suiscan.xyz',    liveTrace: true },
  { id: 'kas',   name: 'Kaspa',          symbol: 'KAS',   family: 'UTXO',   color: '#70c7ba', textColor: '#06140f', explorer: 'kaspa.explorer', liveTrace: false },
  { id: 'ftm',   name: 'Fantom',         symbol: 'FTM',   family: 'EVM',    color: '#13b5ec', textColor: '#ffffff', explorer: 'ftmscan.com',    liveTrace: true },
  { id: 'mnt',   name: 'Mantle',         symbol: 'MNT',   family: 'EVM',    color: '#000000', textColor: '#ffffff', explorer: 'mantlescan.xyz', liveTrace: true },
  { id: 'glmr',  name: 'Moonbeam',       symbol: 'GLMR',  family: 'EVM',    color: '#ff2e56', textColor: '#ffffff', explorer: 'moonbeam.moonscan.io', liveTrace: true },
  { id: 'zep',   name: 'ZetaChain',      symbol: 'ZETA',  family: 'EVM',    color: '#1c1c1c', textColor: '#ffffff', explorer: 'explorer.zetachain.com', liveTrace: true },
  { id: 'stx',   name: 'Stacks',         symbol: 'STX',   family: 'others', color: '#5546ff', textColor: '#ffffff', explorer: 'explorer.hiro.so', liveTrace: false },
  { id: 'icp',   name: 'Internet Computer',symbol: 'ICP', family: 'others', color: '#f15a24', textColor: '#1a0500', explorer: 'dashboard.internetcomputer.org', liveTrace: false },
]

// Tokens with pricing (subset of backend COINGECKO_IDS — the investigative-relevant ones)
export interface TokenInfo {
  symbol: string
  name: string
  chain: string      // native chain id
  category: 'native' | 'stablecoin' | 'wrapped' | 'defi' | 'meme' | 'lst'
}

export const SUPPORTED_TOKENS: TokenInfo[] = [
  // Native L1s
  { symbol: 'BTC',   name: 'Bitcoin',          chain: 'btc',  category: 'native' },
  { symbol: 'ETH',   name: 'Ethereum',         chain: 'eth',  category: 'native' },
  { symbol: 'BNB',   name: 'BNB',              chain: 'bsc',  category: 'native' },
  { symbol: 'POL',   name: 'Polygon',          chain: 'matic',category: 'native' },
  { symbol: 'SOL',   name: 'Solana',           chain: 'sol',  category: 'native' },
  { symbol: 'TRX',   name: 'Tron',             chain: 'trx',  category: 'native' },
  { symbol: 'AVAX',  name: 'Avalanche',        chain: 'avax', category: 'native' },
  { symbol: 'LTC',   name: 'Litecoin',         chain: 'ltc',  category: 'native' },
  { symbol: 'DOGE',  name: 'Dogecoin',         chain: 'doge', category: 'native' },
  { symbol: 'XRP',   name: 'Ripple',           chain: 'xrp',  category: 'native' },
  { symbol: 'TON',   name: 'Toncoin',          chain: 'ton',  category: 'native' },
  { symbol: 'ADA',   name: 'Cardano',          chain: 'ada',  category: 'native' },
  { symbol: 'DOT',   name: 'Polkadot',         chain: 'dot',  category: 'native' },
  { symbol: 'ATOM',  name: 'Cosmos',           chain: 'atom', category: 'native' },
  { symbol: 'XLM',   name: 'Stellar',          chain: 'xlm',  category: 'native' },
  { symbol: 'ALGO',  name: 'Algorand',         chain: 'algo', category: 'native' },
  { symbol: 'APT',   name: 'Aptos',            chain: 'apt',  category: 'native' },
  { symbol: 'SUI',   name: 'Sui',              chain: 'sui',  category: 'native' },
  { symbol: 'NEAR',  name: 'NEAR',             chain: 'near', category: 'native' },
  { symbol: 'FTM',   name: 'Fantom',           chain: 'ftm',  category: 'native' },
  { symbol: 'MNT',   name: 'Mantle',           chain: 'mnt',  category: 'native' },
  { symbol: 'GLMR',  name: 'Moonbeam',         chain: 'glmr', category: 'native' },
  { symbol: 'ZETA',  name: 'ZetaChain',        chain: 'zep',  category: 'native' },
  // Stablecoins
  { symbol: 'USDT',  name: 'Tether',           chain: 'multi', category: 'stablecoin' },
  { symbol: 'USDC',  name: 'USD Coin',         chain: 'multi', category: 'stablecoin' },
  { symbol: 'DAI',   name: 'Dai',              chain: 'eth',  category: 'stablecoin' },
  { symbol: 'TUSD',  name: 'TrueUSD',          chain: 'eth',  category: 'stablecoin' },
  { symbol: 'BUSD',  name: 'Binance USD',      chain: 'eth',  category: 'stablecoin' },
  { symbol: 'FRAX',  name: 'Frax',             chain: 'eth',  category: 'stablecoin' },
  { symbol: 'LUSD',  name: 'LUSD Stablecoin',  chain: 'eth',  category: 'stablecoin' },
  { symbol: 'PYUSD', name: 'PayPal USD',       chain: 'eth',  category: 'stablecoin' },
  { symbol: 'FDUSD', name: 'First Digital USD',chain: 'bsc',  category: 'stablecoin' },
  { symbol: 'USDD',  name: 'Decentralized USD',chain: 'trx',  category: 'stablecoin' },
  { symbol: 'USDE',  name: 'Ethena USDe',      chain: 'eth',  category: 'stablecoin' },
  // Wrapped
  { symbol: 'WETH',  name: 'Wrapped Ether',    chain: 'eth',  category: 'wrapped' },
  { symbol: 'WBTC',  name: 'Wrapped BTC',      chain: 'eth',  category: 'wrapped' },
  { symbol: 'WBNB',  name: 'Wrapped BNB',      chain: 'bsc',  category: 'wrapped' },
  // LST / Restaking
  { symbol: 'STETH', name: 'Lido Staked ETH',  chain: 'eth',  category: 'lst' },
  { symbol: 'CBETH', name: 'Coinbase Staked ETH', chain: 'eth', category: 'lst' },
  { symbol: 'RETH',  name: 'Rocket Pool ETH',  chain: 'eth',  category: 'lst' },
  // DeFi / governance
  { symbol: 'LINK',  name: 'Chainlink',        chain: 'eth',  category: 'defi' },
  { symbol: 'UNI',   name: 'Uniswap',          chain: 'eth',  category: 'defi' },
  { symbol: 'AAVE',  name: 'Aave',             chain: 'eth',  category: 'defi' },
  { symbol: 'ARB',   name: 'Arbitrum',         chain: 'arb',  category: 'defi' },
  { symbol: 'OP',    name: 'Optimism',         chain: 'op',   category: 'defi' },
  { symbol: 'CRV',   name: 'Curve DAO',        chain: 'eth',  category: 'defi' },
  { symbol: 'BAL',   name: 'Balancer',         chain: 'eth',  category: 'defi' },
  { symbol: 'GMX',   name: 'GMX',              chain: 'arb',  category: 'defi' },
  { symbol: 'JOE',   name: 'Trader Joe',       chain: 'avax', category: 'defi' },
  { symbol: 'AERO',  name: 'Aerodrome',        chain: 'base', category: 'defi' },
  { symbol: 'LDO',   name: 'Lido DAO',         chain: 'eth',  category: 'defi' },
  { symbol: 'TIA',   name: 'Celestia',         chain: 'atom', category: 'defi' },
  { symbol: 'SEI',   name: 'Sei',              chain: 'atom', category: 'defi' },
  { symbol: 'INJ',   name: 'Injective',        chain: 'atom', category: 'defi' },
  { symbol: 'RUNE',  name: 'THORChain',        chain: 'atom', category: 'defi' },
  { symbol: 'RNDR',  name: 'Render',           chain: 'eth',  category: 'defi' },
  { symbol: 'TAO',   name: 'Bittensor',        chain: 'atom', category: 'defi' },
  { symbol: 'ICP',   name: 'Internet Computer',chain: 'icp',  category: 'defi' },
  // Meme (investigatively relevant — rug pulls, pump-and-dumps)
  { symbol: 'SHIB',  name: 'Shiba Inu',        chain: 'eth',  category: 'meme' },
  { symbol: 'PEPE',  name: 'Pepe',             chain: 'eth',  category: 'meme' },
  { symbol: 'WIF',   name: 'dogwifhat',        chain: 'sol',  category: 'meme' },
  { symbol: 'BONK',  name: 'Bonk',             chain: 'sol',  category: 'meme' },
  { symbol: 'ORDI',  name: 'Ordinals',         chain: 'btc',  category: 'meme' },
]

export const TOTAL_CHAINS = SUPPORTED_CHAINS.length
export const TOTAL_TOKENS = SUPPORTED_TOKENS.length
