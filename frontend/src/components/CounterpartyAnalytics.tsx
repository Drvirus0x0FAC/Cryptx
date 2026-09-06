import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Loader2, Users, Sparkles, AlertTriangle } from 'lucide-react'
import { getCounterpartyAnalytics } from '../api/analytics'
import type { CounterpartyAnalytics as Analytics, Counterparty } from '../api/analytics'

const WINDOWS: Array<{ id: string; label: string }> = [
  { id: '1h', label: '1H' }, { id: '24h', label: '24H' }, { id: '1w', label: '1W' }, { id: '1m', label: '1M' }, { id: 'all', label: 'ALL' },
]

function usd(n: number): string {
  const a = Math.abs(n)
  if (a >= 1e9) return `$${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `$${(n / 1e3).toFixed(2)}K`
  if (a > 0) return `$${n.toFixed(2)}`
  return '$0'
}

function chainBadge(chains: string[]): string {
  if (!chains.length) return '-'
  return chains.map(c => c.toUpperCase()).join(' · ')
}

export default function CounterpartyAnalytics({ address, chain = 'auto' }: { address?: string | null; chain?: string }) {
  const { t } = useTranslation()
  const [data, setData] = useState<Analytics | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'counterparties' | 'predictions'>('counterparties')
  const [win, setWin] = useState('all')
  const [dir, setDir] = useState<'all' | 'in' | 'out' | 'net'>('all')

  const addr = (address || '').trim()

  useEffect(() => {
    if (!addr) { setData(null); return }
    let cancelled = false
    setLoading(true); setError(null)
    getCounterpartyAnalytics(addr, chain, win)
      .then(d => { if (!cancelled) { if (d.error) setError(d.error); else setData(d) } })
      .catch(e => { if (!cancelled) setError(e?.response?.data?.detail || e?.message || String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [addr, chain, win])

  const sortedCps = useMemo<Counterparty[]>(() => {
    if (!data) return []
    const key = dir === 'in' ? 'in_usd' : dir === 'out' ? 'out_usd' : dir === 'net' ? 'net_usd' : 'usd'
    return [...data.counterparties]
      .filter(c => dir === 'in' ? c.in_usd > 0 : dir === 'out' ? c.out_usd > 0 : true)
      .sort((a, b) => Math.abs(b[key as keyof Counterparty] as number) - Math.abs(a[key as keyof Counterparty] as number))
  }, [data, dir])

  if (!addr) return null

  return (
    <div className="card space-y-3">
      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border pb-2">
        {([
          { id: 'counterparties', label: 'Top Counterparties', icon: <Users size={13} /> },
          { id: 'predictions', label: 'Entity Predictions', icon: <Sparkles size={13} /> },
        ] as const).map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
              tab === t.id ? 'bg-neon-red/12 text-neon-red' : 'text-text-muted hover:text-text-secondary'}`}>
            {t.icon}{t.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1">
          {WINDOWS.map(w => (
            <button key={w.id} onClick={() => setWin(w.id)}
              className={`rounded px-2 py-1 text-[10px] font-bold ${win === w.id ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-muted hover:text-text-secondary'}`}>
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {/* Header line */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-text-muted">
        <span className="font-mono text-text-secondary">{data?.chain?.toUpperCase() || chain.toUpperCase()}</span>
        {data && data.date_range.days > 0 && (
          <span>{new Date(data.date_range.start * 1000).toLocaleDateString()} - {new Date(data.date_range.end * 1000).toLocaleDateString()} ({data.date_range.days} days)</span>
        )}
        {data && <span>{data.totals.tx_count} txns · {data.totals.counterparty_count} counterparties</span>}
        {loading && <span className="flex items-center gap-1 text-neon-cyan"><Loader2 size={11} className="animate-spin" /> loading…</span>}
      </div>

      {error && <div className="flex items-center gap-2 rounded-lg border border-neon-red/35 bg-neon-red/10 p-3 text-xs text-neon-red"><AlertTriangle size={13} />{error}</div>}

      {/* Surface backend fetch issues (rate-limits, unsupported chain, etc.) */}
      {!error && data && data.errors && data.errors.length > 0 && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/8 p-3 text-[11px] text-yellow-400">
          <p className="mb-1 flex items-center gap-1.5 font-semibold"><AlertTriangle size={12} /> Data provider notes for {data.chain?.toUpperCase()}:</p>
          {data.errors.slice(0, 4).map((e, i) => <p key={i} className="font-mono leading-snug">· {e}</p>)}
          <p className="mt-1 text-text-muted">Public explorers rate-limit aggressively. Retry shortly, or add an API key in Settings for higher limits.</p>
        </div>
      )}

      {!error && !loading && data && data.totals.tx_count === 0 && (!data.errors || data.errors.length === 0) && (
        <div className="rounded-lg border border-border bg-bg-secondary/40 p-3 text-xs text-text-muted">
          No transfers returned for this address on <span className="font-mono text-text-secondary">{data.chain?.toUpperCase()}</span> in the selected window.
          If this address is on a different chain, open it from that chain's trace, or widen the time window to ALL.
        </div>
      )}

      {/* ── Top Counterparties ── */}
      {tab === 'counterparties' && data && (
        <div className="space-y-2">
          <div className="flex items-center gap-1 text-[10px]">
            {(['all', 'in', 'out', 'net'] as const).map(d => (
              <button key={d} onClick={() => setDir(d)}
                className={`rounded px-2.5 py-1 font-bold uppercase ${dir === d ? 'bg-neon-red/12 text-neon-red' : 'text-text-muted hover:text-text-secondary'}`}>{d}</button>
            ))}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-[9px] uppercase tracking-widest text-text-muted">
                <th className="py-1 text-left font-medium">Entity</th>
                <th className="py-1 text-left font-medium">Chains</th>
                <th className="py-1 text-right font-medium">Tx</th>
                <th className="py-1 text-right font-medium">Native</th>
                <th className="py-1 text-right font-medium">USD</th>
              </tr></thead>
              <tbody>
                {sortedCps.map(c => {
                  const val = dir === 'in' ? c.in_usd : dir === 'out' ? c.out_usd : dir === 'net' ? c.net_usd : c.usd
                  return (
                    <tr key={c.address} className="border-t border-border/40 hover:bg-bg-secondary/40">
                      <td className="min-w-[360px] py-1.5 pr-3 align-top">
                        <div className="flex flex-col gap-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            {c.entity && <span className="font-semibold text-text-primary">{c.entity}</span>}
                            {c.sanctioned && <span className="rounded bg-neon-red/15 px-1 text-[9px] font-bold text-neon-red">SANCTIONED</span>}
                            {c.type !== 'unknown' && <span className="text-[9px] uppercase text-text-muted">{c.type}</span>}
                          </div>
                          <Link
                            to={`/intel/${encodeURIComponent(c.address)}`}
                            className="block max-w-[680px] break-all font-mono text-[11px] leading-snug text-neon-cyan hover:underline"
                            title="Open address intelligence"
                          >
                            {c.address}
                          </Link>
                        </div>
                      </td>
                      <td className="py-1.5 text-[10px] text-text-muted">{chainBadge(c.chains)}</td>
                      <td className="py-1.5 text-right font-mono text-text-secondary">{c.tx}</td>
                      <td className="py-1.5 text-right font-mono text-[10px] text-text-muted">{c.native_label || '-'}</td>
                      <td className="py-1.5 text-right font-mono font-bold" style={{ color: dir === 'net' ? (val >= 0 ? '#22c578' : '#ff4052') : '#e8e0e2' }}>
                        {dir === 'net' && val > 0 ? '+' : ''}{usd(val)}
                      </td>
                    </tr>
                  )
                })}
                {sortedCps.length === 0 && <tr><td colSpan={5} className="py-4 text-center text-[11px] text-text-muted">No counterparties in window.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Entity Predictions ── */}
      {tab === 'predictions' && data && (
        <div className="space-y-2">
          {data.entity_predictions.map((p, i) => (
            <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-text-primary">{p.label}</p>
                <p className="font-mono text-sm font-bold" style={{ color: p.confidence >= 0.7 ? '#22c578' : p.confidence >= 0.45 ? '#fbbf24' : '#9a858c' }}>{Math.round(p.confidence * 100)}%</p>
              </div>
              <div className="my-1.5 h-1.5 w-full overflow-hidden rounded-full bg-bg-primary">
                <div className="h-full rounded-full" style={{ width: `${Math.round(p.confidence * 100)}%`, background: p.confidence >= 0.7 ? '#22c578' : p.confidence >= 0.45 ? '#fbbf24' : '#64748b' }} />
              </div>
              <p className="text-[11px] text-text-muted">{p.rationale}</p>
            </div>
          ))}
          {data.entity_predictions.length === 0 && <p className="text-xs text-text-muted">No predictions available.</p>}
        </div>
      )}

      {data?.note && <p className="border-t border-border pt-2 text-[10px] italic leading-snug text-text-muted">{data.note}</p>}
    </div>
  )
}
