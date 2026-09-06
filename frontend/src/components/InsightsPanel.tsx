import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertOctagon, AlertTriangle, BrainCircuit, ChevronDown, ChevronUp,
  Info, Lightbulb, Loader2, RefreshCw, TrendingUp,
} from 'lucide-react'
import { fetchInsights } from '../api/predictive'
import type { Insight, InsightResponse } from '../api/predictive'

const SEV_STYLES: Record<string, { border: string; text: string; Icon: typeof Info }> = {
  critical: { border: 'border-red-500/60', text: 'text-red-400', Icon: AlertOctagon },
  high: { border: 'border-orange-500/50', text: 'text-orange-400', Icon: AlertTriangle },
  medium: { border: 'border-yellow-500/40', text: 'text-yellow-400', Icon: AlertTriangle },
  low: { border: 'border-blue-500/30', text: 'text-blue-400', Icon: Info },
  info: { border: 'border-border', text: 'text-text-muted', Icon: Info },
}

function levelColor(level?: string) {
  switch ((level || '').toUpperCase()) {
    case 'CRITICAL': return 'text-red-400'
    case 'HIGH': return 'text-orange-400'
    case 'ELEVATED': return 'text-yellow-400'
    case 'GUARDED': return 'text-blue-400'
    default: return 'text-emerald-400'
  }
}

function InsightRow({ insight }: { insight: Insight }) {
  const [open, setOpen] = useState(false)
  const s = SEV_STYLES[insight.severity] || SEV_STYLES.info
  const { Icon } = s
  return (
    <div className={`border-l-2 ${s.border} bg-bg-secondary/60 rounded-r-md px-3 py-2`}>
      <button className="w-full flex items-start gap-2 text-left" onClick={() => setOpen(!open)}>
        <Icon size={14} className={`${s.text} mt-0.5 shrink-0`} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-text-primary leading-snug">{insight.title}</p>
          {!open && <p className="text-[11px] text-text-muted truncate">{insight.detail}</p>}
        </div>
        {open ? <ChevronUp size={13} className="text-text-muted mt-0.5" /> : <ChevronDown size={13} className="text-text-muted mt-0.5" />}
      </button>
      {open && (
        <div className="mt-1.5 pl-6 space-y-1.5">
          <p className="text-[11px] text-text-secondary leading-relaxed">{insight.detail}</p>
          {insight.action && (
            <p className="text-[11px] text-accent flex items-start gap-1.5">
              <Lightbulb size={12} className="mt-0.5 shrink-0" />
              <span>{insight.action}</span>
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export interface InsightsPanelProps {
  context: 'address' | 'trace' | 'dex' | 'case' | 'monitor' | 'dashboard'
  address?: string
  chain?: string
  /** context payload the screen already has (intel, graph, swaps, watches, case_id…) */
  data?: Record<string, unknown>
  /** re-fetch when this changes (e.g. after a search completes) */
  refreshKey?: string | number
  compact?: boolean
  className?: string
}

/**
 * Reusable "Investigator Insights" panel — the shared analytics layer.
 * Drop into any screen; it fetches context-aware insights, anomaly stats,
 * population percentiles and a condensed pre-crime outlook.
 */
export default function InsightsPanel({
  context, address = '', chain = '', data, refreshKey, compact = false, className = '',
}: InsightsPanelProps) {
  const { t } = useTranslation()
  const [res, setRes] = useState<InsightResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const r = await fetchInsights(context, address, chain, data, !compact)
      setRes(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'insight fetch failed')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [context, address, chain, refreshKey])

  useEffect(() => { void load() }, [load])

  const pred = res?.predictions

  return (
    <div className={`bg-bg-primary border border-border rounded-lg ${className}`}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2">
          <BrainCircuit size={15} className="text-accent" />
          <h3 className="text-xs font-bold uppercase tracking-widest text-text-primary">{t('components:shared.insights.title')}</h3>
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          className="text-text-muted hover:text-text-primary transition-colors"
          title={t('components:shared.insights.refresh')}
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
        </button>
      </div>

      <div className="p-3 space-y-2">
        {error && <p className="text-[11px] text-red-400">{error}</p>}
        {!res && loading && <p className="text-[11px] text-text-muted">{t('components:shared.insights.analyzing')}</p>}

        {pred && (pred.laundering || pred.trajectory) && (
          <div className="grid grid-cols-2 gap-2">
            {pred.laundering && (
              <div className="bg-bg-secondary border border-border rounded-md px-2.5 py-2">
                <p className="text-[9px] uppercase tracking-widest text-text-muted">{t('components:shared.insights.cashoutRisk')}</p>
                <p className={`text-base font-bold font-mono ${levelColor(pred.laundering.level)}`}>
                  {Math.round(pred.laundering.probability * 100)}%
                </p>
                <p className="text-[10px] text-text-muted truncate">window: {pred.laundering.horizon}</p>
              </div>
            )}
            {pred.trajectory && (
              <div className="bg-bg-secondary border border-border rounded-md px-2.5 py-2">
                <p className="text-[9px] uppercase tracking-widest text-text-muted flex items-center gap-1">
                  <TrendingUp size={10} /> {t('components:shared.insights.riskTrajectory')}
                </p>
                <p className={`text-base font-bold font-mono ${levelColor(pred.trajectory.level)}`}>
                  {Math.round(pred.trajectory.probability * 100)}%
                </p>
                <p className="text-[10px] text-text-muted truncate">
                  {pred.trajectory.trend || 'stable'}
                  {pred.trajectory.horizons ? ` · 7d ${Math.round((pred.trajectory.horizons['7d'] || 0) * 100)}%` : ''}
                </p>
              </div>
            )}
          </div>
        )}

        {res?.insights?.map((it, i) => <InsightRow key={`${it.title}-${i}`} insight={it} />)}

        {!compact && res?.percentiles && res.percentiles.length > 0 && (
          <div className="pt-1">
            <p className="text-[9px] uppercase tracking-widest text-text-muted mb-1.5">
              {t('components:shared.insights.vsPopulation')} ({res.percentiles[0].population} {t('components:shared.insights.addresses')})
            </p>
            <div className="space-y-1">
              {res.percentiles.slice(0, 4).map((p) => (
                <div key={p.metric} className="flex items-center gap-2">
                  <span className="text-[10px] text-text-muted w-40 truncate shrink-0">{p.metric}</span>
                  <div className="flex-1 h-1.5 bg-bg-secondary rounded overflow-hidden">
                    <div
                      className={`h-full rounded ${p.percentile > 90 ? 'bg-red-500' : p.percentile > 70 ? 'bg-orange-500' : 'bg-accent'}`}
                      style={{ width: `${Math.max(2, p.percentile)}%` }}
                    />
                  </div>
                  <span className="text-[10px] font-mono text-text-secondary w-10 text-right">
                    p{Math.round(p.percentile)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
