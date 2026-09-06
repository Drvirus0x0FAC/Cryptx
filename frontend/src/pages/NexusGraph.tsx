/**
 * NexusGraph - Advanced force-directed investigation graph.
 * Professional OSINT features:
 *  • d3-force physics simulation      • Cursor-centred zoom + pan
 *  • Node drag + double-click pin     • Right-click context menu
 *  • BFS path-finding + highlight     • Minimap navigator
 *  • Node size modes                  • Animated flow edges
 *  • Search highlight (not filter)    • PNG / JSON export
 *  • Custom node tags                 • Focus mode
 *  • Community / radial layouts       • Hidden node restore
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force'
import type { SimulationNodeDatum, Simulation } from 'd3-force'
import {
  Activity, AlertTriangle, Bot, BrainCircuit, Copy, Download, ExternalLink,
  GitBranch, Loader2, Network, Route, Search, Share2, Shield, Target,
  X, Zap, ZoomIn, ZoomOut, RotateCcw, EyeOff, Tag,
  MapPin, Navigation, Layers, Scan, Fingerprint,
  Database, Clock3, ShieldAlert, FileText, ChevronDown, ChevronRight,
  Wallet, UserRound, MessageCircle, ArrowLeft, GitMerge, LayoutDashboard,
  Sparkles, Info,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { analyzeForensics, analyzeNexusGraph, buildIdentityProfile, fetchDeBankProfile, forensicReportUrl, lookupAddress, runNexusDemix, traceAddress } from '../api/client'
import { holisticTrace, type HolisticNode, type HolisticEdge } from '../api/holistic'
import CounterpartyAnalytics from '../components/CounterpartyAnalytics'
import NexusProgressCinema, { NexusProgressStrip } from '../components/NexusProgressCinema'
import NexusLaunchConsole from '../components/NexusLaunchConsole'
import { ChainGlyph, glyphKey } from '../lib/chainGlyphs'
import { computeFlowLayout, relayoutSubset } from '../lib/nexus/flowLayout'
import {
  useTweenView, usePositionAnimator, fitViewTransform,
  easeInOutCubic, HOME_VIEW, LAYOUT_MS, ISOLATE_MS,
} from '../lib/nexus/graphAnim'
import {
  buildSubgraph, subgraphFromBundles, subgraphFromPath, toSubgraphWorkspace,
  subgraphIsEmpty, toNexusGraphResult,
  type SubgraphKind, type SubgraphResult, type SubgraphWorkspaceModel,
} from '../lib/nexus/subgraph'
import {
  NexusEdgeLayer, mergeEdgeTheme, darkEdgeTheme, lightEdgeTheme,
  type EdgeDirection, type TxBundleLike,
} from '../components/nexus/NexusEdgeLayer'
import { createBoardFromNexus, boardsForRef, type BoardLink } from '../api/boards'
import { GraphNodeKit, classifyEntity, riskStyle } from '../lib/graphkit'
import type { DeBankProfileData, ForensicAnalysis as ForensicAnalysisData, GraphEdge, GraphNode, IdentityProfile, NexusDemixResponse, NexusGraphResult, NexusNode, NexusEdge, NexusResponse, ThreatIntelResult, TraceGraph } from '../types'
import NexusIntelPanel from '../components/NexusIntelPanel'

// ── Types ─────────────────────────────────────────────────────────────────────
type SimNode = NexusNode & SimulationNodeDatum & {
  x: number; y: number; vx: number; vy: number
  fx: number | null; fy: number | null
}
type SizeMode = 'risk' | 'degree' | 'volume' | 'uniform'
type LayoutMode = 'flow' | 'force' | 'community' | 'radial'
type EdgeMode = 'bundled' | 'detail'
type EdgeScope = 'all' | 'selected' | 'path'
type View = { x: number; y: number; z: number }
type ExpandOpts = { hops?: number; mode?: 'linear' | 'wide'; direction?: 'in' | 'out' | 'both' }
type GraphOverlay = { nodes: NexusNode[]; edges: NexusEdge[] }
type IconComponent = LucideIcon
type DetailSection = 'ownership' | 'links' | 'paths' | 'pivots' | 'bridges'
type SubgraphWorkspace = SubgraphWorkspaceModel
type TxBundle = {
  key: string
  source: string
  target: string
  value: number
  count: number
  token: string
  hashes: string[]
  type: string
  latestTime: string
  edges: NexusEdge[]
}

const COMM_COLORS = ['#ff4052', '#ff9f0a', '#ff3b6b', '#00ff88', '#ff2d55', '#0a84ff', '#ffd60a']
const MM_W = 160, MM_H = 90

// ── Helpers ───────────────────────────────────────────────────────────────────
// Now delegates to the unified graphkit risk palette. This fixes the old bug
// where low-risk nodes returned crimson #ff4052 (same as the seed), making
// clean wallets visually echo the suspect subject. Minimap dots + edge colors
// now use the correct green→yellow→amber→red scale too.
function riskColor(score: number) {
  return riskStyle(score).color
}

function communityColor(community: string) {
  let h = 0
  for (let i = 0; i < community.length; i++) h = (h * 31 + community.charCodeAt(i)) & 0xffff
  return COMM_COLORS[h % COMM_COLORS.length]
}

function nodeRadius(n: NexusNode, mode: SizeMode): number {
  const base = 18
  if (mode === 'risk')   return base + Math.min(n.risk_score / 7, 20)
  if (mode === 'degree') return base + Math.min(n.degree * 2.2, 20)
  if (mode === 'volume') return base + Math.min(Math.log1p(n.total_volume) * 2.2, 20)
  return base + 7
}

function edgePairKey(source: string, target: string) {
  return `${source}|${target}`
}

function bundleTxEdges(edges: NexusEdge[]): TxBundle[] {
  const bundles = new Map<string, TxBundle>()
  edges.forEach(edge => {
    const key = edgePairKey(edge.source, edge.target)
    const existing = bundles.get(key)
    if (!existing) {
      bundles.set(key, {
        key,
        source: edge.source,
        target: edge.target,
        value: Number(edge.value || 0),
        count: 1,
        token: edge.token || '',
        hashes: edge.hash ? [edge.hash] : [],
        type: edge.type || 'transaction',
        latestTime: edge.time || '',
        edges: [edge],
      })
      return
    }
    existing.value += Number(edge.value || 0)
    existing.count += 1
    if (edge.hash && existing.hashes.length < 4) existing.hashes.push(edge.hash)
    if (!existing.token && edge.token) existing.token = edge.token
    if (edge.time && edge.time > existing.latestTime) existing.latestTime = edge.time
    existing.edges.push(edge)
  })
  return Array.from(bundles.values()).sort((a, b) => b.value - a.value || b.count - a.count)
}

function tacticalNodeLabel(n: NexusNode) {
  const owner = n.arkham_owner?.name
  if (owner) return owner
  if (n.role_hint && n.role_hint !== 'unknown') return n.role_hint
  return shortAddr(n.address)
}

function flowValueLabel(value: number, token: string) {
  const amount = Number(value || 0)
  const formatted = amount >= 1_000_000
    ? amount.toLocaleString(undefined, { maximumFractionDigits: 1 })
    : amount >= 1_000
      ? amount.toLocaleString(undefined, { maximumFractionDigits: 2 })
      : amount.toLocaleString(undefined, { maximumFractionDigits: 4 })
  return `${formatted}${token ? ` ${token}` : ''}`
}

const CHAIN_BADGES: Record<string, { label: string; fill: string; stroke: string; text: string }> = {
  eth: { label: 'ETH', fill: '#627eea', stroke: '#9fb1ff', text: '#ffffff' },
  ethereum: { label: 'ETH', fill: '#627eea', stroke: '#9fb1ff', text: '#ffffff' },
  btc: { label: 'BTC', fill: '#f7931a', stroke: '#ffd08a', text: '#1f1300' },
  bitcoin: { label: 'BTC', fill: '#f7931a', stroke: '#ffd08a', text: '#1f1300' },
  tron: { label: 'TRX', fill: '#eb0029', stroke: '#ff7a8e', text: '#ffffff' },
  trx: { label: 'TRX', fill: '#eb0029', stroke: '#ff7a8e', text: '#ffffff' },
  bsc: { label: 'BNB', fill: '#f3ba2f', stroke: '#ffe38a', text: '#1d1600' },
  bnb: { label: 'BNB', fill: '#f3ba2f', stroke: '#ffe38a', text: '#1d1600' },
  polygon: { label: 'POL', fill: '#8247e5', stroke: '#c5a6ff', text: '#ffffff' },
  matic: { label: 'POL', fill: '#8247e5', stroke: '#c5a6ff', text: '#ffffff' },
  arbitrum: { label: 'ARB', fill: '#28a0f0', stroke: '#98d8ff', text: '#06131d' },
  optimism: { label: 'OP', fill: '#ff0420', stroke: '#ff8d9a', text: '#ffffff' },
  base: { label: 'BASE', fill: '#0052ff', stroke: '#83a8ff', text: '#ffffff' },
  gnosis: { label: 'GNO', fill: '#04795b', stroke: '#58d6b5', text: '#ffffff' },
  avax: { label: 'AVAX', fill: '#e84142', stroke: '#ff9d9e', text: '#ffffff' },
  avalanche: { label: 'AVAX', fill: '#e84142', stroke: '#ff9d9e', text: '#ffffff' },
  solana: { label: 'SOL', fill: '#14f195', stroke: '#91ffd1', text: '#05140e' },
  xrp: { label: 'XRP', fill: '#23292f', stroke: '#8a949e', text: '#ffffff' },
  litecoin: { label: 'LTC', fill: '#345d9d', stroke: '#9db9e7', text: '#ffffff' },
  dogecoin: { label: 'DOGE', fill: '#c2a633', stroke: '#f6df79', text: '#161203' },
  bch: { label: 'BCH', fill: '#8dc351', stroke: '#d5ff9f', text: '#091100' },
  zcash: { label: 'ZEC', fill: '#ecb244', stroke: '#ffe1a0', text: '#1c1200' },
  cardano: { label: 'ADA', fill: '#0033ad', stroke: '#86a2ff', text: '#ffffff' },
  polkadot: { label: 'DOT', fill: '#e6007a', stroke: '#ff8dcc', text: '#ffffff' },
  cosmos: { label: 'ATOM', fill: '#2e3148', stroke: '#9ba3d8', text: '#ffffff' },
  near: { label: 'NEAR', fill: '#000000', stroke: '#a7f3d0', text: '#ffffff' },
  aptos: { label: 'APT', fill: '#0d0d0d', stroke: '#b7f7df', text: '#ffffff' },
  sui: { label: 'SUI', fill: '#6fbcf0', stroke: '#c7ebff', text: '#05111a' },
  ton: { label: 'TON', fill: '#0098ea', stroke: '#8fdcff', text: '#ffffff' },
  algorand: { label: 'ALGO', fill: '#111111', stroke: '#d9d9d9', text: '#ffffff' },
  stellar: { label: 'XLM', fill: '#111827', stroke: '#cbd5e1', text: '#ffffff' },
  kas: { label: 'KAS', fill: '#70c7ba', stroke: '#c9f5ec', text: '#06140f' },
  kaspa: { label: 'KAS', fill: '#70c7ba', stroke: '#c9f5ec', text: '#06140f' },
  ftm: { label: 'FTM', fill: '#13b5ec', stroke: '#9fe0f9', text: '#ffffff' },
  fantom: { label: 'FTM', fill: '#13b5ec', stroke: '#9fe0f9', text: '#ffffff' },
  mnt: { label: 'MNT', fill: '#000000', stroke: '#7ee787', text: '#ffffff' },
  mantle: { label: 'MNT', fill: '#000000', stroke: '#7ee787', text: '#ffffff' },
  glmr: { label: 'GLMR', fill: '#ff2e56', stroke: '#ff9db3', text: '#ffffff' },
  moonbeam: { label: 'GLMR', fill: '#ff2e56', stroke: '#ff9db3', text: '#ffffff' },
  zep: { label: 'ZETA', fill: '#1c1c1c', stroke: '#8b5cf6', text: '#ffffff' },
  zetachain: { label: 'ZETA', fill: '#1c1c1c', stroke: '#8b5cf6', text: '#ffffff' },
  stx: { label: 'STX', fill: '#5546ff', stroke: '#b3a8ff', text: '#ffffff' },
  stacks: { label: 'STX', fill: '#5546ff', stroke: '#b3a8ff', text: '#ffffff' },
  icp: { label: 'ICP', fill: '#f15a24', stroke: '#fcc8b3', text: '#1a0500' },
}

function inferNodeChain(n: NexusNode, graphChain: string): string {
  const features = n.features || {}
  const candidates = [
    features.chain,
    features.source_chain,
    features.dest_chain,
    features.blockchain,
    features.network,
    graphChain,
    n.labels?.join(' '),
    n.role_hint,
  ].map(v => String(v || '').toLowerCase())
  const joined = candidates.join(' ')
  for (const key of Object.keys(CHAIN_BADGES)) {
    if (joined.includes(key)) return key
  }
  const address = (n.address || n.id || '').toLowerCase()
  if (address.startsWith('bc1') || /^[13][a-km-zA-HJ-NP-Z1-9]{25,}$/.test(n.address || '')) return 'btc'
  if ((n.address || '').startsWith('T')) return 'tron'
  if (address.startsWith('t1') || address.startsWith('t3')) return 'zcash'
  if (address.startsWith('0x')) return (graphChain && graphChain !== 'auto') ? graphChain.toLowerCase() : 'eth'
  return (graphChain || 'eth').toLowerCase()
}

function chainBadge(n: NexusNode, graphChain: string) {
  const key = inferNodeChain(n, graphChain)
  return CHAIN_BADGES[key] || {
    label: key.slice(0, 4).toUpperCase() || 'UNK',
    fill: '#1f2937',
    stroke: '#94a3b8',
    text: '#ffffff',
  }
}

function shortAddr(addr: string) {
  return addr.length > 16 ? `${addr.slice(0, 8)}…${addr.slice(-5)}` : addr
}

function pct(v: number | null | undefined) { return `${Math.round((v ?? 0) * 100)}%` }
function money(v: number | null | undefined) {
  const value = Number(v || 0)
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

function arr<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : []
}

function num(value: unknown, fallback = 0): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function textValue(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value.trim() || fallback
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value && typeof value === 'object') {
    const obj = value as Record<string, unknown>
    for (const key of ['name', 'ens', 'reverse_name', 'domain', 'label', 'candidate', 'value']) {
      const nested = obj[key]
      if (typeof nested === 'string' && nested.trim()) return nested.trim()
    }
    return fallback
  }
  return fallback
}

function normalizeIdentityProfile(raw: unknown, fallbackAddress: string): IdentityProfile {
  const data = (raw && typeof raw === 'object' ? raw : {}) as Partial<IdentityProfile>
  const address = String(data.address || fallbackAddress || '').trim().toLowerCase()
  const portfolio = (data.portfolio && typeof data.portfolio === 'object' ? data.portfolio : {}) as Partial<IdentityProfile['portfolio']>
  const activity = (data.activity && typeof data.activity === 'object' ? data.activity : {}) as Partial<IdentityProfile['activity']>
  const graphSummary = (data.graph_summary && typeof data.graph_summary === 'object' ? data.graph_summary : {}) as Partial<IdentityProfile['graph_summary']>
  const confidence = num(data.confidence, 0.12)
  const confidenceLabel = data.confidence_label === 'HIGH' || data.confidence_label === 'MEDIUM' || data.confidence_label === 'LOW'
    ? data.confidence_label
    : confidence >= 0.74 ? 'HIGH' : confidence >= 0.45 ? 'MEDIUM' : 'LOW'

  return {
    version: String(data.version || 'identity-lens-v1'),
    address,
    short: String(data.short || shortAddr(address)),
    chain: String(data.chain || portfolio.chain || ''),
    likely_entity: textValue(data.likely_entity, 'Unknown public entity'),
    username: textValue(data.username),
    profile: data.profile && typeof data.profile === 'object' ? {
      display_name: textValue((data.profile as Record<string, unknown>).display_name, textValue(data.likely_entity, 'Unknown public entity')),
      username: textValue((data.profile as Record<string, unknown>).username),
      avatar_seed: textValue((data.profile as Record<string, unknown>).avatar_seed, address.slice(-8)),
      public_handles: arr<Record<string, unknown>>((data.profile as Record<string, unknown>).public_handles).map(handle => ({
        platform: textValue(handle.platform, 'Public Profile'),
        handle: textValue(handle.handle, ''),
        source: textValue(handle.source, 'public-record'),
        confidence: num(handle.confidence),
        url: textValue(handle.url, ''),
      })).filter(handle => handle.handle),
      source_count: num((data.profile as Record<string, unknown>).source_count),
    } : undefined,
    confidence,
    confidence_label: confidenceLabel,
    aliases: arr(data.aliases).map(alias => textValue(alias)).filter(Boolean),
    identity_signals: arr<Record<string, unknown>>(data.identity_signals).map(sig => ({
      kind: textValue(sig.kind, 'identity-signal'),
      title: textValue(sig.title, 'Identity signal'),
      detail: textValue(sig.detail, 'Evidence signal returned without detail.'),
      source: textValue(sig.source, 'identity-lens'),
      confidence: num(sig.confidence),
      data: sig.data && typeof sig.data === 'object' ? sig.data as Record<string, unknown> : {},
    })),
    attribution_hypotheses: arr<Record<string, unknown>>(data.attribution_hypotheses).map(hyp => ({
      candidate: textValue(hyp.candidate, 'Unknown candidate'),
      type: textValue(hyp.type, 'attribution-hypothesis'),
      confidence: num(hyp.confidence),
      evidence: arr(hyp.evidence).map(ev => textValue(ev)).filter(Boolean),
      caveat: textValue(hyp.caveat, 'Validate this hypothesis with corroborating evidence before reporting.'),
    })),
    portfolio: {
      chain: String(portfolio.chain || data.chain || ''),
      native_balance: num(portfolio.native_balance),
      native_unit: String(portfolio.native_unit || ''),
      portfolio_usd: num(portfolio.portfolio_usd),
      tx_count: num(portfolio.tx_count),
      first_seen: String(portfolio.first_seen || ''),
      last_seen: String(portfolio.last_seen || ''),
      tokens: arr<Record<string, unknown>>(portfolio.tokens).map(token => ({
        symbol: textValue(token.symbol, 'TOKEN'),
        name: textValue(token.name, textValue(token.symbol, 'Unknown token')),
        balance: num(token.balance),
        usd_value: num(token.usd_value),
        contract: String(token.contract || ''),
      })),
    },
    aggregate_portfolio: data.aggregate_portfolio && typeof data.aggregate_portfolio === 'object' ? {
      total_usd: num((data.aggregate_portfolio as Record<string, unknown>).total_usd),
      chain_count: num((data.aggregate_portfolio as Record<string, unknown>).chain_count),
      active_chain_count: num((data.aggregate_portfolio as Record<string, unknown>).active_chain_count),
      dominant_chain: textValue((data.aggregate_portfolio as Record<string, unknown>).dominant_chain),
      chains: arr<Record<string, unknown>>((data.aggregate_portfolio as Record<string, unknown>).chains).map(chain => ({
        chain: textValue(chain.chain, 'CHAIN'),
        chainid: num(chain.chainid) || undefined,
        native_balance: num(chain.native_balance),
        native_unit: textValue(chain.native_unit),
        portfolio_usd: num(chain.portfolio_usd),
        tx_count: num(chain.tx_count),
        token_count: num(chain.token_count),
        first_seen: textValue(chain.first_seen),
        last_seen: textValue(chain.last_seen),
        explorer: textValue(chain.explorer),
        source: textValue(chain.source),
        active: Boolean(chain.active),
      })),
    } : undefined,
    protocol_positions: arr<Record<string, unknown>>(data.protocol_positions).map(pos => ({
      name: textValue(pos.name, 'Unknown position'),
      type: textValue(pos.type, 'position'),
      chain: textValue(pos.chain),
      usd_value: num(pos.usd_value),
      balance: num(pos.balance),
      symbol: textValue(pos.symbol),
      confidence: num(pos.confidence),
      evidence: textValue(pos.evidence),
    })),
    activity: {
      observed_transactions: num(activity.observed_transactions),
      in_count: num(activity.in_count),
      out_count: num(activity.out_count),
      top_tokens: arr<Record<string, unknown>>(activity.top_tokens).map(token => ({
      token: textValue(token.token, 'native'),
        count: num(token.count),
      })),
      top_counterparties: arr<Record<string, unknown>>(activity.top_counterparties).map(cp => ({
        address: String(cp.address || ''),
        short: String(cp.short || shortAddr(String(cp.address || ''))),
        count: num(cp.count),
      })).filter(cp => cp.address),
    },
    activity_metrics: data.activity_metrics && typeof data.activity_metrics === 'object' ? {
      observed_transactions: num((data.activity_metrics as Record<string, unknown>).observed_transactions),
      first_seen: textValue((data.activity_metrics as Record<string, unknown>).first_seen),
      last_seen: textValue((data.activity_metrics as Record<string, unknown>).last_seen),
      graph_nodes: num((data.activity_metrics as Record<string, unknown>).graph_nodes),
      graph_edges: num((data.activity_metrics as Record<string, unknown>).graph_edges),
      correlations: num((data.activity_metrics as Record<string, unknown>).correlations),
      direct_neighbors: num((data.activity_metrics as Record<string, unknown>).direct_neighbors),
    } : undefined,
    services: arr<Record<string, unknown>>(data.services).map(svc => ({
      type: textValue(svc.type, 'service'),
      name: textValue(svc.name, 'Unknown service'),
      confidence: num(svc.confidence),
      evidence: svc.evidence && typeof svc.evidence === 'object' ? svc.evidence as Record<string, unknown> : {},
    })),
    related_wallets: arr<Record<string, unknown>>(data.related_wallets).map(wallet => ({
      address: String(wallet.address || '').toLowerCase(),
      short: String(wallet.short || shortAddr(String(wallet.address || ''))),
      relationship: textValue(wallet.relationship, 'linked wallet'),
      confidence: num(wallet.confidence),
      risk_score: num(wallet.risk_score),
      labels: arr(wallet.labels).map(label => textValue(label)).filter(Boolean),
      evidence: arr(wallet.evidence).map(ev => textValue(ev)).filter(Boolean),
    })).filter(wallet => wallet.address),
    risk_flags: arr(data.risk_flags).map(flag => textValue(flag)).filter(Boolean),
    graph_summary: {
      nodes: num(graphSummary.nodes),
      edges: num(graphSummary.edges),
      correlations: num(graphSummary.correlations),
      direct_neighbors: num(graphSummary.direct_neighbors),
    },
    investigator_notes: arr(data.investigator_notes).map(note => textValue(note)).filter(Boolean),
  }
}

function errorMessage(e: unknown): string {
  if (e instanceof Error) {
    const maybe = e as Error & { response?: { data?: { detail?: unknown } } }
    const detail = maybe.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    return e.message
  }
  return String(e)
}

function bfsPath(
  src: string, dst: string,
  edges: NexusGraphResult['edges'],
  corrs: NexusGraphResult['correlations'],
): string[] {
  const adj = new Map<string, Set<string>>()
  const link = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, new Set())
    if (!adj.has(b)) adj.set(b, new Set())
    adj.get(a)!.add(b); adj.get(b)!.add(a)
  }
  edges.forEach(e => link(e.source, e.target))
  corrs.forEach(c => link(c.source, c.target))
  const visited = new Set([src])
  const q: string[][] = [[src]]
  while (q.length) {
    const path = q.shift()!
    const cur = path[path.length - 1]
    if (cur === dst) return path
    for (const nb of (adj.get(cur) ?? [])) {
      if (!visited.has(nb)) { visited.add(nb); q.push([...path, nb]) }
    }
  }
  return []
}

function communityLayout(nodes: SimNode[], seed: string, W: number, H: number) {
  const byComm = new Map<string, SimNode[]>()
  nodes.forEach(n => {
    const c = n.community || '?'
    if (!byComm.has(c)) byComm.set(c, [])
    byComm.get(c)!.push(n)
  })
  const result = new Map<string, { x: number; y: number }>()
  const comms = Array.from(byComm.entries())
  const cx = W / 2, cy = H / 2
  // Community ring radius scales with the number of communities so they don't
  // bunch together at the center.
  const cr = Math.max(200, Math.min(480, 160 + comms.length * 42))
  comms.forEach(([, members], ci) => {
    const angle = (Math.PI * 2 * ci) / Math.max(comms.length, 1)
    const ccx = cx + Math.cos(angle) * cr
    const ccy = cy + Math.sin(angle) * cr
    const m = members.length
    members.forEach((n, ni) => {
      if (n.id === seed) { result.set(n.id, { x: cx, y: cy }); return }
      if (m <= 1) { result.set(n.id, { x: ccx, y: ccy }); return }
      // Inner radius scales with member count so nodes have breathing room.
      // For large communities, use a multi-ring spiral to avoid all members
      // piling on a single small circle.
      if (m <= 8) {
        const la = (Math.PI * 2 * ni) / m
        const lr = 38 + Math.min(110, m * 7)
        result.set(n.id, { x: ccx + Math.cos(la) * lr, y: ccy + Math.sin(la) * lr })
      } else {
        // Spiral: distribute across multiple rings
        const ringSize = 8
        const ring = Math.floor(ni / ringSize)
        const inRing = ni % ringSize
        const la = (Math.PI * 2 * inRing) / ringSize + ring * 0.3
        const lr = 50 + ring * 70
        result.set(n.id, { x: ccx + Math.cos(la) * lr, y: ccy + Math.sin(la) * lr })
      }
    })
  })
  return result
}

function radialLayout(nodes: SimNode[], seed: string, W: number, H: number) {
  const result = new Map<string, { x: number; y: number }>()
  const cx = W / 2, cy = H / 2
  // Multi-ring radial: distribute nodes across concentric rings sized by degree
  // so high-degree hubs sit near the center and leaves spread outward. Each ring
  // has enough arc length that nodes don't overlap.
  const nonSeed = nodes.filter(n => n.id !== seed)
  // Sort by degree descending so hubs are innermost
  nonSeed.sort((a, b) => b.degree - a.degree)
  const ringSize = Math.max(6, Math.ceil(Math.sqrt(nonSeed.length) * 1.4))
  const ringStep = 95 // spacing between rings
  nonSeed.forEach((n, i) => {
    const ring = Math.floor(i / ringSize)
    const inRing = i % ringSize
    const nodesInThisRing = Math.min(ringSize, nonSeed.length - ring * ringSize)
    const angle = (Math.PI * 2 * inRing) / Math.max(nodesInThisRing, 1)
    const r = 110 + ring * ringStep
    result.set(n.id, { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r })
  })
  result.set(seed, { x: cx, y: cy })
  return result
}

// BFS visit order from the seed (undirected) — used to stagger layout-switch
// animations so the graph visibly ripples outward from the subject.
function bfsOrderFromSeed(nodes: SimNode[], edges: { source: string; target: string }[], seed: string): string[] {
  const ids = new Set(nodes.map(n => n.id))
  const adj = new Map<string, string[]>()
  const link = (a: string, b: string) => {
    const list = adj.get(a)
    if (list) list.push(b)
    else adj.set(a, [b])
  }
  edges.forEach(e => {
    if (!ids.has(e.source) || !ids.has(e.target)) return
    link(e.source, e.target)
    link(e.target, e.source)
  })
  const seen = new Set<string>([seed])
  const order = [seed]
  const queue = [seed]
  while (queue.length) {
    const cur = queue.shift()!
    for (const nb of adj.get(cur) ?? []) {
      if (seen.has(nb)) continue
      seen.add(nb)
      order.push(nb)
      queue.push(nb)
    }
  }
  nodes.forEach(n => { if (!seen.has(n.id)) order.push(n.id) })
  return order
}
async function exportPNG(svgEl: SVGSVGElement) {
  const cloned = svgEl.cloneNode(true) as SVGSVGElement
  cloned.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  const W = svgEl.clientWidth, H = svgEl.clientHeight
  cloned.setAttribute('width', String(W))
  cloned.setAttribute('height', String(H))
  const svgData = new XMLSerializer().serializeToString(cloned)
  const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const img = new Image()
  img.onload = () => {
    const canvas = document.createElement('canvas')
    canvas.width = W * 2; canvas.height = H * 2
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = document.documentElement.classList.contains('light') ? '#f4f6fb' : '#0a0608'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const a = document.createElement('a')
    a.href = canvas.toDataURL('image/png')
    a.download = `nexus-graph-${Date.now()}.png`
    a.click()
    URL.revokeObjectURL(url)
  }
  img.src = url
}

function exportJSON(graph: NexusGraphResult) {
  const blob = new Blob([JSON.stringify(graph, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `nexus-${graph.seed.slice(0, 10)}-${Date.now()}.json`
  a.click(); URL.revokeObjectURL(url)
}

async function exportNexusExhibit(svg: SVGSVGElement, graph: NexusGraphResult) {
  const { exportExhibit } = await import('../lib/exhibit')
  const caseId = window.prompt('Case ID for chain-of-custody registration (leave blank to skip):') || ''
  await exportExhibit(svg, {
    title: 'Nexus Graph - Investigation Exhibit',
    caseId: caseId.trim() || undefined,
    subject: graph.seed,
    chain: graph.chain,
    tool: 'CrypTX Nexus Graph',
    legend: [
      { color: '#ff4052', label: 'seed / subject' }, { color: '#fbbf24', label: 'exchange' },
      { color: '#ff2d55', label: 'mixer / sanctioned' }, { color: '#9a858c', label: 'contract / dex' },
      { color: '#6f6065', label: 'unknown' },
    ],
    data: graph,
  })
}

function exportSubgraphJSON(graph: NexusGraphResult, ws: SubgraphWorkspace) {
  const r = ws.result ?? buildSubgraph(graph, { nodeIds: ws.ids, edgeKeys: ws.edgeKeys })
  const narrowed = toNexusGraphResult(graph, r)
  const payload = {
    title: ws.title,
    exported_at: new Date().toISOString(),
    ...narrowed,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `nexus-subgraph-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function traceNodeToNexus(node: GraphNode): NexusNode {
  const id = (node.address || node.id || '').toLowerCase()
  const labels = Array.isArray(node.risk_labels) ? node.risk_labels : []
  const txCount = Number(node.tx_count || 0)
  const balance = Number(node.balance || 0)
  const riskScore = Number(node.risk_score || 0)
  const entity = node.entity && node.entity !== 'Unknown' ? node.entity : ''
  const roleHint = entity || (labels[0] || (riskScore >= 70 ? 'high-risk wallet' : 'expanded wallet'))
  return {
    id,
    address: node.address || node.id,
    short: node.short_address || shortAddr(node.address || node.id),
    community: `expand:${Math.max(0, Number(node.hop || 0))}`,
    degree: Math.max(1, txCount),
    inbound_volume: 0,
    outbound_volume: 0,
    total_volume: Math.max(0, balance),
    bridge_score: labels.some(l => /bridge|mixer|swap|dex/i.test(l)) ? 6 : 0,
    risk_score: riskScore,
    role_hint: roleHint,
    labels: labels.length ? labels : ['dynamic-expansion'],
    motif_count: labels.length,
    features: {
      chain: node.chain,
      hop: node.hop,
      entity: node.entity,
      balance: node.balance,
      tx_count: node.tx_count,
      source: node.source,
      explorer: node.explorer,
      dynamic_expansion: true,
    },
  }
}

function traceEdgeToNexus(edge: GraphEdge): NexusEdge {
  return {
    source: (edge.source_address || edge.source || '').toLowerCase(),
    target: (edge.target_address || edge.target || '').toLowerCase(),
    value: Number(edge.amount || 0),
    token: edge.token || 'native',
    hash: edge.hash || '',
    time: '',
    type: 'dynamic-trace',
  }
}

// Detect the chain/asset family from an address's format so "Auto" routes a
// Bitcoin, Tron, or Zcash address to the right tracer instead of assuming Ethereum.
function detectChain(addr: string): string {
  const a = (addr || '').trim()
  if (/^0x[0-9a-fA-F]{40}$/.test(a)) return 'eth'                       // EVM (ETH/AVAX/BSC share this format → pick explicitly for non-ETH)
  if (/^(bc1|tb1)[0-9a-zA-Z]{6,87}$/.test(a)) return 'btc'             // BTC bech32
  if (/^t1[a-km-zA-HJ-NP-Z1-9]{33}$/.test(a)) return 'zcash'          // Zcash transparent p2pkh
  if (/^t3[a-km-zA-HJ-NP-Z1-9]{33}$/.test(a)) return 'zcash'          // Zcash transparent p2sh
  if (/^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(a)) return 'tron'            // Tron base58
  if (/^addr1[0-9a-z]{20,}$/.test(a)) return 'cardano'               // Cardano Shelley
  if (/^cosmos1[0-9a-z]{38,}$/.test(a)) return 'cosmos'              // Cosmos Hub bech32
  if (/^G[A-Z2-7]{55}$/.test(a)) return 'stellar'                    // Stellar
  if (/^[A-Z2-7]{58}$/.test(a)) return 'algorand'                   // Algorand
  if (/^[EU]Q[A-Za-z0-9_-]{46}$/.test(a)) return 'ton'              // TON user-friendly
  if (/^r[1-9A-HJ-NP-Za-km-z]{24,34}$/.test(a)) return 'xrp'        // XRP classic
  if (/^(ltc1[0-9a-z]{6,}|[LM][1-9A-HJ-NP-Za-km-z]{26,33})$/.test(a)) return 'litecoin'
  if (/^D[1-9A-HJ-NP-Za-km-z]{32,34}$/.test(a)) return 'dogecoin'   // Dogecoin
  if (/(\.near|\.testnet)$/.test(a)) return 'near'                  // NEAR named account
  if (/^(bitcoincash:)?[qp][0-9a-z]{38,}$/.test(a)) return 'bch'    // Bitcoin Cash CashAddr
  if (/^1[a-km-zA-HJ-NP-Z1-9]{46,47}$/.test(a)) return 'polkadot'   // Polkadot SS58 (longer than BTC legacy)
  if (/^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$/.test(a)) return 'btc'      // BTC legacy p2pkh/p2sh
  return 'eth'                                                          // default to EVM
}

// Convert a multi-chain Holistic trace result into the {nodes, edges} trace-graph
// shape the Nexus overlay adapters already understand (GraphNode / GraphEdge).
// Holistic node ids are "chain:address"; edges reference those ids.
function holisticToTraceGraph(h: { graph?: { nodes?: HolisticNode[]; edges?: HolisticEdge[] } } | null): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const hn = h?.graph?.nodes || []
  const he = h?.graph?.edges || []
  const idToAddr = new Map<string, string>()
  hn.forEach(n => idToAddr.set(n.id, n.address))
  const nodes: GraphNode[] = hn.map(n => ({
    id: n.address,
    address: n.address,
    short_address: shortAddr(n.address),
    chain: n.chain,
    hop: Number(n.hop || 0),
    risk_score: Number(n.risk || 0),
    entity: n.label || (n.type && n.type !== 'unknown' ? n.type : ''),
    balance: Number(n.inflow_value || 0) + Number(n.outflow_value || 0),
    balance_unit: '',
    tx_count: 0,
    risk_level: n.sanctioned ? 'sanctioned' : Number(n.risk || 0) >= 65 ? 'mixer' : n.type === 'bridge' ? 'bridge_swap' : 'clean',
    risk_color: n.sanctioned ? '#f0356b' : Number(n.risk || 0) >= 65 ? '#ef4444' : n.type === 'bridge' ? '#f59e0b' : '#22c55e',
    source: 'holistic',
    explorer: '',
    risk_labels: [n.type, n.sanctioned ? 'sanctioned' : '', n.vasp || ''].filter(Boolean) as string[],
    is_suspicious: Boolean(n.sanctioned || Number(n.risk || 0) >= 65),
  }))
  const edges: GraphEdge[] = he.map(e => {
    const sa = idToAddr.get(e.source) || e.source
    const ta = idToAddr.get(e.target) || e.target
    return {
      source: sa, target: ta, source_address: sa, target_address: ta,
      amount: Number(e.value || 0), token: e.asset || 'native', hash: e.tx_hash || '',
    }
  })
  return { nodes, edges }
}

function recomputeCommunities(nodes: NexusNode[], edges: NexusEdge[]): NexusGraphResult['communities'] {
  const grouped = new Map<string, NexusNode[]>()
  nodes.forEach(n => {
    const key = n.community || 'unclustered'
    if (!grouped.has(key)) grouped.set(key, [])
    grouped.get(key)!.push(n)
  })
  return Array.from(grouped.entries()).map(([id, members]) => {
    const memberIds = new Set(members.map(n => n.id))
    const edgeCount = edges.filter(e => memberIds.has(e.source) && memberIds.has(e.target)).length
    const maxEdges = Math.max(1, members.length * Math.max(1, members.length - 1))
    return {
      id,
      size: members.length,
      edge_count: edgeCount,
      density: edgeCount / maxEdges,
      members: members.map(n => n.id),
    }
  })
}

function mergeNexusGraph(base: NexusGraphResult, overlay: GraphOverlay): NexusGraphResult {
  if (!overlay.nodes.length && !overlay.edges.length) return base
  const nodes = new Map<string, NexusNode>()
  base.nodes.forEach(n => nodes.set(n.id, n))
  overlay.nodes.forEach(n => {
    const existing = nodes.get(n.id)
    nodes.set(n.id, existing ? {
      ...n,
      ...existing,
      labels: Array.from(new Set([...(existing.labels || []), ...(n.labels || [])])),
      features: { ...n.features, ...existing.features },
      degree: Math.max(existing.degree, n.degree),
      risk_score: Math.max(existing.risk_score, n.risk_score),
      bridge_score: Math.max(existing.bridge_score, n.bridge_score),
    } : n)
  })

  const edgeKey = (e: NexusEdge) => `${e.source}|${e.target}|${e.hash || e.token || e.type}`
  const edges = new Map<string, NexusEdge>()
  base.edges.forEach(e => edges.set(edgeKey(e), e))
  overlay.edges.forEach(e => {
    if (nodes.has(e.source) && nodes.has(e.target)) edges.set(edgeKey(e), e)
  })

  const mergedNodes = Array.from(nodes.values())
  const mergedEdges = Array.from(edges.values())
  const communities = recomputeCommunities(mergedNodes, mergedEdges)
  const bridgeWallets = mergedNodes
    .filter(n => n.bridge_score >= 5)
    .sort((a, b) => b.bridge_score - a.bridge_score)
    .slice(0, 24)
  const pivotQueue = Array.from(new Map([...base.pivot_queue, ...overlay.nodes]
    .sort((a, b) => (b.risk_score + b.bridge_score) - (a.risk_score + a.bridge_score))
    .map(n => [n.id, n])).values()).slice(0, 40)

  return {
    ...base,
    nodes: mergedNodes,
    edges: mergedEdges,
    communities,
    bridge_wallets: bridgeWallets,
    pivot_queue: pivotQueue,
    summary: {
      ...base.summary,
      node_count: mergedNodes.length,
      edge_count: mergedEdges.length,
      community_count: communities.length,
      bridge_wallet_count: bridgeWallets.length,
      highest_risk: Math.max(base.summary.highest_risk, ...mergedNodes.map(n => n.risk_score)),
    },
    explainability: Array.from(new Set([
      ...base.explainability,
      overlay.nodes.length ? `Dynamic graph expansion added ${overlay.nodes.length} wallets and ${overlay.edges.length} transaction flows from on-canvas investigation.` : '',
    ].filter(Boolean))),
  }
}

function traceGraphToOverlay(traceGraph: TraceGraph): GraphOverlay {
  const nodes = traceGraph.nodes.map(traceNodeToNexus).filter(n => n.id && n.address)
  const nodeIds = new Set(nodes.map(n => n.id))
  const edges = traceGraph.edges.map(traceEdgeToNexus).filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
  const degree = new Map<string, number>()
  edges.forEach(e => {
    degree.set(e.source, (degree.get(e.source) || 0) + 1)
    degree.set(e.target, (degree.get(e.target) || 0) + 1)
  })
  nodes.forEach(n => { n.degree = Math.max(n.degree, degree.get(n.id) || 0) })
  return { nodes, edges }
}

function demixResultToOverlay(res: NexusDemixResponse): GraphOverlay {
  const nodes = res.overlay.nodes.map(n => ({
    id: n.id.toLowerCase(),
    address: n.address || n.id,
    short: shortAddr(n.address || n.id),
    community: 'demix',
    degree: 1,
    inbound_volume: 0,
    outbound_volume: 0,
    total_volume: 0,
    bridge_score: 8,
    risk_score: Math.max(55, n.risk_score || res.summary.risk_score || 0),
    role_hint: n.label || 'demix lead',
    labels: ['Nexus Demix', n.label].filter(Boolean),
    motif_count: 0,
    features: { demix_overlay: true },
  }))
  const nodeIds = new Set(nodes.map(n => n.id))
  const edges = res.overlay.edges.map((e, i) => ({
    source: e.source.toLowerCase(),
    target: e.target.toLowerCase(),
    value: Math.round((e.confidence || 0) * 100),
    token: e.method,
    hash: e.tx_hash || `demix-${i}`,
    time: '',
    type: `demix:${e.method}`,
  })).filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
  return { nodes, edges }
}

// ── Stat ──────────────────────────────────────────────────────────────────────
function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
      <p className="text-[10px] text-text-muted uppercase tracking-widest">{label}</p>
      <p className="text-lg font-bold text-text-primary font-mono">{value}</p>
      {sub && <p className="text-[11px] text-text-muted truncate">{sub}</p>}
    </div>
  )
}

function GraphToolButton({
  title,
  icon: Icon,
  active = false,
  disabled = false,
  spinning = false,
  onClick,
  children,
}: {
  title: string
  icon: IconComponent
  active?: boolean
  disabled?: boolean
  spinning?: boolean
  onClick: () => void
  children?: ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
      className="group relative inline-flex h-8 min-w-8 items-center justify-center gap-1 rounded-md px-2 text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
      style={{
        background: active ? 'rgba(255,64,82,0.13)' : 'rgb(var(--bg-elevated) / 0.92)',
        border: `1px solid ${active ? 'rgba(255,64,82,0.45)' : 'rgb(var(--bg-border))'}`,
        color: active ? '#ff4052' : '#9a858c',
      }}
    >
      <Icon size={14} className={spinning ? 'animate-spin' : undefined} />
      {children && <span className="hidden 2xl:inline whitespace-nowrap">{children}</span>}
      <span
        className="pointer-events-none absolute left-1/2 top-full z-50 mt-2 hidden -translate-x-1/2 whitespace-nowrap rounded-md px-2 py-1 text-[10px] text-text-primary shadow-xl group-hover:block"
        style={{ background: 'rgb(var(--bg-elevated) / 0.98)', border: '1px solid rgb(var(--bg-border))' }}
      >
        {title}
      </span>
    </button>
  )
}

// ── Theme-adaptive canvas palette ────────────────────────────────────────────
type GraphPalette = {
  isLight: boolean
  bg: string          // svg canvas background
  grid: string        // background grid lines
  chip: string        // floating label / legend chip fill
  chipStrong: string  // opaque chip fill (menus, tooltips)
  chipBorder: string  // chip / panel border
  chipText: string    // primary text on chips
  chipMuted: string   // secondary text on chips
  nodePlate: string   // dark backing plate behind the brand disc
  nodeStroke: string  // backing-plate stroke
  hullText: string    // community hull captions
}

function makePalette(isLight: boolean): GraphPalette {
  return isLight
    ? {
        isLight: true,
        bg: '#f4f6fb',
        grid: '#d6deea',
        chip: 'rgba(255,255,255,0.92)',
        chipStrong: 'rgba(255,255,255,0.98)',
        chipBorder: 'rgba(148,163,184,0.5)',
        chipText: '#0b1220',
        chipMuted: '#5b6675',
        nodePlate: '#ffffff',
        nodeStroke: 'rgba(15,23,42,0.35)',
        hullText: '#475569',
      }
    : {
        isLight: false,
        bg: '#0a0608',
        grid: '#3a1f28',
        chip: 'rgba(4,13,26,0.88)',
        chipStrong: 'rgba(4,13,26,0.98)',
        chipBorder: '#160a0e',
        chipText: '#f6f4f6',
        chipMuted: '#8f7780',
        nodePlate: '#0b0f1a',
        nodeStroke: 'rgba(255,255,255,0.35)',
        hullText: '#8f7780',
      }
}

/** Tracks the `.light` class the Layout toggles on <html>, reactively. */
function useThemePalette(): GraphPalette {
  const read = () => typeof document !== 'undefined' && document.documentElement.classList.contains('light')
  const [isLight, setIsLight] = useState(read)
  useEffect(() => {
    const el = document.documentElement
    const obs = new MutationObserver(() => setIsLight(el.classList.contains('light')))
    obs.observe(el, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])
  return useMemo(() => makePalette(isLight), [isLight])
}

// ── GraphCanvas ───────────────────────────────────────────────────────────────
function GraphCanvas({ graph, selected, onSelect, onExpandNode, expandingNode, onRestoreOriginal }: {
graph: NexusGraphResult
selected: string | null
onSelect: (id: string) => void
onExpandNode?: (id: string, opts?: ExpandOpts) => Promise<string[]>
expandingNode?: string | null
onRestoreOriginal?: () => void
}) {
const { t } = useTranslation()
const svgRef = useRef<SVGSVGElement>(null)
const pal = useThemePalette()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const simRef = useRef<Simulation<SimNode, any> | null>(null)
  const nodesRef = useRef<SimNode[]>([])
  const [renderTick, setRenderTick] = useState(0)
  const [svgSize, setSvgSize] = useState({ w: 1100, h: 680 })

  // View state (pan + zoom) - kept in both state (for render) and ref (for event handlers)
  const [view, _setView] = useState<View>({ x: 0, y: 0, z: 0.85 })
  const viewRef = useRef<View>({ x: 0, y: 0, z: 0.85 })
  function setView(fn: (v: View) => View) {
    _setView(prev => { const next = fn(prev); viewRef.current = next; return next })
  }
  function setViewDirect(v: View) { viewRef.current = v; _setView(v) }

  // ── Animation toolkit (graphAnim.ts) ──
  // Camera tweens: fitView / reset / zoom buttons all animate via animateViewTo.
  const animateViewTo = useTweenView(() => viewRef.current, setViewDirect)
  // Completion callback for the current position-animation run (layout switch,
  // subgraph isolate/return) — set right before each animateTo call.
  const posAnimDoneRef = useRef<(() => void) | null>(null)
  // When true, the layout-switch effect's onComplete skips its auto fitView
  // (used when a subgraph session restore drives the camera itself).
  const suppressLayoutFitRef = useRef(false)
  const posAnim = usePositionAnimator({
    onFrame: (positions) => {
      for (const n of nodesRef.current) {
        const p = positions.get(n.id)
        if (p) { n.x = p.x; n.y = p.y; n.fx = p.x; n.fy = p.y }
      }
      setRenderTick(t => t + 1)
    },
    onComplete: () => {
      const done = posAnimDoneRef.current
      posAnimDoneRef.current = null
      done?.()
    },
  })

  // Controls
  const [layout, setLayout] = useState<LayoutMode>('flow')
  const [sizeMode, setSizeMode] = useState<SizeMode>('risk')
  const [showLabels, setShowLabels] = useState(true)
  const [showFlow, setShowFlow] = useState(true)
  const [edgeMode, setEdgeMode] = useState<EdgeMode>('bundled')
  const [edgeScope, setEdgeScope] = useState<EdgeScope>('all')
  const [focusMode, setFocusMode] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [showClusters, setShowClusters] = useState(true)
  const [showInspector, setShowInspector] = useState(true)
  const [showLegend, setShowLegend] = useState(true)
  const [graphViewOpen, setGraphViewOpen] = useState(false)
  const [minCorr, setMinCorr] = useState(0.28)
  const [searchQuery, setSearchQuery] = useState('')
  const [subgraph, setSubgraph] = useState<SubgraphWorkspace | null>(null)
  // Snapshot of pre-isolation camera/hidden/layout, restored on session close.
  const subgraphSnapshot = useRef<{ view: View; hidden: Set<string>; layout: LayoutMode } | null>(null)
  // True during the dim → re-layout → fit isolate choreography.
  const [subgraphAnimating, setSubgraphAnimating] = useState(false)
  const [lastTraceIds, setLastTraceIds] = useState(new Set<string>())
  const [hovered, setHovered] = useState<string | null>(null)
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null)
  const [selectedBundleKey, setSelectedBundleKey] = useState<string | null>(null)
  const navigate = useNavigate()
  const [savingBoard, setSavingBoard] = useState(false)
  const [linkedBoards, setLinkedBoards] = useState<BoardLink[]>([])

  // Node state
  const [pinned, setPinned] = useState(new Set<string>())
  const [hidden, setHidden] = useState(new Set<string>())
  const [tags, setTags] = useState<Record<string, string>>({})
  const [tagInput, setTagInput] = useState<{ id: string; val: string } | null>(null)

  // Path finding
  const [pathSrc, setPathSrc] = useState<string | null>(null)
  const [pathDst, setPathDst] = useState<string | null>(null)
  const [pathNodeSet, setPathNodeSet] = useState(new Set<string>())
  const [pathEdgeSet, setPathEdgeSet] = useState(new Set<string>())
  const [pathOrder, setPathOrder] = useState<string[]>([])

  // Context menu
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; id: string } | null>(null)

  // Drag / pan refs
  const isPanning = useRef(false)
  const panStart = useRef({ sx: 0, sy: 0, px: 0, py: 0 })
  const dragStart = useRef({ sx: 0, sy: 0 })
  const dragId = useRef<string | null>(null)
  const dragging = useRef(false)
  const suppressClick = useRef(false)
  const clickTs = useRef(0)

  // Deterministic layout positions for the current mode (null for force).
  // 'flow' uses the professional Sugiyama-style computeFlowLayout with
  // radius-aware spacing; community/radial keep their existing algorithms.
  function computeLayoutPositions(mode: LayoutMode): Map<string, { x: number; y: number }> | null {
    const nodes = nodesRef.current
    if (!nodes.length) return null
    const { w: W, h: H } = svgSize
    if (mode === 'flow') {
      return computeFlowLayout(nodes, graph.edges, graph.seed, W, H, {
        radius: n => nodeRadius(n, sizeMode),
      })
    }
    if (mode === 'community') return communityLayout(nodes, graph.seed, W, H)
    if (mode === 'radial') return radialLayout(nodes, graph.seed, W, H)
    return null
  }

  function resetCanvasState() {
    setViewDirect({ x: 0, y: 0, z: 0.85 })
    setPinned(new Set())
    setHidden(new Set())
    setTags({})
    setTagInput(null)
    setSubgraph(null)
    subgraphSnapshot.current = null
    setSubgraphAnimating(false)
    posAnim.cancel()
    setLastTraceIds(new Set())
    setPathSrc(null)
    setPathDst(null)
    setPathNodeSet(new Set())
    setPathEdgeSet(new Set())
    setPathOrder([])
    setFocusMode(false)
    setEdgeMode('bundled')
    setEdgeScope('all')
    setSelectedBundleKey(null)
    setSearchQuery('')
    setCtxMenu(null)

    // Re-apply the user's currently-selected layout after reset.
    // Previously this always unpinned (fx/fy=null) + restarted the force sim,
    // which silently reverted flow/community/radial layouts to force physics.
    // Now we re-pin to the deterministic layout positions when a non-force
    // layout is active, so the restored graph keeps the user's chosen layout.
    const sim = simRef.current
    const nodes = nodesRef.current
    if (!sim || !nodes.length) return

    if (layout === 'force') {
      nodes.forEach(n => { n.fx = null; n.fy = null })
      sim.alpha(0.45).restart()
    } else {
      const pos = computeLayoutPositions(layout)
      nodes.forEach(n => {
        const p = pos?.get(n.id)
        if (p) { n.fx = p.x; n.fy = p.y; n.x = p.x; n.y = p.y }
        else { n.fx = null; n.fy = null }
      })
      posAnim.setPositions(nodes.map(n => [n.id, { x: n.x, y: n.y }] as const))
      sim.alpha(0.3).restart()
      setTimeout(fitView, 300)
    }
  }

  function restoreOriginalGraph() {
    resetCanvasState()
    onRestoreOriginal?.()
  }

  // ── SVG size observer ──────────────────────────────────────────────────────
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const apply = (w: number, h: number) => setSvgSize(prev =>
      (Math.abs(prev.w - w) < 1 && Math.abs(prev.h - h) < 1) ? prev : { w, h })
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect
      apply(width || 1100, height || 680)
    })
    ro.observe(el)
    const r = el.getBoundingClientRect()
    if (r.width) apply(r.width, r.height)
    return () => ro.disconnect()
  }, [fullscreen])

  // ── Simulation setup ───────────────────────────────────────────────────────
  useEffect(() => {
    simRef.current?.stop()
    const W = svgSize.w, H = svgSize.h
    const cx = W / 2, cy = H / 2

    const nodes: SimNode[] = graph.nodes.map(n => ({
      ...n,
      x: cx + (Math.random() - 0.5) * 350,
      y: cy + (Math.random() - 0.5) * 350,
      vx: 0, vy: 0, fx: null, fy: null,
    }))
    nodesRef.current = nodes
    const idSet = new Set(nodes.map(n => n.id))

    const links = [
      ...graph.edges.map(e => ({ source: e.source, target: e.target })),
      ...graph.correlations.filter(c => c.score >= 0.3).map(c => ({ source: c.source, target: c.target })),
    ].filter(l => idSet.has(l.source) && idSet.has(l.target))

    // ── Adaptive force parameters — scale with graph density ──
    // Dense graphs (50+ nodes) need stronger repulsion and longer links to avoid
    // collapsing into a tangled ball. Sparse graphs stay tight for readability.
    const N = nodes.length
    const linkCount = links.length
    const avgDegree = N > 0 ? linkCount / N : 1
    // Link distance grows with node count so spread-out graphs stay spread
    const linkDist = 150 + Math.min(180, Math.sqrt(N) * 14)
    // Charge strength: stronger (more negative) repulsion for dense graphs
    const chargeStrength = -(620 + Math.min(800, N * 5.5))
    // Charge distanceMax: let repulsion reach further in big graphs
    const chargeDistMax = 720 + Math.min(800, N * 6)
    // distanceMin prevents extreme forces when nodes are very close
    const chargeDistMin = 14 + Math.min(20, avgDegree * 1.5)

    const sim = forceSimulation<SimNode>(nodes)
      .force('link', forceLink(links).id((d: any) => d.id)
        .distance(linkDist)
        .strength(0.42))
      .force('charge', forceManyBody<SimNode>()
        .strength(chargeStrength)
        .distanceMax(chargeDistMax)
        .distanceMin(chargeDistMin))
      .force('center', forceCenter(cx, cy).strength(0.07))
      .force('collide', forceCollide<SimNode>()
        .radius((d: any) => nodeRadius(d as NexusNode, sizeMode) + 38)
        .strength(0.96)
        .iterations(N > 80 ? 2 : 1))
      .velocityDecay(0.22 + Math.min(0.08, N * 0.0008))
      .alphaDecay(N > 100 ? 0.016 : 0.012)
      .on('tick', () => setRenderTick(t => t + 1))

    simRef.current = sim
    setViewDirect({ x: 0, y: 0, z: 0.85 })
    setPinned(new Set()); setHidden(new Set())
    setSubgraph(null); setLastTraceIds(new Set())
    subgraphSnapshot.current = null          // B10: drop stale session snapshot
    setSubgraphAnimating(false)
    posAnimDoneRef.current = null
    posAnim.cancel()
    setPathNodeSet(new Set()); setPathEdgeSet(new Set()); setPathOrder([])
    setPathSrc(null); setPathDst(null)
    setSelectedBundleKey(null); setHoveredEdge(null)

    // Apply the user's currently-selected layout immediately so the freshly-built
    // simulation respects it. Without this, a new graph (or restored original)
    // would always render in 'force' mode until the user manually re-picked a
    // layout — because the [layout] effect only fires on layout *change*, not on
    // graph change.
    if (layout !== 'force') {
      const pos = computeLayoutPositions(layout)
      nodes.forEach(n => {
        const p = pos?.get(n.id)
        if (p) { n.fx = p.x; n.fy = p.y; n.x = p.x; n.y = p.y }
      })
      // Seed the animator so the next layout switch tweens FROM these positions.
      posAnim.setPositions(nodes.map(n => [n.id, { x: n.x, y: n.y }] as const))
      sim.alpha(0.3).restart()
      setTimeout(fitView, 300)
    } else {
      posAnim.setPositions(nodes.map(n => [n.id, { x: n.x, y: n.y }] as const))
    }

    return () => { sim.stop() }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph])

  // ── Layout switching (animated) ────────────────────────────────────────────
  // Deterministic layouts tween every node from its CURRENT position to the new
  // layout (object constancy) with a BFS stagger from the seed, instead of the
  // old hard fx/fy snap. The sim stays parked during the tween; onComplete
  // re-energizes it gently and re-frames the camera (animated fitView).
  useEffect(() => {
    const sim = simRef.current
    const nodes = nodesRef.current
    if (!sim || !nodes.length) return

    if (layout === 'force') {
      posAnimDoneRef.current = null
      posAnim.cancel()
      nodes.forEach(n => { if (!pinned.has(n.id)) { n.fx = null; n.fy = null } })
      sim.alpha(0.5).restart()
      return
    }

    const pos = computeLayoutPositions(layout)
    if (!pos) return
    // Park the sim while the tween runs (onFrame re-pins nodes along the path).
    sim.alpha(0.05)
    posAnim.setPositions(nodes.map(n => [n.id, { x: n.x, y: n.y }] as const))
    posAnimDoneRef.current = () => {
      sim.alpha(0.15).restart()
      if (suppressLayoutFitRef.current) {
        suppressLayoutFitRef.current = false
        return
      }
      fitView()
    }
    posAnim.animateTo(pos, LAYOUT_MS, easeInOutCubic, {
      order: bfsOrderFromSeed(nodes, graph.edges, graph.seed),
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout])

  // ── Wheel zoom ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const fn = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      const factor = e.deltaY > 0 ? 0.88 : 1.12
      setView(v => {
        const newZ = Math.max(0.08, Math.min(6, v.z * factor))
        return {
          x: mx - (mx - v.x) * (newZ / v.z),
          y: my - (my - v.y) * (newZ / v.z),
          z: newZ,
        }
      })
    }
    el.addEventListener('wheel', fn, { passive: false })
    return () => el.removeEventListener('wheel', fn)
  // Re-attach when toggling fullscreen: the portal remounts the SVG into a new
  // DOM node, so the wheel listener must rebind to the fresh element.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullscreen])

  // ── Keyboard ───────────────────────────────────────────────────────────────
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // Layered Escape: innermost surface closes first; fullscreen exits LAST,
      // so Esc inside a subgraph no longer dumps the user out of fullscreen.
      if (ctxMenu) return setCtxMenu(null)
      if (tagInput) return setTagInput(null)
      if (selectedBundleKey) return setSelectedBundleKey(null)
      if (pathSrc || pathNodeSet.size > 0) {
        setPathSrc(null); setPathDst(null)
        setPathNodeSet(new Set()); setPathEdgeSet(new Set()); setPathOrder([])
        return
      }
      if (subgraph) return closeSubgraphSession()
      if (fullscreen) setFullscreen(false)
    }
    window.addEventListener('keydown', fn)
    return () => window.removeEventListener('keydown', fn)
  }, [fullscreen, ctxMenu, tagInput, selectedBundleKey, pathSrc, pathNodeSet, subgraph])

  useEffect(() => {
    if (!fullscreen) return
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = oldOverflow }
  }, [fullscreen])

  // ── Path find ──────────────────────────────────────────────────────────────
  function doFindPath(src: string, dst: string) {
    const path = bfsPath(src, dst, graph.edges, graph.correlations)
    setPathNodeSet(new Set(path))
    const es = new Set<string>()
    for (let i = 0; i < path.length - 1; i++) {
      es.add(`${path[i]}|${path[i + 1]}`); es.add(`${path[i + 1]}|${path[i]}`)
    }
    setPathEdgeSet(es)
    setPathOrder(path)
    return path
  }

  // ── Fit view ───────────────────────────────────────────────────────────────
  // Animated camera framing (CAMERA_MS via animateViewTo; instant under
  // prefers-reduced-motion). Frames visible nodes only (hidden + subgraph-aware).
  function fitView() {
    const nodes = nodesRef.current.filter(n => !hidden.has(n.id) && (!subgraph || subgraph.ids.has(n.id)))
    const target = fitViewTransform(nodes, svgSize.w, svgSize.h, layout === 'flow' ? 180 : 100)
    if (target) animateViewTo(target)
  }

  // ── Board bridge ─────────────────────────────────────────────────────────────
  const seedAddress = useMemo(
    () => graph.nodes.find(n => n.id === graph.seed)?.address || graph.seed,
    [graph.nodes, graph.seed],
  )

  useEffect(() => {
    if (!seedAddress) return
    boardsForRef(seedAddress).then(setLinkedBoards).catch(() => setLinkedBoards([]))
  }, [seedAddress])

  async function saveToBoard() {
    if (savingBoard) return
    setSavingBoard(true)
    try {
      // Use the live, positioned simulation nodes so the board mirrors the on-screen layout.
      const posById = new Map(nodesRef.current.map(n => [n.id, n]))
      const visible = (subgraph ? graph.nodes.filter(n => subgraph.ids.has(n.id)) : graph.nodes)
        .filter(n => !hidden.has(n.id))
      const exportNodes = visible.map(n => {
        const p = posById.get(n.id)
        return {
          id: n.id, address: n.address, chain: graph.chain, label: n.short || n.address.slice(0, 10),
          risk_score: n.risk_score, role_hint: n.role_hint, x: p?.x ?? Math.random() * 600, y: p?.y ?? Math.random() * 400,
        }
      })
      const visibleIds = new Set(exportNodes.map(n => n.id))
      const exportEdges = graph.edges
        .filter(e => visibleIds.has(e.source) && visibleIds.has(e.target))
        .map(e => ({ source: e.source, target: e.target, value: e.value, token: e.token, hash: e.hash, time: e.time }))
      const board = await createBoardFromNexus(
        `Nexus · ${shortAddr(seedAddress)} · ${new Date().toISOString().slice(0, 10)}`,
        { subject: seedAddress, chain: graph.chain, nodes: exportNodes, edges: exportEdges },
      )
      navigate(`/boards/${board.id}`)
    } catch {
      setSavingBoard(false)
    }
  }

  // ── SVG event handlers ─────────────────────────────────────────────────────
  function onSvgDown(e: React.MouseEvent) {
    if ((e.target as Element).closest('[data-node]')) return
    if (e.button === 0) {
      isPanning.current = true
      panStart.current = { sx: e.clientX, sy: e.clientY, px: viewRef.current.x, py: viewRef.current.y }
    }
    setCtxMenu(null)
  }

  function onSvgMove(e: React.MouseEvent) {
    if (isPanning.current && !dragging.current) {
      const { sx, sy, px, py } = panStart.current
      setView(v => ({ ...v, x: px + e.clientX - sx, y: py + e.clientY - sy }))
    } else if (dragId.current) {
      if (!dragging.current) {
        const moved = Math.hypot(e.clientX - dragStart.current.sx, e.clientY - dragStart.current.sy)
        if (moved < 3) return
        dragging.current = true
        suppressClick.current = true
      }
      const rect = svgRef.current!.getBoundingClientRect()
      const { x: px, y: py, z } = viewRef.current
      const gx = (e.clientX - rect.left - px) / z
      const gy = (e.clientY - rect.top - py) / z
      const nd = nodesRef.current.find(n => n.id === dragId.current)
      if (nd) {
        nd.fx = gx; nd.fy = gy
        // Keep the position animator's live truth in sync so an in-flight
        // layout tween never fights the user's cursor.
        posAnim.setPosition(nd.id, { x: gx, y: gy })
        simRef.current?.alpha(0.3).restart()
      }
    }
  }

  function onSvgUp() {
    if (dragging.current && dragId.current) {
      const id = dragId.current
      const nd = nodesRef.current.find(n => n.id === id)
      if (nd) { nd.fx = nd.x; nd.fy = nd.y }
      setPinned(prev => new Set(prev).add(id))
      simRef.current?.alphaTarget(0)
    }
    isPanning.current = false; dragging.current = false; dragId.current = null
  }

  function onNodeDown(e: React.MouseEvent, id: string) {
    e.stopPropagation()
    clickTs.current = Date.now()
    dragId.current = id
    dragging.current = false
    suppressClick.current = false
    dragStart.current = { sx: e.clientX, sy: e.clientY }
    const nd = nodesRef.current.find(n => n.id === id)
    if (nd) { nd.fx = nd.x; nd.fy = nd.y; posAnim.setPosition(id, { x: nd.x, y: nd.y }) }
  }

  function onNodeClick(e: React.MouseEvent, id: string) {
    e.stopPropagation()
    if (suppressClick.current) { suppressClick.current = false; return }
    if (pathSrc && !pathDst && id !== pathSrc) {
      setPathDst(id); doFindPath(pathSrc, id); return
    }
    onSelect(id); setShowInspector(true); setCtxMenu(null)
  }

  function onNodeDblClick(e: React.MouseEvent, id: string) {
    e.stopPropagation(); e.preventDefault()
    const nd = nodesRef.current.find(n => n.id === id)
    if (!nd) return
    setPinned(prev => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id); if (layout === 'force') { nd.fx = null; nd.fy = null } }
      else { next.add(id); nd.fx = nd.x; nd.fy = nd.y }
      return next
    })
  }

  function onNodeCtx(e: React.MouseEvent, id: string) {
    e.preventDefault(); e.stopPropagation()
    setCtxMenu({ x: e.clientX, y: e.clientY, id })
  }

  // ── Context menu actions ───────────────────────────────────────────────────
  function ctxCopy() {
    const nd = graph.nodes.find(n => n.id === ctxMenu!.id)
    if (nd) navigator.clipboard.writeText(nd.address)
    setCtxMenu(null)
  }
  function ctxIntel() {
    const nd = graph.nodes.find(n => n.id === ctxMenu!.id)
    if (nd) window.location.href = `/intel/${encodeURIComponent(nd.address)}`
    setCtxMenu(null)
  }
  function ctxSetPathSrc() {
    setPathSrc(ctxMenu!.id); setPathDst(null)
    setPathNodeSet(new Set()); setPathEdgeSet(new Set()); setPathOrder([])
    setCtxMenu(null)
  }
  function ctxFindPathToSelected() {
    if (selected && selected !== ctxMenu!.id) doFindPath(ctxMenu!.id, selected)
    setCtxMenu(null)
  }
  function ctxPin() {
    const id = ctxMenu!.id
    const nd = nodesRef.current.find(n => n.id === id)
    if (!nd) return setCtxMenu(null)
    setPinned(prev => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id); if (layout === 'force') { nd.fx = null; nd.fy = null } }
      else { next.add(id); nd.fx = nd.x; nd.fy = nd.y }
      return next
    })
    setCtxMenu(null)
  }
  function ctxHide() { setHidden(prev => { const n = new Set(prev); n.add(ctxMenu!.id); return n }); setCtxMenu(null) }
  function ctxTag() { setTagInput({ id: ctxMenu!.id, val: tags[ctxMenu!.id] || '' }); setCtxMenu(null) }
  function ctxExpand(opts: ExpandOpts) {
    const id = ctxMenu!.id
    setCtxMenu(null)
    void requestExpansion(id, opts)
  }

  async function requestExpansion(id: string, opts: ExpandOpts) {
    const ids = await onExpandNode?.(id, opts)
    if (ids?.length) {
      setLastTraceIds(new Set(ids))
    }
  }

  // ── Subgraph sessions (isolate UX) ────────────────────────────────────────
  // openSubgraphSession: snapshot (camera + hidden + layout) on first entry,
  // then run the animated dim → re-layout → fit choreography on the isolated
  // set. closeSubgraphSession restores everything with one click (or Esc).

  /** Animated isolate: members tween to a fresh FLOW layout of the subset,
   *  then the camera fits the re-laid-out members. Non-members are dimmed by
   *  the render layer while `subgraphAnimating` is true. */
  function animateSubgraphRelayout(result: SubgraphResult) {
    const { w: W, h: H } = svgSize
    setSubgraphAnimating(true)
    const currentPos = new Map(nodesRef.current.map(n => [n.id, { x: n.x, y: n.y }] as const))
    const pos = relayoutSubset(
      currentPos, nodesRef.current, graph.edges, graph.seed, result.ids, W, H,
      { radius: n => nodeRadius(n, sizeMode) },
    )
    posAnim.setPositions(currentPos)
    posAnimDoneRef.current = () => {
      setSubgraphAnimating(false)
      const members = nodesRef.current.filter(n => result.ids.has(n.id))
      const target = fitViewTransform(members, W, H, 180)
      if (target) animateViewTo(target)
    }
    posAnim.animateTo(pos, ISOLATE_MS, easeInOutCubic, {
      order: result.nodes.map(n => n.id),
    })
  }

  function openSubgraphSession(result: SubgraphResult, kind: SubgraphKind, title: string) {
    if (subgraphIsEmpty(result)) return
    if (!subgraph) {
      // Snapshot only on first entry so nested isolation returns to the true
      // full-graph state.
      subgraphSnapshot.current = { view: viewRef.current, hidden, layout }
    }
    setSubgraph(toSubgraphWorkspace(result, { title, kind }))
    setFocusMode(false)
    setHidden(new Set())
    setCtxMenu(null)
    animateSubgraphRelayout(result)
  }

  function closeSubgraphSession() {
    const snap = subgraphSnapshot.current
    subgraphSnapshot.current = null
    posAnimDoneRef.current = null
    setSubgraphAnimating(false)
    setSubgraph(null)
    if (!snap) {
      setTimeout(fitView, 60)
      return
    }
    setHidden(snap.hidden) // restore pre-isolation hides (fixes silent reappear)
    if (snap.layout !== layout) {
      // The layout effect re-lays out the full graph; suppress its auto-fit —
      // we restore the pre-isolation camera instead.
      suppressLayoutFitRef.current = true
      setLayout(snap.layout)
      animateViewTo(snap.view)
      return
    }
    if (layout === 'force') {
      posAnim.cancel()
      nodesRef.current.forEach(n => { if (!pinned.has(n.id)) { n.fx = null; n.fy = null } })
      simRef.current?.alpha(0.3).restart()
    } else {
      // Member nodes were moved by the isolate re-layout — tween the full
      // graph back to its deterministic positions (reverse choreography).
      const pos = computeLayoutPositions(layout)
      if (pos) {
        posAnim.setPositions(nodesRef.current.map(n => [n.id, { x: n.x, y: n.y }] as const))
        posAnim.animateTo(pos, LAYOUT_MS, easeInOutCubic)
      }
    }
    animateViewTo(snap.view)
  }

  // Compatibility wrapper for node-set call sites; the note is now derived
  // from subgraph stats via toSubgraphWorkspace.
  function openSubgraph(ids: Iterable<string>, title: string, note?: string, kind: SubgraphKind = 'neighborhood') {
    void note
    openSubgraphSession(buildSubgraph(graph, { nodeIds: ids }), kind, title)
  }

  // ── Minimap ────────────────────────────────────────────────────────────────
  const minimapData = useMemo(() => {
    const nodes = nodesRef.current
    if (!nodes.length) return null
    const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y)
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const gw = maxX - minX || 1, gh = maxY - minY || 1
    const sc = Math.min((MM_W - 8) / gw, (MM_H - 8) / gh) * 0.92
    const ox = (MM_W - gw * sc) / 2 - minX * sc
    const oy = (MM_H - gh * sc) / 2 - minY * sc
    const { x: px, y: py, z } = view
    const { w, h } = svgSize
    const vx = (-px / z) * sc + ox
    const vy = (-py / z) * sc + oy
    const vw = (w / z) * sc, vh = (h / z) * sc
    return { nodes, sc, ox, oy, vx, vy, vw, vh }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderTick, view, svgSize])

  // ── Computed visual sets ───────────────────────────────────────────────────
  const q = searchQuery.trim().toLowerCase()

  const neighborSet = useMemo(() => {
    if (!selected) return new Set<string>()
    const s = new Set<string>([selected, graph.seed])
    graph.edges.forEach(e => {
      if (e.source === selected) s.add(e.target)
      if (e.target === selected) s.add(e.source)
    })
    graph.correlations.forEach(c => {
      if (c.source === selected) s.add(c.target)
      if (c.target === selected) s.add(c.source)
    })
    return s
  }, [selected, graph])

  const visNodes = useMemo(() => {
    void renderTick
    return nodesRef.current.filter(n => {
      // During the isolate choreography non-members stay mounted (dimmed) so
      // the dim → re-layout → fit transition reads as one continuous motion;
      // they unmount when it completes.
      if (subgraph && !subgraph.ids.has(n.id) && !subgraphAnimating) return false
      if (hidden.has(n.id)) return false
      if (focusMode && selected && !neighborSet.has(n.id) && n.id !== graph.seed) return false
      return true
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderTick, hidden, focusMode, selected, neighborSet, graph.seed, subgraph, subgraphAnimating])

  const visIds = useMemo(() => new Set(visNodes.map(n => n.id)), [visNodes])

  const txEdges = useMemo(() => {
    const base = graph.edges.filter(e => visIds.has(e.source) && visIds.has(e.target))
    // Edge-restricted subgraph (flows/path isolation): render exactly the
    // isolated flows (directed pair keys). Skipped during the isolate
    // transition so member/non-member edges can dim in place first.
    const eks = subgraph?.edgeKeys
    if (!subgraphAnimating && eks && eks.size) {
      return base.filter(e => eks.has(edgePairKey(e.source, e.target))).slice(0, 300)
    }
    return base.slice(0, 300)
  }, [graph.edges, visIds, subgraph, subgraphAnimating])

  const scopedTxEdges = useMemo(() => {
    if (edgeScope === 'path' && pathEdgeSet.size > 0) {
      return txEdges.filter(e => pathEdgeSet.has(edgePairKey(e.source, e.target)) || pathEdgeSet.has(edgePairKey(e.target, e.source)))
    }
    if (edgeScope === 'selected' && selected) {
      return txEdges.filter(e => e.source === selected || e.target === selected || neighborSet.has(e.source) || neighborSet.has(e.target))
    }
    return txEdges
  }, [txEdges, edgeScope, pathEdgeSet, selected, neighborSet])

  const txBundles = useMemo(() => bundleTxEdges(scopedTxEdges), [scopedTxEdges])

  const renderTxBundles = useMemo<TxBundle[]>(() => {
    if (edgeMode === 'bundled') return txBundles
    return scopedTxEdges.map((edge, i) => ({
      key: `${edgePairKey(edge.source, edge.target)}|${edge.hash || i}`,
      source: edge.source,
      target: edge.target,
      value: Number(edge.value || 0),
      count: 1,
      token: edge.token || '',
      hashes: edge.hash ? [edge.hash] : [],
      type: edge.type || 'transaction',
      latestTime: edge.time || '',
      edges: [edge],
    }))
  }, [edgeMode, txBundles, scopedTxEdges])

  const selectedBundle = useMemo(
    () => renderTxBundles.find(bundle => bundle.key === selectedBundleKey) || null,
    [renderTxBundles, selectedBundleKey]
  )

  const selectedBundleNodes = useMemo(() => {
    if (!selectedBundle) return null
    return {
      source: graph.nodes.find(n => n.id === selectedBundle.source) || null,
      target: graph.nodes.find(n => n.id === selectedBundle.target) || null,
    }
  }, [graph.nodes, selectedBundle])

  const corrEdges = useMemo(() =>
    graph.correlations
      .filter(c => visIds.has(c.source) && visIds.has(c.target) && c.score >= minCorr)
      .filter(c => {
        if (edgeScope === 'path' && pathNodeSet.size > 0) return pathNodeSet.has(c.source) && pathNodeSet.has(c.target)
        if (edgeScope === 'selected' && selected) return c.source === selected || c.target === selected || neighborSet.has(c.source) || neighborSet.has(c.target)
        return true
      })
      .slice(0, edgeScope === 'all' ? 90 : 140),
    [graph.correlations, visIds, minCorr, edgeScope, pathNodeSet, selected, neighborSet]
  )

  const communityHulls = useMemo(() => {
    void renderTick
    const groups = new Map<string, SimNode[]>()
    visNodes.forEach(n => {
      const key = n.community || 'unclustered'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(n)
    })
    return Array.from(groups.entries())
      .filter(([, members]) => members.length >= 2)
      .map(([id, members]) => {
        const xs = members.map(n => n.x)
        const ys = members.map(n => n.y)
        const pad = 42
        const minX = Math.min(...xs) - pad
        const minY = Math.min(...ys) - pad
        const maxX = Math.max(...xs) + pad
        const maxY = Math.max(...ys) + pad
        const risk = Math.max(...members.map(n => n.risk_score))
        const volume = members.reduce((sum, n) => sum + (n.total_volume || 0), 0)
        return { id, x: minX, y: minY, w: maxX - minX, h: maxY - minY, size: members.length, risk, volume }
      })
  }, [renderTick, visNodes])

  const selectedNode = useMemo(() => graph.nodes.find(n => n.id === selected), [graph.nodes, selected])
  const selectedTxEdges = useMemo(() => selected
    ? graph.edges.filter(e => e.source === selected || e.target === selected)
    : [], [graph.edges, selected])
  const selectedCorrEdges = useMemo(() => selected
    ? graph.correlations.filter(c => c.source === selected || c.target === selected).sort((a, b) => b.score - a.score)
    : [], [graph.correlations, selected])
  const selectedFeatureEntries = useMemo(() => Object.entries(selectedNode?.features || {})
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .slice(0, 18), [selectedNode])
  const subgraphStats = useMemo(() => {
    if (!subgraph) return null
    // Model-driven stats: volume is FLOW volume (Σ isolated edge values), not
    // the old node-volume sum that double-counted internal flows.
    const r = subgraph.result ?? buildSubgraph(graph, { nodeIds: subgraph.ids, edgeKeys: subgraph.edgeKeys })
    return { ...r.stats, nodes: r.nodes, edges: r.edges, correlations: r.correlations }
  }, [graph, subgraph])

  // Chains currently on canvas (for the legend's chain row).
  const legendChains = useMemo(() => {
    const seen = new Map<string, { fill: string; stroke: string; label: string }>()
    for (const vn of visNodes) {
      const k = glyphKey(inferNodeChain(vn as SimNode, graph.chain))
      if (!seen.has(k)) seen.set(k, chainBadge(vn as SimNode, graph.chain))
      if (seen.size >= 8) break
    }
    return [...seen.entries()]
  }, [visNodes, graph.chain])

  const { x: vx, y: vy, z: vz } = view
  const { w: svgW, h: svgH } = svgSize

  // ── Edge layer wiring (NexusEdgeLayer) ──
  // Neutral slate for idle edges ('route'); in/out emerald/amber appears only
  // on emphasis (hover / selection / path / selected-node incident) per the
  // corporate color-restraint rule.
  const edgeTheme = useMemo(() => mergeEdgeTheme(pal.isLight ? lightEdgeTheme : darkEdgeTheme, {
    route: pal.isLight
      ? { stroke: '#64748b', chipBg: 'rgba(255,255,255,0.96)', chipBorder: 'rgba(100,116,139,0.45)', chipText: '#334155', particle: '#94a3b8' }
      : { stroke: '#8b95a5', chipBg: 'rgba(10,14,20,0.94)', chipBorder: 'rgba(139,149,165,0.4)', chipText: '#c3cad6', particle: '#aab3c2' },
  }), [pal.isLight])

  // During the isolate transition, member edges stay lit and everything else
  // dims; afterwards the normal path highlight applies.
  const edgeLayerPathKeys = subgraphAnimating && subgraph?.result ? subgraph.result.edgeKeys : pathEdgeSet

  const nodeAnchor = (id: string) => {
    const n = nodesRef.current.find(x => x.id === id)
    return n ? { x: n.x, y: n.y, r: nodeRadius(n, sizeMode) } : undefined
  }

  const edgeDirectionFor = (bundle: TxBundleLike, focusId: string | null): EdgeDirection => {
    const fwd = `${bundle.source}|${bundle.target}`
    const rev = `${bundle.target}|${bundle.source}`
    const emphasized =
      hoveredEdge === bundle.key ||
      selectedBundleKey === bundle.key ||
      pathEdgeSet.has(fwd) || pathEdgeSet.has(rev) ||
      (!!selected && (bundle.source === selected || bundle.target === selected))
    if (!emphasized) return 'route'
    const ref = focusId ?? graph.seed
    if (bundle.target === ref) return 'in'
    if (bundle.source === ref) return 'out'
    return 'route'
  }

  // Edge click → same selection state the old edge renderer used (opens the
  // transaction-link detail panel and marks the 2-node path).
  const onEdgeBundleClick = (key: string) => {
    const b = renderTxBundles.find(x => x.key === key)
    if (!b) return
    setSelectedBundleKey(b.key)
    setHoveredEdge(b.key)
    setPathEdgeSet(new Set([edgePairKey(b.source, b.target), edgePairKey(b.target, b.source)]))
    setPathNodeSet(new Set([b.source, b.target]))
    setPathOrder([b.source, b.target])
    onSelect(b.target)
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  const graphUI = (
    <div
      className={fullscreen ? 'fixed inset-0 z-[60] w-screen' : 'relative w-full'}
      style={{
        height: fullscreen ? '100dvh' : 'clamp(680px, 72vh, 880px)',
        border: '1px solid rgb(var(--bg-border))',
        borderRadius: fullscreen ? 0 : 12,
        overflow: 'hidden',
        background: pal.bg,
      }}
    >

      {/* ── Toolbar ── */}
      <div className="absolute top-3 left-3 right-3 z-20 flex flex-col gap-2 xl:flex-row xl:items-start xl:justify-between">
        <div className={`grid w-full gap-2 rounded-xl p-2 sm:w-[390px] xl:w-[410px] ${graphViewOpen ? 'sm:grid-cols-2' : ''}`}
          style={{ background: 'rgb(var(--bg-elevated) / 0.96)', border: '1px solid rgb(var(--bg-border))', backdropFilter: 'blur(14px)', boxShadow: '0 18px 45px rgba(0,0,0,0.24)' }}>
          <button
            type="button"
            onClick={() => setGraphViewOpen(v => !v)}
            className={`flex items-center justify-between gap-2 text-left ${graphViewOpen ? 'sm:col-span-2 border-b border-border/60 pb-2' : ''}`}
            title={graphViewOpen ? 'Collapse Graph View controls' : 'Expand Graph View controls'}
          >
            <div className="flex min-w-0 items-center gap-2">
              {graphViewOpen ? <ChevronDown size={14} className="text-neon-cyan shrink-0" /> : <ChevronRight size={14} className="text-neon-cyan shrink-0" />}
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-widest text-text-muted">Graph View</p>
                <p className="truncate text-[11px] text-text-dim">
                  {graphViewOpen ? 'Layout, search, and link sensitivity' : `${layout} · ${sizeMode} · links ${pct(minCorr)}`}
                </p>
              </div>
            </div>
            <span className="rounded border border-neon-cyan/30 bg-neon-cyan/10 px-2 py-0.5 font-mono text-[10px] text-neon-cyan">
              {visNodes.length} nodes
            </span>
          </button>

          {graphViewOpen && (
            <>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-widest text-text-muted">Layout</span>
                <select value={layout} onChange={e => setLayout(e.target.value as LayoutMode)}
                  title="Graph layout"
                  className="h-9 w-full rounded-md px-2 text-xs text-text-secondary"
                  style={{ background: 'rgb(var(--bg-secondary) / 0.96)', border: '1px solid rgb(var(--bg-border))', outline: 'none' }}>
                  <option value="flow">Flow (fund trace)</option>
                  <option value="force">Force physics</option>
                  <option value="community">Community</option>
                  <option value="radial">Radial</option>
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-widest text-text-muted">Node Size</span>
                <select value={sizeMode} onChange={e => setSizeMode(e.target.value as SizeMode)}
                  title="Node size metric"
                  className="h-9 w-full rounded-md px-2 text-xs text-text-secondary"
                  style={{ background: 'rgb(var(--bg-secondary) / 0.96)', border: '1px solid rgb(var(--bg-border))', outline: 'none' }}>
                  <option value="risk">Risk</option>
                  <option value="degree">Degree</option>
                  <option value="volume">Volume</option>
                  <option value="uniform">Uniform</option>
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-widest text-text-muted">Trace Lines</span>
                <select value={edgeMode} onChange={e => setEdgeMode(e.target.value as EdgeMode)}
                  title="Transaction edge rendering"
                  className="h-9 w-full rounded-md px-2 text-xs text-text-secondary"
                  style={{ background: 'rgb(var(--bg-secondary) / 0.96)', border: '1px solid rgb(var(--bg-border))', outline: 'none' }}>
                  <option value="bundled">Bundled pairs</option>
                  <option value="detail">Raw transactions</option>
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-widest text-text-muted">Trace Scope</span>
                <select value={edgeScope} onChange={e => setEdgeScope(e.target.value as EdgeScope)}
                  title="Visible transaction scope"
                  className="h-9 w-full rounded-md px-2 text-xs text-text-secondary"
                  style={{ background: 'rgb(var(--bg-secondary) / 0.96)', border: '1px solid rgb(var(--bg-border))', outline: 'none' }}>
                  <option value="all">All visible flows</option>
                  <option value="selected">Selected neighborhood</option>
                  <option value="path">Marked path only</option>
                </select>
              </label>

              <div className="relative sm:col-span-2">
                <span className="mb-1 block text-[10px] uppercase tracking-widest text-text-muted">Find Wallet</span>
                <Search size={14} className="absolute left-3 top-[31px] text-text-muted pointer-events-none" />
                <input
                  className="h-9 w-full rounded-md py-1 pl-9 pr-2 text-xs text-text-secondary"
                  style={{ background: 'rgb(var(--bg-secondary) / 0.96)', border: '1px solid rgb(var(--bg-border))', outline: 'none' }}
                  placeholder="Search address, role, or cluster..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                />
              </div>

              <div className="sm:col-span-2 rounded-md px-3 py-2"
                title="Correlation threshold"
                style={{ background: 'rgb(var(--bg-secondary) / 0.78)', border: '1px solid rgb(var(--bg-border))' }}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-text-muted">
                    <Route size={12} /> Link Sensitivity
                  </span>
                  <span className="font-mono text-xs text-neon-cyan">{pct(minCorr)}</span>
                </div>
                <input type="range" min="0.1" max="0.9" step="0.05" value={minCorr}
                  className="w-full accent-cyan-400"
                  onChange={e => setMinCorr(Number(e.target.value))} />
              </div>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5 rounded-xl p-1.5 xl:justify-end"
          style={{ background: 'rgb(var(--bg-elevated) / 0.9)', border: '1px solid rgb(var(--bg-border))', backdropFilter: 'blur(14px)' }}>
          {/* Layout selector — always visible (not hidden in Graph View panel) */}
          <select value={layout} onChange={e => setLayout(e.target.value as LayoutMode)}
            title="Graph layout mode"
            className="h-8 rounded-md px-2 text-[11px] font-semibold text-text-secondary cursor-pointer"
            style={{ background: layout !== 'flow' ? 'rgba(220,38,38,0.1)' : 'transparent', border: `1px solid ${layout !== 'flow' ? 'rgba(220,38,38,0.3)' : 'rgb(var(--bg-border))'}`, color: layout !== 'flow' ? '#dc2626' : undefined, outline: 'none' }}>
            <option value="flow">⇥ Flow</option>
            <option value="force">◌ Force</option>
            <option value="community">◉ Community</option>
            <option value="radial">◎ Radial</option>
          </select>
          <div className="w-px h-6 bg-bg-border mx-0.5" />
          <GraphToolButton title={edgeMode === 'bundled' ? 'Showing bundled wallet-pair flows' : 'Showing raw transaction edges'} icon={Route} active={edgeMode === 'bundled'} onClick={() => setEdgeMode(m => m === 'bundled' ? 'detail' : 'bundled')}>
            {edgeMode === 'bundled' ? 'Bundled' : 'Raw'}
          </GraphToolButton>
          <GraphToolButton title="Show only selected wallet neighborhood links" icon={Target} active={edgeScope === 'selected'} onClick={() => setEdgeScope(s => s === 'selected' ? 'all' : 'selected')}>
            Scope
          </GraphToolButton>
          <GraphToolButton title="Show labels" icon={Tag} active={showLabels} onClick={() => setShowLabels(!showLabels)} />
          <GraphToolButton title="Animate value flow" icon={Route} active={showFlow} onClick={() => setShowFlow(!showFlow)} />
          <GraphToolButton title="Focus selected neighborhood" icon={Target} active={focusMode} onClick={() => setFocusMode(!focusMode)} />
          <GraphToolButton title="Show nested community regions" icon={Layers} active={showClusters} onClick={() => setShowClusters(!showClusters)} />
          <GraphToolButton title="Show graph investigator panel" icon={Shield} active={showInspector} onClick={() => setShowInspector(!showInspector)} />
          {selected && onExpandNode && (
            <GraphToolButton
              title="Expand selected wallet"
              icon={expandingNode === selected ? Loader2 : GitBranch}
              active
              disabled={expandingNode === selected}
              spinning={expandingNode === selected}
              onClick={() => void requestExpansion(selected, { hops: 1, mode: 'wide', direction: 'both' })}
            >
              Expand
            </GraphToolButton>
          )}
          {pathNodeSet.size > 0 && (
            <GraphToolButton
              title="Open marked path as subgraph"
              icon={GitBranch}
              active={subgraph?.kind === 'path'}
              onClick={() => {
                if (pathOrder.length > 1) {
                  openSubgraphSession(subgraphFromPath(graph, pathOrder), 'path', `Path · ${pathOrder.length - 1} hops`)
                } else {
                  openSubgraph(pathNodeSet, `Marked path · ${pathNodeSet.size} nodes`, undefined, 'path')
                }
              }}
            >
              Path
            </GraphToolButton>
          )}
          {lastTraceIds.size > 0 && (
            <GraphToolButton
              title="Open latest trace expansion as subgraph"
              icon={Network}
              active={subgraph?.kind === 'trace'}
              onClick={() => openSubgraph(lastTraceIds, `Latest trace expansion · ${lastTraceIds.size} nodes`, undefined, 'trace')}
            >
              Trace
            </GraphToolButton>
          )}
          {selected && neighborSet.size > 1 && (
            <GraphToolButton
              title="Open selected wallet neighborhood as subgraph"
              icon={Target}
              active={subgraph?.kind === 'neighborhood'}
              onClick={() => openSubgraph(neighborSet, `Neighborhood · ${shortAddr(selectedNode?.address || selected)}`)}
            >
              Subgraph
            </GraphToolButton>
          )}
          <GraphToolButton title="Zoom in" icon={ZoomIn} onClick={() => { const v = viewRef.current; animateViewTo({ x: v.x, y: v.y, z: Math.min(6, v.z * 1.25) }) }} />
          <GraphToolButton title="Zoom out" icon={ZoomOut} onClick={() => { const v = viewRef.current; animateViewTo({ x: v.x, y: v.y, z: Math.max(0.08, v.z * 0.8) }) }} />
          <GraphToolButton title="Fit graph to view" icon={Scan} onClick={fitView} disabled={subgraphAnimating} />
          <GraphToolButton title="Re-spread tangled nodes (reheat simulation)" icon={Sparkles} onClick={() => {
            const sim = simRef.current
            const nodes = nodesRef.current
            if (!sim || !nodes.length) return
            // Unpin everything except explicitly-pinned nodes, then reheat at
            // high alpha so the force simulation re-spreads the layout.
            nodes.forEach(n => { if (!pinned.has(n.id)) { n.fx = null; n.fy = null } })
            sim.alpha(0.9).alphaTarget(0.15).restart()
            setTimeout(() => sim.alphaTarget(0), 2500)
            setTimeout(fitView, 3000)
          }} />
          <GraphToolButton title="Reset view" icon={RotateCcw} onClick={() => animateViewTo(HOME_VIEW)} />
          <GraphToolButton title="Toggle on-canvas legend" icon={Info} active={showLegend} onClick={() => setShowLegend(v => !v)} />
          <button
            type="button"
            title="Restore the original Nexus graph and clear overlays, hidden nodes, tags, pinned positions, subgraphs, paths, and filters"
            onClick={restoreOriginalGraph}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md px-3 text-[11px] font-semibold transition-colors"
            style={{
              background: 'rgba(255,64,82,0.13)',
              border: '1px solid rgba(255,64,82,0.45)',
              color: '#ff4052',
            }}
          >
            <RotateCcw size={13} />
            Restore the Original Graph
          </button>
          <button
            type="button"
            title={fullscreen ? 'Exit fullscreen workspace' : 'Open fullscreen workspace'}
            onClick={() => setFullscreen(v => !v)}
            className="inline-flex h-8 items-center justify-center rounded-md px-3 text-[11px] font-semibold uppercase tracking-wider transition-colors"
            style={{
              background: fullscreen ? 'rgba(255,64,82,0.13)' : 'rgb(var(--bg-elevated) / 0.92)',
              border: `1px solid ${fullscreen ? 'rgba(255,64,82,0.45)' : 'rgb(var(--bg-border))'}`,
              color: fullscreen ? '#ff4052' : '#9a858c',
            }}
          >
            {fullscreen ? 'Exit Full Screen' : 'Full Screen'}
          </button>
          <GraphToolButton title="Export court-presentable exhibit (case header, legend, SHA-256, custody chain)" icon={Download} onClick={() => svgRef.current && exportNexusExhibit(svgRef.current, graph)}>Exhibit</GraphToolButton>
          <GraphToolButton title="Export graph PNG" icon={Download} onClick={() => svgRef.current && exportPNG(svgRef.current)}>PNG</GraphToolButton>
          <GraphToolButton title={subgraph ? 'Export active subgraph JSON' : 'Export graph JSON'} icon={Download} disabled={subgraphAnimating} onClick={() => subgraph ? exportSubgraphJSON(graph, subgraph) : exportJSON(graph)}>JSON</GraphToolButton>
          <GraphToolButton title="Save this investigation as an editable Board (persistent canvas, annotations, sharing)"
            icon={LayoutDashboard} onClick={saveToBoard} active={savingBoard} spinning={savingBoard} disabled={savingBoard}>
            {savingBoard ? 'Saving…' : 'Save to Board'}
          </GraphToolButton>
          {linkedBoards.map(b => (
            <button key={b.board_id} type="button"
              title={`Open linked board: ${b.name}${b.open_comments ? ` · ${b.open_comments} open comments` : ''}`}
              onClick={() => navigate(`/boards/${b.board_id}`)}
              className="inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[11px] font-semibold uppercase tracking-wider transition-colors"
              style={{ background: 'rgba(10,132,255,0.13)', border: '1px solid rgba(10,132,255,0.4)', color: '#4aa3ff' }}>
              <LayoutDashboard size={13} />
              {b.name && b.name.length > 16 ? `${b.name.slice(0, 15)}…` : b.name || 'Board'}
            </button>
          ))}
        </div>
      </div>

      {/* ── Path mode banner ── */}
      {pathSrc && !pathDst && (
        <div className="absolute top-[92px] left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 text-xs rounded-lg px-3 py-1.5"
          style={{ background: 'rgba(255,64,82,0.12)', border: '1px solid rgba(255,64,82,0.4)', color: '#ff4052' }}>
          <Navigation size={11} />
          Path from <span className="font-mono">{shortAddr(graph.nodes.find(n => n.id === pathSrc)?.address || pathSrc)}</span>
          - click target node
          <button onClick={() => { setPathSrc(null); setPathNodeSet(new Set()); setPathEdgeSet(new Set()); setPathOrder([]) }}
            className="opacity-60 hover:opacity-100"><X size={10} /></button>
        </div>
      )}

      {/* ── Path result ── */}
      {pathNodeSet.size > 0 && (
        <div className="absolute bottom-[100px] right-3 z-20 flex items-center gap-2 text-xs rounded-lg px-3 py-1.5"
          style={{ background: 'rgba(0,255,136,0.1)', border: '1px solid rgba(0,255,136,0.35)', color: '#00ff88' }}>
          Path: {pathNodeSet.size} hops
          <button onClick={() => { setPathNodeSet(new Set()); setPathEdgeSet(new Set()); setPathOrder([]); setPathSrc(null); setPathDst(null) }}
            className="opacity-60 hover:opacity-100"><X size={10} /></button>
        </div>
      )}

      {selectedBundle && selectedBundleNodes && (
        <div
          className="absolute bottom-3 left-3 z-30 w-[min(480px,calc(100vw-32px))] rounded-xl p-3"
          style={{ background: 'rgba(5,7,13,0.94)', border: '1px solid rgba(56,224,255,0.24)', boxShadow: '0 20px 50px rgba(0,0,0,0.38)', backdropFilter: 'blur(14px)' }}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className="rounded px-2 py-0.5 font-mono text-[10px] font-black"
                  style={{
                    color: selectedBundle.target === graph.seed ? '#ffb020' : selectedBundle.source === graph.seed ? '#46f0a0' : '#38e0ff',
                    background: selectedBundle.target === graph.seed ? 'rgba(255,176,32,0.12)' : selectedBundle.source === graph.seed ? 'rgba(70,240,160,0.12)' : 'rgba(56,224,255,0.12)',
                    border: '1px solid currentColor',
                  }}
                >
                  {selectedBundle.target === graph.seed ? 'INBOUND' : selectedBundle.source === graph.seed ? 'OUTBOUND' : 'ROUTE'}
                </span>
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">transaction link</span>
              </div>
              <div className="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
                <button
                  className="min-w-0 rounded-lg border border-border/60 bg-bg-secondary/60 px-2 py-1.5 text-left hover:border-neon-cyan/60"
                  onClick={() => selectedBundleNodes.source && onSelect(selectedBundleNodes.source.id)}
                >
                  <p className="truncate font-mono text-[11px] font-bold text-text-primary">{selectedBundleNodes.source ? tacticalNodeLabel(selectedBundleNodes.source) : selectedBundle.source}</p>
                  <p className="truncate font-mono text-[9px] text-text-muted">{selectedBundleNodes.source ? shortAddr(selectedBundleNodes.source.address) : selectedBundle.source}</p>
                </button>
                <span className="font-mono text-sm font-black text-neon-green">→</span>
                <button
                  className="min-w-0 rounded-lg border border-border/60 bg-bg-secondary/60 px-2 py-1.5 text-left hover:border-neon-cyan/60"
                  onClick={() => selectedBundleNodes.target && onSelect(selectedBundleNodes.target.id)}
                >
                  <p className="truncate font-mono text-[11px] font-bold text-text-primary">{selectedBundleNodes.target ? tacticalNodeLabel(selectedBundleNodes.target) : selectedBundle.target}</p>
                  <p className="truncate font-mono text-[9px] text-text-muted">{selectedBundleNodes.target ? shortAddr(selectedBundleNodes.target.address) : selectedBundle.target}</p>
                </button>
              </div>
            </div>
            <button
              className="rounded-md p-1 text-text-muted hover:bg-bg-secondary hover:text-text-primary"
              onClick={() => { setSelectedBundleKey(null); setHoveredEdge(null); setPathSrc(null); setPathDst(null); setPathNodeSet(new Set()); setPathEdgeSet(new Set()); setPathOrder([]) }}
              aria-label="Close transaction link details"
            >
              <X size={14} />
            </button>
          </div>

          <div className="mt-3 grid grid-cols-3 gap-2">
            <div className="rounded-lg border border-border/50 bg-black/20 px-2 py-1.5">
              <p className="font-mono text-[9px] uppercase tracking-widest text-text-muted">value</p>
              <p className="font-mono text-[12px] font-black text-neon-green">{flowValueLabel(selectedBundle.value, selectedBundle.token)}</p>
            </div>
            <div className="rounded-lg border border-border/50 bg-black/20 px-2 py-1.5">
              <p className="font-mono text-[9px] uppercase tracking-widest text-text-muted">tx count</p>
              <p className="font-mono text-[12px] font-black text-text-primary">{selectedBundle.count}</p>
            </div>
            <div className="rounded-lg border border-border/50 bg-black/20 px-2 py-1.5">
              <p className="font-mono text-[9px] uppercase tracking-widest text-text-muted">latest</p>
              <p className="truncate font-mono text-[12px] font-black text-text-primary">{selectedBundle.latestTime || '-'}</p>
            </div>
          </div>

          {selectedBundle.hashes.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {selectedBundle.hashes.slice(0, 4).map(hash => (
                <span key={hash} className="max-w-[210px] truncate rounded border border-border/60 bg-bg-secondary/50 px-2 py-0.5 font-mono text-[9px] text-text-muted">
                  {hash}
                </span>
              ))}
            </div>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="rounded-lg border border-neon-green/40 bg-neon-green/10 px-2.5 py-1.5 font-mono text-[10px] font-bold text-neon-green hover:bg-neon-green/15"
              onClick={() => {
                const path = doFindPath(selectedBundle.source, selectedBundle.target)
                setPathSrc(selectedBundle.source)
                setPathDst(selectedBundle.target)
                if (path.length <= 1) {
                  setPathNodeSet(new Set([selectedBundle.source, selectedBundle.target]))
                  setPathEdgeSet(new Set([edgePairKey(selectedBundle.source, selectedBundle.target), edgePairKey(selectedBundle.target, selectedBundle.source)]))
                  setPathOrder([selectedBundle.source, selectedBundle.target])
                }
              }}
            >
              Trace path
            </button>
            <button
              className="rounded-lg border border-neon-cyan/35 bg-neon-cyan/10 px-2.5 py-1.5 font-mono text-[10px] font-bold text-neon-cyan hover:bg-neon-cyan/15"
              title="Isolate exactly this transaction link (both endpoints + their flows) as a subgraph"
              onClick={() => {
                if (!selectedBundle) return
                const src = selectedBundleNodes?.source
                const dst = selectedBundleNodes?.target
                openSubgraphSession(
                  subgraphFromBundles(graph, [selectedBundle]),
                  'flows',
                  `Flows · ${src ? tacticalNodeLabel(src) : shortAddr(selectedBundle.source)} → ${dst ? tacticalNodeLabel(dst) : shortAddr(selectedBundle.target)}`,
                )
              }}
            >
              Isolate these flows
            </button>
            {onExpandNode && (
              <button
                className="rounded-lg border border-border/70 bg-bg-secondary/70 px-2.5 py-1.5 font-mono text-[10px] font-bold text-text-primary hover:border-neon-cyan/50"
                onClick={() => onExpandNode(selectedBundle.target, { hops: 1, direction: 'out', mode: 'wide' })}
              >
                Expand target
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Subgraph breadcrumb (single navigation surface; stats live in the bottom panel) ── */}
      {subgraph && (
        <div className="absolute left-1/2 top-[92px] z-30 flex max-w-[min(640px,calc(100vw-24px))] -translate-x-1/2 items-center gap-1.5 rounded-xl px-3 py-1.5"
          style={{ background: 'rgb(var(--bg-elevated) / 0.96)', border: '1px solid rgb(var(--bg-border))', backdropFilter: 'blur(12px)' }}>
          <button className="shrink-0 text-[11px] font-semibold text-text-muted hover:text-neon-cyan"
            onClick={closeSubgraphSession}>Full graph</button>
          <ChevronRight size={11} className="shrink-0 text-text-muted" />
          <span className="truncate text-xs font-semibold text-neon-cyan">{subgraph.title}</span>
          <span className="shrink-0 text-[10px] text-text-muted">{subgraph.note}</span>
          <button className="ml-1 shrink-0 text-text-muted hover:text-neon-cyan" title="Return to full graph (Esc)"
            onClick={closeSubgraphSession}><X size={11} /></button>
        </div>
      )}

      {/* ── Restore hidden ── */}
      {hidden.size > 0 && (
        <button onClick={() => setHidden(new Set())}
          className="absolute bottom-[100px] left-3 z-20 flex items-center gap-1.5 text-xs rounded px-2 py-1 text-text-muted hover:text-neon-cyan"
          style={{ background: 'rgb(var(--bg-elevated) / 0.92)', border: '1px solid rgb(var(--bg-border))' }}>
          <EyeOff size={10} />{hidden.size} hidden - Restore all
        </button>
      )}

      {expandingNode && (
        <div className="absolute top-[92px] right-3 z-30 flex items-center gap-2 text-xs rounded-lg px-3 py-1.5 text-neon-green"
          style={{ background: 'rgba(0,255,136,0.1)', border: '1px solid rgba(0,255,136,0.35)' }}>
          <Loader2 size={12} className="animate-spin" />
          Expanding {shortAddr(graph.nodes.find(n => n.id === expandingNode)?.address || expandingNode)}
        </div>
      )}

      {/* ── SVG Canvas ── */}
      <svg
        ref={svgRef}
        className="w-full h-full"
        style={{ cursor: isPanning.current ? 'grabbing' : 'grab', display: 'block' }}
        onMouseDown={onSvgDown}
        onMouseMove={onSvgMove}
        onMouseUp={onSvgUp}
        onMouseLeave={onSvgUp}
        onContextMenu={e => e.preventDefault()}
      >
        <defs>
          {/* ── Glow filters ── */}
          <filter id="g-cyan" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="5" result="b" />
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="g-red" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="g-green" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <filter id="g-search" x="-70%" y="-70%" width="240%" height="240%">
            <feGaussianBlur stdDeviation="6" result="b" />
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>

          {/* ── Node gradients ── */}
          <radialGradient id="seed-grad" cx="50%" cy="42%" r="62%">
            <stop offset="0%" stopColor="#ff6b7a" stopOpacity="0.95" />
            <stop offset="60%" stopColor="#ff4052" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#dc2626" stopOpacity="0.3" />
          </radialGradient>
          {/* Glossy sphere shading over the brand disc (crypto-icon look) */}
          <radialGradient id="node-shine" cx="35%" cy="26%" r="78%">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.4" />
            <stop offset="40%" stopColor="#ffffff" stopOpacity="0.08" />
            <stop offset="80%" stopColor="#000000" stopOpacity="0.14" />
            <stop offset="100%" stopColor="#000000" stopOpacity="0.32" />
          </radialGradient>
          {/* High-risk node inner gradient (glowing red core) */}
          <radialGradient id="node-danger" cx="40%" cy="35%" r="70%">
            <stop offset="0%" stopColor="#fca5a5" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#7f1d1d" stopOpacity="0.5" />
          </radialGradient>

          {/* ── Node drop shadows ── */}
          <filter id="n-drop" x="-60%" y="-60%" width="220%" height="220%">
            <feDropShadow dx="0" dy="2" stdDeviation="3.2" floodColor="#000000" floodOpacity="0.6" />
          </filter>
          <filter id="n-drop-sm" x="-50%" y="-50%" width="200%" height="200%">
            <feDropShadow dx="0" dy="1.5" stdDeviation="2" floodColor="#000000" floodOpacity="0.4" />
          </filter>
        </defs>

        {/* Background */}
        <rect width="100%" height="100%" fill={pal.bg} />
        <g opacity={pal.isLight ? 0.5 : 0.07}>
          {Array.from({ length: 26 }).map((_, i) => (
            <line key={`v${i}`} x1={i * 52} y1="0" x2={i * 52} y2="100%" stroke={pal.grid} strokeWidth="0.5" />
          ))}
          {Array.from({ length: 16 }).map((_, i) => (
            <line key={`h${i}`} x1="0" y1={i * 50} x2="100%" y2={i * 50} stroke={pal.grid} strokeWidth="0.5" />
          ))}
        </g>

        <g transform={`translate(${vx},${vy}) scale(${vz})`}>


          {/* Community hulls */}
          {layout !== 'flow' && showClusters && communityHulls.map(hull => {
            const color = communityColor(hull.id)
            return (
              <g key={`hull-${hull.id}`} opacity="0.72">
                <rect
                  x={hull.x}
                  y={hull.y}
                  width={hull.w}
                  height={hull.h}
                  rx={28}
                  fill={color}
                  fillOpacity="0.035"
                  stroke={color}
                  strokeOpacity="0.26"
                  strokeWidth="1.2"
                  strokeDasharray="8 8"
                />
                <text x={hull.x + 14} y={hull.y + 20} fill={color} fontSize="10" fontFamily="monospace" opacity={pal.isLight ? 0.95 : 0.72}>
                  {hull.id} · {hull.size} wallets · max risk {hull.risk}
                </text>
              </g>
            )
          })}

          {/* Transaction edges — NexusEdgeLayer (§3.5: rendered before nodes) */}
          <NexusEdgeLayer
            bundles={renderTxBundles}
            resolveNode={nodeAnchor}
            focusId={selected ?? graph.seed}
            hoveredKey={hoveredEdge}
            selectedKey={selectedBundleKey}
            pathEdgeKeys={edgeLayerPathKeys}
            showLabels={renderTxBundles.length > 60 && vz < 0.9 ? 'active' : 'always'}
            showParticles={showFlow}
            mode={pal.isLight ? 'light' : 'dark'}
            theme={edgeTheme}
            directionFor={edgeDirectionFor}
            onHover={setHoveredEdge}
            onClick={onEdgeBundleClick}
          />

          {/* Correlation edges */}
          {layout !== 'flow' && corrEdges.map((edge, i) => {
            const sn = nodesRef.current.find(n => n.id === edge.source)
            const tn = nodesRef.current.find(n => n.id === edge.target)
            if (!sn || !tn) return null
            const isHot = selected === edge.source || selected === edge.target
            const isPath = pathEdgeSet.has(edgePairKey(edge.source, edge.target)) || pathEdgeSet.has(edgePairKey(edge.target, edge.source))
            const isScoped = edgeScope !== 'all' || isHot || isPath
            const stroke = isPath ? '#fbbf24' : isHot ? '#a78bfa' : (pal.isLight ? '#64748b' : '#94a3b8')
            const opacity = isPath ? 0.65 : isHot ? 0.38 : isScoped ? 0.22 : 0.06
            return (
              <line key={`corr-${i}`}
                x1={sn.x} y1={sn.y} x2={tn.x} y2={tn.y}
                stroke={stroke}
                strokeWidth={isPath ? 1.8 : isHot ? 1.2 : 0.7}
                strokeDasharray={isPath ? "4 7" : "1 9"}
                strokeLinecap="round"
                opacity={opacity}
                style={{ cursor: 'pointer' }}
              />
            )
          })}

          {/* Nodes — rendered in every layout (flow included); only the
              community hulls and correlation edges above are flow-suppressed. */}
          {visNodes.map(simNode => {
            const n = simNode as SimNode
            const isSeed = n.id === graph.seed
            const isSel = selected === n.id
            const isNbr = !isSeed && !isSel && neighborSet.has(n.id)
            const isPath = pathNodeSet.has(n.id)
            const isHover = hovered === n.id
            const matchQ = q !== '' && (
              n.address.toLowerCase().includes(q) ||
              (n.arkham_owner?.name || '').toLowerCase().includes(q) ||
              n.role_hint.toLowerCase().includes(q) ||
              n.community.toLowerCase().includes(q)
            )
            const isPinned = pinned.has(n.id)
            const r = nodeRadius(n, sizeMode)
            const color = isSeed ? '#ff4052' : riskColor(n.risk_score)
            const commColor = communityColor(n.community)

            const opacity = focusMode && selected && !isSel && !isNbr && !isSeed ? 0.08
              : isPath ? 1 : isSel || isSeed ? 1 : matchQ ? 1 : 0.88

            const ringColor = isPath ? '#ffb300' : isSel ? '#ffffff' : isNbr ? '#ff9f0a' : matchQ ? '#ffd60a' : color
            const ringW = isSel || isPath ? 2.5 : matchQ ? 2 : isPinned ? 2 : 1.5
            const glow = isPath ? 'url(#g-green)' : isSel ? 'url(#g-cyan)' : matchQ ? 'url(#g-search)' : n.risk_score >= 75 ? 'url(#g-red)' : undefined
            const ownerName = n.arkham_owner?.name || ''
            const labelText = isHover || isSel
              ? (ownerName ? `${ownerName} · ${shortAddr(n.address)}` : n.address)
              : (ownerName || n.short || shortAddr(n.address))
            // ── Density- and zoom-aware label visibility ──
            // When the graph is dense (many nodes) or zoomed out, showing every
            // label creates unreadable noise. Only show labels for: hovered/
            // selected nodes, high-risk nodes (≥60), the seed, and pinned nodes.
            // As zoom increases past 1.4×, progressively show more labels.
            const nodeCount = visNodes.length
            const denseGraph = nodeCount > 40
            const labelEligible = isHover || isSel || isPinned || n.id === graph.seed
              || n.risk_score >= 60
              || (!denseGraph)               // small graphs: show all
              || (vz > 1.4 && nodeCount <= 80) // zoomed into medium graph
              || (vz > 2.2)                  // deep zoom: show all
            const showThisLabel = showLabels && labelEligible
            // Shorter labels when dense (just short address, no owner) to save space
            const displayLabel = denseGraph && !isHover && !isSel
              ? (ownerName || n.short || shortAddr(n.address))
              : labelText
            const labelW = Math.min(denseGraph ? 220 : 390, Math.max(64, displayLabel.length * 6.4 + 12))
            const badge = chainBadge(n, graph.chain)
            const chainKey = glyphKey(inferNodeChain(n, graph.chain))
            const discR = Math.max(8, r - 3.5)
            const riskC = 2 * Math.PI * (r + 1.5)
            const isolateDim = !!(subgraphAnimating && subgraph && !subgraph.ids.has(n.id))

            return (
              <g key={n.id} data-node={n.id}
                transform={`translate(${n.x},${n.y})`}
                style={{ cursor: 'pointer', opacity: isolateDim ? 0.1 : opacity, transition: 'opacity 380ms ease' }}
                onMouseDown={e => onNodeDown(e, n.id)}
                onClick={e => onNodeClick(e, n.id)}
                onDoubleClick={e => onNodeDblClick(e, n.id)}
                onContextMenu={e => onNodeCtx(e, n.id)}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(prev => prev === n.id ? null : prev)}
              >
                {/* Native hover tooltip with the full address */}
                <title>{`${n.address}${ownerName ? '  ·  Arkham: ' + ownerName : ''}${n.role_hint && n.role_hint !== 'unknown' ? '  ·  ' + n.role_hint : ''}  ·  risk ${n.risk_score}  ·  type ${classifyEntity({ roleHint: n.role_hint, labels: n.labels, bridgeScore: n.bridge_score, arkhamOwner: n.arkham_owner })}`}</title>

                {/* ── GraphNodeKit body ──
                    Type-aware shape (shield=exchange, hex=mixer, diamond=bridge,
                    triangle=scam, square=contract, circle=wallet) + unified
                    risk-arc ring (fixes the old low-risk=crimson bug) + chain
                    brand glyph + type badge + motif chip. The Nexus-specific
                    state (selection/path/pin rings, label, tag) is rendered by
                    the wrapper below so existing interactions are unchanged. */}
                <GraphNodeKit
                  r={r}
                  entity={{ roleHint: n.role_hint, labels: n.labels, bridgeScore: n.bridge_score, arkhamOwner: n.arkham_owner, chain: graph.chain }}
                  riskScore={n.risk_score}
                  chain={graph.chain}
                  motifCount={n.motif_count}
                  isSeed={isSeed}
                  selected={isSel}
                  hovered={isHover}
                  dimmed={opacity < 0.5}
                  onPath={isPath}
                  showLabel={false}
                  showTypeBadge={vz > 0.5}
                  seedColor="#ff4052"
                />

                {/* Nexus selection / highlight outer ring (kept for the rich
                    path/neighbor/query emphasis the kit's simpler ring doesn't cover) */}
                {(isSel || isPath || isHover || matchQ) && (
                  <circle r={r + 9} fill="none"
                    stroke={ringColor} strokeWidth={ringW}
                    strokeDasharray={isPath ? '7 4' : isPinned ? '4 3' : undefined}
                    opacity={0.92}
                    filter={glow}
                  />
                )}

                {/* Risk-score chip (below node) — compact, always visible */}
                {(n.risk_score > 0 || isSeed) && (
                  <g transform={`translate(0, ${r + 11})`} style={{ pointerEvents: 'none' }}>
                    <rect x="-14" y="-7.5" width="28" height="13" rx={6.5}
                      fill={pal.isLight ? 'rgba(255,255,255,0.95)' : 'rgba(10,12,18,0.9)'}
                      stroke={color}
                      strokeWidth={n.risk_score >= 70 ? 1.1 : 0.7}
                      filter={n.risk_score >= 80 ? 'url(#n-drop-sm)' : undefined} />
                    <text textAnchor="middle" y={2.8}
                      fill={color}
                      fontSize="8.5"
                      fontFamily="monospace"
                      fontWeight="bold">
                      {n.risk_score > 0 ? n.risk_score : 'SEED'}
                    </text>
                  </g>
                )}

                {/* Pin indicator (top-right) */}
                {isPinned && (
                  <g transform={`translate(${r - 2},${-r + 2})`} style={{ pointerEvents: 'none' }}>
                    <circle r={5} fill={pal.isLight ? '#fff' : pal.nodePlate} stroke="#ff9f0a" strokeWidth={1.5} />
                    <text y={2.5} textAnchor="middle" fontSize={6.5} fill="#ff9f0a" fontWeight="bold">P</text>
                  </g>
                )}

                {/* Label - density-aware: only eligible nodes labelled to avoid clutter.
                    Professional chip with a left accent bar in the node's risk color. */}
                {showThisLabel && (
                  <g transform={`translate(${r + 8}, -12)`} style={{ pointerEvents: 'none' }}>
                    {/* Left accent bar — encodes the node's risk/type color */}
                    <rect x="0" y="0" width="3" height={n.role_hint && n.role_hint !== 'unknown' ? 30 : 20} rx={1.5} fill={color} />
                    <rect
                      x="4"
                      y="0"
                      width={labelW}
                      height={n.role_hint && n.role_hint !== 'unknown' ? 30 : 20}
                      rx="4"
                      fill={isHover || isSel ? (pal.isLight ? '#ffffff' : pal.chipStrong) : (pal.isLight ? 'rgba(255,255,255,0.92)' : 'rgba(10,12,18,0.88)')}
                      stroke={isPath ? '#ffb300' : isSel || isHover ? (pal.isLight ? '#cbd5e1' : '#fff2f4') : matchQ ? '#f59e0b' : (pal.isLight ? '#e2e8f0' : 'transparent')}
                      strokeWidth="0.8"
                      opacity={isHover || isSel ? 1 : 0.92}
                      filter={isHover || isSel ? 'url(#n-drop-sm)' : undefined}
                    />
                    <text x="10" y="13"
                      fill={isPath ? (pal.isLight ? '#b45309' : '#ffb300') : isSel || isHover ? (pal.isLight ? '#0f172a' : pal.chipText) : matchQ ? (pal.isLight ? '#b45309' : '#ffd60a') : (pal.isLight ? '#1e293b' : pal.chipText)}
                      fontSize={isHover || isSel ? 10 : 9}
                      fontFamily="monospace"
                      fontWeight={isHover || isSel ? 'bold' : 'normal'}>
                      {displayLabel.length > 58 ? `${displayLabel.slice(0, 55)}...` : displayLabel}
                    </text>
                    {n.role_hint && n.role_hint !== 'unknown' && (
                      <text x="10" y="25" fill={pal.isLight ? '#64748b' : pal.chipMuted} fontSize="8" fontFamily="monospace">
                        {n.role_hint} · {n.community || 'unclustered'}
                      </text>
                    )}
                  </g>
                )}

                {/* Custom tag */}
                {tags[n.id] && (
                  <g>
                    <rect x={-r} y={-r - 20} rx={3}
                      width={Math.max(36, tags[n.id].length * 5.8 + 8)} height={14}
                      fill={pal.chipStrong} stroke="#ff4052" strokeWidth="0.8" opacity="0.95" />
                    <text x={-r + 4} y={-r - 9} fontSize="8.5" fill="#ff4052" fontFamily="sans-serif"
                      style={{ pointerEvents: 'none' }}>
                      {tags[n.id]}
                    </text>
                  </g>
                )}
              </g>
            )
          })}
        </g>

        {/* ── Minimap (interactive: click/drag to pan) ── */}
        {minimapData && (
          <g transform={`translate(${svgW - MM_W - 10}, ${svgH - MM_H - 10})`}
            style={{ cursor: 'grab' }}
            onMouseDown={(e) => {
              const target = e.currentTarget as SVGGElement
              const owner = target.ownerSVGElement
              if (!owner) return
              const move = (clientX: number, clientY: number) => {
                const r = owner.getBoundingClientRect()
                const mx = ((clientX - r.left) / r.width) * svgW - (svgW - MM_W - 10)
                const my = ((clientY - r.top) / r.height) * svgH - (svgH - MM_H - 10)
                // minimap point → world point
                const wx = (mx - minimapData.ox) / minimapData.sc
                const wy = (my - minimapData.oy) / minimapData.sc
                // recentre the viewport on the world point
                const vw = svgW / viewRef.current.z
                const vh = svgH / viewRef.current.z
                animateViewTo({ x: wx - vw / 2, y: wy - vh / 2, z: viewRef.current.z })
              }
              move(e.clientX, e.clientY)
              const onMove = (ev: MouseEvent) => move(ev.clientX, ev.clientY)
              const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
              window.addEventListener('mousemove', onMove)
              window.addEventListener('mouseup', onUp)
            }}
          >
            <rect width={MM_W} height={MM_H} rx={6}
              fill={pal.chipStrong} stroke={pal.chipBorder} strokeWidth="1" />
            {minimapData.nodes.filter(n => !hidden.has(n.id)).map(n => {
              const mx = n.x * minimapData.sc + minimapData.ox
              const my = n.y * minimapData.sc + minimapData.oy
              if (mx < 1 || mx > MM_W - 1 || my < 1 || my > MM_H - 1) return null
              return (
                <circle key={n.id} cx={mx} cy={my}
                  r={n.id === graph.seed ? 3 : 1.5}
                  fill={riskColor(n.risk_score)} opacity={0.85} />
              )
            })}
            <rect x={minimapData.vx} y={minimapData.vy}
              width={minimapData.vw} height={minimapData.vh}
              fill="rgba(255,64,82,0.05)" stroke="#ff4052" strokeWidth="0.7" strokeDasharray="3 2" />
            <text x={4} y={MM_H - 4} fill={pal.chipMuted} fontSize="7" fontFamily="monospace">MINIMAP · click to pan</text>
          </g>
        )}

        {/* ── Bottom legend ── */}
        {showLegend && (() => {
          const legendH = 100 + (legendChains.length ? 32 : 0)
          const lift = selectedBundle ? 250 : 0
          return (
            <g transform={`translate(10, ${svgH - legendH - 10 - lift})`} style={{ transition: 'transform 240ms ease' }}>
              <rect width="300" height={legendH} rx={6} fill={pal.chip} stroke={pal.chipBorder} />
              {/* Dismiss */}
              <g transform="translate(286, 12)" style={{ cursor: 'pointer' }} onClick={() => setShowLegend(false)}>
                <circle r={7} fill="none" stroke={pal.chipBorder} />
                <text y={3} textAnchor="middle" fontSize={9} fill={pal.chipMuted}>×</text>
              </g>
              {/* Risk-ring scale */}
              <text x={8} y={14} fill={pal.chipMuted} fontSize="7.5">RISK RING</text>
              {[
                { c: '#ff2d55', l: 'Critical ≥75', x: 8 },
                { c: '#ff9f0a', l: 'High ≥50', x: 78 },
                { c: '#ffd60a', l: 'Medium ≥25', x: 138 },
                { c: '#4ade80', l: 'Low', x: 208 },
              ].map(({ c, l, x }) => (
                <g key={l} transform={`translate(${x}, 30)`}>
                  <circle r={5.5} fill="none" stroke={c} strokeWidth={2}
                    strokeDasharray={`${2 * Math.PI * 5.5 * 0.72} ${2 * Math.PI * 5.5}`} transform="rotate(-90)" strokeLinecap="round" />
                  <text x={10} y={3.5} fill={pal.chipMuted} fontSize="9" fontFamily="sans-serif">{l}</text>
                </g>
              ))}
              <text x={252} y={33} fill={pal.chipMuted} fontSize="7.5">logo = chain</text>
              {/* Edge semantics */}
              <path d="M8 50 Q20 44 32 50" fill="none" stroke={edgeTheme.route.stroke} strokeWidth={1.6} markerEnd="url(#nxe-arrow-route)" />
              <text x={38} y={53} fill={pal.chipMuted} fontSize="9">transaction · chip = total value</text>
              <line x1={8} y1={66} x2={32} y2={66} stroke={edgeTheme.in.stroke} strokeWidth={2.2} markerEnd="url(#nxe-arrow-in)" />
              <text x={38} y={70} fill={edgeTheme.in.chipText} fontSize="9">into focus</text>
              <line x1={112} y1={66} x2={136} y2={66} stroke={edgeTheme.out.stroke} strokeWidth={2.2} markerEnd="url(#nxe-arrow-out)" />
              <text x={142} y={70} fill={edgeTheme.out.chipText} fontSize="9">out of focus</text>
              <line x1={218} y1={66} x2={242} y2={66} stroke={pal.isLight ? '#64748b' : '#94a3b8'} strokeDasharray="5 4" strokeWidth={1.5} />
              <text x={248} y={70} fill={pal.chipMuted} fontSize="9">behavioral link</text>
              {/* Chains present on the canvas */}
              {legendChains.length > 0 && (
                <g transform="translate(8, 92)">
                  <text y={-6} fill={pal.chipMuted} fontSize="7.5">CHAINS ON CANVAS</text>
                  {legendChains.map(([k, b], i) => (
                    <g key={k} transform={`translate(${i * 36 + 9}, 8)`}>
                      <circle r={9} fill={b.fill} stroke={b.stroke} strokeWidth={0.8} />
                      <circle r={9} fill="url(#node-shine)" />
                      <ChainGlyph chain={k} r={6.5} color={b.fill} />
                    </g>
                  ))}
                </g>
              )}
            </g>
          )
        })()}

        {/* ── Stats ── */}
        <g transform="translate(10, 98)">
          <rect width="260" height="18" rx={4} fill={pal.chip} stroke={pal.chipBorder} />
          <text x="8" y="13" fill={pal.chipMuted} fontSize="9" fontFamily="monospace">
            {`${visNodes.length} nodes · ${txEdges.length} flows · ${corrEdges.length} links · ${Math.round(vz * 100)}%`}
            {q ? ` · "${q}"` : ''}
          </text>
        </g>
      </svg>

      {/* ── Context Menu ── */}
      {ctxMenu && (() => {
        const node = graph.nodes.find(n => n.id === ctxMenu.id)
        if (!node) return null
        const isPinned = pinned.has(ctxMenu.id)
        const contextNeighborIds = new Set([
          ctxMenu.id,
          ...graph.edges.flatMap(e => e.source === ctxMenu.id ? [e.target] : e.target === ctxMenu.id ? [e.source] : []),
          ...graph.correlations.flatMap(c => c.source === ctxMenu.id ? [c.target] : c.target === ctxMenu.id ? [c.source] : []),
        ])
        const menuItems = [
    { icon: Copy, label: t('tools:nexusGraph.context.copyAddress'), act: ctxCopy },
    { icon: Shield, label: t('tools:nexusGraph.context.fullIntel'), act: ctxIntel },
    { icon: GitBranch, label: t('tools:nexusGraph.context.expand1hop'), act: () => ctxExpand({ hops: 1, mode: 'wide', direction: 'both' }) },
    { icon: Network, label: t('tools:nexusGraph.context.deepExpand'), act: () => ctxExpand({ hops: 2, mode: 'wide', direction: 'both' }) },
    { icon: Route, label: t('tools:nexusGraph.context.traceIn'), act: () => ctxExpand({ hops: 1, mode: 'wide', direction: 'in' }) },
    { icon: Share2, label: t('tools:nexusGraph.context.traceOut'), act: () => ctxExpand({ hops: 1, mode: 'wide', direction: 'out' }) },
          { icon: ExternalLink, label: 'View on Explorer', act: () => { window.open(`https://etherscan.io/address/${node.address}`, '_blank'); setCtxMenu(null) } },
          {
            icon: Navigation,
            label: selected && selected !== ctxMenu.id ? 'Find path to selected' : 'Set as path start',
            act: selected && selected !== ctxMenu.id ? ctxFindPathToSelected : ctxSetPathSrc,
          },
          { icon: Target, label: 'Open neighborhood subgraph', act: () => openSubgraph(contextNeighborIds, `Neighborhood · ${shortAddr(node.address)}`) },
          ...(pathNodeSet.has(ctxMenu.id) && pathNodeSet.size > 1
            ? [{ icon: GitBranch, label: 'Open marked path subgraph', act: () => openSubgraphSession(subgraphFromPath(graph, pathOrder.length > 1 ? pathOrder : [...pathNodeSet]), 'path', `Path · ${pathOrder.length > 1 ? pathOrder.length - 1 : pathNodeSet.size - 1} hops`) }]
            : []),
          { icon: MapPin, label: isPinned ? '⦿ Unpin node' : '⦿ Pin node', act: ctxPin },
          { icon: Tag, label: 'Tag / Annotate', act: ctxTag },
          { icon: EyeOff, label: 'Hide node', act: ctxHide },
        ]
        // Clamp/flip the menu so it never spills past the viewport edges
        // (e.g. right-clicking a node near the bottom or right of the screen).
        const vw = typeof window !== 'undefined' ? window.innerWidth : 1280
        const vh = typeof window !== 'undefined' ? window.innerHeight : 800
        const estW = 224
        const estH = 56 + menuItems.length * 29
        const menuLeft = Math.max(8, Math.min(ctxMenu.x, vw - estW - 8))
        const menuTop = Math.max(8, Math.min(ctxMenu.y, vh - estH - 8))
        return (
          <div className="fixed z-50 rounded-xl shadow-2xl overflow-y-auto"
            style={{ left: menuLeft, top: menuTop, minWidth: 200, maxHeight: 'calc(100vh - 16px)', background: 'rgb(var(--bg-elevated) / 0.98)', border: '1px solid rgb(var(--bg-border))', backdropFilter: 'blur(12px)' }}
            onMouseLeave={() => setCtxMenu(null)}>
            <div className="px-3 py-2 border-b" style={{ borderColor: 'rgb(var(--bg-border))' }}>
              <p className="text-xs text-text-muted font-mono">{shortAddr(node.address)}</p>
              <p className="text-[10px]" style={{ color: riskColor(node.risk_score) }}>
                Risk {node.risk_score} · {node.role_hint || 'unknown'}
              </p>
            </div>
            {menuItems.map(({ icon: Icon, label, act }) => (
              <button key={label} onClick={act}
                className="flex items-center gap-2.5 w-full px-3 py-1.5 text-xs text-left text-text-secondary hover:text-neon-cyan transition-colors"
                style={{ background: 'transparent' }}
                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,64,82,0.06)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                <Icon size={11} />{label}
              </button>
            ))}
          </div>
        )
      })()}

      {/* ── Tag Input ── */}
      {tagInput && (
        <div className="absolute inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(4px)' }}>
          <div className="rounded-xl p-4 w-72"
            style={{ background: 'rgb(var(--bg-elevated) / 0.98)', border: '1px solid rgb(var(--bg-border))' }}>
            <p className="text-xs text-text-muted mb-1">Annotate: <span className="font-mono text-neon-cyan">{shortAddr(tagInput.id)}</span></p>
            <input autoFocus
              className="w-full text-sm rounded-lg px-3 py-2 text-text-primary mb-3 mt-2"
              style={{ background: 'rgb(var(--bg-secondary))', border: '1px solid rgb(var(--bg-border))', outline: 'none' }}
              value={tagInput.val}
              placeholder="e.g. Exchange deposit, Suspect wallet…"
              onChange={e => setTagInput({ ...tagInput, val: e.target.value })}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  if (tagInput.val.trim()) setTags(t => ({ ...t, [tagInput.id]: tagInput.val.trim() }))
                  else setTags(t => { const n = { ...t }; delete n[tagInput.id]; return n })
                  setTagInput(null)
                } else if (e.key === 'Escape') setTagInput(null)
              }}
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setTagInput(null)}
                className="text-xs px-3 py-1.5 rounded text-text-muted"
                style={{ border: '1px solid rgb(var(--bg-border))' }}>Cancel</button>
              <button
                onClick={() => {
                  if (tagInput.val.trim()) setTags(t => ({ ...t, [tagInput.id]: tagInput.val.trim() }))
                  else setTags(t => { const n = { ...t }; delete n[tagInput.id]; return n })
                  setTagInput(null)
                }}
                className="text-xs px-3 py-1.5 rounded text-neon-cyan"
                style={{ background: 'rgba(255,64,82,0.1)', border: '1px solid rgba(255,64,82,0.3)' }}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Zoom badge ── */}
      <div className="absolute bottom-3 right-[182px] z-10 text-[9px] font-mono text-text-dim rounded px-1.5 py-0.5"
        style={{ background: 'rgb(var(--bg-elevated) / 0.9)', border: '1px solid rgb(var(--bg-border))' }}>
        {Math.round(vz * 100)}%
      </div>

      {showInspector && selectedNode && (
        <div className="absolute top-[108px] right-3 z-20 max-h-[calc(100%-126px)] w-[min(390px,calc(100vw-24px))] overflow-y-auto rounded-xl p-3 space-y-3"
          style={{ background: 'rgb(var(--bg-elevated) / 0.95)', border: '1px solid rgb(var(--bg-border))', backdropFilter: 'blur(12px)' }}>
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-[10px] text-text-muted uppercase tracking-widest">Graph Investigator</p>
              <p className="font-mono text-xs text-text-primary break-all mt-1">{selectedNode.address}</p>
              {selectedNode.arkham_owner?.name && (
                <p className="mt-1 text-xs font-semibold text-neon-cyan">{selectedNode.arkham_owner.name}</p>
              )}
              <p className="mt-1 text-[10px] text-text-muted">
                {selectedTxEdges.length} transaction flows · {selectedCorrEdges.length} behavioral links
              </p>
            </div>
            <div className="flex gap-1">
              <button onClick={() => void navigator.clipboard.writeText(selectedNode.address)} className="rounded border border-border p-1 text-text-muted hover:text-neon-cyan" title="Copy address"><Copy size={12} /></button>
              <button onClick={() => window.open(`https://etherscan.io/address/${selectedNode.address}`, '_blank')} className="rounded border border-border p-1 text-text-muted hover:text-neon-cyan" title="Open explorer"><ExternalLink size={12} /></button>
              <button onClick={() => setShowInspector(false)} className="rounded border border-border p-1 text-text-muted hover:text-neon-cyan" title="Close panel"><X size={12} /></button>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Stat label={t('tools:nexusGraph.detail.risk')} value={selectedNode.risk_score} />
            <Stat label={t('tools:nexusGraph.detail.degree')} value={selectedNode.degree} />
            <Stat label="Cluster" value={selectedNode.community || '-'} />
            <Stat label="Owner" value={selectedNode.arkham_owner?.name || '-'} />
            <Stat label="Role" value={selectedNode.role_hint || '-'} />
            <Stat label="Bridge" value={selectedNode.bridge_score ?? '-'} />
            <Stat label="Volume" value={selectedNode.total_volume ? Math.round(selectedNode.total_volume).toLocaleString() : '-'} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => void requestExpansion(selectedNode.id, { hops: 1, mode: 'wide', direction: 'both' })}
              disabled={expandingNode === selectedNode.id}
              className="inline-flex items-center justify-center gap-1.5 text-xs rounded px-2 py-1.5 text-neon-green disabled:opacity-60"
              style={{ background: 'rgba(0,255,136,0.1)', border: '1px solid rgba(0,255,136,0.35)' }}>
              {expandingNode === selectedNode.id ? <Loader2 size={12} className="animate-spin" /> : <GitBranch size={12} />}
              {expandingNode === selectedNode.id ? 'Expanding...' : 'Expand 1-hop'}
            </button>
            <button
              onClick={() => void requestExpansion(selectedNode.id, { hops: 2, mode: 'wide', direction: 'both' })}
              disabled={expandingNode === selectedNode.id}
              className="inline-flex items-center justify-center gap-1.5 text-xs rounded px-2 py-1.5 text-neon-cyan disabled:opacity-60"
              style={{ background: 'rgba(255,64,82,0.1)', border: '1px solid rgba(255,64,82,0.35)' }}>
              <Network size={12} />
              Deep Expand
            </button>
            <button
              onClick={() => void requestExpansion(selectedNode.id, { hops: 1, mode: 'wide', direction: 'in' })}
              disabled={expandingNode === selectedNode.id}
              className="inline-flex items-center justify-center gap-1.5 text-xs rounded px-2 py-1.5 text-text-secondary hover:text-neon-cyan disabled:opacity-60"
              style={{ background: 'rgb(var(--bg-elevated) / 0.92)', border: '1px solid rgb(var(--bg-border))' }}>
              <Route size={12} />
              Inbound
            </button>
            <button
              onClick={() => void requestExpansion(selectedNode.id, { hops: 1, mode: 'wide', direction: 'out' })}
              disabled={expandingNode === selectedNode.id}
              className="inline-flex items-center justify-center gap-1.5 text-xs rounded px-2 py-1.5 text-text-secondary hover:text-neon-cyan disabled:opacity-60"
              style={{ background: 'rgb(var(--bg-elevated) / 0.92)', border: '1px solid rgb(var(--bg-border))' }}>
              <Share2 size={12} />
              Outbound
            </button>
          </div>
          <button
            onClick={() => openSubgraph(neighborSet, `Neighborhood · ${shortAddr(selectedNode.address)}`)}
            className="inline-flex w-full items-center justify-center gap-1.5 text-xs rounded px-2 py-1.5 text-neon-cyan"
            style={{ background: 'rgba(255,64,82,0.1)', border: '1px solid rgba(255,64,82,0.35)' }}>
            <Target size={12} />
            Open As Subgraph
          </button>
          {lastTraceIds.size > 0 && (
            <button
              onClick={() => openSubgraph(lastTraceIds, `Latest trace expansion · ${lastTraceIds.size} nodes`, undefined, 'trace')}
              className="inline-flex w-full items-center justify-center gap-1.5 text-xs rounded px-2 py-1.5 text-neon-green"
              style={{ background: 'rgba(0,255,136,0.1)', border: '1px solid rgba(0,255,136,0.35)' }}>
              <Network size={12} />
              Open Latest Trace Subgraph
            </button>
          )}
          <div className="flex flex-wrap gap-1">
            {selectedNode.labels.slice(0, 6).map((label, i) => (
              <span key={i} className="text-[9px] px-1.5 py-0.5 rounded border"
                style={{ color: riskColor(selectedNode.risk_score), background: `${riskColor(selectedNode.risk_score)}18`, borderColor: `${riskColor(selectedNode.risk_score)}44` }}>
                {label}
              </span>
            ))}
          </div>
          <div className="rounded-lg border border-border/70 bg-bg-primary/45 p-2.5">
            <p className="mb-2 text-[10px] uppercase tracking-widest text-text-muted">Value Flow</p>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Inbound" value={selectedNode.inbound_volume ? selectedNode.inbound_volume.toFixed(2) : '0'} />
              <Stat label="Outbound" value={selectedNode.outbound_volume ? selectedNode.outbound_volume.toFixed(2) : '0'} />
              <Stat label="Motifs" value={selectedNode.motif_count || 0} />
            </div>
          </div>
          {selectedFeatureEntries.length > 0 && (
            <div className="rounded-lg border border-border/70 bg-bg-primary/45 p-2.5">
              <p className="mb-2 text-[10px] uppercase tracking-widest text-text-muted">Raw Features</p>
              <div className="grid grid-cols-1 gap-1">
                {selectedFeatureEntries.map(([key, value]) => (
                  <div key={key} className="flex items-start justify-between gap-2 rounded border border-border/50 bg-bg-secondary/35 px-2 py-1">
                    <span className="text-[10px] text-text-muted">{key.replace(/_/g, ' ')}</span>
                    <span className="max-w-[190px] break-words text-right font-mono text-[10px] text-text-primary">
                      {typeof value === 'object' ? JSON.stringify(value).slice(0, 90) : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="rounded-lg border border-border/70 bg-bg-primary/45 p-2.5">
            <p className="mb-2 text-[10px] uppercase tracking-widest text-text-muted">Connected Transaction Flows</p>
            <div className="max-h-36 space-y-1 overflow-y-auto pr-1">
              {selectedTxEdges.slice(0, 12).map((edge, i) => {
                const otherId = edge.source === selectedNode.id ? edge.target : edge.source
                const other = graph.nodes.find(n => n.id === otherId)
                return (
                  <button key={`${edge.hash || otherId}-${i}`} className="w-full rounded border border-border/50 bg-bg-secondary/35 px-2 py-1 text-left hover:border-neon-cyan/50"
                    onClick={() => other && onSelect(other.id)}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[10px] text-neon-cyan">{edge.source === selectedNode.id ? 'OUT' : 'IN'} · {shortAddr(other?.address || otherId)}</span>
                      <span className="font-mono text-[10px] text-text-primary">{edge.value ? edge.value.toFixed(2) : '-'} {edge.token || ''}</span>
                    </div>
                    {edge.hash && <p className="mt-0.5 truncate font-mono text-[9px] text-text-dim">{edge.hash}</p>}
                  </button>
                )
              })}
              {selectedTxEdges.length === 0 && <p className="text-xs text-text-muted">No transaction edges attached to this node.</p>}
            </div>
          </div>
          <div className="rounded-lg border border-border/70 bg-bg-primary/45 p-2.5">
            <p className="mb-2 text-[10px] uppercase tracking-widest text-text-muted">Behavioral Correlations</p>
            <div className="max-h-36 space-y-1 overflow-y-auto pr-1">
              {selectedCorrEdges.slice(0, 10).map((corr, i) => {
                const otherId = corr.source === selectedNode.id ? corr.target : corr.source
                const other = graph.nodes.find(n => n.id === otherId)
                return (
                  <button key={`${corr.source}-${corr.target}-${i}`} className="w-full rounded border border-border/50 bg-bg-secondary/35 px-2 py-1 text-left hover:border-neon-cyan/50"
                    onClick={() => other && onSelect(other.id)}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[10px] text-neon-cyan">{shortAddr(other?.address || otherId)}</span>
                      <span className="font-mono text-[10px] text-text-primary">{pct(corr.score)}</span>
                    </div>
                    <p className="mt-0.5 text-[9px] text-text-muted">{corr.type || 'correlation'} · {corr.evidence?.slice(0, 2).join(' · ') || 'behavioral similarity'}</p>
                  </button>
                )
              })}
              {selectedCorrEdges.length === 0 && <p className="text-xs text-text-muted">No behavioral correlations attached to this node.</p>}
            </div>
          </div>
        </div>
      )}

      {/* ── Subgraph / path detail panel (bottom-center, non-overlapping) ── */}
      {((pathSrc && pathDst && pathOrder.length > 1) || (subgraph && subgraphStats)) && (
        <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-20 max-h-[40vh] w-[min(420px,calc(100vw-280px))] overflow-y-auto rounded-xl p-3 space-y-3"
          style={{ background: 'rgb(var(--bg-elevated) / 0.97)', border: '1px solid rgb(var(--bg-border))', backdropFilter: 'blur(14px)', boxShadow: '0 8px 30px rgba(0,0,0,0.2)' }}>
          {subgraph && subgraphStats && (
            <div className="space-y-2">
              <p className="text-[10px] uppercase tracking-widest text-text-muted">Subgraph analysis</p>
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Nodes" value={subgraphStats.nodeCount} />
                <Stat label="Flows" value={subgraphStats.flowCount} />
                <Stat label="Links" value={subgraphStats.linkCount} />
                <Stat label="Risk" value={subgraphStats.maxRisk} />
                <Stat label="Bridges" value={subgraphStats.bridgeCount} />
                <Stat label="Volume" value={Math.round(subgraphStats.volume).toLocaleString()} />
              </div>
              <div className="rounded-lg border border-border/70 bg-bg-primary/45 p-2.5">
                <p className="mb-2 text-[10px] uppercase tracking-widest text-text-muted">Highest-Risk Nodes</p>
                <div className="max-h-32 space-y-1 overflow-y-auto pr-1">
                  {subgraphStats.nodes.slice().sort((a, b) => b.risk_score - a.risk_score).slice(0, 8).map(n => (
                    <button key={n.id} className="flex w-full items-center justify-between gap-2 rounded border border-border/50 bg-bg-secondary/35 px-2 py-1 text-left hover:border-neon-cyan/50"
                      onClick={() => { onSelect(n.id); setShowInspector(true) }}>
                      <span className="min-w-0 truncate font-mono text-[10px] text-neon-cyan">{n.address}</span>
                      <span className="font-mono text-[10px]" style={{ color: riskColor(n.risk_score) }}>{n.risk_score}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
          {pathSrc && pathDst && pathOrder.length > 1 && (
            <div className="space-y-2 border-t border-border/60 pt-3 first:border-t-0 first:pt-0">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] uppercase tracking-widest text-neon-green">Selected Path · {pathOrder.length - 1} hops</p>
              <p className="font-mono text-[10px] text-text-muted mt-0.5">
                {shortAddr(graph.nodes.find(n => n.id === pathSrc)?.address || pathSrc)} → {shortAddr(graph.nodes.find(n => n.id === pathDst)?.address || pathDst)}
              </p>
            </div>
            <button onClick={() => { setPathSrc(null); setPathDst(null); setPathNodeSet(new Set()); setPathEdgeSet(new Set()); setPathOrder([]) }}
              className="text-text-muted hover:text-neon-green" title="Clear path"><X size={13} /></button>
          </div>
          <div className="max-h-[260px] overflow-auto space-y-1 pr-1">
            {pathOrder.map((pid, i) => {
              const pn = graph.nodes.find(n => n.id === pid)
              return (
                <div key={pid} className="flex items-center gap-2 rounded border border-border/60 bg-bg-primary/40 px-2 py-1">
                  <span className="font-mono text-[10px] text-neon-green w-5 shrink-0">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[11px] text-text-primary">{shortAddr(pn?.address || pid)}</p>
                    {pn?.role_hint && pn.role_hint !== 'unknown' && <p className="text-[9px] text-text-muted">{pn.role_hint}{pn.community ? ` · ${pn.community}` : ''}</p>}
                  </div>
                  <span className="font-mono text-[11px] font-bold shrink-0" style={{ color: riskColor(pn?.risk_score || 0) }}>{pn?.risk_score ?? '-'}</span>
                </div>
              )
            })}
          </div>
          <button
            onClick={() => openSubgraphSession(subgraphFromPath(graph, pathOrder), 'path', `Path · ${pathOrder.length - 1} hops`)}
            className="inline-flex w-full items-center justify-center gap-1.5 text-xs rounded px-2 py-1.5 text-neon-green"
            style={{ background: 'rgba(0,255,136,0.1)', border: '1px solid rgba(0,255,136,0.35)' }}>
            <Target size={12} /> Open path as subgraph
          </button>
            </div>
          )}
        </div>
      )}
    </div>
  )

  return fullscreen ? createPortal(graphUI, document.body) : graphUI
}

// ── Node Panel ────────────────────────────────────────────────────────────────
function NodePanel({ node }: { node?: NexusNode }) {
  if (!node) {
    return (
      <div className="border border-border rounded-lg p-4 bg-bg-secondary/50 text-sm text-text-muted">
        <p className="font-medium text-text-secondary mb-1">No node selected</p>
        <p className="text-xs">Click a node to inspect its risk, community, bridge score, and behavioral features.</p>
        <p className="text-xs mt-2 text-text-dim">Right-click any node for investigation options · Double-click to pin</p>
      </div>
    )
  }
  const color = riskColor(node.risk_score)
  return (
    <div className="border border-border rounded-lg p-3 bg-bg-secondary/50 space-y-3">
      <div>
        <p className="text-[10px] text-text-muted uppercase tracking-widest">Selected Wallet</p>
        <p className="font-mono text-xs break-all mt-1" style={{ color }}>{node.address}</p>
        {node.arkham_owner?.name && (
          <p className="mt-1 text-xs font-semibold text-neon-cyan">{node.arkham_owner.name}</p>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Risk" value={node.risk_score} />
        <Stat label="Bridge" value={node.bridge_score.toFixed(1)} />
        <Stat label="Degree" value={node.degree} />
        <Stat label="Motifs" value={node.motif_count} />
      </div>
      <div>
        <p className="text-[10px] text-text-muted uppercase tracking-widest mb-1">Role</p>
        <p className="text-xs text-text-primary">{node.role_hint || '-'}</p>
      </div>
      {node.arkham_owner?.name && (
        <div>
          <p className="text-[10px] text-text-muted uppercase tracking-widest mb-1">Arkham Owner</p>
          <p className="text-xs text-text-primary">{node.arkham_owner.name}</p>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-3 text-xs text-text-secondary space-y-1">
        <p>Inbound: <span className="font-mono text-text-primary">{node.inbound_volume.toFixed(4)}</span></p>
        <p>Outbound: <span className="font-mono text-text-primary">{node.outbound_volume.toFixed(4)}</span></p>
        <p>Total: <span className="font-mono text-text-primary">{node.total_volume.toFixed(4)}</span></p>
        <p>Community: <span className="font-mono text-text-primary">{node.community || '-'}</span></p>
      </div>
      {node.labels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {node.labels.map((l, i) => (
            <span key={i} className="text-[9px] px-1.5 py-0.5 rounded border"
              style={{ color, background: `${color}18`, borderColor: `${color}44` }}>{l}</span>
          ))}
        </div>
      )}
    </div>
  )
}

function DetailAddress({
  address,
  onSelect,
}: {
  address: string
  onSelect: (id: string) => void
}) {
  return (
    <div className="flex min-w-0 items-start gap-2">
      <button
        className="min-w-0 flex-1 text-left font-mono text-xs text-neon-cyan break-all hover:text-white"
        onClick={() => onSelect(address.toLowerCase())}
        title="Select address on graph"
      >
        {address}
      </button>
      <button
        className="shrink-0 rounded border border-border p-1 text-text-muted hover:text-neon-cyan"
        title="Copy address"
        onClick={() => void navigator.clipboard.writeText(address)}
      >
        <Copy size={12} />
      </button>
      <button
        className="shrink-0 rounded border border-border p-1 text-text-muted hover:text-neon-cyan"
        title="Open on Etherscan"
        onClick={() => window.open(`https://etherscan.io/address/${address}`, '_blank')}
      >
        <ExternalLink size={12} />
      </button>
    </div>
  )
}

function ForensicSeverity({ value }: { value: string }) {
  const color =
    value === 'CRITICAL' ? '#ff3b6b' :
    value === 'HIGH' ? '#ff2d55' :
    value === 'MEDIUM' ? '#ff9f0a' :
    value === 'LOW' ? '#0a84ff' : '#b0929a'
  return <span className="text-[10px] font-bold tracking-widest" style={{ color }}>{value}</span>
}

function NexusDemixWorkbench({
  result,
  loading,
  error,
  selectedNode,
  onRun,
  onSelect,
}: {
  result?: NexusDemixResponse | null
  loading: boolean
  error?: string | null
  selectedNode?: NexusNode
  onRun: (scope: 'graph' | 'selected') => void
  onSelect: (id: string) => void
}) {
  const engines = result?.summary.engines_run || []
  const skipped = Object.entries(result?.skipped || {})
  const edgeCount = result?.summary.overlay_edge_count || 0
  return (
    <div className="card border-neon-orange/25">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="card-title flex items-center gap-2"><GitMerge size={13} /> Nexus Demixing Agent</p>
          <p className="mt-1 max-w-3xl text-xs text-text-muted">
            Runs mixer, Tornado, bridge, chain-swap, and AML demixing over the current Nexus graph, then overlays candidate links on the canvas.
          </p>
          {selectedNode && <p className="mt-2 break-all font-mono text-xs text-text-primary">Selected: {selectedNode.address}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary text-xs" disabled={loading} onClick={() => onRun('graph')}>
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Network size={13} />}
            Run Graph
          </button>
          <button className="btn-primary text-xs" disabled={loading || !selectedNode} onClick={() => onRun('selected')}>
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Target size={13} />}
            Run Selected
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-red-500/40 bg-red-500/5 p-3 text-xs text-red-300">
          {error}
        </div>
      )}

      {result ? (
        <div className="mt-4 grid gap-3 xl:grid-cols-[280px_minmax(0,1fr)]">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Risk" value={result.summary.risk_score} />
            <Stat label="Leads" value={edgeCount} sub="overlay edges" />
            <Stat label="Events" value={result.event_inventory.events} />
            <Stat label="Typologies" value={result.summary.typology_count} />
          </div>
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {engines.map(engine => (
                <span key={engine} className="rounded-full border border-neon-orange/30 bg-neon-orange/10 px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-neon-orange">
                  {engine.replace(/_/g, ' ')}
                </span>
              ))}
              {engines.length === 0 && <span className="text-xs text-text-muted">No engines had enough graph-derived events to run.</span>}
            </div>
            {result.typologies.length > 0 && (
              <div className="grid gap-2 md:grid-cols-2">
                {result.typologies.slice(0, 4).map(t => (
                  <div key={`${t.code}-${t.title}`} className="rounded-lg border border-border bg-bg-secondary/50 p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-xs font-semibold text-text-primary">{t.title}</p>
                      <span className="font-mono text-[10px] text-neon-orange">{t.confidence}%</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[11px] text-text-muted">{t.detail}</p>
                  </div>
                ))}
              </div>
            )}
            {result.overlay.edges.length > 0 && (
              <div className="max-h-44 space-y-2 overflow-y-auto pr-1">
                {result.overlay.edges.slice(0, 8).map((e, i) => (
                  <button key={`${e.source}-${e.target}-${i}`} className="w-full rounded-lg border border-border bg-bg-secondary/50 p-2 text-left hover:border-neon-orange/40"
                    onClick={() => onSelect(e.source.toLowerCase())}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate font-mono text-xs text-neon-cyan">{shortAddr(e.source)} → {shortAddr(e.target)}</p>
                      <span className="font-mono text-[10px] text-neon-orange">{pct(e.confidence)}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[11px] text-text-muted">{e.method} · {e.reason || 'candidate demix link'}</p>
                  </button>
                ))}
              </div>
            )}
            {skipped.length > 0 && (
              <details className="rounded-lg border border-border bg-bg-secondary/40 p-2 text-xs text-text-muted">
                <summary className="cursor-pointer text-text-secondary">Skipped engines</summary>
                <div className="mt-2 space-y-1">
                  {skipped.map(([engine, reason]) => <p key={engine}><span className="font-semibold text-text-primary">{engine}</span>: {reason}</p>)}
                </div>
              </details>
            )}
            <p className="text-[11px] italic text-text-muted">{result.disclaimer}</p>
          </div>
        </div>
      ) : !loading && (
        <div className="mt-4 rounded-lg border border-border bg-bg-secondary/50 p-4 text-sm text-text-muted">
          Build a Nexus graph, then run the Demixing Agent on the whole graph or the selected wallet neighborhood.
        </div>
      )}
    </div>
  )
}

function ForensicWorkbench({
  summary,
  full,
  runId,
  loading,
  error,
  seedAddress,
  selectedNode,
  onRun,
  onSelect,
}: {
  summary?: ForensicAnalysisData | null
  full?: ForensicAnalysisData | null
  runId?: string | null
  loading: boolean
  error?: string | null
  seedAddress: string
  selectedNode?: NexusNode
  onRun: (address: string) => void
  onSelect: (id: string) => void
}) {
  const analysis = full || summary || null
  const target = selectedNode?.address || seedAddress
  return (
    <div className="card border-neon-cyan/20">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="card-title flex items-center gap-2"><Fingerprint size={13} /> Embedded Local Forensics</p>
          <p className="text-xs text-text-muted mt-1">
            Local fingerprints, motifs, taint flow, temporal clusters, labels, and explainable algorithm signals inside Nexus.
          </p>
          <p className="font-mono text-xs text-text-primary break-all mt-2">{target}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary text-xs" disabled={loading} onClick={() => onRun(seedAddress)}>
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Fingerprint size={13} />}
            Run Seed
          </button>
          <button className="btn-primary text-xs" disabled={loading || !selectedNode} onClick={() => selectedNode && onRun(selectedNode.address)}>
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Target size={13} />}
            Run Selected
          </button>
          {runId && (
            <a className="btn-ghost text-xs" href={forensicReportUrl(runId)} target="_blank" rel="noopener noreferrer">
              <FileText size={13} /> Report
            </a>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-red-500/40 bg-red-500/5 p-3 text-xs text-red-300">
          {error}
        </div>
      )}

      {!analysis && !loading && (
        <div className="mt-4 rounded-lg border border-border bg-bg-secondary/50 p-4 text-sm text-text-muted">
          Run local forensics on the seed or selected wallet to generate full local evidence. Nexus threat intelligence will also populate this panel when forensic summary data is available.
        </div>
      )}

      {loading && (
        <div className="mt-4 flex items-center gap-3 rounded-lg border border-border bg-bg-secondary/50 p-4 text-sm text-text-secondary">
          <Loader2 size={18} className="animate-spin text-neon-cyan" />
          Running local forensic algorithms and building evidence graph...
        </div>
      )}

      {analysis && (
        <div className="mt-4 space-y-5">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Stat label="Role" value={analysis.role.role.replace(/_/g, ' ')} sub={pct(analysis.role.confidence)} />
            <Stat label="Nodes" value={analysis.graph_metrics.nodes} sub={`${analysis.graph_metrics.edges} edges`} />
            <Stat label="Motifs" value={analysis.motifs.length} sub={`${analysis.algorithm_signals.length} signals`} />
            <Stat label="Flow" value={pct(analysis.features.flow_through_ratio)} sub={`retains ${pct(analysis.features.retention_ratio)}`} />
            <Stat label="Anomaly" value={analysis.cluster_analysis.anomaly_level} sub={pct(analysis.cluster_analysis.anomaly_score)} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-[1fr_0.9fr] gap-5">
            <div className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <p className="card-title flex items-center gap-2"><BrainCircuit size={13} /> Behavioral Fingerprint</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
                <Stat label="In Degree" value={analysis.features.in_degree} />
                <Stat label="Out Degree" value={analysis.features.out_degree} />
                <Stat label="Roundness" value={pct(analysis.features.roundness_score)} />
                <Stat label="Burstiness" value={pct(analysis.features.burstiness_score)} />
                <Stat label="Token Entropy" value={analysis.features.token_entropy} />
                <Stat label="CP Entropy" value={analysis.features.counterparty_entropy} />
                <Stat label="Total In" value={analysis.features.total_in} />
                <Stat label="Total Out" value={analysis.features.total_out} />
              </div>
              <p className="text-xs text-text-secondary mt-3">{analysis.role.reason}</p>
            </div>

            <div className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <p className="card-title flex items-center gap-2"><ShieldAlert size={13} /> Algorithm Signals</p>
              <div className="space-y-2 mt-3 max-h-[260px] overflow-y-auto pr-1">
                {analysis.algorithm_signals.length === 0 ? (
                  <p className="text-xs text-text-muted">No forensic algorithm signals returned.</p>
                ) : analysis.algorithm_signals.map((sig, i) => (
                  <div key={`${sig.type}-${i}`} className="rounded-lg border border-border bg-bg-primary/40 p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-text-primary">{sig.label}</p>
                      <ForensicSeverity value={sig.severity} />
                    </div>
                    <p className="text-[11px] text-text-muted mt-1">{sig.detail}</p>
                    <p className="text-[10px] text-text-dim mt-1">{sig.type} · weight {sig.weight} · confidence {pct(sig.confidence)}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
            <div className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <p className="card-title flex items-center gap-2"><GitBranch size={13} /> Motif Detection</p>
              <div className="space-y-2 mt-3 max-h-[250px] overflow-y-auto pr-1">
                {analysis.motifs.length === 0 ? (
                  <p className="text-xs text-text-muted">No strong graph motifs detected.</p>
                ) : analysis.motifs.map((m, i) => (
                  <div key={`${m.pattern}-${i}`} className="rounded-lg border border-border bg-bg-primary/40 p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-text-primary">{m.pattern.replace(/_/g, ' ')}</p>
                      <ForensicSeverity value={m.severity} />
                    </div>
                    <p className="text-[11px] text-text-muted mt-1">{m.evidence}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <p className="card-title flex items-center gap-2"><Network size={13} /> Taint Flow</p>
              <div className="space-y-2 mt-3 max-h-[250px] overflow-y-auto pr-1">
                {analysis.taint_flow.exposed_addresses.length === 0 ? (
                  <p className="text-xs text-text-muted">No downstream taint propagation found.</p>
                ) : analysis.taint_flow.exposed_addresses.slice(0, 10).map(item => (
                  <button key={item.address} className="w-full text-left rounded-lg border border-border bg-bg-primary/40 p-2.5 hover:border-neon-cyan/40"
                    onClick={() => onSelect(item.address.toLowerCase())}>
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-mono text-xs text-neon-cyan break-all">{item.address}</p>
                      <span className="font-mono text-xs text-text-primary">{pct(item.taint)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <p className="card-title flex items-center gap-2"><Clock3 size={13} /> Temporal Clusters</p>
              <div className="space-y-2 mt-3 max-h-[250px] overflow-y-auto pr-1">
                {analysis.temporal_correlations.length === 0 ? (
                  <p className="text-xs text-text-muted">No synchronized local activity clusters detected.</p>
                ) : analysis.temporal_correlations.map(cluster => (
                  <div key={cluster.time_bucket} className="rounded-lg border border-border bg-bg-primary/40 p-2.5">
                    <div className="flex justify-between gap-2 text-xs">
                      <span className="font-mono text-text-primary">{cluster.time_bucket}</span>
                      <span className="text-neon-cyan">{cluster.address_count} addresses</span>
                    </div>
                    <p className="text-[10px] text-text-muted mt-1">confidence {pct(cluster.confidence)}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <div className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <p className="card-title flex items-center gap-2"><Database size={13} /> Local Labels</p>
              <div className="space-y-2 mt-3">
                {analysis.local_labels.length === 0 ? (
                  <p className="text-xs text-text-muted">No investigator-owned labels matched this address.</p>
                ) : analysis.local_labels.map(label => (
                  <div key={label.id} className="rounded-lg border border-border bg-bg-primary/40 p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-text-primary">{label.label}</p>
                      <span className="font-mono text-xs text-neon-cyan">{label.risk_weight}/100</span>
                    </div>
                    <p className="text-[11px] text-text-muted mt-1">{label.category || label.source}</p>
                    {label.notes && <p className="text-[11px] text-text-secondary mt-1">{label.notes}</p>}
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <p className="card-title flex items-center gap-2"><Fingerprint size={13} /> Counterparty Role Hints</p>
              <div className="overflow-x-auto mt-3">
                <table className="data-table">
                  <thead><tr><th>Address</th><th>Role</th><th>Confidence</th><th>Flow</th></tr></thead>
                  <tbody>
                    {analysis.counterparty_roles.slice(0, 12).map(cp => (
                      <tr key={cp.address} className="cursor-pointer" onClick={() => onSelect(cp.address.toLowerCase())}>
                        <td className="font-mono min-w-[260px] break-all text-neon-cyan">{cp.address}</td>
                        <td>{cp.role.replace(/_/g, ' ')}</td>
                        <td>{pct(cp.confidence)}</td>
                        <td>{pct(cp.flow_through_ratio)}</td>
                      </tr>
                    ))}
                    {analysis.counterparty_roles.length === 0 && (
                      <tr><td colSpan={4} className="text-text-muted">No counterparty role hints available.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Chain color map for chain badges ─────────────────────────────────────────
const CHAIN_COLORS: Record<string, string> = {
  ETH: '#627EEA', BNB: '#F0B90B', BSC: '#F0B90B', MATIC: '#8247E5', POLYGON: '#8247E5', POL: '#8247E5',
  ARB: '#28A0F0', ARBITRUM: '#28A0F0', OP: '#FF0420', OPTIMISM: '#FF0420',
  AVAX: '#E84142', BASE: '#0052FF', ZKSYNC: '#4E529A', LINEA: '#61DFFF',
  FTM: '#1969FF', FANTOM: '#1969FF', CRO: '#002D74', GNOSIS: '#048848',
  SOL: '#9945FF', TRX: '#FF0013', TRON: '#FF0013',
  // Newer chains
  SUI: '#6FBCF0', APT: '#06F7B7', TIA: '#7B2BF9', SEI: '#9E1F19', INJ: '#00D2FF',
  RUNE: '#23DCC8', KAS: '#70C7BA', KASPA: '#70C7BA', STX: '#5546FF', ICP: '#F15A24',
  XLM: '#14B8A6', ALGO: '#111111', XMR: '#FF6600', MNT: '#7EE787', GLMR: '#FF2E56',
  ZETA: '#8B5CF6', DOT: '#E6007A', ATOM: '#6F7390', ADA: '#0033AD', TON: '#0098EA',
  XRP: '#23292F', LTC: '#345D9D', DOGE: '#C2A633', BCH: '#8DC351', NEAR: '#000000',
}
function chainColor(chain: string) {
  return CHAIN_COLORS[(chain || '').toUpperCase()] || '#dc2626'
}

type IdentityTab = 'portfolio' | 'defi' | 'social' | 'attribution' | 'related' | 'debank'

// ── Identity Lens Workbench - compact trigger + mini-profile card ─────────────
function IdentityLensWorkbench({
  profile,
  loading,
  error,
  seedAddress,
  selectedNode,
  onBuild,
  onViewProfile,
}: {
  profile?: IdentityProfile | null
  loading: boolean
  error?: string | null
  seedAddress: string
  selectedNode?: NexusNode
  onBuild: (address: string) => void
  onViewProfile: () => void
}) {
  const selectedTarget = selectedNode?.address || selectedNode?.id || ''
  const target = selectedTarget || seedAddress
  const safeProfile = profile ? normalizeIdentityProfile(profile, target) : null
  const totalUsd = safeProfile?.aggregate_portfolio?.total_usd || safeProfile?.portfolio.portfolio_usd || 0
  const chains = safeProfile?.aggregate_portfolio?.chains || []
  const activeChains = chains.filter(c => c.portfolio_usd > 0 || c.tx_count > 0 || c.active)
  const ensHandle = safeProfile?.profile?.public_handles?.find(h =>
    h.platform?.toLowerCase() === 'ens' || h.platform?.toLowerCase() === 'ens-reverse'
  )
  const displayName = safeProfile?.profile?.display_name || safeProfile?.likely_entity || ''
  const heroName = ensHandle?.handle || displayName || shortAddr(safeProfile?.address || target)

  return (
    <div className="card">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="card-title flex items-center gap-2"><Fingerprint size={13} /> Identity Lens</p>
          <p className="text-xs text-text-muted mt-1">
            Cross-chain wallet intelligence: ENS/username attribution, multi-chain portfolio, DeFi positions, identity signals, and graph evidence.
          </p>
          <p className="font-mono text-xs text-text-secondary break-all mt-2">{target}</p>
        </div>
        <div className="flex flex-wrap gap-2 shrink-0">
          <button className="btn-secondary text-xs" disabled={loading} onClick={() => onBuild(seedAddress)}>
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Shield size={13} />}
            Profile Seed
          </button>
          <button className="btn-primary text-xs" disabled={loading || !selectedTarget} onClick={() => selectedTarget && onBuild(selectedTarget)}>
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Target size={13} />}
            Profile Selected
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-red-500/40 bg-red-500/5 p-3 text-xs text-red-300">{error}</div>
      )}

      {loading && (
        <div className="mt-4 flex items-center gap-3 rounded-lg border border-border bg-bg-secondary/50 p-4 text-sm text-text-secondary">
          <Loader2 size={18} className="animate-spin text-neon-cyan" />
          Scanning all chains, resolving ENS, gathering identity signals and DeFi positions…
        </div>
      )}

      {!safeProfile && !loading && !error && (
        <div className="mt-4 rounded-lg border border-border bg-bg-secondary/50 p-4 text-sm text-text-muted">
          Profile Seed scans the graph seed address; Profile Selected scans the currently selected node. Results open in a full Prism Intelligence profile.
        </div>
      )}

      {safeProfile && (
        <div className="mt-4 overflow-hidden rounded-xl border border-border">
          <div className="bg-gradient-to-br from-[#07111f] via-[#0d2240] to-[#071928] px-5 py-4">
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-red-400 via-red-400 to-emerald-500 text-xl font-black text-white shadow-lg">
                {heroName.replace(/^0x/, '').slice(0, 2).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-base font-black text-white truncate">{heroName}</p>
                <p className="font-mono text-[11px] text-slate-400 break-all mt-0.5">{safeProfile.address}</p>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  <span className="rounded-full px-2 py-0.5 text-xs font-bold"
                    style={{
                      background: safeProfile.confidence_label === 'HIGH' ? '#10b98125' : safeProfile.confidence_label === 'MEDIUM' ? '#f59e0b25' : '#6b728025',
                      color: safeProfile.confidence_label === 'HIGH' ? '#10b981' : safeProfile.confidence_label === 'MEDIUM' ? '#f59e0b' : '#9ca3af',
                    }}>
                    {safeProfile.confidence_label} {pct(safeProfile.confidence)}
                  </span>
                  {activeChains.length > 0 && (
                    <span className="rounded-full bg-red-500/20 px-2 py-0.5 text-xs font-bold text-red-400">{activeChains.length} chains</span>
                  )}
                  {safeProfile.risk_flags.length > 0 && (
                    <span className="rounded-full bg-red-500/20 px-2 py-0.5 text-xs font-bold text-red-400">{safeProfile.risk_flags.length} risk flags</span>
                  )}
                </div>
              </div>
              <div className="text-right shrink-0">
                <p className="text-xl font-black text-white">{money(totalUsd)}</p>
                <p className="text-[11px] text-slate-400 mt-0.5">Net Worth</p>
              </div>
            </div>
          </div>
          <div className="grid grid-cols-4 divide-x divide-border border-t border-border">
            {([
              ['Protocols', String((safeProfile.protocol_positions || []).length)],
              ['Tokens', String(safeProfile.portfolio.tokens.length)],
              ['Transactions', String(safeProfile.portfolio.tx_count)],
              ['Risk Flags', String(safeProfile.risk_flags.length)],
            ] as [string, string][]).map(([label, value]) => (
              <div key={label} className="bg-bg-secondary/40 px-3 py-2.5 text-center">
                <p className="text-[10px] text-text-muted uppercase tracking-widest">{label}</p>
                <p className={`text-sm font-black mt-0.5 ${label === 'Risk Flags' && Number(value) > 0 ? 'text-red-400' : 'text-text-primary'}`}>{value}</p>
              </div>
            ))}
          </div>
          <div className="border-t border-border bg-bg-secondary/20 px-4 py-3">
            <button
              className="w-full flex items-center justify-center gap-2 rounded-lg border border-neon-cyan/40 bg-neon-cyan/5 py-2.5 text-sm font-bold text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
              onClick={onViewProfile}>
              <ExternalLink size={14} /> View Full Intelligence Profile
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Prism Intelligence Profile Sub-Page ───────────────────────────────────────
function IdentityProfileSubPage({
  profile,
  loading,
  error,
  targetAddress,
  debankData,
  debankLoading,
  debankError,
  onDebankRetry,
  onClose,
  onSelect,
  onRerun,
}: {
  profile?: IdentityProfile | null
  loading: boolean
  error?: string | null
  targetAddress?: string
  debankData?: DeBankProfileData | null
  debankLoading?: boolean
  debankError?: string | null
  onDebankRetry?: () => void
  onClose: () => void
  onSelect: (id: string) => void
  onRerun?: (address: string) => void
}) {
  const [activeTab, setActiveTab] = useState<IdentityTab>('debank')
  const [parseSeconds, setParseSeconds] = useState(0)
  const safeProfile = profile ? normalizeIdentityProfile(profile, profile.address || '') : null

  useEffect(() => {
    if (!debankLoading || debankData) {
      setParseSeconds(0)
      return
    }
    const timer = window.setInterval(() => setParseSeconds(s => s + 1), 1000)
    return () => window.clearInterval(timer)
  }, [debankLoading, debankData])

  const chains = safeProfile?.aggregate_portfolio?.chains || []
  const activeChains = chains.filter(c => c.portfolio_usd > 0 || c.tx_count > 0 || c.active)
  const positions = safeProfile?.protocol_positions || []
  const handles = safeProfile?.profile?.public_handles || []
  const signals = safeProfile?.identity_signals || []
  const hypotheses = safeProfile?.attribution_hypotheses || []
  const relatedWallets = safeProfile?.related_wallets || []

  const ensHandle = handles.find(h => {
    const p = (h.platform || '').toLowerCase()
    return p === 'ens' || p === 'ens-reverse' || p.includes('ens')
  })
  const twitterHandle = handles.find(h => {
    const p = (h.platform || '').toLowerCase()
    return p.includes('twitter') || p === 'x' || p.includes('lens')
  })

  const subjectAddress = safeProfile?.address || debankData?.address || targetAddress || ''
  const displayName = debankData?.display_name || safeProfile?.profile?.display_name || safeProfile?.likely_entity || ''
  const heroName = debankData?.web3_id || ensHandle?.handle || displayName || shortAddr(subjectAddress)
  const secondaryName = displayName && displayName !== heroName ? displayName : ''

  const totalUsd = debankData?.total_usd_value ?? safeProfile?.aggregate_portfolio?.total_usd ?? safeProfile?.portfolio.portfolio_usd ?? 0
  const avatarChars = (heroName || subjectAddress).replace(/^0x/, '').slice(0, 2).toUpperCase() || 'WL'
  const chainCount = debankData ? debankData.chain_balances.filter(c => c.usd_value > 0).length : (safeProfile?.aggregate_portfolio?.chain_count || activeChains.length || (safeProfile ? 1 : 0))
  const allTokens = safeProfile?.portfolio.tokens || []

  const primaryChain = safeProfile ? {
    chain: safeProfile.chain || 'ETH',
    chainid: undefined as number | undefined,
    native_balance: safeProfile.portfolio.native_balance,
    native_unit: safeProfile.portfolio.native_unit,
    portfolio_usd: safeProfile.portfolio.portfolio_usd,
    tx_count: safeProfile.portfolio.tx_count,
    token_count: safeProfile.portfolio.tokens.length,
    first_seen: safeProfile.portfolio.first_seen,
    last_seen: safeProfile.portfolio.last_seen,
    active: true,
    explorer: '',
    source: 'primary',
  } : null
  const displayChains = activeChains.length > 0 ? activeChains : (primaryChain ? [primaryChain] : [])
  const heroChainChips = debankData
    ? debankData.chain_balances
      .filter(c => c.usd_value > 0)
      .sort((a, b) => b.usd_value - a.usd_value)
      .slice(0, 6)
      .map(c => ({ key: c.chain_id, label: c.chain_name || c.chain_id.toUpperCase(), color: chainColor(c.chain_id) }))
    : displayChains.slice(0, 6).map(c => ({ key: `${c.chain}-${c.chainid ?? ''}`, label: c.chain, color: chainColor(c.chain) }))
  const parseProgress = Math.min(94, 9 + parseSeconds * 1.35)
  const parseStage =
    parseSeconds < 5 ? 'Preparing Prism Pulse parser' :
    parseSeconds < 15 ? 'Probing public wallet profile endpoints' :
    parseSeconds < 45 ? 'Rendering profile in isolated browser parser' :
    parseSeconds < 75 ? 'Collecting chains, tokens, DeFi positions, NFTs, and activity' :
    'Normalizing parsed wallet intelligence into the investigation profile'

  return (
    <div className="fixed inset-0 z-[80] flex flex-col overflow-hidden" style={{ background: '#060d14' }}>

      {/* ── Sticky Navbar ──────────────────────────────────────────────────── */}
      <div className="shrink-0 z-20" style={{ borderBottom: '1px solid rgba(255,255,255,0.07)', background: 'rgba(8,14,26,0.97)', backdropFilter: 'blur(16px)' }}>
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-6 py-3.5">
          <button onClick={onClose}
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors"
            style={{ color: '#94a3b8' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
            onMouseLeave={e => (e.currentTarget.style.background = '')}>
            <ArrowLeft size={15} /> Back to Nexus
          </button>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest" style={{ color: '#475569' }}>
            <Fingerprint size={14} className="text-red-400" /> Identity Lens
          </div>
          <button
            onClick={() => subjectAddress && navigator.clipboard?.writeText(subjectAddress)}
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors"
            style={{ color: '#94a3b8' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
            onMouseLeave={e => (e.currentTarget.style.background = '')}>
            <Copy size={14} /> Copy Address
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">

        {/* ── Profile Header ─────────────────────────────────────────────── */}
        <div className="relative overflow-hidden" style={{ background: 'linear-gradient(135deg, #081421 0%, #102544 48%, #06252d 100%)', borderBottom: '1px solid rgba(56,189,248,0.12)' }}>
          <div className="absolute inset-0 opacity-25"
            style={{ backgroundImage: 'linear-gradient(rgba(56,189,248,.12) 1px, transparent 1px), linear-gradient(90deg, rgba(56,189,248,.12) 1px, transparent 1px)', backgroundSize: '48px 48px' }} />
          <div className="absolute inset-0"
            style={{ background: 'linear-gradient(90deg, rgba(8,13,24,0.35), transparent 45%, rgba(6,13,20,0.22))' }} />

          <div className="relative mx-auto max-w-7xl px-6 py-7">
            {loading && (
              <div className="mb-4 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold"
                style={{ color: '#f87171', background: 'rgba(56,189,248,0.08)', border: '1px solid rgba(56,189,248,0.18)' }}>
                <Loader2 size={13} className="animate-spin text-red-400" />
                Auto-parsing Prism Pulse profile
              </div>
            )}

            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-center">
              <div className="flex min-w-0 items-center gap-4">
                <div className="relative shrink-0">
                  <div className="flex h-20 w-20 items-center justify-center rounded-2xl border text-2xl font-black text-white shadow-xl"
                    style={{ borderColor: 'rgba(255,255,255,0.12)', background: 'linear-gradient(135deg, #ff5a6e, #22c55e)' }}>
                    {avatarChars}
                  </div>
                  <div className="absolute -bottom-1 -right-1 rounded-full border-2 border-[#081421] p-1"
                    style={{ background: debankData ? '#22c55e' : '#f59e0b' }}>
                    {debankData ? <Zap size={10} className="text-white" /> : <Loader2 size={10} className="animate-spin text-white" />}
                  </div>
                </div>

                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="min-w-0 truncate text-2xl font-black leading-tight text-white sm:text-3xl">
                      {heroName || (loading ? 'Resolving...' : 'Unknown Wallet')}
                    </h2>
                    <span className="rounded-full px-2.5 py-1 text-[10px] font-black uppercase tracking-widest"
                      style={{ color: debankData ? '#34d399' : '#fbbf24', background: debankData ? 'rgba(52,211,153,0.12)' : 'rgba(251,191,36,0.12)', border: `1px solid ${debankData ? 'rgba(52,211,153,0.24)' : 'rgba(251,191,36,0.24)'}` }}>
                      {debankData ? 'Live Parsed' : 'Parsing'}
                    </span>
                  </div>
                  {secondaryName && <p className="mt-1 truncate text-sm text-slate-400">{secondaryName}</p>}
                  <p className="mt-1 max-w-3xl break-all font-mono text-xs text-slate-500 sm:text-sm">
                    {subjectAddress || (loading || debankLoading ? '-' : '-')}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {heroChainChips.map(c => (
                      <span key={c.key}
                        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold"
                        style={{ background: `${c.color}18`, color: c.color, border: `1px solid ${c.color}40` }}>
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: c.color }} />
                        {c.label}
                      </span>
                    ))}
                    {chainCount > heroChainChips.length && (
                      <span className="rounded-full px-2.5 py-1 text-[11px] font-bold text-slate-300"
                        style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>
                        +{chainCount - heroChainChips.length} more
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="rounded-2xl p-4 lg:text-right" style={{ background: 'rgba(2,8,23,0.28)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <p className="text-[10px] font-bold uppercase tracking-[0.22em]" style={{ color: '#64748b' }}>Total Net Worth</p>
                <p className="mt-1 text-4xl font-black text-white">{money(totalUsd)}</p>
                <div className="mt-3 flex flex-wrap gap-2 lg:justify-end">
                  {ensHandle && (
                    <a href={ensHandle.url || undefined} target="_blank" rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-full bg-red-500/20 px-3 py-1 text-xs font-bold text-red-300 hover:bg-red-500/30 transition-colors">
                      <Database size={11} /> {ensHandle.handle}
                    </a>
                  )}
                  {twitterHandle && (
                    <a href={twitterHandle.url || undefined} target="_blank" rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-full bg-red-500/20 px-3 py-1 text-xs font-bold text-red-300 hover:bg-red-500/30 transition-colors">
                      <MessageCircle size={11} /> {twitterHandle.handle}
                    </a>
                  )}
                  <span className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold"
                    style={{
                      background: safeProfile?.confidence_label === 'HIGH' ? '#10b98118' : '#f59e0b18',
                      color: safeProfile?.confidence_label === 'HIGH' ? '#10b981' : '#f59e0b',
                      border: `1px solid ${safeProfile?.confidence_label === 'HIGH' ? '#10b98140' : '#f59e0b40'}`,
                    }}>
                    <Shield size={11} /> {safeProfile?.confidence_label || 'MEDIUM'} {pct(safeProfile?.confidence)}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Metrics Rail ───────────────────────────────────────────────── */}
        <div className="mx-auto mt-5 max-w-7xl px-6">
          <div className="grid grid-cols-2 gap-2 rounded-2xl p-2 sm:grid-cols-3 lg:grid-cols-6"
            style={{ border: '1px solid rgba(56,189,248,0.12)', background: 'rgba(13,24,42,0.72)' }}>
            {([
              ['Net Worth', debankData ? money(debankData.total_usd_value) : money(totalUsd)],
              ['Chains', String(chainCount)],
              ['Tokens', String(debankData ? debankData.tokens.length : allTokens.length)],
              ['Protocols', String(debankData ? debankData.protocols.length : positions.length)],
              ['NFTs', String(debankData ? debankData.nfts.length : 0)],
              ['Recent TX', String(debankData ? debankData.transactions.length : safeProfile?.portfolio.tx_count || safeProfile?.activity_metrics?.observed_transactions || 0)],
            ] as [string, string][]).map(([label, value], i) => (
              <div key={label} className="rounded-xl px-3 py-3 text-center"
                style={{ background: i === 0 ? 'rgba(56,189,248,0.08)' : 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.05)' }}>
                <p className="text-[10px] uppercase tracking-widest" style={{ color: '#475569' }}>{label}</p>
                <p className="text-xl font-black mt-1 text-white">{value}</p>
              </div>
            ))}
          </div>
        </div>

        {/* ── Error ──────────────────────────────────────────────────────── */}
        {error && (
          <div className="mx-auto mt-4 max-w-7xl px-6">
            <div className="rounded-xl p-4 text-sm" style={{ border: '1px solid rgba(248,113,113,0.3)', background: 'rgba(248,113,113,0.07)', color: '#fca5a5' }}>{error}</div>
          </div>
        )}

        {/* ── Prism Pulse Parser Status ─────────────────────────────────── */}
        {(safeProfile || debankData || debankLoading || loading || debankError) && (
          <div className="mx-auto mt-5 max-w-7xl px-6">
            <div className="rounded-2xl p-4" style={{ border: '1px solid rgba(56,189,248,0.18)', background: 'rgba(13,24,42,0.72)' }}>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: 'rgba(56,189,248,0.12)', border: '1px solid rgba(56,189,248,0.25)' }}>
                    {debankLoading ? <Loader2 size={17} className="animate-spin text-red-300" /> : <Zap size={17} className="text-red-300" />}
                  </div>
                  <div>
                    <p className="text-sm font-black text-white">Prism Pulse Engine</p>
                    <p className="text-xs" style={{ color: '#64748b' }}>
                      {debankLoading ? parseStage : debankData ? 'Parsed wallet intelligence rendered below.' : 'Parser ready for this selected wallet.'}
                    </p>
                  </div>
                </div>
                <div className="min-w-[220px]">
                  <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-widest" style={{ color: '#475569' }}>
                    <span>{debankData ? 'Complete' : debankLoading ? 'Parsing' : 'Idle'}</span>
                    <span>{debankData ? '100%' : debankLoading ? `${Math.round(parseProgress)}%` : '0%'}</span>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full" style={{ background: 'rgba(255,255,255,0.06)' }}>
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{ width: `${debankData ? 100 : debankLoading ? parseProgress : 0}%`, background: 'linear-gradient(90deg, #ff5a6e, #34d399)' }}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Tab Content ────────────────────────────────────────────────── */}
        {(safeProfile || debankData || debankLoading || debankError) && (
          <div className="mx-auto max-w-7xl px-6 py-5 pb-12">

            {/* Identity tab strip */}
            <div className="result-tabs mb-5">
              {([
                { id: 'debank', label: 'Prism Pulse' },
                { id: 'portfolio', label: 'Portfolio' },
                { id: 'defi', label: 'DeFi' },
                { id: 'social', label: 'Social & Handles' },
                { id: 'attribution', label: 'Attribution' },
                { id: 'related', label: 'Related Wallets' },
              ] as { id: IdentityTab; label: string }[])
                .filter(t => t.id === 'debank' || safeProfile)
                .map(({ id, label }) => (
                  <button
                    key={id}
                    type="button"
                    className={activeTab === id ? 'active' : ''}
                    onClick={() => setActiveTab(id)}
                  >
                    {label}
                  </button>
                ))}
            </div>

            {/* PORTFOLIO TAB */}
            {safeProfile && activeTab === 'portfolio' && (
              <div className="space-y-5">
                {/* Chain breakdown */}
                <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                  <div className="mb-4 flex items-center justify-between">
                    <h3 className="text-base font-black text-white">Chain Breakdown</h3>
                    <span className="text-xs" style={{ color: '#475569' }}>{displayChains.length} chains scanned</span>
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {displayChains.map(c => (
                      <a key={`${c.chain}-${c.chainid ?? ''}`}
                        href={c.explorer || undefined} target="_blank" rel="noreferrer"
                        className="group relative overflow-hidden rounded-xl p-4 transition-all"
                        style={{ border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}
                        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = `${chainColor(c.chain)}55`; (e.currentTarget as HTMLElement).style.background = `${chainColor(c.chain)}08` }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255,255,255,0.06)'; (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.02)' }}>
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-2.5">
                            <div className="flex h-9 w-9 items-center justify-center rounded-full text-xs font-black text-white shadow-lg"
                              style={{ background: chainColor(c.chain) }}>
                              {c.chain.slice(0, 3)}
                            </div>
                            <div>
                              <p className="text-sm font-black text-white">{c.chain}</p>
                              {c.source && c.source !== 'primary' && (
                                <p className="text-[10px]" style={{ color: '#475569' }}>{c.source}</p>
                              )}
                            </div>
                          </div>
                          <span className="text-[11px] font-bold" style={{ color: c.active ? '#34d399' : '#4b5563' }}>
                            {c.active ? '● active' : '○ quiet'}
                          </span>
                        </div>
                        <p className="text-lg font-black text-white">{money(c.portfolio_usd)}</p>
                        <p className="mt-1 text-xs" style={{ color: '#64748b' }}>
                          {Number(c.native_balance).toFixed(4)} {c.native_unit} · {c.tx_count} txs · {c.token_count} tokens
                        </p>
                        {(c.first_seen || c.last_seen) && (
                          <p className="mt-1 text-[10px]" style={{ color: '#475569' }}>
                            {c.first_seen ? `First: ${c.first_seen.slice(0, 10)}` : ''}
                            {c.last_seen ? ` · Last: ${c.last_seen.slice(0, 10)}` : ''}
                          </p>
                        )}
                      </a>
                    ))}
                  </div>
                </div>

                {/* Token holdings table */}
                <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                  <h3 className="mb-4 text-base font-black text-white">Token Holdings</h3>
                  {allTokens.length === 0 ? (
                    <div className="py-10 text-center" style={{ color: '#475569' }}>
                      <Database size={32} className="mx-auto mb-3 opacity-30" />
                      <p className="text-sm">No token holdings returned from current data providers.</p>
                      <p className="text-xs mt-1 opacity-70">Open Prism Pulse results for real-time holdings.</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-[11px] uppercase tracking-widest" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', color: '#475569' }}>
                            <th className="pb-2.5 text-left font-bold">Token</th>
                            <th className="pb-2.5 text-right font-bold">Balance</th>
                            <th className="pb-2.5 text-right font-bold">Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {allTokens.map((token, i) => (
                            <tr key={`${token.contract}-${i}`} className="transition-colors"
                              style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}
                              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                              onMouseLeave={e => (e.currentTarget.style.background = '')}>
                              <td className="py-3">
                                <div className="flex items-center gap-2.5">
                                  <div className="flex h-8 w-8 items-center justify-center rounded-full text-xs font-black" style={{ background: 'rgba(255,255,255,0.06)', color: '#94a3b8' }}>
                                    {(token.symbol || '?').slice(0, 2).toUpperCase()}
                                  </div>
                                  <div>
                                    <p className="font-bold text-white">{token.symbol}</p>
                                    <p className="text-[11px]" style={{ color: '#475569' }}>{token.name}</p>
                                  </div>
                                </div>
                              </td>
                              <td className="py-3 text-right font-mono text-sm" style={{ color: '#94a3b8' }}>
                                {token.balance.toLocaleString(undefined, { maximumFractionDigits: 6 })}
                              </td>
                              <td className="py-3 text-right">
                                <span className={`font-bold ${token.usd_value > 0 ? 'text-emerald-400' : ''}`} style={token.usd_value <= 0 ? { color: '#475569' } : {}}>
                                  {token.usd_value > 0 ? money(token.usd_value) : '-'}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* DEFI TAB */}
            {safeProfile && activeTab === 'defi' && (
              <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                <h3 className="mb-4 text-base font-black text-white">DeFi & Protocol Positions</h3>
                {positions.length === 0 ? (
                  <div className="py-12 text-center" style={{ color: '#475569' }}>
                    <Route size={32} className="mx-auto mb-3 opacity-30" />
                    <p className="text-sm">No DeFi protocol positions detected from current providers.</p>
                    <p className="text-xs mt-1 opacity-70">Open Prism Pulse results for real-time DeFi data with full protocol breakdown.</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {positions.map((pos, i) => (
                      <div key={`${pos.name}-${pos.chain}-${i}`}
                        className="rounded-xl p-4 transition-colors"
                        style={{ border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}
                        onMouseEnter={e => (e.currentTarget.style.borderColor = 'rgba(56,189,248,0.3)')}
                        onMouseLeave={e => (e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)')}>
                        <div className="flex items-start gap-3">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white text-xs font-black shadow-lg"
                            style={{ background: chainColor(pos.chain || 'ETH') }}>
                            {(pos.symbol || pos.name).slice(0, 2).toUpperCase()}
                          </div>
                          <div className="min-w-0">
                            <p className="font-bold text-white truncate">{pos.name}</p>
                            <p className="text-xs" style={{ color: '#475569' }}>{pos.type} · {pos.chain}</p>
                          </div>
                        </div>
                        <p className="mt-3 text-lg font-black text-white">
                          {pos.usd_value ? money(pos.usd_value) : `${pos.balance.toLocaleString()} ${pos.symbol}`}
                        </p>
                        {pos.evidence && <p className="mt-1 text-[11px]" style={{ color: '#64748b' }}>{pos.evidence}</p>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* PRISM PULSE RESULTS */}
            {activeTab === 'debank' && (
              <div className="space-y-5">
                {debankLoading && !debankData && (
                  <div className="rounded-2xl p-8" style={{ border: '1px solid rgba(56,189,248,0.14)', background: 'rgba(13,24,42,0.8)' }}>
                    <div className="flex flex-col gap-6 lg:flex-row lg:items-center">
                      <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl" style={{ background: 'rgba(56,189,248,0.12)', border: '1px solid rgba(56,189,248,0.25)' }}>
                        <Loader2 size={34} className="animate-spin text-red-400" />
                      </div>
                      <div className="flex-1">
                        <p className="text-lg font-black text-white">Parsing Prism Pulse profile</p>
                        <p className="mt-1 text-sm" style={{ color: '#94a3b8' }}>{parseStage}</p>
                        <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-2">
                          {[
                            'Resolve wallet profile and Web3 ID',
                            'Capture chain balances and net worth',
                            'Extract token holdings and protocol exposure',
                            'Normalize NFTs, recent activity, and tags',
                          ].map((step, i) => {
                            const done = parseProgress >= (i + 1) * 22
                            return (
                              <div key={step} className="flex items-center gap-2 rounded-xl px-3 py-2" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.05)' }}>
                                {done ? <Shield size={13} className="text-emerald-400" /> : <Loader2 size={13} className="animate-spin text-red-400" />}
                                <span className="text-xs font-semibold" style={{ color: done ? '#cbd5e1' : '#64748b' }}>{step}</span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
                {!debankLoading && !debankData && (
                  <div className="rounded-2xl p-10 text-center" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                    <Zap size={36} className="mx-auto mb-3 opacity-30" style={{ color: '#ff5a6e' }} />
                    <p className="text-sm text-white font-semibold mb-1">
                      {debankError ? 'Prism Pulse could not return live data' : 'Prism Pulse is ready'}
                    </p>
                    {debankError && (
                      <p className="text-xs mb-4 max-w-md mx-auto px-2 py-2 rounded-lg" style={{ background: 'rgba(248,113,113,0.08)', color: '#fca5a5', border: '1px solid rgba(248,113,113,0.2)' }}>
                        {debankError}
                      </p>
                    )}
                    {!debankError && (
                      <p className="text-xs mb-4" style={{ color: '#475569' }}>
                        Browser scrape runs in the background (~60-90s). Click Retry if it didn't start.
                      </p>
                    )}
                    {onDebankRetry && (
                      <button
                        className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-bold transition-colors"
                        style={{ background: 'rgba(56,189,248,0.12)', color: '#ff5a6e', border: '1px solid rgba(56,189,248,0.3)' }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(56,189,248,0.2)')}
                        onMouseLeave={e => (e.currentTarget.style.background = 'rgba(56,189,248,0.12)')}
                        onClick={onDebankRetry}>
                        <Zap size={13} /> Retry Live Parse
                      </button>
                    )}
                  </div>
                )}
                {debankData && (() => {
                  const dbTokens = debankData.tokens.filter(t => t.usd_value > 0.01).slice(0, 50)
                  const dbChains = debankData.chain_balances.filter(c => c.usd_value > 0).sort((a, b) => b.usd_value - a.usd_value)
                  const dbProtocols = debankData.protocols.sort((a, b) => b.net_usd_value - a.net_usd_value)
                  const dbNfts = debankData.nfts.filter(n => n.usd_value > 0 || n.amount > 0)
                  const dbTxs = debankData.transactions.slice(0, 20)
                  const status = debankData.source_status
                  return (
                    <>
                      {status && (
                        <div className="rounded-2xl p-4" style={{
                          border: status.degraded ? '1px solid rgba(251,191,36,0.25)' : '1px solid rgba(52,211,153,0.22)',
                          background: status.degraded ? 'rgba(251,191,36,0.08)' : 'rgba(52,211,153,0.07)',
                        }}>
                          <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                            <div>
                              <p className="text-sm font-black" style={{ color: status.degraded ? '#fbbf24' : '#34d399' }}>
                                {status.degraded ? 'Live portfolio telemetry unavailable · using local intelligence fallback' : 'Prism Pulse connected'}
                              </p>
                              <p className="mt-1 text-xs" style={{ color: '#94a3b8' }}>{status.message}</p>
                              {status.errors?.length > 0 && (
                                <p className="mt-2 text-[11px] font-mono" style={{ color: '#64748b' }}>
                                  {status.errors.slice(0, 2).join(' · ')}
                                </p>
                              )}
                            </div>
                            {onDebankRetry && status.degraded && (
                              <button
                                className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-bold"
                                style={{ background: 'rgba(251,191,36,0.12)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.25)' }}
                                onClick={onDebankRetry}>
                                <Zap size={12} /> Retry Live Scrape
                              </button>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Social identity header from live wallet telemetry */}
                      {(debankData.display_name || debankData.web3_id || debankData.bio || debankData.follower_count > 0) && (
                        <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(56,189,248,0.2)', background: 'linear-gradient(135deg, rgba(56,189,248,0.06), rgba(52,211,153,0.04))' }}>
                          <div className="flex items-center gap-4">
                            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl text-xl font-black text-white"
                              style={{ background: 'linear-gradient(135deg, #ff5a6e, #34d399)' }}>
                              {(debankData.display_name || debankData.address).replace(/^0x/, '').slice(0, 2).toUpperCase()}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                {debankData.display_name && <p className="text-lg font-black text-white">{debankData.display_name}</p>}
                                {debankData.web3_id && <span className="rounded-full px-2.5 py-0.5 text-xs font-black" style={{ background: 'rgba(56,189,248,0.15)', color: '#ff5a6e' }}>{debankData.web3_id}</span>}
                                {debankData.is_vip && <span className="rounded-full px-2.5 py-0.5 text-xs font-black" style={{ background: 'rgba(251,191,36,0.15)', color: '#fbbf24' }}>VIP</span>}
                                {debankData.is_pro && <span className="rounded-full px-2.5 py-0.5 text-xs font-black" style={{ background: 'rgba(168,85,247,0.15)', color: '#c084fc' }}>PRO</span>}
                              </div>
                              {debankData.bio && <p className="text-sm mt-1" style={{ color: '#94a3b8' }}>{debankData.bio}</p>}
                              {debankData.tags.length > 0 && (
                                <div className="flex flex-wrap gap-1.5 mt-2">
                                  {debankData.tags.map((t, i) => (
                                    <span key={i} className="rounded-full px-2 py-0.5 text-[10px] font-semibold" style={{ background: 'rgba(255,255,255,0.06)', color: '#94a3b8' }}>{t.name}</span>
                                  ))}
                                </div>
                              )}
                            </div>
                            <div className="shrink-0 text-right">
                              {debankData.follower_count > 0 && (
                                <div>
                                  <p className="text-xl font-black text-white">{debankData.follower_count.toLocaleString()}</p>
                                  <p className="text-[11px]" style={{ color: '#475569' }}>Followers</p>
                                </div>
                              )}
                              {debankData.following_count > 0 && (
                                <div className="mt-2">
                                  <p className="text-base font-black text-white">{debankData.following_count.toLocaleString()}</p>
                                  <p className="text-[11px]" style={{ color: '#475569' }}>Following</p>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Net worth + chain breakdown */}
                      <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                        <div className="mb-5 flex items-end justify-between">
                          <h3 className="text-base font-black text-white">Portfolio Breakdown</h3>
                          <div className="text-right">
                            <p className="text-[11px]" style={{ color: '#475569' }}>Signal Total</p>
                            <p className="text-2xl font-black text-white">{money(debankData.total_usd_value)}</p>
                          </div>
                        </div>
                        {dbChains.length === 0 ? (
                          <p className="text-sm" style={{ color: '#475569' }}>No chain balances found from live portfolio telemetry.</p>
                        ) : (
                          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                            {dbChains.map(c => {
                              const pct_ = debankData.total_usd_value > 0 ? (c.usd_value / debankData.total_usd_value) * 100 : 0
                              const color = chainColor(c.chain_id)
                              return (
                                <div key={c.chain_id} className="rounded-xl p-3" style={{ border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}>
                                  <div className="flex items-center gap-2 mb-2">
                                    <div className="h-6 w-6 rounded-full flex items-center justify-center text-[9px] font-black text-white" style={{ background: color }}>
                                      {c.chain_id.slice(0, 3).toUpperCase()}
                                    </div>
                                    <span className="text-xs font-bold text-white truncate">{c.chain_name || c.chain_id}</span>
                                  </div>
                                  <p className="text-sm font-black text-white">{money(c.usd_value)}</p>
                                  <div className="mt-2 h-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
                                    <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(pct_, 100)}%`, background: color }} />
                                  </div>
                                  <p className="mt-1 text-[10px]" style={{ color: '#475569' }}>{pct_.toFixed(1)}%</p>
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>

                      {/* Token holdings */}
                      <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                        <div className="mb-4 flex items-center justify-between">
                          <h3 className="text-base font-black text-white">Live Token Holdings</h3>
                          <span className="text-xs" style={{ color: '#475569' }}>{debankData.tokens.length} tokens total · showing top {dbTokens.length}</span>
                        </div>
                        {dbTokens.length === 0 ? (
                          <p className="text-sm py-6 text-center" style={{ color: '#475569' }}>No significant token holdings found.</p>
                        ) : (
                          <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                              <thead>
                                <tr className="text-[11px] uppercase tracking-widest" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', color: '#475569' }}>
                                  <th className="pb-2.5 text-left font-bold">Token</th>
                                  <th className="pb-2.5 text-left font-bold">Chain</th>
                                  <th className="pb-2.5 text-right font-bold">Amount</th>
                                  <th className="pb-2.5 text-right font-bold">Price</th>
                                  <th className="pb-2.5 text-right font-bold">24h</th>
                                  <th className="pb-2.5 text-right font-bold">Value</th>
                                </tr>
                              </thead>
                              <tbody>
                                {dbTokens.map((t, i) => {
                                  const change = t.price_24h_change || 0
                                  return (
                                    <tr key={`${t.chain}-${t.id}-${i}`} className="transition-colors"
                                      style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}
                                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                                      onMouseLeave={e => (e.currentTarget.style.background = '')}>
                                      <td className="py-3">
                                        <div className="flex items-center gap-2.5">
                                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[10px] font-black text-white"
                                            style={{ background: chainColor(t.chain) }}>
                                            {(t.symbol || '?').slice(0, 2).toUpperCase()}
                                          </div>
                                          <div>
                                            <div className="flex items-center gap-1.5">
                                              <p className="font-bold text-white">{t.symbol || t.name}</p>
                                              {t.is_scam && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(248,113,113,0.15)', color: '#f87171' }}>SCAM</span>}
                                              {t.is_suspicious && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(251,191,36,0.15)', color: '#fbbf24' }}>⚠</span>}
                                            </div>
                                            <p className="text-[10px] truncate max-w-[120px]" style={{ color: '#475569' }}>{t.name}</p>
                                          </div>
                                        </div>
                                      </td>
                                      <td className="py-3">
                                        <span className="rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ background: `${chainColor(t.chain)}20`, color: chainColor(t.chain) }}>
                                          {t.chain.toUpperCase()}
                                        </span>
                                      </td>
                                      <td className="py-3 text-right font-mono text-xs" style={{ color: '#94a3b8' }}>
                                        {t.amount.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                                      </td>
                                      <td className="py-3 text-right font-mono text-xs" style={{ color: '#94a3b8' }}>
                                        {t.price > 0 ? `$${t.price.toLocaleString(undefined, { maximumFractionDigits: 4 })}` : '-'}
                                      </td>
                                      <td className="py-3 text-right font-bold text-xs">
                                        <span style={{ color: change > 0 ? '#34d399' : change < 0 ? '#f87171' : '#64748b' }}>
                                          {change !== 0 ? `${change > 0 ? '+' : ''}${(change * 100).toFixed(2)}%` : '-'}
                                        </span>
                                      </td>
                                      <td className="py-3 text-right font-black" style={{ color: '#34d399' }}>
                                        {money(t.usd_value)}
                                      </td>
                                    </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>

                      {/* DeFi protocols */}
                      {dbProtocols.length > 0 && (
                        <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                          <h3 className="mb-4 text-base font-black text-white">DeFi Protocol Positions</h3>
                          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                            {dbProtocols.map((p, i) => (
                              <a key={`${p.protocol_id}-${i}`} href={p.site_url || undefined} target="_blank" rel="noreferrer"
                                className="rounded-xl p-4 block transition-all"
                                style={{ border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}
                                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'rgba(56,189,248,0.3)' }}
                                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255,255,255,0.06)' }}>
                                <div className="flex items-center gap-3 mb-3">
                                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white text-xs font-black" style={{ background: chainColor(p.chain) }}>
                                    {p.protocol_name.slice(0, 2).toUpperCase()}
                                  </div>
                                  <div className="min-w-0">
                                    <p className="font-bold text-white truncate">{p.protocol_name}</p>
                                    <p className="text-[10px]" style={{ color: '#475569' }}>{p.detail_types.join(', ') || 'DeFi'} · {p.chain.toUpperCase()}</p>
                                  </div>
                                </div>
                                <p className="text-lg font-black" style={{ color: p.net_usd_value >= 0 ? '#34d399' : '#f87171' }}>{money(p.net_usd_value)}</p>
                                {p.debt_usd_value > 0 && (
                                  <div className="mt-2 flex gap-3 text-[11px]">
                                    <span style={{ color: '#34d399' }}>Assets: {money(p.asset_usd_value)}</span>
                                    <span style={{ color: '#f87171' }}>Debt: {money(p.debt_usd_value)}</span>
                                  </div>
                                )}
                                {p.asset_tokens.length > 0 && (
                                  <div className="mt-2 flex flex-wrap gap-1">
                                    {p.asset_tokens.slice(0, 4).map((t, j) => (
                                      <span key={j} className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,255,255,0.06)', color: '#94a3b8' }}>
                                        {t.symbol || t.name}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </a>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* NFTs */}
                      {dbNfts.length > 0 && (
                        <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                          <h3 className="mb-4 text-base font-black text-white">NFT Holdings</h3>
                          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                            {dbNfts.slice(0, 20).map((n, i) => (
                              <div key={`${n.id}-${i}`} className="rounded-xl p-3" style={{ border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}>
                                <div className="flex h-12 w-12 mx-auto items-center justify-center rounded-xl text-sm font-black text-white mb-2"
                                  style={{ background: 'linear-gradient(135deg, #8b5cf6, #ec4899)' }}>
                                  {(n.name || 'NFT').slice(0, 2).toUpperCase()}
                                </div>
                                <p className="text-xs font-bold text-white text-center truncate">{n.name || `#${n.id.slice(-4)}`}</p>
                                <p className="text-[10px] text-center mt-0.5 truncate" style={{ color: '#475569' }}>{n.collection_name}</p>
                                {n.usd_value > 0 && (
                                  <p className="text-xs font-black text-center mt-1 text-emerald-400">{money(n.usd_value)}</p>
                                )}
                              </div>
                            ))}
                          </div>
                          {dbNfts.length > 20 && <p className="text-xs mt-3 text-center" style={{ color: '#475569' }}>+{dbNfts.length - 20} more NFTs not shown</p>}
                        </div>
                      )}

                      {/* Recent transactions */}
                      {dbTxs.length > 0 && (
                        <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                          <h3 className="mb-4 text-base font-black text-white">Recent Transactions</h3>
                          <div className="space-y-2">
                            {dbTxs.map((tx, i) => {
                              const date = tx.time_at ? new Date(tx.time_at * 1000).toLocaleDateString() : '-'
                              const time = tx.time_at ? new Date(tx.time_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
                              return (
                                <div key={`${tx.tx_id}-${i}`} className="flex items-center gap-3 rounded-xl px-3 py-2.5" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[10px] font-black text-white" style={{ background: chainColor(tx.chain) }}>
                                    {tx.chain.slice(0, 3).toUpperCase()}
                                  </div>
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                      <span className="text-xs font-bold text-white capitalize">{tx.category?.replace(/_/g, ' ') || 'transfer'}</span>
                                      {tx.project_id && <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(56,189,248,0.1)', color: '#ff5a6e' }}>{tx.project_id}</span>}
                                    </div>
                                    <p className="font-mono text-[10px] truncate" style={{ color: '#475569' }}>{tx.tx_id}</p>
                                  </div>
                                  <div className="shrink-0 text-right">
                                    <p className="text-xs font-semibold" style={{ color: '#64748b' }}>{date}</p>
                                    {time && <p className="text-[10px]" style={{ color: '#475569' }}>{time}</p>}
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )}
                    </>
                  )
                })()}
              </div>
            )}

            {/* SOCIAL & IDENTITY TAB */}
            {safeProfile && activeTab === 'social' && (
              <div className="space-y-5">
                {/* Public handles */}
                <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                  <h3 className="mb-4 flex items-center gap-2 text-base font-black text-white">
                    <UserRound size={16} /> Public Identity & Handles
                  </h3>
                  {handles.length === 0 ? (
                    <div className="py-10 text-center" style={{ color: '#475569' }}>
                      <UserRound size={32} className="mx-auto mb-3 opacity-30" />
                      <p className="text-sm">No public handles verified from ENS, entity records, or local labels.</p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {handles.map((h, i) => (
                        <a key={`${h.platform}-${i}`}
                          href={h.url || undefined} target="_blank" rel="noreferrer"
                          className="flex items-center gap-3 rounded-xl p-4 transition-all"
                          style={{ border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}
                          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'rgba(56,189,248,0.3)'; (e.currentTarget as HTMLElement).style.background = 'rgba(56,189,248,0.04)' }}
                          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255,255,255,0.06)'; (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.02)' }}>
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-black" style={{ background: 'rgba(255,255,255,0.06)', color: '#94a3b8' }}>
                            {(h.platform || '?').slice(0, 2).toUpperCase()}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="font-black text-white">{h.handle}</p>
                            <p className="text-xs" style={{ color: '#475569' }}>{h.platform} · {h.source}</p>
                          </div>
                          <span className="shrink-0 rounded-full px-2.5 py-1 text-xs font-black" style={{ background: 'rgba(56,189,248,0.1)', color: '#ff5a6e' }}>{pct(h.confidence)}</span>
                        </a>
                      ))}
                    </div>
                  )}
                </div>

                {/* Identity signals */}
                <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                  <h3 className="mb-4 flex items-center gap-2 text-base font-black text-white">
                    <Shield size={16} /> Identity Evidence Signals
                  </h3>
                  {signals.length === 0 ? (
                    <p className="text-sm" style={{ color: '#64748b' }}>No strong public identity signals found for this address.</p>
                  ) : (
                    <div className="space-y-3">
                      {signals.map((sig, i) => (
                        <div key={`${sig.kind}-${i}`} className="rounded-xl p-4" style={{ border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}>
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="font-bold text-white">{sig.title}</p>
                              <p className="text-sm mt-0.5" style={{ color: '#94a3b8' }}>{sig.detail}</p>
                            </div>
                            <span className="shrink-0 rounded-full px-2.5 py-1 text-xs font-black" style={{ background: 'rgba(56,189,248,0.1)', color: '#ff5a6e' }}>{pct(sig.confidence)}</span>
                          </div>
                          <p className="text-[11px] mt-2" style={{ color: '#475569' }}>{sig.kind} · {sig.source}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Aliases */}
                {safeProfile.aliases.length > 0 && (
                  <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                    <h3 className="mb-4 text-base font-black text-white">All Known Aliases</h3>
                    <div className="flex flex-wrap gap-2">
                      {safeProfile.aliases.map(alias => (
                        <span key={alias} className="rounded-full px-3 py-1.5 text-sm font-semibold" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.03)', color: '#94a3b8' }}>
                          {alias}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ATTRIBUTION TAB */}
            {safeProfile && activeTab === 'attribution' && (
              <div className="space-y-5">
                {/* Hypotheses */}
                <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                  <h3 className="mb-4 flex items-center gap-2 text-base font-black text-white">
                    <BrainCircuit size={16} /> Attribution Hypotheses
                  </h3>
                  {hypotheses.length === 0 ? (
                    <p className="text-sm" style={{ color: '#64748b' }}>No attribution hypotheses returned for this address.</p>
                  ) : (
                    <div className="space-y-3">
                      {hypotheses.map((hyp, i) => (
                        <div key={`${hyp.candidate}-${i}`} className="rounded-xl p-4"
                          style={i === 0
                            ? { border: '1px solid rgba(56,189,248,0.3)', background: 'rgba(56,189,248,0.06)' }
                            : { border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}>
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                {i === 0 && (
                                  <span className="rounded-full px-2 py-0.5 text-[10px] font-black text-white uppercase tracking-wide" style={{ background: '#0e7490' }}>Top Match</span>
                                )}
                                <p className="font-black text-white">{hyp.candidate}</p>
                              </div>
                              <p className="text-xs mt-0.5" style={{ color: '#64748b' }}>{hyp.type}</p>
                            </div>
                            <span className="shrink-0 text-lg font-black" style={{ color: i === 0 ? '#ff5a6e' : '#94a3b8' }}>{pct(hyp.confidence)}</span>
                          </div>
                          {hyp.evidence.length > 0 && (
                            <div className="mt-3 space-y-1">
                              {hyp.evidence.slice(0, 4).map((ev, j) => (
                                <p key={j} className="flex items-start gap-1.5 text-xs" style={{ color: '#94a3b8' }}>
                                  <span className="mt-0.5 shrink-0 text-red-400">•</span>{ev}
                                </p>
                              ))}
                            </div>
                          )}
                          {hyp.caveat && <p className="mt-2 text-[11px] italic" style={{ color: '#475569' }}>{hyp.caveat}</p>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Risk flags */}
                {safeProfile.risk_flags.length > 0 && (
                  <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(248,113,113,0.3)', background: 'rgba(248,113,113,0.06)' }}>
                    <h3 className="mb-4 flex items-center gap-2 text-base font-black text-red-400">
                      <AlertTriangle size={16} /> Risk Flags
                    </h3>
                    <div className="space-y-2">
                      {safeProfile.risk_flags.map((flag, i) => (
                        <div key={i} className="flex items-start gap-2 rounded-lg px-3 py-2.5" style={{ background: 'rgba(248,113,113,0.08)' }}>
                          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-red-400" />
                          <p className="text-sm text-red-300">{flag}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Investigator notes */}
                {safeProfile.investigator_notes.length > 0 && (
                  <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(251,191,36,0.25)', background: 'rgba(251,191,36,0.05)' }}>
                    <h3 className="mb-3 flex items-center gap-2 text-base font-black text-amber-400">
                      <AlertTriangle size={16} /> Investigator Notes
                    </h3>
                    <div className="space-y-2">
                      {safeProfile.investigator_notes.map((note, i) => (
                        <p key={i} className="flex items-start gap-1.5 text-sm text-amber-300">
                          <span className="mt-1 shrink-0 text-amber-500">•</span>{note}
                        </p>
                      ))}
                    </div>
                  </div>
                )}

                {/* On-chain activity metrics */}
                <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                  <h3 className="mb-4 text-base font-black text-white">On-chain Activity</h3>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    {([
                      ['Observed Txs', safeProfile.activity.observed_transactions || safeProfile.activity_metrics?.observed_transactions || 0],
                      ['Inbound', safeProfile.activity.in_count],
                      ['Outbound', safeProfile.activity.out_count],
                      ['Graph Nodes', safeProfile.graph_summary.nodes],
                      ['Graph Edges', safeProfile.graph_summary.edges],
                      ['Direct Neighbors', safeProfile.graph_summary.direct_neighbors],
                    ] as [string, number][]).map(([label, value]) => (
                      <div key={label} className="rounded-xl px-4 py-3" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.04)' }}>
                        <p className="text-[10px] uppercase tracking-widest" style={{ color: '#475569' }}>{label}</p>
                        <p className="text-xl font-black text-white mt-0.5">{value}</p>
                      </div>
                    ))}
                  </div>
                  {safeProfile.activity.top_tokens.length > 0 && (
                    <div className="mt-4">
                      <p className="mb-2 text-xs font-bold uppercase tracking-widest" style={{ color: '#475569' }}>Most Active Tokens</p>
                      <div className="flex flex-wrap gap-2">
                        {safeProfile.activity.top_tokens.slice(0, 12).map(t => (
                          <span key={t.token} className="rounded-full px-3 py-1 text-xs font-semibold" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.03)', color: '#94a3b8' }}>
                            {t.token} <span style={{ color: '#475569' }}>×{t.count}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* RELATED WALLETS TAB */}
            {safeProfile && activeTab === 'related' && (
              <div className="rounded-2xl p-5" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-base font-black text-white">Graph-Linked Wallets</h3>
                  <p className="text-xs" style={{ color: '#475569' }}>{relatedWallets.length} wallets found via graph analysis</p>
                </div>
                {relatedWallets.length === 0 ? (
                  <div className="py-12 text-center" style={{ color: '#475569' }}>
                    <Network size={32} className="mx-auto mb-3 opacity-30" />
                    <p className="text-sm">No graph-linked wallets found. Run Nexus Graph analysis first for richer results.</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {relatedWallets.map(wallet => (
                      <div key={wallet.address}
                        className="rounded-xl p-4 transition-colors"
                        style={{ border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}
                        onMouseEnter={e => (e.currentTarget.style.borderColor = 'rgba(56,189,248,0.25)')}
                        onMouseLeave={e => (e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)')}>
                        <div className="flex items-start justify-between gap-3">
                          <p className="min-w-0 break-all font-mono text-xs text-red-400">{wallet.address}</p>
                          <span className="shrink-0 font-black text-white">{pct(wallet.confidence)}</span>
                        </div>
                        <p className="mt-1.5 text-xs" style={{ color: '#64748b' }}>{wallet.relationship} · risk {wallet.risk_score}</p>
                        {wallet.labels.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {wallet.labels.slice(0, 4).map((label, li) => (
                              <span key={li} className="rounded-full px-2 py-0.5 text-[10px] font-semibold" style={{ background: 'rgba(255,255,255,0.06)', color: '#94a3b8' }}>{label}</span>
                            ))}
                          </div>
                        )}
                        <div className="mt-3 flex gap-2">
                          <button
                            className="flex-1 rounded-lg px-3 py-1.5 text-xs font-bold transition-colors"
                            style={{ background: 'rgba(255,255,255,0.06)', color: '#94a3b8' }}
                            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.1)')}
                            onMouseLeave={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.06)')}
                            onClick={() => onSelect(wallet.address)}>
                            View in Graph
                          </button>
                          {onRerun && (
                            <button
                              className="flex-1 rounded-lg px-3 py-1.5 text-xs font-bold transition-colors"
                              style={{ background: 'rgba(56,189,248,0.1)', color: '#ff5a6e' }}
                              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(56,189,248,0.18)')}
                              onMouseLeave={e => (e.currentTarget.style.background = 'rgba(56,189,248,0.1)')}
                              onClick={() => onRerun(wallet.address)}>
                              Profile This
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Loading placeholder when profile not yet loaded */}
        {!safeProfile && loading && (
          <div className="mx-auto mt-6 max-w-7xl px-6">
            <div className="rounded-2xl p-10 text-center" style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(13,24,42,0.8)' }}>
              <Loader2 size={36} className="mx-auto animate-spin text-red-400" />
              <p className="mt-4 text-white font-semibold">Building full wallet intelligence profile…</p>
              <p className="mt-1 text-sm" style={{ color: '#475569' }}>Scanning ENS, resolving handles, aggregating DeFi positions across all chains</p>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}


function SectionDetailModal({
  section,
  graph,
  threat,
  onClose,
  onSelect,
}: {
  section: DetailSection
  graph: NexusGraphResult
  threat?: ThreatIntelResult | null
  onClose: () => void
  onSelect: (id: string) => void
}) {
  const { t } = useTranslation()
  const titleMap: Record<DetailSection, { title: string; icon: IconComponent; count: number }> = {
    ownership: { title: t('tools:nexusGraph.detail.ownership'), icon: GitBranch, count: threat?.ownership_cluster.linked_wallets.length || 0 },
    links: { title: t('tools:nexusGraph.detail.links'), icon: BrainCircuit, count: graph.correlations.length },
    paths: { title: t('tools:nexusGraph.detail.paths'), icon: Route, count: graph.paths_from_seed.length },
    pivots: { title: t('tools:nexusGraph.detail.pivots'), icon: Target, count: graph.pivot_queue.length },
    bridges: { title: t('tools:nexusGraph.detail.bridges'), icon: Network, count: graph.bridge_wallets.length },
  }
  const meta = titleMap[section]
  const Icon = meta.icon
  const nodeById = new Map(graph.nodes.map(n => [n.id, n]))
  const nodeAddress = (id: string) => nodeById.get(id)?.address || id

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-border bg-bg-primary shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-border p-4">
          <div>
            <p className="card-title flex items-center gap-2"><Icon size={15} /> {meta.title}</p>
            <p className="text-xs text-text-muted mt-1">{meta.count} investigation records · full addresses are selectable and copyable</p>
          </div>
          <button className="rounded border border-border p-2 text-text-muted hover:text-neon-cyan" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="overflow-y-auto p-4">
          {section === 'ownership' && (
            <div className="space-y-3">
              <div className="rounded-lg border border-border bg-bg-secondary/50 p-3">
                <p className="text-xs text-text-secondary">{threat?.ownership_cluster.warning || 'No ownership cluster warning returned.'}</p>
              </div>
              {threat?.ownership_cluster.linked_wallets.map(w => (
                <div key={w.address} className="rounded-lg border border-border bg-bg-secondary/50 p-3">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <DetailAddress address={w.address} onSelect={onSelect} />
                    <span className="badge badge-muted shrink-0">{pct(w.confidence)} confidence</span>
                  </div>
                  <p className="mt-2 text-xs text-text-secondary">{w.role}</p>
                  <div className="mt-2 space-y-1">
                    {w.evidence.map((ev, i) => <p key={i} className="text-[11px] text-text-muted">• {ev}</p>)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {section === 'links' && (
            <div className="space-y-3">
              {graph.correlations.map((c, i) => (
                <div key={`${c.source}-${c.target}-${i}`} className="rounded-lg border border-border bg-bg-secondary/50 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-[10px] uppercase tracking-widest text-text-muted">{c.type || 'behavioral correlation'}</p>
                    <span className="badge badge-muted">{pct(c.score)}</span>
                  </div>
                  <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
                    <DetailAddress address={nodeAddress(c.source)} onSelect={onSelect} />
                    <DetailAddress address={nodeAddress(c.target)} onSelect={onSelect} />
                  </div>
                  <div className="mt-3 space-y-1">
                    {c.evidence.map((ev, evI) => <p key={evI} className="text-[11px] text-text-muted">• {ev}</p>)}
                  </div>
                  {c.path.length > 0 && (
                    <p className="mt-3 font-mono text-[11px] text-text-secondary break-all">
                      Path: {c.path.map(nodeAddress).join(' -> ')}
                    </p>
                  )}
                </div>
              ))}
              {graph.correlations.length === 0 && <p className="text-sm text-text-muted">No high-confidence correlations detected.</p>}
            </div>
          )}

          {section === 'paths' && (
            <div className="space-y-3">
              {graph.paths_from_seed.map(p => (
                <div key={p.target} className="rounded-lg border border-border bg-bg-secondary/50 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <DetailAddress address={nodeAddress(p.target)} onSelect={onSelect} />
                    <span className="badge badge-muted shrink-0">{p.hops} hops</span>
                  </div>
                  <div className="mt-3 space-y-2">
                    {p.path.map((addr, i) => (
                      <div key={`${addr}-${i}`} className="flex items-start gap-2">
                        <span className="mt-0.5 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-text-muted">{i + 1}</span>
                        <DetailAddress address={nodeAddress(addr)} onSelect={onSelect} />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {graph.paths_from_seed.length === 0 && <p className="text-sm text-text-muted">{t('tools:nexusGraph.detail.noPaths')}</p>}
            </div>
          )}

          {(section === 'pivots' || section === 'bridges') && (
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              {(section === 'pivots' ? graph.pivot_queue : graph.bridge_wallets).map(n => (
                <button
                  key={n.id}
                  className="rounded-lg border border-border bg-bg-secondary/50 p-3 text-left hover:border-neon-cyan/40"
                  onClick={() => onSelect(n.id)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-mono text-xs text-neon-cyan break-all">{n.address}</p>
                    <span className="font-mono text-xs shrink-0" style={{ color: riskColor(n.risk_score) }}>{n.risk_score}</span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <Stat label="Bridge" value={n.bridge_score.toFixed(1)} />
                    <Stat label="Volume" value={n.total_volume.toFixed(3)} />
                    <Stat label="Degree" value={n.degree} />
                    <Stat label="Motifs" value={n.motif_count} />
                  </div>
                  <p className="mt-3 text-xs text-text-secondary">{n.role_hint || 'No role hint'}</p>
                  {n.labels.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {n.labels.slice(0, 8).map((label, i) => (
                        <span key={i} className="rounded border px-1.5 py-0.5 text-[9px]"
                          style={{ color: riskColor(n.risk_score), background: `${riskColor(n.risk_score)}18`, borderColor: `${riskColor(n.risk_score)}44` }}>
                          {label}
                        </span>
                      ))}
                    </div>
                  )}
                </button>
              ))}
              {(section === 'bridges' && graph.bridge_wallets.length === 0) && <p className="text-sm text-text-muted">{t('tools:nexusGraph.detail.noBridges')}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── NexusGraph Page ───────────────────────────────────────────────────────────
type PhaseState = 'idle' | 'running' | 'ok' | 'skipped' | 'error'

/** One line of the live run telemetry feed rendered by NexusProgressCinema. */
export type RunLogEntry = {
  id: number
  t: number
  phase: 'intel' | 'trace' | 'nexus' | 'run'
  level: 'info' | 'ok' | 'warn' | 'error'
  text: string
}

export default function NexusGraph() {
  const { t } = useTranslation()
  const { addr } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const isEmbed = location.pathname.startsWith('/nexus-embed')
  const navHops = (location.state as { hops?: number } | null)?.hops
  const [address, setAddress] = useState('')
  const [focus, setFocus] = useState('')
  const [traceChain, setTraceChain] = useState('auto')
  const [traceHops, setTraceHops] = useState(navHops ?? 3)
  const [includeAi, setIncludeAi] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<NexusResponse | null>(null)
  const [graphOverlay, setGraphOverlay] = useState<GraphOverlay>({ nodes: [], edges: [] })
  const [expandingNode, setExpandingNode] = useState<string | null>(null)
  const [forensicAnalysis, setForensicAnalysis] = useState<ForensicAnalysisData | null>(null)
  const [forensicRunId, setForensicRunId] = useState<string | null>(null)
  const [forensicLoading, setForensicLoading] = useState(false)
  const [forensicError, setForensicError] = useState<string | null>(null)
  const [demixResult, setDemixResult] = useState<NexusDemixResponse | null>(null)
  const [demixLoading, setDemixLoading] = useState(false)
  const [demixError, setDemixError] = useState<string | null>(null)
  const [identityProfile, setIdentityProfile] = useState<IdentityProfile | null>(null)
  const [identitySubject, setIdentitySubject] = useState('')
  const [identityLoading, setIdentityLoading] = useState(false)
  const [identityError, setIdentityError] = useState<string | null>(null)
  const [identityViewOpen, setIdentityViewOpen] = useState(false)
  const [debankData, setDebankData] = useState<DeBankProfileData | null>(null)
  const [debankLoading, setDebankLoading] = useState(false)
  const [debankError, setDebankError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [showFullScreenGraph, setShowFullScreenGraph] = useState(false)
  const [detailSection, setDetailSection] = useState<DetailSection | null>(null)
  const [phases, setPhases] = useState<Record<string, PhaseState>>({
    intel: 'idle', trace: 'idle', nexus: 'idle',
  })
  const [phaseMsg, setPhaseMsg] = useState<Record<string, string>>({})
  const [runLog, setRunLog] = useState<RunLogEntry[]>([])
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null)
  const [runFinishedAt, setRunFinishedAt] = useState<number | null>(null)
  /** The cinema plays a completion beat, then collapses into the slim strip. */
  const [cinemaCollapsed, setCinemaCollapsed] = useState(false)
  const logSeq = useRef(0)

  useEffect(() => { if (addr) setAddress(decodeURIComponent(addr)) }, [addr])

  useEffect(() => {
    if (!showFullScreenGraph) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setShowFullScreenGraph(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showFullScreenGraph])

  // Completion beat: hold the finished cinema on screen long enough for the
  // 100 % sweep and the count-up to land, then collapse it to the slim strip
  // so the results view gets the space back.
  useEffect(() => {
    if (running || error || !result || cinemaCollapsed) return
    const h = window.setTimeout(() => setCinemaCollapsed(true), 1800)
    return () => window.clearTimeout(h)
  }, [running, error, result, cinemaCollapsed])

  // Auto-run when addr param is present (navigated from search page)
  // Skip auto-run in embed mode (iframe) - the parent page handles navigation
  useEffect(() => {
    if (isEmbed) return
    if (addr && !result && !running) {
      const target = decodeURIComponent(addr)
      setAddress(target)
      runWithTarget(target, traceHops)
    }
  }, [addr, result, running, traceHops, isEmbed])

  /** Append a timestamped line to the live telemetry feed (capped at 120). */
  function pushLog(phase: RunLogEntry['phase'], level: RunLogEntry['level'], text: string) {
    if (!text) return
    logSeq.current += 1
    const entry: RunLogEntry = { id: logSeq.current, t: Date.now(), phase, level, text }
    setRunLog(l => (l.length >= 120 ? [...l.slice(-119), entry] : [...l, entry]))
  }

  const PHASE_VERB: Record<PhaseState, string> = {
    idle: 'queued', running: 'engaged', ok: 'complete', skipped: 'skipped', error: 'failed',
  }

  function setPhase(id: string, state: PhaseState, msg = '') {
    setPhases(p => ({ ...p, [id]: state }))
    setPhaseMsg(p => ({ ...p, [id]: msg }))
    const level: RunLogEntry['level'] =
      state === 'ok' ? 'ok' : state === 'error' ? 'error' : state === 'skipped' ? 'warn' : 'info'
    const label = id === 'intel' ? 'Address intelligence' : id === 'trace' ? 'Transaction trace' : 'Nexus correlation'
    pushLog(id as RunLogEntry['phase'], level, msg ? `${label} ${PHASE_VERB[state]} — ${msg}` : `${label} ${PHASE_VERB[state]}`)
  }

  function run() {
    const target = address.trim()
    if (!target) return

    // If on search page (no addr param), navigate to results page with hops
    if (!addr) {
      navigate(`/nexus/${encodeURIComponent(target)}`, { 
        replace: true,
        state: { hops: traceHops }
      })
      return
    }

    // On results page, run analysis
    runWithTarget(target, traceHops)
  }

  async function runWithTarget(target: string, hopsOverride?: number) {
    if (!target) return
    setRunning(true)
    setError(null)
    setResult(null)
    setGraphOverlay({ nodes: [], edges: [] })
    setExpandingNode(null)
    setForensicAnalysis(null)
    setForensicRunId(null)
    setForensicError(null)
    setDemixResult(null)
    setDemixError(null)
    setIdentityProfile(null)
    setIdentityError(null)
    setDebankData(null)
    setDebankLoading(false)
    setDebankError(null)
    setSelected(null)
    setDetailSection(null)
    setPhases({ intel: 'idle', trace: 'idle', nexus: 'idle' })
    setPhaseMsg({})
    logSeq.current = 0
    setRunLog([])
    setCinemaCollapsed(false)
    setRunStartedAt(Date.now())
    setRunFinishedAt(null)

    // Resolve the effective chain. "Auto" detects it from the address format so a
    // bc1…/1…/3… (BTC), T… (Tron) or t1…/t3… (Zcash) address routes correctly
    // instead of being forced down the Ethereum-only path.
    const detected = traceChain === 'auto' ? detectChain(target) : traceChain
    const evmChains = ['eth', 'bsc', 'polygon', 'arbitrum', 'optimism', 'base', 'gnosis', 'avax']

    pushLog('run', 'info', `Investigation opened on ${target}`)
    pushLog('run', 'info', traceChain === 'auto'
      ? `Chain auto-detected from address format → ${detected.toUpperCase()}`
      : `Chain locked by operator → ${detected.toUpperCase()}`)
    pushLog('run', 'info', `Trace depth ${Math.max(1, Math.min(8, hopsOverride ?? traceHops ?? 3))} hop(s) · AI synthesis ${includeAi ? 'enabled' : 'disabled'}${focus.trim() ? ` · focus: ${focus.trim().slice(0, 60)}` : ''}`)

    try {
      // ── Phase 1: Address Intelligence ──────────────────────────────────────
      setPhase('intel', 'running', traceChain === 'auto' ? `detected ${detected.toUpperCase()} from address format` : undefined)
      let intel: unknown
      try {
        pushLog('intel', 'info', 'Querying address-intel service · identity, labels, risk scoring (90 s budget)')
        intel = await lookupAddress(target, 90_000)
        setPhase('intel', 'ok', traceChain === 'auto' ? `detected ${detected.toUpperCase()}` : undefined)
      } catch (e) {
        const msg = errorMessage(e)
        if (evmChains.includes(detected)) {
          setPhase('intel', 'error', msg)
          setError(`Phase 1 failed - ${msg}`)
          return
        }
        // Non-EVM chain (BTC, Zcash, TRON): address-intel is EVM-only, so skip it
        // and let the multi-chain trace + nexus build carry the investigation.
        setPhase('intel', 'skipped', `address-intel is EVM-only - skipped for ${detected.toUpperCase()}`)
        intel = undefined
      }

      // ── Phase 2: Transaction Trace ─────────────────────────────────────────
      // Hop depth is operator-controlled (no assumed default). When a specific
      // chain is chosen, route through the multi-chain Holistic engine so BTC,
      // Zcash, TRON, and ERC-20/stablecoin (USDT) flows are traced - not just ETH.
      const hops = Math.max(1, Math.min(8, hopsOverride ?? traceHops ?? 3))
      let traceGraph: unknown = null
      const traceErrors: string[] = []

      if (detected !== 'eth') {
        setPhase('trace', 'running', `holistic ${detected.toUpperCase()} ${hops}-hop cross-chain trace`)
        try {
          pushLog('trace', 'info', `Holistic cross-chain engine · ${detected.toUpperCase()} · both directions · ${hops} hop(s)`)
          const h = await holisticTrace({ subject: target, chain: detected, direction: 'both', max_hops: hops })
          const nodeCount = h?.graph?.nodes?.length || 0
          const edgeCount = h?.graph?.edges?.length || 0
          if (nodeCount > 0 || edgeCount > 0) {
            traceGraph = holisticToTraceGraph(h)
            const chains = (h.summary?.chains_touched || []).join(', ') || detected.toUpperCase()
            setPhase('trace', 'ok', `holistic ${detected.toUpperCase()} · ${h.summary?.node_count ?? nodeCount} nodes / ${h.summary?.edge_count ?? edgeCount} edges · chains: ${chains}`)
          } else {
            const detail = (h?.errors || []).slice(-1)[0] || 'no transfers found on chain'
            setPhase('trace', 'skipped', `holistic ${detected.toUpperCase()} returned no flow - ${detail}; graph builds from intel only`)
          }
        } catch (e) {
          const msg = errorMessage(e)
          traceErrors.push(`holistic ${detected}: ${msg}`)
          setPhase('trace', 'skipped', `holistic trace unavailable - ${msg}; graph builds from intel only`)
        }
      } else {
        // Auto → Ethereum-family multi-attempt tracer, honoring the chosen hop depth.
        setPhase('trace', 'running', `wide ${hops}-hop trace · timeout 240 s`)
        const h2 = Math.max(1, hops - 1)
        const traceAttempts = [
          { label: `wide ${hops}-hop both-direction trace`, params: { address: target, hops, mode: 'wide' as const, direction: 'both' as const, timeout: 240_000, timeout_seconds: 240 } },
          { label: `wide ${h2}-hop both-direction fallback`, params: { address: target, hops: h2, mode: 'wide' as const, direction: 'both' as const, timeout: 180_000, timeout_seconds: 180 } },
          { label: `linear ${hops}-hop outbound/inbound fallback`, params: { address: target, hops, mode: 'linear' as const, direction: 'both' as const, timeout: 150_000, timeout_seconds: 150 } },
          { label: 'wide 1-hop emergency fallback', params: { address: target, hops: 1, mode: 'wide' as const, direction: 'both' as const, timeout: 90_000, timeout_seconds: 90 } },
        ]
        try {
          for (const attempt of traceAttempts) {
            setPhase('trace', 'running', `${attempt.label} · timeout ${Math.round((attempt.params.timeout || 0) / 1000)} s`)
            try {
              const tr = await traceAddress(attempt.params)
              traceGraph = tr.graph
              const stats = tr.graph?.stats
              const detail = stats
                ? `${attempt.label} complete · ${stats.nodes} nodes / ${stats.edges} edges`
                : `${attempt.label} complete`
              setPhase('trace', 'ok', detail)
              break
            } catch (e) {
              const msg = errorMessage(e)
              traceErrors.push(`${attempt.label}: ${msg}`)
              pushLog('trace', 'warn', `${attempt.label} failed — ${msg}; escalating to next strategy`)
            }
          }
          if (!traceGraph) {
            setPhase('trace', 'skipped', `all trace attempts failed - graph builds from intel only; ${traceErrors.slice(-1)[0] || 'no provider detail'}`)
          }
        } catch (e) {
          const msg = errorMessage(e)
          setPhase('trace', 'skipped', `trace unavailable - graph builds from intel only; ${msg}`)
        }
      }

      // ── Phase 3: Nexus Graph Analysis ──────────────────────────────────────
      setPhase('nexus', 'running', includeAi ? 'correlating + AI synthesis · may take up to 5 min' : 'correlating behavioural links')
      pushLog('nexus', 'info', `Fusing intel + trace into the nexus graph · max 250 nodes · AI synthesis ${includeAi ? 'on' : 'off'}`)
      const nexus = await analyzeNexusGraph({
        address: target, intel, trace_graph: traceGraph,
        include_ai: includeAi, analyst_focus: focus, max_nodes: 250,
      })
      const ns = nexus?.nexus?.summary
      setPhase('nexus', 'ok', ns
        ? `${ns.node_count} nodes · ${ns.edge_count} edges · ${ns.correlation_count} behavioural links · ${ns.community_count} cluster(s)`
        : '')
      const ti = nexus?.threat_intel
      if (ti) pushLog('nexus', ti.threat_score >= 60 ? 'warn' : 'ok', `Threat profile resolved — ${ti.threat_level} (${ti.threat_score}/100) · ${ti.pivot_leads?.length ?? 0} pivot lead(s)`)
      pushLog('run', 'ok', 'Investigation complete — graph ready')
      setResult(nexus)
      setSelected(nexus.nexus.seed)
    } catch (e) {
      const msg = errorMessage(e)
      setPhase('nexus', 'error', msg)
      pushLog('run', 'error', `Investigation aborted at nexus build — ${msg}`)
      setError(`Phase 3 failed - ${msg}`)
    } finally {
      setRunFinishedAt(Date.now())
      setRunning(false)
    }
  }

  async function expandNode(id: string, opts: ExpandOpts = {}) {
    const baseGraph = result?.nexus ? mergeNexusGraph(result.nexus, graphOverlay) : null
    const node = baseGraph?.nodes.find(n => n.id === id || n.address.toLowerCase() === id.toLowerCase())
    const target = node?.address || id
    if (!target || expandingNode) return []

    setSelected(node?.id || id)
    setExpandingNode(node?.id || id)
    setError(null)
    try {
      const hops = Math.max(1, Math.min(2, opts.hops ?? 1))
      const timeoutSeconds = hops >= 2 ? 180 : 120
      const trace = await traceAddress({
        address: target,
        hops,
        mode: opts.mode ?? 'wide',
        direction: opts.direction ?? 'both',
        timeout: timeoutSeconds * 1000,
        timeout_seconds: timeoutSeconds,
      })
      const overlay = traceGraphToOverlay(trace.graph)
      setGraphOverlay(prev => ({
        nodes: [...prev.nodes, ...overlay.nodes],
        edges: [...prev.edges, ...overlay.edges],
      }))
      const normalized = target.toLowerCase()
      setSelected(overlay.nodes.find(n => n.id === normalized)?.id || node?.id || id)
      return Array.from(new Set([normalized, ...overlay.nodes.map(n => n.id)]))
    } catch (e) {
      const msg = errorMessage(e)
      setError(`Graph expansion failed - ${msg}`)
      return []
    } finally {
      setExpandingNode(null)
    }
  }

  async function runGraphDemix(scope: 'graph' | 'selected') {
    const currentGraph = result?.nexus ? mergeNexusGraph(result.nexus, graphOverlay) : null
    if (!currentGraph || demixLoading) return
    const selectedTarget = scope === 'selected' && selectedNode ? selectedNode.address : ''
    setDemixLoading(true)
    setDemixError(null)
    try {
      const res = await runNexusDemix({
        nexus: currentGraph,
        selected_addresses: selectedTarget ? [selectedTarget] : [],
        run_tornado: true,
        run_mixer: true,
        run_bridge: true,
        run_chain_swap: true,
        run_aml: true,
        max_candidates: 8,
        time_window_seconds: 86_400,
        value_tolerance: 0.025,
      })
      setDemixResult(res)
      const overlay = demixResultToOverlay(res)
      if (overlay.nodes.length || overlay.edges.length) {
        setGraphOverlay(prev => ({
          nodes: [...prev.nodes, ...overlay.nodes],
          edges: [...prev.edges, ...overlay.edges],
        }))
        const first = overlay.nodes[0]
        if (first) setSelected(first.id)
      }
    } catch (e) {
      setDemixError(errorMessage(e))
    } finally {
      setDemixLoading(false)
    }
  }

  function restoreOriginalGraphState() {
    setGraphOverlay({ nodes: [], edges: [] })
    setDemixResult(null)
    setDemixError(null)
    setForensicAnalysis(null)
    setForensicRunId(null)
    setForensicError(null)
    setIdentityProfile(null)
    setIdentityError(null)
    setIdentityViewOpen(false)
    setDebankData(null)
    setDebankLoading(false)
    setDebankError(null)
    setDetailSection(null)
    setExpandingNode(null)
    if (result?.nexus?.seed) setSelected(result.nexus.seed)
  }

  async function runEmbeddedForensics(target: string) {
    const subject = target.trim()
    if (!subject || forensicLoading) return
    setForensicLoading(true)
    setForensicError(null)
    setForensicAnalysis(null)
    setForensicRunId(null)
    try {
      const res = await analyzeForensics({ address: subject, persist: true })
      setForensicAnalysis(res.analysis)
      setForensicRunId(res.run_id)
      setSelected(res.analysis.address.toLowerCase())
    } catch (e) {
      const msg = errorMessage(e)
      setForensicError(msg)
    } finally {
      setForensicLoading(false)
    }
  }

  async function runIdentityProfile(target: string) {
    const subject = target.trim()
    if (!subject || identityLoading) return
    setIdentityLoading(true)
    setIdentityViewOpen(true)
    setIdentitySubject(subject)
    setIdentityError(null)
    setIdentityProfile(null)
    setDebankData(null)
    setDebankLoading(true)
    setDebankError(null)

    // Kick off live profile fetch in parallel.
    fetchDeBankProfile(subject)
      .then(d => setDebankData(d))
      .catch(e => {
        const msg = e?.response?.data?.detail || e?.message || 'Live profile parse failed'
        setDebankError(String(msg))
      })
      .finally(() => setDebankLoading(false))

    try {
      const currentGraph = result?.nexus ? mergeNexusGraph(result.nexus, graphOverlay) : undefined
      const res = await buildIdentityProfile({
        address: subject,
        graph: currentGraph,
        threat: result?.threat_intel,
        include_lookup: true,
      })
      if (!res?.identity_profile) {
        throw new Error('Identity Lens returned no profile payload.')
      }
      const normalized = normalizeIdentityProfile(res.identity_profile, subject)
      setIdentityProfile(normalized)
      setSelected(normalized.address || subject.toLowerCase())
    } catch (e) {
      const msg = errorMessage(e)
      setIdentityError(msg)
    } finally {
      setIdentityLoading(false)
    }
  }

  const graph = useMemo(() => result?.nexus ? mergeNexusGraph(result.nexus, graphOverlay) : undefined, [result, graphOverlay])
  const threat = result?.threat_intel
  const selectedNode = graph?.nodes.find(n => n.id === selected)

  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      {identityViewOpen && (
        <IdentityProfileSubPage
          profile={identityProfile}
          loading={identityLoading}
          error={identityError}
          targetAddress={identitySubject}
          debankData={debankData}
          debankLoading={debankLoading}
          debankError={debankError}
          onDebankRetry={() => {
            const addr = identityProfile?.address || debankData?.address || identitySubject
            if (!addr) return
            setDebankData(null)
            setDebankLoading(true)
            setDebankError(null)
            fetchDeBankProfile(addr)
              .then(d => setDebankData(d))
              .catch(e => setDebankError(e?.response?.data?.detail || e?.message || 'Live profile parse failed'))
              .finally(() => setDebankLoading(false))
          }}
          onClose={() => setIdentityViewOpen(false)}
          onSelect={(id) => {
            setSelected(id.toLowerCase())
            setIdentityViewOpen(false)
          }}
          onRerun={(addr) => {
            setIdentityViewOpen(false)
            runIdentityProfile(addr)
          }}
        />
      )}

      <div className="noscroll-grow space-y-5">
      {/* Launch console — the input screen, centred in the result region so it
          shares the run screen's staging. Hidden once we're on a results URL. */}
      {!addr && (
        <div className="my-auto w-full">
          <NexusLaunchConsole
            address={address}
            onAddressChange={setAddress}
            onSubmit={run}
            detectedChain={address.trim() ? detectChain(address.trim()) : null}
            chain={traceChain}
            onChainChange={setTraceChain}
            hops={traceHops}
            onHopsChange={setTraceHops}
            focus={focus}
            onFocusChange={setFocus}
            includeAi={includeAi}
            onIncludeAiChange={setIncludeAi}
            busy={running}
          />
        </div>
      )}

      {/* ── Cinematic run screen ─────────────────────────────────────────
          Fills and vertically centres the result region while the pipeline is
          in flight, plays a completion beat, then collapses to a slim strip. */}
      {(running || error || graph) && !cinemaCollapsed && (
        <div className="my-auto w-full">
          <NexusProgressCinema
            phases={phases}
            phaseMsg={phaseMsg}
            log={runLog}
            running={running}
            error={error}
            startedAt={runStartedAt}
            finishedAt={runFinishedAt}
            target={address}
            chain={traceChain === 'auto' ? detectChain(address || '') : traceChain}
            hops={traceHops}
            includeAi={includeAi}
            summary={graph ? {
              nodes: graph.summary.node_count,
              edges: graph.summary.edge_count,
              links: graph.summary.correlation_count,
              clusters: graph.summary.community_count,
              highRisk: graph.nodes.filter(n => n.risk_score > 70).length,
              threatLevel: threat?.threat_level,
              threatScore: threat?.threat_score,
            } : null}
            onOpenGraph={() => setShowFullScreenGraph(true)}
          />
        </div>
      )}

      {/* Collapsed run summary — the headline numbers, one line tall. */}
      {graph && !running && cinemaCollapsed && (
        <NexusProgressStrip
          summary={{
            nodes: graph.summary.node_count,
            edges: graph.summary.edge_count,
            links: graph.summary.correlation_count,
            clusters: graph.summary.community_count,
            highRisk: graph.nodes.filter(n => n.risk_score > 70).length,
          }}
          elapsedMs={runStartedAt && runFinishedAt ? runFinishedAt - runStartedAt : 0}
          threatLevel={threat?.threat_level}
          threatScore={threat?.threat_score}
          onOpenGraph={() => setShowFullScreenGraph(true)}
          onExpand={() => setCinemaCollapsed(false)}
        />
      )}

      {graph && !running && cinemaCollapsed && (
        <div className="space-y-5">
          {/* Overview */}
          <div className="card">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <p className="card-title flex items-center gap-2"><Network size={13} /> Nexus Overview</p>
                <p className="font-mono text-sm text-text-primary break-all">{graph.seed}</p>
                <p className="text-xs text-text-muted mt-1">v{graph.version} · Correlations are investigative leads, not ownership proof.</p>
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
              <Stat label="Nodes" value={graph.summary.node_count} />
              <Stat label="Edges" value={graph.summary.edge_count} />
              <Stat label="Links" value={graph.summary.correlation_count} sub="behavioral" />
              <Stat label="Clusters" value={graph.summary.community_count} />
              <Stat label="Threat" value={threat?.threat_level || '-'} sub={threat ? `${threat.threat_score}/100` : undefined} />
              <Stat label="Pivots" value={threat?.pivot_leads.length ?? graph.pivot_queue.length} />
            </div>
          </div>

          {threat && (
            <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-5">
              <div className="card border-neon-red/20">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="card-title flex items-center gap-2"><Shield size={13} /> Threat Intelligence Profile</p>
                    <p className="text-sm text-text-secondary mt-2">{threat.executive.summary}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-display text-xl font-bold" style={{ color: riskColor(threat.threat_score) }}>{threat.threat_level}</p>
                    <p className="text-xs text-text-muted font-mono">{threat.threat_score}/100</p>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
                  <Stat label="Attribution" value={threat.executive.most_likely_attribution.confidence_label} sub={threat.executive.most_likely_attribution.candidate} />
                  <Stat label="Typology" value={threat.executive.top_typology.confidence_label} sub={threat.executive.top_typology.name} />
                  <Stat label="Network Dump" value={threat.network_dump.nodes.length} sub={`${threat.network_dump.edges.length} edges`} />
                </div>
              </div>

              <div className="card">
                <p className="card-title flex items-center gap-2"><Target size={13} /> Highest-Value Threat Pivots</p>
                <div className="space-y-2 mt-3 max-h-[220px] overflow-y-auto pr-1">
                  {threat.pivot_leads.slice(0, 8).map(p => (
                    <button key={p.address} className="w-full text-left border border-border rounded-lg p-2.5 bg-bg-secondary/50 hover:border-neon-cyan/40"
                      onClick={() => setSelected(p.address)}>
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-mono text-xs text-text-primary truncate">{shortAddr(p.address)}</p>
                        <span className="badge badge-muted">{p.priority_score}</span>
                      </div>
                      <p className="text-[11px] text-text-muted mt-1">{p.role_hint} · {p.reasons.slice(0, 2).join('; ') || 'pivot lead'}</p>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          <NexusDemixWorkbench
            result={demixResult}
            loading={demixLoading}
            error={demixError}
            selectedNode={selectedNode}
            onRun={runGraphDemix}
            onSelect={id => setSelected(id)}
          />

          <ForensicWorkbench
            summary={threat?.forensic}
            full={forensicAnalysis}
            runId={forensicRunId}
            loading={forensicLoading}
            error={forensicError}
            seedAddress={graph.seed}
            selectedNode={selectedNode}
            onRun={runEmbeddedForensics}
            onSelect={id => setSelected(id)}
          />

          <IdentityLensWorkbench
            profile={identityProfile}
            loading={identityLoading}
            error={identityError}
            seedAddress={graph.seed}
            selectedNode={selectedNode}
            onBuild={runIdentityProfile}
            onViewProfile={() => setIdentityViewOpen(true)}
          />

          {/* AI Assessment */}
          {result?.ai_assessment && (
            <div className="card border-neon-cyan/25">
              <p className="card-title flex items-center gap-2"><Bot size={13} /> AI Graph Assessment</p>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-3 text-sm">
                {Object.entries(result.ai_assessment).map(([key, value]) => (
                  <div key={key} className="border border-border rounded-lg p-3 bg-bg-secondary/50">
                    <p className="text-[10px] text-text-muted uppercase tracking-widest mb-2">{key.replace(/_/g, ' ')}</p>
                    <p className="text-text-secondary whitespace-pre-wrap text-xs">
                      {Array.isArray(value) ? value.join('\n') : String(value ?? '')}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {threat && (
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
              <div className="card">
                <p className="card-title flex items-center gap-2"><Shield size={13} /> Attribution Hypotheses</p>
                <div className="space-y-2 mt-3">
                  {threat.attribution_hypotheses.slice(0, 6).map((h, i) => (
                    <div key={i} className="border border-border rounded-lg p-2.5 bg-bg-secondary/50">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-semibold text-text-primary truncate">{h.candidate}</p>
                        <span className="badge badge-muted">{h.confidence_label} {pct(h.confidence)}</span>
                      </div>
                      <p className="text-[11px] text-text-muted mt-1">{h.type} · {h.category}</p>
                      <p className="text-[11px] text-text-secondary mt-1">{h.evidence.filter(Boolean).slice(0, 2).join('; ')}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card">
                <p className="card-title flex items-center gap-2"><Zap size={13} /> Laundering Typologies</p>
                <div className="space-y-2 mt-3">
                  {threat.laundering_typologies.slice(0, 6).map((t, i) => (
                    <div key={i} className="border border-border rounded-lg p-2.5 bg-bg-secondary/50">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-semibold text-text-primary truncate">{t.name}</p>
                        <span className="font-mono text-xs" style={{ color: riskColor(t.score * 100) }}>{pct(t.score)}</span>
                      </div>
                      <p className="text-[11px] text-text-muted mt-1">{t.evidence.slice(0, 2).join('; ')}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card">
                <div className="flex items-center justify-between gap-3">
                  <p className="card-title flex items-center gap-2"><GitBranch size={13} /> Ownership Cluster Leads</p>
                  <button className="btn-secondary text-xs" onClick={() => setDetailSection('ownership')}>
                    <ExternalLink size={12} /> {t('tools:nexusGraph.detail.openDetails')}
                  </button>
                </div>
                <p className="text-[11px] text-text-muted mt-2">{threat.ownership_cluster.warning}</p>
                <div className="space-y-2 mt-3 max-h-[250px] overflow-y-auto pr-1">
                  {threat.ownership_cluster.linked_wallets.slice(0, 8).map(w => (
                    <button key={w.address} className="w-full text-left border border-border rounded-lg p-2.5 bg-bg-secondary/50 hover:border-neon-cyan/40"
                      onClick={() => setSelected(w.address.toLowerCase())}>
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-mono text-xs text-text-primary break-all">{w.address}</p>
                        <span className="badge badge-muted">{pct(w.confidence)}</span>
                      </div>
                      <p className="text-[11px] text-text-muted mt-1">{w.role} · {w.evidence.slice(0, 2).join('; ')}</p>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Tables */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <div className="card">
              <div className="flex items-center justify-between gap-3">
                <p className="card-title flex items-center gap-2"><BrainCircuit size={13} /> Strongest Behavioral Links</p>
                <button className="btn-secondary text-xs" onClick={() => setDetailSection('links')}>
                  <ExternalLink size={12} /> {t('tools:nexusGraph.detail.openDetails')}
                </button>
              </div>
              <div className="space-y-2 mt-3">
                {graph.correlations.slice(0, 10).map((c, i) => (
                  <button key={i} className="w-full text-left border border-border rounded-lg p-2.5 bg-bg-secondary/50 hover:border-neon-cyan/40"
                    onClick={() => { setSelected(c.source); setDetailSection('links') }}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-mono text-text-primary break-all">
                        {c.source} → {c.target}
                      </p>
                      <span className="badge badge-muted shrink-0">{pct(c.score)}</span>
                    </div>
                    <p className="text-[11px] text-text-muted mt-1">{c.evidence.slice(0, 2).join('; ') || 'Behavioral similarity'}</p>
                  </button>
                ))}
                {graph.correlations.length === 0 && <p className="text-sm text-text-muted">No high-confidence correlations detected.</p>}
              </div>
            </div>

            <div className="card">
              <div className="flex items-center justify-between gap-3">
                <p className="card-title flex items-center gap-2"><Route size={13} /> Paths From Seed</p>
                <button className="btn-secondary text-xs" onClick={() => setDetailSection('paths')}>
                  <ExternalLink size={12} /> {t('tools:nexusGraph.detail.openDetails')}
                </button>
              </div>
              <div className="space-y-2 mt-3">
                {graph.paths_from_seed.slice(0, 10).map(p => (
                  <button key={p.target} className="w-full text-left border border-border rounded-lg p-2.5 bg-bg-secondary/50 hover:border-neon-cyan/40"
                    onClick={() => { setSelected(p.target); setDetailSection('paths') }}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-mono text-text-primary break-all">{p.target}</p>
                      <span className="badge badge-muted">{p.hops} hops</span>
                    </div>
                    <p className="text-[10px] text-text-muted mt-1 font-mono break-all">
                      {p.path.join(' → ')}
                    </p>
                  </button>
                ))}
                {graph.paths_from_seed.length === 0 && <p className="text-sm text-text-muted">{t('tools:nexusGraph.detail.noPaths')}</p>}
              </div>
            </div>
          </div>

          {/* Exchange Usage · Top Counterparties · Entity Predictions */}
          <CounterpartyAnalytics address={result?.nexus?.seed || address} chain={traceChain} />

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <div className="card">
              <div className="flex items-center justify-between gap-3">
                <p className="card-title flex items-center gap-2"><Target size={13} /> Pivot Queue</p>
                <button className="btn-secondary text-xs" onClick={() => setDetailSection('pivots')}>
                  <ExternalLink size={12} /> {t('tools:nexusGraph.detail.openDetails')}
                </button>
              </div>
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead><tr><th>Risk</th><th>Address</th><th>Role</th><th>Bridge</th><th>Volume</th></tr></thead>
                  <tbody>
                    {graph.pivot_queue.slice(0, 20).map(n => (
                      <tr key={n.id} onClick={() => setSelected(n.id)} className="cursor-pointer">
                        <td className="font-mono" style={{ color: riskColor(n.risk_score) }}>{n.risk_score}</td>
                        <td className="font-mono min-w-[320px] break-all text-neon-cyan">{n.address}</td>
                        <td className="text-text-muted">{n.role_hint}</td>
                        <td className="font-mono">{n.bridge_score.toFixed(1)}</td>
                        <td className="font-mono">{n.total_volume.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card">
              <div className="flex items-center justify-between gap-3">
                <p className="card-title flex items-center gap-2"><Network size={13} /> Bridge Wallets</p>
                <button className="btn-secondary text-xs" onClick={() => setDetailSection('bridges')}>
                  <ExternalLink size={12} /> {t('tools:nexusGraph.detail.openDetails')}
                </button>
              </div>
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead><tr><th>Bridge</th><th>Address</th><th>Community</th><th>Risk</th></tr></thead>
                  <tbody>
                    {graph.bridge_wallets.slice(0, 20).map(n => (
                      <tr key={n.id} onClick={() => setSelected(n.id)} className="cursor-pointer">
                        <td className="font-mono text-neon-cyan">{n.bridge_score.toFixed(1)}</td>
                        <td className="font-mono min-w-[320px] break-all text-neon-cyan">{n.address}</td>
                        <td className="text-text-muted">{n.community || '-'}</td>
                        <td className="font-mono" style={{ color: riskColor(n.risk_score) }}>{n.risk_score}</td>
                      </tr>
                    ))}
                    {graph.bridge_wallets.length === 0 && (
                      <tr><td colSpan={4} className="text-text-muted">{t('tools:nexusGraph.detail.noBridges')}</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* ── Embedded Intelligence Capabilities ── */}
          <NexusIntelPanel
            nodes={graph.nodes}
            edges={graph.edges as NexusEdge[]}
            seedAddress={graph.seed}
          />

          {detailSection && (
            <SectionDetailModal
              section={detailSection}
              graph={graph}
              threat={threat}
              onClose={() => setDetailSection(null)}
              onSelect={id => {
                setSelected(id.toLowerCase())
                setDetailSection(null)
              }}
            />
          )}
        </div>
      )}

      {/* Cinematic Graph Overlay - Centered Modal */}
      {showFullScreenGraph && graph && (
        <div className="igraph-overlay">
          <div className="igraph-overlay-backdrop" onClick={() => setShowFullScreenGraph(false)} />
          <div className="igraph-overlay-modal">
            {/* Rotating border animation */}
            <div className="igraph-overlay-border-spin" />

            {/* Toolbar */}
            <div className="igraph-overlay-toolbar">
              <div className="flex items-center gap-3">
                <div className="igraph-overlay-icon-wrap">
                  <GitBranch size={16} />
                  <div className="igraph-overlay-icon-pulse" />
                </div>
                <div>
                  <p className="igraph-overlay-title">Investigation Graph</p>
                  <p className="igraph-overlay-subtitle">{graph.nodes.length} nodes · {graph.edges.length} edges</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowFullScreenGraph(false)}
                className="igraph-overlay-close"
                title="Close (Esc)"
              >
                <X size={16} />
              </button>
            </div>

            {/* Graph Canvas */}
            <div className="igraph-overlay-body">
              <GraphCanvas
                graph={graph}
                selected={selected}
                onSelect={setSelected}
                onExpandNode={expandNode}
                expandingNode={expandingNode}
                onRestoreOriginal={restoreOriginalGraphState}
              />
            </div>

            {/* Corner decorations */}
            <div className="igraph-overlay-corner igraph-overlay-corner-tl" />
            <div className="igraph-overlay-corner igraph-overlay-corner-tr" />
            <div className="igraph-overlay-corner igraph-overlay-corner-bl" />
            <div className="igraph-overlay-corner igraph-overlay-corner-br" />
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
