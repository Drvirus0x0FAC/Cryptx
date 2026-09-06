import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle, Bell, BellRing, Eye, Loader2, Play, Plus,
  RefreshCw, Search, Trash2, Wallet, XCircle,
} from 'lucide-react'
import {
  createMonitorWatches,
  deleteMonitorWatch,
  listMonitorNotifications,
  listMonitorWatches,
  markMonitorNotificationRead,
  scanMonitorNow,
  updateMonitorWatch,
  listAlertRules,
  createAlertRule,
  updateAlertRule,
  deleteAlertRule,
} from '../api/client'
import type { AlertRule } from '../api/client'
import type { WalletMonitorNotification, WalletMonitorWatch } from '../types'
import CinematicStage from '../components/CinematicStage'
import DeliveryChannels from '../components/DeliveryChannels'
import InsightsPanel from '../components/InsightsPanel'

const CHAINS = ['AUTO', 'ETH', 'MATIC', 'BSC', 'ARB', 'OP', 'BASE', 'BTC', 'TRX']

function short(value: string, n = 8) {
  if (!value) return ''
  return value.length > n * 2 + 2 ? `${value.slice(0, n)}...${value.slice(-n)}` : value
}

function txValue(n: WalletMonitorNotification) {
  const tx = n.tx || {}
  const value = tx.value ?? tx.value_eth ?? tx.value_trx ?? tx.delta_btc ?? 0
  return `${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 8 })} ${String(tx.token || n.chain || '')}`
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
      <p className="text-[10px] text-text-muted uppercase tracking-widest">{label}</p>
      <p className="text-lg font-bold text-text-primary font-mono">{value}</p>
      {sub && <p className="text-[11px] text-text-muted truncate">{sub}</p>}
    </div>
  )
}

