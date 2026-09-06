/* ── Mega Report Generator ──────────────────────────────────────────────────── */
export interface ReportType {
  id: string
  name: string
  audience: string
  classification: string
  accent: string
  icon: string
  blurb: string
}

export interface GeneratedReport {
  html: string
  artifact_id: string
  report_type: string
  case_id: string
  ai_used: boolean
  generated_at: string
  metrics?: Record<string, unknown>
}

/* ── Blockchain Threat Landscape (RSS threat feeds) ─────────────────────────── */
export interface ThreatFeedSource {
  id: string
  name: string
  category: string
  url: string
  publisher?: string
  count?: number
  error?: string | null
  fetched_at?: string
}

export interface ThreatFeedItem {
  id: string
  source_id: string
  source_name: string
  publisher: string
  category: string
  title: string
  link: string
  author: string
  published: string | null
  summary: string
  image?: string
  reading_minutes: number
  content_html?: string
}

export interface ThreatFeedNewsResponse {
  items: ThreatFeedItem[]
  sources: ThreatFeedSource[]
  total: number
  generated_at: string
}

/* ── Ransomware Intelligence ─────────────────────────────────────────────────── */
export interface RansomwareLocation {
  fqdn: string
  title: string
  type: string
  available: boolean
  enabled: boolean
}

export interface RansomwareTechnique {
  id: string
  name: string
  details: string
}

export interface RansomwareTactic {
  tactic_id: string
  tactic_name: string
  techniques: RansomwareTechnique[]
}

export interface CryptoAddresses {
  btc: string[]
  eth: string[]
  xmr: string[]
  ltc: string[]
  doge: string[]
  zec: string[]
  dash: string[]
  bch: string[]
}

export interface CryptoWallet {
  address: string
  chain: string
  chain_label: string
  blockchain_raw: string
  balance_sats: number
  balance_usd: number
  tx_count: number
  last_tx_time: string
  first_seen: string
  source: string
  family: string
  group: string
}

export interface WalletStats {
  total_wallets: number
  total_balance_usd: number
  total_tx_count: number
  chains: string[]
}

export interface RansomwareGroup {
  name: string
  aliases: string[]
  description: string
  added_date: string | null
  first_seen?: string
  last_seen?: string
  victim_count?: number
  locations: RansomwareLocation[]
  leak_sites: RansomwareLocation[]
  active_sites: RansomwareLocation[]
  ttps: RansomwareTactic[]
  tools: unknown[]
  tool_categories: string[]
  crypto_addresses: CryptoAddresses
  wallets?: CryptoWallet[]
  wallet_stats?: WalletStats
  profile_url: string
  source: string
  ransomlook_data?: {
    profile_links: string[]
    affiliates: string[]
    contact: Record<string, string>
    raas: boolean
    slug: string
  }
}

export interface RansomwareIncident {
  id: string
  title: string
  group: string
  description: string
  discovered: string
  victim_name: string
  victim_industry: string
  victim_country: string
  website: string
  ransom_demanded: string
  data_leaked: string
  post_url: string
  crypto_addresses: CryptoAddresses
  address_count?: number
  source: string
}

export interface ThreatActorProfile {
  name: string
  aliases: string[]
  description: string
  added_date: string | null
  first_seen: string
  last_seen: string
  active: boolean
  victim_count: number
  raas: boolean
  locations: RansomwareLocation[]
  leak_sites: RansomwareLocation[]
  active_sites: RansomwareLocation[]
  profile_url: string
  profile_links: string[]
  ttps: RansomwareTactic[]
  tools: unknown[]
  tool_categories: string[]
  affiliates: string[]
  contact: Record<string, string>
  crypto_addresses: CryptoAddresses
  total_addresses: number
  known_address_matches: {
    address: string
    chain: string
    actor: string
    label: string
    context: string
    source: string
    first_seen: string
    severity: string
  }[]
  chains_used: string[]
  wallets: CryptoWallet[]
  wallet_stats: WalletStats
  incident_count: number
  incidents_with_crypto: number
  victim_countries: string[]
  victim_industries: string[]
  sources: string[]
}

export interface AddressIntelEntry {
  address: string
  chain: string
  chain_label: string
  actors: string[]
  incidents: {
    title: string
    group: string
    date: string
    victim: string
  }[]
  known_info: {
    chain: string
    actor: string
    label: string
    context: string
    source: string
    first_seen: string
    severity: string
  } | null
  first_seen: string | null
  sources: string[]
  wallet_data: CryptoWallet | null
  incident_count: number
  actor_count: number
}

export interface RansomwareStats {
  total_posts: number
  total_groups: number
  recent_posts: unknown[]
  top_groups: unknown[]
  this_month: number
  source: string
  fetched_at: string
}

export interface RansomwareGroupsResponse {
  groups: RansomwareGroup[]
  total: number
  active: number
  with_wallets: number
}

export interface RansomwareIncidentsResponse {
  incidents: RansomwareIncident[]
  total: number
  with_crypto_addresses: number
}

export interface RansomwareSearchResponse {
  query: string
  groups: RansomwareGroup[]
  incidents: RansomwareIncident[]
  total_groups: number
  total_incidents: number
}

export interface RansomwareFeedResponse {
  summary: {
    total_groups: number
    active_groups: number
    total_incidents: number
    incidents_with_crypto_addresses: number
    total_tracked_addresses: number
    known_malicious_addresses: number
    threat_actors_profiled: number
  }
  stats: RansomwareStats
  recent_incidents: RansomwareIncident[]
  active_groups: { name: string; sites: number; ttps_count: number }[]
  incidents_with_crypto: RansomwareIncident[]
  top_addresses: AddressIntelEntry[]
  threat_actors_summary: {
    name: string
    incident_count: number
    total_addresses: number
    active: boolean
    chains_used: string[]
    victim_count: number
  }[]
  generated_at: string
}

export interface RansomwareAddressResponse {
  address: string
  found: boolean
  chain: string | null
  chain_label: string | null
  actors: string[]
  incidents: {
    title: string
    group: string
    date: string
    victim: string
  }[]
  known_info: {
    chain: string
    actor: string
    label: string
    context: string
    source: string
    first_seen: string
    severity: string
  } | null
  bitcoin_abuse: {
    found: boolean
    address: string
    count?: number
    reports: {
      abuse_type: string
      description: string
      created_at: string
    }[]
    note?: string
    error?: string
  } | null
  sources: string[]
}

export interface ThreatActorsResponse {
  profiles: ThreatActorProfile[]
  total: number
  with_wallets: number
  with_crypto: number
  total_wallet_balance_usd: number
}

export interface AddressIntelResponse {
  addresses: AddressIntelEntry[]
  total: number
  by_chain: Record<string, number>
  total_balance_usd: number
}

export interface ThreatBaselineResponse {
  groups: RansomwareGroupsResponse
  incidents: RansomwareIncidentsResponse
  actors: ThreatActorsResponse
  addresses: AddressIntelResponse
  stats: RansomwareStats
  cache_age_sec: number
  cache_populated: boolean
  generated_at: string
}

export interface SanctionId {
  name: string
  category: string
  description?: string
}

export interface SanctionsResult {
  sanctioned: boolean
  source: string
  identifications?: SanctionId[]
  error?: string
}

export interface MixerHit {
  counterparty: string
  mixer_name: string
  mixer_type: string
  chain: string
  tx_hash: string
  direction: string
  time: string
}

export interface BridgeSwapHit {
  counterparty: string
  name: string
  type: string
  chain: string
  tx_hash: string
  direction: string
  side: string
  time: string
  token: string
  value: string | number
}

export interface ChainHopSwap {
  bridge_hits: BridgeSwapHit[]
  swap_hits: BridgeSwapHit[]
  bridge_count: number
  swap_count: number
  heuristics: Array<{ type: string; severity: string; evidence: string }>
  possible_chain_hopping: boolean
  possible_chain_swapping: boolean
  risk_level: 'clean' | 'medium' | 'high'
}

export interface TokenBalance {
  symbol: string
  name?: string
  balance: number
  contract?: string
  usd_value?: number
}

