import axios from 'axios'
import type {
  AddressIntel,
  TraceResult,
  DexResult,
  SanctionsResult,
  ApiSettings,
  RiskScore,
  Case,
  BatchScreenResult,
  TxDetail,
  ForensicResult,
  LocalLabel,
  AiInvestigationResult,
  AiStatus,
  ThreatIntelResponse,
  NexusResponse,
  NexusDemixResponse,
  IdentityProfileResponse,
  TxLensResponse,
  TxLensJob,
  WalletMonitorWatch,
  WalletMonitorNotification,
  WalletMonitorScanResult,
  PathfinderResponse,
  ClusteringResponse,
  CashoutResponse,
  TxInterpretResponse,
  CrossChainResponse,
  TimelineResponse,
  EvidenceRecord,
  EvidenceSummary,
  AuditLogEntry,
  AgentQueryType,
  AgentResponse,
  AgentRunRequest,
  VictimReport,
  ScamCluster,
  ScamIntelSummary,
  ScamTypeInfo,
  ExportBundle,
  NFTTronResult,
  ThreatFeedItem,
  ThreatFeedSource,
  ThreatFeedNewsResponse,
  RansomwareGroup,
  RansomwareGroupsResponse,
  RansomwareIncident,
  RansomwareIncidentsResponse,
  RansomwareStats,
  RansomwareSearchResponse,
  RansomwareFeedResponse,
  RansomwareAddressResponse,
  ThreatActorsResponse,
  AddressIntelResponse,
  ThreatBaselineResponse,
  ThreatActorProfile,
  AddressIntelEntry,
  ReportType,
  GeneratedReport,
  ArkhamResult,
  DeBankResult,
  AttributionAnalysis,
  AlertDestination,
  AlertDelivery,
  SavedInvestigation,
  FeedSyncState,
  FeedRecord,
  FeedDiffAlert,
  FeedImport,
  FeedImportRow,
  EntityInvestigationResult,
  TimeTravelResult,
  TimeTravelPoint,
  DeepTraceResult,
  CaseQaResult,
  CustodyReport,
  CollabPresence,
} from '../types'

export const api = axios.create({
  baseURL: '/api',
  timeout: 120_000,
  headers: { 'Content-Type': 'application/json' },
})

/* Apply the user's configurable request timeout (Settings → Tool Features).
   Read lazily from localStorage and kept in sync when the user changes it. */
function applyTimeoutPref() {
  try {
    const raw = localStorage.getItem('cryptx_prefs')
    if (!raw) return
    const secs = Number(JSON.parse(raw)?.apiTimeoutSec)
    if (Number.isFinite(secs) && secs >= 10 && secs <= 600) {
      api.defaults.timeout = secs * 1000
    }
  } catch {
    /* ignore malformed prefs */
  }
}
applyTimeoutPref()
if (typeof window !== 'undefined') {
  window.addEventListener('cryptx-prefs-changed', applyTimeoutPref)
}

export const AUTH_TOKEN_KEY = 'cryptx_auth_token'
export const AUTH_REFRESH_TOKEN_KEY = 'cryptx_refresh_token'

let refreshPromise: Promise<AuthSession> | null = null

function storeAuthSession(session: AuthSession) {
  sessionStorage.setItem(AUTH_TOKEN_KEY, session.access_token)
  sessionStorage.setItem(AUTH_REFRESH_TOKEN_KEY, session.refresh_token)
}

function clearAuthSession() {
  sessionStorage.removeItem(AUTH_TOKEN_KEY)
  sessionStorage.removeItem(AUTH_REFRESH_TOKEN_KEY)
}

