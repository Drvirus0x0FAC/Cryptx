/**
 * entityTypes — canonical entity-type model + visual mapping for every CrypTX graph.
 *
 * Previously, NONE of the three graphs visually distinguished entity *type*
 * (exchange vs. mixer vs. bridge vs. scam vs. contract vs. wallet). They only
 * encoded risk score + chain glyph, so a sanctioned exchange looked identical
 * to a clean personal wallet if their scores happened to match. The role /
 * category data (`role_hint`, `labels`, `risk_labels`, `arkham_owner`,
 * `bridge_score`, `category`, address format) was available but only ever
 * shown as text.
 *
 * This module is the single source of truth that closes that gap:
 *   • `EntityType`        — the closed taxonomy
 *   • `classifyEntity()`  — heuristic classifier turning a heterogeneous node
 *                           into one stable EntityType
 *   • `ENTITY_META`       — type → { shape, color, glyph, label }, consumed by
 *                           nodeShapes + GraphNodeKit so every graph renders a
 *                           mixer as a hexagon, a bridge as a diamond, etc.
 *
 * Pure (no React) — importable from any rendering layer.
 */
import type { NodeShape } from './nodeShapes'

export type EntityType =
  | 'wallet'       // a plain externally-owned address / UTXO wallet
  | 'contract'     // a smart contract (code-bearing)
  | 'exchange'     // centralised exchange / VASP hot wallet
  | 'mixer'        // tumbler / CoinJoin / privacy pool (Tornado, etc.)
  | 'bridge'       // cross-chain bridge / lock-mint router
  | 'dex'          // decentralised exchange router / pool
  | 'scam'         // scam / fraud / drainer address
  | 'sanctioned'   // OFAC SDN / designated entity
  | 'miner'        // miner / validator / pool payout
  | 'entity'       // generic off-chain entity (person / org)
  | 'unknown'      // fallback

export interface EntityMeta {
  shape: NodeShape
  /** accent color used for the type badge + ring tint */
  color: string
  /** short pictogram key (rendered by GraphNodeKit's TypeGlyph) */
  glyph: EntityType
  label: string
}

/** The closed map: type → visual identity. Single source of truth. */
export const ENTITY_META: Record<EntityType, EntityMeta> = {
  wallet:      { shape: 'circle',   color: '#64d2ff', glyph: 'wallet',     label: 'Wallet' },
  contract:    { shape: 'square',   color: '#0a84ff', glyph: 'contract',   label: 'Contract' },
  exchange:    { shape: 'shield',   color: '#30d158', glyph: 'exchange',   label: 'Exchange' },
  mixer:       { shape: 'hexagon',  color: '#bf5af2', glyph: 'mixer',      label: 'Mixer' },
  bridge:      { shape: 'diamond',  color: '#5e9eff', glyph: 'bridge',     label: 'Bridge' },
  dex:         { shape: 'rounded',  color: '#26d0ce', glyph: 'dex',        label: 'DEX' },
  scam:        { shape: 'triangle', color: '#ff453a', glyph: 'scam',       label: 'Scam' },
  sanctioned:  { shape: 'octagon',  color: '#f0356b', glyph: 'sanctioned', label: 'Sanctioned' },
  miner:       { shape: 'hexagon',  color: '#ffd60a', glyph: 'miner',      label: 'Miner' },
  entity:      { shape: 'rounded',  color: '#8e9db5', glyph: 'entity',     label: 'Entity' },
  unknown:     { shape: 'circle',   color: '#8e9db5', glyph: 'unknown',    label: 'Unknown' },
}

export const ENTITY_TYPE_ORDER: EntityType[] = [
  'wallet', 'contract', 'exchange', 'mixer', 'bridge', 'dex', 'scam', 'sanctioned', 'miner', 'entity', 'unknown',
]

