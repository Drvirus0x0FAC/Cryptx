import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import {
  Layers, Play, Download, AlertCircle, Loader2,
} from 'lucide-react'
import { batchScreen } from '../api/client'
import CinematicStage from '../components/CinematicStage'
import type { BatchResult, BatchStats } from '../types'

const LEVEL_BADGE: Record<string, string> = {
  SANCTIONED: 'badge-purple',
  CRITICAL:   'badge-red',
  HIGH:       'badge-red',
  MEDIUM:     'badge-amber',
  LOW:        'badge-amber',
  CLEAN:      'badge-green',
  ERROR:      'badge-muted',
}

const LEVEL_SCORE_COLOR: Record<string, string> = {
  SANCTIONED: '#ff5d86',
  CRITICAL:   '#F87171',
  HIGH:       '#F87171',
  MEDIUM:     '#FBBF24',
  LOW:        '#FBBF24',
  CLEAN:      '#34D399',
  ERROR:      '#475569',
}

function StatCard({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <div className="card text-center py-3 px-2">
      <div className="text-display text-2xl font-bold" style={{ color: color ?? '#cdd9f0', textShadow: color ? `0 0 10px ${color}44` : undefined }}>
        {value}
      </div>
      <div className="text-[10px] text-text-muted mt-1 tracking-widest uppercase text-tech">{label}</div>
    </div>
  )
}

