import axios from 'axios'
import { AUTH_TOKEN_KEY } from './client'

// Self-contained API module for Boards, prices, OSINT sweep and attribution submissions.
const api = axios.create({ baseURL: '/api', timeout: 180_000, headers: { 'Content-Type': 'application/json' } })

api.interceptors.request.use((config) => {
  const token = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(AUTH_TOKEN_KEY) : null
  if (token) config.headers = { ...config.headers, Authorization: `Bearer ${token}` } as typeof config.headers
  return config
})
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) window.dispatchEvent(new Event('cryptx-auth-expired'))
    return Promise.reject(err)
  },
)

// ── board state types (frontend-owned document) ───────────────────────────────

export type NodeKind =
  | 'address' | 'tx' | 'cluster' | 'note'
  // crimewall entity kinds
  | 'person' | 'org' | 'exchange' | 'ip' | 'email' | 'phone' | 'social' | 'evidence' | 'wallet' | 'event'
export type NodeShape = 'circle' | 'square' | 'diamond'

/** Lead / hypothesis status for crimewall triage. */
export type LeadStatus = 'none' | 'suspect' | 'confirmed' | 'cleared' | 'poi'

/** Relationship types for manual "red string" links. */
export const RELATIONSHIP_KINDS = [
  'controls', 'same_owner', 'kyc_match', 'communicates', 'funds', 'associates',
  'employs', 'registered_to', 'ip_overlap', 'device_match', 'custom',
] as const
export type RelationshipKind = typeof RELATIONSHIP_KINDS[number]

export interface BoardNode {
  id: string
  kind: NodeKind
  /** address / tx hash / cluster name / note text */
  ref: string
  chain: string
  label: string
  caption: string
  note: string
  x: number
  y: number
  color: string
  shape: NodeShape
  /** cluster members (node ids) when kind === 'cluster' */
  members?: string[]
  collapsed?: boolean
  /** cross-chain hop marker */
  crossChain?: boolean
  /** UTXO/EVM tx-split metadata */
  txMeta?: { inputs: Array<{ address: string; value: number }>; outputs: Array<{ address: string; value: number }>; asset: string }
  risk?: number
  vasp?: string | null
  nodeType?: string
  /** crimewall: lead triage status */
  lead?: LeadStatus
  /** crimewall: flagged as priority (pinned corner marker) */
  priority?: boolean
  /** crimewall: entity attributes (free-form key/value shown in inspector) */
  attrs?: Record<string, string>
  /** crimewall: image URL for photo-pin entities */
  imageUrl?: string
}

export interface BoardEdge {
  id: string
  source: string
  target: string
  asset: string
  value: number
  valueUsd?: number | null
  usdBasis?: string
  txHash: string
  ts: number
  kind: string // transfer | bridge | swap | deposit | manual | relationship
  label: string
  crossChain?: boolean
  color?: string
  /** crimewall: relationship type for manual red-string links */
  relationship?: RelationshipKind
  /** crimewall: analyst confidence 0-100 for manual links */
  confidence?: number
  /** curved offset for parallel edges */
  curve?: number
}

/** Crimewall zone — a named, colored region of the canvas (e.g. "Layering", "Cash-out"). */
export interface BoardZone {
  id: string
  name: string
  x: number
  y: number
  w: number
  h: number
  color: string
}

export interface BoardCluster {
  id: string
  name: string
  members: string[]
  collapsed: boolean
  color: string
}

export interface BoardState {
  nodes: BoardNode[]
  edges: BoardEdge[]
  clusters: BoardCluster[]
  /** crimewall zones (optional for backwards compat with older boards) */
  zones?: BoardZone[]
  viewport: { x: number; y: number; z: number }
  preferences: { fiat: boolean; showGlyphs: boolean; labelDensity: string }
}

export const EMPTY_BOARD_STATE: BoardState = {
  nodes: [], edges: [], clusters: [], zones: [],
  viewport: { x: 0, y: 0, z: 1 },
  preferences: { fiat: true, showGlyphs: true, labelDensity: 'normal' },
}

// ── entities ──────────────────────────────────────────────────────────────────

export interface BoardFolder {
  id: string; name: string; case_id: string; created_by: string; created_at: string; board_count?: number
}

export interface BoardPreview {
  nodes: Array<{ x: number; y: number; c: string; k: string }>
  edges: Array<[number, number]>
}

export interface BoardMeta {
  id: string; name: string; description: string; folder_id: string; case_id: string
  state_hash: string; version: number; created_by: string; created_at: string; updated_at: string
  node_count?: number; edge_count?: number; zone_count?: number
  open_comments?: number; active_shares?: number
  preview?: BoardPreview | null
}

