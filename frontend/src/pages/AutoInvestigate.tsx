import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle, Bot, CheckCircle2, Download, FileText, Loader2,
  Radar, Search, ShieldAlert, Target, Zap,
} from 'lucide-react'
import { startAutoInvestigation, getAutoJob } from '../api/client'
import type { AutoJob } from '../api/client'
import CinematicStage from '../components/CinematicStage'

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
      <p className="text-[10px] text-text-muted uppercase tracking-widest">{label}</p>
      <p className="text-lg font-bold text-text-primary font-mono">{value}</p>
      {sub && <p className="text-[11px] text-text-muted truncate">{sub}</p>}
    </div>
  )
}

export default function AutoInvestigate() {
  const { t } = useTranslation()
  const { addr } = useParams<{ addr: string }>()
  const [address, setAddress] = useState(addr ?? '')
  const [caseId, setCaseId] = useState('')
  const [job, setJob] = useState<AutoJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const pollRef = useRef<number | null>(null)

  async function run(target?: string) {
    const a = (target ?? address).trim()
    if (!a || running) return
    setRunning(true)
    setError(null)
    setJob(null)
    try {
      const { job_id } = await startAutoInvestigation({ address: a, case_id: caseId.trim() || undefined })
      const poll = async () => {
        try {
          const j = await getAutoJob(job_id)
          setJob(j)
          if (j.status === 'running') {
            pollRef.current = window.setTimeout(poll, 1500)
          } else {
            setRunning(false)
            if (j.status === 'failed') setError(j.error || t('tools:autoInvestigate.failed'))
          }
        } catch (e) {
          setRunning(false)
          setError(e instanceof Error ? e.message : String(e))
        }
      }
      poll()
    } catch (e) {
      setRunning(false)
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    if (addr) { setAddress(addr); run(addr) }
    return () => { if (pollRef.current) window.clearTimeout(pollRef.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addr])

  function downloadReport(kind: 'md' | 'html') {
    if (!job?.result) return
    const content = kind === 'md' ? job.result.report_markdown : job.result.report_html
    const blob = new Blob([content], { type: kind === 'md' ? 'text/markdown' : 'text/html' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `auto-investigation-${job.address.slice(0, 10)}.${kind === 'md' ? 'md' : 'html'}`
    a.click()
    URL.revokeObjectURL(url)
  }

  const result = job?.result
  const partial = job?.partial ?? {}

  return (
    <div className="noscroll-page p-6 max-w-6xl mx-auto space-y-5">
      <CinematicStage
        variant="auto"
        icon={Radar}
        kicker={t('tools:autoInvestigate.title')}
        title={t('tools:autoInvestigate.title')}
        subtitle={t('tools:autoInvestigate.subtitle')}
        collapsed={!!job}
      >
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_220px_auto] gap-3 items-end">
        <div>
          <label className="block text-[10px] text-text-muted uppercase tracking-widest mb-1">{t('tools:autoInvestigate.inputLabel')}</label>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input className="input pl-9" placeholder={t('tools:autoInvestigate.inputPlaceholder')}
              value={address} onChange={e => setAddress(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') run() }} />
          </div>
        </div>
        <div>
          <label className="block text-[10px] text-text-muted uppercase tracking-widest mb-1">{t('tools:autoInvestigate.caseLabel')}</label>
          <input className="input font-mono text-xs" placeholder={t('tools:autoInvestigate.casePlaceholder')}
            value={caseId} onChange={e => setCaseId(e.target.value)} />
        </div>
        <button className="btn-primary h-9" disabled={running || !address.trim()} onClick={() => run()}>
          {running ? <Loader2 size={14} className="animate-spin" /> : <Radar size={14} />}
          {t('tools:autoInvestigate.run')}
        </button>
        </div>
      </CinematicStage>

      {/* Result / job content — grows & scrolls internally */}
      <div className="noscroll-grow space-y-5">
      {error && (
        <div className="card border-risk-mixer/50 flex items-start gap-3">
          <AlertTriangle className="text-risk-mixer shrink-0 mt-0.5" size={18} />
          <div>
            <p className="text-sm font-semibold text-risk-mixer">{t('tools:autoInvestigate.failed')}</p>
            <p className="text-xs text-text-muted mt-1">{error}</p>
          </div>
        </div>
      )}

      {/* Progress */}
      {job && job.status === 'running' && (
        <div className="card space-y-4">
          <div className="flex items-center gap-4">
            <Loader2 className="animate-spin text-neon-green shrink-0" size={30} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm text-text-primary font-semibold">{job.stage}</p>
                <span className="font-mono text-xs text-neon-green">{job.progress}%</span>
              </div>
              <p className="text-xs text-text-muted mt-1">{job.detail}</p>
              <div className="h-2 rounded-full bg-bg-secondary border border-border mt-3 overflow-hidden">
                <div className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${job.progress}%`, background: 'linear-gradient(90deg, #00ff88, #ff5a6e)' }} />
              </div>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-2">
            {job.stages.map(stage => {
              const idx = job.stages.indexOf(stage)
              const activeIdx = job.stages.indexOf(job.stage)
              const done = activeIdx > idx || job.progress >= 100
              const current = stage === job.stage
              return (
                <div key={stage} className="flex items-center gap-2 border border-border rounded-lg px-3 py-2 bg-bg-secondary/50"
                  style={{ borderColor: current ? 'rgba(0,255,136,0.5)' : undefined }}>
                  {done ? <CheckCircle2 size={13} className="text-neon-green" /> : current ? <Loader2 size={13} className="animate-spin text-neon-green" /> : <span className="w-[13px] h-[13px] rounded-full border border-text-muted/40" />}
                  <span className={current ? 'text-neon-green text-xs' : 'text-text-secondary text-xs'}>{stage}</span>
                </div>
              )
            })}
          </div>
          {/* Live partials */}
          {Object.keys(partial).length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {partial.risk && <Stat label={t('tools:autoInvestigate.stats.risk')} value={String(partial.risk.score ?? '…')} sub={String(partial.risk.level ?? '')} />}
              {partial.forensics && <Stat label={t('tools:autoInvestigate.stats.role')} value={String(partial.forensics.role ?? '…')} sub={t('tools:autoInvestigate.stats.motifs', { count: partial.forensics.motifs ?? 0 })} />}
              {partial.threat_intel && <Stat label={t('tools:autoInvestigate.stats.threat')} value={String(partial.threat_intel.threat_level ?? '…')} sub={String(partial.threat_intel.top_typology ?? '')} />}
              {partial.intel_summary && <Stat label={t('tools:autoInvestigate.stats.txs')} value={String(partial.intel_summary.tx_count ?? '…')} sub={String(partial.intel_summary.chain ?? '')} />}
            </div>
          )}
        </div>
      )}

      {/* Result */}
      {result && job?.status === 'completed' && (
        <div className="space-y-4">
          <div className="card">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <p className="card-title flex items-center gap-2"><Bot size={13} /> {t('tools:autoInvestigate.package.title')}</p>
                <p className="font-mono text-sm text-text-primary break-all">{result.address}</p>
                {result.custody?.chain_hash && (
                  <p className="text-xs text-neon-green mt-1">
                    {t('tools:autoInvestigate.package.custody')} <span className="font-mono">{result.custody.chain_hash.slice(0, 24)}…</span>
                  </p>
                )}
              </div>
              <div className="flex gap-2">
                <button className="btn-secondary text-xs" onClick={() => downloadReport('html')}>
                  <FileText size={13} /> {t('tools:autoInvestigate.package.reportHtml')}
                </button>
                <button className="btn-ghost text-xs" onClick={() => downloadReport('md')}>
                  <Download size={13} /> {t('tools:autoInvestigate.package.reportMd')}
                </button>
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
              <Stat label={t('tools:autoInvestigate.stats.risk')} value={`${result.risk?.score ?? '-'}/100`} sub={result.risk?.risk_level} />
              <Stat label={t('tools:autoInvestigate.stats.threat')} value={String((result.threat_intel as { threat_level?: string })?.threat_level ?? '-')} />
              <Stat label={t('tools:autoInvestigate.stats.role')} value={String((result.forensics as { role?: { role?: string } })?.role?.role ?? '-').replace(/_/g, ' ')} />
              <Stat label={t('tools:autoInvestigate.stats.courtDefensible')} value={(result.attribution as { court_defensible?: boolean })?.court_defensible ? t('tools:autoInvestigate.stats.yes') : t('tools:autoInvestigate.stats.no')} sub={t('tools:autoInvestigate.stats.courtDefensibleSub')} />
            </div>
            <pre className="mt-4 whitespace-pre-wrap rounded-lg border border-border bg-bg-secondary/50 p-4 text-xs text-text-secondary">
              {result.report_markdown}
            </pre>
          </div>

          {/* Exit VASPs - where to serve legal process */}
          {(() => {
            const ev = result.exit_vasp as {
              exit_vasps?: Array<{ address: string; chain: string; vasp_name: string; vasp_type: string; jurisdiction: string; hop?: number; in_kyv_directory: boolean; legal_process: string }>
              cashout_indicators?: Array<{ type?: string; name?: string; description?: string; confidence?: number }>
              error?: string
            } | undefined
            if (!ev) return null
            return (
              <div className="card" style={{ borderColor: (ev.exit_vasps?.length ?? 0) > 0 ? 'rgba(34,197,120,0.4)' : undefined }}>
                <p className="card-title flex items-center gap-2"><Target size={13} /> {t('tools:autoInvestigate.exitVasp.title')}</p>
                {(ev.exit_vasps?.length ?? 0) === 0 ? (
                  <p className="text-xs text-text-muted">
                    {ev.error ? t('tools:autoInvestigate.exitVasp.unavailable', { error: ev.error }) : t('tools:autoInvestigate.exitVasp.none')}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {ev.exit_vasps!.map((v, i) => (
                      <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3">
                        <div className="flex items-center gap-2 flex-wrap text-xs">
                          <span className="font-bold text-text-primary">{v.vasp_name}</span>
                          <span className="px-1.5 py-0.5 rounded bg-bg-secondary text-[9px] uppercase">{v.vasp_type}</span>
                          <span className="text-text-muted text-[10px]">{v.jurisdiction}</span>
                          {v.hop != null && <span className="text-text-muted text-[10px]">{t('tools:autoInvestigate.exitVasp.hop', { n: v.hop })}</span>}
                          {v.in_kyv_directory && <span className="text-emerald-400 text-[9px]">{t('tools:autoInvestigate.exitVasp.kyvDirectory')}</span>}
                          <div className="flex-1" />
                          <Link to={`/intel/${encodeURIComponent(v.address)}`} className="text-neon-cyan text-[10px] hover:underline">{t('tools:autoInvestigate.exitVasp.inspect')}</Link>
                        </div>
                        <p className="font-mono text-[10px] text-text-secondary mt-1 break-all">{v.address}</p>
                        <p className="text-[11px] text-text-secondary mt-1">{v.legal_process}</p>
                      </div>
                    ))}
                  </div>
                )}
                {(ev.cashout_indicators?.length ?? 0) > 0 && (
                  <div className="mt-3 pt-2 border-t border-border">
                    <p className="text-[10px] uppercase tracking-widest text-text-muted mb-1">{t('tools:autoInvestigate.exitVasp.cashoutIndicators')}</p>
                    {ev.cashout_indicators!.slice(0, 5).map((c, i) => (
                      <p key={i} className="text-[11px] text-text-secondary">
                        • {c.name || c.type} {c.confidence != null && <span className="text-text-muted">({Math.round((c.confidence || 0) * 100)}%)</span>}
                        {c.description && <span className="text-text-muted"> - {c.description}</span>}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )
          })()}

          <div className="card">
            <p className="card-title flex items-center gap-2"><Target size={13} /> {t('tools:autoInvestigate.continue.title')}</p>
            <div className="flex flex-wrap gap-2">
              <Link to={`/intel/${encodeURIComponent(result.address)}`} className="btn-secondary text-xs"><ShieldAlert size={13} /> {t('tools:autoInvestigate.continue.addressIntel')}</Link>
              <Link to={`/nexus/${encodeURIComponent(result.address)}`} className="btn-secondary text-xs"><Zap size={13} /> {t('tools:autoInvestigate.continue.nexusGraph')}</Link>
              <Link to={`/holistic/${encodeURIComponent(result.address)}`} className="btn-secondary text-xs"><Radar size={13} /> {t('tools:autoInvestigate.continue.holisticTrace')}</Link>
              <Link to={`/forensics/${encodeURIComponent(result.address)}`} className="btn-ghost text-xs">{t('tools:autoInvestigate.continue.forensics')}</Link>
            </div>
          </div>
        </div>
      )}

      {!job && !error && (
        <div className="flex justify-center py-16">
          <div className="text-center space-y-2">
            <Radar className="mx-auto text-text-muted" size={44} />
            <p className="text-text-secondary">{t('tools:autoInvestigate.empty')}</p>
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
