import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { BarChart2, Search, Loader2, AlertCircle, ArrowDownLeft, ArrowUpRight } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { fetchDex } from '../api/client'
import type { DexResult, DexSwap } from '../types'
import { useFormat } from '../i18n/format'
import CinematicStage from '../components/CinematicStage'

const BUY_COLOR  = '#22c55e'
const SELL_COLOR = '#ef4444'

function SwapRow({ swap, fmtUsd }: { swap: DexSwap; fmtUsd: (n: number) => string }) {
  const isBuy = swap.direction === 'buy'
  return (
    <tr className="border-b border-border/50 hover:bg-bg-tertiary/50">
      <td className="py-1.5 pr-3">
        {isBuy ? (
          <ArrowDownLeft size={12} className="text-risk-clean" />
        ) : (
          <ArrowUpRight size={12} className="text-risk-mixer" />
        )}
      </td>
      <td className="py-1.5 pr-3 text-text-muted text-xs whitespace-nowrap">
        {swap.time ? swap.time.slice(0, 19) : '-'}
      </td>
      <td className="py-1.5 pr-3 text-xs">
        <span className="text-text-primary font-semibold">{swap.token0_symbol}</span>
        <span className="text-text-muted mx-1">→</span>
        <span className="text-text-primary font-semibold">{swap.token1_symbol}</span>
      </td>
      <td className="py-1.5 pr-3 font-mono text-xs text-text-secondary">
        {Number(swap.amount0).toLocaleString(undefined, { maximumFractionDigits: 6 })}
        {' → '}
        {Number(swap.amount1).toLocaleString(undefined, { maximumFractionDigits: 6 })}
      </td>
      <td className="py-1.5 pr-3 text-xs text-text-muted">{swap.dex}</td>
      <td className="py-1.5 text-right text-xs font-mono text-text-primary">
        {swap.usd_value != null ? fmtUsd(Number(swap.usd_value)) : '-'}
      </td>
    </tr>
  )
}

