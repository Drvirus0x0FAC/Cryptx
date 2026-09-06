/**
 * F8: Time-Travel — reconstruct wallet state at a past timestamp.
 * Shows a date picker + reconstructed balances/flows as of that date.
 * Plugs into Address Intel page.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Clock, Loader2, Rewind } from 'lucide-react'
import { reconstructAtTime, timelineEvolution } from '../api/client'
import type { TimeTravelResult, TimeTravelPoint } from '../types'

export default function TimeTravelPanel({ address, chain, txList }: { address: string; chain?: string; txList: Record<string, unknown>[] }) {
  const { t } = useTranslation()
  const [targetDate, setTargetDate] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<TimeTravelResult | null>(null)
  const [points, setPoints] = useState<TimeTravelPoint[]>([])
  const [error, setError] = useState('')

  async function reconstruct() {
    if (!targetDate || txList.length === 0) return
    setLoading(true); setError('')
    try {
      const [r, evo] = await Promise.all([
        reconstructAtTime({ tx_list: txList, address, chain, target_date: targetDate }),
        timelineEvolution({ tx_list: txList, address, chain }),
      ])
      setResult(r); setPoints(evo.points)
    } catch (e) { setError(e instanceof Error ? e.message : 'failed') }
    finally { setLoading(false) }
  }

  if (!address || txList.length === 0) return null

  return (
    <div className="card-cyber space-y-3">
      <div className="flex items-center gap-2">
        <Rewind size={15} style={{ color: '#a78bfa' }} />
        <h3 className="card-title">Time-Travel (Historical State)</h3>
      </div>
      <p className="text-[11px] text-text-muted">
        Reconstruct this wallet's balance &amp; graph as of a past date. {txList.length} transactions available.
      </p>
      <div className="flex gap-2 items-center">
        <Clock size={14} style={{ color: '#6b7280' }} />
        <input type="date" value={targetDate} onChange={e => setTargetDate(e.target.value)} className="input flex-1 text-xs" />
        <button onClick={reconstruct} disabled={loading || !targetDate} className="btn-primary text-xs">
          {loading ? <Loader2 size={12} className="animate-spin" /> : null}
          Reconstruct
        </button>
      </div>

      {error && <p className="text-neon-red text-xs">⚠ {error}</p>}

      {/* Evolution sparkline */}
      {points.length > 1 && (
        <div className="pt-2">
          <div className="text-[10px] text-text-muted uppercase mb-1">{t('components:shared.timeTravel.balanceEvolution')}</div>
          <div className="flex items-end gap-0.5 h-12">
            {points.map((p, i) => {
              const max = Math.max(...points.map(x => Math.abs(x.net_balance)), 1)
              const h = Math.max(2, (Math.abs(p.net_balance) / max) * 100)
              return (
                <div key={i} className="flex-1 rounded-t" title={`${p.iso}: ${p.net_balance.toFixed(4)}`}
                  style={{ height: `${h}%`, background: p.net_balance >= 0 ? 'rgba(52,211,153,0.4)' : 'rgba(248,113,113,0.4)' }} />
              )
            })}
          </div>
          <div className="flex justify-between text-[9px] text-text-muted mt-1">
            <span>{points[0]?.iso.slice(0, 10)}</span>
            <span>{points[points.length - 1]?.iso.slice(0, 10)}</span>
          </div>
        </div>
      )}

      {result && (
        <div className="space-y-2 animate-slide-up pt-2 border-t border-white/10">
          <div className="text-xs font-bold" style={{ color: '#a78bfa' }}>
            State as of {result.target_iso.slice(0, 10)}
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="flex justify-between p-2 rounded" style={{ background: 'rgba(255,255,255,0.02)' }}>
              <span className="text-text-muted">{t('components:shared.timeTravel.cumulativeIn')}</span>
              <span className="text-green-400 font-mono">{result.cumulative_in.toFixed(4)}</span>
            </div>
            <div className="flex justify-between p-2 rounded" style={{ background: 'rgba(255,255,255,0.02)' }}>
              <span className="text-text-muted">{t('components:shared.timeTravel.cumulativeOut')}</span>
              <span className="text-red-400 font-mono">{result.cumulative_out.toFixed(4)}</span>
            </div>
          </div>
          {Object.keys(result.balances).length > 0 && (
            <div className="text-xs">
              <div className="text-[10px] text-text-muted uppercase mb-1">{t('components:shared.timeTravel.balances')}</div>
              {Object.entries(result.balances).map(([asset, bal]) => (
                <div key={asset} className="flex justify-between font-mono py-0.5">
                  <span className="text-text-secondary">{asset}</span>
                  <span style={{ color: '#fff2f4' }}>{Number(bal).toFixed(6)}</span>
                </div>
              ))}
            </div>
          )}
          <div className="text-[10px] text-text-muted">{t('components:shared.timeTravel.counterparties')} <span className="text-neon-cyan">{result.counterparty_count}</span></div>
          <p className="text-[9px] text-text-muted italic">{result.disclaimer}</p>
        </div>
      )}
    </div>
  )
}