api.interceptors.request.use(config => {
  const token = sessionStorage.getItem(AUTH_TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  response => response,
  async error => {
    const original = error?.config
    const status = error?.response?.status
    const url = String(original?.url || '')
    const isAuthEndpoint = url.includes('/auth/login') || url.includes('/auth/register') || url.includes('/auth/refresh') || url.includes('/auth/logout')
    if (status === 401 && original && !original._retry && !isAuthEndpoint) {
      const refreshToken = sessionStorage.getItem(AUTH_REFRESH_TOKEN_KEY)
      if (refreshToken) {
        original._retry = true
        try {
          refreshPromise = refreshPromise || refreshUserSession(refreshToken)
          const session = await refreshPromise
          refreshPromise = null
          storeAuthSession(session)
          original.headers = original.headers || {}
          original.headers.Authorization = `Bearer ${session.access_token}`
          return api(original)
        } catch (refreshError) {
          refreshPromise = null
          clearAuthSession()
          window.dispatchEvent(new Event('cryptx-auth-expired'))
          return Promise.reject(refreshError)
        }
      }
    }
    if (status === 401) {
      clearAuthSession()
      window.dispatchEvent(new Event('cryptx-auth-expired'))
    }
    return Promise.reject(error)
  },
)

// ── Authentication ───────────────────────────────────────────────────────────

export interface AuthUser {
  id: string
  email: string
  name: string
  role: string
  registration_type?: string
  must_change_password?: boolean
  totp_enabled?: boolean
  org_id?: string
  org_role?: string
  created_at?: string
  last_login_at?: string | null
}

export interface AuthSessionInfo {
  id: string
  created_at: string
  last_seen_at: string
  access_expires_at: string
  refresh_expires_at: string
  revoked_at?: string | null
  revoked_reason?: string | null
  user_agent: string
  ip_address: string
}

export interface AuthSession {
  access_token: string
  refresh_token: string
  token_type: string
  expires_at?: string
  refresh_expires_at?: string
  session?: AuthSessionInfo
  user: AuthUser
}

export interface LoginResponse {
  requires_2fa?: boolean
  pending_token?: string
  access_token?: string
  refresh_token?: string
  token_type?: string
  user?: AuthUser
  session?: AuthSessionInfo
}

export async function loginUser(email: string, password: string): Promise<LoginResponse> {
  const { data } = await api.post<LoginResponse>('/auth/login', { email, password })
  return data
}

export async function verify2FALogin(pendingToken: string, code: string): Promise<AuthSession> {
  const { data } = await api.post<AuthSession>('/auth/2fa/verify', { pending_token: pendingToken, code })
  return data
}

export async function setup2FA(): Promise<{ secret: string; uri: string; qr_svg: string }> {
  const { data } = await api.post('/auth/2fa/setup')
  return data
}

export async function enable2FA(code: string): Promise<{ totp_enabled: boolean }> {
  const { data } = await api.post('/auth/2fa/enable', { code })
  return data
}

export async function disable2FA(code: string): Promise<{ totp_enabled: boolean }> {
  const { data } = await api.post('/auth/2fa/disable', { code })
  return data
}

export async function teamDisable2FA(memberId: string): Promise<{ totp_enabled: boolean; user_id: string }> {
  const { data } = await api.post('/auth/2fa/team-disable', { member_id: memberId })
  return data
}

export async function beaconLogout(): Promise<void> {
  const token = sessionStorage.getItem(AUTH_TOKEN_KEY)
  if (!token) return
  try {
    await navigator.sendBeacon(
      '/api/auth/beacon-logout',
      new Blob([], { type: 'application/json' })
    )
  } catch { /* best-effort */ }
  // Also try a regular fetch with the token as fallback
  try {
    await fetch('/api/auth/beacon-logout', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      keepalive: true,
    })
  } catch { /* best-effort */ }
  sessionStorage.removeItem(AUTH_TOKEN_KEY)
  sessionStorage.removeItem(AUTH_REFRESH_TOKEN_KEY)
}

export async function registerUser(payload: {
  email: string
  password: string
  name?: string
  registration_type?: string
  team_name?: string
}): Promise<AuthSession> {
  const { data } = await api.post<AuthSession>('/auth/register', payload)
  return data
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const { data } = await api.get<{ user: AuthUser }>('/auth/me')
  return data.user
}

export async function fetchCurrentSession(): Promise<{ user: AuthUser; session: AuthSessionInfo }> {
  const { data } = await api.get<{ user: AuthUser; session: AuthSessionInfo }>('/auth/me')
  return data
}

export async function requestPasswordReset(email: string): Promise<{ sent: boolean; dev_reset_token?: string | null }> {
  const { data } = await api.post('/auth/forgot-password', { email })
  return data
}

export async function resetPassword(token: string, password: string): Promise<{ reset: boolean; user: AuthUser }> {
  const { data } = await api.post<{ reset: boolean; user: AuthUser }>('/auth/reset-password', { token, password })
  return data
}

export async function refreshUserSession(refresh_token: string): Promise<AuthSession> {
  const { data } = await api.post<AuthSession>('/auth/refresh', { refresh_token })
  return data
}

export async function logoutUser(refresh_token?: string | null): Promise<void> {
  await api.post('/auth/logout', { refresh_token })
}

export async function updateAuthProfile(payload: { name: string }): Promise<AuthUser> {
  const { data } = await api.patch<{ user: AuthUser }>('/auth/profile', payload)
  return data.user
}

export async function changeAuthPassword(payload: { current_password: string; new_password: string }): Promise<AuthSession> {
  const { data } = await api.post<AuthSession>('/auth/change-password', payload)
  return data
}

export async function listAuthSessions(): Promise<{ current_session_id: string; sessions: AuthSessionInfo[] }> {
  const { data } = await api.get<{ current_session_id: string; sessions: AuthSessionInfo[] }>('/auth/sessions')
  return data
}

export async function revokeAuthSession(sessionId: string): Promise<void> {
  await api.delete(`/auth/sessions/${encodeURIComponent(sessionId)}`)
}

export async function logoutOtherSessions(): Promise<void> {
  await api.post('/auth/logout-all')
}

// ── Address Intel ─────────────────────────────────────────────────────────────

export async function lookupAddress(address: string, timeoutMs = 90_000): Promise<AddressIntel> {
  const { data } = await api.post<AddressIntel>('/address', { address }, { timeout: timeoutMs })
  return data
}

export async function checkSanctions(address: string): Promise<SanctionsResult> {
  const { data } = await api.post<SanctionsResult>('/sanctions', { address })
  return data
}

// ── Owner attribution (unified, provider-agnostic) ───────────────────────────

export async function arkhamLookup(address: string, timeoutMs = 120_000): Promise<ArkhamResult> {
  const { data } = await api.post<ArkhamResult>('/arkham/lookup', { address }, { timeout: timeoutMs })
  return data
}

export async function debankOwner(address: string, timeoutMs = 120_000): Promise<DeBankResult> {
  const { data } = await api.post<DeBankResult>('/debank/owner', { address }, { timeout: timeoutMs })
  return data
}

/** Unified owner attribution + associated wallet balances for an address. */
export async function attributionAnalysis(address: string, timeoutMs = 150_000): Promise<AttributionAnalysis> {
  const { data } = await api.post<AttributionAnalysis>('/attribution-analysis', { address }, { timeout: timeoutMs })
  return data
}

// ── Risk Scoring ─────────────────────────────────────────────────────────────

export async function scoreRisk(intel: AddressIntel): Promise<RiskScore> {
  const { data } = await api.post<RiskScore>('/risk-score', { intel })
  return data
}

// ── Public Enrichment ────────────────────────────────────────────────────────

export async function enrichPublicAddress(payload: {
  address: string
  chain?: string
  intel?: unknown
  refresh?: boolean
}): Promise<{ status: string; enrichment: import('../types').PublicEnrichment }> {
  const { data } = await api.post('/public-enrichment/address', payload, { timeout: 120_000 })
  return data
}

export async function refreshPublicEnrichment(): Promise<{ refreshed_at: string; imported: number; sources: unknown[] }> {
  const { data } = await api.post('/public-enrichment/refresh', {}, { timeout: 180_000 })
  return data
}

export async function publicEnrichmentStatus(): Promise<Record<string, unknown>> {
  const { data } = await api.get('/public-enrichment/status')
  return data
}

// ── Fund Tracer ───────────────────────────────────────────────────────────────

export async function traceAddress(params: {
  address: string
  hops: number
  mode: 'linear' | 'wide'
  direction: 'out' | 'in' | 'both'
  timeout?: number
  timeout_seconds?: number
}): Promise<TraceResult> {
  const { timeout: ms, ...body } = params
  const { data } = await api.post<TraceResult>('/trace', body, ms ? { timeout: ms } : undefined)
  return data
}

/**
 * Deep analysis trace: runs the multi-hop trace + orchestrates the five
 * analysis engines (forensic motifs, cashout, crosschain, clustering, risk)
 * plus three new algorithms (peel-chain, layering, dwell-time). Returns the
 * same {trace, graph} shape as traceAddress, but with graph.patterns populated
 * and graph.nodes enriched (balance, tx_count, first/last_seen, risk_labels).
 */
export async function traceDeepAddress(params: {
  address: string
  hops: number
  mode: 'linear' | 'wide'
  direction: 'out' | 'in' | 'both'
  timeout?: number
  timeout_seconds?: number
}): Promise<TraceResult> {
  const { timeout: ms, ...body } = params
  const { data } = await api.post<TraceResult>('/trace/deep', body, ms ? { timeout: ms } : undefined)
  return data
}

export async function fetchTraceHtml(params: {
  address: string
  hops: number
  mode: string
  direction: string
}): Promise<string> {
  const resp = await fetch('/api/trace/html', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!resp.ok) {
    const err = await resp.text()
    throw new Error(err || `HTTP ${resp.status}`)
  }
  return resp.text()
}

// ── DEX Analysis ─────────────────────────────────────────────────────────────

export async function fetchDex(address: string): Promise<DexResult> {
  const { data } = await api.post<DexResult>('/dex', { address })
  return data
}

// ── ENS ──────────────────────────────────────────────────────────────────────

export async function resolveEns(name: string): Promise<unknown> {
  const { data } = await api.post('/ens/resolve', { name })
  return data
}

export async function reverseEns(address: string): Promise<unknown> {
  const { data } = await api.post('/ens/reverse', { address })
  return data
}

// ── Case Management ───────────────────────────────────────────────────────────

export async function listCases(): Promise<Case[]> {
  const { data } = await api.get<{ cases: Case[] }>('/cases')
  return data.cases
}

export async function createCase(name: string, description = ''): Promise<Case> {
  const { data } = await api.post<Case>('/cases', { name, description })
  return data
}

export async function getCase(caseId: string): Promise<Case> {
  const { data } = await api.get<Case>(`/cases/${caseId}`)
  return data
}

export async function updateCase(
  caseId: string,
  updates: { name?: string; description?: string; status?: string }
): Promise<Case> {
  const { data } = await api.patch<Case>(`/cases/${caseId}`, updates)
  return data
}

export async function deleteCase(caseId: string): Promise<void> {
  await api.delete(`/cases/${caseId}`)
}

export async function addAddressToCase(
  caseId: string,
  payload: {
    address: string
    chain?: string
    label?: string
    notes?: string
    risk_score?: number
    risk_level?: string
  }
): Promise<void> {
  await api.post(`/cases/${caseId}/addresses`, payload)
}

export async function removeAddressFromCase(caseId: string, address: string): Promise<void> {
  await api.delete(`/cases/${caseId}/addresses/${address}`)
}

export async function addNote(caseId: string, note: string): Promise<void> {
  await api.post(`/cases/${caseId}/notes`, { note })
}

export async function deleteNote(caseId: string, noteId: number): Promise<void> {
  await api.delete(`/cases/${caseId}/notes/${noteId}`)
}

// ── Case member roles ────────────────────────────────────────────────────────

export interface CaseMember {
  case_id: string
  user_id: string
  email: string
  case_role: 'full_access' | 'reviewer'
  added_by: string
  added_at: string
}

export async function listCaseMembers(caseId: string): Promise<{ owner: Record<string, string>; members: CaseMember[] }> {
  const { data } = await api.get(`/cases/${caseId}/members`)
  return data
}

export async function addCaseMember(caseId: string, email: string, caseRole: 'full_access' | 'reviewer' = 'full_access'): Promise<{ added: string; case_role: string }> {
  const { data } = await api.post(`/cases/${caseId}/members`, { email, case_role: caseRole })
  return data
}

export async function updateCaseMemberRole(caseId: string, userId: string, caseRole: 'full_access' | 'reviewer'): Promise<{ user_id: string; case_role: string }> {
  const { data } = await api.put(`/cases/${caseId}/members/${encodeURIComponent(userId)}/role`, { case_role: caseRole })
  return data
}

export async function removeCaseMember(caseId: string, userId: string): Promise<{ removed: string }> {
  const { data } = await api.delete(`/cases/${caseId}/members/${encodeURIComponent(userId)}`)
  return data
}

// ── Case tasks ───────────────────────────────────────────────────────────────

export interface CaseTask {
  id: string
  case_id: string
  title: string
  description: string
  status: 'open' | 'in_progress' | 'done' | 'closed'
  priority: 'low' | 'medium' | 'high' | 'urgent'
  assigned_to: string
  assigned_by: string
  assignee_name?: string
  assigner_name?: string
  due_date: string
  created_at: string
  updated_at: string
  completed_at: string
}

export interface TaskMessage {
  id: number
  task_id: string
  user_id: string
  user_name: string
  message: string
  msg_type: 'chat' | 'system' | 'delivery'
  created_at: string
}

export interface TaskDeliverable {
  id: string
  task_id: string
  title: string
  description: string
  content: string
  status: 'pending' | 'submitted' | 'approved' | 'rejected' | 'revision_requested'
  submitted_by: string
  reviewed_by: string
  review_note: string
  created_at: string
  updated_at: string
}

export async function listCaseTasks(caseId: string): Promise<{ tasks: CaseTask[] }> {
  const { data } = await api.get(`/cases/${caseId}/tasks`)
  return data
}

export async function createCaseTask(caseId: string, payload: {
  title: string
  description?: string
  assigned_to: string
  priority?: string
  due_date?: string
}): Promise<{ task_id: string; status: string }> {
  const { data } = await api.post(`/cases/${caseId}/tasks`, payload)
  return data
}

export async function getCaseTask(caseId: string, taskId: string): Promise<{ task: CaseTask }> {
  const { data } = await api.get(`/cases/${caseId}/tasks/${taskId}`)
  return data
}

export async function updateCaseTask(caseId: string, taskId: string, updates: {
  title?: string
  description?: string
  status?: string
  priority?: string
  due_date?: string
  assigned_to?: string
}): Promise<{ task: CaseTask }> {
  const { data } = await api.patch(`/cases/${caseId}/tasks/${taskId}`, updates)
  return data
}

export async function deleteCaseTask(caseId: string, taskId: string): Promise<{ deleted: string }> {
  const { data } = await api.delete(`/cases/${caseId}/tasks/${taskId}`)
  return data
}

// ── Task messages (chat) ─────────────────────────────────────────────────────

export async function listTaskMessages(caseId: string, taskId: string): Promise<{ messages: TaskMessage[] }> {
  const { data } = await api.get(`/cases/${caseId}/tasks/${taskId}/messages`)
  return data
}

export async function sendTaskMessage(caseId: string, taskId: string, message: string): Promise<{ sent: boolean }> {
  const { data } = await api.post(`/cases/${caseId}/tasks/${taskId}/messages`, { message })
  return data
}

// ── Task deliverables ────────────────────────────────────────────────────────

export async function listTaskDeliverables(caseId: string, taskId: string): Promise<{ deliverables: TaskDeliverable[] }> {
  const { data } = await api.get(`/cases/${caseId}/tasks/${taskId}/deliverables`)
  return data
}

export async function submitDeliverable(caseId: string, taskId: string, payload: {
  title: string
  description?: string
  content?: string
}): Promise<{ deliverable_id: string; status: string }> {
  const { data } = await api.post(`/cases/${caseId}/tasks/${taskId}/deliverables`, payload)
  return data
}

export async function reviewDeliverable(caseId: string, taskId: string, deliverableId: string, payload: {
  status: 'approved' | 'rejected' | 'revision_requested'
  review_note?: string
}): Promise<{ deliverable_id: string; status: string }> {
  const { data } = await api.put(`/cases/${caseId}/tasks/${taskId}/deliverables/${deliverableId}/review`, payload)
  return data
}

// ── Notifications ─────────────────────────────────────────────────────────────

export interface UserNotification {
  id: string
  user_id: string
  actor_id: string
  actor_name: string
  type: string
  case_id: string
  task_id: string
  title: string
  message: string
  is_read: number
  created_at: string
}

export async function listNotifications(params?: {
  unread_only?: boolean
  limit?: number
}): Promise<UserNotification[]> {
  const { data } = await api.get<{ notifications: UserNotification[] }>('/notifications', { params })
  return data.notifications
}

export async function getUnreadNotificationCount(): Promise<number> {
  const { data } = await api.get<{ count: number }>('/notifications/unread-count')
  return data.count
}

export async function markNotificationRead(notifId: string): Promise<void> {
  await api.post(`/notifications/${notifId}/read`)
}

export async function markAllNotificationsRead(): Promise<void> {
  await api.post('/notifications/read-all')
}

// ── Case Audit Log ────────────────────────────────────────────────────────────

export interface AuditEntry {
  id: number
  case_id: string
  user_id: string
  user_name: string
  user_role: string
  action: string
  target: string
  detail: string
  timestamp: string
}

export async function listCaseAudit(caseId: string, params?: {
  limit?: number
  offset?: number
  action?: string
  user_id?: string
  from_ts?: string
  to_ts?: string
}): Promise<{ entries: AuditEntry[]; total: number }> {
  const { data } = await api.get(`/cases/${caseId}/audit`, { params })
  return data
}

// ── Batch Screening ───────────────────────────────────────────────────────────

export async function batchScreen(
  addresses: string[],
  maxConcurrent = 5
): Promise<BatchScreenResult> {
  const { data } = await api.post<BatchScreenResult>('/batch/screen', {
    addresses,
    max_concurrent: maxConcurrent,
  })
  return data
}

// ── Transaction Detail ────────────────────────────────────────────────────────

export async function lookupTx(hash: string, chain?: string): Promise<TxDetail> {
  const { data } = await api.post<TxDetail>('/tx', { hash, chain })
  return data
}

export async function investigateTx(payload: {
  hash: string
  chain?: string
  include_ai?: boolean
  analyst_focus?: string
  enrich_addresses?: boolean
  expand_traces?: boolean
  max_addresses?: number
}): Promise<TxLensResponse> {
  const { data } = await api.post<TxLensResponse>('/tx-investigate/analyze', payload)
  return data
}

export async function startTxInvestigationJob(payload: {
  hash: string
  chain?: string
  include_ai?: boolean
  analyst_focus?: string
  enrich_addresses?: boolean
  expand_traces?: boolean
  max_addresses?: number
}): Promise<TxLensJob> {
  const { data } = await api.post<TxLensJob>('/tx-investigate/jobs', payload)
  return data
}

export async function getTxInvestigationJob(jobId: string): Promise<TxLensJob> {
  const { data } = await api.get<TxLensJob>(`/tx-investigate/jobs/${encodeURIComponent(jobId)}`)
  return data
}

// ── Wallet Monitoring ───────────────────────────────────────────────────────

export async function listMonitorWatches(): Promise<WalletMonitorWatch[]> {
  const { data } = await api.get<{ watches: WalletMonitorWatch[] }>('/monitor/watches')
  return data.watches
}

export async function createMonitorWatches(payload: {
  addresses: string[]
  chain?: string
  label?: string
  poll_interval?: number
  baseline_existing?: boolean
}): Promise<WalletMonitorWatch[]> {
  const { data } = await api.post<{ watches: WalletMonitorWatch[] }>('/monitor/watches', payload)
  return data.watches
}

export async function updateMonitorWatch(
  monitorId: string,
  payload: { active?: boolean; label?: string; poll_interval?: number }
): Promise<WalletMonitorWatch> {
  const { data } = await api.patch<WalletMonitorWatch>(`/monitor/watches/${monitorId}`, payload)
  return data
}

export async function deleteMonitorWatch(monitorId: string): Promise<void> {
  await api.delete(`/monitor/watches/${monitorId}`)
}

export async function scanMonitorNow(): Promise<WalletMonitorScanResult> {
  const { data } = await api.post<WalletMonitorScanResult>('/monitor/scan')
  return data
}

export async function listMonitorNotifications(params?: {
  unread_only?: boolean
  limit?: number
}): Promise<WalletMonitorNotification[]> {
  const { data } = await api.get<{ notifications: WalletMonitorNotification[] }>('/monitor/notifications', { params })
  return data.notifications
}

export async function markMonitorNotificationRead(notificationId: string): Promise<WalletMonitorNotification> {
  const { data } = await api.post<WalletMonitorNotification>(`/monitor/notifications/${notificationId}/read`)
  return data
}

// ── Local Forensic Analysis ──────────────────────────────────────────────────

export async function analyzeForensics(payload: {
  address: string
  intel?: AddressIntel
  trace_graph?: unknown
  dex_activity?: unknown
  persist?: boolean
}): Promise<ForensicResult> {
  const { data } = await api.post<ForensicResult>('/forensics/analyze', payload)
  return data
}

export async function listLabels(query = ''): Promise<LocalLabel[]> {
  const { data } = await api.get<{ labels: LocalLabel[] }>('/labels', { params: { query } })
  return data.labels
}

export async function createLabel(payload: {
  address: string
  chain?: string
  label: string
  category?: string
  risk_weight?: number
  confidence?: number
  source?: string
  notes?: string
}): Promise<LocalLabel> {
  const { data } = await api.post<LocalLabel>('/labels', payload)
  return data
}

export async function importLabels(csvText: string): Promise<{ imported: number; labels: LocalLabel[] }> {
  const { data } = await api.post<{ imported: number; labels: LocalLabel[] }>('/labels/import', {
    csv_text: csvText,
  })
  return data
}

export async function deleteLabel(labelId: number): Promise<void> {
  await api.delete(`/labels/${labelId}`)
}

export function forensicReportUrl(runId: string): string {
  return `/api/forensics/runs/${encodeURIComponent(runId)}/report`
}

export function caseReportUrl(caseId: string): string {
  return `/api/cases/${encodeURIComponent(caseId)}/report`
}

// ── AI Copilot ───────────────────────────────────────────────────────────────

export async function aiStatus(): Promise<AiStatus> {
  const { data } = await api.get<AiStatus>('/ai/status')
  return data
}

export async function testAiProvider(): Promise<AiStatus> {
  const { data } = await api.post<AiStatus>('/ai/test')
  return data
}

export async function aiInvestigate(payload: {
  address?: string
  chain?: string
  intel?: unknown
  risk?: unknown
  forensic?: unknown
  case?: unknown
  question?: string
}): Promise<AiInvestigationResult> {
  const { data } = await api.post<AiInvestigationResult>('/ai/investigate', payload)
  return data
}

export async function aiExtractNotes(text: string): Promise<Record<string, unknown>> {
  const { data } = await api.post('/ai/extract-notes', { text })
  return data
}

export async function aiChat(messages: Array<{ role: 'user' | 'assistant'; content: string }>, evidence?: unknown): Promise<{ content: string; model: string }> {
  const { data } = await api.post('/ai/chat', { messages, evidence })
  return data
}

// ── Threat Intelligence ─────────────────────────────────────────────────────

export async function analyzeThreatIntel(payload: {
  address: string
  intel?: unknown
  trace_graph?: unknown
  dex_activity?: unknown
  include_ai?: boolean
  analyst_focus?: string
}): Promise<ThreatIntelResponse> {
  const { data } = await api.post<ThreatIntelResponse>('/threat-intel/analyze', payload)
  return data
}

// ── Nexus Graph ─────────────────────────────────────────────────────────────

export async function analyzeNexusGraph(payload: {
  address: string
  intel?: unknown
  trace_graph?: unknown
  include_ai?: boolean
  analyst_focus?: string
  max_nodes?: number
}): Promise<NexusResponse> {
  const { data } = await api.post<NexusResponse>('/nexus/analyze', payload, { timeout: 300_000 })
  return data
}

export async function runNexusDemix(payload: {
  nexus: unknown
  selected_addresses?: string[]
  run_tornado?: boolean
  run_mixer?: boolean
  run_bridge?: boolean
  run_chain_swap?: boolean
  run_aml?: boolean
  max_candidates?: number
  time_window_seconds?: number
  value_tolerance?: number
}): Promise<NexusDemixResponse> {
  const { data } = await api.post<NexusDemixResponse>('/nexus/demix', payload, { timeout: 180_000 })
  return data
}

export async function buildIdentityProfile(payload: {
  address: string
  intel?: unknown
  graph?: unknown
  threat?: unknown
  include_lookup?: boolean
}): Promise<IdentityProfileResponse> {
  const { data } = await api.post<IdentityProfileResponse>('/identity/profile', payload, { timeout: 120_000 })
  return data
}

export async function fetchDeBankProfile(address: string): Promise<import('../types').DeBankProfileData> {
  const { data } = await api.get(`/identity/debank/${encodeURIComponent(address)}`, { timeout: 180_000 })
  return data
}

// ── NFT / TRON Sentinel ─────────────────────────────────────────────────────

export async function analyzeNFTTron(payload: {
  subject: string
  chain?: string
  focus?: string
}): Promise<NFTTronResult> {
  const { data } = await api.post<NFTTronResult>('/nft-tron/analyze', payload, { timeout: 120_000 })
  return data
}

// ── Compliance: Sanctions / KYV / Regulatory / Demixing (v3) ─────────────────

export async function screenSanctions(address: string, chain?: string): Promise<import('../types').SanctionsScreenResult> {
  const { data } = await api.post('/sanctions/screen', { address, chain })
  return data
}

export async function screenSanctionsBulk(addresses: string[], chain?: string): Promise<{ total: number; sanctioned_count: number; results: import('../types').SanctionsScreenResult[] }> {
  const { data } = await api.post('/sanctions/screen-bulk', { addresses, chain })
  return data
}

export async function searchSanctions(query: string, limit = 25, min_score = 0.55): Promise<import('../types').SanctionsSearchResult> {
  const { data } = await api.post('/sanctions/search', { query, limit, min_score })
  return data
}

export async function getSanctionsEntity(uid: string): Promise<import('../types').SanctionsEntityDetail> {
  const { data } = await api.get(`/sanctions/entity/${encodeURIComponent(uid)}`)
  return data
}

export async function refreshSanctions(): Promise<{ refreshed_at: string; entities_added: number; sources: unknown[] }> {
  const { data } = await api.post('/sanctions/refresh', {}, { timeout: 120_000 })
  return data
}

export async function sanctionsStatus(): Promise<import('../types').SanctionsStatus> {
  const { data } = await api.get('/sanctions/status')
  return data
}

export async function lookupVasp(address: string, chain?: string): Promise<import('../types').KyvResult> {
  const { data } = await api.get(`/kyv/${encodeURIComponent(address)}`, { params: chain ? { chain } : undefined })
  return data
}

export async function addVasp(payload: { address: string; vasp_name: string; vasp_type?: string; chain?: string; country?: string; jurisdiction?: string; label?: string }): Promise<import('../types').KyvResult> {
  const { data } = await api.post('/kyv', payload)
  return data
}

export async function listVasps(): Promise<{ vasp_count: number; address_count: number; vasps: Array<Record<string, unknown>> }> {
  const { data } = await api.get('/kyv')
  return data
}

export async function generateSar(payload: Record<string, unknown>): Promise<import('../types').RegulatoryReport> {
  const { data } = await api.post('/regulatory/sar', { payload })
  return data
}

export async function generateCtr(payload: Record<string, unknown>): Promise<import('../types').RegulatoryReport> {
  const { data } = await api.post('/regulatory/ctr', { payload })
  return data
}

export async function generateTravelRule(payload: Record<string, unknown>): Promise<import('../types').RegulatoryReport> {
  const { data } = await api.post('/regulatory/travel-rule', { payload })
  return data
}

export async function sarCategories(): Promise<{ categories: string[] }> {
  const { data } = await api.get('/regulatory/sar-categories')
  return data
}

export async function demixTornado(payload: { deposits: Array<Record<string, unknown>>; withdrawals: Array<Record<string, unknown>> }): Promise<import('../types').DemixResult> {
  const { data } = await api.post('/demix/tornado', payload)
  return data
}

export async function demixBridge(payload: { source_events: Array<Record<string, unknown>>; dest_events: Array<Record<string, unknown>> }): Promise<import('../types').DemixResult> {
  const { data } = await api.post('/demix/bridge', payload)
  return data
}

export async function demixMixer(payload: {
  deposits: Array<Record<string, unknown>>
  withdrawals: Array<Record<string, unknown>>
  max_candidates?: number
  time_window_seconds?: number
  value_tolerance?: number
}): Promise<import('../types').DemixResult> {
  const { data } = await api.post('/demix/mixer', payload)
  return data
}

export async function detectChainSwaps(payload: {
  events: Array<Record<string, unknown>>
  value_tolerance?: number
  time_window_seconds?: number
  max_candidates?: number
}): Promise<import('../types').ChainSwapResult> {
  const { data } = await api.post('/demix/chain-swap', payload)
  return data
}

export async function analyzeAmlDemix(payload: {
  deposits?: Array<Record<string, unknown>>
  withdrawals?: Array<Record<string, unknown>>
  source_events?: Array<Record<string, unknown>>
  dest_events?: Array<Record<string, unknown>>
  chain_events?: Array<Record<string, unknown>>
  value_tolerance?: number
  time_window_seconds?: number
  max_candidates?: number
}): Promise<import('../types').AmlDemixResult> {
  const { data } = await api.post('/demix/analyze', payload)
  return data
}

// ── Intelligence: Pathfinding / Clustering / Cashout ─────────────────────────

export async function findPaths(payload: {
  source_id: string
  nodes: unknown[]
  edges: unknown[]
  max_hops?: number
  strategies?: string[]
}): Promise<PathfinderResponse> {
  const { data } = await api.post<PathfinderResponse>('/nexus/paths', payload)
  return data
}

export async function analyzeCluster(payload: {
  nodes: unknown[]
  edges: unknown[]
  methods?: string[]
  gas_threshold?: number
  time_window?: number
  min_shared_counterparties?: number
}): Promise<ClusteringResponse> {
  const { data } = await api.post<ClusteringResponse>('/cluster/analyze', payload)
  return data
}

export async function detectCashout(payload: {
  subject_id: string
  nodes: unknown[]
  edges: unknown[]
}): Promise<CashoutResponse> {
  const { data } = await api.post<CashoutResponse>('/cashout/detect', payload)
  return data
}

// ── Phase 2: TX Interpretation / Cross-Chain / Timeline ──────────────────────

export async function interpretTx(tx: unknown): Promise<TxInterpretResponse> {
  const { data } = await api.post<TxInterpretResponse>('/tx/interpret', { tx })
  return data
}

export async function traceCrossChain(payload: {
  subject_id: string
  nodes: unknown[]
  edges: unknown[]
  time_window?: number
  value_tolerance?: number
}): Promise<CrossChainResponse> {
  const { data } = await api.post<CrossChainResponse>('/crosschain/trace', payload)
  return data
}

export async function buildTimeline(payload: {
  address: string
  intel?: unknown
  trace_graph?: unknown
  risk?: unknown
  case?: unknown
  cashout?: unknown
  crosschain?: unknown
  limit?: number
}): Promise<TimelineResponse> {
  const { data } = await api.post<TimelineResponse>('/timeline/build', payload)
  return data
}

// ── Phase 3: Evidence Vault ───────────────────────────────────────────────────

export async function saveEvidence(
  caseId: string,
  payload: {
    evidence_type: string
    title: string
    content: unknown
    subject?: string
    chain?: string
    tags?: string[]
    analyst_notes?: string
  }
): Promise<{ status: string; evidence: EvidenceRecord }> {
  const { data } = await api.post(`/evidence/${caseId}`, payload)
  return data
}

export async function listEvidence(
  caseId: string,
  params?: { evidence_type?: string; subject?: string; limit?: number }
): Promise<{ status: string; evidence: EvidenceRecord[]; count: number }> {
  const { data } = await api.get(`/evidence/${caseId}`, { params })
  return data
}

export async function getEvidence(
  caseId: string,
  evidenceId: string
): Promise<{ status: string; evidence: EvidenceRecord }> {
  const { data } = await api.get(`/evidence/${caseId}/${evidenceId}`)
  return data
}

export async function annotateEvidence(
  caseId: string,
  evidenceId: string,
  payload: { notes: string; tags?: string[] }
): Promise<{ status: string; evidence: EvidenceRecord }> {
  const { data } = await api.patch(`/evidence/${caseId}/${evidenceId}`, payload)
  return data
}

export async function deleteEvidence(caseId: string, evidenceId: string): Promise<void> {
  await api.delete(`/evidence/${caseId}/${evidenceId}`)
}

export async function evidenceSummary(caseId: string): Promise<{ status: string; summary: EvidenceSummary }> {
  const { data } = await api.get(`/evidence/${caseId}/summary`)
  return data
}

export async function evidenceAuditLog(
  caseId: string,
  evidenceId: string
): Promise<{ status: string; audit_log: AuditLogEntry[] }> {
  const { data } = await api.get(`/evidence/${caseId}/${evidenceId}/audit`)
  return data
}

// ── AI Investigation Agent ────────────────────────────────────────────────────

export async function listAgentQueries(): Promise<{ queries: AgentQueryType[] }> {
  const { data } = await api.get<{ queries: AgentQueryType[] }>('/ai-agent/queries')
  return data
}

export async function runAgentQuery(payload: AgentRunRequest): Promise<AgentResponse> {
  const { data } = await api.post<AgentResponse>('/ai-agent/run', payload)
  return data
}

// ── Victim Reports & Scam Intelligence ───────────────────────────────────────

export async function submitVictimReport(payload: {
  scam_type: string
  scammer_address: string
  chain?: string
  victim_address?: string
  amount_usd?: number
  token?: string
  incident_date?: string
  description?: string
  contact_name?: string
  contact_email?: string
  jurisdiction?: string
  tx_hashes?: string[]
  tags?: string[]
  case_id?: string
}): Promise<{ status: string; report: VictimReport }> {
  const { data } = await api.post('/victim-reports', payload)
  return data
}

export async function listVictimReports(params?: {
  scammer_address?: string
  scam_type?: string
  status?: string
  case_id?: string
  chain?: string
  limit?: number
  offset?: number
}): Promise<{ reports: VictimReport[]; total: number; limit: number; offset: number }> {
  const { data } = await api.get('/victim-reports', { params })
  return data
}

export async function getVictimReport(id: string): Promise<{ status: string; report: VictimReport }> {
  const { data } = await api.get(`/victim-reports/${id}`)
  return data
}

export async function updateVictimReport(
  id: string,
  updates: {
    status?: string
    analyst_notes?: string
    case_id?: string
    jurisdiction?: string
    contact_name?: string
    contact_email?: string
    tags?: string[]
    description?: string
    amount_usd?: number
    incident_date?: string
  }
): Promise<{ status: string; report: VictimReport }> {
  const { data } = await api.patch(`/victim-reports/${id}`, updates)
  return data
}

export async function deleteVictimReport(id: string): Promise<void> {
  await api.delete(`/victim-reports/${id}`)
}

export async function scamIntelSummary(): Promise<{ status: string } & ScamIntelSummary> {
  const { data } = await api.get('/scam-intel/summary')
  return data
}

export async function scamClusters(params?: {
  min_victims?: number
  scam_type?: string
  limit?: number
}): Promise<{ status: string; clusters: ScamCluster[]; count: number }> {
  const { data } = await api.get('/scam-intel/clusters', { params })
  return data
}

export async function scamIntelAddress(address: string): Promise<{ status: string; intel: unknown }> {
  const { data } = await api.get(`/scam-intel/address/${encodeURIComponent(address)}`)
  return data
}

export async function exportReportBundle(
  reportIds: string[]
): Promise<{ status: string; bundle: ExportBundle }> {
  const { data } = await api.post('/scam-intel/export', { report_ids: reportIds })
  return data
}

export async function listScamTypes(): Promise<{ scam_types: ScamTypeInfo[] }> {
  const { data } = await api.get('/scam-intel/scam-types')
  return data
}

// ── Chain of custody ──────────────────────────────────────────────────────────

export interface CustodyVerifyResult {
  valid: boolean
  records_checked: number
  case_records: number
  chain_tip: string
  problems: { id: string; title: string; error: string }[]
  verified_at: string
  note: string
}

export async function verifyCustodyChain(caseId = ''): Promise<CustodyVerifyResult> {
  const { data } = await api.get('/custody/verify', { params: { case_id: caseId } })
  return data
}

export async function registerExport(caseId: string, payload: {
  kind: string; title: string; content: Record<string, unknown>; subject?: string; actor?: string
}): Promise<{ status: string; evidence: EvidenceRecord & { chain_hash?: string } }> {
  const { data } = await api.post(`/custody/register/${encodeURIComponent(caseId)}`, payload)
  return data
}

// ── Label growth loop / entity search ────────────────────────────────────────

export async function importAttributionLabels(items: Record<string, unknown>[], source: string): Promise<{
  imported: number; skipped_duplicates: number; errors: number; source: string
}> {
  const { data } = await api.post('/attribution/import', { items, source })
  return data
}

export async function importOfacLabels(): Promise<{
  imported: number; skipped_duplicates: number; errors: number; rows_in_file: number
}> {
  const { data } = await api.post('/attribution/import/ofac', {}, { timeout: 300_000 })
  return data
}

export interface EntityHit {
  kind: 'attribution' | 'vasp' | 'sanctions' | 'board' | 'case' | 'label'
  name: string
  address: string
  chain: string
  category: string
  source: string
  confidence: number
  /** board / case id for direct navigation */
  ref?: string
}

export async function searchEntities(q: string, limit = 20): Promise<{ query: string; hits: EntityHit[] }> {
  const { data } = await api.get('/entity/search', { params: { q, limit } })
  return data
}

export async function confirmVictimLabel(reportId: string): Promise<{ status: string }> {
  const { data } = await api.post(`/victim-reports/${encodeURIComponent(reportId)}/confirm-label`)
  return data
}

// ── Alert rules ───────────────────────────────────────────────────────────────

export interface AlertRule {
  id: string
  name: string
  address: string
  chain: string
  direction: 'any' | 'in' | 'out'
  min_value: number
  counterparty_category: string
  enabled: boolean
  created_at: string
}

export async function listAlertRules(): Promise<{ rules: AlertRule[]; categories: string[]; directions: string[] }> {
  const { data } = await api.get('/monitor/rules')
  return data
}

export async function createAlertRule(rule: Omit<AlertRule, 'id' | 'created_at'>): Promise<AlertRule> {
  const { data } = await api.post('/monitor/rules', rule)
  return data
}

export async function updateAlertRule(id: string, rule: Omit<AlertRule, 'id' | 'created_at'>): Promise<AlertRule> {
  const { data } = await api.patch(`/monitor/rules/${encodeURIComponent(id)}`, rule)
  return data
}

export async function deleteAlertRule(id: string): Promise<void> {
  await api.delete(`/monitor/rules/${encodeURIComponent(id)}`)
}

// ── Auto-investigation ────────────────────────────────────────────────────────

export interface AutoJob {
  job_id: string
  address: string
  status: 'running' | 'completed' | 'failed'
  stage: string
  progress: number
  detail: string
  stages: string[]
  partial: Record<string, Record<string, unknown>>
  result: {
    address: string
    chain: string
    risk: RiskScore
    forensics: Record<string, unknown>
    threat_intel: Record<string, unknown>
    attribution: Record<string, unknown>
    exit_vasp?: Record<string, unknown>
    report_markdown: string
    report_html: string
    custody: { evidence_id?: string; chain_hash?: string; error?: string } | null
  } | null
  error: string | null
}

export async function startAutoInvestigation(payload: {
  address: string; chain?: string; case_id?: string
}): Promise<{ job_id: string }> {
  const { data } = await api.post('/auto/start', payload)
  return data
}

export async function getAutoJob(jobId: string): Promise<AutoJob> {
  const { data } = await api.get(`/auto/jobs/${encodeURIComponent(jobId)}`)
  return data
}

// ── VASP dossier ──────────────────────────────────────────────────────────────

export interface VaspDossier {
  vasp_name: string
  vasp_type: string
  country: string
  jurisdiction: string
  address_count: number
  chains: string[]
  addresses: { address: string; chain: string; label: string; source: string }[]
  sanctions_exposure: { address: string; detail: unknown[] }[]
  high_risk_attributions: { address: string; categories: string[] }[]
  risk_level: string
  risk_reasons: string[]
  disclaimer: string
  markdown: string
}

export async function getVaspDossier(name: string): Promise<VaspDossier> {
  const { data } = await api.get(`/kyv/dossier/${encodeURIComponent(name)}`)
  return data
}

// ── RBAC admin ────────────────────────────────────────────────────────────────

export interface AdminUser {
  id: string
  email: string
  name: string
  role: string
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

export async function adminListUsers(): Promise<{ users: AdminUser[]; roles: string[] }> {
  const { data } = await api.get('/auth/users')
  return data
}

export async function adminSetRole(userId: string, role: string): Promise<{ user: AdminUser }> {
  const { data } = await api.patch(`/auth/users/${encodeURIComponent(userId)}/role`, { role })
  return data
}

export async function adminSetActive(userId: string, isActive: boolean): Promise<{ user: AdminUser }> {
  const { data } = await api.patch(`/auth/users/${encodeURIComponent(userId)}/active`, { is_active: isActive })
  return data
}

// ── Team management ──────────────────────────────────────────────────────────

export interface TeamInfo {
  id: string
  name: string
  slug: string
  plan: string
  created_at: string
}

export interface TeamMember {
  id: string
  email: string
  name: string
  role: string
  org_role: string
  is_active: boolean
  totp_enabled?: boolean
  created_at: string
  last_login_at: string | null
}

export async function fetchTeamInfo(): Promise<{ team: TeamInfo; members: TeamMember[]; member_count: number }> {
  const { data } = await api.get('/auth/team/info')
  return data
}

export async function updateTeamName(teamName: string): Promise<{ team: TeamInfo }> {
  const { data } = await api.patch('/auth/team/name', { team_name: teamName })
  return data
}

export async function createTeamMember(payload: {
  email: string
  name: string
  temp_password?: string
}): Promise<{ member: TeamMember & { temp_password: string } }> {
  const { data } = await api.post('/auth/team/members', payload)
  return data
}

export async function listTeamMembers(): Promise<{ members: TeamMember[] }> {
  const { data } = await api.get('/auth/team/members')
  return data
}

export async function removeTeamMember(memberId: string): Promise<{ removed: boolean }> {
  const { data } = await api.delete(`/auth/team/members/${encodeURIComponent(memberId)}`)
  return data
}

// ── Settings ──────────────────────────────────────────────────────────────────

export async function getSettings(): Promise<ApiSettings> {
  const { data } = await api.get<ApiSettings>('/settings')
  return data
}

export async function saveSettings(settings: Partial<ApiSettings>): Promise<void> {
  await api.post('/settings', settings)
}

// ── Health ────────────────────────────────────────────────────────────────────

export async function healthCheck(): Promise<boolean> {
  try {
    await api.get('/health', { baseURL: '', timeout: 3000 })
    return true
  } catch {
    return false
  }
}

/* ── Mega Report Generator ──────────────────────────────────────────────────── */
export async function getReportTypes(): Promise<{ types: ReportType[] }> {
  const { data } = await api.get('/reports/types')
  return data
}

export async function generateReport(payload: {
  case_id: string
  report_type: string
  include_ai?: boolean
}): Promise<GeneratedReport> {
  const { data } = await api.post('/reports/generate', payload)
  return data
}

/* ── Blockchain Threat Landscape (RSS threat feeds) ─────────────────────────── */
export async function getThreatBaseline(): Promise<ThreatBaselineResponse> {
  const { data } = await api.get('/ransomware/baseline', { timeout: 30_000 })
  return data
}

export async function refreshThreatData(): Promise<{ status: string; message?: string }> {
  const { data } = await api.post('/ransomware/refresh', {}, { timeout: 10_000 })
  return data
}

export async function getThreatRefreshStatus(): Promise<{ running: boolean; started_at: string | null; completed_at: string | null; error: string | null }> {
  const { data } = await api.get('/ransomware/refresh-status')
  return data
}

export async function getThreatFeedNews(params?: {
  source?: string
  limit?: number
  refresh?: boolean
}): Promise<ThreatFeedNewsResponse> {
  const { data } = await api.get('/threat-feed/news', { params })
  return data
}

export async function getThreatFeedItem(
  itemId: string,
  refresh = false,
): Promise<ThreatFeedItem> {
  const { data } = await api.get(`/threat-feed/item/${itemId}`, { params: { refresh } })
  return data.item
}

export async function listThreatFeedSources(): Promise<{ sources: ThreatFeedSource[] }> {
  const { data } = await api.get('/threat-feed/sources')
  return data
}

/* ── Ransomware Intelligence ─────────────────────────────────────────────────── */
export async function getRansomwareGroups(refresh = false): Promise<RansomwareGroupsResponse> {
  const { data } = await api.get('/ransomware/groups', { params: { refresh } })
  return data
}

export async function getRansomwareGroupDetail(groupName: string, refresh = false) {
  const { data } = await api.get(`/ransomware/groups/${encodeURIComponent(groupName)}`, { params: { refresh } })
  return data
}

export async function getRansomwareIncidents(params?: {
  group?: string
  limit?: number
  refresh?: boolean
}): Promise<RansomwareIncidentsResponse> {
  const { data } = await api.get('/ransomware/incidents', { params })
  return data
}

export async function getRansomwareStats(refresh = false): Promise<RansomwareStats> {
  const { data } = await api.get('/ransomware/stats', { params: { refresh } })
  return data
}

export async function searchRansomware(q: string): Promise<RansomwareSearchResponse> {
  const { data } = await api.get('/ransomware/search', { params: { q } })
  return data
}

export async function lookupRansomwareAddress(address: string): Promise<RansomwareAddressResponse> {
  const { data } = await api.get(`/ransomware/address/${encodeURIComponent(address)}`)
  return data
}

export async function getRansomwareFeed(params?: {
  limit?: number
  refresh?: boolean
}): Promise<RansomwareFeedResponse> {
  const { data } = await api.get('/ransomware/feed', { params })
  return data
}

// ── Threat Actor Profiles ──────────────────────────────────────────────────────
export async function getThreatActors(params?: {
  refresh?: boolean
  limit?: number
  sort_by?: string
  active_only?: boolean
  with_crypto_only?: boolean
}): Promise<ThreatActorsResponse> {
  const { data } = await api.get('/ransomware/threat-actors', { params })
  return data
}

export async function getThreatActorDetail(name: string, refresh?: boolean) {
  const { data } = await api.get(`/ransomware/threat-actors/${encodeURIComponent(name)}`, { params: { refresh } })
  return data
}

// ── Address Intelligence ───────────────────────────────────────────────────────
export async function getAddressIntel(params?: {
  refresh?: boolean
  limit?: number
  chain?: string
  actor?: string
  with_balance_only?: boolean
}): Promise<AddressIntelResponse> {
  const { data } = await api.get('/ransomware/address-intel', { params })
  return data
}

export async function getAddressIntelDetail(address: string) {
  const { data } = await api.get(`/ransomware/address-intel/${encodeURIComponent(address)}`)
  return data
}

// ── Crypto Wallets ─────────────────────────────────────────────────────────────
export async function getCryptoWallets(params?: {
  refresh?: boolean
  limit?: number
  chain?: string
  group?: string
}) {
  const { data } = await api.get('/ransomware/crypto-wallets', { params })
  return data
}

export async function getCryptoGroups(refresh?: boolean) {
  const { data } = await api.get('/ransomware/crypto-groups', { params: { refresh } })
  return data
}

// ════════════════════════════════════════════════════════════════════════════
// V2 FEATURES API — graph store, exports, feed sync, ingestion, DeFi trackers,
// entity investigation, time-travel, deep chain, case QA, custody, collab, portal
// ════════════════════════════════════════════════════════════════════════════

// ── F1: Alert delivery destinations ──────────────────────────────────────────
export async function listAlertDestinations(): Promise<{ destinations: AlertDestination[]; kinds: string[] }> {
  const { data } = await api.get('/monitor/destinations')
  return data
}
export async function createAlertDestination(payload: { name: string; kind: string; config: Record<string, unknown>; enabled?: boolean }): Promise<AlertDestination> {
  const { data } = await api.post('/monitor/destinations', payload)
  return data
}
export async function toggleAlertDestination(id: string, enabled: boolean): Promise<{ updated: boolean }> {
  const { data } = await api.patch(`/monitor/destinations/${id}?enabled=${enabled}`)
  return data
}
export async function deleteAlertDestination(id: string): Promise<{ deleted: boolean }> {
  const { data } = await api.delete(`/monitor/destinations/${id}`)
  return data
}
export async function listAlertDeliveries(limit = 50): Promise<{ deliveries: AlertDelivery[] }> {
  const { data } = await api.get(`/monitor/deliveries?limit=${limit}`)
  return data
}

// ── F2: Saved investigations (graph store) ───────────────────────────────────
export async function listInvestigations(caseId?: string): Promise<{ investigations: SavedInvestigation[] }> {
  const { data } = await api.get('/investigations', { params: caseId ? { case_id: caseId } : {} })
  return data
}
export async function getInvestigation(id: string): Promise<SavedInvestigation> {
  const { data } = await api.get(`/investigations/${id}`)
  return data
}
export async function saveInvestigation(payload: { subject: string; chain?: string; graph: Record<string, unknown>; name?: string; case_id?: string }): Promise<SavedInvestigation> {
  const { data } = await api.post('/investigations', payload, { timeout: 60_000 })
  return data
}
export async function expandInvestigation(id: string, newGraph: Record<string, unknown>): Promise<SavedInvestigation> {
  const { data } = await api.post(`/investigations/${id}/expand`, { new_graph: newGraph }, { timeout: 60_000 })
  return data
}
export async function snapshotInvestigation(id: string, note?: string): Promise<{ id: string }> {
  const { data } = await api.post(`/investigations/${id}/snapshot`, null, { params: { note: note || '' } })
  return data
}
export async function deleteInvestigation(id: string): Promise<{ deleted: boolean }> {
  const { data } = await api.delete(`/investigations/${id}`)
  return data
}

// ── F3/F13: Exports (PDF / DOCX / FinCEN XML / STIX / MISP) ──────────────────
export async function exportCapabilities(): Promise<{ pdf: string; docx: string; fincen_xml: boolean; stix: boolean; misp: boolean }> {
  const { data } = await api.get('/exports/capabilities')
  return data
}
export async function exportPdf(payload: { html_content: string; title?: string; case_id?: string }): Promise<Blob> {
  const { data } = await api.post('/exports/pdf', payload, { responseType: 'blob', timeout: 120_000 })
  return data
}
export async function exportDocx(payload: { case_id?: string; report_data?: Record<string, unknown>; title?: string }): Promise<Blob> {
  const { data } = await api.post('/exports/docx', payload, { responseType: 'blob', timeout: 120_000 })
  return data
}
export async function exportFinCenXml(payload: Record<string, unknown>): Promise<{ blob: Blob; artifactId: string }> {
  const resp = await api.post('/exports/fincen-xml', { payload }, { responseType: 'blob', timeout: 60_000 })
  return { blob: resp.data, artifactId: resp.headers['x-artifact-id'] || '' }
}
export async function exportStix(payload: { case_id: string; addresses?: unknown[]; indicators?: unknown[] }): Promise<unknown> {
  const { data } = await api.post('/exports/stix', payload)
  return data
}
export async function exportMisp(payload: { case_id: string; addresses?: unknown[]; tags?: string[] }): Promise<unknown> {
  const { data } = await api.post('/exports/misp', payload)
  return data
}

// ── F4: Feed sync (sanctions auto-refresh + diff alerts) ─────────────────────
export async function syncFeeds(): Promise<{ synced_at: string; feeds: Record<string, unknown> }> {
  const { data } = await api.post('/feeds/sync', {}, { timeout: 180_000 })
  return data
}
export async function feedStatus(): Promise<{ feeds: FeedSyncState[] }> {
  const { data } = await api.get('/feeds/status')
  return data
}
export async function searchFeedRecords(params?: { address?: string; chain?: string; designation?: string; limit?: number }): Promise<{ records: FeedRecord[] }> {
  const { data } = await api.get('/feeds/search', { params })
  return data
}
export async function feedDiffAlerts(params?: { reviewed?: boolean; case_id?: string; limit?: number }): Promise<{ alerts: FeedDiffAlert[] }> {
  const { data } = await api.get('/feeds/diff-alerts', { params })
  return data
}
export async function reviewFeedDiffAlert(id: string): Promise<{ reviewed: boolean }> {
  const { data } = await api.post(`/feeds/diff-alerts/${id}/review`)
  return data
}

// ── F5: Feed ingestion (known-bad pipeline) ──────────────────────────────────
export async function importFeedCsv(payload: { source: string; csv_content: string; filename?: string }): Promise<FeedImport> {
  const { data } = await api.post('/ingestion/import-csv', payload, { timeout: 60_000 })
  return data
}
export async function importFeedJson(payload: { source: string; json_content: string; filename?: string }): Promise<FeedImport> {
  const { data } = await api.post('/ingestion/import-json', payload, { timeout: 60_000 })
  return data
}
export async function listFeedImports(status?: string): Promise<{ imports: FeedImport[]; sources: string[] }> {
  const { data } = await api.get('/ingestion/imports', { params: status ? { status } : {} })
  return data
}
export async function getFeedImport(id: string, rowStatus?: string): Promise<FeedImport & { rows?: FeedImportRow[] }> {
  const { data } = await api.get(`/ingestion/imports/${id}`, { params: rowStatus ? { row_status: rowStatus } : {} })
  return data
}
export async function reviewFeedImport(id: string, rowIds: number[], action: 'approve' | 'reject'): Promise<FeedImport> {
  const { data } = await api.post(`/ingestion/imports/${id}/review`, { row_ids: rowIds, action })
  return data
}

// ── F6: DeFi trackers (stablecoin freeze + exploits) ─────────────────────────
export async function analyzeDefi(payload: { tx_list: Record<string, unknown>[]; subject?: string; trackers?: string[] }): Promise<Record<string, unknown>> {
  const { data } = await api.post('/defi/analyze', payload)
  return data
}

// ── F7: Entity investigation (multi-address) ─────────────────────────────────
export async function investigateEntity(payload: { addresses: string[]; chain?: string }, timeoutMs = 180_000): Promise<EntityInvestigationResult> {
  const { data } = await api.post('/entity/investigate', payload, { timeout: timeoutMs })
  return data
}

// ── F8: Time-travel (historical state) ───────────────────────────────────────
export async function reconstructAtTime(payload: { tx_list: Record<string, unknown>[]; address: string; chain?: string; target_date?: string; target_timestamp?: number }): Promise<TimeTravelResult> {
  const { data } = await api.post('/timetravel/reconstruct', payload)
  return data
}
export async function timelineEvolution(payload: { tx_list: Record<string, unknown>[]; address: string; chain?: string; intervals?: number }): Promise<{ points: TimeTravelPoint[] }> {
  const { data } = await api.post('/timetravel/evolution', payload)
  return data
}

// ── F9: Deep chain fetchers (BTC UTXO + Solana SPL) ──────────────────────────
export async function deepTraceBtc(address: string, hops = 3): Promise<DeepTraceResult> {
  const { data } = await api.get(`/deeptrace/btc/${address}`, { params: { hops }, timeout: 120_000 })
  return data
}
export async function deepTraceSol(address: string): Promise<DeepTraceResult> {
  const { data } = await api.get(`/deeptrace/sol/${address}`, { timeout: 120_000 })
  return data
}

// ── F10: Case QA (AI RAG) ────────────────────────────────────────────────────
export async function askCaseQuestion(caseId: string, question: string): Promise<CaseQaResult> {
  const { data } = await api.post(`/case-qa/${caseId}/ask`, { question }, { timeout: 120_000 })
  return data
}

// ── F11: Chain-of-custody audit ──────────────────────────────────────────────
export async function custodyReport(caseId: string): Promise<CustodyReport> {
  const { data } = await api.get(`/custody/${caseId}`)
  return data
}
export function custodyReportHtmlUrl(caseId: string): string {
  return `/api/custody/${caseId}/html`
}

// ── F12: Collaboration presence ──────────────────────────────────────────────
export async function joinCollabRoom(roomId: string): Promise<{ joined: string; presence: CollabPresence[] }> {
  const { data } = await api.post('/collaboration/join', { room_id: roomId })
  return data
}
export async function collabHeartbeat(roomId: string, cursor?: Record<string, unknown>, panel?: string): Promise<{ presence: CollabPresence[] }> {
  const { data } = await api.post('/collaboration/heartbeat', { room_id: roomId, cursor, panel })
  return data
}
export async function leaveCollabRoom(roomId: string): Promise<{ left: string }> {
  const { data } = await api.post('/collaboration/leave', { room_id: roomId })
  return data
}
export async function listCollabRooms(): Promise<{ rooms: Record<string, CollabPresence[]> }> {
  const { data } = await api.get('/collaboration/rooms')
  return data
}
export async function acquireCaseLock(caseId: string): Promise<{ acquired: boolean; held_by?: string }> {
  const { data } = await api.post('/collaboration/lock', { case_id: caseId })
  return data
}
export async function releaseCaseLock(caseId: string): Promise<{ released: boolean }> {
  const { data } = await api.post('/collaboration/unlock', { case_id: caseId })
  return data
}

// ── F14: Public victim portal (no auth) ──────────────────────────────────────
export async function publicVictimReport(payload: {
  scam_type: string; scammer_address: string; victim_address?: string; amount_usd?: number;
  token?: string; chain?: string; incident_date?: string; description?: string;
  contact_name?: string; contact_email?: string; jurisdiction?: string; tx_hashes?: string[];
}): Promise<{ report_id: string; status: string; linked_case_id?: string; message: string }> {
  const { data } = await api.post('/portal/victim-report', payload)
  return data
}
export async function publicScamStats(): Promise<{ total_reports: number; total_damage_usd: number; top_scam_types: { type: string; count: number }[]; scam_types: string[] }> {
  const { data } = await api.get('/portal/scam-stats')
  return data
}

// ════════════════════════════════════════════════════════════════════════════
// 2026 Enhancement Domains (additive) — Contract Forensics (A), Laundering (B),
// Court Readiness / Daubert (C), Recovery Ops (D).
// ════════════════════════════════════════════════════════════════════════════

// ── Domain A: Smart-contract forensics ──
export async function scanContract(payload: {
  address?: string; chain?: string; bytecode?: string; source?: string;
  abi_selectors?: string[]; verified?: boolean | null
}): Promise<any> {
  const { data } = await api.post('/contract/scan', payload)
  return data
}
export async function fingerprintContract(bytecode: string): Promise<any> {
  const { data } = await api.post('/contract/fingerprint', { bytecode })
  return data
}
export async function compareContracts(payload: {
  bytecode: string; other_bytecode?: string; library?: any[]; threshold?: number; top_k?: number
}): Promise<any> {
  const { data } = await api.post('/contract/compare', payload)
  return data
}
export async function reconstructIncident(payload: {
  txs: any[]; contract?: string; attacker?: string
}): Promise<any> {
  const { data } = await api.post('/contract/incident', payload)
  return data
}
export async function approvalExposure(payload: {
  approvals: any[]; malicious_spenders?: string[]
}): Promise<any> {
  const { data } = await api.post('/contract/approvals', payload)
  return data
}

// ── Domain B: Modern laundering & tracing ──
export async function detectPoisoning(payload: {
  subject: string; transfers: any[]; edge?: number
}): Promise<any> {
  const { data } = await api.post('/laundering/poisoning', payload)
  return data
}
export async function swapTrace(payload: {
  subject: string; transfers: any[]; candidate_outputs?: any[];
  value_tolerance?: number; time_window_seconds?: number
}): Promise<any> {
  const { data } = await api.post('/laundering/swap-trace', payload)
  return data
}
export async function launderingTypologies(payload: {
  subject: string; transfers: any[]
}): Promise<any> {
  const { data } = await api.post('/laundering/typologies', payload)
  return data
}
export async function launderingServices(): Promise<any> {
  const { data } = await api.get('/laundering/services')
  return data
}

// ── Domain C: Court readiness / Daubert ──
export async function daubertMethods(): Promise<any> {
  const { data } = await api.get('/daubert/methods')
  return data
}
export async function buildDaubertDossier(payload: {
  case_ref: string; methods_used: string[]; analyst?: string; subject?: string; findings?: any[]
}): Promise<any> {
  const { data } = await api.post('/daubert/dossier', payload)
  return data
}
export async function notarizeExhibit(payload: {
  payload: any; prev_hash?: string; label?: string
}): Promise<any> {
  const { data } = await api.post('/daubert/notarize', payload)
  return data
}
export async function verifyNotarizationChain(records: any[]): Promise<any> {
  const { data } = await api.post('/daubert/verify-chain', { records })
  return data
}

// ── Domain D: Recovery ops ──
export async function recoveryRoute(asset: string, chain = '', vasp_name = ''): Promise<any> {
  const { data } = await api.get('/recovery/route', { params: { asset, chain, vasp_name } })
  return data
}
export async function previewFreezeRequest(payload: Record<string, unknown>): Promise<any> {
  const { data } = await api.post('/recovery/preview', payload)
  return data
}
export async function createFreezeRequest(payload: Record<string, unknown>): Promise<any> {
  const { data } = await api.post('/recovery/requests', payload)
  return data
}
export async function listFreezeRequests(case_id = '', status = ''): Promise<any> {
  const { data } = await api.get('/recovery/requests', { params: { case_id, status } })
  return data
}
export async function setFreezeStatus(id: string, payload: { status: string; note?: string; by?: string }): Promise<any> {
  const { data } = await api.post(`/recovery/requests/${id}/status`, payload)
  return data
}
export async function recoverySummary(): Promise<any> {
  const { data } = await api.get('/recovery/summary')
  return data
}

// ════════════════════════════════════════════════════════════════════════════
// Case-native AI Investigator (Recommendation D3)
// ════════════════════════════════════════════════════════════════════════════
export interface AgentCaseBrief {
  id: string; name: string; status: string; description: string
  created_at: string; updated_at: string
  address_count: number; note_count: number; evidence_count: number; max_risk: number
}
export interface AgentBriefing {
  case: { id: string; name: string; status: string; description: string }
  stats: { addresses: number; evidence: number; notes: number; max_risk: number }
  addresses: { address: string; chain: string; risk_score: number | null; risk_level: string; label: string }[]
  suggested_prompts: string[]
  actions: { id: string; label: string; description: string; icon: string }[]
  ai_configured: boolean
  welcome: string
}
export interface AgentChatResult {
  answer: string
  citations: { evidence_id: string; valid: boolean }[]
  context_used?: { addresses: number; evidence_retrieved: number; notes: number }
  ai_used: boolean
  followups: string[]
  disclaimer?: string
}
export async function agentStatus(): Promise<{ configured: boolean; provider: any }> {
  const { data } = await api.get('/agent/status'); return data
}
export async function agentListCases(): Promise<{ cases: AgentCaseBrief[] }> {
  const { data } = await api.get('/agent/cases'); return data
}
export async function agentBriefing(caseId: string): Promise<AgentBriefing> {
  const { data } = await api.get(`/agent/case/${caseId}/briefing`); return data
}
export async function agentChat(caseId: string, messages: { role: string; content: string }[]): Promise<AgentChatResult> {
  const { data } = await api.post(`/agent/case/${caseId}/chat`, { messages }, { timeout: 180_000 }); return data
}
export async function agentAction(caseId: string, query_type: string, free_text = ''): Promise<any> {
  const { data } = await api.post(`/agent/case/${caseId}/action`, { query_type, free_text }, { timeout: 180_000 }); return data
}

// ── Deep trace with live progress (Server-Sent Events over POST) ──────────────
export interface DeepProgress { pct: number; label: string; detail: string }
/**
 * Streams deep-analysis progress. Calls `onProgress` as each phase runs and
 * resolves with the final {trace, graph}. Throws on a server error event.
 * If the transport never starts (SSE blocked), the caller may fall back to
 * the non-streaming traceDeepAddress().
 */
export async function traceDeepStream(
  params: { address: string; hops: number; mode: 'linear' | 'wide'; direction: 'out' | 'in' | 'both'; timeout_seconds?: number },
  onProgress: (p: DeepProgress) => void,
  signal?: AbortSignal,
): Promise<TraceResult> {
  const token = sessionStorage.getItem(AUTH_TOKEN_KEY)
  const resp = await fetch('/api/trace/deep/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(params),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const txt = await resp.text().catch(() => '')
    throw new Error(txt || `HTTP ${resp.status}`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let result: TraceResult | null = null
  let errDetail = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    for (const part of parts) {
      const dataLine = part.split('\n').find(l => l.startsWith('data:'))
      if (!dataLine) continue
      const jsonStr = dataLine.slice(5).trim()
      if (!jsonStr) continue
      let evt: any
      try { evt = JSON.parse(jsonStr) } catch { continue }
      if (evt.type === 'progress') onProgress({ pct: evt.pct ?? 0, label: evt.label ?? '', detail: evt.detail ?? '' })
      else if (evt.type === 'result') result = { trace: evt.trace, graph: evt.graph } as unknown as TraceResult
      else if (evt.type === 'error') errDetail = evt.detail || 'Deep analysis failed'
    }
  }
  if (errDetail) throw new Error(errDetail)
  if (!result) throw new Error('Deep analysis stream ended without a result')
  return result
}

// ════════════════════════════════════════════════════════════════════════════
// Next-Horizon 2026-07: Comply / Freeze Network / Scam Atlas / Perp DEX
// ════════════════════════════════════════════════════════════════════════════

// ── 3.1 Stablecoin compliance suite ──
export async function complyCreateProgram(payload: Record<string, unknown>): Promise<any> {
  const { data } = await api.post('/comply/programs', payload)
  return data
}
export async function complyListPrograms(): Promise<any> {
  const { data } = await api.get('/comply/programs')
  return data
}
export async function complyGetProgram(pid: string): Promise<any> {
  const { data } = await api.get(`/comply/programs/${pid}`)
  return data
}
export async function complyDeleteProgram(pid: string): Promise<any> {
  const { data } = await api.delete(`/comply/programs/${pid}`)
  return data
}
export async function complyAddAddresses(pid: string, entries: Record<string, unknown>[], actor = ''): Promise<any> {
  const { data } = await api.post(`/comply/programs/${pid}/addresses`, { entries, actor })
  return data
}
export async function complyListAddresses(pid: string): Promise<any> {
  const { data } = await api.get(`/comply/programs/${pid}/addresses`)
  return data
}
export async function complyRemoveAddress(pid: string, aid: string): Promise<any> {
  const { data } = await api.delete(`/comply/programs/${pid}/addresses/${aid}`)
  return data
}
export async function complyRunScreening(pid: string, actor = ''): Promise<any> {
  const { data } = await api.post(`/comply/programs/${pid}/screen`, { actor })
  return data
}
export async function complyListScreenings(pid: string): Promise<any> {
  const { data } = await api.get(`/comply/programs/${pid}/screenings`)
  return data
}
export async function complyGetScreening(sid: string): Promise<any> {
  const { data } = await api.get(`/comply/screenings/${sid}`)
  return data
}
export async function complyEvaluateTransfers(pid: string, transfers: Record<string, unknown>[], actor = ''): Promise<any> {
  const { data } = await api.post(`/comply/programs/${pid}/transfers`, { transfers, actor })
  return data
}
export async function complyReport(pid: string): Promise<any> {
  const { data } = await api.get(`/comply/programs/${pid}/report`)
  return data
}
export async function complyAuditLog(pid: string): Promise<any> {
  const { data } = await api.get(`/comply/programs/${pid}/audit`)
  return data
}

// ── 3.2 Freeze-network operationalization ──
export async function freezeNetDirectory(asset = '', target_type = ''): Promise<any> {
  const { data } = await api.get('/freeze-net/directory', { params: { asset, target_type } })
  return data
}
export async function freezeNetAddWatch(payload: Record<string, unknown>): Promise<any> {
  const { data } = await api.post('/freeze-net/watches', payload)
  return data
}
export async function freezeNetListWatches(case_id = '', status = ''): Promise<any> {
  const { data } = await api.get('/freeze-net/watches', { params: { case_id, status } })
  return data
}
export async function freezeNetSetWatchStatus(wid: string, status: string): Promise<any> {
  const { data } = await api.post(`/freeze-net/watches/${wid}/status`, { status })
  return data
}
export async function freezeNetDeleteWatch(wid: string): Promise<any> {
  const { data } = await api.delete(`/freeze-net/watches/${wid}`)
  return data
}
export async function freezeNetEvaluate(wid: string, payload: Record<string, unknown>): Promise<any> {
  const { data } = await api.post(`/freeze-net/watches/${wid}/evaluate`, payload)
  return data
}
export async function freezeNetScan(): Promise<any> {
  const { data } = await api.post('/freeze-net/scan')
  return data
}
export async function freezeNetEvents(watch_id = ''): Promise<any> {
  const { data } = await api.get('/freeze-net/events', { params: { watch_id } })
  return data
}
export async function freezeNetKpis(): Promise<any> {
  const { data } = await api.get('/freeze-net/kpis')
  return data
}

// ── 3.3 Scam Network Atlas ──
export async function scamAtlas(rebuild = false): Promise<any> {
  const { data } = await api.get('/scam-infra/atlas', { params: { rebuild } })
  return data
}
export async function scamAtlasSummary(): Promise<any> {
  const { data } = await api.get('/scam-infra/summary')
  return data
}
export async function scamNetworkDetail(nid: string): Promise<any> {
  const { data } = await api.get(`/scam-infra/networks/${nid}`)
  return data
}
export async function scamNetworkPromote(nid: string, assigned_by = 'scam-atlas'): Promise<any> {
  const { data } = await api.post(`/scam-infra/networks/${nid}/promote`, { assigned_by })
  return data
}

// ── 3.4 Perp DEX / Hyperliquid ──
export async function perpDexAnalyze(address: string): Promise<any> {
  const { data } = await api.get(`/perp-dex/hyperliquid/${address}`)
  return data
}

// ── Spot prices (home Market Pulse) ──
export async function getSpotPrice(asset: string): Promise<{ asset: string; usd: number | null; source?: string }> {
  const { data } = await api.get('/prices/spot', { params: { asset } })
  return data
}