export default function WalletMonitor() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [addresses, setAddresses] = useState('')
  const [label, setLabel] = useState('')
  const [chain, setChain] = useState('AUTO')
  const [baseline, setBaseline] = useState(true)
  const [watches, setWatches] = useState<WalletMonitorWatch[]>([])
  const [notifications, setNotifications] = useState<WalletMonitorNotification[]>([])
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  // Criteria-based alert rules
  const [rules, setRules] = useState<AlertRule[]>([])
  const [ruleCats, setRuleCats] = useState<string[]>(['any', 'mixer', 'exchange', 'bridge', 'sanctioned', 'scam'])
  const [ruleForm, setRuleForm] = useState({
    name: '', address: '', chain: '', direction: 'any' as AlertRule['direction'],
    min_value: 0, counterparty_category: 'any', enabled: true,
  })
  const [savingRule, setSavingRule] = useState(false)

  async function refresh() {
    const [w, n] = await Promise.all([
      listMonitorWatches(),
      listMonitorNotifications({ limit: 100 }),
    ])
    setWatches(w)
    setNotifications(n)
    listAlertRules().then(r => { setRules(r.rules); if (r.categories?.length) setRuleCats(r.categories) }).catch(() => undefined)
  }

  async function addRule() {
    if (!ruleForm.name.trim()) return
    setSavingRule(true)
    setError(null)
    try {
      await createAlertRule(ruleForm)
      setRuleForm(f => ({ ...f, name: '', address: '', min_value: 0 }))
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSavingRule(false)
    }
  }

  useEffect(() => {
    refresh().catch(() => undefined)
    const iv = setInterval(() => refresh().catch(() => undefined), 15_000)
    return () => clearInterval(iv)
  }, [])

  async function addWatches() {
    const list = addresses.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean)
    if (!list.length) return
    setLoading(true)
    setError(null)
    try {
      await createMonitorWatches({
        addresses: list,
        chain: chain === 'AUTO' ? undefined : chain,
        label,
        poll_interval: 90,
        baseline_existing: baseline,
      })
      setAddresses('')
      setLabel('')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  async function manualScan() {
    setScanning(true)
    setError(null)
    try {
      await scanMonitorNow()
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setScanning(false)
    }
  }

  async function openNotification(n: WalletMonitorNotification) {
    await markMonitorNotificationRead(n.id).catch(() => undefined)
    await refresh().catch(() => undefined)
    navigate(`/tx/${encodeURIComponent(n.chain || 'ETH')}/${encodeURIComponent(n.tx_hash.split(':rule:')[0])}`)
  }

  const unread = notifications.filter((n) => !n.is_read)
  const filteredWatches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return watches
    return watches.filter((w) => `${w.address} ${w.chain} ${w.label}`.toLowerCase().includes(q))
  }, [watches, query])

  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg flex items-center justify-center"
          style={{ background: 'rgba(0,255,136,0.12)', border: '1px solid rgba(0,255,136,0.35)' }}>
          <BellRing size={18} className="text-neon-green" />
        </div>
        <div>
          <h1 className="text-display text-sm font-bold tracking-widest uppercase text-text-primary">{t('tools:walletMonitor.title')}</h1>
          <p className="text-xs text-text-secondary">{t('tools:walletMonitor.subtitle')}</p>
        </div>
      </div>

      <div className="noscroll-grow space-y-5">
      {/* Predictive triage: which watched wallets are staging a cash-out */}
      {watches.length > 0 && (
        <InsightsPanel
          context="monitor"
          data={{ watches: watches.map((w) => ({ address: w.address, chain: w.chain })) }}
          refreshKey={watches.length}
          compact
        />
      )}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label={t('tools:walletMonitor.stats.watching')} value={watches.length} />
        <Stat label={t('tools:walletMonitor.stats.active')} value={watches.filter((w) => w.active).length} />
        <Stat label={t('tools:walletMonitor.stats.unread')} value={unread.length} />
        <Stat label={t('tools:walletMonitor.stats.notifications')} value={notifications.length} />
        <Stat label={t('tools:walletMonitor.stats.poll')} value={t('tools:walletMonitor.stats.poll')} sub={t('tools:walletMonitor.stats.pollSub')} />
      </div>

      {/* V2 F1: Alert delivery channels (webhook / email / telegram / SSE) */}
      <div className="card-cyber p-4">
        <DeliveryChannels />
      </div>

      <CinematicStage
        variant="monitor"
        icon={BellRing}
        collapsed={false}
      >
        <div className="space-y-3">
          <div className="grid grid-cols-1 lg:grid-cols-[130px_1fr_220px_auto] gap-3">
            <select className="input" value={chain} onChange={(e) => setChain(e.target.value)}>
              {CHAINS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <textarea
              className="input min-h-[76px] resize-y"
              placeholder={t('tools:walletMonitor.add.placeholder')}
              value={addresses}
              onChange={(e) => setAddresses(e.target.value)}
            />
            <input className="input" placeholder={t('tools:walletMonitor.add.labelPlaceholder')} value={label} onChange={(e) => setLabel(e.target.value)} />
            <button className="btn-primary self-start" disabled={loading || !addresses.trim()} onClick={addWatches}>
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              {t('tools:walletMonitor.add.button')}
            </button>
          </div>
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input type="checkbox" checked={baseline} onChange={(e) => setBaseline(e.target.checked)} />
            {t('tools:walletMonitor.add.baseline')}
          </label>
        </div>
      </CinematicStage>

      {error && (
        <div className="card border-risk-mixer/50 flex items-start gap-3">
          <AlertTriangle className="text-risk-mixer shrink-0 mt-0.5" size={18} />
          <p className="text-xs text-risk-mixer">{error}</p>
        </div>
      )}

      {/* ── Criteria-based Alert Rules ── */}
      <div className="card space-y-3">
        <p className="card-title flex items-center gap-2"><AlertTriangle size={13} /> {t('tools:walletMonitor.rules.title')}</p>
        <p className="text-xs text-text-muted -mt-1">
          {t('tools:walletMonitor.rules.hint')}
        </p>
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_200px_110px_110px_130px_auto] gap-2 items-end">
          <label className="text-[10px] uppercase tracking-widest text-text-muted">{t('tools:walletMonitor.rules.ruleName')}
            <input className="input mt-1 text-xs" placeholder={t('tools:walletMonitor.rules.ruleNamePlaceholder')}
              value={ruleForm.name} onChange={e => setRuleForm(f => ({ ...f, name: e.target.value }))} />
          </label>
          <label className="text-[10px] uppercase tracking-widest text-text-muted">{t('tools:walletMonitor.rules.address')}
            <input className="input mt-1 text-xs font-mono" placeholder={t('tools:walletMonitor.rules.addressPlaceholder')}
              value={ruleForm.address} onChange={e => setRuleForm(f => ({ ...f, address: e.target.value }))} />
          </label>
          <label className="text-[10px] uppercase tracking-widest text-text-muted">{t('tools:walletMonitor.rules.direction')}
            <select className="input mt-1 text-xs" value={ruleForm.direction}
              onChange={e => setRuleForm(f => ({ ...f, direction: e.target.value as AlertRule['direction'] }))}>
              {['any', 'in', 'out'].map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label className="text-[10px] uppercase tracking-widest text-text-muted">{t('tools:walletMonitor.rules.minValue')}
            <input className="input mt-1 text-xs" type="number" min={0} step="any"
              value={ruleForm.min_value || ''} placeholder="0"
              onChange={e => setRuleForm(f => ({ ...f, min_value: Number(e.target.value) || 0 }))} />
          </label>
          <label className="text-[10px] uppercase tracking-widest text-text-muted">{t('tools:walletMonitor.rules.counterparty')}
            <select className="input mt-1 text-xs" value={ruleForm.counterparty_category}
              onChange={e => setRuleForm(f => ({ ...f, counterparty_category: e.target.value }))}>
              {ruleCats.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <button className="btn-primary text-xs h-9" disabled={savingRule || !ruleForm.name.trim()} onClick={addRule}>
            {savingRule ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} {t('tools:walletMonitor.rules.addRule')}
          </button>
        </div>
        {rules.length > 0 && (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th>{t('tools:walletMonitor.rules.colRule')}</th><th>{t('tools:walletMonitor.rules.colScope')}</th><th>{t('tools:walletMonitor.rules.colDirection')}</th><th>{t('tools:walletMonitor.rules.colMinValue')}</th><th>{t('tools:walletMonitor.rules.colCounterparty')}</th><th>{t('tools:walletMonitor.rules.colStatus')}</th><th /></tr></thead>
              <tbody>
                {rules.map(r => (
                  <tr key={r.id}>
                    <td className="text-text-primary font-semibold">{r.name}</td>
                    <td className="font-mono text-[11px]">{r.address ? short(r.address, 8) : t('tools:walletMonitor.rules.allWatches')}{r.chain ? ` · ${r.chain}` : ''}</td>
                    <td>{r.direction}</td>
                    <td>{r.min_value || '-'}</td>
                    <td>{r.counterparty_category}</td>
                    <td>
                      <button className={r.enabled ? 'badge badge-green' : 'badge badge-muted'}
                        onClick={() => updateAlertRule(r.id, { ...r, enabled: !r.enabled }).then(refresh)}>
                        {r.enabled ? t('tools:walletMonitor.rules.enabled') : t('tools:walletMonitor.rules.disabled')}
                      </button>
                    </td>
                    <td>
                      <button className="btn-ghost text-xs" onClick={() => deleteAlertRule(r.id).then(refresh)}>
                        <Trash2 size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_0.9fr] gap-5">
        <div className="card">
          <div className="flex items-center justify-between gap-3 mb-3">
            <p className="card-title flex items-center gap-2"><Wallet size={13} /> {t('tools:walletMonitor.watchlist.title')}</p>
            <button className="btn-ghost text-xs" onClick={manualScan} disabled={scanning}>
              {scanning ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              {t('tools:walletMonitor.watchlist.scanNow')}
            </button>
          </div>
          <div className="relative mb-3">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input className="input pl-8 py-1.5 text-xs" placeholder={t('tools:walletMonitor.watchlist.filterPlaceholder')} value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th>{t('tools:walletMonitor.watchlist.colStatus')}</th><th>{t('tools:walletMonitor.watchlist.colAddress')}</th><th>{t('tools:walletMonitor.watchlist.colChain')}</th><th>{t('tools:walletMonitor.watchlist.colLabel')}</th><th>{t('tools:walletMonitor.watchlist.colLastChecked')}</th><th>{t('tools:walletMonitor.watchlist.colActions')}</th></tr></thead>
              <tbody>
                {filteredWatches.map((w) => (
                  <tr key={w.id}>
                    <td>{w.active ? <span className="badge badge-green">{t('tools:walletMonitor.watchlist.active')}</span> : <span className="badge badge-muted">{t('tools:walletMonitor.watchlist.paused')}</span>}</td>
                    <td className="font-mono max-w-[260px] truncate">{w.address}</td>
                    <td>{w.chain || '-'}</td>
                    <td>{w.label || '-'}</td>
                    <td className="text-xs text-text-muted">{w.last_checked || '-'}</td>
                    <td>
                      <div className="flex gap-2">
                        <button className="btn-ghost text-xs" onClick={() => updateMonitorWatch(w.id, { active: !w.active }).then(refresh)}>
                          {w.active ? <XCircle size={12} /> : <Play size={12} />}
                        </button>
                        <button className="btn-ghost text-xs" onClick={() => deleteMonitorWatch(w.id).then(refresh)}>
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {filteredWatches.length === 0 && <tr><td colSpan={6} className="text-text-muted">{t('tools:walletMonitor.watchlist.empty')}</td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <p className="card-title flex items-center gap-2"><Bell size={13} /> {t('tools:walletMonitor.notifications.title')}</p>
          <div className="space-y-2 mt-3 max-h-[560px] overflow-y-auto pr-1">
            {notifications.map((n) => (
              <button
                key={n.id}
                className="w-full text-left border border-border rounded-lg p-3 bg-bg-secondary/50 hover:border-neon-cyan/40"
                onClick={() => openNotification(n)}
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="font-mono text-xs text-text-primary truncate">{short(n.tx_hash.split(':rule:')[0], 10)}</p>
                  <span className="flex items-center gap-1.5">
                    {(n.tx as { alert_rule?: string })?.alert_rule && (
                      <span className="badge" style={{ background: 'rgba(251,191,36,0.15)', color: '#FBBF24', border: '1px solid rgba(251,191,36,0.35)' }}>
                        {t('tools:walletMonitor.notifications.ruleBadge', { name: (n.tx as { alert_rule?: string }).alert_rule })}
                      </span>
                    )}
                    {!n.is_read && <span className="badge badge-red">{t('tools:walletMonitor.notifications.new')}</span>}
                  </span>
                </div>
                <p className="text-[11px] text-text-muted mt-1">{n.chain} · {short(n.address, 10)} · {txValue(n)}</p>
                <p className="text-[11px] text-text-dim mt-1">{n.tx?.time || n.created_at}</p>
                <span className="inline-flex items-center gap-1 text-[11px] text-neon-cyan mt-2">
                  <Eye size={11} /> {t('tools:walletMonitor.notifications.openDetails')}
                </span>
              </button>
            ))}
            {notifications.length === 0 && <p className="text-sm text-text-muted">{t('tools:walletMonitor.notifications.empty')}</p>}
          </div>
        </div>
      </div>
      </div>
    </div>
  )
}
