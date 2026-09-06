import { useState, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import {
  UserX, AlertTriangle, DollarSign, Globe, FileDown,
  ChevronDown, ChevronRight, Plus, Trash2, Copy,
  RefreshCw, Shield, TrendingDown, Hash, Filter,
  CheckCircle, Clock, Eye, ArrowUpRight, X, Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  listVictimReports,
  submitVictimReport,
  updateVictimReport,
  deleteVictimReport,
  scamIntelSummary,
  scamClusters,
  exportReportBundle,
  listScamTypes,
} from '../api/client'
import type { VictimReport, ScamCluster, ScamIntelSummary, ScamTypeInfo } from '../types'
import ResultTabs from '../components/ResultTabs'
import CinematicStage from '../components/CinematicStage'
import { useTabParam } from '../hooks/useTabParam'

// ── Helpers ───────────────────────────────────────────────────────────────────

const CHAINS = ['ETH', 'BTC', 'BSC', 'TRX', 'POLYGON', 'ARB', 'OP', 'AVAX', 'SOL', 'OTHER']

const STATUS_META: Record<string, { key: string; color: string; icon: LucideIcon }> = {
  open:         { key: 'tools:victimReport.status.open',         color: 'text-yellow-400 border-yellow-700/30 bg-yellow-900/10', icon: Clock },
  under_review: { key: 'tools:victimReport.status.underReview',  color: 'text-red-400 border-red-700/30 bg-red-900/10',          icon: Eye },
  escalated:    { key: 'tools:victimReport.status.escalated',    color: 'text-orange-400 border-orange-700/30 bg-orange-900/10', icon: ArrowUpRight },
  referred:     { key: 'tools:victimReport.status.referred',     color: 'text-purple-400 border-purple-700/30 bg-purple-900/10', icon: Shield },
  closed:       { key: 'tools:victimReport.status.closed',       color: 'text-neon-green border-neon-green/30 bg-neon-green/5',  icon: CheckCircle },
}

const SEV_COLORS: Record<string, string> = {
  critical: 'text-red-400 bg-red-900/20 border-red-700/30',
  high:     'text-orange-400 bg-orange-900/20 border-orange-700/30',
  medium:   'text-yellow-400 bg-yellow-900/15 border-yellow-700/20',
}

function fmtUsd(n: number): string {
  if (!n) return '-'
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

function short(addr: string, n = 8): string {
  if (!addr || addr.length <= n * 2 + 2) return addr
  return `${addr.slice(0, n)}…${addr.slice(-6)}`
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation()
  const m = STATUS_META[status] || STATUS_META.open
  const Icon = m.icon
  return (
    <span className={`inline-flex items-center gap-1 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border ${m.color}`}>
      <Icon size={9} /> {t(m.key)}
    </span>
  )
}

function SevBadge({ severity }: { severity: string }) {
  return (
    <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border ${SEV_COLORS[severity] || SEV_COLORS.medium}`}>
      {severity}
    </span>
  )
}

// ── Submit Form ───────────────────────────────────────────────────────────────

const EMPTY_FORM = {
  scam_type: 'pig_butchering',
  scammer_address: '',
  chain: 'ETH',
  victim_address: '',
  amount_usd: '',
  token: 'ETH',
  incident_date: '',
  description: '',
  contact_name: '',
  contact_email: '',
  jurisdiction: '',
  tx_hashes_raw: '',
  tags_raw: '',
  case_id: '',
}

function SubmitForm({
  scamTypes,
  onSubmitted,
  onClose,
}: {
  scamTypes: ScamTypeInfo[]
  onSubmitted: (r: VictimReport) => void
  onClose: () => void
}) {
  const [form, setForm]     = useState(EMPTY_FORM)
  const [loading, setLoad]  = useState(false)
  const [error, setError]   = useState('')
  const { t } = useTranslation()

  function set(k: string, v: string) { setForm(f => ({ ...f, [k]: v })) }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.scammer_address.trim()) { setError(t('tools:victimReport.form.addrRequired')); return }
    setLoad(true); setError('')
    try {
      const { report } = await submitVictimReport({
        scam_type:       form.scam_type,
        scammer_address: form.scammer_address.trim(),
        chain:           form.chain,
        victim_address:  form.victim_address.trim(),
        amount_usd:      parseFloat(form.amount_usd) || 0,
        token:           form.token.trim() || 'Unknown',
        incident_date:   form.incident_date,
        description:     form.description.trim(),
        contact_name:    form.contact_name.trim(),
        contact_email:   form.contact_email.trim(),
        jurisdiction:    form.jurisdiction.trim(),
        tx_hashes:       form.tx_hashes_raw.split(/[\n,]+/).map(s => s.trim()).filter(Boolean),
        tags:            form.tags_raw.split(',').map(s => s.trim()).filter(Boolean),
        case_id:         form.case_id.trim(),
      })
      onSubmitted(report)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      setError(e.response?.data?.detail || e.message || String(err))
    } finally {
      setLoad(false)
    }
  }

  const fieldCls = 'input w-full text-xs'
  const labelCls = 'block text-[10px] text-text-muted mb-1'

  return createPortal(
    <div className="fixed inset-0 z-[9998] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-bg-elevated border border-bg-border rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-bg-border">
          <div className="flex items-center gap-2">
            <UserX size={16} className="text-red-400" />
            <h2 className="text-sm font-bold text-text-primary">{t('tools:victimReport.form.title')}</h2>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={submit} className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* Scam type + chain row */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>{t('tools:victimReport.form.scamType')}</label>
              <select className={fieldCls} value={form.scam_type} onChange={e => set('scam_type', e.target.value)}>
                {scamTypes.map(t => (
                  <option key={t.id} value={t.id}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>{t('tools:victimReport.form.chain')}</label>
              <select className={fieldCls} value={form.chain} onChange={e => set('chain', e.target.value)}>
                {CHAINS.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>

          {/* Scammer address */}
          <div>
            <label className={labelCls}>{t('tools:victimReport.form.scammerAddr')}</label>
            <input className={`${fieldCls} font-mono`} placeholder={t('tools:victimReport.form.scammerAddrPh')}
              value={form.scammer_address} onChange={e => set('scammer_address', e.target.value)} />
          </div>

          {/* Amount + token */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>{t('tools:victimReport.form.amountLost')}</label>
              <input className={fieldCls} type="number" min="0" step="any" placeholder="0.00"
                value={form.amount_usd} onChange={e => set('amount_usd', e.target.value)} />
            </div>
            <div>
              <label className={labelCls}>{t('tools:victimReport.form.token')}</label>
              <input className={fieldCls} placeholder={t('tools:victimReport.form.tokenPh')}
                value={form.token} onChange={e => set('token', e.target.value)} />
            </div>
          </div>

          {/* Incident date + victim address */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>{t('tools:victimReport.form.incidentDate')}</label>
              <input className={fieldCls} type="date"
                value={form.incident_date} onChange={e => set('incident_date', e.target.value)} />
            </div>
            <div>
              <label className={labelCls}>{t('tools:victimReport.form.victimAddr')}</label>
              <input className={`${fieldCls} font-mono`} placeholder={t('tools:victimReport.form.victimAddrPh')}
                value={form.victim_address} onChange={e => set('victim_address', e.target.value)} />
            </div>
          </div>

          {/* Description */}
          <div>
            <label className={labelCls}>{t('tools:victimReport.form.description')}</label>
            <textarea className={`${fieldCls} h-24 resize-none`}
              placeholder={t('tools:victimReport.form.descriptionPh')}
              value={form.description} onChange={e => set('description', e.target.value)} />
          </div>

          {/* TX hashes */}
          <div>
            <label className={labelCls}>{t('tools:victimReport.form.txHashes')}</label>
            <textarea className={`${fieldCls} h-16 resize-none font-mono text-[10px]`}
              placeholder="0xabc123…&#10;0xdef456…"
              value={form.tx_hashes_raw} onChange={e => set('tx_hashes_raw', e.target.value)} />
          </div>

          {/* Contact + jurisdiction */}
          <div className="rounded-lg border border-bg-border bg-bg-primary p-3 space-y-3">
            <div className="text-[10px] font-semibold text-text-muted uppercase tracking-wide">{t('tools:victimReport.form.contactInfo')}</div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>{t('tools:victimReport.form.yourName')}</label>
                <input className={fieldCls} placeholder="—"
                  value={form.contact_name} onChange={e => set('contact_name', e.target.value)} />
              </div>
              <div>
                <label className={labelCls}>{t('tools:victimReport.form.email')}</label>
                <input className={fieldCls} type="email" placeholder="—"
                  value={form.contact_email} onChange={e => set('contact_email', e.target.value)} />
              </div>
            </div>
            <div>
              <label className={labelCls}>{t('tools:victimReport.form.jurisdiction')}</label>
              <input className={fieldCls} placeholder={t('tools:victimReport.form.jurisdictionPh')}
                value={form.jurisdiction} onChange={e => set('jurisdiction', e.target.value)} />
            </div>
          </div>

          {/* Tags + case */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>{t('tools:victimReport.form.tags')}</label>
              <input className={fieldCls} placeholder={t('tools:victimReport.form.tagsPh')}
                value={form.tags_raw} onChange={e => set('tags_raw', e.target.value)} />
            </div>
            <div>
              <label className={labelCls}>{t('tools:victimReport.form.linkCase')}</label>
              <input className={fieldCls} placeholder={t('tools:victimReport.form.linkCasePh')}
                value={form.case_id} onChange={e => set('case_id', e.target.value)} />
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-2 text-[11px] text-red-400 bg-red-900/10 border border-red-700/20 rounded-lg px-3 py-2">
              <AlertTriangle size={12} /> {error}
            </div>
          )}
        </form>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-4 border-t border-bg-border">
          <p className="text-[10px] text-text-dim max-w-xs">
            {t('tools:victimReport.form.privacyNote')}
          </p>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="btn-secondary text-xs px-4 py-2">{t('tools:victimReport.form.cancel')}</button>
            <button onClick={submit} disabled={loading} className="btn-primary text-xs px-5 py-2">
              {loading ? t('tools:victimReport.form.submitting') : t('tools:victimReport.form.submit')}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}

// ── Report card ───────────────────────────────────────────────────────────────

function ReportCard({
  report,
  scamTypes,
  selected,
  onSelect,
  onUpdate,
  onDelete,
}: {
  report: VictimReport
  scamTypes: ScamTypeInfo[]
  selected: boolean
  onSelect: (id: string, checked: boolean) => void
  onUpdate: (r: VictimReport) => void
  onDelete: (id: string) => void
}) {
  const [open, setOpen]         = useState(false)
  const [updatingStatus, setUS] = useState(false)
  const scamMeta = scamTypes.find(t => t.id === report.scam_type)
  const { t } = useTranslation()

  async function changeStatus(newStatus: string) {
    setUS(true)
    try {
      const { report: updated } = await updateVictimReport(report.id, { status: newStatus })
      onUpdate(updated)
    } finally {
      setUS(false)
    }
  }

  async function handleDelete() {
    if (!confirm(t('tools:victimReport.report.deleteConfirm'))) return
    await deleteVictimReport(report.id)
    onDelete(report.id)
  }

  return (
    <div className={`rounded-xl border transition-colors ${selected ? 'border-neon-cyan/40 bg-neon-cyan/3' : 'border-bg-border bg-bg-elevated'}`}>
      {/* Summary row */}
      <div className="flex items-center gap-3 px-4 py-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={e => onSelect(report.id, e.target.checked)}
          className="w-3.5 h-3.5 shrink-0 accent-neon-cyan"
        />
        <button
          className="flex-1 flex items-center gap-3 text-left min-w-0"
          onClick={() => setOpen(o => !o)}
        >
          <div className="flex-1 min-w-0 space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              {scamMeta && (
                <SevBadge severity={scamMeta.severity} />
              )}
              <span className="text-xs font-semibold text-text-primary">{scamMeta?.label || report.scam_type}</span>
              <span className="text-[10px] text-text-muted">{report.chain}</span>
              <StatusBadge status={report.status} />
            </div>
            <div className="flex items-center gap-3 flex-wrap text-[10px] text-text-muted">
              <span className="font-mono">{short(report.scammer_address)}</span>
              {report.amount_usd > 0 && (
                <span className="text-red-400 font-semibold">{fmtUsd(report.amount_usd)}</span>
              )}
              {report.incident_date && <span>{report.incident_date}</span>}
              {report.tags.map(tag => (
                <span key={tag} className="px-1.5 py-0.5 rounded-full border border-bg-border text-text-dim">{tag}</span>
              ))}
            </div>
          </div>
          {open ? <ChevronDown size={13} className="text-text-muted shrink-0" /> : <ChevronRight size={13} className="text-text-muted shrink-0" />}
        </button>
      </div>

      {/* Expanded detail */}
      {open && (
        <div className="border-t border-bg-border px-4 py-4 space-y-4">
          {/* Addresses */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-[10px] text-text-muted mb-1">{t('tools:victimReport.report.scammerAddr')}</div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[11px] text-red-400 break-all">{report.scammer_address}</span>
                <button onClick={() => navigator.clipboard.writeText(report.scammer_address)}>
                  <Copy size={10} className="text-text-muted hover:text-neon-cyan shrink-0" />
                </button>
              </div>
            </div>
            {report.victim_address && (
              <div>
                <div className="text-[10px] text-text-muted mb-1">{t('tools:victimReport.report.victimAddr')}</div>
                <span className="font-mono text-[11px] text-text-secondary break-all">{report.victim_address}</span>
              </div>
            )}
          </div>

          {/* Description */}
          {report.description && (
            <div>
              <div className="text-[10px] text-text-muted mb-1">{t('tools:victimReport.report.description')}</div>
              <p className="text-[11px] text-text-secondary leading-relaxed">{report.description}</p>
            </div>
          )}

          {/* TX hashes */}
          {report.tx_hashes.length > 0 && (
            <div>
              <div className="text-[10px] text-text-muted mb-1.5">{t('tools:victimReport.report.txHashes')}</div>
              <div className="space-y-1">
                {report.tx_hashes.map((h, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-neon-cyan truncate">{h}</span>
                    <button onClick={() => navigator.clipboard.writeText(h)}>
                      <Copy size={9} className="text-text-muted hover:text-neon-cyan shrink-0" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Analyst notes */}
          {report.analyst_notes && (
            <div className="bg-bg-primary rounded-lg border border-bg-border px-3 py-2.5">
              <div className="text-[10px] text-text-muted mb-1">{t('tools:victimReport.report.analystNotes')}</div>
              <p className="text-[11px] text-text-secondary">{report.analyst_notes}</p>
            </div>
          )}

          {/* Status + actions */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] text-text-muted">{t('tools:victimReport.report.statusLabel')}</span>
            <select
              value={report.status}
              disabled={updatingStatus}
              onChange={e => changeStatus(e.target.value)}
              className="input text-[10px] py-0.5 px-2 h-auto"
            >
              {Object.entries(STATUS_META).map(([k, v]) => (
                <option key={k} value={k}>{t(v.key)}</option>
              ))}
            </select>
            <button
              onClick={handleDelete}
              className="ml-auto text-[10px] text-red-500 hover:text-red-400 flex items-center gap-1 transition-colors"
            >
              <Trash2 size={10} /> {t('tools:victimReport.report.delete')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Cluster card ──────────────────────────────────────────────────────────────

function ClusterCard({
  cluster,
  scamTypes,
  onFilterAddress,
}: {
  cluster: ScamCluster
  scamTypes: ScamTypeInfo[]
  onFilterAddress: (addr: string) => void
}) {
  const [open, setOpen] = useState(false)
  const { t } = useTranslation()
  return (
    <div className="rounded-xl border border-red-700/20 bg-red-900/5 overflow-hidden">
      <button
        className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-red-900/8 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="font-mono text-[11px] text-red-400 font-semibold">{short(cluster.scammer_address, 10)}</span>
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-red-900/30 border border-red-700/30 text-red-400">
              {t('tools:victimReport.cluster.victims', { count: cluster.victim_count })}
            </span>
            {cluster.scam_types.map(t => {
              const meta = scamTypes.find(x => x.id === t)
              return meta ? <SevBadge key={t} severity={meta.severity} /> : null
            })}
          </div>
          <div className="flex items-center gap-3 text-[10px] text-text-muted flex-wrap">
            <span className="text-red-400 font-bold">{fmtUsd(cluster.total_damage_usd)}</span>
            {cluster.chains.map(c => <span key={c} className="text-text-dim">{c}</span>)}
            {cluster.first_incident && <span>{cluster.first_incident} → {cluster.last_incident || t('tools:victimReport.intel.ongoing')}</span>}
          </div>
        </div>
        {open ? <ChevronDown size={13} className="text-text-muted shrink-0" /> : <ChevronRight size={13} className="text-text-muted shrink-0" />}
      </button>
      {open && (
        <div className="border-t border-red-700/10 px-4 py-3 space-y-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-red-400 flex-1 break-all">{cluster.scammer_address}</span>
            <button onClick={() => navigator.clipboard.writeText(cluster.scammer_address)}>
              <Copy size={10} className="text-text-muted hover:text-neon-cyan shrink-0" />
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {cluster.scam_types.map(t => {
              const meta = scamTypes.find(x => x.id === t)
              return (
                <span key={t} className="text-[10px] text-text-secondary">
                  {meta?.label || t}
                </span>
              )
            })}
          </div>
          <button
            onClick={() => onFilterAddress(cluster.scammer_address)}
            className="text-[10px] text-neon-cyan hover:text-neon-cyan/80 flex items-center gap-1 transition-colors"
          >
            <Filter size={10} /> {t('tools:victimReport.cluster.filterReports')}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Stats header ──────────────────────────────────────────────────────────────

function StatsHeader({ summary }: { summary: ScamIntelSummary | null }) {
  const { t } = useTranslation()
  if (!summary) return null
  const stats = [
    { label: t('tools:victimReport.stats.totalReports'),    value: summary.total_reports.toLocaleString(),       icon: UserX,        color: 'text-red-400' },
    { label: t('tools:victimReport.stats.uniqueScammers'),  value: summary.unique_scammers.toLocaleString(),     icon: Users,        color: 'text-orange-400' },
    { label: t('tools:victimReport.stats.totalDamage'),     value: fmtUsd(summary.total_damage_usd),             icon: TrendingDown, color: 'text-red-400' },
    { label: t('tools:victimReport.stats.chainsAffected'),  value: summary.chains_affected.toLocaleString(),     icon: Globe,        color: 'text-red-400' },
  ]
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {stats.map(s => {
        const Icon = s.icon
        return (
          <div key={s.label} className="rounded-xl border border-bg-border bg-bg-elevated px-4 py-3">
            <div className="flex items-center gap-2 mb-1">
              <Icon size={12} className={s.color} />
              <span className="text-[10px] text-text-muted">{s.label}</span>
            </div>
            <div className={`text-lg font-bold font-mono ${s.color}`}>{s.value}</div>
          </div>
        )
      })}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function VictimReportPage() {
  const { t } = useTranslation()
  const [tab, setTab]                 = useTabParam<'reports' | 'intel'>('reports', ['reports', 'intel'])
  const [reports, setReports]         = useState<VictimReport[]>([])
  const [total, setTotal]             = useState(0)
  const [clusters, setClusters]       = useState<ScamCluster[]>([])
  const [summary, setSummary]         = useState<ScamIntelSummary | null>(null)
  const [scamTypes, setScamTypes]     = useState<ScamTypeInfo[]>([])
  const [showForm, setShowForm]       = useState(false)
  const [loading, setLoading]         = useState(false)
  const [selected, setSelected]       = useState<Set<string>>(new Set())
  const [exporting, setExporting]     = useState(false)

  // Filters
  const [filterAddr, setFilterAddr]   = useState('')
  const [filterType, setFilterType]   = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterChain, setFilterChain] = useState('')

  const loadReports = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listVictimReports({
        scammer_address: filterAddr,
        scam_type:       filterType,
        status:          filterStatus,
        chain:           filterChain,
        limit:           100,
      })
      setReports(res.reports)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [filterAddr, filterType, filterStatus, filterChain])

  const loadIntel = useCallback(async () => {
    const [sumRes, clRes] = await Promise.all([
      scamIntelSummary(),
      scamClusters({ limit: 50 }),
    ])
    setSummary(sumRes)
    setClusters(clRes.clusters)
  }, [])

  useEffect(() => {
    listScamTypes().then(r => setScamTypes(r.scam_types))
    loadReports()
    loadIntel()
  }, [])

  useEffect(() => { loadReports() }, [loadReports])

  function toggleSelect(id: string, checked: boolean) {
    setSelected(prev => {
      const next = new Set(prev)
      if (checked) next.add(id); else next.delete(id)
      return next
    })
  }

  function toggleSelectAll() {
    if (selected.size === reports.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(reports.map(r => r.id)))
    }
  }

  async function handleExport() {
    if (selected.size === 0) return
    setExporting(true)
    try {
      const { bundle } = await exportReportBundle([...selected])
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `victim-report-bundle-${Date.now()}.json`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setExporting(false)
    }
  }

  function onSubmitted(r: VictimReport) {
    setShowForm(false)
    setReports(prev => [r, ...prev])
    setTotal(t => t + 1)
    loadIntel()
  }

  function onUpdate(updated: VictimReport) {
    setReports(prev => prev.map(r => r.id === updated.id ? updated : r))
  }

  function onDelete(id: string) {
    setReports(prev => prev.filter(r => r.id !== id))
    setTotal(t => t - 1)
    setSelected(prev => { const n = new Set(prev); n.delete(id); return n })
    loadIntel()
  }

  const TABS = [
    { id: 'reports', label: t('tools:victimReport.tabs.reports'), icon: UserX,    count: total },
    { id: 'intel',   label: t('tools:victimReport.tabs.intel'),   icon: Shield, count: clusters.length },
  ] as const

  return (
    <div className="noscroll-page flex flex-col h-full overflow-hidden">

      {/* ── Header ── */}
      <div className="border-b border-bg-border px-6 py-4 space-y-4 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
              style={{ background: 'linear-gradient(135deg, rgba(239,68,68,0.2), rgba(249,115,22,0.1))', border: '1px solid rgba(239,68,68,0.4)' }}>
              <UserX size={18} style={{ color: '#ef4444' }} />
            </div>
            <div>
              <h1 className="text-sm font-bold text-text-primary">{t('tools:victimReport.title')}</h1>
              <p className="text-[10px] text-text-muted">{t('tools:victimReport.subtitle')}</p>
            </div>
          </div>
          <button
            onClick={() => setShowForm(true)}
            className="btn-primary text-xs px-4 py-2 flex items-center gap-2"
          >
            <Plus size={13} /> {t('tools:victimReport.submitReport')}
          </button>
        </div>

        <StatsHeader summary={summary} />

        {/* Tabs */}
        <div className="flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <ResultTabs active={tab} onChange={setTab} tabs={[...TABS]} />
          </div>
          <button
            onClick={() => { loadReports(); loadIntel() }}
            className="text-text-muted hover:text-neon-cyan transition-colors shrink-0"
            title={t('common:actions.refresh')}
          >
            <RefreshCw size={13} />
          </button>
        </div>
      </div>

      {/* ── Reports tab ── */}
      {tab === 'reports' && (
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {/* Filter bar */}
          <CinematicStage variant="victim" icon={UserX} collapsed={false}>
          <div className="flex items-center gap-2 flex-wrap">
            <Filter size={12} className="text-text-muted shrink-0" />
            <input
              className="input text-xs py-1.5 px-2.5 w-52 font-mono"
              placeholder={t('tools:victimReport.filters.byAddrPh')}
              value={filterAddr}
              onChange={e => setFilterAddr(e.target.value)}
            />
            <select className="input text-xs py-1.5 px-2.5" value={filterType} onChange={e => setFilterType(e.target.value)}>
              <option value="">{t('tools:victimReport.filters.allTypes')}</option>
              {scamTypes.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <select className="input text-xs py-1.5 px-2.5" value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
              <option value="">{t('tools:victimReport.filters.allStatuses')}</option>
              {Object.entries(STATUS_META).map(([k, v]) => <option key={k} value={k}>{t(v.key)}</option>)}
            </select>
            <select className="input text-xs py-1.5 px-2.5" value={filterChain} onChange={e => setFilterChain(e.target.value)}>
              <option value="">{t('tools:victimReport.filters.allChains')}</option>
              {CHAINS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            {(filterAddr || filterType || filterStatus || filterChain) && (
              <button onClick={() => { setFilterAddr(''); setFilterType(''); setFilterStatus(''); setFilterChain('') }}
                className="text-[10px] text-text-muted hover:text-red-400 flex items-center gap-1">
                <X size={10} /> {t('tools:victimReport.filters.clear')}
              </button>
            )}

            {/* Bulk actions */}
            {reports.length > 0 && (
              <div className="ml-auto flex items-center gap-2">
                <button onClick={toggleSelectAll} className="text-[10px] text-text-muted hover:text-neon-cyan transition-colors">
                  {selected.size === reports.length ? t('tools:victimReport.filters.deselectAll') : t('tools:victimReport.filters.selectAll', { count: reports.length })}
                </button>
                {selected.size > 0 && (
                  <button
                    onClick={handleExport}
                    disabled={exporting}
                    className="text-[10px] text-neon-cyan border border-neon-cyan/30 px-2.5 py-1 rounded-lg hover:bg-neon-cyan/5 flex items-center gap-1 transition-colors"
                  >
                    <FileDown size={10} /> {t('tools:victimReport.filters.exportSelected', { count: selected.size })}
                  </button>
                )}
              </div>
            )}
          </div>
          </CinematicStage>

          {/* Report count */}
          <div className="text-[10px] text-text-muted">
            {loading ? t('tools:victimReport.filters.loading') : t('tools:victimReport.filters.reportCount', { count: total })}
          </div>

          {/* Report list */}
          {reports.length === 0 && !loading ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <UserX size={32} className="text-text-muted mb-3 opacity-40" />
              <p className="text-sm text-text-secondary font-semibold mb-1">{t('tools:victimReport.empty.noReports')}</p>
              <p className="text-[11px] text-text-muted max-w-xs">
                {(filterAddr || filterType || filterStatus) ? t('tools:victimReport.empty.tryFilters') : t('tools:victimReport.empty.submitFirst')}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {reports.map(r => (
                <ReportCard
                  key={r.id}
                  report={r}
                  scamTypes={scamTypes}
                  selected={selected.has(r.id)}
                  onSelect={toggleSelect}
                  onUpdate={onUpdate}
                  onDelete={onDelete}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Intelligence tab ── */}
      {tab === 'intel' && (
        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Left: cluster list */}
            <div className="lg:col-span-2 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold text-text-secondary">{t('tools:victimReport.intel.clusters')}</h3>
                <span className="text-[10px] text-text-muted">{t('tools:victimReport.intel.clustersByDamage', { count: clusters.length })}</span>
              </div>
              {clusters.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <Shield size={28} className="text-text-muted mb-3 opacity-40" />
                  <p className="text-[11px] text-text-muted">{t('tools:victimReport.intel.noClusters')}</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {clusters.map(c => (
                    <ClusterCard
                      key={c.scammer_address}
                      cluster={c}
                      scamTypes={scamTypes}
                      onFilterAddress={addr => {
                        setFilterAddr(addr)
                        setTab('reports')
                      }}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Right: breakdowns */}
            <div className="space-y-4">
              {/* By scam type */}
              {summary && summary.by_scam_type.length > 0 && (
                <div className="rounded-xl border border-bg-border bg-bg-elevated p-4 space-y-3">
                  <h4 className="text-xs font-semibold text-text-secondary flex items-center gap-2">
                    <Hash size={12} className="text-text-muted" /> {t('tools:victimReport.intel.byScamType')}
                  </h4>
                  <div className="space-y-2">
                    {summary.by_scam_type.map(t => {
                      const meta = scamTypes.find(x => x.id === t.scam_type)
                      const maxDmg = Math.max(...summary.by_scam_type.map(x => x.damage || 0), 1)
                      const pct = Math.round(((t.damage || 0) / maxDmg) * 100)
                      return (
                        <div key={t.scam_type} className="space-y-1">
                          <div className="flex items-center justify-between text-[10px]">
                            <span className="text-text-secondary">{meta?.label || t.scam_type}</span>
                            <span className="text-text-muted">{t.count} · {fmtUsd(t.damage || 0)}</span>
                          </div>
                          <div className="h-1 rounded-full bg-bg-primary">
                            <div
                              className="h-1 rounded-full bg-red-600"
                              style={{ width: `${pct}%`, opacity: 0.7 }}
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* By status */}
              {summary && summary.by_status.length > 0 && (
                <div className="rounded-xl border border-bg-border bg-bg-elevated p-4 space-y-3">
                  <h4 className="text-xs font-semibold text-text-secondary flex items-center gap-2">
                    <CheckCircle size={12} className="text-text-muted" /> {t('tools:victimReport.intel.byStatus')}
                  </h4>
                  <div className="space-y-1.5">
                    {summary.by_status.map(s => {
                      const m = STATUS_META[s.status]
                      if (!m) return null
                      return (
                        <div key={s.status} className="flex items-center justify-between">
                          <StatusBadge status={s.status} />
                          <span className="text-[11px] font-semibold text-text-primary">{s.count}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Top scammers */}
              {summary && summary.top_scammers.length > 0 && (
                <div className="rounded-xl border border-red-700/20 bg-red-900/5 p-4 space-y-3">
                  <h4 className="text-xs font-semibold text-red-400 flex items-center gap-2">
                    <TrendingDown size={12} /> {t('tools:victimReport.intel.topScammers')}
                  </h4>
                  <div className="space-y-2">
                    {summary.top_scammers.slice(0, 5).map((s, i) => (
                      <div key={s.scammer_address} className="flex items-start gap-2">
                        <span className="text-[10px] text-text-dim w-4 shrink-0 mt-0.5">#{i + 1}</span>
                        <div className="flex-1 min-w-0">
                          <button
                            onClick={() => { setFilterAddr(s.scammer_address); setTab('reports') }}
                            className="font-mono text-[10px] text-red-400 hover:text-red-300 transition-colors truncate block w-full text-left"
                          >
                            {short(s.scammer_address)}
                          </button>
                          <div className="text-[9px] text-text-muted">{t('tools:victimReport.cluster.victims', { count: s.victims })} · {fmtUsd(s.damage)}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent activity */}
              {summary && summary.recent_reports.length > 0 && (
                <div className="rounded-xl border border-bg-border bg-bg-elevated p-4 space-y-3">
                  <h4 className="text-xs font-semibold text-text-secondary flex items-center gap-2">
                    <Clock size={12} className="text-text-muted" /> {t('tools:victimReport.intel.recentReports')}
                  </h4>
                  <div className="space-y-2">
                    {summary.recent_reports.map(r => {
                      const meta = scamTypes.find(t => t.id === r.scam_type)
                      return (
                        <div key={r.id} className="text-[10px] space-y-0.5">
                          <div className="flex items-center gap-2">
                            {r.scam_type && <SevBadge severity={meta?.severity || 'medium'} />}
                            <span className="text-text-muted">{meta?.label || r.scam_type}</span>
                            {r.amount_usd && r.amount_usd > 0 && (
                              <span className="text-red-400 font-semibold ml-auto">{fmtUsd(r.amount_usd)}</span>
                            )}
                          </div>
                          <div className="font-mono text-text-dim">{r.scammer_address ? short(r.scammer_address) : '-'}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Submit form modal */}
      {showForm && (
        <SubmitForm
          scamTypes={scamTypes}
          onSubmitted={onSubmitted}
          onClose={() => setShowForm(false)}
        />
      )}
    </div>
  )
}
