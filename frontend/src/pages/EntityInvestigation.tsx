/**
 * Entity Investigation — investigate a GROUP of addresses as one subject.
 * Upload/paste multiple addresses → the tool clusters them, computes aggregate
 * flows, shows inter-cluster links, and surfaces external counterparties.
 *
 * Route: /entity
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Users, Loader2, AlertTriangle, ArrowDownRight, ArrowUpRight,
  GitMerge, Search,
} from 'lucide-react'
import { investigateEntity } from '../api/client'
import type { EntityInvestigationResult } from '../types'
import CinematicStage from '../components/CinematicStage'

export default function EntityInvestigation() {
  const { t } = useTranslation()
  const [addressText, setAddressText] = useState('')
  const [chain, setChain] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<EntityInvestigationResult | null>(null)

  async function run() {
    const addresses = addressText
      .split(/[\s,\n]+/)
      .map(a => a.trim())
      .filter(Boolean)
    if (addresses.length < 2) {
      setError(t('tools:entity.errors.minTwo'))
      return
    }
    setLoading(true); setError(''); setResult(null)
    try {
      const r = await investigateEntity({ addresses, chain: chain.trim() })
      setResult(r)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('tools:entity.errors.failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6 page-enter">
      {/* Input */}
      <CinematicStage
        variant="entity"
        icon={Users}
        kicker={t('tools:entity.title')}
        title={t('tools:entity.title')}
        subtitle={t('tools:entity.subtitle')}
        collapsed={!!result}
      >
      <div className="space-y-3">
        <label className="card-title block">{t('tools:entity.inputLabel')}</label>
        <textarea
          value={addressText}
          onChange={e => setAddressText(e.target.value)}
          placeholder={t('tools:entity.inputPlaceholder')}
          rows={6}
          className="input resize-none font-mono text-xs"
        />
        <div className="flex gap-3 items-center">
          <input
            value={chain}
            onChange={e => setChain(e.target.value)}
            placeholder={t('tools:entity.chainPlaceholder')}
            className="input flex-1"
          />
          <button onClick={run} disabled={loading || !addressText.trim()} className="btn-primary">
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
            {t('tools:entity.submit')}
          </button>
        </div>
        {error && (
          <p className="text-neon-red text-xs flex items-center gap-1">
            <AlertTriangle size={13} /> {error}
          </p>
        )}
      </div>
      </CinematicStage>

      {/* Results */}
      {result && (
        <div className="space-y-4 animate-slide-up">
          {/* Aggregate flows */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label={t('tools:entity.stats.addresses')} value={result.address_count} icon={<Users size={16} />} />
            <StatCard label={t('tools:entity.stats.totalIn')} value={fmt(result.aggregate_flows.total_in)} icon={<ArrowDownRight size={16} />} color="#34D399" />
            <StatCard label={t('tools:entity.stats.totalOut')} value={fmt(result.aggregate_flows.total_out)} icon={<ArrowUpRight size={16} />} color="#F87171" />
            <StatCard label={t('tools:entity.stats.clusters')} value={result.cluster_count} icon={<GitMerge size={16} />} color="#60A5FA" />
          </div>

          {/* Clusters */}
          {result.cluster_count > 0 && (
            <div className="card-cyber">
              <h3 className="card-title">{t('tools:entity.clusters.title', { count: result.cluster_count })}</h3>
              <p className="text-[11px] text-text-muted mb-2">{t('tools:entity.clusters.disclaimer')}</p>
              <div className="space-y-2">
                {(result.clusters as Array<Record<string, unknown>>).slice(0, 10).map((c, i) => (
                  <div key={i} className="text-xs border border-white/5 rounded p-2"
                    style={{ background: 'rgba(255,255,255,0.02)' }}>
                    <div className="flex justify-between mb-1">
                      <span className="font-bold" style={{ color: '#60A5FA' }}>{t('tools:entity.clusters.clusterN', { n: i + 1 })}</span>
                      <span className="text-text-muted">
                        {t('tools:entity.clusters.members', { count: (c.members as string[])?.length || 0, conf: String(c.confidence ?? '?') })}
                      </span>
                    </div>
                    <div className="font-mono text-[10px] text-text-secondary truncate">
                      {((c.members as string[]) || []).slice(0, 5).join(', ')}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* External counterparties */}
          <div className="card-cyber">
            <h3 className="card-title">{t('tools:entity.counterparties.title')}</h3>
            <div className="overflow-x-auto cryptx-table-wrap">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-text-muted border-b border-white/10">
                    <th className="py-2 px-2">{t('tools:entity.counterparties.colAddress')}</th>
                    <th className="py-2 px-2">{t('tools:entity.counterparties.colType')}</th>
                    <th className="py-2 px-2 text-right">{t('tools:entity.counterparties.colIn')}</th>
                    <th className="py-2 px-2 text-right">{t('tools:entity.counterparties.colOut')}</th>
                    <th className="py-2 px-2 text-right">{t('tools:entity.counterparties.colTxs')}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.external_counterparties.map((cp, i) => (
                    <tr key={i} className="border-b border-white/5 hover:bg-white/5">
                      <td className="py-1.5 px-2 font-mono">{cp.address.slice(0, 16)}…</td>
                      <td className="py-1.5 px-2"><span className="badge badge-muted">{cp.type}</span></td>
                      <td className="py-1.5 px-2 text-right text-green-400">{fmt(cp.in)}</td>
                      <td className="py-1.5 px-2 text-right text-red-400">{fmt(cp.out)}</td>
                      <td className="py-1.5 px-2 text-right text-text-muted">{cp.txs}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <p className="text-[10px] text-text-muted italic">{result.disclaimer}</p>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, icon, color = '#fff2f4' }: { label: string; value: string | number; icon: React.ReactNode; color?: string }) {
  return (
    <div className="card-cyber">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wider text-text-muted">{label}</span>
        <span style={{ color }}>{icon}</span>
      </div>
      <div className="text-lg font-bold" style={{ color }}>{value}</div>
    </div>
  )
}

function fmt(n: number): string {
  if (!n || n === 0) return '0'
  if (n < 0.001) return n.toExponential(2)
  if (n < 1) return n.toFixed(4)
  if (n < 1000) return n.toFixed(2)
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
}
