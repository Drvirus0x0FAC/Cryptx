import axios from 'axios'
import { AUTH_TOKEN_KEY } from './client'

// Self-contained API module for the deterministic attribution engine.
const api = axios.create({ baseURL: '/api', timeout: 60_000, headers: { 'Content-Type': 'application/json' } })

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

export interface EvidenceItem { type: string; value: string; ref: string }

export interface Attribution {
  id: string
  category: string
  actor: string
  label: string
  source: string
  method: string
  method_class: 'deterministic' | 'analyst' | 'heuristic' | string
  confidence: number
  evidence: EvidenceItem[]
  assigned_by: string
  assigned_at: string
}

export interface AttributionResult {
  address: string
  chain: string
  attribution_count: number
  court_defensible: boolean
  court_defensible_reason: string
  primary: Attribution | null
  overall_confidence: number
  categories: string[]
  actors: string[]
  attributions: Attribution[]
  checked_at: string
  disclaimer: string
}

export interface MethodsCatalog {
  method_classes: Array<{ class: string; description: string; confidence: string }>
  deterministic_sources: string[]
  categories: string[]
  court_confidence_threshold: number
}

export interface AuditRecord extends Record<string, unknown> {
  id: string
  address: string
  category: string
  source: string
  method_class: string
  confidence: number
  assigned_by: string
  assigned_at: string
  valid: number
  evidence: EvidenceItem[]
}

export async function getAttribution(address: string, chain?: string): Promise<AttributionResult> {
  const { data } = await api.get<AttributionResult>(`/attribution/${encodeURIComponent(address)}`, { params: chain ? { chain } : undefined })
  return data
}

export async function attributionAudit(address: string): Promise<{ address: string; records: AuditRecord[]; count: number }> {
  const { data } = await api.get(`/attribution/${encodeURIComponent(address)}/audit`)
  return data
}

export async function attributionMethods(): Promise<MethodsCatalog> {
  const { data } = await api.get<MethodsCatalog>('/attribution/methods')
  return data
}

export async function addAttribution(payload: {
  address: string
  category: string
  actor?: string
  label?: string
  source?: string
  confidence?: number
  evidence?: EvidenceItem[]
  chain?: string
  assigned_by?: string
  note?: string
}): Promise<AttributionResult & { id: string }> {
  const { data } = await api.post('/attribution', payload)
  return data
}

export async function revokeAttribution(id: string): Promise<{ revoked: boolean; id: string }> {
  const { data } = await api.post(`/attribution/revoke/${encodeURIComponent(id)}`)
  return data
}
