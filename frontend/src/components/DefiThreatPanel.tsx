/**
 * F6: DeFi Threat trackers — stablecoin freeze/seize, flash-loan, rug-pull, MEV.
 * Drop-in panel for TX Lens page.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Snowflake, Zap, TrendingDown, Bot } from 'lucide-react'
import { analyzeDefi } from '../api/client'

export default function DefiThreatPanel({ txList, subject }: { txList: Record<string, unknown>[]; subject?: string }) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)

  async function run() {
    setLoading(true)
    try { setResult(await analyzeDefi({ tx_list: txList, subject, trackers: ['all'] })) }
    finally { setLoading(false) }
  }

  if (!txList || txList.length === 0) return null

  const sc = result?.stablecoin_actions as Record<string, unknown> | undefined
  const fl = result?.flash_loan_attacks as Record<string, unknown> | undefined
  const rp = result?.rug_pulls as Record<string, unknown> | undefined
  const mev = result?.mev_bots as Record<string, unknown> | undefined

  return (
    <div className="card-cyber space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="card-title">{t('components:shared.defiThreat.title')}</h3>
        <button onClick={run} disabled={loading} className="btn-primary text-xs">
          {loading ? <Loader2 size={12} className="animate-spin" /> : null}
          Scan {txList.length} Txs
        </button>
      </div>

      {result && (
        <div className="grid grid-cols-2 gap-2">
          <ThreatCard icon={<Snowflake size={14} />} title={t('components:shared.defiThreat.stablecoin')}
            count={Number(sc?.total_events ?? 0)} severity={String(sc?.severity ?? 'none')}
            color="#60A5FA" note={sc ? `freeze:${(sc.freeze_events as unknown[])?.length || 0} blacklist:${(sc.blacklist_events as unknown[])?.length || 0} seize:${(sc.seizure_events as unknown[])?.length || 0}` : ''} />
          <ThreatCard icon={<Zap size={14} />} title={t('components:shared.defiThreat.flashLoan')}
            count={Number(fl?.total ?? 0)} severity={Number(fl?.total) > 0 ? 'high' : 'none'}
            color="#FBBF24" note={fl?.disclaimer as string} />
          <ThreatCard icon={<TrendingDown size={14} />} title={t('components:shared.defiThreat.rugPull')}
            count={Number(rp?.total ?? 0)} severity={Number(rp?.total) > 0 ? 'critical' : 'none'}
            color="#F87171" note={rp?.disclaimer as string} />
          <ThreatCard icon={<Bot size={14} />} title={t('components:shared.defiThreat.mevBots')}
            count={Number(mev?.total ?? 0)} severity={Number(mev?.total) > 0 ? 'medium' : 'none'}
            color="#A78BFA" note={mev?.disclaimer as string} />
        </div>
      )}
    </div>
  )
}

function ThreatCard({ icon, title, count, severity, color, note }: {
  icon: React.ReactNode; title: string; count: number; severity: string; color: string; note?: string
}) {
  const sevColor = severity === 'critical' ? '#F87171' : severity === 'high' ? '#FBBF24' : severity === 'medium' ? '#A78BFA' : '#34D399'
  return (
    <div className="card-cyber p-2.5" style={{ borderColor: count > 0 ? sevColor : undefined }}>
      <div className="flex items-center justify-between mb-1">
        <span style={{ color }}>{icon}</span>
        {count > 0 && <span className="text-[9px] px-1.5 py-0.5 rounded uppercase font-bold" style={{ background: `${sevColor}22`, color: sevColor }}>{severity}</span>}
      </div>
      <div className="text-lg font-bold" style={{ color: count > 0 ? sevColor : '#6b7280' }}>{count}</div>
      <div className="text-[10px] text-text-muted">{title}</div>
      {note && <div className="text-[8px] text-text-muted mt-1 line-clamp-2">{note}</div>}
    </div>
  )
}