export interface Transaction {
  hash?: string
  txid?: string
  time: string
  from?: string
  to?: string
  direction: 'IN' | 'OUT' | ''
  value_eth?: number
  value_trx?: number
  delta_btc?: number
  value?: number
  token?: string
  is_error?: boolean
  confirmed?: boolean
}

export interface ArkhamCounterparty {
  address: string
  entity: string
  label: string
  chain: string
}

export interface ArkhamResult {
  found: boolean
  name?: string
  entity_id?: string
  entity_name?: string
  entity_type?: string
  entity_note?: string
  entity_website?: string
  entity_twitter?: string
  label?: string
  label_type?: string
  labels?: string[]
  tags?: string[]
  is_verified?: boolean
  confidence?: number
  chains_seen?: string[]
  balance_usd?: number
  portfolio_usd?: number
  source?: string
  source_url?: string
  counterparties?: ArkhamCounterparty[]
  error?: string
}

export interface DeBankResult {
  found: boolean
  name?: string
  display_name?: string
  web3_id?: string
  bio?: string
  follower_count?: number
  following_count?: number
  is_vip?: boolean
  is_pro?: boolean
  total_usd_value?: number
  portfolio_usd?: number
  used_chains?: string[]
  chain_count?: number
  token_count?: number
  protocol_count?: number
  nft_count?: number
  source?: string
  source_url?: string
  deep_available?: boolean
  error?: string
}

export interface AttributionOwner {
  name: string
  type?: string | null
  verified?: boolean
  labels?: string[]
  confidence?: number | null
  aliases?: string[]
  bio?: string
}

export interface AttributionToken {
  symbol: string
  name?: string
  chain?: string
  price?: number
  amount?: number
  usd_value?: number
  logo_url?: string
  is_wallet?: boolean
  protocol_id?: string | null
  is_scam?: boolean
  is_suspicious?: boolean
}

export interface AttributionChain {
  chain_id: string
  chain_name: string
  usd_value: number
  logo_url?: string
}

export interface AttributionProtocol {
  name: string
  chain?: string
  net_usd_value?: number
  asset_usd_value?: number
  debt_usd_value?: number
  logo_url?: string
  site_url?: string
  detail_types?: string[]
}

export interface AttributionPortfolio {
  total_usd: number
  chains: AttributionChain[]
  tokens: AttributionToken[]
  protocols: AttributionProtocol[]
  token_count?: number
  chain_count?: number
  protocol_count?: number
}

export interface AttributionAnalysis {
  address: string
  found: boolean
  owner?: AttributionOwner | null
  portfolio?: AttributionPortfolio | null
  errors?: string[]
  checked_at?: string
}

export interface ScamRecord {
  name?: string
  email?: string
  phone?: string
  bitcoinaddress?: string
  address?: string
  country?: string
  category?: string
  reporttype?: string
  source?: string
  date?: string
  report?: string
  description?: string
  [key: string]: unknown
}

export interface ScamReport {
  found: boolean
  count?: number
  query?: string
  type?: string
  records?: ScamRecord[]
  error?: string
  skipped?: boolean
}

export interface AddressIntel {
  address: string
  chain: string
  detected_chain?: string
  balance: number
  balance_unit: string
  portfolio_usd?: number
  total_received?: number
  tx_count: number
  native_tx_count?: number
  token_tx_count?: number
  first_seen?: string
  last_seen?: string
  recent_txs?: Transaction[]
  token_txs?: Transaction[]
  tokens?: TokenBalance[]
  mixer_hits?: MixerHit[]
  chain_hop_swap?: ChainHopSwap
  sanctions?: SanctionsResult
  arkham?: ArkhamResult
  debank?: DeBankResult
  scam_reports?: ScamReport
  public_enrichment?: PublicEnrichment
  explorer?: string
  source?: string
  error?: string
  fallback_warning?: string
  chainid?: number
}

export interface PublicEnrichmentSource {
  name: string
  url?: string
  ok: boolean
  configured: boolean
  detail?: string
  checked_at?: string
}

export interface PublicEnrichmentLabel {
  category: string
  label: string
  source: string
  source_url?: string
  confidence?: number
  method?: string
  evidence?: Record<string, unknown>
}

export interface PublicEnrichmentProviderResult {
  source: PublicEnrichmentSource
  found?: boolean
  count?: number
  records?: Array<Record<string, unknown>>
  labels?: PublicEnrichmentLabel[]
}

export interface PublicEnrichment {
  address: string
  chain: string
  summary: {
    label_count: number
    abuse_report_count: number
    ransomware_hit_count: number
    sanctions_dataset_hit_count: number
    portfolio_usd?: number | null
    defi_chain_tvl?: number | null
  }
  labels: PublicEnrichmentLabel[]
  abuse: {
    found: boolean
    count: number
    sources: PublicEnrichmentProviderResult[]
  }
  ransomware: {
    found: boolean
    matches: PublicEnrichmentLabel[]
  }
  prices?: {
    source?: PublicEnrichmentSource
    assets?: Record<string, { coingecko_id: string; usd: number; usd_24h_change?: number | null }>
    portfolio_usd?: number | null
  }
  defi?: {
    source?: PublicEnrichmentSource
    chain?: Record<string, unknown> | null
    stablecoins?: Array<{ symbol?: string; name?: string; circulating_usd?: number }>
  }
  sources?: PublicEnrichmentSource[]
  generated_at: string
  disclaimer?: string
  error?: string
}

export type RiskLevel =
  | 'clean'
  | 'entity'
  | 'bridge_swap'
  | 'scam'
  | 'mixer'
  | 'sanctioned'
  | 'error'

export interface GraphNode {
  id: string
  address: string
  short_address: string
  hop: number
  chain: string
  balance: number
  balance_unit: string
  tx_count: number
  entity: string
  risk_level: RiskLevel | string
  risk_color: string
  risk_score: number
  risk_labels: string[]
  is_suspicious: boolean
  transactions?: Transaction[]
  counterparties?: unknown[]
  raw?: Record<string, unknown>
  explorer: string
  source: string
  // ── Deep-analysis enrichment (populated by POST /api/trace/deep) ──
  first_seen?: number
  last_seen?: number
  inflow_value?: number
  outflow_value?: number
  cluster_id?: string
}

export interface GraphEdge {
  source: string
  target: string
  amount: number
  token: string
  hash: string
  source_address: string
  target_address: string
}

export interface TracePattern {
  scope: string
  node_id: string
  address: string
  pattern: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  confidence: 'low' | 'medium' | 'high' | number
  evidence: string
  // ── Deep-analysis extras (optional) ──
  path?: string[]
  categories?: string[]
}

export interface TraceStats {
  nodes: number
  edges: number
  suspicious_nodes: number
  timeline_events: number
  patterns: number
  risk_levels: Record<string, number>
}

/** A wallet cluster (common-control lead) from the clustering engine.
 *  Fields are optional to accommodate both the full clustering endpoint shape
 *  (see WalletCluster at line ~2067) and the lighter analysis-block variant. */
export interface WalletClusterMember {
  members?: string[]
  member_count?: number
  method?: string
  confidence?: number
  lead?: string
}

/** Per-wallet dwell-time record from the dwell-time algorithm. */
export interface DwellRecord {
  address: string
  dwell_sec: number
  rapid: boolean
}

/** Structured deep-analysis block returned in trace.analysis by /trace/deep. */
export interface TraceAnalysis {
  pattern_count?: number
  engines?: {
    cashout?: { indicator_count?: number; primary_dest?: string | null; risk?: { level?: string; score?: number } }
    clusters?: { count?: number; clusters?: WalletClusterMember[] }
    crosschain?: { bridge_hops?: number; value_matches?: number; paths?: unknown[]; bridges_seen?: string[] }
    forensics?: { role?: { role?: string; confidence?: number }; motif_count?: number }
    risk?: { scored_nodes?: number }
  }
  dwell?: {
    rapid_wallet_count?: number
    rapid_wallets?: string[]
    rapid_threshold_sec?: number
    avg_dwell_sec?: number
    dwell_times?: DwellRecord[]
    summary?: string
  }
  peel_chains?: TracePattern[]
  layering?: TracePattern[]
  engine_errors?: string[]
  note?: string
}

