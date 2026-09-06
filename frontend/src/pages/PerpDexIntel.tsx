import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CandlestickChart, Loader2, Search, ShieldAlert, ArrowUpRight, Wallet, Activity,
} from 'lucide-react'
import { perpDexAnalyze } from '../api/client'
import { useFormat } from '../i18n/format'
import CinematicStage from '../components/CinematicStage'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

const SEV_COLOR: Record<string, string> = { high: '#ff4052', medium: '#ffd60a', info: '#9a858c' }

/**
 * Perp DEX Intel — Hyperliquid coverage (3.4).
 * Public-API account analysis with deterministic abuse detectors: wash trading,
 * intentional-loss value transfer, pass-through placement, liquidation activity,
 * HIP-3 thin-market concentration. Pivots to Arbitrum tracing (same EOA).
 */
export default function PerpDexIntel() {
  const { t } = useTranslation()
  const { formatCurrency, formatNumber } = useFormat()
  const { addr } = useParams()
  const [address, setAddress] = useState(addr || '')
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function analyze(a?: string) {
    const target = (a ?? address).trim()
    if (!target) return
    setBusy(true); setErr(''); setResult(null)
    try { setResult(await perpDexAnalyze(target)) }
    catch (e) { setErr(friendlyError(e)) } finally { setBusy(false) }
  }
  useEffect(() => { if (addr) { setAddress(addr); analyze(addr) } }, [addr])

  const fs = result?.fills_stats
  const ls = result?.ledger_stats
  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <CinematicStage
        variant="perpdex"
        icon={CandlestickChart}
        kicker={t('tools:perpDex.title')}
        title={t('tools:perpDex.title')}
        subtitle={t('tools:perpDex.subtitle')}
        collapsed={!!result}
      >
        <div className="flex gap-2 flex-wrap">
        <input className="input flex-1 font-mono text-sm" placeholder={t('tools:perpDex.inputPlaceholder')}
          value={address} onChange={e => setAddress(e.target.value)} onKeyDown={e => e.key === 'Enter' && analyze()} />
        <button className="btn-primary flex items-center gap-2" onClick={() => analyze()} disabled={busy || !address.trim()}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />} {t('tools:perpDex.analyze')}
        </button>
        </div>
      </CinematicStage>
      {/* Results — grows & scrolls internally */}
      <div className="noscroll-grow space-y-5">
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {busy && !result && <div className="card text-sm text-text-muted">{t('tools:perpDex.loading')}</div>}

      {result && (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <div className="card"><p className="text-xs text-text-muted flex items-center gap-1"><Wallet size={12} /> {t('tools:perpDex.stats.accountValue')}</p>
              <p className="text-2xl font-bold text-text-primary">{result.account.account_value_usd != null ? formatCurrency(Number(result.account.account_value_usd)) : '—'}</p></div>
            <div className="card"><p className="text-xs text-text-muted flex items-center gap-1"><Activity size={12} /> {t('tools:perpDex.stats.tradedVolume')}</p>
              <p className="text-2xl font-bold text-text-primary">{formatCurrency(Number(fs?.volume_usd || 0))}</p>
              <p className="text-[11px] text-text-muted">{t('tools:perpDex.stats.fillsRoundTrips', { fills: fs?.fill_count || 0, rounds: fs?.round_trips || 0 })}</p></div>
            <div className="card"><p className="text-xs text-text-muted">{t('tools:perpDex.stats.netClosedPnl')}</p>
              <p className={`text-2xl font-bold ${Number(fs?.net_closed_pnl_usd || 0) < 0 ? 'text-red-400' : 'text-green-400'}`}>
                {formatCurrency(Number(fs?.net_closed_pnl_usd || 0))}</p>
              <p className="text-[11px] text-text-muted">{t('tools:perpDex.stats.fees', { amount: formatNumber(Number(fs?.fees_usd || 0)) })}</p></div>
            <div className="card"><p className="text-xs text-text-muted">{t('tools:perpDex.stats.depositsWithdrawals')}</p>
              <p className="text-lg font-bold text-text-primary">{formatCurrency(Number(ls?.deposit_usd || 0))} <span className="text-text-muted font-normal">{t('tools:perpDex.stats.in')}</span></p>
              <p className="text-lg font-bold text-text-primary">{formatCurrency(Number(ls?.withdrawal_usd || 0))} <span className="text-text-muted font-normal">{t('tools:perpDex.stats.out')}</span></p></div>
          </div>

          <div className="card space-y-2">
            <p className="text-sm font-semibold text-text-primary flex items-center gap-2">
              {t('tools:perpDex.detectors.title')}
              <span className="badge text-[10px] uppercase" style={{ background: SEV_COLOR[result.risk_level] + '22', color: SEV_COLOR[result.risk_level] }}>
                {result.risk_level}
              </span>
            </p>
            {result.detectors.map((d: any, i: number) => (
              <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3">
                <p className="flex items-center gap-2 text-sm font-medium" style={{ color: SEV_COLOR[d.severity] || '#9a858c' }}>
                  <ShieldAlert size={14} /> {d.detector.replace(/_/g, ' ')} <span className="badge text-[10px]">{d.severity}</span>
                </p>
                <p className="text-xs text-text-secondary mt-1">{d.verdict}</p>
                <p className="text-[11px] text-text-muted mt-0.5">{t('tools:perpDex.detectors.basis', { basis: d.basis })}</p>
              </div>
            ))}
            <p className="text-[11px] text-text-muted italic">{result.method_note}</p>
            {result.errors?.length > 0 && <p className="text-[11px] text-yellow-300">{t('tools:perpDex.detectors.partialData', { errors: result.errors.join(' · ') })}</p>}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card overflow-x-auto">
              <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">{t('tools:perpDex.volumeByMarket.title')}</p>
              <table className="w-full text-sm">
                <thead><tr className="text-text-muted text-left"><th className="p-2">{t('tools:perpDex.volumeByMarket.colMarket')}</th><th className="p-2">{t('tools:perpDex.volumeByMarket.colVolume')}</th><th className="p-2">{t('tools:perpDex.volumeByMarket.colPnl')}</th><th className="p-2">{t('tools:perpDex.volumeByMarket.colFills')}</th></tr></thead>
                <tbody>
                  {Object.entries(fs?.by_coin || {}).map(([coin, v]: any) => (
                    <tr key={coin} className="border-t border-border text-xs">
                      <td className="p-2 font-medium">{coin}</td>
                      <td className="p-2">{formatCurrency(Number(v.volume))}</td>
                      <td className="p-2" style={{ color: v.pnl < 0 ? '#ff4052' : '#34D399' }}>{formatCurrency(Number(v.pnl))}</td>
                      <td className="p-2">{v.fills}</td>
                    </tr>
                  ))}
                  {!fs?.by_coin && <tr><td colSpan={4} className="p-4 text-center text-text-muted">{t('tools:perpDex.volumeByMarket.noFills')}</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="space-y-4">
              <div className="card">
                <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">{t('tools:perpDex.openPositions.title')}</p>
                {(result.account.positions || []).length === 0 && <p className="text-xs text-text-muted">{t('tools:perpDex.openPositions.none')}</p>}
                {(result.account.positions || []).map((p: any, i: number) => (
                  <p key={i} className="text-xs text-text-secondary">
                    {t('tools:perpDex.openPositions.row', { coin: p.coin, size: p.size, entry: p.entry_px, value: formatNumber(Number(p.position_value || 0)), upnl: formatNumber(Number(p.unrealized_pnl || 0)), lev: p.leverage })}
                  </p>
                ))}
              </div>
              <div className="card space-y-1.5">
                <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">{t('tools:perpDex.pivots.title')}</p>
                {result.pivots.map((p: any, i: number) => (
                  <Link key={i} to={p.route} className="flex items-center gap-1 text-sm text-neon-cyan hover:underline">
                    {p.label} <ArrowUpRight size={13} />
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
      </div>
    </div>
  )
}
