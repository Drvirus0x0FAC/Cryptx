/**
 * ReportStudio - the CrypTX Mega Report Generator.
 * Pick a case + an audience-tailored report type, generate an AI-written (with
 * deterministic fallback) CrypTX-branded report, preview it, print it, or download it.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  FileText, Shield, Briefcase, Cpu, Zap, Scale, Download, Printer, ExternalLink,
  Loader2, AlertTriangle, RefreshCw, FolderOpen,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { listCases, getReportTypes, generateReport } from '../api/client'
import type { Case, ReportType, GeneratedReport } from '../types'
import ExportButtons from '../components/ExportButtons'
import CinematicStage from '../components/CinematicStage'

const ICONS: Record<string, LucideIcon> = {
  scale: Scale, shield: Shield, briefcase: Briefcase, cpu: Cpu, bolt: Zap,
}

export default function ReportStudio() {
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const paramCase = searchParams.get('case') || ''
  const paramType = searchParams.get('type') || ''
  const paramAuto = searchParams.get('auto') === '1'

  const [cases, setCases] = useState<Case[]>([])
  const [types, setTypes] = useState<ReportType[]>([])
  const [caseId, setCaseId] = useState('')
  const [typeId, setTypeId] = useState('')
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState<GeneratedReport | null>(null)
  const [error, setError] = useState('')
  const autoDone = useRef(false)

  useEffect(() => {
    listCases().then(setCases).catch(() => setCases([]))
    getReportTypes().then(r => {
      setTypes(r.types)
      setTypeId(paramType || (r.types[0]?.id ?? ''))
    }).catch(() => setTypes([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!caseId && cases.length) setCaseId(paramCase || cases[0].id)
  }, [cases, caseId, paramCase])

  // Auto-generate once when arriving from a case with ?auto=1.
  useEffect(() => {
    if (paramAuto && !autoDone.current && caseId && typeId && types.length) {
      autoDone.current = true
      void onGenerate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramAuto, caseId, typeId, types])

  const activeType = useMemo(() => types.find(t => t.id === typeId), [types, typeId])
  const activeCase = useMemo(() => cases.find(c => c.id === caseId), [cases, caseId])

  async function onGenerate() {
    if (!caseId || !typeId) return
    setLoading(true); setError(''); setReport(null)
    try {
      const res = await generateReport({ case_id: caseId, report_type: typeId, include_ai: true })
      setReport(res)
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || t('tools:reportStudio.errors.failed'))
    } finally {
      setLoading(false)
    }
  }

  function download() {
    if (!report) return
    const blob = new Blob([report.html], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `CrypTX_${report.report_type}_${(activeCase?.name || 'case').replace(/[^a-z0-9]+/gi, '_')}.html`
    a.click()
    URL.revokeObjectURL(url)
  }

  function printReport() {
    const frame = document.getElementById('report-frame') as HTMLIFrameElement | null
    frame?.contentWindow?.focus()
    frame?.contentWindow?.print()
  }

  function openTab() {
    if (!report) return
    const w = window.open('', '_blank')
    w?.document.write(report.html)
    w?.document.close()
  }

  return (
    <div className="noscroll-page page-enter max-w-[1500px] mx-auto px-5 py-6">
      {/* Header */}
      <div className="flex items-start gap-3 mb-5">
        <div className="p-2.5 rounded-xl bg-neon-cyan/10 border border-neon-cyan/30">
          <FileText className="text-neon-cyan" size={22} />
        </div>
        <div>
          <h1 className="text-xl font-display font-bold text-text-bright">{t('tools:reportStudio.title')}</h1>
          <p className="text-[13px] text-text-muted mt-0.5">
            {t('tools:reportStudio.subtitle')}
          </p>
        </div>
      </div>

      <div className="noscroll-grow grid grid-cols-1 lg:grid-cols-[360px_1fr] gap-5">
        {/* Controls */}
        <CinematicStage variant="reports" icon={FileText} title={t('tools:reportStudio.title')} subtitle={t('tools:reportStudio.subtitle')} collapsed={false}>
        <div className="space-y-4">
          {/* Case picker */}
          <div className="bg-bg-card border border-border rounded-xl p-4">
            <label className="text-[11px] uppercase tracking-wider text-text-muted font-semibold flex items-center gap-1.5 mb-2">
              <FolderOpen size={12} /> {t('tools:reportStudio.caseLabel')}
            </label>
            <select
              value={caseId}
              onChange={e => setCaseId(e.target.value)}
              className="w-full bg-bg-surface border border-border rounded-lg px-3 py-2 text-[13px] text-text-primary focus:border-neon-cyan/40 focus:outline-none"
            >
              {cases.length === 0 && <option value="">{t('tools:reportStudio.noCases')}</option>}
              {cases.map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            {activeCase && (
              <p className="text-[11px] text-text-dim mt-2">
                {t('tools:reportStudio.caseMeta', { count: activeCase.address_count ?? 0, status: activeCase.status })}
              </p>
            )}
          </div>

          {/* Report type cards */}
          <div className="bg-bg-card border border-border rounded-xl p-4">
            <label className="text-[11px] uppercase tracking-wider text-text-muted font-semibold mb-2 block">
              {t('tools:reportStudio.reportTypeLabel')}
            </label>
            <div className="space-y-2">
              {types.map(t => {
                const Icon = ICONS[t.icon] || FileText
                const active = t.id === typeId
                return (
                  <button
                    key={t.id}
                    onClick={() => setTypeId(t.id)}
                    className={`w-full text-left rounded-lg border p-3 transition flex gap-3 items-start
                      ${active ? 'border-transparent' : 'border-border hover:border-border bg-bg-surface'}`}
                    style={active ? { background: `${t.accent}18`, borderColor: `${t.accent}66` } : undefined}
                  >
                    <span className="mt-0.5 p-1.5 rounded-md" style={{ background: `${t.accent}1f`, color: t.accent }}>
                      <Icon size={16} />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-bold text-text-bright">{t.name}</span>
                      <span className="block text-[11px] text-text-muted leading-snug mt-0.5">{t.blurb}</span>
                      <span className="inline-block mt-1.5 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                        style={{ color: t.accent, background: `${t.accent}18`, border: `1px solid ${t.accent}44` }}>
                        {t.classification}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Generate */}
          <div className="bg-bg-card border border-border rounded-xl p-4 space-y-3">
            <button
              onClick={onGenerate}
              disabled={loading || !caseId || !typeId}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-neon-cyan/15 border border-neon-cyan/40 text-neon-cyan text-[13px] font-bold hover:bg-neon-cyan/25 transition disabled:opacity-40"
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <FileText size={15} />}
              {loading ? t('tools:reportStudio.generating') : t('tools:reportStudio.generate')}
            </button>
            {error && (
              <div className="flex items-start gap-2 text-[12px] text-neon-red bg-neon-red/10 border border-neon-red/30 rounded-lg px-3 py-2">
                <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" /> {error}
              </div>
            )}
          </div>
        </div>
        </CinematicStage>

        {/* Preview */}
        <div className="bg-bg-card border border-border rounded-xl overflow-hidden flex flex-col min-h-[70vh]">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border">
            <span className="text-[12px] font-semibold text-text-secondary">
              {report ? (activeType?.name || t('tools:reportStudio.preview.title')) : t('tools:reportStudio.preview.title')}
            </span>
            {report && (
              <span className="text-[10px] text-text-dim">{report.generated_at}</span>
            )}
            <div className="ml-auto flex items-center gap-1.5">
              <button onClick={onGenerate} disabled={loading || !report} title={t('tools:reportStudio.preview.regenerate')}
                className="topbar-icon-btn disabled:opacity-30"><RefreshCw size={14} /></button>
              <button onClick={printReport} disabled={!report} title={t('tools:reportStudio.preview.print')}
                className="topbar-icon-btn disabled:opacity-30"><Printer size={14} /></button>
              <button onClick={openTab} disabled={!report} title={t('tools:reportStudio.preview.openTab')}
                className="topbar-icon-btn disabled:opacity-30"><ExternalLink size={14} /></button>
              <button onClick={download} disabled={!report} title={t('tools:reportStudio.preview.download')}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-neon-green/10 border border-neon-green/30 text-neon-green text-[12px] font-semibold hover:bg-neon-green/20 transition disabled:opacity-30">
                <Download size={13} /> {t('tools:reportStudio.preview.downloadBtn')}
              </button>
            </div>
          </div>

          {/* V2: Native format exports (PDF / DOCX / FinCEN XML / STIX / MISP) */}
          {report && (
            <div className="px-4 py-2 border-b border-white/5 flex items-center gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-text-muted mr-1">{t('tools:reportStudio.preview.exportAs')}</span>
              <ExportButtons
                htmlContent={report.html}
                caseId={caseId}
                title={`CrypTX_${report.report_type}_${(activeCase?.name || 'case').replace(/[^a-z0-9]+/gi, '_')}`}
              />
            </div>
          )}

          <div className="flex-1 bg-[rgb(var(--bg-primary))]">
            {loading && (
              <div className="h-full flex items-center justify-center gap-2 text-text-muted">
                <Loader2 size={18} className="animate-spin" /> {t('tools:reportStudio.preview.building')}
              </div>
            )}
            {!loading && !report && (
              <div className="h-full flex flex-col items-center justify-center gap-2 text-text-dim text-[13px]">
                <FileText size={30} className="opacity-40" />
                {t('tools:reportStudio.preview.empty')}
              </div>
            )}
            {!loading && report && (
              <iframe
                id="report-frame"
                title="report-preview"
                srcDoc={report.html}
                sandbox="allow-same-origin"
                className="w-full h-full min-h-[70vh] border-0"
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