export interface TraceGraph {
  seed: string
  mode: string
  direction: string
  hops_requested: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  timeline: unknown[]
  patterns: TracePattern[]
  warnings: string[]
  stats: TraceStats
  // Deep-analysis payload (present when /trace/deep was used)
  analysis?: TraceAnalysis
}

export interface TraceResult {
  trace: {
    seed: string
    hops_requested: number
    mode: string
    direction: string
    total_looked_up: number
    warnings: string[]
    error: string | null
    nodes: unknown[]
    analysis?: TraceAnalysis
    patterns?: TracePattern[]
  }
  graph: TraceGraph
}

export interface DexSwap {
  tx_hash: string
  timestamp: number
  time: string
  token0_symbol: string
  token1_symbol: string
  amount0: number
  amount1: number
  direction: 'buy' | 'sell' | 'unknown'
  usd_value?: number
  pool?: string
  dex: string
}

export interface DexPatterns {
  total_swaps: number
  buy_count: number
  sell_count: number
  buy_ratio?: number
  unique_tokens?: number
  possible_wash_trading?: boolean
  wash_trading_evidence?: string[]
  top_tokens?: Array<{ symbol: string; count: number }>
  [key: string]: unknown
}

export interface DexResult {
  activity: {
    address: string
    swaps: DexSwap[]
    errors?: string[]
    [key: string]: unknown
  }
  analysis: DexPatterns
}

export interface ApiSettings {
  _meta?: {
    runtime_env_path?: string
    project_env_path?: string
    written_env_paths?: string[]
  }
  AI_PROVIDER: string
  ETHERSCAN_API_KEY: string
  ARKHAM_API_KEY: string
  CHAINALYSIS_API_KEY: string
  SCAMSEARCH_API_KEY: string
  BLOCKCYPHER_TOKEN: string
  THEGRAPH_API_KEY: string
  ETHPLORER_API_KEY: string
  UD_API_KEY: string
  DEEPSEEK_API_KEY: string
  DEEPSEEK_MODEL: string
  DEEPSEEK_BASE_URL: string
  OPENAI_API_KEY: string
  OPENAI_MODEL: string
  OPENAI_BASE_URL: string
  CODEX_API_KEY: string
  CODEX_MODEL: string
  CODEX_BASE_URL: string
  CLAUDE_API_KEY: string
  CLAUDE_MODEL: string
  CLAUDE_BASE_URL: string
  GEMINI_API_KEY: string
  GEMINI_MODEL: string
  GEMINI_BASE_URL: string
  QWEN_API_KEY: string
  QWEN_MODEL: string
  QWEN_BASE_URL: string
  KIMI_API_KEY: string
  KIMI_MODEL: string
  KIMI_BASE_URL: string
  MISTRAL_API_KEY: string
  MISTRAL_MODEL: string
  MISTRAL_BASE_URL: string
  ANTIGRAVITY_API_KEY: string
  ANTIGRAVITY_MODEL: string
  ANTIGRAVITY_BASE_URL: string
  MANUS_API_KEY: string
  MANUS_MODEL: string
  MANUS_BASE_URL: string
  MIMI_API_KEY: string
  MIMI_MODEL: string
  MIMI_BASE_URL: string
  CUSTOM_LLM_API_KEY: string
  CUSTOM_LLM_MODEL: string
  CUSTOM_LLM_BASE_URL: string
  BITCOINABUSE_API_TOKEN: string
  PASTEBIN_API_KEY: string
  PASTEBIN_USER_KEY: string
  DUNE_API_KEY: string
  DUNE_LABELS_QUERY_ID: string
}

// ── Risk Scoring (v2 - CARA / Prism style) ────────────────────────────────────

export type RiskScoreLevel =
  | 'CLEAN'
  | 'LOW'
  | 'MEDIUM'
  | 'HIGH'
  | 'CRITICAL'
  | 'SANCTIONED'
  | 'ERROR'

export type RiskCategory =
  | 'sanctioned'
  | 'mixer'
  | 'darknet'
  | 'scam'
  | 'ransomware'
  | 'bridge'
  | 'dex'
  | 'exchange'
  | 'behavioral'
  | 'exposure'

export interface RiskSignal {
  type: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'
  weight: number
  label: string
  detail: string
  count?: number
  source?: string
}

export interface ExposureBreakdownItem {
  entity: string
  volume: number
}

export interface ExposureResult {
  direct_pct: number
  risky_volume: number
  total_volume: number
  unit: string
  breakdown: ExposureBreakdownItem[]
}

export interface RiskIndicators {
  sanctions_checked: boolean
  mixer_interactions: number
  scam_reports: number
  arkham_attribution: boolean
  bridge_interactions: number
  swap_interactions: number
  tx_count: number
  balance: number
  token_count: number
  direct_exposure_pct: number
  forensic_confidence?: number
  forensic_motifs?: number
}

export interface RiskScore {
  score: number
  risk_level: RiskScoreLevel
  categories: RiskCategory[]
  signals: RiskSignal[]
  exposure: ExposureResult
  indicators: RiskIndicators
  address: string
  chain: string
}

// ── Case Management ────────────────────────────────────────────────────────────

export interface CaseAddress {
  id: number
  case_id: string
  address: string
  chain: string
  label: string
  notes: string
  risk_score: number
  risk_level: string
  added_at: string
}

export interface CaseNote {
  id: number
  case_id: string
  note: string
  created_at: string
}

export interface Case {
  id: string
  name: string
  description: string
  status: 'active' | 'closed' | 'archived'
  created_at: string
  updated_at: string
  owner_id?: string
  owner_email?: string
  addresses?: CaseAddress[]
  notes?: CaseNote[]
  // From list query
  address_count?: number
  max_risk_score?: number
}

// ── Transaction Detail ────────────────────────────────────────────────────────

export interface TxTokenTransfer {
  from: string
  to: string
  value_raw: string
  contract: string
  symbol?: string
  decimals?: number
  log_index?: number
  tx_hash?: string
}

export interface TxInternalCall {
  from: string
  to: string
  value_eth: number
  type: string
  gas?: string
  gas_used?: string
  error?: string
}

export interface TxBtcIO {
  address: string
  value_btc: number
  type?: string
}

export interface TxDetail {
  hash: string
  chain: string
  chain_label: string
  native_unit?: string
  status: 'success' | 'failed' | 'confirmed' | 'mempool' | 'unknown'
  block?: number | null
  timestamp?: string
  confirmations?: number | boolean | null
  from: string
  to: string
  contract_created?: string | null
  value: number
  value_usd?: number | null
  gas_limit?: number
  gas_used?: number
  gas_efficiency?: number | null
  gas_price_gwei?: number
  tx_fee?: number
  fee_btc?: number | null
  fee_trx?: number | null
  nonce?: number
  tx_index?: number
  is_contract_call?: boolean
  method_id?: string | null
  input_data?: string
  token_transfers: TxTokenTransfer[]
  internal_txs: TxInternalCall[]
  log_count?: number
  // BTC specific
  size_bytes?: number
  vsize?: number
  weight?: number
  inputs?: TxBtcIO[]
  outputs?: TxBtcIO[]
  input_count?: number
  output_count?: number
  is_coinbase?: boolean
  // TRX specific
  energy_used?: number
  bandwidth?: number
  contract_type?: string
  // Risk
  risk_hints?: Record<string, { sanctioned: boolean; source: string }>
  // Error / explorer
  error?: string
  explorer_url?: string
}

// ── TX Lens Investigation ───────────────────────────────────────────────────

export interface TxLensParty {
  address: string
  short: string
  role: string
  inbound: number
  outbound: number
  labels: string[]
  risk_score: number
  risk_level: string
  risk_categories: string[]
  risk_signals: RiskSignal[]
  intel: Record<string, unknown>
}

export interface TxLensFlow {
  source: string
  target: string
  value: number
  token: string
  asset_type: string
  contract?: string
  hash: string
  time: string
  evidence: string
  error?: string
}

export interface TxLensIndicator {
  name: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | string
  score: number
  evidence: string[]
}