export interface Board extends BoardMeta { state: BoardState }

export interface BoardShare {
  token: string; board_id: string; mode: 'public' | 'private'; live: number | boolean
  snapshot_enc?: number; snapshot_hash?: string; created_by: string; created_at: string
  expires_at: string; revoked: number; access_count: number; url_path?: string
  encrypted_at_rest?: boolean
}

export interface BoardComment {
  id: string; board_id: string; author: string; body: string; node_ref: string
  resolved: number; created_at: string
}

export interface SharedBoardPayload {
  name: string; description: string; state: BoardState; state_hash: string
  live: boolean; read_only: boolean; mode: string; updated_at?: string; frozen_at?: string
}

// ── folders ───────────────────────────────────────────────────────────────────

export async function listFolders(caseId = ''): Promise<BoardFolder[]> {
  const { data } = await api.get('/boards/folders', { params: caseId ? { case_id: caseId } : {} })
  return data.folders
}
export async function createFolder(name: string, caseId = ''): Promise<BoardFolder> {
  const { data } = await api.post('/boards/folders', { name, case_id: caseId })
  return data
}
export async function renameFolder(id: string, name: string): Promise<BoardFolder> {
  const { data } = await api.patch(`/boards/folders/${encodeURIComponent(id)}`, { name })
  return data
}
export async function deleteFolder(id: string): Promise<void> {
  await api.delete(`/boards/folders/${encodeURIComponent(id)}`)
}

// ── boards ────────────────────────────────────────────────────────────────────

export async function listBoards(folderId = '', caseId = ''): Promise<BoardMeta[]> {
  const { data } = await api.get('/boards', { params: { folder_id: folderId, case_id: caseId } })
  return data.boards
}
export async function createBoard(name: string, opts: { description?: string; folder_id?: string; case_id?: string; state?: BoardState } = {}): Promise<Board> {
  const { data } = await api.post('/boards', { name, ...opts })
  return data
}
export async function getBoard(id: string): Promise<Board> {
  const { data } = await api.get(`/boards/${encodeURIComponent(id)}`)
  return data
}
export async function updateBoard(id: string, patch: Partial<{ name: string; description: string; folder_id: string; case_id: string; state: BoardState }>): Promise<BoardMeta> {
  const { data } = await api.put(`/boards/${encodeURIComponent(id)}`, patch)
  return data
}
export async function deleteBoard(id: string): Promise<void> {
  await api.delete(`/boards/${encodeURIComponent(id)}`)
}
export async function duplicateBoard(id: string): Promise<Board> {
  const { data } = await api.post(`/boards/${encodeURIComponent(id)}/duplicate`)
  return data
}

// ── shares ────────────────────────────────────────────────────────────────────

export async function createShare(boardId: string, opts: { mode: 'public' | 'private'; password?: string; live?: boolean; expires_hours?: number }): Promise<BoardShare> {
  const { data } = await api.post(`/boards/${encodeURIComponent(boardId)}/share`, {
    mode: opts.mode, password: opts.password || '', live: opts.live !== false, expires_hours: opts.expires_hours || 0,
  })
  return data
}
export async function listShares(boardId: string): Promise<BoardShare[]> {
  const { data } = await api.get(`/boards/${encodeURIComponent(boardId)}/shares`)
  return data.shares
}
export async function revokeShare(token: string): Promise<void> {
  await api.post(`/boards/share/${encodeURIComponent(token)}/revoke`)
}
// public endpoints (no auth)
export async function sharedMeta(token: string): Promise<{ mode: string; live: boolean; needs_password: boolean; revoked: boolean; expired: boolean }> {
  const { data } = await axios.get(`/api/boards/shared/${encodeURIComponent(token)}/meta`)
  return data
}
export async function accessShared(token: string, password = ''): Promise<SharedBoardPayload> {
  const { data } = await axios.post(`/api/boards/shared/${encodeURIComponent(token)}`, { password })
  return data
}

// ── comments ──────────────────────────────────────────────────────────────────

export async function listComments(boardId: string): Promise<BoardComment[]> {
  const { data } = await api.get(`/boards/${encodeURIComponent(boardId)}/comments`)
  return data.comments
}
export async function addComment(boardId: string, body: string, nodeRef = ''): Promise<BoardComment> {
  const { data } = await api.post(`/boards/${encodeURIComponent(boardId)}/comments`, { body, node_ref: nodeRef })
  return data
}
export async function resolveComment(commentId: string, resolved = true): Promise<void> {
  await api.post(`/boards/comments/${encodeURIComponent(commentId)}/resolve`, null, { params: { resolved } })
}
export async function deleteComment(commentId: string): Promise<void> {
  await api.delete(`/boards/comments/${encodeURIComponent(commentId)}`)
}

