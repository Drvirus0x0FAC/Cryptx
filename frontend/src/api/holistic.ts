import axios from 'axios'
import { AUTH_TOKEN_KEY } from './client'

// Self-contained API module for the Holistic cross-chain trace engine.
const api = axios.create({ baseURL: '/api', timeout: 300_000, headers: { 'Content-Type': 'application/json' } })

// Attach the bearer token on every request (matches the main client's auth).
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

export interface HolisticNode {
  id: string
  address: string
  chain: string
  type: 'subject' | 'exchange' | 'bridge' | 'dex' | 'mixer' | 'sanctioned' | 'contract' | 'unknown' | string
  label: string
  hop: number
  risk: number
  is_terminal: boolean
  sanctioned: boolean
  vasp: string | null
  inflow_value: number
  outflow_value: number
  note: string
}

export interface HolisticEdge {
  source: string
  target: string
  chain: string
  asset: string
  value: number
  value_usd: number
  tx_hash: string
  timestamp: number
  direction: 'in' | 'out'
  kind: 'transfer' | 'bridge' | 'swap' | 'deposit' | string
  hop: number
}

export interface HolisticSummary {
  node_count: number
  edge_count: number
  chains_touched: string[]
  chain_count: number
  bridges_crossed: Array<{ id: string; label: string }>
  bridge_crossing_count: number
  mixers_hit: Array<{ id: string; label: string }>
  exchanges_reached: Array<{ id: string; label: string }>
  cash_out_points: Array<{ id: string; label: string; hop: number; vasp: string | null }>
  sanctioned_hits: Array<{ id: string; label: string }>
  ultimate_destinations: Array<{ id: string; type: string; label: string; hop: number }>
  total_traced_value: number
  risk_score: number
}

export interface HolisticTraceResult {
  subject: string
  subject_chain: string
  config: { max_hops: number; direction: string }
  graph: { nodes: HolisticNode[]; edges: HolisticEdge[] }
  summary: HolisticSummary
  errors: string[]
  disclaimer: string
  source?: string
  note?: string
  generated_at: number
}

export interface HolisticRegistry {
  bridges: Array<{ address: string; name: string; chain: string }>
  dex_routers: Array<{ address: string; name: string; chain: string }>
  mixers: Array<{ address: string; name: string; chain: string }>
  supported_live_chains: string[]
  node_types: string[]
}

export async function holisticTrace(payload: {
  subject: string
  chain?: string
  direction?: 'in' | 'out' | 'both'
  max_hops?: number
  max_nodes?: number
  min_value?: number
}): Promise<HolisticTraceResult> {
  const { data } = await api.post<HolisticTraceResult>('/holistic/trace', payload)
  return data
}

export async function holisticTraceEvents(payload: {
  subject: string
  chain?: string
  direction?: 'in' | 'out' | 'both'
  max_hops?: number
  min_value?: number
  events: Array<Record<string, unknown>>
}): Promise<HolisticTraceResult> {
  const { data } = await api.post<HolisticTraceResult>('/holistic/trace-events', payload)
  return data
}

export async function holisticRegistry(): Promise<HolisticRegistry> {
  const { data } = await api.get<HolisticRegistry>('/holistic/registry')
  return data
}