/** Lowercase keyword sets used by the classifier. */
const KW = {
  sanctioned: ['ofac', 'sdn', 'sanction', 'designated', 'lazarus', 'rocketman', 'bluenoroff', 'tradertraitor'],
  mixer:      ['mixer', 'tornado', 'tumbler', 'coinjoin', 'blender', 'chipmixer', 'privacy pool', 'aztec', 'spin'],
  bridge:     ['bridge', 'wormhole', 'stargate', 'across', 'hop protocol', 'synapse', 'multichain', 'celer', 'layerzero', 'thorchain', 'renbridge', 'routernode'],
  dex:        ['dex', 'uniswap', 'sushiswap', 'pancakeswap', 'curve', 'balancer', '1inch', 'router', 'liquidity pool', 'amm'],
  exchange:   ['exchange', 'binance', 'okx', 'okex', 'kraken', 'coinbase', 'bybit', 'huobi', 'kucoin', 'bitfinex', 'gemini', 'bitstamp', 'bittrex', 'poloniex', 'upbit', 'vasp', 'hot wallet', 'deposit', 'withdrawal'],
  scam:       ['scam', 'phish', 'drainer', 'rug', 'fraud', 'pig butchering', 'honeypot', 'fake', 'impersonat', 'cloned'],
  miner:      ['miner', 'mining', 'pool', 'f2pool', 'antpool', 'validator', 'staking rewards', 'coinbase reward'],
}

function hasAny(text: string, words: string[]): boolean {
  return words.some(w => text.includes(w))
}

/**
 * Heuristic classifier. Reads whichever of these a node exposes:
 *   category?, type?, kind?, role_hint?, risk_labels[]?, labels[]?,
 *   arkham_owner?, bridge_score?, is_suspicious?, address, chain
 *
 * Precedence (highest first):
 *   1. explicit sanctioned flag / sanctions keyword
 *   2. explicit mixer/bridge/dex/scam/miner category or keyword
 *   3. exchange (VASP / arkham owner / centralised keywords)
 *   4. contract (address is a contract OR category=contract)
 *   5. wallet (default EOA)
 *
 * The classifier is intentionally generous — when in doubt it keeps the most
 * investigative-relevant classification (e.g. a sanctioned exchange is
 * 'sanctioned', not 'exchange').
 */
export interface EntityInput {
  category?: string | null
  type?: string | null
  kind?: string | null
  roleHint?: string | null
  role_hint?: string | null
  labels?: string[] | null
  riskLabels?: string[] | null
  risk_labels?: string[] | null
  arkhamOwner?: { name?: string } | string | null
  arkham_owner?: { name?: string } | string | null
  bridgeScore?: number | null
  bridge_score?: number | null
  isContract?: boolean | null
  is_contract?: boolean | null
  isSuspicious?: boolean | null
  address?: string
}

export function classifyEntity(n: EntityInput): EntityType {
  const blob = [
    n.category, n.type, n.kind, n.roleHint, n.role_hint,
    ...(n.labels || []), ...(n.riskLabels || n.risk_labels || []),
    typeof n.arkhamOwner === 'string' ? n.arkhamOwner : n.arkhamOwner?.name,
    typeof n.arkham_owner === 'string' ? n.arkham_owner : n.arkham_owner?.name,
  ].filter(Boolean).join(' ').toLowerCase()

  const bridgeScore = n.bridgeScore ?? n.bridge_score ?? 0

  // 1. Sanctions (categorical, highest precedence)
  if (hasAny(blob, KW.sanctioned)) return 'sanctioned'

  // 2. Mixer
  if (hasAny(blob, KW.mixer)) return 'mixer'

  // 3. Bridge (explicit keyword OR strong bridge score)
  if (hasAny(blob, KW.bridge) || (typeof bridgeScore === 'number' && bridgeScore >= 5)) return 'bridge'

  // 4. DEX
  if (hasAny(blob, KW.dex)) return 'dex'

  // 5. Scam
  if (hasAny(blob, KW.scam)) return 'scam'

  // 6. Miner
  if (hasAny(blob, KW.miner)) return 'miner'

  // 7. Exchange / VASP
  if (hasAny(blob, KW.exchange)) return 'exchange'

  // 8. Contract
  if (n.isContract || n.is_contract) return 'contract'
  if (n.category && /contract|token|erc20|erc721|nft|deploy/i.test(n.category)) return 'contract'

  // 9. Generic off-chain entity
  if (n.kind && ['person', 'org', 'organisation', 'organization', 'email', 'phone', 'ip', 'social'].includes(n.kind)) return 'entity'

  // 10. Default: wallet
  return 'wallet'
}

/** Convenience: visual meta for a node, classifying first. */
export function entityMetaFor(n: EntityInput): EntityMeta {
  return ENTITY_META[classifyEntity(n)]
}