export default function BatchScreener() {
  const { t } = useTranslation()
  const [input, setInput]         = useState('')
  const [sortCol, setSortCol]     = useState<'score' | 'address' | 'chain'>('score')
  const [sortDir, setSortDir]     = useState<'desc' | 'asc'>('desc')
  const [filterLevel, setFilter]  = useState<string>('all')

  const mutation = useMutation({
    mutationFn: () => {
      const addrs = input.split(/[\n,;]+/).map((a) => a.trim()).filter(Boolean)
      return batchScreen(addrs)
    },
  })

  const results: BatchResult[] = mutation.data?.results ?? []
  const stats: BatchStats | undefined = mutation.data?.stats

  const sorted = [...results]
    .filter((r) => filterLevel === 'all' || r.risk_level === filterLevel)
    .sort((a, b) => {
      let cmp = 0
      if (sortCol === 'score')   cmp = a.score - b.score
      else if (sortCol === 'address') cmp = a.address.localeCompare(b.address)
      else if (sortCol === 'chain')   cmp = (a.chain || '').localeCompare(b.chain || '')
      return sortDir === 'desc' ? -cmp : cmp
    })

  const handleSort = (col: typeof sortCol) => {
    if (sortCol === col) setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    else { setSortCol(col); setSortDir('desc') }
  }

  const exportCsv = () => {
    if (!results.length) return
    const header = 'Address,Chain,Score,Risk Level,Categories,Error'
    const rows = results.map((r) =>
      `"${r.address}","${r.chain}",${r.score},"${r.risk_level}","${r.categories.join('|')}","${r.error ?? ''}"`
    )
    const blob = new Blob([[header, ...rows].join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `batch-screen-${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const addressCount = input.split(/[\n,;]+/).filter((l) => l.trim()).length

  return (
    <div className="noscroll-page p-6 max-w-6xl mx-auto space-y-6 page-enter">

      {/* Input card */}
      <CinematicStage
        variant="batch"
        icon={Layers}
        collapsed={!!results && results.length > 0}
      >
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <label className="card-title mb-0">{t('tools:batchScreener.inputLabel')}</label>
            <span className="text-[10px] text-tech text-text-muted">
              {t('tools:batchScreener.countLabel', { count: addressCount })}
            </span>
          </div>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={`0xdAC17F958D2ee523a2206206994597C13D831ec7\nbc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh\nT9yD14Nj9j7xAB4dbGeiX9h8UpykdthLx5`}
            rows={7}
            className="input resize-y"
            style={{ minHeight: 140 }}
          />
          <div className="flex gap-3 items-center">
            <button
              onClick={() => mutation.mutate()}
              disabled={!input.trim() || mutation.isPending}
              className="btn-primary"
            >
              {mutation.isPending
                ? <><Loader2 size={14} className="animate-spin" /> {t('tools:batchScreener.screening')}</>
                : <><Play size={14} /> {addressCount > 0 ? t('tools:batchScreener.screenBtn', { count: addressCount }) : t('tools:batchScreener.inputLabel')}</>
              }
            </button>
            <button onClick={() => setInput('')} className="btn-ghost">{t('tools:batchScreener.clear')}</button>
            {results.length > 0 && (
              <button onClick={exportCsv} className="btn-ghost ml-auto">
                <Download size={13} />
                {t('tools:batchScreener.exportCsv')}
              </button>
            )}
            {mutation.isError && (
              <div className="flex items-center gap-2 text-neon-red text-xs">
                <AlertCircle size={13} />
                {t('tools:batchScreener.errors.failed')}
              </div>
            )}
          </div>
        </div>
      </CinematicStage>

      {/* Stats + results — grows & scrolls internally */}
      <div className="noscroll-grow space-y-6">
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-4 lg:grid-cols-8 gap-2">
          <StatCard label={t('tools:batchScreener.stats.total')}      value={stats.total} />
          <StatCard label={t('tools:batchScreener.stats.scored')}     value={stats.scored}     color="#ff5a6e" />
          <StatCard label={t('tools:batchScreener.stats.avg')}        value={stats.avg_score}  />
          <StatCard label={t('tools:batchScreener.stats.max')}        value={stats.max_score}  color={stats.max_score >= 60 ? '#F87171' : undefined} />
          <StatCard label={t('tools:batchScreener.stats.sanctioned')} value={stats.sanctioned} color={stats.sanctioned > 0 ? '#ff5d86' : undefined} />
          <StatCard label={t('tools:batchScreener.stats.critHigh')}   value={stats.critical + stats.high} color={(stats.critical + stats.high) > 0 ? '#F87171' : undefined} />
          <StatCard label={t('tools:batchScreener.stats.medium')}     value={stats.medium}     color={stats.medium > 0 ? '#FBBF24' : undefined} />
          <StatCard label={t('tools:batchScreener.stats.clean')}      value={stats.clean}      color={stats.clean > 0 ? '#34D399' : undefined} />
        </div>
      )}

      {/* Results table */}
      {results.length > 0 && (
        <div className="card overflow-hidden p-0">
          {/* Filter bar */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-bg-border">
            <div className="flex gap-1.5 flex-wrap">
              {(['all', 'SANCTIONED', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'CLEAN'] as const).map((lvl) => {
                const filterKey = lvl === 'all' ? 'all' : lvl.toLowerCase()
                return (
                  <button
                    key={lvl}
                    onClick={() => setFilter(lvl)}
                    className={lvl === filterLevel
                      ? 'badge badge-cyan'
                      : 'badge badge-muted opacity-60 hover:opacity-100'
                    }
                  >
                    {t(`tools:batchScreener.filter.${filterKey}`)}
                  </button>
                )
              })}
            </div>
            <span className="text-[10px] text-text-muted text-tech">{t('tools:batchScreener.rowsCount', { count: sorted.length })}</span>
          </div>

          <div className="scroll-panel-tbl">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="pl-4 cursor-pointer hover:text-text-primary"
                    onClick={() => handleSort('score')}>
                    {t('tools:batchScreener.table.score')} {sortCol === 'score' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th>{t('tools:batchScreener.table.level')}</th>
                  <th className="cursor-pointer hover:text-text-primary"
                    onClick={() => handleSort('address')}>
                    {t('tools:batchScreener.table.address')} {sortCol === 'address' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th className="cursor-pointer hover:text-text-primary"
                    onClick={() => handleSort('chain')}>
                    {t('tools:batchScreener.table.chain')}
                  </th>
                  <th>{t('tools:batchScreener.table.signals')}</th>
                  <th className="pr-4">{t('tools:batchScreener.table.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.address}>
                    <td className="pl-4 py-3">
                      <span className="text-display text-xl font-bold"
                        style={{ color: LEVEL_SCORE_COLOR[r.risk_level] ?? '#98828a',
                                 textShadow: `0 0 8px ${LEVEL_SCORE_COLOR[r.risk_level] ?? '#98828a'}55` }}>
                        {r.score >= 0 ? r.score : '-'}
                      </span>
                    </td>
                    <td className="py-3">
                      <span className={LEVEL_BADGE[r.risk_level] ?? 'badge-muted'}>
                        {r.risk_level}
                      </span>
                    </td>
                    <td className="py-3 max-w-[200px]">
                      <span className="text-tech text-[11px] text-neon-cyan truncate block">{r.address}</span>
                    </td>
                    <td className="py-3">
                      <span className="badge badge-muted">{r.chain || '?'}</span>
                    </td>
                    <td className="py-3 max-w-[220px]">
                      {r.error ? (
                        <span className="text-[11px] text-neon-red">{r.error.slice(0, 60)}</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {r.signals.slice(0, 3).map((s, i) => (
                            <span key={i} className="badge badge-red text-[9px]">{s.slice(0, 28)}</span>
                          ))}
                          {r.signals.length > 3 && (
                            <span className="badge badge-muted text-[9px]">+{r.signals.length - 3}</span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="py-3 pr-4">
                      <Link
                        to={`/intel?address=${encodeURIComponent(r.address)}`}
                        className="text-[11px] text-neon-cyan hover:text-text-bright text-tech"
                      >
                        {t('tools:batchScreener.table.fullIntel')}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!mutation.isPending && results.length === 0 && !mutation.isError && (
        <div className="text-center py-16 text-text-muted">
          <Layers size={40} className="mx-auto mb-3 opacity-20" />
          <p className="text-sm">{t('tools:batchScreener.empty')}</p>
        </div>
      )}
      </div>
    </div>
  )
}
