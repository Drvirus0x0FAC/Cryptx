import axios from 'axios'
import { AUTH_TOKEN_KEY } from './client'

// Self-contained API module for counterparty / exchange-usage analytics.
const api = axios.create({ baseURL: '/api', timeout: 120_000, headers: { 'Content-Type': 'application/json' } })

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

export interface ExchangeItem { exchange: string; usd: number; native_label: string; pct: number }
export interface SeriesPoint { t: string; value: number }
export interface Counterparty {
  address: string
  entity: string
  type: string
  sanctioned: boolean
  risk: number
  chains: string[]
  tx: number
  usd: number
  in_usd: number
  out_usd: number
  net_usd: number
  native_label: string
  tokens: string[]
  first_seen: number
  last_seen: number
}
export interface EntityPrediction { label: string; confidence: number; rationale: string }

export interface CounterpartyAnalytics {
  address: string
  chain: string
  window: string
  date_range: { start: number; end: number; days: number }
  totals: { deposit_usd: number; withdrawal_usd: number; tx_count: number; counterparty_count: number }
  exchange_usage: {
    deposits: { total_usd: number; items: ExchangeItem[] }
    withdrawals: { total_usd: number; items: ExchangeItem[] }
    deposit_series: SeriesPoint[]
    withdrawal_series: SeriesPoint[]
  }
  counterparties: Counterparty[]
  entity_predictions: EntityPrediction[]
  errors: string[]
  note: string
  disclaimer: string
  generated_at: number
  error?: string
}

export async function getCounterpartyAnalytics(
  address: string, chain = 'auto', window = 'all',
): Promise<CounterpartyAnalytics> {
  const { data } = await api.get<CounterpartyAnalytics>('/analytics/counterparties', {
    params: { address, chain, window },
  })
  return data
}