export interface TxLensAttribution {
  address: string
  role: string
  candidate: string
  confidence: number
  evidence: string[]
  limitations: string[]
}

export interface TxLensPivot {
  address: string
  short: string
  priority_score: number
  role: string
  risk_level: string
  reasons: string[]
  recommended_actions: string[]
}

export interface TxLensResult {
  version: string
  tx_hash: string
  chain: string
  summary: {
    status: string
    timestamp: string
    party_count: number
    flow_count: number
    asset_count: number
    indicator_count: number
    tx_risk_score: number
    highest_party_risk: number
  }
  transaction: TxDetail
  parties: TxLensParty[]
  value_flows: TxLensFlow[]
  local_graph: {
    seed_tx: string
    nodes: Array<{
      id: string
      address: string
      short: string
      role: string
      risk_score: number
      risk_level: string
      labels: string[]
      inbound: number
      outbound: number
    }>
    edges: TxLensFlow[]
    stats: {
      nodes: number
      edges: number
      assets: number
      contracts: number
    }
  }
  laundering_indicators: TxLensIndicator[]
  attribution_hypotheses: TxLensAttribution[]
  pivot_leads: TxLensPivot[]
  trace_context: {
    traced_addresses?: string[]
    graphs?: Record<string, unknown>
    warnings?: string[]
  }
  next_steps: string[]
}

export interface TxLensResponse {
  tx_lens: TxLensResult
  ai_assessment?: Record<string, unknown> | null
}

export interface TxLensJob {
  job_id: string
  status: 'queued' | 'running' | 'complete' | 'failed'
  progress: number
  stage: string
  detail: string
  result?: TxLensResponse | null
  error?: string | null
  created_at: string
  updated_at: string
}

// ── Wallet Monitoring ───────────────────────────────────────────────────────

export interface WalletMonitorWatch {
  id: string
  address: string
  chain: string
  label: string
  active: boolean
  poll_interval: number
  last_checked: string
  last_seen?: string[]
  created_at: string
  updated_at: string
}

export interface WalletMonitorNotification {
  id: string
  monitor_id: string
  address: string
  chain: string
  tx_hash: string
  is_read: boolean
  created_at: string
  tx: {
    hash?: string
    txid?: string
    time?: string
    from?: string
    to?: string
    direction?: string
    value?: number
    value_eth?: number
    value_trx?: number
    delta_btc?: number
    token?: string
    [key: string]: unknown
  }
}

export interface WalletMonitorScanResult {
  scanned: number
  results: Array<{ monitor_id: string; new_count: number; error?: string }>
}

// ── Batch Screening ────────────────────────────────────────────────────────────

export interface BatchResult {
  address: string
  chain: string
  balance: number
  balance_unit: string
  tx_count: number
  score: number
  risk_level: RiskScoreLevel
  categories: RiskCategory[]
  signals: string[]
  error: string | null
}

export interface BatchStats {
  total: number
  scored: number
  errors: number
  sanctioned: number
  critical: number
  high: number
  medium: number
  low: number
  clean: number
  avg_score: number
  max_score: number
}

export interface BatchScreenResult {
  results: BatchResult[]
  stats: BatchStats
}

// ── Local Forensic Analysis ──────────────────────────────────────────────────

export interface ForensicRole {
  role: string
  confidence: number
  reason: string
  alternatives?: Array<{ role: string; confidence: number; reason: string }>
}

export interface ForensicFeatures {
  tx_count: number
  native_balance: number
  edge_count: number
  in_degree: number
  out_degree: number
  total_in: number
  total_out: number
  flow_through_ratio: number
  retention_ratio: number
  counterparty_entropy: number
  token_entropy: number
  roundness_score: number
  median_value: number
  median_intertx_gap_seconds?: number | null
  burstiness_score: number
  active_hour_histogram: Record<string, number>
  first_seen?: string
  last_seen?: string
}

export interface ForensicMotif {
  pattern: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  confidence: number
  evidence: string
}

export interface ForensicGraphMetrics {
  nodes: number
  edges: number
  subject_degree: number
  subject_centrality: number
  max_degree: number
  components_estimate: number
  hub_candidates: Array<{ address: string; short: string; degree: number }>
}

export interface LocalLabel {
  id: number
  chain: string
  address: string
  label: string
  category: string
  risk_weight: number
  confidence: number
  source: string
  notes: string
  created_at: string
  updated_at: string
}

export interface ForensicClusterAnalysis {
  communities: Array<{
    id: string
    size: number
    edge_count: number
    density: number
    contains_subject: boolean
    members: string[]
  }>
  subject_community?: {
    id: string
    size: number
    edge_count: number
    density: number
    contains_subject: boolean
    members: string[]
  } | null
  core_number: number
  max_core_number: number
  weighted_degree: number
  anomaly_score: number
  anomaly_level: 'NORMAL' | 'LOW' | 'MEDIUM' | 'HIGH'
  anomaly_terms: Record<string, number>
}

export interface ForensicTaintFlow {
  seed: string
  model: string
  depth: number
  exposed_addresses: Array<{ address: string; short: string; taint: number }>
  top_paths: Array<{ address: string; taint: number; depth: number; path: string[]; tx_hash: string }>
}

export interface ForensicAlgorithmSignal {
  type: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'
  weight: number
  label: string
  detail: string
  confidence?: number
}

export interface ForensicAnalysis {
  address: string
  chain: string
  algorithm_version: string
  confidence: number
  role: ForensicRole
  counterparty_roles: Array<{
    address: string
    short: string
    role: string
    confidence: number
    reason: string
    in_degree: number
    out_degree: number
    flow_through_ratio: number
  }>
  features: ForensicFeatures
  motifs: ForensicMotif[]
  graph_metrics: ForensicGraphMetrics
  cluster_analysis: ForensicClusterAnalysis
  taint_flow: ForensicTaintFlow
  temporal_correlations: Array<{
    type: string
    time_bucket: string
    address_count: number
    addresses: string[]
    confidence: number
  }>
  dex_forensics: {
    swap_count: number
    top_pair?: string
    top_pair_count?: number
    buy_sell_symmetry?: number
    possible_wash_cycle: boolean
    confidence: number
  }
  local_labels: LocalLabel[]
  algorithm_signals: ForensicAlgorithmSignal[]
  evidence_counts: {
    transactions: number
    edges: number
    motifs: number
    temporal_clusters: number
    local_labels?: number
  }
}

export interface ForensicResult {
  run_id: string | null
  analysis: ForensicAnalysis
}

// ── AI Copilot ────────────────────────────────────────────────────────────────

export type AiView = 'brief' | 'evidence' | 'hypotheses' | 'next_steps' | 'narrative' | 'quality'

export interface AiFullReport {
  brief?: {
    executive_summary?: string
    risk_level_interpretation?: string
    top_concerns?: string[]
    confidence_statement?: string
  }
  evidence?: {
    confirmed_facts?: string[]
    risk_signals?: string[]
    graph_observations?: string[]
    temporal_observations?: string[]
    local_label_observations?: string[]
  }
  hypotheses?: Array<{
    title?: string
    confidence?: number
    supporting_evidence?: string[]
    contradicting_evidence?: string[]
    next_checks?: string[]
  }>
  next_steps?: {
    priority_actions?: Array<{
      priority?: 'P1' | 'P2' | 'P3' | string
      action?: string
      why?: string
      expected_evidence?: string
    }>
    data_gaps?: string[]
    preservation_plan?: string[]
  }
  report_narrative?: {
    case_summary?: string
    risk_rationale?: string[]
    timeline_narrative?: string
    limitations?: string[]
    recommended_next_steps?: string[]
  }
  quality_control?: {
    do_not_claim?: string[]
    needs_human_review?: string[]
    source_limitations?: string[]
  }
  analyst_focus?: string
  raw_response?: Record<string, unknown>
  [key: string]: unknown
}

export interface AiInvestigationResult {
  provider: string
  model: string
  analysis: AiFullReport
  usage?: Record<string, unknown>
}

