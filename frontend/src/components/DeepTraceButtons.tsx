/**
 * F9: Deep Trace — BTC UTXO multi-hop + Solana SPL instruction-level trace.
 * Drop-in panel for Fund Tracer / Holistic Trace pages.
 * Props: address, chain. Auto-selects BTC or SOL deep tracer.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Network, Snowflake } from 'lucide-react'
import { deepTraceBtc, deepTraceSol } from '../api/client'
import type { DeepTraceResult } from '../types'

export default function DeepTraceButtons({ address, chain }: { address: string; chain?: string }) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState('')
  const [result, setResult] = useState<DeepTraceResult | null>(null)
  const [error, setError] = useState('')

  const detected = (chain || '').toLowerCase()
  const isBtc = detected === 'btc' || address.startsWith('bc1') || (address.startsWith('1') && address.length < 35) || (address.startsWith('3') && address.length < 35)
  const isSol = detected === 'sol' || address.length > 40

  async function run(kind: 'btc' | 'sol') {
    setLoading(kind); setError(''); setResult(null)
    try {
      const r = kind === 'btc' ? await deepTraceBtc(address, 3) : await deepTraceSol(address)
      setResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'trace failed')
    } finally { setLoading('') }
  }

  if (!isBtc && !isSol) return null

  return (
    <div className="card-cyber space-y-3">
      <div className="flex items-center gap-2">
        {isBtc ? <Network size={15} style={{ color: '#F7931A' }} /> : <Snowflake size={15} style={{ color: '#14F195' }} />}
        <h3 className="card-title">Deep {isBtc ? 'Bitcoin' : 'Solana'} Trace</h3>
        <span className="text-[10px] text-text-muted ml-auto">
          {isBtc ? 'UTXO multi-hop (peel-chain)' : 'SPL instruction-level'}
        </span>
      </div>
      <p className="text-[11px] text-text-muted">
        {isBtc
          ? 'Follows BTC outputs forward across hops using full input/output address data — overcomes the "hop-0 stall" limitation.'
          : 'Parses Solana instruction tree to extract real SPL token transfers — beyond simple balance deltas.'}
      </p>
      <button
        onClick={() => run(isBtc ? 'btc' : 'sol')}
        disabled={!!loading || !address}
        className="btn-primary text-xs">
        {loading ? <Loader2 size={12} className="animate-spin" /> : null}
        Run Deep Trace
      </button>

      {error && <p className="text-neon-red text-xs">⚠ {error}</p>}

      {result && (
        <div className="space-y-2 animate-slide-up">
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="card-cyber py-2"><div className="text-lg font-bold text-neon-cyan">{result.node_count}</div><div className="text-[9px] text-text-muted uppercase">Nodes</div></div>
            <div className="card-cyber py-2"><div className="text-lg font-bold text-neon-red">{result.edge_count}</div><div className="text-[9px] text-text-muted uppercase">Edges</div></div>
            <div className="card-cyber py-2"><div className="text-lg font-bold text-neon-green">{String(result.hops_completed ?? (result as Record<string, unknown>).txs_fetched ?? '?')}</div><div className="text-[9px] text-text-muted uppercase">Hops/Txs</div></div>
          </div>
          {result.edges && result.edges.length > 0 && (
            <div className="cryptx-table-wrap">
              <table className="w-full text-[10px] font-mono">
                <thead><tr className="text-text-muted border-b border-white/10"><th className="text-left py-1">Source → Target</th><th className="text-right">Value</th></tr></thead>
                <tbody>
                  {result.edges.slice(0, 15).map((e, i) => (
                    <tr key={i} className="border-b border-white/5">
                      <td className="py-1 truncate max-w-[200px]">{String(e.source).slice(0, 12)}… → {String(e.target).slice(0, 12)}…</td>
                      <td className="text-right">{Number(e.value).toFixed(6)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-[9px] text-text-muted italic">{result.disclaimer}</p>
        </div>
      )}
    </div>
  )
}