export default function DexAnalysis() {
  const { t } = useTranslation()
  const { formatCurrency } = useFormat()
  const { addr } = useParams<{ addr: string }>()
  const navigate  = useNavigate()
  const [input, setInput]   = useState(addr ?? '')
  const [target, setTarget] = useState(addr ?? '')

  useEffect(() => {
    if (addr) { setTarget(addr); setInput(addr) }
  }, [addr])

  const { data, isFetching, error } = useQuery<DexResult>({
    queryKey: ['dex', target],
    queryFn: () => fetchDex(target),
    enabled: !!target,
    retry: false,
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const q = input.trim()
    if (!q) return
    navigate(`/dex/${encodeURIComponent(q)}`)
    setTarget(q)
  }

  const swaps: DexSwap[] = data?.activity?.swaps ?? []
  const analysis = data?.analysis

  // Build chart data
  const tokenCounts: Record<string, { buys: number; sells: number }> = {}
  for (const s of swaps) {
    const key = `${s.token0_symbol}/${s.token1_symbol}`
    if (!tokenCounts[key]) tokenCounts[key] = { buys: 0, sells: 0 }
    if (s.direction === 'buy') tokenCounts[key].buys++
    else tokenCounts[key].sells++
  }
  const chartData = Object.entries(tokenCounts)
    .sort((a, b) => (b[1].buys + b[1].sells) - (a[1].buys + a[1].sells))
    .slice(0, 10)
    .map(([pair, counts]) => ({ pair, ...counts }))

  const fmtUsd = (n: number) => formatCurrency(n)

  return (
    <div className="noscroll-page p-6 max-w-6xl mx-auto space-y-5">
      {/* Search */}
      <CinematicStage
        variant="dex"
        icon={BarChart2}
        kicker={t('tools:dex.title')}
        title={t('tools:dex.title')}
        onSubmit={handleSubmit}
        collapsed={!!target}
      >
        <div className="flex gap-2 flex-wrap">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            className="input pl-9"
            placeholder={t('tools:dex.inputPlaceholder')}
            value={input}
            onChange={e => setInput(e.target.value)}
          />
        </div>
        <button type="submit" className="btn-primary" disabled={isFetching}>
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <BarChart2 size={14} />}
          {t('tools:dex.analyze')}
        </button>
        </div>
      </CinematicStage>

      {/* Results — grows & scrolls internally */}
      <div className="noscroll-grow space-y-5">
      {/* Error */}
      {error && (
        <div className="card border-risk-mixer/50 flex items-start gap-3">
          <AlertCircle className="text-risk-mixer shrink-0" size={18} />
          <div>
            <p className="text-sm font-semibold text-risk-mixer">{t('tools:dex.lookupFailed')}</p>
            <p className="text-xs text-text-muted mt-1">
              {error instanceof Error ? error.message : String(error)}
            </p>
          </div>
        </div>
      )}

      {isFetching && (
        <div className="flex items-center justify-center py-16">
          <div className="text-center space-y-3">
            <Loader2 className="animate-spin text-accent-cyan mx-auto" size={32} />
            <p className="text-text-secondary text-sm">{t('tools:dex.loading')}</p>
          </div>
        </div>
      )}

      {data && !isFetching && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: t('tools:dex.stats.totalSwaps'),  val: analysis?.total_swaps ?? swaps.length },
              { label: t('tools:dex.stats.buys'),         val: analysis?.buy_count ?? swaps.filter(s => s.direction === 'buy').length },
              { label: t('tools:dex.stats.sells'),        val: analysis?.sell_count ?? swaps.filter(s => s.direction === 'sell').length },
              { label: t('tools:dex.stats.uniquePairs'),  val: analysis?.unique_tokens ?? Object.keys(tokenCounts).length },
            ].map(({ label, val }) => (
              <div key={label} className="bg-bg-tertiary border border-border rounded-lg p-3 text-center">
                <p className="text-[10px] text-text-muted uppercase tracking-widest">{label}</p>
                <p className="text-2xl font-bold text-text-primary font-mono">{val}</p>
              </div>
            ))}
          </div>

          {/* Wash trading alert */}
          {analysis?.possible_wash_trading && (
            <div className="card border-risk-medium/50 bg-risk-medium/5">
              <p className="text-sm font-semibold text-risk-medium mb-1">
                {t('tools:dex.washTrading.title')}
              </p>
              {(analysis.wash_trading_evidence ?? []).map((ev: string, i: number) => (
                <p key={i} className="text-xs text-text-muted">{ev}</p>
              ))}
            </div>
          )}

          {/* Chart */}
          {chartData.length > 0 && (
            <div className="card">
              <p className="card-title">{t('tools:dex.chart.title')}</p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={chartData} barGap={2} barCategoryGap="30%">
                  <XAxis
                    dataKey="pair"
                    tick={{ fill: '#b0929a', fontSize: 11 }}
                    axisLine={{ stroke: '#2a1620' }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: '#b0929a', fontSize: 11 }}
                    axisLine={{ stroke: '#2a1620' }}
                    tickLine={false}
                    width={28}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#120a0e', border: '1px solid #2a1620',
                      borderRadius: 8, color: '#e2eaf8', fontSize: 12,
                    }}
                  />
                  <Bar dataKey="buys" name={t('tools:dex.chart.buys')} fill={BUY_COLOR} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="sells" name={t('tools:dex.chart.sells')} fill={SELL_COLOR} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Swap table */}
          {swaps.length > 0 ? (
            <div className="card">
              <p className="card-title">{t('tools:dex.table.historyTitle', { count: swaps.length })}</p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border text-text-secondary">
                      <th className="text-left pb-2 pr-3">{t('tools:dex.table.colDir')}</th>
                      <th className="text-left pb-2 pr-3">{t('tools:dex.table.colTime')}</th>
                      <th className="text-left pb-2 pr-3">{t('tools:dex.table.colPair')}</th>
                      <th className="text-left pb-2 pr-3">{t('tools:dex.table.colAmounts')}</th>
                      <th className="text-left pb-2 pr-3">{t('tools:dex.table.colDex')}</th>
                      <th className="text-right pb-2">{t('tools:dex.table.colUsd')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {swaps.slice(0, 50).map((s, i) => (
                      <SwapRow key={i} swap={s} fmtUsd={fmtUsd} />
                    ))}
                  </tbody>
                </table>
                {swaps.length > 50 && (
                  <p className="text-xs text-text-muted mt-2">{t('tools:dex.table.showing', { count: swaps.length })}</p>
                )}
              </div>
            </div>
          ) : (
            <div className="card">
              <p className="text-text-muted text-sm">{t('tools:dex.noSwaps')}</p>
              <p className="text-text-muted text-xs mt-1">
                {t('tools:dex.noSwapsHint')}
              </p>
            </div>
          )}
        </>
      )}

      {!target && !isFetching && (
        <div className="flex items-center justify-center py-16">
          <div className="text-center space-y-2">
            <BarChart2 className="mx-auto text-text-muted" size={40} />
            <p className="text-text-secondary">{t('tools:dex.empty')}</p>
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