export interface AiStatus {
  provider: string
  provider_name?: string
  kind?: string
  configured: boolean
  model?: string
  base_url?: string
  api_key_env?: string
  model_env?: string
  base_url_env?: string
  env_path?: string
  env_exists?: boolean
  key_length?: number
  notes?: string
  providers?: Array<{
    id: string
    name: string
    kind: string
    key_env: string
    model_env: string
    base_url_env?: string
    default_model?: string
    default_base_url?: string
    notes?: string
  }>
  ok?: boolean
  usage?: Record<string, unknown>
  sample?: unknown
}

// ── Threat Intelligence ──────────────────────────────────────────────────────

export interface ThreatAttributionHypothesis {
  type: string
  candidate: string
  category: string
  confidence: number
  confidence_label: string
  evidence: string[]
  limitations: string[]
}

export interface ThreatTypology {
  name: string
  score: number
  confidence_label: string
  evidence: string[]
}

export interface ThreatPivotLead {
  address: string
  short: string
  priority_score: number
  role_hint: string
  labels: string[]
  reasons: string[]
  recommended_pivots: string[]
  first_seen?: string
  last_seen?: string
}

export interface ThreatIntelResult {
  version: string
  subject: string
  chain: string
  threat_score: number
  threat_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  executive: {
    most_likely_attribution: ThreatAttributionHypothesis
    top_typology: ThreatTypology
    summary: string
  }
  attribution_hypotheses: ThreatAttributionHypothesis[]
  ownership_cluster: {
    subject: string
    cluster_confidence: string
    linked_wallets: Array<{
      address: string
      short: string
      role: string
      confidence: number
      evidence: string[]
    }>
    subject_community?: unknown
    warning: string
  }
  laundering_typologies: ThreatTypology[]
  pivot_leads: ThreatPivotLead[]
  network_dump: {
    seed: string
    nodes: Array<{ id: string; short: string; degree: number; in_volume: number; out_volume: number; is_seed: boolean }>
    edges: Array<{ source: string; target: string; value: number; token: string; hash: string; time: string }>
  }
  forensic: ForensicAnalysis
  investigator_warnings: string[]
}

export interface ThreatIntelResponse {
  threat_intel: ThreatIntelResult
  ai_assessment?: Record<string, unknown> | null
}

// ── Nexus Graph ──────────────────────────────────────────────────────────────

export interface NexusNode {
  id: string
  address: string
  short: string
  arkham_owner?: { name: string }
  community: string
  degree: number
  inbound_volume: number
  outbound_volume: number
  total_volume: number
  bridge_score: number
  risk_score: number
  role_hint: string
  labels: string[]
  motif_count: number
  features: Record<string, unknown>
}

export interface NexusEdge {
  source: string
  target: string
  value: number
  token: string
  hash: string
  time: string
  type: string
}

export interface NexusCorrelation {
  source: string
  target: string
  score: number
  evidence: string[]
  path: string[]
  type: string
}

export interface NexusGraphResult {
  version: string
  seed: string
  chain: string
  summary: {
    node_count: number
    edge_count: number
    correlation_count: number
    community_count: number
    bridge_wallet_count: number
    highest_risk: number
  }
  nodes: NexusNode[]
  edges: NexusEdge[]
  correlations: NexusCorrelation[]
  communities: Array<{
    id: string
    size: number
    edge_count: number
    density: number
    members: string[]
  }>
  bridge_wallets: NexusNode[]
  pivot_queue: NexusNode[]
  paths_from_seed: Array<{ target: string; target_short: string; path: string[]; hops: number }>
  explainability: string[]
}

export interface NexusResponse {
  nexus: NexusGraphResult
  threat_intel?: ThreatIntelResult | null
  ai_assessment?: Record<string, unknown> | null
}

export interface NexusDemixOverlayNode {
  id: string
  address: string
  label: string
  risk_score: number
}

export interface NexusDemixOverlayEdge {
  source: string
  target: string
  method: string
  confidence: number
  reason: string
  tx_hash?: string
}

export interface NexusDemixResponse {
  status: string
  source: string
  event_inventory: {
    events: number
    deposits: number
    withdrawals: number
    source_events: number
    dest_events: number
    chain_events: number
  }
  results: {
    tornado?: DemixResult
    mixer?: DemixResult
    bridge?: DemixResult
    chain_swaps?: ChainSwapResult
    aml?: AmlDemixResult
  }
  skipped: Record<string, string>
  overlay: {
    nodes: NexusDemixOverlayNode[]
    edges: NexusDemixOverlayEdge[]
  }
  summary: {
    risk_score: number
    typology_count: number
    overlay_node_count: number
    overlay_edge_count: number
    engines_run: string[]
  }
  typologies: AmlTypology[]
  disclaimer: string
}

// ── Identity Lens ───────────────────────────────────────────────────────────

export interface IdentityEvidence {
  kind: string
  title: string
  detail: string
  source: string
  confidence: number
  data?: Record<string, unknown>
}

export interface IdentityHypothesis {
  candidate: string
  type: string
  confidence: number
  evidence: string[]
  caveat: string
}

export interface IdentityRelatedWallet {
  address: string
  short: string
  relationship: string
  confidence: number
  risk_score: number
  labels: string[]
  evidence: string[]
}

export interface IdentityProfile {
  version: string
  address: string
  short: string
  chain: string
  likely_entity: string
  username?: string
  profile?: {
    display_name: string
    username: string
    avatar_seed: string
    public_handles: Array<{ platform: string; handle: string; source: string; confidence: number; url?: string }>
    source_count: number
  }
  confidence: number
  confidence_label: 'LOW' | 'MEDIUM' | 'HIGH'
  aliases: string[]
  identity_signals: IdentityEvidence[]
  attribution_hypotheses: IdentityHypothesis[]
  portfolio: {
    chain: string
    native_balance: number
    native_unit: string
    portfolio_usd: number
    tx_count: number
    first_seen: string
    last_seen: string
    tokens: Array<{ symbol: string; name: string; balance: number; usd_value: number; contract: string }>
  }
  aggregate_portfolio?: {
    total_usd: number
    chain_count: number
    active_chain_count: number
    dominant_chain: string
    chains: Array<{
      chain: string
      chainid?: number
      native_balance: number
      native_unit: string
      portfolio_usd: number
      tx_count: number
      token_count: number
      first_seen: string
      last_seen: string
      explorer: string
      source: string
      active: boolean
    }>
  }
  protocol_positions?: Array<{
    name: string
    type: string
    chain: string
    usd_value: number
    balance: number
    symbol: string
    confidence: number
    evidence: string
  }>
  activity: {
    observed_transactions: number
    in_count: number
    out_count: number
    top_tokens: Array<{ token: string; count: number }>
    top_counterparties: Array<{ address: string; short: string; count: number }>
  }
  activity_metrics?: {
    observed_transactions: number
    first_seen: string
    last_seen: string
    graph_nodes: number
    graph_edges: number
    correlations: number
    direct_neighbors: number
  }
  services: Array<{ type: string; name: string; confidence: number; evidence: Record<string, unknown> }>
  related_wallets: IdentityRelatedWallet[]
  risk_flags: string[]
  graph_summary: { nodes: number; edges: number; correlations: number; direct_neighbors: number }
  investigator_notes: string[]
}

export interface IdentityProfileResponse {
  identity_profile: IdentityProfile
}

export interface DeBankTokenInfo {
  id: string
  chain: string
  name: string
  symbol: string
  decimals: number
  logo_url: string
  price: number
  amount: number
  raw_amount: number
  usd_value: number
  is_verified: boolean
  is_core: boolean
  is_wallet: boolean
  protocol_id: string | null
  credit_score: number
  price_24h_change: number
  is_scam: boolean
  is_suspicious: boolean
}

export interface DeBankChainBalance {
  chain_id: string
  chain_name: string
  logo_url: string
  native_token_id: string
  wrapped_token_id: string
  usd_value: number
}

export interface DeBankProtocolPosition {
  protocol_id: string
  protocol_name: string
  chain: string
  logo_url: string
  site_url: string
  tvl: number
  asset_usd_value: number
  debt_usd_value: number
  net_usd_value: number
  detail_types: string[]
  asset_tokens: DeBankTokenInfo[]
}