// ── board ↔ investigation links (bidirectional Nexus bridge) ─────────────────

export interface BoardLink {
  id?: string; link_id?: string; board_id: string; kind: string; ref: string
  ref_chain?: string; label?: string; created_at?: string
  name?: string; case_id?: string; updated_at?: string; open_comments?: number
}

export async function addBoardLink(boardId: string, kind: string, ref: string, refChain = '', label = ''): Promise<BoardLink> {
  const { data } = await api.post(`/boards/${encodeURIComponent(boardId)}/links`, { kind, ref, ref_chain: refChain, label })
  return data
}
export async function boardLinks(boardId: string): Promise<BoardLink[]> {
  const { data } = await api.get(`/boards/${encodeURIComponent(boardId)}/links`)
  return data.links
}
export async function boardsForRef(ref: string, kind = ''): Promise<BoardLink[]> {
  const { data } = await api.get('/board-links', { params: { ref, kind } })
  return data.boards
}
export async function deleteBoardLink(linkId: string): Promise<void> {
  await api.delete(`/board-links/${encodeURIComponent(linkId)}`)
}

// Convert a live Nexus graph (positioned nodes) into a persistent Board document.
const NEXUS_CHAIN_COLORS: Record<string, string> = {
  btc: '#f7931a', eth: '#627eea', tron: '#ff2d55', trx: '#ff2d55', sol: '#9945ff',
  polygon: '#8247e5', matic: '#8247e5', arbitrum: '#28a0f0', optimism: '#ff0420',
  base: '#0052ff', bsc: '#f0b90b', bnb: '#f0b90b', zcash: '#ecb244',
}
function nexusRisk(score: number): string {
  if (score >= 75) return '#ff2d55'
  if (score >= 50) return '#ff9f0a'
  if (score >= 25) return '#ffd60a'
  return '#8e9db5'
}

export interface NexusExportNode {
  id: string; address: string; chain?: string; label?: string
  risk_score?: number; role_hint?: string; vasp?: string | null; x: number; y: number
}
export interface NexusExportEdge {
  source: string; target: string; value?: number; token?: string; hash?: string; time?: string
}

export function nexusToBoardState(nodes: NexusExportNode[], edges: NexusExportEdge[], seed: string, chain = 'eth'): BoardState {
  const idMap = new Map<string, string>()
  const bNodes: BoardNode[] = nodes.map((n) => {
    const bid = `n_${n.id}`
    idMap.set(n.id, bid)
    const c = (n.chain || chain || 'eth').toLowerCase()
    return {
      id: bid, kind: 'address', ref: n.address || n.id, chain: c,
      label: n.label || (n.address || n.id).slice(0, 10),
      caption: n.role_hint && n.role_hint !== 'unknown' ? n.role_hint : (n.id === seed ? 'subject' : ''),
      note: '', x: n.x, y: n.y,
      color: (n.risk_score ?? 0) >= 50 ? nexusRisk(n.risk_score ?? 0) : (NEXUS_CHAIN_COLORS[c] || '#8e9db5'),
      shape: n.id === seed ? 'diamond' : 'circle',
      risk: n.risk_score, vasp: n.vasp ?? null,
    }
  })
  const bEdges: BoardEdge[] = edges.map((e, i) => ({
    id: `e_${i}`, source: idMap.get(e.source) || `n_${e.source}`, target: idMap.get(e.target) || `n_${e.target}`,
    asset: e.token || '', value: e.value || 0, valueUsd: null,
    txHash: e.hash || '', ts: e.time ? Math.floor(new Date(e.time).getTime() / 1000) || 0 : 0,
    kind: 'transfer', label: '',
  })).filter((e) => bNodes.some((n) => n.id === e.source) && bNodes.some((n) => n.id === e.target))
  return { ...EMPTY_BOARD_STATE, nodes: bNodes, edges: bEdges }
}

/** Create a board from a Nexus investigation and register the bidirectional link. */
export async function createBoardFromNexus(
  name: string,
  args: { subject: string; chain?: string; nodes: NexusExportNode[]; edges: NexusExportEdge[]; caseId?: string },
): Promise<Board> {
  const state = nexusToBoardState(args.nodes, args.edges, args.subject, args.chain)
  const board = await createBoard(name, { description: `Saved from Nexus investigation of ${args.subject}`, case_id: args.caseId, state })
  try {
    await addBoardLink(board.id, 'nexus_subject', args.subject, args.chain || '', `Nexus: ${args.subject.slice(0, 12)}…`)
  } catch { /* linking is best-effort */ }
  return board
}

