import axios from 'axios'
import { AUTH_TOKEN_KEY } from './client'

// Self-contained API module for the Predictive Intelligence engine + shared insights layer.
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

export type PredictionType = 'laundering' | 'rugpull' | 'trajectory' | 'victim' | 'all'

export interface PredictionEvidence { weight: number; severity: string; finding: string }
export interface AnomalyOutlier { feature: string; z: number; note: string }
export interface AnomalyReport {
  anomaly_score: number
  population_n: number
  z_scores: Record<string, number>
  outliers: AnomalyOutlier[]
}
export interface Prediction {
  type: string
  address: string
  chain: string
  probability: number
  level: string
  confidence: number
  horizon: string
  trend?: string
  horizons?: Record<string, number>
  layer_scores: { precursor_patterns: number; anomaly: number; ml_model: number | null }
  blend_weights: Record<string, number>
  evidence: PredictionEvidence[]
  anomaly: AnomalyReport
  recommended_actions: string[]
}
export interface PredictAllResult {
  address: string
  chain: string
  composite_threat: number
  composite_level: string
  primary_threat: string
  primary_horizon: string
  predictions: Record<string, Prediction>
  model: ModelStatus
  generated_at: string
  methodology: string
}
export interface ModelStatus {
  sklearn_available: boolean
  models: { name: string; samples: number; positives: number; accuracy: number; engine: string; trained_at: string }[]
  baseline_features: number
  feature_vectors: number
  recent_predictions?: number
}
export interface TrainResult {
  trained: boolean
  samples: number
  positives: number
  accuracy?: number
  engine?: string
  reason?: string
}
export interface PredictionHistoryRow {
  address: string; chain: string; ptype: string; probability: number
  level: string; horizon: string; created_at: string
}

export interface Insight { severity: string; title: string; detail: string; action: string; tag: string }
export interface PercentileRow { metric: string; value: number; percentile: number; population: number }
export interface InsightResponse {
  context: string
  address: string
  insights: Insight[]
  percentiles?: PercentileRow[]
  anomaly?: { score: number; outliers: AnomalyOutlier[] }
  predictions?: {
    laundering?: { probability: number; level: string; horizon: string }
    trajectory?: { probability: number; level: string; trend?: string; horizons?: Record<string, number> }
  }
}

export async function runPrediction(address: string, chain = '', type: PredictionType = 'all', intel?: unknown) {
  const { data } = await api.post('/predict', { address, chain, type, intel })
  return data as PredictAllResult | Prediction
}

export async function runPredictAll(address: string, chain = '', intel?: unknown): Promise<PredictAllResult> {
  const { data } = await api.post('/predict', { address, chain, type: 'all', intel })
  return data as PredictAllResult
}

export async function getModelStatus(): Promise<ModelStatus> {
  const { data } = await api.get('/predict/status')
  return data as ModelStatus
}

export async function trainModels(): Promise<TrainResult> {
  const { data } = await api.post('/predict/train')
  return data as TrainResult
}

export async function rebuildBaselines(): Promise<{ population: number; features: number }> {
  const { data } = await api.post('/predict/baselines')
  return data
}

export async function getPredictionHistory(address = '', limit = 50): Promise<PredictionHistoryRow[]> {
  const { data } = await api.get('/predict/history', { params: { address, limit } })
  return data as PredictionHistoryRow[]
}

export async function fetchInsights(
  context: string,
  address = '',
  chain = '',
  data?: Record<string, unknown>,
  includePredictions = true,
): Promise<InsightResponse> {
  const res = await api.post('/insights', {
    context, address, chain, data: data ?? {}, include_predictions: includePredictions,
  })
  return res.data as InsightResponse
}