export interface DeBankNFTItem {
  id: string
  chain: string
  name: string
  collection_id: string
  collection_name: string
  logo_url: string
  amount: number
  usd_value: number
}

export interface DeBankTransaction {
  tx_id: string
  chain: string
  time_at: number
  category: string
  project_id: string | null
  receives: Array<{ token_id: string; amount: number }>
  sends: Array<{ token_id: string; amount: number }>
}

export interface DeBankProfileData {
  address: string
  total_usd_value: number
  chain_balances: DeBankChainBalance[]
  tokens: DeBankTokenInfo[]
  protocols: DeBankProtocolPosition[]
  nfts: DeBankNFTItem[]
  transactions: DeBankTransaction[]
  display_name: string | null
  bio: string
  follower_count: number
  following_count: number
  tags: Array<{ name: string }>
  is_vip: boolean
  is_pro: boolean
  web3_id: string | null
  used_chains: string[]
  source_status?: {
    source: string
    ok: boolean
    degraded: boolean
    message: string
    errors: string[]
  }
}

// ── NFT / TRON Sentinel ─────────────────────────────────────────────────────

export interface NFTTronSignal {
  title: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | string
  score: number
  detail: string
  evidence: string[]
}

export interface NFTTronCollectionLead {
  id: string
  name: string
  count: number
  floor_usd: number
  sample_tokens: Array<{
    name: string
    token_id?: string
    contract?: string
  }>
}

export interface NFTTronMotif {
  id: string
  title: string
  severity: string
  logic: string
  next_steps: string[]
  relevance: number
}

export interface NFTTronPivot {
  title: string
  kind: string
  url: string
}

export interface NFTTronGraphNode {
  id: string
  label: string
  type: string
  risk: number
}

export interface NFTTronGraphEdge {
  source: string
  target: string
  label: string
  weight: number
}

export interface OpenSeaProfileData {
  address: string
  display_name: string | null
  username: string | null
  bio: string
  profile_image_url: string | null
  banner_image_url: string | null
  follower_count: number
  following_count: number
  is_verified: boolean
  is_staff: boolean
  portfolio_value_usd: number
  nft_percentage: number
  token_percentage: number
}

export interface OpenSeaCollection {
  name: string
  slug: string
  image_url: string | null
  category: string
  item_count: number
  floor_price: number
  floor_currency: string
  total_volume: number
  volume_currency: string
}

export interface OpenSeaNFT {
  token_id: string
  name: string
  collection_name: string
  collection_slug: string
  image_url: string | null
  permalink: string | null
  contract_address: string
  schema_name: string
  last_sale_price: number
  last_sale_currency: string
  current_price: number
  current_price_currency: string
  rarity_rank: number | null
}

export interface OpenSeaEvent {
  event_type: string
  created_date: string
  asset_name: string
  asset_token_id: string
  collection_slug: string
  from_address: string | null
  to_address: string | null
  price: number
  currency: string
  transaction_hash: string | null
  quantity: number
}

export interface OpenSeaLookup {
  available: boolean
  degraded: boolean
  error: string | null
  profile: OpenSeaProfileData | null
  counts: { collections: number; nfts: number; events: number }
  collections: OpenSeaCollection[]
  nfts: OpenSeaNFT[]
  events: OpenSeaEvent[]
  profile_url: string
}

export interface NFTTronResult {
  subject: string
  submitted_subject: string
  classification: {
    kind: string
    chain: string
    normalized: string
    valid: boolean
  }
  risk_score: number
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | string
  summary: {
    headline: string
    assessment: string
    focus: string
  }
  signals: NFTTronSignal[]
  nft: {
    source: string
    metrics: {
      nft_count: number
      collection_count: number
      estimated_floor_value_usd: number
      suspicious_token_count: number
      collections: NFTTronCollectionLead[]
    }
    collections: NFTTronCollectionLead[]
  }
  opensea?: OpenSeaLookup
  tron: {
    source: string
    metrics: {
      native_balance_trx: number
      tx_count: number
      trc20_count: number
      usdt_transfer_count: number
      unique_counterparties: number
      contract_call_count: number
      age_days: number | null
    }
    recent_trc20: Array<Record<string, unknown>>
    recent_transactions: Array<Record<string, unknown>>
  }
  motifs: NFTTronMotif[]
  osint_pivots: NFTTronPivot[]
  graph: {
    nodes: NFTTronGraphNode[]
    edges: NFTTronGraphEdge[]
  }
  ton_profile?: TonProfile | null
  investigation_playbook: string[]
  limitations: string[]
  generated_at: number
}

// ── TON (TonViewer-style) profile ─────────────────────────────────────────────

export interface TonJetton {
  symbol: string; name: string; address: string; image: string; decimals: number
  balance: number; price_usd: number | null; value_usd: number | null; verification: string
}
export interface TonNft {
  address: string; name: string; image: string; collection: string
  collection_address: string; verified: boolean; trust: string
}
export interface TonEvent {
  event_id: string; timestamp: number; type: string; status: string; description: string
  value: string; is_scam: boolean; action_count: number
  counterparties: Array<{ address: string; name: string }>
}
export interface TonNftItem {
  address: string; name: string; description: string; image: string
  collection: { name: string; address: string; description: string }
  owner: { address: string; name: string }
  verified: boolean; trust: string; index?: number | string; dns?: string | null
  on_sale: boolean; sale_price: string | null
  attributes: Array<{ trait: string; value: unknown }>
  error?: string
}
// ── TONScan enrichment (tonscan.com scraper) ──────────────────────────────────
export interface TonScanNftItem {
  name: string
  image?: string
  sale_status: 'for_sale' | 'not_for_sale' | 'sold' | 'unknown'
  last_sale_ton?: number | null
}
export interface TonScanProfile {
  tonscan_url: string
  tonscan_name: string
  tonscan_dns: string
  tonscan_description: string
  tonscan_entity_type: string
  tonscan_balance: string
  tonscan_contract_hash: string
  tonscan_interfaces: string[]
  tonscan_floor_price: string
  tonscan_volume: string
  tonscan_nft_items: TonScanNftItem[]
  tonscan_nft_images: string[]
}
export interface TonProfile {
  address: { given: string; raw: string; bounceable: string; non_bounceable: string; testnet: boolean }
  kind: 'wallet' | 'nft_item' | 'nft_collection' | 'jetton_master' | 'contract' | string
  explorer: string
  tonscan: TonScanProfile | null
  ton_price_usd: number | null
  account: {
    status: string; balance_ton: number; balance_usd: number | null; name: string; icon: string
    is_scam: boolean; is_wallet: boolean; interfaces: string[]; last_activity: number; get_methods: string[]
  }
  totals: {
    balance_ton: number; balance_usd: number | null; jetton_count: number
    jetton_value_usd: number | null; nft_count: number; portfolio_usd: number | null
  }
  jettons: TonJetton[]
  nfts: TonNft[]
  nft_item: TonNftItem | null
  events: TonEvent[]
  risk_score: number; risk_level: string
  signals: NFTTronSignal[]
  errors: string[]
  generated_at: number
  disclaimer: string
}

// ── Compliance: Sanctions / KYV / Regulatory / Demixing (v3) ─────────────────

export interface SanctionsMatch {
  uid: string
  name: string
  type: string
  programs: string[]
  country: string
  source: string
  listed_on: string
  aliases: string[]
  matched_chain?: string
  score?: number
}

export interface SanctionsScreenResult {
  address: string
  chain: string
  sanctioned: boolean
  match_count: number
  matches: SanctionsMatch[]
  checked_at: string
}

export interface SanctionsSearchResult {
  query: string
  match_count: number
  matches: SanctionsMatch[]
  checked_at: string
}

export interface SanctionsEntityAddress {
  address: string
  chain: string
}

export interface SanctionsEntityDetail {
  uid: string
  name: string
  type: string
  programs: string[]
  country: string
  source: string
  listed_on: string
  aliases: string[]
  updated_at: string
  addresses: SanctionsEntityAddress[]
  address_count: number
}