// ── prices (fiat toggle) ──────────────────────────────────────────────────────

export interface PriceQuote { asset: string; usd: number | null; basis: string; date: string | null }
export async function historicalPrice(asset: string, ts?: number): Promise<PriceQuote> {
  const { data } = await api.get('/prices/historical', { params: { asset, ts } })
  return data
}
export async function convertBatch(items: Array<{ asset: string; amount: number; ts?: number; id?: string }>): Promise<Array<{ id?: string; asset: string; amount: number; ts?: number; unit_usd: number | null; usd_at_time: number | null; basis: string }>> {
  const { data } = await api.post('/prices/convert', { items })
  return data.items
}

// ── OSINT sweep ───────────────────────────────────────────────────────────────

export interface OsintHit {
  source: string; title: string; url: string; snippet: string; timestamp?: string
  subreddit?: string; repo?: string; category?: string; high_signal?: boolean; abuse?: boolean
  post_type?: 'post' | 'comment'; author?: string; score?: number; num_comments?: number
}
export interface OsintSignals {
  level: 'critical' | 'high' | 'elevated' | 'notable' | 'informational' | 'clear'
  headline: string
  by_category: Array<{ category: string; label: string; hits: number }>
  high_signal_hits: number; darkweb_hits: number; abuse_hits: number
}
export type RedditType = 'all' | 'posts' | 'comments' | 'off'
export interface OsintSweepResult {
  address: string; cache_version?: number; swept_at: string; total_hits: number; hits: OsintHit[]
  signals?: OsintSignals
  reddit_type?: RedditType
  reddit_deep?: {
    enabled: boolean; search_type: string; posts: number; comments: number
    status?: string | null; warning?: string | null
  }
  sources: Record<string, { ok: boolean; hits: number; status?: string | null; error?: string | null; warning?: string | null; category?: string }>
  unconfigured_sources: Array<{ name: string; requires: string; note: string }>
  disclaimer: string; cached: boolean
}
export async function osintSweep(address: string, refresh = false, redditType: RedditType = 'all'): Promise<OsintSweepResult> {
  const { data } = await api.get(`/osint-sweep/${encodeURIComponent(address)}`, { params: { refresh, reddit_type: redditType } })
  return data
}
export async function osintToEvidence(address: string, caseId: string): Promise<{ evidence_id: string; chain_hash: string; total_hits: number }> {
  const { data } = await api.post(`/osint-sweep/${encodeURIComponent(address)}/to-evidence`, { case_id: caseId })
  return data
}

// ── attribution submissions ───────────────────────────────────────────────────

export interface AttributionSubmission {
  id: string; address: string; chain: string; category: string; actor: string; label: string
  source: string; confidence: number; evidence: Array<{ type: string; value: string; ref?: string }>
  note: string; submitted_by: string; submitted_at: string
  status: 'pending' | 'approved' | 'rejected'
  reviewed_by: string; reviewed_at: string; review_note: string; resulting_attr_id: string
}
export async function submitAttribution(payload: {
  address: string; chain?: string; category?: string; actor?: string; label?: string
  source?: string; confidence?: number; evidence: Array<{ type: string; value: string; ref?: string }>; note?: string
}): Promise<AttributionSubmission> {
  const { data } = await api.post('/attribution-submissions', payload)
  return data
}
export async function listSubmissions(status = ''): Promise<{ submissions: AttributionSubmission[]; stats: { pending: number; approved: number; rejected: number; total: number } }> {
  const { data } = await api.get('/attribution-submissions', { params: status ? { status } : {} })
  return data
}
export async function reviewSubmission(id: string, action: 'approve' | 'reject', reviewNote = ''): Promise<AttributionSubmission> {
  const { data } = await api.post(`/attribution-submissions/${encodeURIComponent(id)}/review`, { action, review_note: reviewNote })
  return data
}

// ── attribution source report (fetch with auth → blob URL for viewing) ────────

export async function fetchSourceReportHtml(address: string, chain?: string): Promise<string> {
  const { data } = await api.get(`/attribution/${encodeURIComponent(address)}/source-report`, {
    params: chain ? { chain } : {}, responseType: 'text', transformResponse: [(d) => d],
  })
  return data as string
}
export function openSourceReport(address: string, chain?: string): void {
  fetchSourceReportHtml(address, chain).then((html) => {
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
    window.open(url, '_blank', 'noopener')
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  })
}