export interface SanctionsStatus {
  entity_count: number
  address_count: number
  seeded_at: string | null
  refreshed_at: string | null
  sources: Array<{ source: string; entities: number }>
  available_feeds: Array<{ name: string; url: string }>
}

export interface VaspInfo {
  name: string
  type: string
  country: string
  jurisdiction: string
  label: string
  chain: string
  source: string
}

export interface KyvResult {
  address: string
  is_vasp: boolean
  vasp: VaspInfo | null
}

export interface RegulatoryReport {
  report_type: string
  report_standard: string
  generated_at: string
  markdown: string
  [key: string]: unknown
}

export interface DemixCandidate {
  confidence: number
  reasons: string[]
  [key: string]: unknown
}

export interface DemixLink {
  best_confidence: number
  candidate_count: number
  candidates: DemixCandidate[]
  [key: string]: unknown
}

export interface DemixResult {
  method: string
  high_confidence_links: number
  links: DemixLink[]
  disclaimer: string
  risk?: {
    score: number
    level: string
    indicator_count?: number
    chain_count?: number
    component_count?: number
    typology_count?: number
  }
  typologies?: AmlTypology[]
  [key: string]: unknown
}

export interface AmlTypology {
  code: string
  title: string
  severity: string
  detail: string
  confidence: number
  evidence: string[]
}

export interface ChainSwapResult extends DemixResult {
  method: string
  events_analyzed: number
  chain_swap_count: number
  chains_involved: string[]
  protocols_seen: string[]
}

export interface AmlDemixResult {
  method: string
  risk: {
    score: number
    level: string
    component_count: number
    typology_count: number
  }
  summary: string
  components: {
    mixer?: DemixResult | null
    bridge?: DemixResult | null
    chain_swaps: ChainSwapResult
  }
  typologies: AmlTypology[]
  recommended_actions: string[]
  disclaimer: string
}

// ── Phase 1: Multi-Route Pathfinding ────────────────────────────────────────

export interface PathHop {
  from:     string
  to:       string
  tx_hash:  string
  value:    number
  token:    string
  time:     string
}

export interface PathDestination {
  id:    string
  label: string
  role:  string
  risk:  number
}

export interface InvestigationPath {
  strategy:    'shortest' | 'highest_value' | 'highest_risk' | 'most_recent' | 'mixer_routed' | 'bridge_routed'
  path:        string[]
  hops:        PathHop[]
  hop_count:   number
  total_value: number
  max_risk:    number
  latest_ts:   number
  destination: PathDestination
  confidence:  number
}

export interface PathfinderResult {
  source:         string
  by_strategy:    Record<string, InvestigationPath | null>
  unique_paths:   InvestigationPath[]
  path_count:     number
  target_count:   number
  max_confidence: number
}

export interface PathfinderResponse {
  status: string
  paths:  PathfinderResult
}

// ── Phase 1: Wallet Clustering ───────────────────────────────────────────────

export interface WalletCluster {
  cluster_id:   string
  lead_address: string
  members:      string[]
  member_count: number
  methods:      string[]
  confidence:   number
  evidence:     string[]
  finding:      string
  disclaimer:   string
}

export interface ClusteringResult {
  clusters:          WalletCluster[]
  cluster_count:     number
  total_clustered:   number
  methods_applied:   string[]
  raw_signal_count:  number
  disclaimer:        string
  summary:           string
}

export interface ClusteringResponse {
  status:     string
  clustering: ClusteringResult
}

// ── Phase 1: Cashout Detection ───────────────────────────────────────────────

export interface CashoutIndicator {
  type:         string
  severity:     'high' | 'medium' | 'low'
  destination?: string
  dest_label?:  string
  value?:       number
  total_value?: number
  tx_count?:    number
  description:  string
  confidence:   number
  [key: string]: unknown
}

export interface CashoutRisk {
  level:        'critical' | 'high' | 'medium' | 'low'
  score:        number
  summary:      string
  high_count:   number
  medium_count: number
}

export interface CashoutResult {
  subject:               string
  indicators:            CashoutIndicator[]
  indicator_count:       number
  risk:                  CashoutRisk
  primary_cashout_dest:  string | null
  exchange_exposure:     boolean
  stablecoin_exit:       boolean
  structuring_detected:  boolean
}

export interface CashoutResponse {
  status:  string
  cashout: CashoutResult
}

// ── Phase 2: TX Interpretation Layer ────────────────────────────────────────

export interface TxInterpretEvent {
  seq:          number
  type:         string
  icon?:        string
  actor:        string
  actor_short:  string
  timestamp?:   string
  description:  string
  severity:     'info' | 'medium' | 'high' | 'critical'
}

export interface TxMethodInfo {
  selector:   string | null
  name:       string
  category:   string
  annotation: string
}

export interface TxContractInfo {
  name: string | null
  type: string
}

export interface TxRiskFlag {
  flag:     string
  severity: string
  detail:   string
}

export interface TxInterpretation {
  tx_hash:             string
  chain:               string
  method:              TxMethodInfo
  to_contract:         TxContractInfo
  what_happened:       TxInterpretEvent[]
  narrative:           string
  token_naratives:     string[]
  internal_naratives:  string[]
  approval_warnings:   Array<{ type: string; severity: string; detail: string; [k: string]: unknown }>
  risk_flags:          TxRiskFlag[]
  event_count:         number
  has_swap:            boolean
  has_bridge:          boolean
  has_mixer:           boolean
  has_approval:        boolean
}

export interface TxInterpretResponse {
  status:         string
  interpretation: TxInterpretation
}

// ── Phase 2: Cross-Chain Trace ───────────────────────────────────────────────

export interface BridgeHop {
  type:           string
  bridge_name:    string
  bridge_address: string
  dest_chains:    string[]
  direction:      'outbound' | 'inbound'
  value:          number
  token:          string
  timestamp:      number
  tx_hash:        string
  confidence:     number
  description:    string
}

export interface ValueTimeMatch {
  type:           string
  out_address:    string
  in_address:     string
  value:          number
  value_diff_pct: number
  time_diff_sec:  number
  out_tx:         string
  in_tx:          string
  confidence:     number
  description:    string
}

export interface CrossChainRisk {
  level:           string
  score:           number
  bridge_hops:     number
  value_matches:   number
  wrapped_assets:  number
  stablecoin_hops: number
}

export interface CrossChainResult {
  subject:            string
  bridge_hops:        BridgeHop[]
  value_matches:      ValueTimeMatch[]
  wrapped_movements:  Array<{ type: string; token: string; out_total: number; in_total: number; confidence: number; description: string }>
  stablecoin_hops:    Array<{ type: string; token: string; out_usd: number; in_usd: number; net_usd: number; tx_count: number; confidence: number; description: string }>
  crosschain_paths:   unknown[]
  risk:               CrossChainRisk
  bridges_seen:       string[]
  chains_involved:    string[]
  total_findings:     number
  summary:            string
}

export interface CrossChainResponse {
  status:     string
  crosschain: CrossChainResult
}

// ════════════════════════════════════════════════════════════════════════════
// V2 FEATURE TYPES
// ════════════════════════════════════════════════════════════════════════════

// ── F1: Alert delivery ───────────────────────────────────────────────────────
export interface AlertDestination {
  id: string
  name: string
  kind: 'webhook' | 'email' | 'telegram' | 'sse' | 'inapp'
  config: Record<string, unknown>
  enabled: boolean
  created_at: string
}
export interface AlertDelivery {
  id: string
  notification_id: string
  destination_id: string
  destination_name?: string
  destination_kind?: string
  status: string
  attempts: number
  last_error: string
  delivered_at: string
  created_at: string
}

// ── F2: Saved investigations ─────────────────────────────────────────────────
export interface SavedInvestigation {
  id: string
  subject: string
  chain: string
  name: string
  case_id?: string
  params?: Record<string, unknown>
  graph: { nodes?: unknown[]; edges?: unknown[]; [k: string]: unknown }
  node_count: number
  edge_count: number
  created_at: string
  updated_at: string
}

// ── F4: Feed sync ────────────────────────────────────────────────────────────
export interface FeedSyncState {
  feed_id: string
  feed_name: string
  last_synced: string
  last_status: string
  record_count: number
  new_count: number
  error: string
  updated_at: string
}
export interface FeedRecord {
  id: number
  feed_id: string
  address: string
  chain: string
  entity: string
  designation: string
  source_url: string
  first_seen: string
}
export interface FeedDiffAlert {
  id: string
  address: string
  chain: string
  feed_id: string
  entity: string
  case_id: string
  created_at: string
  reviewed: number
}

// ── F5: Feed ingestion ───────────────────────────────────────────────────────
export interface FeedImport {
  id: string
  source: string
  filename: string
  status: string
  total_rows: number
  imported_rows: number
  approved_rows: number
  error: string
  imported_by: string
  created_at: string
  updated_at: string
}
export interface FeedImportRow {
  id: number
  import_id: string
  address: string
  chain: string
  label: string
  category: string
  entity: string
  risk_weight: number
  confidence: number
  status: string
  reviewed_by: string
  reviewed_at: string
}

// ── F7: Entity investigation ─────────────────────────────────────────────────
export interface EntityInvestigationResult {
  entity_addresses: string[]
  chain: string
  address_count: number
  aggregate_flows: { total_in: number; total_out: number; net: number; internal: number }
  clusters: unknown[]
  cluster_count: number
  inter_cluster_links: unknown[]
  external_counterparties: Array<{ address: string; in: number; out: number; txs: number; type: string; label: string }>
  total_edges: number
  disclaimer: string
}

// ── F8: Time-travel ──────────────────────────────────────────────────────────
export interface TimeTravelResult {
  address: string
  chain: string
  target_timestamp: number
  target_iso: string
  balances: Record<string, number>
  cumulative_in: number
  cumulative_out: number
  net: number
  counterparty_count: number
  top_counterparties: Array<{ address: string; in: number; out: number; txs: number }>
  active_edges: number
  disclaimer: string
}
export interface TimeTravelPoint {
  timestamp: number
  iso: string
  net_balance: number
  counterparties: number
  cumulative_in: number
}

// ── F9: Deep trace ───────────────────────────────────────────────────────────
export interface DeepTraceResult {
  chain: string
  subject: string
  hops_completed?: number
  node_count: number
  edge_count: number
  nodes?: Array<{ address: string; chain: string; type: string }>
  edges?: Array<{ source: string; target: string; value: number; token: string; tx_hash: string; timestamp: string; hop?: number }>
  engine: string
  disclaimer: string
  [k: string]: unknown
}

// ── F10: Case QA ─────────────────────────────────────────────────────────────
export interface CaseQaResult {
  answer: string
  citations: Array<{ evidence_id: string; valid: boolean }>
  context_used: { addresses: number; evidence_retrieved: number; notes: number }
  ai_used: boolean
  disclaimer?: string
}

// ── F11: Custody report ──────────────────────────────────────────────────────
export interface CustodyReport {
  case_id: string
  case_name: string
  generated_at: string
  custody_integrity: { chain_valid: boolean; records_checked: number; problems: unknown[]; chain_tip: string }
  evidence_summary: { total: number; avg_quality: number; by_type: Record<string, unknown> }
  audit_trail: Array<{ timestamp: string; actor: string; action: string; detail: string }>
  case_events: Array<{ timestamp: string; actor: string; action: string; detail: string }>
  exports: Array<{ id: string; subject: string; title: string; format: string; created_at: string }>
  summary: {
    total_audit_entries: number
    total_case_events: number
    total_exports: number
    actor_activity: Record<string, number>
    action_counts: Record<string, number>
    first_activity: string
    last_activity: string
  }
}

// ── F12: Collaboration ───────────────────────────────────────────────────────
export interface CollabPresence {
  user_id: string
  name: string
  cursor: Record<string, unknown> | null
  panel: string
  last_seen: number
}

// ── Phase 3: Investigation Timeline ─────────────────────────────────────────

export interface TimelineEvent {
  id:           string
  timestamp:    string
  ts_epoch:     number
  type:         string
  icon:         string
  color:        string
  actor:        string
  actor_short:  string
  counterparty: string
  cp_short:     string
  value:        number
  token:        string
  description:  string
  severity:     'info' | 'medium' | 'high' | 'critical'
  source:       string
  tx_hash:      string
  metadata:     Record<string, unknown>
}

export interface TimelineResult {
  address:     string
  events:      TimelineEvent[]
  event_count: number
  total_raw:   number
  date_range:  { earliest: string; latest: string }
  stats:       { by_type: Record<string, number>; by_severity: Record<string, number> }
}

export interface TimelineResponse {
  status:   string
  timeline: TimelineResult
}

// ── Phase 3: Evidence Vault ──────────────────────────────────────────────────

export interface EvidenceRecord {
  id:            string
  case_id:       string
  evidence_type: string
  title:         string
  subject:       string
  chain:         string
  content_hash:  string
  quality_score: number
  tags:          string[]
  analyst_notes: string
  created_at:    string
  content?:      Record<string, unknown>
}

export interface EvidenceSummary {
  case_id:     string
  total:       number
  avg_quality: number
  by_type:     Record<string, { count: number; avg_quality: number }>
}

export interface AuditLogEntry {
  id:          number
  evidence_id: string
  action:      string
  actor:       string
  detail:      string
  timestamp:   string
}

// ── Phase 4: AI Investigation Agent ─────────────────────────────────────────

export interface AgentQueryType {
  id:          string
  label:       string
  description: string
  icon:        string
}

export interface AgentQueryResult {
  query_type:   string
  query_label:  string
  result:       Record<string, unknown>
  raw_content:  string
  model:        string
  usage:        Record<string, unknown>
  analyst_note: string
  has_error:    boolean
}

export interface AgentRunRequest {
  query_type:  string
  free_text?:  string
  address?:    string
  chain?:      string
  intel?:      unknown
  risk?:       unknown
  forensic?:   unknown
  case?:       unknown
  case_b?:     unknown
  cluster?:    unknown
  cashout?:    unknown
  paths?:      unknown
  crosschain?: unknown
  timeline?:   unknown
  nodes?:      unknown[]
  edges?:      unknown[]
  max_tokens?: number
  temperature?: number
}

export interface AgentResponse {
  status:      string
  query_type:  string
  query_label: string
  result:      Record<string, unknown>
  raw_content: string
  model:       string
  usage:       Record<string, unknown>
  analyst_note: string
  has_error:   boolean
}

// ── Victim Report & Scam Intelligence ────────────────────────────────────────

export interface VictimReport {
  id:               string
  case_id:          string | null
  scam_type:        string
  scammer_address:  string
  victim_address:   string
  amount_usd:       number
  token:            string
  chain:            string
  incident_date:    string
  report_date:      string
  description:      string
  contact_name:     string
  contact_email:    string
  jurisdiction:     string
  status:           string
  evidence_hashes:  string[]
  tx_hashes:        string[]
  tags:             string[]
  analyst_notes:    string | null
  created_at:       string
  updated_at:       string
}

export interface ScamCluster {
  scammer_address:  string
  victim_count:     number
  total_damage_usd: number
  scam_types:       string[]
  chains:           string[]
  first_incident:   string | null
  last_incident:    string | null
}

export interface ScamTypeBreakdown {
  scam_type: string
  count:     number
  damage:    number
}

export interface ScamIntelSummary {
  total_reports:    number
  unique_scammers:  number
  total_damage_usd: number
  chains_affected:  number
  by_scam_type:     ScamTypeBreakdown[]
  by_status:        Array<{ status: string; count: number }>
  recent_reports:   Partial<VictimReport>[]
  top_scammers:     Array<{ scammer_address: string; victims: number; damage: number; types: string[] }>
}

export interface ScamTypeInfo {
  id:       string
  label:    string
  severity: string
}

export interface ExportBundle {
  bundle_id:         string
  generated_at:      string
  report_count:      number
  scammer_addresses: string[]
  total_damage_usd:  number
  scam_types:        string[]
  chains:            string[]
  jurisdictions:     string[]
  reports:           VictimReport[]
  disclaimer:        string
}
